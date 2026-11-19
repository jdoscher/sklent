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
