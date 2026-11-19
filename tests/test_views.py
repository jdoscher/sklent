"""Views and render modes (area V): F17 quick check and outputs, F24 shots and masters,
F4 exploded, F9 section, F10 configurations, F20 highlight, F22 motion, F15 transparent
and hero, F16 plate and bed fit. SolidCraft is faked; real renders run on the render host."""

import json
import math
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sklent import db, jobs, render, sets, steps
from sklent.features import views
from sklent.features.views import api as vapi
from sklent.features.views import beds as bedlib
from sklent.features.views import sheets
from sklent.features.views import steps as vsteps
from sklent.render import FOV, Output, RenderOptions, _basis, render_set
from sklent.solidcraft import SolidCraft, SolidCraftError

H = {"Authorization": "Bearer test-token-0123456789"}


# ---------------------------------------------------------------- a fake SolidCraft

class FakeSC:
    """Writes small grey PNGs for screenshots and render jobs; answers the commands the
    views steps use from `replies`; records every call."""

    instances: list["FakeSC"] = []
    replies: dict = {}
    info = [{"name": "a", "visible": True, "bbox": {"min": [-10, -10, 0], "max": [10, 10, 20]},
             "volume_mm3": 100.0},
            {"name": "b", "visible": True, "bbox": {"min": [20, -5, 0], "max": [30, 5, 4]},
             "volume_mm3": 10.0}]

    def __init__(self, design: Path = Path("d.sc"), out_dir: Path = Path(".")):
        FakeSC.instances.append(self)
        self.proc = SimpleNamespace(pid=-1)
        self.calls: list[tuple] = []
        self.shots: list[tuple[Path, dict]] = []

    def bodies(self):
        self.calls.append(("bodies",))
        r = FakeSC.replies.get("bodies")
        return r() if callable(r) else [dict(b) for b in FakeSC.info]

    bounds = staticmethod(SolidCraft.bounds)

    def paint(self, bodies, color, opacity):
        self.calls.append(("paint", tuple(bodies), opacity))

    def tool(self, name, **args):
        self.calls.append((name, args))
        r = FakeSC.replies.get(name)
        if isinstance(r, Exception):
            raise r
        return r() if callable(r) else (r or {})

    def screenshot(self, path: Path, camera: dict, width: int, height: int):
        Image.new("RGB", (8, 8), (128, 128, 128)).save(path)
        self.shots.append((Path(path), camera))

    def execute(self, command: str, **params):
        self.calls.append((command, params))
        r = FakeSC.replies.get(command)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(**params)
        if command == "render.start":
            return {"job": {"session": 1, "serial": 1, "generation": 1}, "error": None}
        if command == "render.status":
            return {"progress": {"phase": "completed"}}
        if command == "render.export":
            Image.new("RGBA", (12, 10), (0, 0, 0, 0)).save(params["path"])
            return {"bytes": 1}
        if command == "motion.export_animation":
            folder = Path(params["path"])
            folder.mkdir(parents=True, exist_ok=True)
            for i in range(1, 4):
                Image.new("RGB", (8, 8), (128, 128, 128)).save(folder / f"frame-{i:04d}.png")
            return {"frames": 3, "fps": 20.0}
        return r if r is not None else {}

    def kill(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


@pytest.fixture
def fake(monkeypatch):
    FakeSC.instances, FakeSC.replies = [], {}
    monkeypatch.setattr(render, "SolidCraft", FakeSC)
    encoded = []

    def enc(frames, out, *a, **k):
        encoded.append((Path(frames).name, Path(out).name))
        Path(out).write_bytes(b"movie")

    monkeypatch.setattr(render, "encode", enc)
    monkeypatch.setattr(render, "encode_gif", enc)
    monkeypatch.setattr(render, "encode_prores", enc)
    FakeSC.encoded = encoded
    return FakeSC


@pytest.fixture
def no_steps():
    saved = dict(steps._STEPS)
    steps._STEPS.clear()
    yield
    steps._STEPS.update(saved)


def _ctx(tmp_path, sc, settings=None, info=None):
    info = info or [dict(b) for b in FakeSC.info]
    class Pal:
        shaded, wireframe = "#e9edf1", "#c9d1da"
    return steps.StepContext(sc=sc, design=tmp_path / "d.sc", out_dir=tmp_path, stem="d",
                             opts=RenderOptions(), info=info, bodies=[b["name"] for b in info],
                             box=SolidCraft.bounds(info), palette=Pal(), pitch=math.radians(24),
                             report={}, settings={**views.defaults(), **(settings or {})})


# ---------------------------------------------------------------- F17 outputs + quick check

def test_outputs_option_validates_and_orders():
    assert RenderOptions().validate().outputs == list(render.CORE_OUTPUTS)
    assert RenderOptions(outputs=["hires", "1080p", "hires"]).validate().outputs == ["1080p", "hires"]
    assert RenderOptions(outputs=[]).validate().outputs == []
    with pytest.raises(ValueError, match="outputs"):
        RenderOptions(outputs=["4k-movie"]).validate()


def test_quick_check_makes_only_the_preview_and_no_frames(tmp_path, fake, no_steps):
    progress = []
    outputs, report = render_set(Path("d.sc"), tmp_path, "d", RenderOptions(outputs=[]),
                                 lambda f, m: progress(m) if False else progress.append(m), processes=1)
    assert [(o.file, o.variant, o.width) for o in outputs] == [("d-preview.png", "preview", 1024)]
    sc = fake.instances[0]
    assert len(sc.shots) == 1 and (tmp_path / "d-preview.png").exists()
    assert "quick check ready" in progress and report["frame_ms"] is None
    assert not fake.encoded


def test_preview_comes_first_and_is_guarded(tmp_path, fake, no_steps, monkeypatch):
    seen = []
    real = render.clamp_all

    def spy(frames, stills, every=4):
        seen.append(([p.name for p in frames], [p.name for p in stills]))
        return real(frames, stills, every)

    monkeypatch.setattr(render, "clamp_all", spy)
    outputs, report = render_set(Path("d.sc"), tmp_path, "d", RenderOptions(seconds=2, fps=24, outputs=["social"]),
                                 processes=1)
    sc = fake.instances[0]
    assert sc.shots[0][0].name == "d-preview.png"  # before any frame
    assert seen[0] == ([], ["d-preview.png"])  # guarded before the UI can show it
    assert {o.variant for o in outputs} == {"preview", "social"}
    assert not any(p.parent.name.endswith("_land") for p, _ in sc.shots)  # social needs no frames


def test_outputs_subset_skips_unneeded_frames(tmp_path, fake, no_steps):
    outputs, _ = render_set(Path("d.sc"), tmp_path, "d",
                            RenderOptions(seconds=2, fps=24, styles=["shaded"], outputs=["reel"]), processes=1)
    sc = fake.instances[0]
    dirs = {p.parent.name for p, _ in sc.shots if p.parent.parent.name == "_frames"}
    assert dirs == {"shaded_vert"}
    assert [o.variant for o in outputs] == ["preview", "reel"]


# ---------------------------------------------------------------- F24 shots and masters

def _project(p, cam, w, h):
    f, r, u = _basis(cam[1], cam[2])
    q = np.array(p) - np.array(cam[0])
    depth = q @ f + cam[3]
    tan_v = math.tan(FOV / 2)
    return (q @ r) / depth / (tan_v * w / h), (q @ u) / depth / tan_v


@pytest.mark.parametrize("shot", render.SHOTS)
def test_shot_presets_keep_the_part_in_frame_and_ease(shot):
    lo, hi = [-110, -63, 0], [110, 63, 142]
    pitch = math.radians(24)
    path = render.shot_path(shot, (lo, hi), pitch, 60)
    assert len(path) == 60
    for cam in path:
        worst = max(max(abs(v) for v in _project([x, y, z], cam, 1920, 1080))
                    for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2]))
        assert worst <= 1.0
    # eased: the first and last steps move less than the middle ones
    moves = [abs(path[i + 1][1] - path[i][1]) + abs(path[i + 1][2] - path[i][2])
             + abs(path[i + 1][3] - path[i][3]) / 100 for i in range(59)]
    assert moves[0] < moves[30] and moves[-1] < moves[30]
    if shot in ("half-orbit", "top-to-iso"):  # they settle on the hero (iso) angle
        assert abs(path[-1][1] - render.STILL_YAW) < 1e-9 and abs(path[-1][2] - pitch) < 1e-9


def test_ortho_fit_scale():
    cam = render.ortho_fit([-47.5, -33, 0], [47.5, 33, 32], 1000, 500, 0.0, 0.0, margin=1.0)
    # front view: 95 mm wide × 32 mm tall into 1000 × 500 px → width-bound at 1000/95 px/mm
    assert cam["fov"] == 0
    assert abs(render.ortho_scale(cam, 500) - 1000 / 95) < 1e-6


def test_shots_masters_and_highlight_render(tmp_path, fake, no_steps, monkeypatch):
    settings = {"views_shot_push_in": True, "views_shot_low_angle": True, "views_shot_seconds": 2,
                "views_master_4k": True, "views_master_zip": True, "views_master_prores": True,
                "views_master_seconds": 3, "views_highlight_names": ["b*"]}
    opts = RenderOptions(seconds=2, fps=24, styles=["shaded"], outputs=["1080p"])
    outputs, report = render_set(Path("d.sc"), tmp_path, "d", opts, processes=1, settings=settings)
    by = {o.variant: o for o in outputs}
    assert {"preview", "1080p", "preset-push-in", "preset-low-angle", "master-4k", "prores", "frames-zip",
            "highlight", "highlight-turntable"} <= set(by)
    assert by["master-4k"].width == 3840 and by["highlight"].style == "highlight"
    z = zipfile.ZipFile(tmp_path / by["frames-zip"].file)
    assert len(z.namelist()) == 72  # 3 s × 24 fps, no repeated loop frame
    sc = fake.instances[0]
    frames = [p for p, _ in sc.shots if p.parent.parent.name == "_frames"]
    count = {d: sum(1 for p in frames if p.parent.name == d) for d in {p.parent.name for p in frames}}
    assert count == {"shaded_land": 48, "shaded_master": 72, "shaded_shot-push-in": 48,
                     "shaded_shot-low-angle": 48, "highlight_land": 48}
    assert ("paint", ("a",), 0.0) in sc.calls and ("paint", ("b",), 1.0) in sc.calls  # b solid, a x-ray
    assert report["highlight"]["bodies"] == ["b"]
    low = [c for p, c in sc.shots if p.parent.name == "shaded_shot-low-angle"]
    assert all(abs(c["pitch"] - math.radians(6)) < 1e-9 for c in low)


def test_framing_uses_placed_boxes(tmp_path, fake, no_steps):
    # inspect_design measures a component's bodies in its own frame; measure gives the placed box
    FakeSC.replies = {"measure": {"bodies": [{"name": "b", "bbox": {"min": [0, 29, 7], "max": [40, 32, 37]}}]}}
    _, report = render_set(Path("d.sc"), tmp_path, "d", RenderOptions(outputs=[]), processes=1)
    assert report["bounds_mm"] == ([-10, -10, 0], [40, 32, 37])
    FakeSC.replies = {"measure": SolidCraftError("measure: no")}
    _, report = render_set(Path("d.sc"), tmp_path, "d", RenderOptions(outputs=[]), processes=1)
    assert report["bounds_mm"] == ([-10, -10, 0], [30, 10, 20])


def test_highlight_that_matches_nothing_is_reported(tmp_path, fake, no_steps):
    outputs, report = render_set(Path("d.sc"), tmp_path, "d", RenderOptions(outputs=[]), processes=1,
                                 settings={"views_highlight_names": ["nope"]})
    assert report["highlight"]["skipped"] and [o.variant for o in outputs] == ["preview"]


def test_an_oversized_master_is_dropped_with_a_reason(tmp_path, fake, no_steps, monkeypatch):
    monkeypatch.setattr(render, "MASTER_MAX_BYTES", 3)  # the fake encoder writes 5 bytes
    outputs, report = render_set(Path("d.sc"), tmp_path, "d", RenderOptions(seconds=2, fps=24, styles=["shaded"],
                                                                         outputs=[]),
                                 processes=1, settings={"views_master_4k": True, "views_master_seconds": 2})
    assert "master-4k" not in {o.variant for o in outputs}
    assert "views_master_seconds" in report["skipped"]["d-shaded-master-3840x2160.mp4"]
    assert not (tmp_path / "d-shaded-master-3840x2160.mp4").exists()


def test_plan_reads_settings():
    p = render.plan(RenderOptions(seconds=8, outputs=["gif"]), {"views_master_zip": 1, "views_master_seconds": 0,
                                                                "views_shot_top_to_iso": True})
    assert p.land and not p.vert and p.stills == [] and p.master == ["zip"] and p.master_seconds == 8
    assert p.shots == ["top-to-iso"]


# ---------------------------------------------------------------- F16 beds

def test_beds_parse_format_and_fit():
    beds = bedlib.parse_beds(bedlib.DEFAULT_BEDS)
    assert [b["name"] for b in beds][:2] == ["Bambu Lab A1 mini", "Bambu Lab X1/P1/A1"]
    assert bedlib.clean_beds(" Prusa MK4 250 x 210 x 220 mm ;") == "Prusa MK4 250x210x220"
    assert bedlib.clean_beds([{"name": "Big", "x": 300, "y": 300, "z": 300}]) == "Big 300x300x300"
    with pytest.raises(ValueError):
        bedlib.parse_beds("Prusa MK4 250x210")
    mk4 = {"name": "MK4", "x": 250, "y": 210, "z": 220}
    assert bedlib.fits([215, 240, 20], mk4)  # turned and laid flat
    assert not bedlib.fits([260, 10, 10], mk4)
    fit = bedlib.bed_fit([{"name": "case", "size": [95, 66, 32]}, {"name": "rail", "size": [10, 10, 230]}],
                         beds, "bambu lab a1 mini")
    assert fit["bed"] == "Bambu Lab A1 mini" and not fit["fits"] and fit["too_big"] == ["rail"]
    assert fit["label"] == "180³" and "Prusa MK4" in fit["fits_beds"]
    assert fit["largest"]["name"] == "rail"


# ---------------------------------------------------------------- steps

def test_facts_step_writes_views_json(tmp_path):
    FakeSC.replies = {"config.table": {"rows": [{"name": "S"}, {"name": "L"}], "active": "S"},
                      "motion.list": {"studies": [{"id": 1, "name": "Open"}]}, "explode.list": {"views": []}}
    ctx = _ctx(tmp_path, FakeSC())
    vsteps.facts(ctx)
    data = sets.read_json(tmp_path, "views.json")
    assert data["configurations"] == ["S", "L"] and data["motion_studies"] == ["Open"]
    assert [p["size"] for p in data["parts"]] == [[20, 20, 20], [10, 10, 4]]


def test_exploded_still_and_animation(tmp_path, fake):
    FakeSC.replies = {"explode.list": {"views": []},
                      "explode.create": {"name": "Sklent exploded", "view": 9,
                                         "moves": [{"occurrence": 2, "translate": [0, 40, 0]}]}}
    sc = FakeSC()
    ctx = _ctx(tmp_path, sc)
    vsteps.exploded(ctx)
    assert [o.variant for o in ctx.added] == ["exploded", "explode-anim", "explode-anim"]
    still_cam = sc.shots[0][1]
    assert still_cam["target"][1] == pytest.approx((-10 + 50) / 2)  # framed on the grown box
    anim = next(p for c, p in [(c[0], c[1]) for c in sc.calls if len(c) > 1] if c == "motion.export_animation")
    assert anim["back"] is True and anim["samples"] % 2 == 1 and anim["view"] == "Sklent exploded"
    assert sc.calls[-1] == ("explode.show", {})  # back to assembled
    assert not (tmp_path / "_explode").exists()


def test_exploded_skips_designs_without_components(tmp_path, fake):
    FakeSC.replies = {"explode.create": SolidCraftError(
        "execute: `explode.create` is not available right now: Exploded View pulls components apart, so the "
        "design needs two or more of them")}
    ctx = _ctx(tmp_path, FakeSC())
    vsteps.exploded(ctx)
    assert not ctx.added and ctx.report["views"]["exploded"]["skipped"].startswith("Exploded View pulls")


def test_exploded_prefers_a_saved_view(tmp_path, fake):
    FakeSC.replies = {"explode.list": {"views": [{"id": 7, "name": "Author", "moves": [[3, [5, 0, 0]]]}]}}
    sc = FakeSC()
    ctx = _ctx(tmp_path, sc)
    vsteps.exploded(ctx)
    assert not any(c[0] == "explode.create" for c in sc.calls)
    assert ("explode.show", {"view": "Author"}) in sc.calls
    assert ctx.report["views"]["exploded"]["source"] == "saved"


@pytest.mark.parametrize("box, plane, flip", [
    (([-47.5, -33, 0], [47.5, 33, 32]), "XZ", True),  # long in X
    (([-5, -100, 0], [5, 100, 20]), "YZ", False),  # long in Y
    (([-5, -10, 0], [5, 10, 200]), "YZ", False),  # tall, Y the longer side
    (([-30, -10, 0], [30, 10, 200]), "XZ", True),  # tall, X the longer side
])
def test_section_plane_contains_the_longest_axis(box, plane, flip):
    cut = vsteps.section_plane(box)
    assert cut["plane"] == plane and cut["flip"] is flip
    centre = [(box[0][i] + box[1][i]) / 2 for i in range(3)]
    assert float(cut["at"]) == pytest.approx(centre[1] if plane == "XZ" else centre[0])


def test_section_step_cuts_shoots_and_clears(tmp_path, fake):
    sc = FakeSC()
    ctx = _ctx(tmp_path, sc, info=[FakeSC.info[0]])
    vsteps.section(ctx)
    assert [o.variant for o in ctx.added] == ["section", "section"]
    cut = next(p for c, p in [(c[0], c[1]) for c in sc.calls if len(c) > 1] if c == "inspect.section")
    assert cut["hatch"] is True
    assert sc.shots[1][1]["fov"] == 0  # the face-on still is orthographic
    assert sc.calls[-1] == ("inspect.section", {"clear": True})


def test_motion_step_clips_each_study(tmp_path, fake):
    FakeSC.replies = {"motion.list": {"studies": [{"id": 9, "name": "Open and close"}]}}
    ctx = _ctx(tmp_path, FakeSC())
    vsteps.motion(ctx)
    assert {o.variant for o in ctx.added} == {"motion-open-and-close"}
    assert {Path(o.file).suffix for o in ctx.added} == {".mp4", ".gif"}
    assert not list(tmp_path.glob("_motion-*"))


def test_motion_step_skips_without_studies(tmp_path, fake):
    FakeSC.replies = {"motion.list": {"studies": []}}
    ctx = _ctx(tmp_path, FakeSC())
    vsteps.motion(ctx)
    assert not ctx.added and "no motion studies" in ctx.report["views"]["motion"]["skipped"]


def test_configs_lineup_at_one_scale_and_restores(tmp_path, fake):
    rows = [{"id": 15, "name": "Default", "values": {"suppress:Fillet1": "false"}},
            {"id": 16, "name": "Plain", "values": {"suppress:Fillet1": "true", "param:w": "40 mm"}}]
    FakeSC.replies = {"config.table": {"rows": rows, "active": "Default"}}
    sc = FakeSC()
    ctx = _ctx(tmp_path, sc)
    vsteps.configs(ctx)
    variants = [o.variant for o in ctx.added]
    assert variants == ["config-1", "config-2", "config-lineup"]
    cams = [c for p, c in sc.shots]
    assert cams[0] == cams[1]  # one camera: one scale
    assert sc.calls[-2] == ("config.activate", {"row": "Default"}) and sc.calls[-1][0] == "paint"
    assert Image.open(tmp_path / "d-config-lineup.png").size[0] > 1000
    assert vsteps._values_label(rows[1]["values"]) == "−Fillet1 w=40 mm"


def test_configs_skip_without_a_table(tmp_path, fake):
    FakeSC.replies = {"config.table": {"rows": []}}
    ctx = _ctx(tmp_path, FakeSC())
    vsteps.configs(ctx)
    assert not ctx.added and ctx.report["views"]["configs"]["skipped"]


def test_transparent_falls_back_to_raytrace_when_raster_refuses(tmp_path, fake):
    starts = []

    def start(**p):
        starts.append(p["settings"]["job"])
        if p["settings"]["job"]["method"] == "raster":
            raise SolidCraftError("execute: LimitExceeded: the scene has at least 262276 triangles")
        return {"job": {"serial": len(starts)}, "error": None}

    FakeSC.replies = {"render.start": start}
    ctx = _ctx(tmp_path, FakeSC())
    vsteps.transparent(ctx)
    assert [o.variant for o in ctx.added] == ["transparent", "transparent"]
    assert starts[1] == {"method": "cpu_raytrace", "transparent_background": True, "options": {"budget": "studio"}}
    assert ctx.report["views"]["transparent"]["method"] == "cpu_raytrace"
    assert Image.open(tmp_path / ctx.added[0].file).mode == "RGBA"


def test_hero_skips_a_scene_too_big_for_the_budget(tmp_path, fake):
    FakeSC.replies = {"render.start": SolidCraftError("execute: LimitExceeded: over the studio budget")}
    ctx = _ctx(tmp_path, FakeSC())
    vsteps.hero(ctx)
    assert not ctx.added and "too big" in ctx.report["views"]["hero"]["skipped"]


def test_hero_renders_with_the_studio_budget(tmp_path, fake):
    sc = FakeSC()
    ctx = _ctx(tmp_path, sc)
    vsteps.hero(ctx)
    start = next(p for c, p in [(c[0], c[1]) for c in sc.calls if len(c) > 1] if c == "render.start")
    assert start["settings"]["job"] == {"method": "cpu_raytrace", "transparent_background": True,
                                        "options": {"budget": "studio"}}
    assert [o.variant for o in ctx.added] == ["hero"]


def test_plate_isolates_each_part_and_puts_visibility_back(tmp_path, fake):
    info = [*FakeSC.info, {**FakeSC.info[1], "name": "b2"}]  # b2 is a copy of b: one cell, ×2
    FakeSC.replies = {
        "browser.visibility": lambda **p: {"visibility": {"hidden_bodies": [n for n in ("a", "b", "b2")
                                                                             if n not in p["items"]]}}}
    sc = FakeSC()
    ctx = _ctx(tmp_path, sc, info=info)
    vsteps.plate(ctx)
    assert [o.variant for o in ctx.added] == ["plate"]
    isolates = [c[1] for c in sc.calls if c[0] == "browser.visibility"]
    assert [i["items"] for i in isolates] == [["a"], ["b"]]
    assert sum(1 for c in sc.calls if c[0] == "edit.undo") == 2
    tops = [c[1]["settings"]["camera"] for c in sc.calls if c[0] == "render.start"]
    assert tops[0]["fov"] == 0 and tops[1]["pitch"] == pytest.approx(math.pi / 2)  # b lies flat: top-down
    assert ctx.report["views"]["plate"]["cells"] == 2
    assert not (tmp_path / "_plate").exists()


def test_lineup_and_plate_sheets(tmp_path):
    cells = []
    for i in range(3):
        p = tmp_path / f"c{i}.png"
        Image.new("RGBA", (50 + 10 * i, 40), (150, 150, 150, 255)).save(p)
        cells.append((p, f"part {i}", "10 × 20 mm"))
    w, h = sheets.plate(cells, tmp_path / "plate.png", px_per_mm=5, title="t")
    assert (w, h) == Image.open(tmp_path / "plate.png").size
    part = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    part.paste((240, 240, 240, 255), (3, 3, 7, 7))
    ring = np.asarray(sheets.outlined(part))
    assert ring.shape[:2] == (12, 12) and tuple(ring[3, 5][:3]) == sheets.EDGE
    assert tuple(ring[5, 5][:3]) == (240, 240, 240)
    w, h = sheets.lineup(cells, tmp_path / "lineup.png", title="t")
    im = np.asarray(Image.open(tmp_path / "lineup.png").convert("RGB"), dtype=np.float32) / 255
    assert (im.max(axis=2) - im.min(axis=2)).max() < 0.05  # neutral greys only


def test_steps_are_registered_in_the_v_range():
    mine = [s for s in steps.registered() if s.name.startswith("views-")]
    assert {s.name for s in mine} == {"views-facts", "views-exploded", "views-section", "views-motion",
                                      "views-configs", "views-transparent", "views-hero", "views-plate"}
    assert all(10 <= s.order <= 49 for s in mine)


def test_settings_defaults():
    s = jobs.get_all_settings()
    assert s["outputs"] == list(render.CORE_OUTPUTS)
    off = ["views_exploded", "views_section", "views_transparent", "views_hero", "views_plate",
           "views_master_4k", "views_master_zip", "views_master_prores", "views_shot_half_orbit",
           "views_shot_push_in", "views_shot_top_to_iso", "views_shot_low_angle"]
    assert not any(s[k] for k in off)
    assert s["views_configs"] and s["views_motion"] and s["views_bedfit"]
    with pytest.raises(ValueError):
        jobs.set_options({"views_master_seconds": 1})
    with pytest.raises(ValueError):
        jobs.set_options({"views_beds": "nonsense"})
    jobs.set_options({"outputs": ["social"], "views_beds": "Big 300x300x300", "views_bed": "Big"})
    assert jobs.get_options().outputs == ["social"]


# ---------------------------------------------------------------- API, requests, highlight

def _design(settings, *, files=None, status="rendered", blob="b" * 40):
    source = jobs.add_source("https://github.com/o/r")
    did = db.new_id()
    folder = settings.renders_dir / did / blob[:12]
    folder.mkdir(parents=True)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha, commit_sha,"
            " status, render_dir, files, rendered_sha, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [did, source["id"], "o", "r", "main", "case.sc", "https://github.com/o/r/blob/c/case.sc", blob,
             "c" * 40, status, str(folder), json.dumps(files or []), blob, db.now()])
    return did, folder


def test_render_overrides_consume_the_request_and_add_the_highlight(settings):
    did, _ = _design(settings)
    views.save_request(did, views.clean_request(["hires"], settings={"views_section": "yes"}))
    views.set_highlight(did, ["Arm*", "Arm*", " "])
    opts, s = views.render_overrides(did, RenderOptions(), jobs.get_all_settings())
    assert opts.outputs == ["hires"] and s["views_section"] is True
    assert s["views_highlight_names"] == ["Arm*"]
    assert views.pending_request(did) is None  # consumed
    opts, s = views.render_overrides(did, RenderOptions(), jobs.get_all_settings())
    assert opts.outputs == list(render.CORE_OUTPUTS)
    with pytest.raises(ValueError):
        views.clean_request(settings={"palette": "red"})


def test_repo_config_highlight_is_used_when_the_design_has_none(settings, monkeypatch):
    import sys
    did, _ = _design(settings)
    monkeypatch.setitem(sys.modules, "sklent.repo_config", SimpleNamespace(get=lambda i: {"highlight": "Lid"}))
    import sklent
    monkeypatch.setattr(sklent, "repo_config", sys.modules["sklent.repo_config"], raising=False)
    assert views.highlight_for(did) == (["Lid"], ".sklent.yaml")
    views.set_highlight(did, ["Base"])
    assert views.highlight_for(did) == (["Base"], "design")


def test_jobs_render_applies_the_request(settings, monkeypatch):
    did, _ = _design(settings, status="new")
    views.save_request(did, views.clean_request(preview_only=True))
    seen = {}

    class Forge:
        def __init__(self, *a, **k):
            pass

        def fetch(self, *a, **k):
            return b"solidcraft"

    def fake_render_set(local, out_dir, stem, opts, progress, **kw):
        seen["outputs"], seen["settings"] = opts.outputs, kw["settings"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "case-preview.png").write_bytes(b"x")
        return [Output("case-preview.png", "shaded", "preview", 8, 8)], {"bodies": 1}

    monkeypatch.setattr(jobs, "Forge", Forge)
    monkeypatch.setattr(jobs, "looks_like_design", lambda data, path=None: True)
    monkeypatch.setattr(jobs, "render_set", fake_render_set)
    jobs.render(did, force=True)
    assert seen["outputs"] == [] and seen["settings"]["outputs"] == []


def test_views_api(settings):
    did, folder = _design(settings, files=[{"file": "case-preview.png", "style": "shaded", "variant": "preview",
                                            "width": 8, "height": 8}])
    Image.new("RGB", (8, 8), (128, 128, 128)).save(folder / "case-preview.png")
    (folder / "report.json").write_text(json.dumps({"bodies": 2, "bounds_mm": [[0, 0, 0], [300, 10, 10]],
                                                    "views": {"hero": {"skipped": "too big"}}}))
    sets.write_json(folder, "views.json", {"parts": [{"name": "a", "size": [95, 66, 32]},
                                                     {"name": "b", "size": [300, 10, 10]}],
                                           "configurations": [], "motion_studies": ["Open"], "explode_views": 0,
                                           "bodies": ["a", "b"]})
    from sklent.app import app
    c = TestClient(app)
    d = c.get(f"/api/designs/{did}", headers=H).json()
    assert d["views"]["preview_url"].startswith(f"/api/designs/{did}/views/preview")
    fit = d["views"]["bed_fit"]
    assert fit["bed"] == "Bambu Lab X1/P1/A1" and fit["fits"] is False and fit["too_big"] == ["b"]
    assert c.get(d["views"]["preview_url"], headers=H).headers["content-type"] == "image/png"
    v = c.get(f"/api/designs/{did}/views", headers=H).json()
    assert v["notes"]["hero"]["skipped"] == "too big" and v["facts"]["motion_studies"] == ["Open"]
    assert v["bodies"] == ["a", "b"] and v["outputs"] == list(render.CORE_OUTPUTS)
    r = c.put(f"/api/designs/{did}/views/highlight", json={"names": ["b"]}, headers=H)
    assert r.json() == {"names": ["b"], "source": "design"}
    r = c.post(f"/api/designs/{did}/views/render", json={"outputs": ["gif"], "settings": {"views_hero": True}},
               headers=H)
    assert r.status_code == 200 and r.json()["request"] == {"outputs": ["gif"], "settings": {"views_hero": True}}
    assert r.json()["job"]["force"] == 1
    assert c.post(f"/api/designs/{did}/views/render", json={"outputs": ["8k"]}, headers=H).status_code == 422
    assert c.post(f"/api/designs/{did}/views/render", json={"preview_only": True}, headers=H).json()["request"] == \
        {"outputs": [], "settings": {"views_configs": False, "views_motion": False}}
    assert c.get("/api/views/beds", headers=H).json()["beds"][0]["name"] == "Bambu Lab A1 mini"
    assert c.get("/api/designs/nope/views", headers=H).status_code == 404
    s = c.put("/api/settings", json={"views_plate": True, "outputs": ["hires"]}, headers=H).json()
    assert s["views_plate"] is True and s["outputs"] == ["hires"]


def test_bed_fit_from_an_older_one_body_set(settings):
    did, folder = _design(settings)
    (folder / "report.json").write_text(json.dumps({"bodies": 1, "bounds_mm": [[0, 0, 0], [95, 66, 32]]}))
    fit = vapi.bed_fit(did, None)
    assert fit["fits"] and fit["largest"]["size"] == [95, 66, 32]


def test_mcp_tools_listed():
    import asyncio

    from sklent.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"quick_check", "render_outputs", "get_views", "set_highlight", "view_output",
            "set_views_settings"} <= names
