import json

import httpx
from fastapi.testclient import TestClient

from sklent import jobs, service
from sklent.kist import Kist
from sklent.sources import RepoInfo, TreeFile

TREE = {
    "a": [TreeFile("parts/case.sc", "blob1", 100), TreeFile("tests/fix.sc", "blobT", 5),
          TreeFile("README.md", "r", 1), TreeFile("parts/lid.solidcraft", "blob2", 200)],
}


class FakeForge:
    def __init__(self, *a, **k):
        pass

    def list_repos(self, owner):
        return [RepoInfo(owner, "a", "main"), RepoInfo(owner, "forked", "main", fork=True)]

    def repo_info(self, owner, repo):
        return RepoInfo(owner, repo, "main")

    def resolve(self, owner, repo, ref):
        return "c" * 40

    def tree(self, owner, repo, sha):
        return TREE[repo]

    def blob_url(self, owner, repo, sha, path):
        return f"https://github.com/{owner}/{repo}/blob/{sha}/{path}"


def test_scan_finds_designs_skips_tests_and_forks_and_tracks_changes(monkeypatch):
    monkeypatch.setattr(jobs, "Forge", FakeForge)
    src = jobs.add_source("https://github.com/someone")
    msg = jobs.scan(src["id"])
    designs = {d["path"]: d for d in service.list_designs()}
    assert set(designs) == {"parts/case.sc", "parts/lid.solidcraft"}
    assert "2 queued" in msg
    assert all(d["status"] == "queued" for d in designs.values())

    # pretend both rendered, then change one
    from sklent import db
    with db.connect() as conn:
        conn.execute("UPDATE designs SET status = 'rendered', rendered_sha = blob_sha")
        conn.execute("DELETE FROM jobs")
    TREE["a"][0] = TreeFile("parts/case.sc", "blob1b", 100)
    msg = jobs.scan(src["id"])
    assert "1 new or changed, 1 queued" in msg
    TREE["a"][0] = TreeFile("parts/case.sc", "blob1", 100)


def test_overlapping_sources_share_one_design(monkeypatch):
    monkeypatch.setattr(jobs, "Forge", FakeForge)
    account = jobs.add_source("https://github.com/someone")
    jobs.scan(account["id"])
    repo = jobs.add_source("https://github.com/someone/a/tree/main/parts")
    msg = jobs.scan(repo["id"])
    designs = service.list_designs()
    assert len(designs) == 2 and {d["source_id"] for d in designs} == {repo["id"]}
    assert "0 new or changed" in msg


def test_adding_the_same_url_twice_reuses_the_source():
    a = jobs.add_source("https://github.com/o/r")
    b = jobs.add_source("github.com/o/r.git")
    assert a["id"] == b["id"]


def test_enqueue_dedupes_queued_jobs():
    s = jobs.add_source("https://github.com/o/r")
    j1 = jobs.enqueue("scan", source_id=s["id"])
    j2 = jobs.enqueue("scan", source_id=s["id"], force=True)
    assert j1["id"] == j2["id"] and j2["force"] == 1


def test_settings_round_trip_and_reject_colours():
    assert jobs.set_options({"palette": "white", "seconds": 6}).palette == "white"
    assert jobs.get_options().seconds == 6
    for bad in ({"palette": "#ff0000"}, {"nope": 1}):
        try:
            jobs.set_options(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_kist_client_builds_folder_path_and_uploads(tmp_path):
    folders = [{"id": "root", "name": "SolidCraft", "parent_id": None}]
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        assert req.headers["authorization"] == "Bearer kt"
        if req.url.path == "/api/folders" and req.method == "GET":
            return httpx.Response(200, json=folders)
        if req.url.path == "/api/folders":
            body = json.loads(req.content)
            f = {"id": f"f{len(calls)}", **body}
            return httpx.Response(201, json=f)
        if req.url.path == "/api/items":
            assert b'name="folder_ids"' in req.content and b"style:shaded" in req.content
            return httpx.Response(201, json={"item": {"id": "item1"}, "created": True})
        return httpx.Response(200, json={})

    k = Kist("http://kist", "kt", httpx.Client(transport=httpx.MockTransport(handler)))
    fid = k.ensure_folder(["SolidCraft", "o", "r", "case"])
    assert [c for c in calls if c[0] == "POST"] == [("POST", "/api/folders")] * 3
    f = tmp_path / "case-shaded.gif"
    f.write_bytes(b"GIF89a")
    assert k.upload(f, folder_id=fid, tags=["solidcraft", "style:shaded"], notes="n",
                    source_url="u")["id"] == "item1"


def test_api_requires_token_and_lists():
    from sklent.app import app
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/sources").status_code == 401
        h = {"Authorization": "Bearer test-token-0123456789"}
        r = c.post("/api/sources", json={"url": "https://github.com/o/r", "scan": False}, headers=h)
        assert r.status_code == 201
        assert c.get("/api/sources", headers=h).json()[0]["label"] == "o/r"
        assert c.post("/api/sources", json={"url": "https://github.com/o/r/pulls/1"},
                      headers=h).status_code == 422
        assert c.get("/", headers=h).status_code == 200
        r = c.post("/mcp", headers={**h, "Accept": "application/json, text/event-stream"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert {"render_url", "wait_for_job", "view_render", "get_render_set"} <= names
