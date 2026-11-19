"""F1 revision history (sets kept per version, Kist versions, keep policy, compare,
changelog) and F29 build-history timelapse."""

import json
import shutil
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sklent import db, jobs, service, sets, steps
from sklent.features import revisions
from sklent.features.revisions import compare, timelapse
from sklent.kist import Kist
from sklent.render import Output

H = {"Authorization": "Bearer test-token-0123456789"}
BLOB1, BLOB2, BLOB3 = "1" * 40, "2" * 40, "3" * 40
C1, C2, C3 = "a" * 40, "b" * 40, "c" * 40


def _design(blob=BLOB1, commit=C1) -> str:
    src = jobs.add_source("https://github.com/o/r")
    did = db.new_id()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha, commit_sha,"
            " status, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [did, src["id"], "o", "r", "main", "parts/case.sc", "https://github.com/o/r/blob/x/parts/case.sc",
             blob, commit, "new", db.now()])
    return did


def _bump(did, blob, commit):
    with db.connect() as conn:
        db.update(conn, "designs", did, blob_sha=blob, commit_sha=commit)


class FakeForge:
    """Enough of sources.Forge: fetch, plus the history calls through _get."""
    commits: list[dict] = []
    tags: list[dict] = []
    blobs: dict[str, str] = {}
    provider = "github"

    def __init__(self, *a, **k):
        pass

    def fetch(self, *a, **k):
        return b"solidcraft"

    def _get(self, path, **kw):
        if "/commits?" in path:
            head = path.split("sha=")[1].split("&")[0]
            shas = [c["sha"] for c in self.commits]
            start = shas.index(head) if head in shas else 0
            data = [{"sha": c["sha"], "commit": {"message": c["message"],
                                                  "author": {"name": "Jay", "date": c["date"]}},
                     "author": {"login": "jay"}} for c in self.commits[start:]]
        elif "/tags?" in path:
            data = [{"name": t["name"], "commit": {"sha": t["sha"]}} for t in self.tags]
        elif "/contents/" in path:
            ref = path.split("ref=")[1]
            data = {"sha": self.blobs.get(ref)}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=data, request=httpx.Request("GET", "http://x" + path))


def _png(path: Path, square: tuple[int, int, int, int] | None = None, size=(64, 36)):
    a = np.full((size[1], size[0], 3), 200, np.uint8)
    if square:
        x0, y0, x1, y1 = square
        a[y0:y1, x0:x1] = 60
    Image.fromarray(a).save(path)


@pytest.fixture
def fake(monkeypatch):
    FakeForge.commits = [
        {"sha": C3, "message": "Thicker lid\n\nbody", "date": "2026-11-03T10:00:00Z"},
        {"sha": C2, "message": "Add vents", "date": "2026-11-02T10:00:00Z"},
        {"sha": C1, "message": "First case", "date": "2026-11-01T10:00:00Z"},
    ]
    FakeForge.tags = []
    FakeForge.blobs = {}
    monkeypatch.setattr(jobs, "Forge", FakeForge)
    monkeypatch.setattr(revisions, "Forge", FakeForge)
    monkeypatch.setattr(jobs, "looks_like_design", lambda data, path=None: True)
    state = {"square": None, "n": 0, "fail": None}

    def fake_render_set(local, out_dir, stem, opts, progress, **_):
        out_dir.mkdir(parents=True, exist_ok=True)
        state["n"] += 1
        _png(out_dir / f"{stem}-shaded-hires-64x36.png", state["square"])
        _png(out_dir / f"{stem}-shaded-social-36.png", state["square"], (36, 36))
        if state["fail"]:
            raise state["fail"]
        return ([Output(f"{stem}-shaded-hires-64x36.png", "shaded", "hires", 64, 36),
                 Output(f"{stem}-shaded-social-36.png", "shaded", "social", 36, 36)],
                {"bodies": 1, "options": {"palette": "cool-grey"}, "bounds_mm": [[0, 0, 0], [1, 1, 1]],
                 "n": state["n"]})

    monkeypatch.setattr(jobs, "render_set", fake_render_set)
    return state


def _three_versions(fake):
    did = _design(BLOB1, C1)
    jobs.render(did)
    _bump(did, BLOB2, C2)
    fake["square"] = (10, 10, 20, 20)
    jobs.render(did)
    _bump(did, BLOB3, C3)
    fake["square"] = (10, 10, 30, 20)
    jobs.render(did)
    return did


# ---------------------------------------------------------------- sets kept per version

def test_every_version_keeps_its_set_newest_first(fake, settings):
    did = _three_versions(fake)
    all_ = sets.list_sets(did)
    assert [s["id"] for s in all_] == [BLOB3[:12], BLOB2[:12], BLOB1[:12]]
    assert [s["current"] for s in all_] == [True, False, False]
    assert all_[1]["commit_sha"] == C2 and all_[1]["commit"]["message"] == "Add vents"
    assert all_[0]["commit"]["author"] == "jay" and all_[2]["commit"]["date"].startswith("2026-11-01")
    assert sets.latest_set(did)["id"] == BLOB3[:12]
    assert sets.get_set(did, BLOB1[:12])["files"][0]["variant"] == "hires"
    assert not list((settings.renders_dir / did).glob(".*"))  # no staging left behind

    from sklent.app import app
    c = TestClient(app)
    listed = c.get(f"/api/designs/{did}/sets", headers=H).json()
    assert [s["commit"] for s in listed] == [C3[:10], C2[:10], C1[:10]]
    assert listed[0]["message"] == "Thicker lid" and listed[2]["thumb_url"].endswith("social-36.png")
    old = listed[2]["files"][0]["url"]
    assert c.get(old, headers=H).status_code == 200
    assert c.get(f"/api/designs/{did}/sets/{BLOB1[:12]}/files/nope.png", headers=H).status_code == 404
    assert c.get(f"/api/designs/{did}/sets/nope", headers=H).status_code == 404
    d = c.get(f"/api/designs/{did}", headers=H).json()
    assert d["revisions"]["count"] == 3


def test_rerendering_the_same_version_replaces_only_that_set(fake, settings):
    did = _three_versions(fake)
    before = sets.get_set(did, BLOB2[:12])
    jobs.render(did, force=True)  # current is BLOB3
    after = sets.list_sets(did)
    assert len(after) == 3
    assert sets.get_set(did, BLOB2[:12])["rendered_at"] == before["rendered_at"]
    assert sets.latest_set(did)["report"]["n"] == 4  # the BLOB3 set is the new one


def test_a_failed_or_cancelled_forced_rerender_keeps_the_old_set(fake, settings, monkeypatch):
    did = _design()
    jobs.render(did)
    folder = settings.renders_dir / did / BLOB1[:12]
    assert (folder / "set.json").exists()
    fake["fail"] = RuntimeError("solidcraft-cli exited")
    with pytest.raises(RuntimeError):
        jobs.render(did, force=True)
    d = jobs.get_design(did)
    assert d["status"] == "failed" and d["render_dir"] == str(folder) and d["files"]
    assert sets.read_json(folder, "report.json")["n"] == 1
    assert not sets.staging_dir(did, BLOB1[:12]).exists()

    monkeypatch.setattr(jobs, "_cancel_requested", lambda: True)
    with pytest.raises(jobs.JobCancelled):
        jobs.render(did, force=True)
    d = jobs.get_design(did)
    assert d["render_dir"] == str(folder) and d["files"] and d["status"] == "rendered"
    assert sets.latest_set(did)["report"]["n"] == 1
    assert not sets.staging_dir(did, BLOB1[:12]).exists()


def test_cancel_a_running_forced_rerender_through_the_worker(fake, settings, monkeypatch):
    did = _design()
    jobs.render(did)
    killed = threading.Event()
    monkeypatch.setattr(jobs, "kill_all", lambda: killed.set() or 1)
    monkeypatch.setattr(jobs, "_cancelled", set())  # job ids restart per test database
    started = threading.Event()

    def slow(local, out_dir, stem, opts, progress, **_):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "partial.png").write_bytes(b"x")
        started.set()
        for i in range(400):
            if killed.is_set():
                raise RuntimeError("killed")
            progress(i / 400, "frame")
            time.sleep(0.01)
        raise AssertionError("never cancelled")

    monkeypatch.setattr(jobs, "render_set", slow)
    with db.connect() as conn:  # a running row, not queued: no stray worker can claim it
        jid = conn.execute("INSERT INTO jobs (kind, design_id, force, status, created_at) VALUES"
                           " ('render', ?, 1, 'running', ?)", [did, db.now()]).lastrowid
        job = db.row(conn.execute("SELECT * FROM jobs WHERE id = ?", [jid]).fetchone())
    t = threading.Thread(target=jobs.run_job, args=(job,))
    t.start()
    assert started.wait(5), (t.is_alive(), service.get_job(job["id"]))
    jobs.cancel(job["id"])
    t.join(5)
    d = jobs.get_design(did)
    assert d["status"] == "rendered" and d["files"] and sets.latest_set(did) is not None
    assert not sets.staging_dir(did, BLOB1[:12]).exists()


def test_sets_from_before_revisions_are_still_listed_and_described(fake, settings):
    did = _design()
    folder = settings.renders_dir / did / BLOB1[:12]
    folder.mkdir(parents=True)
    _png(folder / "case-shaded-social-36.png")
    files = [{"file": "case-shaded-social-36.png", "style": "shaded", "variant": "social", "width": 36, "height": 36}]
    with db.connect() as conn:
        db.update(conn, "designs", did, render_dir=str(folder), files=files, rendered_sha=BLOB1,
                  rendered_at="2026-10-01T00:00:00+00:00", status="rendered")
    s = sets.list_sets(did)
    assert len(s) == 1 and s[0]["current"] and s[0]["commit_sha"] == C1 and s[0]["legacy"]
    _bump(did, BLOB2, C2)
    jobs.render(did)
    old = sets.get_set(did, BLOB1[:12])
    assert old and not old["current"] and old["files"] == files  # set.json written from the row
    assert len(sets.list_sets(did)) == 2


# ---------------------------------------------------------------- keep policy

def test_keep_policy_prunes_old_untagged_sets_from_disk_only(fake, settings):
    FakeForge.tags = [{"name": "v1.0", "sha": "t" * 40}]
    FakeForge.blobs = {"t" * 40: BLOB1}
    jobs.set_options({"revisions_keep": 1})
    did = _three_versions(fake)
    ids = [s["id"] for s in sets.list_sets(did)]
    assert ids == [BLOB3[:12], BLOB1[:12]]  # BLOB2 pruned; BLOB1 is tagged v1.0
    assert sets.get_set(did, BLOB1[:12])["tags"] == ["v1.0"]
    assert sets.to_prune([{"id": "x", "tags": []}], 0) == []  # 0 keeps everything


def test_prune_never_trashes_a_kist_item_a_kept_set_shares(fake, settings):
    did = _three_versions(fake)
    for s in sets.list_sets(did):  # Kist dedupes identical bytes: one item in every set
        sets.update_meta(s["dir"], kist_items=[{"id": "same", "file": "x"}, {"id": f"own-{s['id']}", "file": "y"}])
    with db.connect() as conn:
        db.update(conn, "designs", did, kist_items=[{"id": "same", "file": "x"}, {"id": "own-cur", "file": "y"}])

    class K:
        trashed: list[str] = []

        def trash(self, i):
            self.trashed.append(i)

    k = K()
    assert sets.prune(did, 1, k) == [BLOB2[:12], BLOB1[:12]]
    assert sorted(k.trashed) == [f"own-{BLOB1[:12]}", f"own-{BLOB2[:12]}"]


def test_keep_setting_validation():
    assert jobs.set_options({"revisions_keep": "all"}) and jobs.get_all_settings()["revisions_keep"] == 0
    for bad in ({"revisions_keep": -1}, {"revisions_keep": "lots"},
                {"revisions_timelapse_max_features": 1}):
        with pytest.raises(ValueError):
            jobs.set_options(bad)
    s = jobs.get_all_settings()
    assert s["revisions_prune_kist"] is False and s["revisions_timelapse"] is False
    assert s["revisions_timelapse_max_bodies"] == 100 and s["revisions_timelapse_max_features"] == 200


# ---------------------------------------------------------------- Kist

class FakeKist:
    def __init__(self):
        self.items: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.stacks: dict[str, list] = {}

    def handler(self, req: httpx.Request):
        p, m = req.url.path, req.method
        self.calls.append((m, p))
        if p == "/api/folders" and m == "GET":
            return httpx.Response(200, json=[])
        if p == "/api/folders":
            return httpx.Response(201, json={"id": f"f{len(self.calls)}", **json.loads(req.content)})
        if p == "/api/items" and m == "POST":
            body = req.content.decode("latin-1")
            tags = body.split('name="tags"')[1].split("\r\n\r\n")[1].split("\r\n")[0].split(",")
            iid = f"i{len(self.items) + 1}"
            self.items[iid] = {"id": iid, "tags": tags, "notes": "", "stack_id": None}
            return httpx.Response(201, json={"item": self.items[iid], "created": True})
        if p.startswith("/api/items/") and p.endswith("/links"):
            return httpx.Response(201, json=[])
        if p.startswith("/api/items/") and p.endswith("/tags"):
            iid = p.split("/")[3]
            self.items[iid]["tags"] += json.loads(req.content)["add"]
            return httpx.Response(200, json=self.items[iid])
        if p.startswith("/api/items/") and m == "GET":
            iid = p.split("/")[3]
            return httpx.Response(200, json=self.items[iid]) if iid in self.items else httpx.Response(404)
        if p == "/api/stacks" and m == "POST":
            b = json.loads(req.content)
            sid = f"s{len(self.stacks) + 1}"
            self.stacks[sid] = b["item_ids"]
            for i in b["item_ids"]:
                self.items[i]["stack_id"] = sid
            return httpx.Response(201, json={"id": sid})
        if p.startswith("/api/stacks/") and m == "PATCH":
            sid = p.split("/")[3]
            for i in json.loads(req.content)["add"]:
                self.items[i]["stack_id"] = sid
            return httpx.Response(200, json={"id": sid})
        if m == "DELETE":
            return httpx.Response(200, json={})
        raise AssertionError((m, p))


def test_kist_items_are_kept_tagged_by_rev_and_linked_as_versions(fake, settings, monkeypatch):
    k = FakeKist()
    client = httpx.Client(transport=httpx.MockTransport(k.handler))
    monkeypatch.setattr(jobs, "Kist", lambda: Kist("http://kist", "kt", client))
    did = _design()
    # a set from before revisions, filed with notes but no rev tag
    folder = settings.renders_dir / did / BLOB1[:12]
    folder.mkdir(parents=True)
    _png(folder / "case-shaded-hires-64x36.png")
    k.items["old1"] = {"id": "old1", "tags": ["solidcraft"], "stack_id": None,
                       "notes": f"o/r:parts/case.sc at {C1[:10]}, rendered by sklent"}
    files = [{"file": "case-shaded-hires-64x36.png", "style": "shaded", "variant": "hires", "width": 64, "height": 36}]
    with db.connect() as conn:
        db.update(conn, "designs", did, render_dir=str(folder), files=files, rendered_sha=BLOB1, status="rendered",
                  kist_items=[{"id": "old1", "file": "case-shaded-hires-64x36.png"}], kist_folder_id="f")
    _bump(did, BLOB2, C2)
    jobs.render(did)
    assert not [c for c in k.calls if c[0] == "DELETE"]  # nothing trashed
    assert f"rev:{C1[:10]}" in k.items["old1"]["tags"]  # the older item got its rev tag
    new_hires = next(i for i in jobs.get_design(did)["kist_items"] if i["variant"] == "hires")
    assert f"rev:{C2[:10]}" in k.items[new_hires["id"]]["tags"]
    assert ("POST", f"/api/items/{new_hires['id']}/links") in k.calls
    assert k.items[new_hires["id"]]["stack_id"] == k.items["old1"]["stack_id"] is not None
    assert sets.get_set(did, BLOB1[:12])["commit_sha"] == C1[:10]

    _bump(did, BLOB3, C3)
    jobs.render(did)  # the next version joins the same stack
    newest = next(i for i in jobs.get_design(did)["kist_items"] if i["variant"] == "hires")
    assert k.items[newest["id"]]["stack_id"] == k.items["old1"]["stack_id"]
    assert not [c for c in k.calls if c[0] == "DELETE"]

    # pruning with revisions_prune_kist trashes the pruned sets' items, never others
    jobs.set_options({"revisions_keep": 1, "revisions_prune_kist": True})
    _bump(did, "4" * 40, "d" * 40)
    FakeForge.commits.insert(0, {"sha": "d" * 40, "message": "v4", "date": "2026-11-04T10:00:00Z"})
    jobs.render(did)
    deleted = {c[1].split("/")[3] for c in k.calls if c[0] == "DELETE"}
    current = {i["id"] for i in jobs.get_design(did)["kist_items"]}
    assert "old1" in deleted and newest["id"] in deleted and not deleted & current


# ---------------------------------------------------------------- compare and changelog

def test_compare_finds_the_changed_pixels(fake, settings):
    did = _three_versions(fake)
    from sklent.app import app
    c = TestClient(app)
    r = c.get(f"/api/designs/{did}/compare", headers=H).json()  # current vs the one before
    assert r["a"]["id"] == BLOB2[:12] and r["b"]["id"] == BLOB3[:12]
    assert r["changed"] > 0 and r["bbox"][0] < 20 / 64 < r["bbox"][2]
    assert {"style": "shaded", "variant": "hires", "kind": "still"} in r["choices"]
    assert r["reframed"] is False
    mask = c.get(r["diff_url"], headers=H)
    assert mask.status_code == 200
    from io import BytesIO
    alpha = np.asarray(Image.open(BytesIO(mask.content)))[..., 3]
    assert alpha[15, 25] == 255 and alpha[30, 60] == 0  # changed / unchanged
    assert alpha[15, 15] == 0  # inside the old square too: same in both
    comp = c.get(r["composite_url"], headers=H)
    assert comp.status_code == 200 and Image.open(BytesIO(comp.content)).mode == "RGB"
    same = c.get(f"/api/designs/{did}/compare?a={BLOB1[:12]}&b={BLOB1[:12]}", headers=H)
    assert same.status_code == 422
    assert c.get(f"/api/designs/{did}/compare?variant=reel", headers=H).status_code == 404


def test_compare_rgb_is_neutral(fake, settings):
    did = _three_versions(fake)
    a, b = sets.get_set(did, BLOB1[:12]), sets.get_set(did, BLOB3[:12])
    img = np.asarray(Image.open(compare.composite(a, b, width=400)).convert("RGB")).astype(int)
    assert (img.max(axis=2) - img.min(axis=2)).max() <= 2  # greys only, no hue


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_compare_the_same_frame_of_a_video(fake, settings):
    did = _three_versions(fake)
    for s in sets.list_sets(did):
        frames = s["dir"] / "_f"
        frames.mkdir()
        for i in range(6):
            _png(frames / f"f{i:04d}.png", (i * 5, 0, i * 5 + 8, 8) if s["current"] else None)
        from sklent.render import encode
        encode(frames, s["dir"] / "case-shaded-1080p.mp4", 30, crf=18)
        shutil.rmtree(frames)
        files = [*s["files"], {"file": "case-shaded-1080p.mp4", "style": "shaded", "variant": "1080p",
                               "width": 64, "height": 36}]
        sets.update_meta(s["dir"], files=files)
        if s["current"]:
            with db.connect() as conn:
                db.update(conn, "designs", did, files=files)
        rep = sets.read_json(s["dir"], "report.json")
        rep["options"].update(seconds=0.2, fps=30)
        sets.write_json(s["dir"], "report.json", rep)
    out = revisions.compare_out(did, None, None, "shaded", "1080p", 3)
    assert out["frame"] == 3 and out["frames"] == 6 and out["changed"] > 0
    assert "frame.png" in out["a_url"]
    from sklent.app import app
    assert TestClient(app).get(out["b_url"], headers=H).headers["content-type"] == "image/png"


def test_changelog_lists_the_commits_between_two_sets(fake, settings):
    did = _three_versions(fake)
    log = revisions.changelog_out(did, BLOB1[:12], BLOB3[:12])
    assert [c["message"] for c in log["commits"]] == ["Thicker lid\n\nbody", "Add vents"]
    assert log["complete"] is True
    from sklent.app import app
    r = TestClient(app).get(f"/api/designs/{did}/changelog?base={BLOB2[:12]}&head={BLOB3[:12]}", headers=H)
    assert [c["sha"] for c in r.json()["commits"]] == [C3]


def test_changelog_says_when_the_forge_is_away(fake, settings, monkeypatch):
    did = _three_versions(fake)
    revisions._log_cache.clear()

    class Down(FakeForge):
        def _get(self, path, **kw):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(revisions, "Forge", Down)
    log = revisions.changelog_out(did, None, None)
    assert log["commits"] == [] and "didn't answer" in log["error"]


def test_forgejo_history_calls_use_its_query_shape():
    seen = []

    class F:
        provider = "forgejo"

        def _get(self, path, **kw):
            seen.append(path)
            return httpx.Response(200, json=[], request=httpx.Request("GET", "http://x"))

    sets.path_commits(F(), "o", "r", "main", "a b/c.sc", 5)
    sets.repo_tags(F(), "o", "r")
    assert "limit=5" in seen[0] and "path=a%20b/c.sc" in seen[0] and "files=false" in seen[0]
    assert seen[1].endswith("/tags?limit=30")


def test_one_set_cannot_be_compared(fake, settings):
    did = _design()
    jobs.render(did)
    from sklent.app import app
    assert TestClient(app).get(f"/api/designs/{did}/compare", headers=H).status_code == 409


# ---------------------------------------------------------------- MCP

def test_mcp_tools_are_registered():
    import asyncio

    from sklent.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"list_sets", "compare_sets", "view_compare"} <= names


# ---------------------------------------------------------------- F29 timelapse

class TLSC:
    def __init__(self, features=5):
        self.features, self.marker, self.calls = features, features, []

    def execute(self, command, **params):
        self.calls.append((command, params))
        assert command == "timeline.rollback"
        pos = params["position"]
        self.marker = self.features if pos == "end" else pos
        return {"features": self.features, "marker": self.marker}

    def screenshot(self, path, camera, w, h):
        assert camera["fov"] > 0
        _png(Path(path), (0, 0, 4 * self.marker, 4), (64, 36))

    def paint(self, bodies, color, opacity):
        self.calls.append(("paint", color))


class Pal:
    shaded, wireframe = "#c8c8c8", "#bbbbbb"


def _tl_ctx(tmp_path, sc, bodies=("b1",), **settings_):
    return steps.StepContext(sc=sc, design=tmp_path / "d.sc", out_dir=tmp_path, stem="d", opts=None,
                             info=[], bodies=list(bodies), box=([0, 0, 0], [10, 10, 10]), palette=Pal(),
                             pitch=0.4, report={}, settings={"revisions_timelapse": True, **settings_})


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_timelapse_steps_through_the_history(tmp_path):
    sc = TLSC(5)
    ctx = _tl_ctx(tmp_path, sc)
    timelapse.run(ctx)
    rolls = [p["position"] for c, p in sc.calls if c == "timeline.rollback"]
    assert rolls == ["end", 1, 2, 3, 4, 5, "end"]
    assert [(o.variant, o.file) for o in ctx.added] == [("timelapse", "d-timelapse-1080p.mp4"),
                                                        ("timelapse-gif", "d-timelapse.gif")]
    assert (tmp_path / "d-timelapse-1080p.mp4").stat().st_size > 0 and (tmp_path / "d-timelapse.gif").exists()
    assert ctx.report["timelapse"]["frames"] == 5 and not (tmp_path / "_timelapse").exists()
    assert sc.calls[-1] == ("paint", "#c8c8c8")  # put back for later steps


def test_timelapse_skips_above_the_budgets(tmp_path):
    ctx = _tl_ctx(tmp_path, TLSC(5), bodies=["b"] * 3, revisions_timelapse_max_bodies=2)
    timelapse.run(ctx)
    assert "3 bodies is over the timelapse budget of 2" in ctx.report["timelapse"]["skipped"] and not ctx.added
    ctx = _tl_ctx(tmp_path, TLSC(50), revisions_timelapse_max_features=20)
    timelapse.run(ctx)
    assert "50 features is over the timelapse budget of 20" in ctx.report["timelapse"]["skipped"]
    ctx = _tl_ctx(tmp_path, TLSC(1))
    timelapse.run(ctx)
    assert "nothing to build up" in ctx.report["timelapse"]["skipped"]


def test_timelapse_is_a_registered_step_off_by_default(tmp_path):
    step = next(s for s in steps.registered() if s.name == "timelapse")
    assert 80 <= step.order <= 89
    ctx = _tl_ctx(tmp_path, TLSC())
    assert step.when(ctx) is True
    ctx.settings = {}
    assert step.when(ctx) is False


def test_timelapse_frames_go_grey(tmp_path, monkeypatch):
    class Colour(TLSC):
        def screenshot(self, path, camera, w, h):
            a = np.zeros((36, 64, 3), np.uint8)
            a[..., 0] = 220  # a red body part-way through the history
            Image.fromarray(a).save(path)

    seen = {}
    def encode(frames, mp4, gif, w):
        seen["px"] = np.asarray(Image.open(sorted(frames.glob("*.png"))[0]))[0, 0].tolist()
        mp4.write_bytes(b"x")
        gif.write_bytes(b"x")

    monkeypatch.setattr(timelapse, "encode", encode)
    ctx = _tl_ctx(tmp_path, Colour(3))
    timelapse.run(ctx)
    r, g, b = seen["px"]
    assert max(r, g, b) - min(r, g, b) <= 8 and ctx.report["timelapse"]["clamped"] > 0
