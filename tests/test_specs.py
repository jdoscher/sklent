"""Specs and sheets (area S): spec card, BOM, views sheet, dimensions, contact sheet and
assembly steps, with a fake SolidCraft (the real thing runs on the render host only)."""

import io
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sklent import db, jobs, render, steps
from sklent.features import specs
from sklent.features.specs import assembly, bom, draw, meta, ortho, spec, views
from sklent.render import Output

H = {"Authorization": "Bearer test-token-0123456789"}
WEB = Path(__file__).resolve().parents[1] / "sklent" / "web"


# ---------------------------------------------------------------- a fake SolidCraft

def _gradient(w: int, h: int) -> np.ndarray:
    """SolidCraft's light theme background: a vertical blue-grey gradient."""
    top, bottom = np.array([240, 243, 247]), np.array([203, 210, 221])
    t = np.linspace(0, 1, h)[:, None, None]
    return np.broadcast_to(top * (1 - t) + bottom * t, (h, w, 3)).astype(np.uint8)


class FakeSC:
    """Draws the world box's orthographic projection (from the camera maths) as a grey block
    with a dark outline on the gradient, so scale and cut-outs can be checked exactly."""

    def __init__(self, bodies=None, comps=None, bom_rows=None, world=None, materials=None):
        self.bodies_ = bodies or [{"name": "Body1", "visible": True, "closed": True, "volume_mm3": 1000.0,
                                   "area_mm2": 600.0,
                                   "bbox": {"min": [-47.5, -33.0, 0.0], "max": [47.5, 33.0, 32.0]}}]
        self.world = world  # measure's bodies; defaults to bodies_
        self.comps = comps or [{"id": 0, "name": "root", "parent": None, "bodies": ["Body1"], "children": []}]
        self.bom_rows = bom_rows or []
        self.materials = materials or {}
        self.calls: list = []
        self.shots: list[tuple] = []
        self.hidden_paths: set = set()
        self.hidden_items: set = set()

    # tools
    def tool(self, name, **args):
        self.calls.append((name, args))
        if name == "inspect_design":
            return {"params": [{"name": "wall", "value": 2.0, "unit": "mm", "expression": "2 mm", "model": False},
                               {"name": "d1", "value": 95.0, "unit": "mm", "expression": "95 mm", "model": True}],
                    "units": "mm"}
        if name == "version":
            return {"version": "0.44.1"}
        if name == "measure":
            rows = self.world if self.world is not None else self.bodies_
            if args.get("names_only"):
                return {"bodies": [{"name": b["name"], "definition": b.get("definition", b["name"])} for b in rows]}
            out = []
            for b in rows:
                m = self.materials.get(b.get("definition", b["name"]), "Default")
                dens = {"Default": 1.29, "ABS Plastic": 1.06}[m]
                out.append({**b, "material": m, "density_g_cm3": dens, "mass_g": b["volume_mm3"] / 1000 * dens})
            return {"bodies": out, "total": {"mass_g": sum(b["mass_g"] for b in out)}}
        if name == "batch":
            return {"ok": True}
        if name == "describe_command":
            raise RuntimeError("unknown command")
        raise AssertionError(name)

    def execute(self, command, **params):
        self.calls.append((command, params))
        if command == "component.list":
            return {"components": self.comps}
        if command == "assembly.bom":
            return {"rows": self.bom_rows}
        if command == "material.assign":
            for b in params["bodies"]:
                self.materials[b] = params["material"]
            return {}
        if command == "material.list":
            return {"materials": [{"name": "ABS Plastic", "density_g_cm3": 1.06}]}
        if command == "browser.visibility":
            key = [tuple(p) for p in params.get("paths") or []]
            target = self.hidden_paths
            items = params.get("items") or []
            if params["visible"]:
                target.difference_update(key)
                self.hidden_items.difference_update(items)
            else:
                target.update(key)
                self.hidden_items.update(items)
            return {}
        raise AssertionError(command)

    def paint(self, bodies, color, opacity):
        self.calls.append(("paint", color, opacity))

    def screenshot(self, path: Path, camera: dict, width: int, height: int):
        self.shots.append((path.name, camera, width, height))
        img = _gradient(width, height).copy()
        lo, hi = self._world_box()
        if camera["fov"] == 0:
            scale = height / (0.8 * camera["distance"])
            f, r, u = ortho.basis(camera["yaw"], camera["pitch"])
            c = ortho.corners(lo, hi) - np.array(camera["target"])
            xs, ys = c @ r * scale + width / 2, -(c @ u) * scale + height / 2
            x0, x1, y0, y1 = (int(round(v)) for v in (xs.min(), xs.max(), ys.min(), ys.max()))
            if x1 > 0 and y1 > 0 and x0 < width and y0 < height:
                img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = (60, 64, 70)
                img[max(0, y0) + 1:max(0, y1 - 1), max(0, x0 + 1):max(0, x1 - 1)] = (200, 204, 210)
        else:
            img[height // 3: 2 * height // 3, width // 3: 2 * width // 3] = (150, 155, 160)
        Image.fromarray(img).save(path)

    def _world_box(self):
        rows = self.world if self.world is not None else self.bodies_
        lo = np.min([b["bbox"]["min"] for b in rows], axis=0)
        hi = np.max([b["bbox"]["max"] for b in rows], axis=0)
        return lo.tolist(), hi.tolist()


class Pal:
    name = "white"
    shaded, wireframe = "#e9edf1", "#c9d1da"


def _ctx(tmp_path, sc, settings=None, design="pi-case.sc"):
    info = [dict(b) for b in sc.bodies_]
    box = render.SolidCraft.bounds(info)
    out = tmp_path / "set"
    out.mkdir(exist_ok=True)
    return steps.StepContext(sc=sc, design=tmp_path / design, out_dir=out, stem=Path(design).stem, opts=None,
                             info=info, bodies=[b["name"] for b in info], box=box, palette=Pal(),
                             pitch=math.radians(24), report={}, settings=settings or {})


@pytest.fixture
def only_specs_steps(monkeypatch):
    monkeypatch.setattr(steps, "_STEPS", {k: v for k, v in steps._STEPS.items() if k.startswith("specs-")})


# ---------------------------------------------------------------- drawing primitives

def test_tokens_come_from_kists_light_theme():
    t = draw.light_tokens()
    assert t["bg"].startswith("#") and t["text"].startswith("#")
    ink = draw.ink()
    assert ink.paper == draw._hex(t["bg"]) and ink.text == draw._hex(t["text"])
    # every sheet colour is neutral enough to pass the colour guard untouched
    for c in (ink.paper, ink.text, ink.dim, ink.frame, ink.rule):
        assert (max(c) - min(c)) / 255 < 0.12


def test_vendored_fonts_load():
    for face in ("ui", "mono", "serif"):
        f = draw.font(face, 24)
        assert f.getname()[0] in ("Inter", "JetBrains Mono", "Instrument Serif")
        assert draw.text_w(f, "95 × 66") > 0


def test_cutout_lifts_the_part_off_the_gradient_exactly():
    plate = _gradient(200, 120)
    shot = plate.copy()
    shot[30:90, 50:150] = (120, 124, 130)
    shot[50:70, 90:110] = plate[50:70, 90:110]  # a hole through the part shows the background
    im = draw.cutout(Image.fromarray(shot), Image.fromarray(plate))
    a = np.asarray(im.getchannel("A"))
    assert a[0, 0] == 0 and a[60, 60] == 255 and a[60, 100] == 0
    assert draw.opaque_box(im) == (50, 30, 150, 90)


def test_formatting():
    assert draw.fmt_mm(95.0) == "95" and draw.fmt_mm(32.5) == "32.5" and draw.fmt_mm(0.8) == "0.8"
    assert draw.fmt_mm(1600.4) == "1600"
    assert draw.envelope([[-47.5, -33, 0], [47.5, 33, 32]]) == "95 × 66 × 32"
    assert spec.fmt_value(85.0) == "85" and spec.fmt_value(2.5) == "2.5" and spec.fmt_value(12000) == "12,000"
    assert spec.fmt_mass(30.58) == "31 g" and spec.fmt_mass(1.43) == "1.4 g" and spec.fmt_mass(2500) == "2.5 kg"


def test_title_block_pairs_halves_and_sits_on_the_bottom():
    s = draw.Sheet(800, 600)
    cells = [draw.Cell("Title", "pi-case\npi-case.sc", wide=True, kind="serif"), draw.Cell("Rev", "1258878"),
             draw.Cell("Date", "2026-11-18"), draw.Cell("Licence", None)]
    h = draw.title_block_height(cells, label_size=12, value_size=16, title_size=30)
    top = draw.title_block(s, (400, 0, 800, 600), cells, label_size=12, value_size=16, title_size=30)
    assert top == 600 - h and len(draw._rows(cells)) == 3


# ---------------------------------------------------------------- orthographic maths

def test_view_extents_and_scale():
    lo, hi = [-47.5, -33, 0], [47.5, 33, 32]
    assert [round(v, 6) for v in ortho.extent(lo, hi, "front")] == [95, 32, 66]
    assert [round(v, 6) for v in ortho.extent(lo, hi, "top")] == [95, 66, 32]
    assert [round(v, 6) for v in ortho.extent(lo, hi, "right")] == [66, 32, 95]
    # 0.44.1 measured: 800 px tall at distance 100 shows 80 mm (10 px/mm)
    assert ortho.distance_for(800, 10.0) == pytest.approx(100.0)
    assert ortho.scale_label(1) == "1:1" and ortho.scale_label(0.5) == "1:2" and ortho.scale_label(5) == "5:1"
    assert ortho.best_scale(lambda s: s <= 20) == 2  # 2:1 is 16 px/mm on paper
    assert ortho.best_scale(lambda s: s <= 1) == 0.1


def test_views_sheet_picks_the_largest_iso_scale_that_fits():
    # top over front (Y + Z high), right beside front (X + Y wide), plus gaps and labels
    assert views.views_layout([0, 0, 0], [95, 66, 32], 3000, 1600, 120, 48) == (1, 8.0)
    assert views.views_layout([0, 0, 0], [30, 74, 10], 3000, 1640, 120, 48) == (2, 16.0)
    assert views.views_layout([0, 0, 0], [1600, 490, 296], 3000, 1600, 120, 48)[0] == 0.1


def test_drawing_backend_is_feature_detected():
    sc = FakeSC()
    assert ortho.drawing_support(sc) is False
    name, fn = ortho.sheet_backend(sc)
    assert name == "screenshots" and fn is not None


def test_shooter_scale_is_exact(tmp_path):
    sc = FakeSC()
    sh = ortho.Shooter(sc, tmp_path, ([-47.5, -33, 0], [47.5, 33, 32]))
    im, info = sh.view("front", 10.0, pad=12)
    assert im.size == (950 + 24, 320 + 24)
    assert info["measured_px"][2] - info["measured_px"][0] == pytest.approx(950, abs=2)
    assert info["measured_px"][3] - info["measured_px"][1] == pytest.approx(320, abs=2)
    # the plate is shot looking at empty space, once per size
    plates = [s for s in sc.shots if s[0].startswith("plate-")]
    assert len(plates) == 1


# ---------------------------------------------------------------- BOM

BOM_YAML = b"""
currency: EUR
parts:
  - name: M3x8 socket head cap screw
    qty: 6
    supplier: Example Fasteners
    url: https://example.com/m3x8
    price: 0.12
  - name: Rubber foot
    qty: 4
    price: nope
  - match: arm
    supplier: Workshop
    notes: print in PETG
  - match: Nothing here
  - url: javascript:alert(1)
  - name: Bad link
    url: javascript:alert(1)
"""


def test_bom_yaml_parse_merge_and_csv():
    model = [{"qty": 2, "name": "Arm", "part_number": "", "kind": "make", "source": "model", "description": ""},
             {"qty": 1, "name": "Hub", "part_number": "H-1", "kind": "buy", "source": "model", "description": ""}]
    extra, currency, warnings = bom.parse_yaml(BOM_YAML)
    assert currency == "EUR"
    assert any("price" in w for w in warnings) and any("needs a name" in w for w in warnings)
    assert any("url must be http" in w for w in warnings)
    rows = bom.merge(model, extra)
    by = {r["name"]: r for r in rows}
    assert by["Arm"]["supplier"] == "Workshop" and by["Arm"]["source"] == "model+bom.yaml" and by["Arm"]["qty"] == 2
    assert by["M3x8 socket head cap screw"]["kind"] == "buy" and by["M3x8 socket head cap screw"]["total"] == 0.72
    assert by["Rubber foot"]["price"] is None and by["Bad link"]["url"] == ""
    assert "Nothing here" not in by
    assert bom.unmatched(model, extra) == ["bom.yaml: match 'Nothing here' names no part in the model"]
    assert [r["item"] for r in rows] == list(range(1, len(rows) + 1))
    sm = bom.summary(rows, currency)
    assert sm["parts"] == 2 + 1 + 6 + 4 + 1 and sm["total_price"] == 0.72 and sm["make"] == 2
    csv_text = bom.to_csv(rows)
    assert csv_text.splitlines()[0] == ",".join(bom.COLUMNS)


def test_bom_yaml_inline_and_broken():
    entries, _, _ = bom.parse_yaml([{"name": "Fan 40 mm", "qty": 1}])
    assert entries[0]["name"] == "Fan 40 mm"
    assert bom.parse_yaml(b"parts: [unclosed")[0] == []
    assert bom.parse_yaml(b"42")[2] == ["bom.yaml: expected a list of parts"]


def test_model_rows_skip_reference_parts():
    sc = FakeSC(bom_rows=[{"count": 2, "definition": "Arm", "bom_type": "normal"},
                          {"count": 1, "definition": "Fixture", "bom_type": "reference"},
                          {"count": 4, "definition": "Bearing", "bom_type": "purchased", "part_number": "608"}])
    rows = bom.model_rows(sc)
    assert [(r["name"], r["qty"], r["kind"]) for r in rows] == [("Arm", 2, "make"), ("Bearing", 4, "buy")]


# ---------------------------------------------------------------- spec

def test_mass_needs_a_real_material():
    rows = [{"name": "a", "closed": True, "material": "Default", "mass_g": 37.2, "density_g_cm3": 1.29}]
    assert spec.mass_and_material(rows, None, 28850, None)["mass_g"] is None
    rows[0].update(material="ABS Plastic", mass_g=30.58, density_g_cm3=1.06)
    out = spec.mass_and_material(rows, None, 28850, None)
    assert out["mass_g"] == pytest.approx(30.58) and out["material"] == "ABS Plastic"
    # too big to measure: density × volume for an assigned material only
    assert spec.mass_and_material(None, "ABS Plastic", 1000.0, lambda m: 1.06)["mass_g"] == pytest.approx(1.06)
    assert spec.mass_and_material(None, None, 1000.0, lambda m: 1.06)["mass_g"] is None


def test_spec_uses_placed_bodies_for_assemblies(tmp_path):
    # inspect_design lists a component's body once, at its definition; measure has each placement
    sc = FakeSC(bodies=[{"name": "Base", "visible": True, "closed": True, "volume_mm3": 1000.0,
                         "bbox": {"min": [0, 0, 0], "max": [10, 10, 10]}},
                        {"name": "ArmBody", "visible": True, "closed": True, "volume_mm3": 160.0,
                         "bbox": {"min": [20, 0, 0], "max": [30, 4, 4]}}],
                world=[{"name": "Base", "closed": True, "volume_mm3": 1000.0,
                        "bbox": {"min": [0, 0, 0], "max": [10, 10, 10]}},
                       {"name": "ArmBody", "closed": True, "volume_mm3": 160.0,
                        "bbox": {"min": [20, 50, 0], "max": [30, 54, 4]}},
                       {"name": "ArmBody (Arm:2)", "definition": "ArmBody", "closed": True, "volume_mm3": 160.0,
                        "bbox": {"min": [20, 70, 0], "max": [30, 74, 4]}}])
    ctx = _ctx(tmp_path, sc, {"specs_material": "ABS Plastic"})
    data = spec.build_spec(ctx, {}, {})
    assert data["bounds_mm"] == [[0, 0, 0], [30, 74, 10]] and data["bodies"] == 3
    assert data["volume_mm3"] == pytest.approx(1320.0)
    assert data["mass_g"] == pytest.approx(1.32 * 1.06) and data["material"] == "ABS Plastic"
    assert data["parameters"] == [{"name": "wall", "value": 2.0, "unit": "mm", "expression": "2 mm", "comment": None}]
    assert ("material.assign", {"bodies": ["Base", "ArmBody"], "material": "ABS Plastic"}) in sc.calls


# ---------------------------------------------------------------- assembly steps

ARM_COMPS = [
    {"id": 0, "name": "root", "parent": None, "bodies": ["Base"],
     "children": [{"id": 3, "component": 2, "name": "Arm:1"}, {"id": 6, "component": 2, "name": "Arm:2"},
                  {"id": 8, "component": 7, "name": "Arm (copy):1"}]},
    {"id": 2, "name": "Arm", "parent": 0, "bodies": ["ArmBody"], "children": []},
    {"id": 7, "name": "Arm (copy)", "parent": 0, "bodies": ["Body1"], "children": []},
]


def test_assembly_plan_and_buildup(tmp_path):
    sc = FakeSC(comps=ARM_COMPS)
    st = assembly.structure(sc)
    plan = assembly.default_steps(st)
    assert [p["name"] for p in plan] == ["Base parts", "Add Arm", "Add Arm (copy)"]
    cfg, unknown = assembly.steps_from_config(st, [{"name": "Arms", "components": ["arm", "Arm (copy):1", "Gear"]},
                                                   "Base"])
    assert [(p["name"], p["components"], p["root_bodies"]) for p in cfg] == [("Arms", [2, 7], []),
                                                                           ("Base", [], ["Base"])]
    assert unknown == ["Gear"]
    ctx = _ctx(tmp_path, sc)
    ctx.info = [{"name": n, "visible": True} for n in ("Base", "ArmBody", "Body1")]
    ctx.bodies = ["Base", "ArmBody", "Body1"]
    shots = assembly.run_steps(ctx, st, plan, "arm", {"fov": 0.5}, (64, 48))
    assert [s["file"] for s in shots] == ["arm-assembly-01.png", "arm-assembly-02.png", "arm-assembly-03.png"]
    assert shots[1]["qty"] == {"Arm": 2}
    assert not sc.hidden_paths and not sc.hidden_items  # everything shown again
    md = assembly.buildup("arm", shots)
    assert "## Step 2: Add Arm" in md and "* Add [Arm]{Qty: 2}" in md and "{{BOM}}" in md
    assert "![Step 3: Add Arm (copy)](arm-assembly-03.png)" in md


# ---------------------------------------------------------------- the steps, end to end

def test_steps_make_every_sheet(tmp_path, only_specs_steps):
    (tmp_path / "bom.yaml").write_bytes(BOM_YAML)
    sc = FakeSC(comps=ARM_COMPS, bom_rows=[{"count": 2, "definition": "Arm", "bom_type": "normal"}])
    ctx = _ctx(tmp_path, sc, {"specs_assembly": True})
    steps.run_all(ctx)
    res = ctx.report["steps"]
    assert all(r["ok"] for r in res.values()), res
    variants = {o.variant: o for o in ctx.added}
    assert set(variants) >= {"spec-card", "bom-csv", "bom-sheet", "views-sheet", "views-sheet-pdf", "dimensions",
                             "assembly-1", "assembly-2", "assembly-3", "assembly-md"}
    assert all(o.style == "specs" for o in ctx.added)
    assert (variants["spec-card"].width, variants["spec-card"].height) == (2048, 1152)
    for o in ctx.added:
        assert (ctx.out_dir / o.file).is_file(), o.file
    with Image.open(ctx.out_dir / "pi-case-spec-card.png") as im:
        assert im.size == (2048, 1152)
    assert (ctx.out_dir / "pi-case-views-sheet.pdf").read_bytes()[:5] == b"%PDF-"
    # PNGs go through the colour guard; CSV, PDF and Markdown don't
    guarded = {p.name for p in ctx.guard}
    assert "pi-case-spec-card.png" in guarded and "pi-case-bom.csv" not in guarded
    data = json.loads((ctx.out_dir / "spec.json").read_text())
    assert data["title"] == "pi-case" and data["size_mm"] == [95, 66, 32]
    b = json.loads((ctx.out_dir / "bom.json").read_text())
    assert b["bom_yaml"] == "bom.yaml" and b["summary"]["currency"] == "EUR"
    # the dimension still is to scale: the box's projection matches the cut-out
    d = ctx.report["specs"]["dimensions"]
    assert d["width_mm"] == 95 and d["height_mm"] == 32 and d["depth_mm"] == 66
    assert abs(d["measured_px"][0] - d["expected_px"][0]) <= 2 and abs(d["measured_px"][1] - d["expected_px"][1]) <= 2
    assert ctx.report["specs"]["views"]["scale"] in ("1:1", "2:1")
    assert not (ctx.out_dir / "_specs").exists()  # scratch removed
    assert ("paint", Pal.shaded, 1.0) in sc.calls  # restored after the white-palette sheets


def test_steps_follow_settings_and_skip_single_parts(tmp_path, only_specs_steps):
    sc = FakeSC()
    ctx = _ctx(tmp_path, sc, {"specs_card": False, "specs_views": False, "specs_dimensions": True})
    steps.run_all(ctx)
    assert {o.variant for o in ctx.added} == {"dimensions"}
    assert (ctx.out_dir / "spec.json").is_file()  # the data always
    assert "skipped" in ctx.report["specs"]["bom"]
    assert "specs-assembly" not in ctx.report["steps"]  # off by default
    # an outputs list naming specs variants picks just those
    (tmp_path / "b").mkdir()
    ctx2 = _ctx(tmp_path / "b", FakeSC(), {"outputs": ["1080p", "spec-card"]})
    steps.run_all(ctx2)
    assert {o.variant for o in ctx2.added} == {"spec-card"}


def test_a_failing_step_never_fails_the_render(tmp_path, only_specs_steps):
    sc = FakeSC()

    def broken(*a, **k):
        raise RuntimeError("no GPU")

    sc.screenshot = broken
    ctx = _ctx(tmp_path, sc)
    steps.run_all(ctx)
    assert ctx.report["steps"]["specs-views"]["ok"] is False
    assert (ctx.out_dir / "spec.json").is_file()


# ---------------------------------------------------------------- settings

def test_settings_are_registered_and_validated():
    s = jobs.get_all_settings()
    for k, v in specs.DEFAULTS.items():
        assert s[k] == v
    jobs.set_options({"specs_assembly": "yes", "specs_material": "ABS Plastic", "specs_assembly_max_steps": 12})
    s = jobs.get_all_settings()
    assert s["specs_assembly"] is True and s["specs_material"] == "ABS Plastic" and s["specs_assembly_max_steps"] == 12
    for bad in ({"specs_assembly_max_steps": 0}, {"specs_material": "x" * 65}, {"specs_bom_file": "../etc/passwd"}):
        with pytest.raises(ValueError):
            jobs.set_options(bad)


# ---------------------------------------------------------------- design metadata

def _source(url="https://github.com/o/r") -> dict:
    return jobs.add_source(url)


def _design(source_id: str, render_dir: Path | None, files: list, path="parts/case.sc") -> str:
    did = db.new_id()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha, commit_sha,"
            " status, render_dir, files, rendered_sha, rendered_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [did, source_id, "o", "r", "main", path, f"https://github.com/o/r/blob/c/{path}", "b" * 40, "c" * 40,
             "rendered" if render_dir else "new", str(render_dir) if render_dir else None, json.dumps(files),
             "b" * 40 if render_dir else None, db.now(), db.now()])
    return did


def test_design_row_comes_from_the_set_folder(settings, tmp_path):
    did = _design(_source()["id"], None, [])
    out = settings.renders_dir / did / "bbbbbbbbbbbb"
    out.mkdir(parents=True)
    ctx = _ctx(tmp_path, FakeSC())
    ctx.out_dir = out
    row = meta.design_row(ctx)
    assert row["id"] == did and row["owner"] == "o" and row["provider"] == "github"
    ctx.out_dir = tmp_path  # a local render: no row
    assert meta.design_row(ctx) == {}
    ctx.settings = {"design": {"owner": "x", "repo": "y"}}
    assert meta.design_row(ctx) == {"owner": "x", "repo": "y"}
    assert meta.licence({"license": {"spdx": "CERN-OHL-S-2.0"}}) == "CERN-OHL-S-2.0"
    assert meta.pick({"assembly": {"steps": [1]}}, "assembly.steps") == [1]


# ---------------------------------------------------------------- API, contact sheet, MCP

def _rendered_design(settings, sid, name="case", spec_json=True):
    out = settings.renders_dir / "x" / name
    out.mkdir(parents=True)
    Image.fromarray(_gradient(256, 256)).save(out / f"{name}-shaded-social-2048.png")
    (out / f"{name}-bom.csv").write_text("item,qty\n1,2\n")
    files = [{"file": f"{name}-shaded-social-2048.png", "style": "shaded", "variant": "social", "width": 2048,
              "height": 2048},
             {"file": f"{name}-bom.csv", "style": "specs", "variant": "bom-csv", "width": 0, "height": 0}]
    did = _design(sid, out, files, path=f"parts/{name}.sc")
    if spec_json:
        (out / "spec.json").write_text(json.dumps({"title": name, "bounds_mm": [[0, 0, 0], [95, 66, 32]],
                                                   "bodies": 1, "licence": "MIT"}))
        (out / "bom.json").write_text(json.dumps({"rows": [], "summary": {"lines": 0}}))
    return did


def test_api_spec_bom_and_design_json(settings):
    from sklent.app import app

    sid = _source()["id"]
    did = _rendered_design(settings, sid)
    bare = _rendered_design(settings, sid, "bare", spec_json=False)
    c = TestClient(app)  # no lifespan: the worker and MCP session aren't needed
    if True:
        d = c.get(f"/api/designs/{did}", headers=H).json()
        assert d["spec"]["licence"] == "MIT"
        assert c.get(f"/api/designs/{bare}", headers=H).json()["spec"] is None
        assert c.get(f"/api/designs/{did}/spec", headers=H).json()["title"] == "case"
        assert c.get(f"/api/designs/{did}/bom", headers=H).json()["summary"]["lines"] == 0
        assert c.get(f"/api/designs/{bare}/spec", headers=H).status_code == 404
        assert c.get(f"/api/designs/{did}/assembly", headers=H).status_code == 404
        assert c.get("/api/designs/nope/spec", headers=H).status_code == 404
        assert c.get(f"/api/designs/{did}/spec").status_code == 401


def test_contact_sheet_builds_caches_and_files_into_kist_once(settings, monkeypatch):
    from sklent import kist
    from sklent.app import app

    uploads = []

    class FakeKist:
        enabled = True

        def ensure_folder(self, path):
            uploads.append(("folder", tuple(path)))
            return "f1"

        def upload(self, file, **kw):
            uploads.append(("upload", file.name, tuple(kw["tags"])))
            return {"id": f"i{len(uploads)}"}

    monkeypatch.setattr(kist, "Kist", FakeKist)
    sid = _source()["id"]
    empty = _source("https://github.com/o/empty")["id"]
    for i in range(3):
        _rendered_design(settings, sid, f"part{i}")
    c = TestClient(app)
    if True:
        assert c.post(f"/api/sources/{empty}/contact-sheet", headers=H).status_code == 409
        assert c.post("/api/sources/nope/contact-sheet", headers=H).status_code == 404
        r = c.post(f"/api/sources/{sid}/contact-sheet", headers=H).json()
        assert r["designs"] == 3 and r["pages"] == 1 and len(r["kist_items"]) == 2
        assert ("folder", ("SolidCraft", "o", "r")) in uploads
        assert any(u[0] == "upload" and "format:contact-sheet" in u[2] for u in uploads)
        again = c.post(f"/api/sources/{sid}/contact-sheet", headers=H).json()
        assert again["kist_items"] == r["kist_items"] and len(uploads) == 3  # filed once per key
        png = c.get(r["png"][0], headers=H)
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(png.content)) as im:
            assert im.size == (3840, 2160)
        pdf = c.get(r["pdf"], headers=H)
        assert pdf.content[:5] == b"%PDF-"
        assert c.get(f"/api/sources/{sid}/contact-sheet.png?page=2", headers=H).status_code == 404


def test_mcp_tools_are_listed():
    import asyncio

    from sklent.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"get_design_spec", "get_bom", "make_contact_sheet", "view_sheet"} <= names


def test_set_files_carry_agreed_variant_names():
    assert set(specs.VARIANTS) == {"spec-card", "bom-csv", "bom-sheet", "views-sheet", "views-sheet-pdf",
                                   "dimensions", "assembly-md"}
    assert Output("a", "specs", "assembly-1", 1, 1).variant.startswith("assembly-")


# ---------------------------------------------------------------- web

def test_web_module_and_css_follow_the_design_rules():
    js = WEB / "js" / "features" / "specs.js"
    css = WEB / "css" / "features" / "specs.css"
    assert "import './features/specs.js';" in (WEB / "js" / "features.js").read_text()
    assert '/static/css/features/specs.css' in (WEB / "index.html").read_text()
    src = js.read_text()
    for target in re.findall(r"^\s*import\s+(?:[^'\"]+\s+from\s+)?['\"](\.[^'\"]+)['\"]", src, re.M):
        assert (js.parent / target).resolve().is_file(), target
    text = css.read_text()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", text), "tokens only, no colour values"
    tokens = "".join(p.read_text() for p in (WEB / "css").glob("*tokens.css"))
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", tokens))
    for v in set(re.findall(r"var\((--[a-z0-9-]+)", text)):
        assert v in defined, v
    own = {c for c in re.findall(r"\.([a-z][a-z0-9-]*)", text)} - {"sk-data"}  # sk-data: the shared spec voice
    assert own and all(c.startswith("sk-specs-") for c in own), own
