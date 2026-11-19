"""Integration tests for 0.2: every feature together (one render with every step, settings
round trip, viewer gate over every route and MCP tool, cross-feature hooks)."""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from sklent import features, jobs, render, steps
from sklent.render import RenderOptions, render_set
from sklent.solidcraft import SolidCraft

features.load()

H = {"Authorization": "Bearer test-token-0123456789"}


# ---------------------------------------------------------------- an omnivorous SolidCraft

def _png(path, size=(8, 8), mode="RGB"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, (128, 128, 128) if mode == "RGB" else (128, 128, 128, 255)).save(path)


class AllSC:
    """Answers every tool and command the feature steps use, with an assembly of two parts,
    a configuration table, a motion study, an exploded view and a short timeline."""

    info = [
        {"name": "Base", "visible": True, "volume_mm3": 1000.0, "area_mm2": 600.0, "closed": True,
         "bbox": {"min": [-40.0, -30.0, 0.0], "max": [40.0, 30.0, 10.0]}},
        {"name": "Lid", "visible": True, "volume_mm3": 400.0, "area_mm2": 300.0, "closed": True,
         "bbox": {"min": [-40.0, -30.0, 10.0], "max": [40.0, 30.0, 14.0]}},
    ]
    comps = [{"id": 0, "name": "root", "parent": None, "bodies": [], "children": [1, 2]},
             {"id": 1, "name": "Base", "parent": 0, "bodies": ["Base"], "children": []},
             {"id": 2, "name": "Lid", "parent": 0, "bodies": ["Lid"], "children": []}]

    def __init__(self, design: Path = Path("d.sc"), out_dir: Path = Path(".")):
        self.proc = SimpleNamespace(pid=-1)
        self.calls: list = []
        self.marker = 3

    def bodies(self):
        return [dict(b) for b in AllSC.info]

    bounds = staticmethod(SolidCraft.bounds)

    def paint(self, bodies, color, opacity):
        self.calls.append(("paint", color, opacity))

    def screenshot(self, path, camera, width, height):
        _png(path, (min(width, 64), min(height, 64)))

    def tool(self, name, **args):
        self.calls.append((name, args))
        if name == "inspect_design":
            return {"bodies": self.bodies(), "params": [{"name": "wall", "value": 2.0, "unit": "mm",
                                                         "expression": "2 mm", "model": False}],
                    "units": "mm", "features": 3}
        if name == "version":
            return {"version": "0.44.1"}
        if name == "measure":
            if args.get("names_only"):
                return {"bodies": [{"name": b["name"], "definition": b["name"]} for b in AllSC.info]}
            out = [{**b, "material": "Default", "density_g_cm3": 1.29, "mass_g": b["volume_mm3"] / 1000 * 1.29}
                   for b in AllSC.info]
            return {"bodies": out, "total": {"mass_g": sum(b["mass_g"] for b in out),
                                             "volume_mm3": 1400.0}}
        if name == "describe_command":
            raise RuntimeError("unknown command")  # no drawing.* before SolidCraft 0.45
        return {}

    def execute(self, command, **params):
        self.calls.append((command, params))
        if command == "component.list":
            return {"components": AllSC.comps}
        if command == "assembly.bom":
            return {"rows": [{"name": "Base", "qty": 1}, {"name": "Lid", "qty": 1}]}
        if command == "material.list":
            return {"materials": [{"name": "ABS Plastic", "density_g_cm3": 1.06}]}
        if command == "config.table":
            return {"rows": [{"name": "Short"}, {"name": "Long"}], "active": "Short"}
        if command == "motion.list":
            return {"studies": [{"id": 9, "name": "Open"}]}
        if command == "explode.list":
            return {"views": [{"id": 7, "name": "Author", "moves": [[2, [0, 0, 20]]]}]}
        if command == "explode.create":
            return {"id": 8}
        if command == "motion.export_animation":
            folder = Path(params["path"])
            folder.mkdir(parents=True, exist_ok=True)
            for i in range(1, 4):
                _png(folder / f"frame-{i:04d}.png")
            return {"frames": 3, "fps": 20.0}
        if command == "render.start":
            return {"job": {"session": 1, "serial": 1, "generation": 1}, "error": None}
        if command == "render.status":
            return {"progress": {"phase": "completed"}}
        if command == "render.export":
            _png(params["path"], (12, 10), "RGBA")
            return {"bytes": 1}
        if command == "inspect.section":
            return {"ok": True}
        if command == "timeline.rollback":
            pos = params["position"]
            self.marker = 3 if pos == "end" else pos
            return {"features": 3, "marker": self.marker}
        if command == "file.export":
            Path(params["path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(params["path"]).write_bytes(f"solid {params.get('format')}\n".encode() * 50)
            return {}
        return {}

    def kill(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def _encode(frames, out, *a, **k):
    Path(out).write_bytes(b"movie")


@pytest.fixture
def allsc(monkeypatch):
    monkeypatch.setattr(render, "SolidCraft", AllSC)
    for name in ("encode", "encode_gif", "encode_prores"):
        if hasattr(render, name):
            monkeypatch.setattr(render, name, _encode)
    return AllSC


def _every_setting_on() -> dict:
    """Every registered feature setting at its default, then every boolean toggle on."""
    s = jobs.get_all_settings()
    for k, (default, _) in jobs._EXTRA.items():
        if isinstance(default, bool) and k not in ("inputs_review_post", "outputs_review_share_links"):
            s[k] = True
    s["views_highlight_names"] = ["Lid"]
    return s


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg (timelapse, motion clips)")
def test_one_render_with_every_step_on(tmp_path, allsc):
    """Every feature step registered, defaults on plus every optional step forced on: the
    render finishes, every step that ran reports ok, and no two outputs share a name."""
    names = {s.name for s in steps.registered()}
    assert {"views-facts", "views-exploded", "views-section", "views-motion", "views-configs",
            "views-transparent", "views-hero", "views-plate", "specs-spec", "specs-bom", "specs-views",
            "specs-dimensions", "specs-assembly", "specs-cleanup", "timelapse", "outputs-filepack"} <= names
    settings = _every_setting_on()
    opts = RenderOptions(seconds=2, fps=24, styles=["shaded"])
    settings.update({k: v for k, v in opts.__dict__.items()})
    outputs, report = render_set(tmp_path / "case.sc", tmp_path / "out", "case", opts, processes=1,
                                 settings=settings)
    results = report["steps"]
    bad = {k: v.get("error") for k, v in results.items() if not v.get("ok")}
    assert not bad, bad
    assert set(results) == names, set(names) - set(results)
    files = [o.file for o in outputs]
    assert len(files) == len(set(files)), [f for f in files if files.count(f) > 1]
    for f in files:
        assert (tmp_path / "out" / f).exists(), f
    variants = {o.variant for o in outputs}
    # one of each area's outputs made it
    assert {"preview", "hires", "gif", "highlight", "spec-card", "timelapse", "step"} <= variants, variants


# ---------------------------------------------------------------- settings round trip

def _changed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return round(value + 0.5, 3)
    return None


def test_every_registered_setting_round_trips_through_put_settings():
    from fastapi.testclient import TestClient

    from sklent.app import app
    c = TestClient(app)
    before = c.get("/api/settings", headers=H).json()
    assert set(jobs._EXTRA) <= set(before)
    changes = {}
    for k, (default, _) in jobs._EXTRA.items():
        new = _changed(default)
        if new is not None:
            changes[k] = new
    # values the validators accept, for the text, list and range-limited settings
    presets = json.loads(json.dumps(jobs._EXTRA["outputs_presets"][0]))
    presets[0]["enabled"] = not presets[0]["enabled"]
    changes.update({
        "specs_material": "PETG", "specs_bom_file": "parts/bom.yaml",
        "inputs_public_url": "https://sklent.example.com", "outputs_licence": "CC-BY-4.0",
        "outputs_brand_text": "Studio", "outputs_brand_card_text": "Made with Sklent",
        "outputs_brand_opacity": 0.5, "outputs_brand_position": "top-left",
        "outputs_filepack_quality": "fine", "outputs_filepack_exclude": ["m3*"],
        "outputs_filepack_formats": ["step"], "outputs_marketplaces": ["printables"],
        "outputs_presets": presets, "views_master_seconds": 12.0,
        "views_beds": "Prusa MK4 250x210x220; Tiny 100x100x100", "views_bed": "Tiny",
    })
    missing = set(jobs._EXTRA) - set(changes)
    assert not missing, f"no round-trip value for {missing}"
    r = c.put("/api/settings", json=changes, headers=H)
    assert r.status_code == 200, r.text
    after = c.get("/api/settings", headers=H).json()
    for k, v in changes.items():
        got = after[k]
        assert got == v or (isinstance(v, float) and got == pytest.approx(v)), (k, v, got)
    untouched = set(jobs._EXTRA) - set(changes)
    for k in untouched:
        assert after[k] == before[k], k
    # and a render sees them
    s = jobs.get_all_settings()
    assert all(s[k] == after[k] for k in changes)


# ---------------------------------------------------------------- viewer tokens: every route, every tool

def _mcp(c, headers, method, params=None):
    return c.post("/mcp", headers={**headers, "Accept": "application/json, text/event-stream"},
                  json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def test_a_viewer_reaches_no_write_route_and_no_write_tool():
    """Walk every registered /api route and MCP tool as a viewer token: every non-GET route
    and every tool that writes, renders or reaches out answers 403; reads go through."""
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    from sklent import mcp_server
    from sklent.app import app
    from sklent.features.inputs import tokens

    v = {"Authorization": f"Bearer {tokens.create('Walker')['token']}"}
    with TestClient(app) as c:
        from sklent.api import router as core
        routes = [(m, "/api" + r.path) for rt in [core, *features.routers()] for r in rt.routes
                  if isinstance(r, APIRoute) for m in sorted(r.methods - {"HEAD", "OPTIONS"})]
        assert len(routes) > 80  # every feature's router is mounted
        writes = [(m, p) for m, p in routes if m != "GET"]
        assert len(writes) > 30
        for method, path in routes:
            url = path.replace("{", "").replace("}", "")  # any value: the gate comes first
            r = c.request(method, url, headers=v, json={})
            if method != "GET" or path.startswith("/api/tokens"):
                assert r.status_code == 403, (method, path, r.status_code)
            else:
                assert r.status_code != 403, (method, path, r.text[:200])

        tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
        assert set(tools) == mcp_server.READ_ONLY_TOOLS | mcp_server.WRITE_TOOLS, \
            set(tools) ^ (mcp_server.READ_ONLY_TOOLS | mcp_server.WRITE_TOOLS)
        assert not mcp_server.READ_ONLY_TOOLS & mcp_server.WRITE_TOOLS
        for name, t in tools.items():
            ro = bool(t.annotations and t.annotations.read_only_hint)
            assert ro == (name in mcp_server.READ_ONLY_TOOLS), name
            r = _mcp(c, v, "tools/call", {"name": name, "arguments": {}})
            if ro:
                assert r.status_code != 403, name
            else:
                assert r.status_code == 403 and "can only read" in r.json()["error"]["message"], name
        listed = _mcp(c, v, "tools/list").json()["result"]["tools"]
        assert {t["name"] for t in listed} == set(tools)
    mcp_server.mcp.session_manager._has_started = False  # the next test's lifespan starts it again


# ---------------------------------------------------------------- fixes (brief task 3)

def test_turntable_frames_every_placed_instance(tmp_path, monkeypatch):
    """3a: an assembly placing one component twice, offset: inspect_design has one body at
    its definition, measure has both placements. The turntable, stills and preview all
    frame the union of the placed boxes."""

    class ArmSC(AllSC):
        def bodies(self):
            return [{"name": "Arm", "visible": True, "bbox": {"min": [0, 0, 0], "max": [10, 10, 10]}}]

        def tool(self, name, **args):
            if name == "measure" and args.get("summary"):
                return {"bodies": [{"name": "Arm", "bbox": {"min": [100, 0, 0], "max": [110, 10, 10]}},
                                   {"name": "Arm (Arm:2)", "bbox": {"min": [-50, 0, 0], "max": [-40, 10, 10]}}]}
            if name == "measure" and args.get("names_only"):
                return {"bodies": [{"name": "Arm", "definition": "Arm"},
                                   {"name": "Arm (Arm:2)", "definition": "Arm"}]}
            return super().tool(name, **args)

    info = render.world_bodies(ArmSC(), None)
    assert [b["name"] for b in info] == ["Arm"]  # body names stay unique (painting, steps)
    assert render.placed_bounds(info) == ([-50, 0, 0], [110, 10, 10])
    monkeypatch.setattr(render, "SolidCraft", ArmSC)
    for name in ("encode", "encode_gif"):
        monkeypatch.setattr(render, name, _encode)
    monkeypatch.setattr(steps, "_STEPS", {})
    _, report = render_set(tmp_path / "arm.sc", tmp_path / "out", "arm", RenderOptions(seconds=2, fps=24),
                           processes=1)
    assert report["bounds_mm"] == ([-50, 0, 0], [110, 10, 10])


def test_world_bodies_falls_back_to_the_instance_name_pattern():
    class NoNamesSC(AllSC):
        def bodies(self):
            return [{"name": "Leg", "visible": True, "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}}]

        def tool(self, name, **args):
            if name == "measure" and args.get("summary"):
                return {"bodies": [{"name": "Leg", "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}},
                                   {"name": "Leg (Leg:3)", "bbox": {"min": [5, 0, 0], "max": [6, 1, 1]}},
                                   {"name": "Stray", "bbox": {"min": [0, 9, 0], "max": [1, 10, 1]}}]}
            if name == "measure":
                raise RuntimeError("names_only not here")
            return super().tool(name, **args)

    info = render.world_bodies(NoNamesSC(), None)
    assert render.placed_bounds(info) == ([0, 0, 0], [6, 10, 1])


def _design_row(settings, source_url="https://github.com/o/r", files=None, blob="b" * 40, commit="c" * 40,
                status="rendered"):
    from sklent import db
    source = jobs.add_source(source_url, auto_render=False)
    did = db.new_id()
    folder = settings.renders_dir / did / blob[:12]
    folder.mkdir(parents=True)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha, commit_sha,"
            " status, render_dir, files, rendered_sha, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [did, source["id"], "o", "r", source["ref"] or "main", "case.sc",
             "https://github.com/o/r/blob/c/case.sc", blob, commit, status, str(folder),
             json.dumps(files or []), blob, db.now()])
    return did, folder, source


def test_latest_set_commit_sha_is_a_commit_never_the_blob(settings):
    """3b: a set from before revisions (no set.json) gives the scanned commit, not the blob."""
    from sklent import sets
    from sklent.features.outputs import common
    did, _, _ = _design_row(settings, blob="b" * 40, commit="c" * 40)
    s = sets.latest_set(did)
    assert s["commit_sha"] == "c" * 40
    assert common.commit_of(jobs.get_design(did), s) == "c" * 40


def test_cancel_ids_never_outlive_their_job():
    """3h: cancel requests are cleared when a job ends, and never kept for a job this
    process isn't running."""
    from sklent import db
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO jobs (kind, status, created_at) VALUES ('scan', 'running', ?)", [db.now()])
        jid = cur.lastrowid
    jobs.cancel(jid)  # running, but not by this process's worker
    assert jid not in jobs._cancelled
    with db.connect() as conn:
        jid2 = conn.execute("INSERT INTO jobs (kind, status, created_at) VALUES ('scan', 'running', ?)",
                            [db.now()]).lastrowid
    jobs._running["job"] = jid2
    try:
        jobs.cancel(jid2)
        assert jid2 in jobs._cancelled
    finally:
        jobs._running["job"] = None
    jobs._cancelled.add(12345)  # a leftover from anywhere
    jobs.run_job({"id": jid2, "kind": "scan", "source_id": "nope", "design_id": None, "force": 0})
    assert not jobs._cancelled


class _FakeKist:
    enabled = True

    def __init__(self):
        self.folders, self.uploads = [], []

    def ensure_folder(self, path):
        self.folders.append(list(path))
        return "f1"

    def upload(self, path, folder_id=None, tags=(), notes="", source_url=None):
        self.uploads.append({"file": Path(path).name, "folder": folder_id, "tags": list(tags)})
        return {"id": f"i{len(self.uploads)}"}

    def file_version(self, new, old):
        pass

    def trash(self, item_id):
        pass


def _fake_render(monkeypatch, kist):
    class Forge:
        def __init__(self, *a, **k):
            pass

        def fetch(self, *a, **k):
            return b"solidcraft"

        def _get(self, *a, **k):
            raise RuntimeError("offline")

    def fake_render_set(local, out_dir, stem, opts, progress, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        _png(out_dir / f"{stem}-shaded-social-8.png")
        return [render.Output(f"{stem}-shaded-social-8.png", "shaded", "social", 8, 8)], {"bodies": 1}

    monkeypatch.setattr(jobs, "Forge", Forge)
    monkeypatch.setattr(jobs, "Kist", lambda: kist)
    monkeypatch.setattr(jobs, "looks_like_design", lambda data, path=None: True)
    monkeypatch.setattr(jobs, "render_set", fake_render_set)


@pytest.mark.parametrize("url,where,tag", [
    ("https://github.com/o/r/pull/7", "pr-7", "ref:pr-7"),
    ("https://github.com/o/r/tree/dev", "@dev", "ref:dev"),
    ("https://github.com/o/r", None, None),
])
def test_pr_and_branch_renders_file_into_their_own_kist_folder(settings, monkeypatch, url, where, tag):
    """3d: PR and branch renders go to `<design>/pr-<n>` or `<design>/@<branch>` in Kist with a
    `ref:` tag, through the same set lifecycle (rev: tags, versions) as the default branch."""
    kist = _FakeKist()
    _fake_render(monkeypatch, kist)
    did, _, _ = _design_row(settings, url, status="new")
    jobs.render(did, force=True)
    folder = kist.folders[-1]
    assert folder[-1] == (where or "case") and (where is None or folder[-2] == "case")
    tags = kist.uploads[0]["tags"]
    assert any(t.startswith("rev:") for t in tags)
    assert ([t for t in tags if t.startswith("ref:")] == [tag]) if tag else not any(t.startswith("ref:") for t in tags)


# ---------------------------------------------------------------- CSS across every area's sheet

WEB = Path(__file__).resolve().parents[1] / "sklent" / "web"
CSS_DIR = WEB / "css"
TOKEN_SHEETS = {"kist-tokens.css", "sk-tokens.css"}


def _sheets() -> dict[str, str]:
    import re
    return {str(p.relative_to(CSS_DIR)): re.sub(r"/\*.*?\*/", "", p.read_text(), flags=re.S)
            for p in sorted(CSS_DIR.rglob("*.css")) if p.name not in TOKEN_SHEETS}


def _selectors(css: str):
    """Every selector of every rule (at-rule preludes skipped, nested blocks walked)."""
    import re
    for prelude in re.findall(r"([^{}]+)\{", css):
        prelude = prelude.strip()
        if not prelude or prelude.startswith("@"):
            continue
        for sel in prelude.split(","):
            yield sel.strip()


def _compounds(selector: str):
    import re
    sel = re.sub(r"\([^()]*\)", "", selector)  # :not(.x), :is(...) arguments aside
    sel = re.sub(r"\[[^\]]*\]", "", sel)
    for part in re.split(r"\s*[\s>+~]\s*", sel):
        if part:
            yield part


def test_css_collisions_between_area_sheets():
    """A bare `.name` rule in one sheet also styles every `.x.name` compound in another (all
    sheets are global): flag a class that is bare in one sheet and a modifier elsewhere.
    (Python port of Kist's web/tests/css-collisions.test.ts.)"""
    import re
    bare: dict[str, set[str]] = {}
    modifier: dict[str, set[str]] = {}
    for sheet, css in _sheets().items():
        for sel in _selectors(css):
            for i, comp in enumerate(_compounds(sel)):
                classes = re.findall(r"\.(-?[_a-zA-Z][\w-]*)", comp)
                rest = re.sub(r"\.(-?[_a-zA-Z][\w-]*)|::?[\w-]+", "", comp).strip()
                if i == 0 and len(classes) == 1 and not rest:  # `.name` with nothing above it
                    bare.setdefault(classes[0], set()).add(sheet)
                elif len(classes) > 1:
                    for c in classes[1:]:
                        modifier.setdefault(c, set()).add(sheet)
    clashes = sorted(f".{c}: bare in {sorted(bare[c])}, a modifier in {sorted(modifier[c] - bare[c])}"
                     for c in set(bare) & set(modifier) if modifier[c] - bare[c])
    assert not clashes, "\n".join(clashes)


def test_feature_sheets_use_their_area_prefix():
    """An area sheet's rules start from its own sk-<area>-… class (or a D seam element),
    so they can't reach into another area's markup."""
    import re
    for p in sorted((CSS_DIR / "features").glob("*.css")):
        area = p.stem
        css = re.sub(r"/\*.*?\*/", "", p.read_text(), flags=re.S)
        loose = []
        for sel in _selectors(css):
            comps = list(_compounds(sel))
            if not comps or comps[0].startswith((":root", "html", "body", "@", "from", "to")) or "%" in comps[0]:
                continue
            if f"sk-{area}" not in sel and f"sk-{area[:3]}" not in sel:
                loose.append(sel)
        assert not loose, (p.name, loose[:10])


def _themes():
    import importlib.util
    spec = importlib.util.spec_from_file_location("tc", Path(__file__).parent / "test_contrast.py")
    tc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tc)
    return tc, tc.parse_themes(tc.TOKENS.read_text())


def test_feature_text_on_its_own_background_passes_contrast():
    """Every rule in an area sheet that sets both a text colour and a background from
    tokens passes 4.5:1 in all three themes (3:1 for the ink-faint 'dim' tokens)."""
    import re
    tc, themes = _themes()
    bad = []
    for sheet, css in _sheets().items():
        if not sheet.startswith("features/"):
            continue
        for body in re.findall(r"\{([^{}]*)\}", css):
            fg = re.search(r"(?<![-\w])color:\s*var\(--([\w-]+)\)\s*(;|$)", body)
            bg = re.search(r"background(?:-color)?:\s*var\(--([\w-]+)\)\s*(;|$)", body)
            if not (fg and bg):
                continue
            for theme in tc.THEMES:
                t = themes[theme]
                a, b = t.get(fg.group(1)), t.get(bg.group(1))
                if not (a and b and a.startswith("#") and b.startswith("#")):
                    continue
                need = 3.0 if "dim" in fg.group(1) or "faint" in fg.group(1) else 4.5
                r = tc.contrast(a, b)
                if r < need:
                    bad.append(f"{sheet} {theme}: --{fg.group(1)} on --{bg.group(1)} = {r:.2f}")
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- cross-feature hooks (brief task 4)

CORE = {"preview": "png", "1080p": "mp4", "reel": "mp4", "discord": "mp4", "gif": "gif", "social": "png",
        "hires": "png"}
V_VARIANTS = {"exploded": "png", "explode-anim": "mp4", "section": "png", "config-lineup": "png",
              "config-1": "png", "highlight": "png", "highlight-turntable": "mp4", "motion-open": "mp4",
              "transparent": "png", "hero": "png", "plate": "png", "master-4k": "mp4", "frames-zip": "zip",
              "prores": "mov", "preset-push-in": "mp4"}
S_VARIANTS = {"spec-card": "png", "bom-sheet": "png", "views-sheet": "png", "views-sheet-pdf": "pdf",
              "dimensions": "png", "assembly-1": "png"}
R_VARIANTS = {"timelapse": "mp4", "timelapse-gif": "gif"}
STILL_EXT = {"png"}


def _mp4(path: Path) -> None:
    import subprocess
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x36:d=1:r=24",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


@pytest.fixture
def every_variant(settings, monkeypatch):
    """A rendered design whose set holds one file of every agreed variant name, plus S's
    spec.json and bom.json, and a .sklent.yaml-style repo config."""
    variants = {**CORE, **V_VARIANTS, **S_VARIANTS, **R_VARIANTS}
    files = []
    did, folder, source = _design_row(settings)
    movie = folder / "_movie.mp4"
    _mp4(movie)
    for i, (variant, ext) in enumerate(variants.items()):
        name = f"case-{variant}.{ext}"
        if ext == "png":
            Image.new("RGB", (96, 64), (128 + i % 40, 128, 128)).save(folder / name)
        elif ext in ("mp4", "mov"):
            shutil.copyfile(movie, folder / name)
        elif ext == "gif":
            Image.new("RGB", (32, 18), (128, 128, 128)).save(folder / name)
        elif ext == "pdf":
            Image.new("RGB", (32, 18), (255, 255, 255)).save(folder / name, "PDF")
        else:
            (folder / name).write_bytes(b"PK\x05\x06" + b"\0" * 18)
        style = "shaded" if variant not in ("highlight", "highlight-turntable") else "highlight"
        files.append({"file": name, "style": style, "variant": variant, "width": 96 if ext == "png" else 64,
                      "height": 64 if ext == "png" else 36})
    movie.unlink()
    (folder / "spec.json").write_text(json.dumps({"bodies": 2, "mass_g": 30.6, "material": "PETG",
                                                  "bounds_mm": [[0, 0, 0], [95, 66, 32]], "licence": "MIT"}))
    (folder / "bom.json").write_text(json.dumps({"rows": [{"name": "Lid", "qty": 1}, {"name": "M3 screw", "qty": 4}]}))
    (folder / "report.json").write_text(json.dumps({"bodies": 2, "bounds_mm": [[0, 0, 0], [95, 66, 32]],
                                                    "options": {"fps": 24}}))
    from sklent import db
    with db.connect() as conn:
        db.update(conn, "designs", did, files=files)
    cfg = {"title": "Pi case", "licence": "CERN-OHL-S-2.0", "material": "PETG", "highlight": ["Lid"],
           "bom": "parts/bom.yaml", "steps": [{"title": "Base", "parts": ["Base"]}]}
    import sklent.repo_config as rc
    monkeypatch.setattr(rc, "get", lambda design_id: cfg if design_id == did else {})
    return SimpleNamespace(id=did, folder=folder, source=source, files=files, variants=variants, cfg=cfg)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_every_variant_reaches_the_page_the_pack_and_the_detail_sheet(every_variant):
    """O iterates set["files"] by variant with no hard-coded list: every still V, S and R
    make shows up in the project page and the listing pack, and every file of every
    variant is listed (with a working URL) on the design the detail sheet draws."""
    import zipfile

    from fastapi.testclient import TestClient

    from sklent.app import app
    from sklent.features.outputs import listing, page
    ev = every_variant
    stills = {v for v, ext in ev.variants.items() if ext in STILL_EXT}

    c = TestClient(app)
    d = c.get(f"/api/designs/{ev.id}", headers=H).json()
    assert {f["variant"] for f in d["files"]} == set(ev.variants)
    for f in d["files"]:
        assert c.get(f["url"], headers=H).status_code == 200, f["file"]

    built = page.build_design(ev.id, include_files=False)
    exports = Path(ev.folder) / "exports" if (Path(ev.folder) / "exports").is_dir() else None
    z = zipfile.ZipFile(next(Path(ev.folder).rglob(built["file"])))
    html = z.read(next(n for n in z.namelist() if n.endswith("/index.html"))).decode()
    renders = [n for n in z.namelist() if "/assets/render-" in n]
    assert len(renders) == len(stills - {"hires"})  # the page drops hires: the square is the same view
    import html as htmllib
    text_html = htmllib.unescape(html)
    shown = {v for v in stills if f"CAD render · {v}" in text_html}
    assert len(shown) == len(stills - {"hires"}) - 1  # all but the hero, which heads the page
    assert any(n.endswith("spec.json") for n in z.namelist())  # S's spec.json read by O's page
    assert "Pi case" in html  # title from the repo config

    pack = listing.build(ev.id, "printables")
    packed = {f.get("variant") for f in pack["files"] if f.get("kind") == "render"}
    assert stills - {"hires"} <= packed, stills - {"hires"} - packed
    text = listing.listing_text(ev.id, name="printables")
    assert "30.6 g (PETG)" in text and "CERN-OHL-S-2.0" in text  # spec.json + licence via repo_config
    assert exports is None or exports.is_dir()


def test_repo_config_reaches_views_specs_and_outputs(every_variant):
    """One `.sklent.yaml` (P's repo_config.get) feeds V's highlight, S's material, licence,
    bom file and assembly steps, and O's title and licence."""
    from sklent.features.outputs import common
    from sklent.features.specs import meta
    from sklent.features.views import highlight_for
    ev = every_variant
    assert highlight_for(ev.id) == (["Lid"], ".sklent.yaml")
    cfg = meta.config(ev.id)
    assert cfg.get("material") == "PETG" and cfg.get("licence") == "CERN-OHL-S-2.0"
    assert cfg.get("bom") == "parts/bom.yaml" and cfg.get("steps")[0]["title"] == "Base"
    m = common.meta(ev.id)
    assert (m["title"], m["licence"]) == ("Pi case", "CERN-OHL-S-2.0")
    assert m["from"]["title"] == "repo"


def test_spec_json_reaches_the_design_json_for_the_title_block(every_variant):
    from fastapi.testclient import TestClient

    from sklent.app import app
    d = TestClient(app).get(f"/api/designs/{every_variant.id}", headers=H).json()
    assert d["spec"]["mass_g"] == 30.6 and d["spec"]["material"] == "PETG"
    detail = (WEB / "js" / "detail.js").read_text()
    assert "d.spec" in detail or "design.spec" in detail  # D's title block reads it


def test_review_comment_links_the_kist_share_link(every_variant):
    """O's share_link(design_id) is what P's review comment links the still to."""
    from sklent import db
    from sklent.features.inputs import refs
    from sklent.features.outputs import share_link
    ev = every_variant
    assert share_link(ev.id) is None
    plain = refs.review_comment(ev.source["id"], "https://sklent.example.com")
    with db.connect() as conn:
        conn.execute("INSERT INTO outputs_review (id, scope, target_id, share_url, created_at) VALUES (?,?,?,?,?)",
                     ["r1", "design", ev.id, "https://kist.example.com/s/abc", db.now()])
    assert share_link(ev.id) == "https://kist.example.com/s/abc"
    linked = refs.review_comment(ev.source["id"], "https://sklent.example.com")
    md = linked["markdown"] if isinstance(linked, dict) else linked
    assert "https://kist.example.com/s/abc" in md
    assert "https://kist.example.com/s/abc" not in (plain["markdown"] if isinstance(plain, dict) else plain)
