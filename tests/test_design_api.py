"""A2 (plural job messages), A3 (blob + report on /api/designs) and job cancelling."""

import json
import threading
import time

from fastapi.testclient import TestClient

from sklent import db, jobs, service
from sklent.render import Output

H = {"Authorization": "Bearer test-token-0123456789"}


def _source() -> dict:
    return jobs.add_source("https://github.com/o/r")


def _design(source_id: str, *, path: str = "parts/case.sc", blob: str = "b" * 40, render_dir: str | None = None,
            files: list | None = None, status: str = "new") -> str:
    did = db.new_id()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha, commit_sha,"
            " status, render_dir, files, rendered_sha, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [did, source_id, "o", "r", "main", path, f"https://github.com/o/r/blob/c/{path}",
             blob, "c" * 40, status, render_dir, json.dumps(files or []),
             blob if render_dir else None, db.now()])
    return did


def test_plural():
    assert jobs.plural(1, "body", "bodies") == "1 body"
    assert jobs.plural(2, "body", "bodies") == "2 bodies"
    assert jobs.plural(1418, "body", "bodies") == "1,418 bodies"
    assert jobs.plural(12, "file") == "12 files"


class _Forge:
    def __init__(self, *a, **k):
        pass

    def fetch(self, *a, **k):
        return b"solidcraft"


def test_render_message_says_one_body(monkeypatch, settings):
    did = _design(_source()["id"])
    monkeypatch.setattr(jobs, "Forge", _Forge)
    monkeypatch.setattr(jobs, "looks_like_design", lambda data: True)

    def fake_render_set(local, out_dir, stem, opts, progress, **_):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "a.png").write_bytes(b"x")
        return [Output("a.png", "shaded", "social", 8, 8)], {"bodies": 1}

    monkeypatch.setattr(jobs, "render_set", fake_render_set)
    assert jobs.render(did, force=True) == "rendered 1 file (1 body)"


REPORT = {
    "options": {"palette": "white", "seconds": 8.0},
    "clamped": {"shaded": 0.0},
    "bodies": 1418,
    "hidden_bodies": 2,
    "bounds_mm": [[-3.9960923459148034e-10, 0.0, -30.0], [354.9999999999978, 355.0, 10.000000000000062]],
    "frame_ms": 35.6,
    "processes": 3,
    "timings_s": {"load": 8.0, "frames": 32.0},
}


def test_designs_carry_blob_and_report_even_when_the_data_dir_moved(settings):
    sid = _source()["id"]
    blob = "1258878" + "7" * 33
    did = _design(sid, blob=blob, status="rendered",
                  files=[{"file": "case-shaded-social-8.png", "style": "shaded", "variant": "social",
                          "width": 8, "height": 8}])
    # stored as the old host's absolute path; the set really lives under this data dir
    folder = settings.renders_dir / did / blob[:12]
    folder.mkdir(parents=True)
    (folder / "case-shaded-social-8.png").write_bytes(b"png!")
    (folder / "report.json").write_text(json.dumps(REPORT))
    with db.connect() as conn:
        db.update(conn, "designs", did, render_dir=f"/data/renders/{did}/{blob[:12]}")
    bare = _design(sid, path="parts/lid.sc", blob="d" * 40)

    from sklent.app import app
    c = TestClient(app)  # no lifespan: no worker, and the MCP session manager runs once a process
    listed = {d["id"]: d for d in c.get("/api/designs", headers=H).json()}
    one = c.get(f"/api/designs/{did}", headers=H).json()
    assert c.get(f"/api/designs/{did}/files/case-shaded-social-8.png", headers=H).content == b"png!"
    for d in (listed[did], one):
        assert d["blob"] == blob
        assert d["files"][0]["bytes"] == 4
        r = d["report"]
        assert set(r) == {"bodies", "hidden_bodies", "bounds_mm", "palette", "frame_ms", "processes",
                          "timings_s"}
        assert r["bodies"] == 1418 and r["hidden_bodies"] == 2 and r["palette"] == "white"
        assert r["bounds_mm"] == [[-0.0, 0.0, -30.0], [355.0, 355.0, 10.0]]
        assert r["frame_ms"] == 35.6 and r["processes"] == 3 and r["timings_s"]["frames"] == 32.0
    assert listed[bare]["report"] is None and listed[bare]["blob"] == "d" * 40


def test_cancel_a_queued_render_and_refuse_finished_or_unknown_jobs():
    did = _design(_source()["id"])
    job = jobs.enqueue("render", design_id=did)
    assert jobs.get_design(did)["status"] == "queued"
    from sklent.app import app
    c = TestClient(app)  # no lifespan, so no worker claims the job
    r = c.post(f"/api/jobs/{job['id']}/cancel", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert jobs.get_design(did)["status"] == "new"
    assert c.post(f"/api/jobs/{job['id']}/cancel", headers=H).status_code == 409
    assert c.post("/api/jobs/999999/cancel", headers=H).status_code == 404
    assert c.post(f"/api/jobs/{job['id']}/cancel").status_code == 401


def test_cancel_queued_without_the_worker():
    did = _design(_source()["id"], status="new")
    job = jobs.enqueue("render", design_id=did)
    out = jobs.cancel(job["id"])
    assert out["status"] == "cancelled" and out["finished_at"]
    assert jobs.get_design(did)["status"] == "new"
    assert jobs._claim() is None  # a cancelled job is never picked up


def test_cancel_a_running_render_kills_solidcraft_and_restores_the_design(monkeypatch, settings):
    did = _design(_source()["id"], status="failed")
    with db.connect() as conn:
        db.update(conn, "designs", did, error="earlier failure")
    monkeypatch.setattr(jobs, "Forge", _Forge)
    monkeypatch.setattr(jobs, "looks_like_design", lambda data: True)
    killed = threading.Event()
    monkeypatch.setattr(jobs, "kill_all", lambda: killed.set() or 1)
    started = threading.Event()

    def slow_render_set(local, out_dir, stem, opts, progress, **_):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "partial.png").write_bytes(b"x")
        started.set()
        for i in range(400):  # a frame loop: reports progress until killed
            if killed.is_set():
                raise RuntimeError("solidcraft-cli exited during tools/call")
            progress(i / 400, f"frame {i}/400")
            time.sleep(0.01)
        raise AssertionError("never cancelled")

    monkeypatch.setattr(jobs, "render_set", slow_render_set)
    job = jobs.enqueue("render", design_id=did, force=True)
    claimed = jobs._claim()
    assert claimed and claimed["id"] == job["id"]
    t = threading.Thread(target=jobs.run_job, args=(claimed,))
    t.start()
    assert started.wait(5)
    out = jobs.cancel(job["id"])
    t.join(5)
    assert not t.is_alive()
    assert killed.is_set()
    assert out["status"] == "cancelled"
    assert service.get_job(job["id"])["status"] == "cancelled"  # not overwritten as failed
    d = jobs.get_design(did)
    assert d["status"] == "failed" and d["error"] == "earlier failure"
    assert not (settings.renders_dir / did / ("b" * 12)).exists()


def test_cancel_a_running_row_no_worker_owns_restores_the_design(monkeypatch):
    """A job row left `running` with no worker on it (another process, a crash) is still
    cancellable, and its design goes back to its previous status straight away."""
    did = _design(_source()["id"], status="rendering")
    with db.connect() as conn:
        jid = conn.execute("INSERT INTO jobs (kind, design_id, status, created_at) VALUES"
                           " ('render', ?, 'running', ?)", [did, db.now()]).lastrowid
    killed = []
    monkeypatch.setattr(jobs, "kill_all", lambda: killed.append(1) or 0)
    assert jobs.cancel(jid)["status"] == "cancelled"
    assert jobs.get_design(did)["status"] == "new"
    assert not killed  # not this worker's job: nothing of ours to kill
