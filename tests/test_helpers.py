"""0.2.1: render control (GPU / software / off, GPU process cap, quiet hours), the host's
claim gate, helper tokens, and the render helper protocol and client."""

import io
import json
import tarfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sklent import auth, db, features, jobs, render, sets, solidcraft
from sklent.features.helpers import client as hclient
from sklent.features.helpers import control, server
from sklent.features.inputs import tokens
from sklent.render import Output

features.load()

H = {"Authorization": "Bearer test-token-0123456789"}
BLOB1, BLOB2 = "1" * 40, "2" * 40
C1 = "a" * 40


# ---------------------------------------------------------------- fixtures


def _design(blob=BLOB1, commit=C1, path="parts/case.sc") -> str:
    src = jobs.add_source("https://github.com/o/r")
    did = db.new_id()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha, commit_sha,"
            " status, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                did,
                src["id"],
                "o",
                "r",
                "main",
                path,
                f"https://github.com/o/r/blob/x/{path}",
                blob,
                commit,
                "new",
                db.now(),
            ],
        )
    return did


class FakeForge:
    def __init__(self, *a, **k):
        pass

    def fetch(self, *a, **k):
        return b"solidcraft design bytes"

    def _get(self, *a, **k):
        raise RuntimeError("offline")


class FakeKist:
    enabled = True

    def __init__(self):
        self.uploads, self.versions = [], []

    def ensure_folder(self, path):
        return "f1"

    def upload(self, path, folder_id=None, tags=(), notes="", source_url=None):
        self.uploads.append({"file": Path(path).name, "tags": list(tags), "bytes": Path(path).read_bytes()})
        return {"id": f"i{len(self.uploads)}"}

    def file_version(self, new, old):
        self.versions.append((new, old))

    def trash(self, item_id):
        pass


def _png(path: Path, shade: int = 200):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 9), (shade, shade, shade)).save(path)


def _fake_render_set(state):
    def fake(local, out_dir, stem, opts, progress, **kw):
        state.setdefault("calls", []).append({"local": Path(local), "kw": kw})
        out_dir.mkdir(parents=True, exist_ok=True)
        progress(0.5, "frames")
        _png(out_dir / f"{stem}-shaded-hires-16x9.png", state.get("shade", 200))
        return (
            [Output(f"{stem}-shaded-hires-16x9.png", "shaded", "hires", 16, 9)],
            {
                "bodies": 1,
                "options": {"palette": "cool-grey"},
                "renderer": kw.get("renderer") or "gpu",
                "host": kw.get("host") or "host",
            },
        )

    return fake


@pytest.fixture
def fake(monkeypatch):
    kist = FakeKist()
    state: dict = {"kist": kist}
    monkeypatch.setattr(jobs, "Forge", FakeForge)
    monkeypatch.setattr(jobs, "Kist", lambda: kist)
    monkeypatch.setattr(jobs, "looks_like_design", lambda data, path=None: True)
    monkeypatch.setattr(jobs, "render_set", _fake_render_set(state))
    monkeypatch.setattr(render, "render_set", _fake_render_set(state))
    monkeypatch.setattr(server, "host_version", lambda: "0.44.1")
    monkeypatch.setattr(solidcraft, "version", lambda: "0.44.1")
    monkeypatch.setattr(
        solidcraft, "gpu_info", lambda renderer=None: {"renderer": renderer or "gpu", "adapter": "Fake"}
    )
    return state


@pytest.fixture
def api():
    return TestClient(app())


def app():
    from sklent.app import app as a

    return a


def _helper_token(name="gpu-box"):
    return tokens.create(name, "helper")["token"]


def _claim_body(name="gpu-box", version="0.44.1", **kw):
    return {"name": name, "solidcraft_version": version, "renderer": "gpu", "gpu": "Fake GPU", "mem_gb": 15.0, **kw}


def _stage_tar(
    files: dict[str, bytes],
    outputs: list[dict],
    manifest_files: dict | None = None,
    extra: list[tarfile.TarInfo] | None = None,
) -> bytes:
    buf = io.BytesIO()
    manifest = {
        "outputs": outputs,
        "files": manifest_files if manifest_files is not None else {k: len(v) for k, v in files.items()},
    }
    with tarfile.open(fileobj=buf, mode="w") as tar:
        data = json.dumps(manifest).encode()
        info = tarfile.TarInfo(server.MANIFEST)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        for info in extra or []:
            tar.addfile(info)
    return buf.getvalue()


def _good_result(stem="case", host="gpu-box"):
    png = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (16, 9), (90, 90, 90)).save(png, "PNG")
    files = {
        f"{stem}-shaded-hires-16x9.png": png.getvalue(),
        "report.json": json.dumps(
            {"bodies": 1, "options": {"palette": "cool-grey"}, "renderer": "gpu", "host": host}
        ).encode(),
        "views.json": b"{}",
    }
    outputs = [
        {"file": f"{stem}-shaded-hires-16x9.png", "style": "shaded", "variant": "hires", "width": 16, "height": 9}
    ]
    return files, outputs


def _seen(name="gpu-box", minutes_ago=0):
    t = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO helpers (name, first_seen, last_seen) VALUES (?,?,?)", [name, t, t])


def _age(job_id, minutes):
    t = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET created_at = ? WHERE id = ?", [t, job_id])


# ---------------------------------------------------------------- settings


def test_rendering_settings_defaults_and_validation(monkeypatch, settings):
    s = jobs.get_all_settings()
    assert s["render_device"] == "gpu" and s["render_gpu_processes"] == 1
    assert s["render_quiet_hours"] == "" and s["render_quiet_mode"] == "wait"
    assert s["helpers_fallback_minutes"] == 30 and s["helpers_require_same_solidcraft"] is True
    assert s["helpers_max_attempts"] == 2 and s["helpers_lease_seconds"] == 300 and s["helpers_seen_window"] == 10
    monkeypatch.setenv("SK_RENDERER", "software")  # the env default, until the UI sets one
    from sklent import config

    config.get_settings.cache_clear()
    assert jobs.get_all_settings()["render_device"] == "software"
    jobs.set_options({"render_device": "off", "render_quiet_hours": " 7:05 - 22:00 "})
    s = jobs.get_all_settings()
    assert s["render_device"] == "off" and s["render_quiet_hours"] == "07:05-22:00"
    for bad in (
        {"render_device": "cuda"},
        {"render_quiet_hours": "late"},
        {"render_quiet_hours": "25:00-01:00"},
        {"render_quiet_hours": "07:00-07:00"},
        {"render_quiet_mode": "nap"},
        {"render_gpu_processes": 0},
        {"helpers_fallback_minutes": -1},
        {"helpers_max_attempts": 1.5},
    ):
        with pytest.raises(ValueError):
            jobs.set_options(bad)


def test_a_repo_config_cant_change_server_side_render_settings(settings):
    from sklent.repo_config import clean_settings

    clean, errors = clean_settings({"helpers_require_same_solidcraft": False, "views_exploded": True})
    assert clean == {"views_exploded": True}
    assert errors and "helpers_require_same_solidcraft" in errors[0]


@pytest.mark.parametrize(
    "hours,hhmm,active",
    [
        ("22:00-07:00", (23, 30), True),
        ("22:00-07:00", (6, 59), True),
        ("22:00-07:00", (7, 0), False),
        ("22:00-07:00", (12, 0), False),
        ("09:00-17:00", (9, 0), True),
        ("09:00-17:00", (17, 0), False),
        ("", (3, 0), False),
        ("nonsense", (3, 0), False),
    ],
)
def test_quiet_hours_wrap_past_midnight(hours, hhmm, active):
    now = datetime(2026, 11, 19, *hhmm).astimezone()
    assert control.quiet_active(hours, now) is active


# ---------------------------------------------------------------- the host's gate


def test_host_plan_follows_device_quiet_hours_and_helpers(settings):
    p = control.host_plan()
    assert p["take"] == "all" and p["renderer"] == "gpu" and p["processes"] == 1 and p["reason"] is None
    jobs.set_options({"render_gpu_processes": 2})
    assert control.host_plan()["processes"] == 2
    jobs.set_options({"render_device": "software"})
    p = control.host_plan()
    assert p["renderer"] == "software" and p["processes"] == settings.render_processes
    jobs.set_options({"render_device": "off"})
    assert control.host_plan()["take"] == "none"
    jobs.set_options({"render_device": "gpu"})

    now = datetime(2026, 11, 19, 23, 0).astimezone()
    jobs.set_options({"render_quiet_hours": "22:00-07:00"})
    p = control.host_plan(now)
    assert p["take"] == "none" and p["reason"] == "Quiet hours: helpers only"
    jobs.set_options({"render_quiet_mode": "software"})
    p = control.host_plan(now)
    assert p["take"] == "all" and p["renderer"] == "software" and "software" in p["reason"]
    assert control.host_plan(datetime(2026, 11, 19, 12, 0).astimezone())["renderer"] == "gpu"
    jobs.set_options({"render_quiet_hours": ""})

    _seen("gpu-box", minutes_ago=2)  # a helper around: the host waits for the fallback
    p = control.host_plan()
    assert p["take"] == "older" and p["helper_seen"]
    jobs.set_options({"helpers_fallback_minutes": 0})
    assert control.host_plan()["take"] == "none"
    jobs.set_options({"helpers_fallback_minutes": 30})
    _seen("gpu-box", minutes_ago=11)  # not seen within helpers_seen_window (10 min)
    assert control.host_plan()["take"] == "all"


def test_a_skipped_render_doesnt_block_the_scans_behind_it(settings):
    did = _design()
    r = jobs.enqueue("render", design_id=did)
    s = jobs.enqueue("scan", source_id=jobs.get_design(did)["source_id"])
    _seen("gpu-box")
    job = jobs._claim()
    assert job["id"] == s["id"] and job["kind"] == "scan"  # the render waits for a helper
    assert jobs._claim() is None
    _age(r["id"], 31)  # older than helpers_fallback_minutes: the host takes it
    assert jobs._claim()["id"] == r["id"]


def test_fallback_of_one_minute_takes_the_render_after_a_minute(settings):
    did = _design()
    r = jobs.enqueue("render", design_id=did)
    _seen("gpu-box")
    jobs.set_options({"helpers_fallback_minutes": 1})
    assert jobs._claim() is None
    _age(r["id"], 1)
    assert jobs._claim()["id"] == r["id"]


def test_quiet_hours_in_wait_mode_and_device_off_keep_the_host_from_rendering(settings, monkeypatch):
    did = _design()
    jobs.enqueue("render", design_id=did)
    monkeypatch.setattr(control, "local_now", lambda: datetime(2026, 11, 19, 23, 0).astimezone())
    jobs.set_options({"render_quiet_hours": "22:00-07:00"})
    assert jobs._claim() is None  # no helper seen, but quiet hours
    jobs.set_options({"render_quiet_hours": "", "render_device": "off"})
    assert jobs._claim() is None
    jobs.set_options({"render_device": "gpu"})
    assert jobs._claim()["kind"] == "render"


def test_a_design_never_renders_twice_at_once(settings):
    did = _design()
    a = jobs.enqueue("render", design_id=did)
    assert jobs._claim()["id"] == a["id"]
    jobs.enqueue("render", design_id=did, force=True)  # queued behind the running one
    assert jobs._claim() is None


def test_host_render_uses_the_plan_renderer_and_process_cap(fake, settings):
    did = _design()
    jobs.set_options({"render_gpu_processes": 1})
    job = jobs.enqueue("render", design_id=did)
    plan = jobs.host_plan()
    claimed = jobs._claim(plan)
    jobs.run_job(claimed, plan)
    kw = fake["calls"][-1]["kw"]
    assert kw["renderer"] == "gpu" and kw["processes"] == 1
    assert jobs.get_design(did)["status"] == "rendered"
    assert json.loads((sets.latest_set(did)["dir"] / "report.json").read_text())["renderer"] == "gpu"
    assert jobs.get_design(did)["files"] and job


def test_db_init_keeps_a_helpers_running_job(settings):
    did = _design()
    j = jobs.enqueue("render", design_id=did)
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET status = 'running', helper = 'gpu-box' WHERE id = ?", [j["id"]])
        conn.execute("UPDATE designs SET status = 'rendering' WHERE id = ?", [did])
    db.init()
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE id = ?", [j["id"]]).fetchone()[0] == "running"
    assert jobs.get_design(did)["status"] == "rendering"


# ---------------------------------------------------------------- tokens


def test_helper_tokens_have_their_own_scope_and_prefix(settings):
    t = tokens.create("gpu-box", "helper")
    assert t["token"].startswith("skh") and t["scope"] == "helper"
    assert tokens.lookup(t["token"])["scope"] == "helper"
    assert tokens.list_tokens()[0]["scope"] == "helper"
    with pytest.raises(ValueError):
        tokens.create("x", "root")


def test_tokens_made_before_scopes_become_viewer_tokens(tmp_path, monkeypatch):
    import sqlite3

    from sklent import config

    data = tmp_path / "old"
    data.mkdir()
    conn = sqlite3.connect(data / "sklent.db")
    conn.executescript("""CREATE TABLE inputs_viewer_tokens (id TEXT PRIMARY KEY, name TEXT NOT NULL,
        hash TEXT NOT NULL UNIQUE, hint TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, source_id TEXT,
        design_id TEXT, force INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued',
        progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '', error TEXT, created_at TEXT NOT NULL,
        started_at TEXT, finished_at TEXT);""")
    conn.execute(
        "INSERT INTO inputs_viewer_tokens VALUES ('t1', 'Old', ?, 'skv…', '2026-01-01', NULL, NULL)",
        [tokens._hash("skv" + "a" * 32)],
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("SK_DATA_DIR", str(data))
    config.get_settings.cache_clear()
    db.init()
    assert tokens.lookup("skv" + "a" * 32) == {"id": "t1", "name": "Old", "scope": "viewer"}
    with db.connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}
    assert {"helper", "attempts"} <= cols


def test_a_helper_token_reaches_only_the_helper_protocol(settings, api):
    """Walk every /api route and every MCP tool with a helper token: only claim and the
    job routes get past the gate; every other route and all of MCP answer 403."""
    from fastapi.routing import APIRoute

    from sklent import mcp_server
    from sklent.api import router as core

    h = {"Authorization": f"Bearer {_helper_token()}"}
    routes = [
        (m, "/api" + r.path)
        for rt in [core, *features.routers()]
        for r in rt.routes
        if isinstance(r, APIRoute)
        for m in sorted(r.methods - {"HEAD", "OPTIONS"})
    ]
    allowed = [(m, p) for m, p in routes if auth.helper_may_call(p)]
    assert {p for _, p in allowed} == {
        "/api/helpers/claim",
        "/api/helpers/jobs/{job_id}/inputs.tar",
        "/api/helpers/jobs/{job_id}/repo-file",
        "/api/helpers/jobs/{job_id}/progress",
        "/api/helpers/jobs/{job_id}/fail",
        "/api/helpers/jobs/{job_id}/result",
    }
    for method, path in routes:
        url = path.replace("{", "").replace("}", "")
        r = api.request(method, url, headers=h, json={})
        if path in auth.PUBLIC_PATHS:
            continue
        if (method, path) in allowed:
            assert r.status_code != 403, (method, path, r.text[:200])
        else:
            assert r.status_code == 403, (method, path, r.status_code)
    assert api.get("/api/helpers", headers=h).status_code == 403  # the registry is the admin's
    for name in [t.name for t in __import__("asyncio").run(mcp_server.mcp.list_tools())]:
        r = api.post(
            "/mcp",
            headers={**h, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {}}},
        )
        assert r.status_code == 403, name
    r = api.post(
        "/mcp",
        headers={**h, "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert r.status_code == 403
    assert api.get("/api/whoami", headers=h).status_code == 403
    # a cookie or a token query don't widen it
    assert api.get("/api/designs", params={"token": h["Authorization"][7:]}).status_code == 403


def test_viewers_cant_reach_helpers_or_list_helpers(settings, api):
    v = {"Authorization": f"Bearer {tokens.create('Class')['token']}"}
    assert api.get("/api/helpers", headers=v).status_code == 403
    assert api.post("/api/helpers/claim", headers=v, json=_claim_body()).status_code == 403
    assert api.get("/api/render-state", headers=v).status_code == 200
    r = api.post(
        "/mcp",
        headers={**v, "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_helpers", "arguments": {}}},
    )
    assert r.status_code == 403 and "admin" in r.json()["error"]["message"]


# ---------------------------------------------------------------- protocol


def test_claim_render_upload_files_the_set_like_a_host_render(fake, settings, api):
    did = _design()
    h = {"Authorization": f"Bearer {_helper_token()}"}
    assert api.post("/api/helpers/claim", headers=h, json=_claim_body()).status_code == 204
    job = jobs.enqueue("render", design_id=did)
    scan = jobs.enqueue("scan", source_id=jobs.get_design(did)["source_id"])
    r = api.post("/api/helpers/claim", headers=h, json=_claim_body())
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["job"]["id"] == job["id"] and c["job"]["helper"] == "gpu-box" and c["lease_s"] == 300
    assert c["design"]["id"] == did and c["design"]["provider"] == "github"
    assert c["settings_snapshot"]["palette"] == "cool-grey" and "render_device" in c["settings_snapshot"]
    assert c["design_file"] == "repo/parts/case.sc" and c["stem"] == "case"
    with db.connect() as conn:  # scans stay on the host
        assert conn.execute("SELECT status FROM jobs WHERE id = ?", [scan["id"]]).fetchone()[0] == "queued"
    assert jobs.get_design(did)["status"] == "rendering"

    tar = api.get(f"/api/helpers/jobs/{job['id']}/inputs.tar", headers=h, params={"name": "gpu-box"})
    assert tar.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(tar.content)) as t:
        assert t.getnames() == ["repo/parts/case.sc"]
        assert t.extractfile("repo/parts/case.sc").read() == b"solidcraft design bytes"
    assert not list(settings.work_dir.glob("inputs-*.tar"))  # the temporary tar is gone

    p = api.post(
        f"/api/helpers/jobs/{job['id']}/progress",
        headers=h,
        params={"name": "gpu-box"},
        json={"fraction": 0.5, "message": "frame 10/20"},
    )
    assert p.json() == {"cancel": False}
    j = api.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert j["progress"] == 0.45 and j["message"] == "frame 10/20" and j["helper"] == "gpu-box"
    # another helper can't report on it
    assert api.post(
        f"/api/helpers/jobs/{job['id']}/progress", headers=h, params={"name": "other"}, json={"fraction": 0.6}
    ).json() == {"cancel": True}

    files, outputs = _good_result()
    up = api.post(
        f"/api/helpers/jobs/{job['id']}/result", headers=h, params={"name": "gpu-box"}, content=_stage_tar(files, outputs)
    )
    assert up.status_code == 200, up.text
    assert up.json()["done"] and "filed 1 in Kist" in up.json()["message"]
    d = jobs.get_design(did)
    assert d["status"] == "rendered" and d["rendered_sha"] == BLOB1 and d["files"][0]["variant"] == "hires"
    folder = sets.latest_set(did)["dir"]
    assert (folder / "views.json").is_file() and (folder / "case-shaded-hires-16x9.png").is_file()
    report = json.loads((folder / "report.json").read_text())
    assert report["host"] == "gpu-box" and report["renderer"] == "gpu"
    assert fake["kist"].uploads[0]["file"] == "case-shaded-hires-16x9.png"
    assert "rev:" + C1[:10] in fake["kist"].uploads[0]["tags"]
    j = api.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert j["status"] == "done" and j["helper"] == "gpu-box"
    helpers = api.get("/api/helpers", headers=H).json()
    assert helpers[0]["name"] == "gpu-box" and helpers[0]["jobs_done"] == 1 and helpers[0]["active"]
    assert helpers[0]["version"] == "0.44.1" and helpers[0]["gpu"] == "Fake GPU" and helpers[0]["current_job"] is None
    assert not (settings.work_dir / did).exists()
    assert api.get(f"/api/designs/{did}", headers=H).json()["report"]["host"] == "gpu-box"

    # a second version, rendered by the helper too: its Kist items are versions of the first
    with db.connect() as conn:
        db.update(conn, "designs", did, blob_sha=BLOB2)
    job2 = jobs.enqueue("render", design_id=did)
    assert api.post("/api/helpers/claim", headers=h, json=_claim_body()).json()["job"]["id"] == job2["id"]
    files, outputs = _good_result()
    assert (
        api.post(
            f"/api/helpers/jobs/{job2['id']}/result",
            headers=h,
            params={"name": "gpu-box"},
            content=_stage_tar(files, outputs),
        ).status_code
        == 200
    )
    assert fake["kist"].versions == [("i2", "i1")]
    assert len(sets.list_sets(did)) == 2


def test_a_different_solidcraft_is_refused_with_409(fake, settings, api):
    did = _design()
    jobs.enqueue("render", design_id=did)
    h = {"Authorization": f"Bearer {_helper_token()}"}
    r = api.post("/api/helpers/claim", headers=h, json=_claim_body(version="0.43.0"))
    assert r.status_code == 409 and "0.44.1" in r.json()["detail"] and "0.43.0" in r.json()["detail"]
    assert api.get("/api/helpers", headers=H).json()[0]["refused"]
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
    jobs.set_options({"helpers_require_same_solidcraft": False})
    assert api.post("/api/helpers/claim", headers=h, json=_claim_body(version="0.43.0")).status_code == 200


def test_bad_uploads_are_refused_and_fail_the_job(fake, settings, api):
    h = {"Authorization": f"Bearer {_helper_token()}"}
    files, outputs = _good_result()
    link = tarfile.TarInfo("evil")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    cases = [
        ({**files, "../escape.txt": b"x"}, outputs, None, None, "unsafe path"),
        ({**files, "/abs.txt": b"x"}, outputs, None, None, "unsafe path"),
        (files, outputs, {**{k: len(v) for k, v in files.items()}, "ghost.png": 3}, None, "missing"),
        (files, outputs, {k: len(v) + 1 for k, v in files.items()}, None, "bytes"),
        (files, outputs, {k: len(v) for k, v in files.items() if k != "views.json"}, None, "not in the manifest"),
        (files, [{**outputs[0], "file": "nope.png"}], None, None, "not in the upload"),
        (files, outputs, None, [link], "plain files"),
    ]
    for i, (fs, outs, man, extra, why) in enumerate(cases):
        did = _design(path=f"parts/case{i}.sc")
        jobs.enqueue("render", design_id=did)
        job = api.post("/api/helpers/claim", headers=h, json=_claim_body()).json()["job"]
        r = api.post(
            f"/api/helpers/jobs/{job['id']}/result",
            headers=h,
            params={"name": "gpu-box"},
            content=_stage_tar(fs, outs, man, extra),
        )
        assert r.status_code == 422 and why in r.json()["detail"], (why, r.text)
        assert api.get(f"/api/jobs/{job['id']}", headers=H).json()["status"] == "failed"
        assert jobs.get_design(did)["status"] == "failed"
        assert not (settings.data_dir / "escape.txt").exists() and not Path("/abs.txt").exists()
        assert not sets.staging_dir(did, BLOB1[:12]).exists()
    # no manifest first
    did = _design(path="parts/last.sc")
    jobs.enqueue("render", design_id=did)
    job = api.post("/api/helpers/claim", headers=h, json=_claim_body()).json()["job"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo("report.json")
        info.size = 2
        t.addfile(info, io.BytesIO(b"{}"))
    r = api.post(f"/api/helpers/jobs/{job['id']}/result", headers=h, params={"name": "gpu-box"}, content=buf.getvalue())
    assert r.status_code == 422 and server.MANIFEST in r.json()["detail"]


def test_an_expired_lease_requeues_then_fails_after_max_attempts(fake, settings, api):
    did = _design()
    job = jobs.enqueue("render", design_id=did)
    h = {"Authorization": f"Bearer {_helper_token()}"}

    def expire():
        with db.connect() as conn:
            conn.execute("UPDATE helper_leases SET lease_until = '2000-01-01T00:00:00+00:00'")

    assert api.post("/api/helpers/claim", headers=h, json=_claim_body()).json()["job"]["attempts"] == 1
    expire()
    assert server.reap_expired() == 1
    j = jobs.get_design(did), api.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert j[1]["status"] == "queued" and j[1]["helper"] is None and "queued again" in j[1]["message"]
    assert j[0]["status"] == "queued" and not (settings.work_dir / did).exists()
    # the late helper finds out it lost the job
    assert api.post(
        f"/api/helpers/jobs/{job['id']}/progress", headers=h, params={"name": "gpu-box"}, json={"fraction": 0.9}
    ).json() == {"cancel": True}
    files, outputs = _good_result()
    assert (
        api.post(
            f"/api/helpers/jobs/{job['id']}/result",
            headers=h,
            params={"name": "gpu-box"},
            content=_stage_tar(files, outputs),
        ).status_code
        == 409
    )
    # the second claim (another helper run) can finish it
    c = api.post("/api/helpers/claim", headers=h, json=_claim_body(name="gpu-box2")).json()
    assert c["job"]["id"] == job["id"] and c["job"]["attempts"] == 2
    expire()
    jobs.housekeeping()  # the worker's turn reaps too
    j = api.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert j["status"] == "failed" and "after 2 attempts" in j["error"]
    assert jobs.get_design(did)["status"] == "failed"


def test_a_stopped_helper_requeues_and_a_real_failure_fails(fake, settings, api):
    did = _design()
    job = jobs.enqueue("render", design_id=did)
    h = {"Authorization": f"Bearer {_helper_token()}"}
    api.post("/api/helpers/claim", headers=h, json=_claim_body())
    r = api.post(
        f"/api/helpers/jobs/{job['id']}/fail",
        headers=h,
        params={"name": "gpu-box"},
        json={"error": "helper stopped", "retry": True},
    )
    assert r.json() == {"requeued": True}
    assert api.get(f"/api/jobs/{job['id']}", headers=H).json()["status"] == "queued"
    api.post("/api/helpers/claim", headers=h, json=_claim_body())
    r = api.post(
        f"/api/helpers/jobs/{job['id']}/fail",
        headers=h,
        params={"name": "gpu-box"},
        json={"error": "solidcraft-cli exited during screenshot"},
    )
    assert r.json() == {"requeued": False}
    j = api.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert j["status"] == "failed" and j["error"] == "solidcraft-cli exited during screenshot"
    d = jobs.get_design(did)
    assert d["status"] == "failed" and "exited" in d["error"]
    assert api.get("/api/helpers", headers=H).json()[0]["jobs_failed"] == 1


def test_cancelling_a_helpers_job_stops_it_and_keeps_the_old_set(fake, settings, api):
    did = _design()
    jobs.render(did)  # the set that must stay current
    first = sets.latest_set(did)
    job = jobs.enqueue("render", design_id=did, force=True)
    h = {"Authorization": f"Bearer {_helper_token()}"}
    assert api.post("/api/helpers/claim", headers=h, json=_claim_body()).status_code == 200
    assert api.post(f"/api/jobs/{job['id']}/cancel", headers=H).json()["status"] == "cancelled"
    assert jobs.get_design(did)["status"] == "rendered"
    assert api.post(
        f"/api/helpers/jobs/{job['id']}/progress", headers=h, params={"name": "gpu-box"}, json={"fraction": 0.3}
    ).json() == {"cancel": True}
    files, outputs = _good_result()
    assert (
        api.post(
            f"/api/helpers/jobs/{job['id']}/result",
            headers=h,
            params={"name": "gpu-box"},
            content=_stage_tar(files, outputs),
        ).status_code
        == 409
    )
    now = sets.latest_set(did)
    assert now["dir"] == first["dir"] and now["rendered_at"] == first["rendered_at"]
    assert jobs.get_design(did)["status"] == "rendered" and len(fake["kist"].uploads) == 1
    assert not (settings.work_dir / did).exists()
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM helper_leases").fetchone()[0] == 0


def test_max_bodies_leaves_big_designs_to_others(fake, settings, api):
    big = _design(path="parts/big.sc")
    jobs.render(big)
    folder = sets.latest_set(big)["dir"]
    (folder / "report.json").write_text(json.dumps({"bodies": 1418}))
    small = _design(path="parts/small.sc")
    jobs.enqueue("render", design_id=big, force=True)
    sj = jobs.enqueue("render", design_id=small)
    h = {"Authorization": f"Bearer {_helper_token()}"}
    c = api.post("/api/helpers/claim", headers=h, json=_claim_body(max_bodies=500)).json()
    assert c["job"]["id"] == sj["id"]
    with db.connect() as conn:
        assert conn.execute(
            "SELECT status, attempts FROM jobs WHERE design_id = ? AND status != 'done'", [big]
        ).fetchone()[:] == ("queued", 0)


def test_render_state_says_quiet_hours_helpers_only(settings, api, monkeypatch):
    monkeypatch.setattr(control, "local_now", lambda: datetime(2026, 11, 19, 23, 0).astimezone())
    jobs.set_options({"render_quiet_hours": "22:00-07:00"})
    s = api.get("/api/render-state", headers=H).json()
    assert s["reason"] == "Quiet hours: helpers only" and s["quiet"] and s["take"] == "none"


# ---------------------------------------------------------------- the client


def _client_helper(api, name="gpu-box", **kw):
    c = TestClient(app(), headers={"Authorization": f"Bearer {_helper_token(name)}"})
    return hclient.Helper("http://testserver", "unused", name, client=c, **kw)


def test_the_client_renders_a_job_end_to_end(fake, settings, api):
    did = _design()
    job = jobs.enqueue("render", design_id=did)
    helper = _client_helper(api, processes=2, renderer="software")
    assert helper.run(once=True) == 0
    call = fake["calls"][-1]
    assert call["local"].name == "case.sc" and call["kw"]["renderer"] == "software"
    assert call["kw"]["processes"] == 2 and call["kw"]["host"] == "gpu-box"
    assert call["kw"]["settings"]["design"]["id"] == did
    j = api.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert j["status"] == "done", j
    report = json.loads((sets.latest_set(did)["dir"] / "report.json").read_text())
    assert report["host"] == "gpu-box" and report["renderer"] == "software"
    assert "helper_total" in report["timings_s"]
    assert helper.run(once=True) == 0  # nothing left: 204


def test_the_client_reports_a_refusal_and_bad_tokens(fake, settings, api, monkeypatch):
    did = _design()
    jobs.enqueue("render", design_id=did)
    monkeypatch.setattr(solidcraft, "version", lambda: "0.40.0")
    assert _client_helper(api).run(once=True) == 2
    bad = hclient.Helper(
        "http://testserver",
        "x",
        "gpu-box",
        client=TestClient(app(), headers=H | {"Authorization": "Bearer skh" + "x" * 32}),
    )
    assert bad.run(once=True) == 3


def test_the_client_stopped_mid_render_hands_the_job_back(fake, settings, api, monkeypatch):
    did = _design()
    job = jobs.enqueue("render", design_id=did)
    helper = _client_helper(api)

    def stopping(local, out_dir, stem, opts, progress, **kw):
        helper.request_stop()  # SIGTERM arrives
        progress(0.4, "frame 9/20")
        raise AssertionError("progress must raise once stopped")

    monkeypatch.setattr(render, "render_set", stopping)
    helper.run(once=True)
    j = api.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert j["status"] == "queued" and "helper stopped" in j["message"]
    assert jobs.get_design(did)["status"] == "queued"


def test_the_client_stops_when_the_server_cancels(fake, settings, api, monkeypatch):
    did = _design()
    job = jobs.enqueue("render", design_id=did)
    helper = _client_helper(api)
    seen = {}

    def cancelled_midway(local, out_dir, stem, opts, progress, **kw):
        jobs.cancel(job["id"])
        hclient.PROGRESS_EVERY = 0
        try:
            progress(0.5, "frame 10/20")
        except hclient.Cancelled:
            seen["cancelled"] = True
            raise
        finally:
            hclient.PROGRESS_EVERY = 2.0
        return [], {}

    monkeypatch.setattr(render, "render_set", cancelled_midway)
    helper.run(once=True)
    assert seen == {"cancelled": True}
    assert api.get(f"/api/jobs/{job['id']}", headers=H).json()["status"] == "cancelled"
    assert jobs.get_design(did)["status"] == "new"


def test_the_client_renders_every_feature_step_without_a_database(settings, api, monkeypatch, fake):
    """The real render_set with every step, on a fake SolidCraft, while the database is
    off limits to the rendering thread: a helper needs none of the server's state."""
    import test_integration as ti

    monkeypatch.setattr(render, "render_set", _real_render_set)
    monkeypatch.setattr(render, "SolidCraft", ti.AllSC)
    for name in ("encode", "encode_gif", "encode_prores"):
        monkeypatch.setattr(render, name, ti._encode)
    from sklent.features.revisions import timelapse

    monkeypatch.setattr(timelapse, "encode", lambda frames, mp4, gif, w: (mp4.write_bytes(b"m"), gif.write_bytes(b"g")))
    from sklent.features.views import steps as vsteps

    monkeypatch.setattr(vsteps.R, "encode", ti._encode)
    monkeypatch.setattr(vsteps.R, "encode_gif", ti._encode)
    on = ti._every_setting_on()
    on.update(seconds=2, fps=24, styles=["shaded"], outputs=["social", "hires"])
    jobs.set_options({k: v for k, v in on.items() if k in jobs._EXTRA or k in ("seconds", "fps", "styles", "outputs")})
    did = _design()
    job = jobs.enqueue("render", design_id=did)

    render_thread: dict = {}
    real_connect = db._connect

    def guarded():
        if threading.get_ident() == render_thread.get("id"):
            raise AssertionError("the helper's render touched the database")
        return real_connect()

    monkeypatch.setattr(db, "_connect", guarded)
    real = render.render_set

    def marked(*a, **k):
        render_thread["id"] = threading.get_ident()
        try:
            return real(*a, **k)
        finally:
            render_thread.clear()

    monkeypatch.setattr(render, "render_set", marked)
    helper = _client_helper(api)
    assert helper.run(once=True) == 0
    j = api.get(f"/api/jobs/{job['id']}", headers=H).json()
    assert j["status"] == "done", j
    report = json.loads((sets.latest_set(did)["dir"] / "report.json").read_text())
    bad = {k: v.get("error") for k, v in report["steps"].items() if not v.get("ok")}
    assert not bad, bad
    variants = {f["variant"] for f in jobs.get_design(did)["files"]}
    assert {"preview", "hires", "spec-card", "step"} <= variants, variants


_real_render_set = render.render_set


def test_safe_extract_refuses_traversal(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo("../x.sc")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    (tmp_path / "in.tar").write_bytes(buf.getvalue())
    with pytest.raises(RuntimeError):
        hclient.safe_extract(tmp_path / "in.tar", tmp_path / "out")


def test_pack_stage_lists_every_file_after_the_manifest(tmp_path):
    stage = tmp_path / "s"
    _png(stage / "a.png")
    (stage / "sub").mkdir()
    (stage / "sub" / "b.json").write_text("{}")
    hclient.pack_stage(stage, [Output("a.png", "shaded", "hires", 16, 9)], tmp_path / "r.tar")
    with tarfile.open(tmp_path / "r.tar") as t:
        names = t.getnames()
        manifest = json.loads(t.extractfile(names[0]).read())
    assert names[0] == server.MANIFEST and set(names[1:]) == {"a.png", "sub/b.json"}
    assert manifest["files"]["sub/b.json"] == 2 and manifest["outputs"][0]["file"] == "a.png"


# ---------------------------------------------------------------- software rendering


def test_software_renderer_env_limits_vulkan_to_lavapipe(monkeypatch, settings):
    monkeypatch.setattr(solidcraft, "lvp_icd", lambda: "/usr/share/vulkan/icd.d/lvp_icd.json")
    env = solidcraft.renderer_env("software")
    assert env["SOLIDCRAFT_GPU"] == "software" and env["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert env["VK_DRIVER_FILES"] == env["VK_ICD_FILENAMES"] == "/usr/share/vulkan/icd.d/lvp_icd.json"
    assert solidcraft.renderer_env("gpu") is None and solidcraft.renderer_env(None) is None


def test_gpu_info_reads_what_solidcraft_lands_on(monkeypatch, settings):
    import subprocess

    solidcraft.gpu_info.cache_clear()
    out = {
        "chosen": {"name": "llvmpipe (LLVM 20.1.2, 256 bits)", "backend": "Vulkan", "tier": "software"},
        "lands_on": "software",
    }
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": json.dumps(out)})())
    assert solidcraft.gpu_info("software") == {
        "renderer": "software",
        "adapter": "llvmpipe (LLVM 20.1.2, 256 bits)",
        "backend": "Vulkan",
        "lands_on": "software",
    }
    solidcraft.gpu_info.cache_clear()


def test_render_set_records_renderer_and_host(monkeypatch, tmp_path, settings):
    import test_integration as ti

    monkeypatch.setattr(render, "SolidCraft", ti.AllSC)
    monkeypatch.setattr(render, "gpu_info", lambda r=None: {"renderer": r or "gpu", "adapter": "Iris Xe"})
    from sklent import steps

    monkeypatch.setattr(steps, "_STEPS", {})
    opened = []

    class SC(ti.AllSC):
        def __init__(self, d=Path("d.sc"), o=Path("."), **k):
            opened.append(k)
            super().__init__(d, o)

    monkeypatch.setattr(render, "SolidCraft", SC)
    _, report = render.render_set(
        tmp_path / "d.sc",
        tmp_path / "o",
        "d",
        render.RenderOptions(outputs=[]),
        processes=1,
        renderer="software",
        host="mac-mini",
    )
    assert report["renderer"] == "software" and report["host"] == "mac-mini" and report["adapter"] == "Iris Xe"
    assert opened == [{"renderer": "software"}]
