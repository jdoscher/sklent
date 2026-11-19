"""Inputs and access (area P): STEP/STL/3MF (F3), linked designs (F14), .sklent.yaml (F25),
branch/PR/tag renders (F12), class sets and deadlines (F28), viewer tokens (F18)."""

import io
import json
import struct
import zipfile
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from sklent import db, jobs, repo_config, service
from sklent.features.inputs import classes, links, refs, tokens
from sklent.render import Output
from sklent.sources import (
    Forge,
    RepoInfo,
    SourceError,
    TreeFile,
    design_format,
    drop_mesh_exports,
    git_blob_sha,
    is_design_path,
    looks_like_design,
    parse_source,
    parse_time,
)

H = {"Authorization": "Bearer test-token-0123456789"}
SC = b'{\n"format": "solidcraft/58", "name": "x"}'
STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;"
STL_ASCII = b"solid box\n facet normal 0 0 1\n outer loop\n"


def binary_stl(n: int = 2) -> bytes:
    return b"\0" * 80 + struct.pack("<I", n) + b"\0" * 50 * n


def three_mf() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def assembly(*paths: str, packaged: bool = False) -> bytes:
    doc = {"format": "solidcraft/58", "name": "asm",
           "links": {str(i + 1): {"path": p} for i, p in enumerate(paths)}}
    if not packaged:
        return json.dumps(doc).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("container.json", "{}")
        z.writestr("document.json", json.dumps(doc))
    return buf.getvalue()


# ---------------------------------------------------------------- a fake forge

class FakeForge:
    """Trees and files per repo; `commits` per repo for deadline lookups."""

    files: dict[str, dict[str, bytes]] = {}
    commits: dict[str, list[tuple[str, str]]] = {}  # repo -> [(sha, iso date)] newest first
    repos: list[str] = []
    pulls: dict[int, dict] = {}
    pull_paths: dict[int, list[str]] = {}
    fetched: list[str] = []

    def __init__(self, *a, **k):
        pass

    @classmethod
    def reset(cls):
        cls.files, cls.commits, cls.repos, cls.pulls, cls.pull_paths, cls.fetched = {}, {}, [], {}, {}, []

    def list_repos(self, owner):
        return [RepoInfo(owner, r, "main") for r in self.repos]

    def repo_info(self, owner, repo):
        return RepoInfo(owner, repo, "main")

    def resolve(self, owner, repo, ref):
        if ref.startswith("pull/"):
            return self.pulls[int(ref[5:])]["head_sha"]
        return f"head-{repo}-{ref}".ljust(40, "0")[:40]

    def tree(self, owner, repo, sha):
        files = self.files.get(f"{repo}@{sha}") or self.files.get(repo, {})
        return [TreeFile(p, git_blob_sha(d), len(d)) for p, d in files.items()]

    def fetch(self, owner, repo, sha, path, max_bytes):
        self.fetched.append(path)
        files = self.files.get(f"{repo}@{sha}") or self.files.get(repo, {})
        if path not in files:
            raise SourceError(f"could not download {path} (404)")
        return files[path]

    def blob_url(self, owner, repo, sha, path):
        return f"https://github.com/{owner}/{repo}/blob/{sha}/{path}"

    def pull(self, owner, repo, number):
        return self.pulls[number]

    def pull_files(self, owner, repo, number):
        return self.pull_paths[number]

    def commit_before(self, owner, repo, ref, until):
        for sha, when in self.commits.get(repo, []):
            if parse_time(when) <= until:
                return sha, when
        return None


@pytest.fixture
def client():
    """The app with its lifespan (MCP needs it). The MCP session manager runs once per
    instance, so let the next test start it again."""
    from sklent.app import app
    from sklent.mcp_server import mcp

    with TestClient(app) as c:
        yield c
    mcp.session_manager._has_started = False


@pytest.fixture
def forge(monkeypatch):
    FakeForge.reset()
    monkeypatch.setattr(jobs, "Forge", FakeForge)
    return FakeForge


def designs_by_path(source_id=None):
    return {d["path"]: d for d in service.list_designs(source_id=source_id)}


def fake_render(monkeypatch, seen: list | None = None):
    def render_set(local, out_dir, stem, opts, progress, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{stem}-shaded-social-8.png").write_bytes(b"png")
        if seen is not None:
            seen.append({"local": local, "opts": opts, "settings": kw.get("settings")})
        return [Output(f"{stem}-shaded-social-8.png", "shaded", "social", 8, 8)], {
            "bodies": 1, "bounds_mm": [[0, 0, 0], [95, 66, 32]], "options": {"palette": opts.palette}}
    monkeypatch.setattr(jobs, "render_set", render_set)


# ---------------------------------------------------------------- F3: formats

def test_design_formats_and_sniffing():
    assert [design_format(p) for p in ("a.sc", "b.SOLIDCRAFT", "c.Step", "d.stp", "e.STL", "f.3mf", "g.scad")] == \
        ["sc", "sc", "step", "step", "stl", "3mf", None]
    assert is_design_path("x.stl") and not is_design_path("x.stl", ["sc", "step"])
    assert is_design_path("x.sc", ["step"])  # SolidCraft's own files are always found
    assert looks_like_design(STEP, "a.step") and not looks_like_design(SC, "a.step")
    assert looks_like_design(STL_ASCII, "a.stl") and looks_like_design(binary_stl(3), "a.stl")
    assert not looks_like_design(binary_stl(3)[:-1], "a.stl")
    assert looks_like_design(three_mf(), "a.3mf") and not looks_like_design(b"PK\x03\x04junk", "a.3mf")
    assert looks_like_design(SC, "a.sc") and not looks_like_design(STEP, "a.sc")
    assert git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"  # `git hash-object`


def test_mesh_exports_next_to_a_design_are_skipped():
    paths = ["parts/case.sc", "parts/case.stl", "parts/case.3mf", "parts/lid.stl", "other/case.stl"]
    assert drop_mesh_exports(paths) == {"parts/case.stl", "parts/case.3mf"}


def test_scan_finds_step_stl_3mf_and_respects_the_format_settings(forge):
    forge.files["r"] = {"parts/case.sc": SC, "parts/case.stl": STL_ASCII, "robot.step": STEP,
                        "bracket.stl": binary_stl(), "kit.3mf": three_mf(), "tests/fix.stl": STL_ASCII,
                        "notes.scad": b"cube();"}
    src = jobs.add_source("https://github.com/o/r", auto_render=False)
    jobs.scan(src["id"])
    assert set(designs_by_path()) == {"parts/case.sc", "robot.step", "bracket.stl", "kit.3mf"}
    jobs.set_options({"inputs_mesh": False})
    jobs.scan(src["id"])
    live = {p for p, d in designs_by_path().items() if d["status"] != "removed"}
    assert live == {"parts/case.sc", "robot.step"}
    assert designs_by_path()["robot.step"]["format"] == "step"
    with pytest.raises(ValueError):
        jobs.set_options({"inputs_step": "yes"})


def test_a_source_naming_one_mesh_renders_it_even_when_meshes_are_off(forge):
    forge.files["r"] = {"parts/case.sc": SC, "parts/case.stl": STL_ASCII}
    jobs.set_options({"inputs_mesh": False})
    src = jobs.add_source("https://github.com/o/r/blob/main/parts/case.stl", auto_render=False)
    jobs.scan(src["id"])
    assert set(designs_by_path()) == {"parts/case.stl"}


def test_render_downloads_a_step_file_and_reports_its_format(forge, monkeypatch, settings):
    forge.files["r"] = {"robot.step": STEP}
    seen: list = []
    fake_render(monkeypatch, seen)
    src = jobs.add_source("https://github.com/o/r", auto_render=False)
    jobs.scan(src["id"])
    d = designs_by_path()["robot.step"]
    assert "rendered 1 file" in jobs.render(d["id"])
    assert seen[0]["local"].name == "robot.step"
    rep = json.loads((settings.renders_dir / d["id"] / d["blob"][:12] / "report.json").read_text())
    assert rep["inputs"] == {"format": "step"}


def test_a_file_that_is_not_what_its_name_says_fails_clearly(forge, monkeypatch):
    forge.files["r"] = {"robot.step": b"<html>404</html>"}
    fake_render(monkeypatch)
    src = jobs.add_source("https://github.com/o/r", auto_render=False)
    jobs.scan(src["id"])
    with pytest.raises(SourceError, match="not a STEP file"):
        jobs.render(designs_by_path()["robot.step"]["id"])


def test_github_lfs_pointer_is_fetched_from_media():
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 9\n"
    hits = []

    def handler(request: httpx.Request):
        hits.append(request.url.host)
        if request.url.host == "api.github.com":
            return httpx.Response(200, content=pointer)
        return httpx.Response(200, content=STL_ASCII)

    f = Forge("github", "https://github.com", httpx.Client(transport=httpx.MockTransport(handler)))
    assert f.fetch("o", "r", "c" * 40, "big.stl", 2**20) == STL_ASCII
    assert hits == ["api.github.com", "media.githubusercontent.com"]


# ---------------------------------------------------------------- F14: linked designs

def test_design_links_from_json_and_packaged_designs():
    assert links.design_links(assembly("parts/lid.sc", "../common/fan.sc")) == ["parts/lid.sc", "../common/fan.sc"]
    assert links.design_links(assembly("parts/lid.sc", packaged=True)) == ["parts/lid.sc"]
    assert links.design_links(SC) == [] and links.design_links(b"PK\x03\x04junk") == []
    assert links.resolve_link("asm/top.sc", "../parts/lid.sc") == "parts/lid.sc"
    assert links.resolve_link("top.sc", "../escape.sc") is None
    assert links.resolve_link("top.sc", "/home/me/lid.sc") is None


def test_render_fetches_linked_designs_and_rekeys_the_assembly(forge, monkeypatch, settings):
    lid_v1, lid_v2 = SC + b" ", SC + b"  "
    forge.files["r"] = {"asm/top.sc": assembly("../parts/lid.sc", "sub.sc"),
                        "asm/sub.sc": assembly("../parts/fan.sc"),
                        "parts/lid.sc": lid_v1, "parts/fan.sc": SC}
    seen: list = []
    fake_render(monkeypatch, seen)
    src = jobs.add_source("https://github.com/o/r", auto_render=False)
    jobs.scan(src["id"])
    top = designs_by_path()["asm/top.sc"]
    own = top["blob"]
    jobs.render(top["id"])
    assert seen[0]["local"].parts[-3:] == ("repo", "asm", "top.sc")
    # the work folder is gone after the render, but the fetch order shows recursion
    assert forge.fetched[:4] == ["asm/top.sc", "parts/lid.sc", "asm/sub.sc", "parts/fan.sc"]
    row = links.row(top["id"])
    assert [d["path"] for d in row["deps"]] == ["parts/lid.sc", "asm/sub.sc", "parts/fan.sc"]
    rekeyed = jobs.get_design(top["id"])
    assert rekeyed["blob_sha"] != own and rekeyed["rendered_sha"] == rekeyed["blob_sha"]
    assert row["own_blob"] == own

    # editing a linked part changes the assembly's key: the next scan marks it changed
    jobs.scan(src["id"])
    assert jobs.get_design(top["id"])["status"] == "rendered"
    forge.files["r"]["parts/lid.sc"] = lid_v2
    msg = jobs.scan(src["id"])
    assert jobs.get_design(top["id"])["status"] == "new"
    assert "new or changed" in msg
    out = service.design_out(jobs.get_design(top["id"]))
    assert [d["path"] for d in out["inputs"]["links"]] == ["parts/lid.sc", "asm/sub.sc", "parts/fan.sc"]


def test_a_missing_linked_file_keeps_the_saved_copy(forge, monkeypatch):
    forge.files["r"] = {"top.sc": assembly("parts/gone.sc", "/abs/x.sc")}
    fake_render(monkeypatch)
    src = jobs.add_source("https://github.com/o/r", auto_render=False)
    jobs.scan(src["id"])
    top = designs_by_path()["top.sc"]
    jobs.render(top["id"])
    row = links.row(top["id"])
    assert row["deps"] == [{"path": "parts/gone.sc", "blob": None, "missing": True}]
    assert any("outside the repo" in n for n in row["notes"]) and any("saved copy" in n for n in row["notes"])


class FakeSC:
    def __init__(self, links_reply):
        self.calls = []
        self.links_reply = links_reply

    def execute(self, command, **params):
        self.calls.append((command, params))
        return {"links": self.links_reply} if command == "component.links" else {}

    def tool(self, name, **args):
        self.calls.append((name, args))


def test_open_hook_updates_changed_links_and_reopens_y_up_step(tmp_path):
    (tmp_path / "parts").mkdir()
    top = tmp_path / "asm" / "top.sc"
    top.parent.mkdir()
    top.write_bytes(assembly("../parts/lid.sc", "../parts/fan.sc"))
    sc = FakeSC([{"component": 1, "path": "../parts/lid.sc", "found": True, "changed": True},
                 {"component": 2, "path": "../parts/fan.sc", "found": True, "changed": False}])
    links.on_open(sc, top)
    assert ("component.update_links", {"components": [1]}) in sc.calls
    rep = links.report_for(top)
    assert rep["updated"] == 1 and len(rep["links"]) == 2
    assert links.allow_paths(top) == [tmp_path.resolve()]

    step = tmp_path / "robot.step"
    step.write_bytes(STEP)
    (tmp_path / "robot.step.sklent.json").write_text('{"up": "y"}')
    sc = FakeSC([])
    links.on_open(sc, step)
    assert sc.calls == [("open", {"path": str(step), "up": "y"})]
    assert links.report_for(step) == {"format": "step", "up": "y"}


def test_solidcraft_runs_the_open_hooks(monkeypatch, tmp_path):
    from sklent import solidcraft

    started = {}

    class Proc:
        def __init__(self, args, **kw):
            started["args"] = args
            self.stdin = io.StringIO()
            self.stdout = io.StringIO('{"jsonrpc": "2.0", "id": 1, "result": {}}\n')
            self.stderr = io.StringIO()
            self.pid = 1

    monkeypatch.setattr(solidcraft.subprocess, "Popen", Proc)
    called = []
    monkeypatch.setattr(solidcraft, "OPEN_HOOKS", [lambda sc, d: called.append(d)])
    monkeypatch.setattr(solidcraft, "ALLOW_PATH_HOOKS", [lambda d: [tmp_path / "extra"]])
    solidcraft.SolidCraft(tmp_path / "d.sc", tmp_path / "out")
    assert called == [tmp_path / "d.sc"]
    assert started["args"][-2:] == ["--allow-path", str(tmp_path / "extra")]


# ---------------------------------------------------------------- F25: .sklent.yaml

def test_parse_validates_and_reports():
    data, errors = repo_config.parse(b"""
name: Mounts
license: MIT
include: parts/**
formats: [sc, mesh, scad]
highlight: Lid
steps: [{title: Base, parts: [Base]}, {nope: 1}]
up: x
wat: 1
designs:
  case.sc: {title: Case, colour: red}
""")
    assert data["licence"] == "MIT" and data["include"] == ["parts/**"] and data["highlight"] == ["Lid"]
    assert data["formats"] == ["sc", "stl", "3mf"]
    assert data["steps"] == [{"title": "Base", "parts": ["Base"]}]
    assert data["designs"] == {"case.sc": {"title": "Case"}}
    assert "up" not in data
    joined = " | ".join(errors)
    for bit in ("scad", "steps[2]", "up: must be y or z", "wat: unknown", "designs.case.sc.colour"):
        assert bit in joined
    assert repo_config.parse(b"- a list")[1] == ["expected a mapping at the top level"]
    assert "not valid YAML" in repo_config.parse(b"a: [1,")[1][0]
    assert repo_config.parse(b"!!python/object/apply:os.system ['echo hi']")[1][0].startswith("not valid YAML")
    assert repo_config.parse(b"x" * (repo_config.MAX_BYTES + 1))[0] == {}


@pytest.mark.parametrize("path, pattern, hit", [
    ("parts/a.sc", "parts/**", True), ("parts/x/a.sc", "parts/*.sc", False), ("parts/x/a.sc", "parts/**/*.sc", True),
    ("parts/a.sc", "parts/**/*.sc", True), ("deep/x/old.stl", "old.stl", True), ("old/a.sc", "old/", True),
    ("a.SC", "*.sc", True), ("ab.sc", "a?.sc", True), ("abc.sc", "a?.sc", False), ("b.sc", "[ab].sc", True),
])
def test_globs(path, pattern, hit):
    assert repo_config.glob_match(path, pattern) is hit


def test_resolve_merges_root_then_folder_then_design_entries():
    files = {
        ".sklent.yaml": {"blob": "r", "errors": [], "data": repo_config.parse(b"""
licence: MIT
bom: hw/bom.yaml
settings: {palette: white, seconds: 6, fps: 60, views_exploded: true}
exclude: ["**/old/**"]
""")[0]},
        "parts/.sklent.yml": {"blob": "p", "errors": ["x: unknown key (ignored)"], "data": repo_config.parse(b"""
include: ["/*.sc", "kit/*"]
bom: ../hw/parts.yaml
settings: {palette: cool-grey}
designs:
  case.sc: {title: Pi case, highlight: [Lid], settings: {styles: [shaded]}}
""")[0]},
    }
    from sklent.jobs import register_setting
    register_setting("views_exploded", False, bool)
    cfg = repo_config.resolve("parts/case.sc", files)
    assert cfg["included"] and cfg["licence"] == "MIT" and cfg["title"] == "Pi case" and cfg["highlight"] == ["Lid"]
    assert cfg["bom"] == "hw/parts.yaml"
    assert cfg["settings"] == {"palette": "cool-grey", "seconds": 6, "views_exploded": True, "styles": ["shaded"]}
    assert any("fps" in e for e in cfg["errors"]) and any("parts/.sklent.yml: x" in e for e in cfg["errors"])
    assert [f["path"] for f in cfg["from"]] == [".sklent.yaml", "parts/.sklent.yml"]
    assert not repo_config.resolve("parts/sub/deep.sc", files)["included"]  # not in the folder's include
    assert repo_config.resolve("parts/kit/a.stl", files)["included"]
    assert not repo_config.resolve("x/old/a.sc", files)["included"]
    assert repo_config.resolve("top.sc", files)["settings"]["palette"] == "white"
    assert repo_config.resolve("anything.sc", {}) == {}


def test_repo_cannot_switch_on_posting_or_pick_a_colour():
    clean, errors = repo_config.clean_settings({"palette": "red", "inputs_review_post": True, "inputs_mesh": True})
    assert clean == {} and len(errors) == 3


def test_scan_applies_repo_config_and_render_uses_its_settings(forge, monkeypatch, settings):
    forge.files["r"] = {
        ".sklent.yaml": b"settings: {palette: white, styles: [shaded]}\nexclude: [drafts/**]\nformats: [sc]\n"
                        b"designs: {case.sc: {title: Case, licence: CC-BY-4.0}}\nbogus: 1\n",
        "case.sc": SC, "drafts/x.sc": SC, "robot.step": STEP}
    src = jobs.add_source("https://github.com/o/r", auto_render=False)
    msg = jobs.scan(src["id"])
    assert set(designs_by_path()) == {"case.sc"}
    assert "bogus: unknown key" in msg
    d = designs_by_path()["case.sc"]
    assert d["config"]["title"] == "Case" and d["config"]["licence"] == "CC-BY-4.0"
    assert d["config"]["from"][0]["path"] == ".sklent.yaml" and d["config"]["commit"]
    assert repo_config.get(d["id"])["settings"] == {"palette": "white", "styles": ["shaded"]}
    assert jobs.get_options(d["id"]).palette == "white" and jobs.get_options().palette == "cool-grey"
    seen: list = []
    fake_render(monkeypatch, seen)
    jobs.render(d["id"])
    assert seen[0]["opts"].palette == "white" and seen[0]["opts"].styles == ["shaded"]
    # the config file is fetched once per blob, not on every scan
    n = forge.fetched.count(".sklent.yaml")
    jobs.scan(src["id"])
    assert forge.fetched.count(".sklent.yaml") == n


def test_for_local_reads_configs_up_to_the_git_root(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".sklent.yaml").write_text("licence: MIT\nsettings: {palette: white}\n")
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / ".sklent.yaml").write_text("designs: {lid.sc: {title: Lid}}\n")
    cfg = repo_config.for_local(tmp_path / "parts" / "lid.sc")
    assert cfg["licence"] == "MIT" and cfg["title"] == "Lid" and cfg["settings"] == {"palette": "white"}


# ---------------------------------------------------------------- F12: refs and PRs

GH, FJ = "https://github.com", "https://forge.example.com"


@pytest.mark.parametrize("url, ref", [
    ("https://github.com/o/r/pull/12", "pull/12"),
    ("https://github.com/o/r/pull/12/files", "pull/12"),
    ("https://forge.example.com/o/r/pulls/7", "pull/7"),
    ("https://github.com/o/r/tree/v1.2", "v1.2"),
    ("https://github.com/o/r/releases/tag/v1.2", "v1.2"),
    ("https://forge.example.com/o/r/src/tag/rev-B", "rev-B"),
    ("https://github.com/o/r/commit/" + "a" * 40, "a" * 40),
])
def test_ref_urls(url, ref):
    s = parse_source(url)
    assert (s.kind, s.ref, s.path) == ("repo", ref, None)
    assert parse_source(s.canonical_url) == s


def test_branch_refs_show_unless_they_are_the_default(forge):
    forge.files["r"] = {"a.sc": SC}
    dev = jobs.add_source("https://github.com/o/r/tree/dev", auto_render=False)
    main = jobs.add_source("https://github.com/o/r/tree/main", auto_render=False)
    jobs.scan(dev["id"])
    jobs.scan(main["id"])
    by_source = {d["source_id"]: d for d in service.list_designs()}
    assert by_source[dev["id"]]["ref_info"] == {"kind": "ref", "label": "dev"}
    assert by_source[main["id"]]["ref_info"] is None
    assert by_source[dev["id"]]["id"] != by_source[main["id"]]["id"]  # keyed by source + ref


def test_pull_urls_are_forge_specific_and_prefix_urls_round_trip():
    with pytest.raises(SourceError):
        parse_source("https://github.com/o/r/pulls/1")
    with pytest.raises(SourceError):
        parse_source("https://forge.example.com/o/r/pull/1")
    assert parse_source("https://github.com/o/r/pull/3").canonical_url == "https://github.com/o/r/pull/3"
    assert parse_source("https://forge.example.com/o/r/pulls/3").canonical_url == FJ + "/o/r/pulls/3"
    s = parse_source("https://github.com/school?prefix=bracket-hw-")
    assert (s.kind, s.owner, s.prefix) == ("account", "school", "bracket-hw-")
    assert parse_source(s.canonical_url) == s
    assert parse_source("https://github.com/orgs/school/repositories").owner == "school"


def gh_pull_handler(request: httpx.Request):
    p = request.url.path
    if p.endswith("/pulls/5"):
        return httpx.Response(200, json={"title": "Thicker lid", "state": "open",
                                         "html_url": "https://github.com/o/r/pull/5",
                                         "head": {"sha": "h" * 40, "ref": "lid"},
                                         "base": {"sha": "b" * 40, "ref": "main"}})
    if p.endswith("/pulls/5/files"):
        page = int(request.url.params["page"])
        return httpx.Response(200, json=[{"filename": "lid.sc", "status": "modified"},
                                         {"filename": "old.sc", "status": "removed"}] if page == 1 else [])
    raise AssertionError(p)


def test_forge_pull_calls():
    f = Forge("github", GH, httpx.Client(transport=httpx.MockTransport(gh_pull_handler)))
    assert f.resolve("o", "r", "pull/5") == "h" * 40
    assert f.pull("o", "r", 5)["base_ref"] == "main"
    assert f.pull_files("o", "r", 5) == ["lid.sc"]


def test_pr_source_renders_changed_designs_and_their_assemblies_apart_from_main(forge, monkeypatch):
    main = {"lid.sc": SC, "case.sc": SC + b" ", "asm.sc": assembly("lid.sc"), "other.sc": SC + b"  "}
    forge.files["r"] = main
    fake_render(monkeypatch)
    base = jobs.add_source("https://github.com/o/r", auto_render=False)
    jobs.scan(base["id"])
    for d in service.list_designs(source_id=base["id"]):
        jobs.render(d["id"])  # records asm.sc's link to lid.sc
    forge.pulls[5] = {"number": 5, "title": "Thicker lid", "state": "open", "html_url": "https://github.com/o/r/pull/5",
                      "head_sha": "h" * 40, "head_ref": "lid", "base_sha": "b" * 40, "base_ref": "main"}
    forge.pull_paths[5] = ["lid.sc", "README.md"]
    forge.files["r@" + "h" * 40] = {**main, "lid.sc": SC + b"\n\n"}
    pr = service.render_url("https://github.com/o/r/pull/5")
    assert pr["source"]["ref"] == "pull/5"
    pr_designs = designs_by_path(pr["source"]["id"])
    assert set(pr_designs) == {"lid.sc", "asm.sc"}
    assert {d["ref"] for d in pr_designs.values()} == {"pull/5"}
    assert all(d["commit"] == "h" * 10 for d in pr_designs.values())
    # main's designs are untouched
    main_paths = {d["path"] for d in service.list_designs(source_id=base["id"])}
    assert main_paths == {"lid.sc", "case.sc", "asm.sc", "other.sc"}
    assert pr_designs["lid.sc"]["ref_info"]["label"] == "PR #5"
    assert pr_designs["lid.sc"]["ref_info"]["title"] == "Thicker lid"

    for d in pr_designs.values():
        jobs.render(d["id"])
    md = refs.review_comment(pr["source"]["id"], "https://sk.example.com")["markdown"]
    assert "PR #5 · Thicker lid" in md and "`lid` → `main`" in md
    assert "| Before · main" in md and "https://sk.example.com/api/designs/" in md
    assert "95 × 66 × 32 mm" in md and "1 body" in md
    assert "token" not in md

    with pytest.raises(PermissionError):
        refs.post_review_comment(pr["source"]["id"], "https://sk.example.com")


def test_posting_the_review_comment_when_switched_on(forge, monkeypatch):
    forge.pulls[5] = {"number": 5, "title": "t", "head_sha": "h" * 40, "head_ref": "x", "base_ref": "main"}
    forge.pull_paths[5] = []
    src = jobs.add_source("https://github.com/o/r/pull/5", auto_render=False)
    jobs.scan(src["id"])
    jobs.set_options({"inputs_review_post": True})
    posted = {}

    class PostForge(FakeForge):
        def post_comment(self, owner, repo, number, body):
            posted.update(owner=owner, repo=repo, number=number, body=body)
            return "https://github.com/o/r/pull/5#issuecomment-1"

    monkeypatch.setattr("sklent.sources.Forge", PostForge)
    out = refs.post_review_comment(src["id"], "https://sk.example.com")
    assert out["url"].endswith("issuecomment-1") and posted["number"] == 5
    assert refs.pull_of(src["id"])["posted_url"] == out["url"]


def test_forge_post_comment_hits_the_issue_comments_endpoint():
    sent = {}

    def handler(request):
        sent["url"], sent["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(201, json={"html_url": "https://forge.example.com/o/r/pulls/7#c1"})

    f = Forge("forgejo", FJ, httpx.Client(transport=httpx.MockTransport(handler)))
    assert f.post_comment("o", "r", 7, "hi").endswith("#c1")
    assert sent == {"url": FJ + "/api/v1/repos/o/r/issues/7/comments", "body": {"body": "hi"}}


def test_review_comment_api_and_setting_gate(forge, client):
    forge.pulls[5] = {"number": 5, "title": "t", "head_sha": "h" * 40, "head_ref": "x", "base_ref": "main"}
    forge.pull_paths[5] = []
    if True:
        c = client
        sid = c.post("/api/sources", json={"url": "https://github.com/o/r/pull/5", "scan": False}, headers=H).json()
        sid = sid["source"]["id"]
        r = c.get(f"/api/sources/{sid}/review-comment", headers=H).json()
        assert r["post_enabled"] is False and r["markdown"].startswith("### Sklent renders · PR #5")
        assert c.post(f"/api/sources/{sid}/review-comment", headers=H).status_code == 403


# ---------------------------------------------------------------- F28: class sets and deadlines

def test_commit_before_checks_dates_and_pages_back():
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        page = int(request.url.params["page"])
        # a forge that ignores `until`: newest first, two pages
        commits = [[{"sha": "c3", "commit": {"committer": {"date": "2026-11-21T08:00:00Z"}}},
                    {"sha": "c2", "commit": {"committer": {"date": "2026-11-21T01:00:00Z"}}}],
                   [{"sha": "c1", "commit": {"committer": {"date": "2026-11-20T23:00:00-08:00"}}}], []][page - 1]
        return httpx.Response(200, json=commits)

    f = Forge("forgejo", FJ, httpx.Client(transport=httpx.MockTransport(handler)))
    due = parse_time("2026-11-21T07:59:00Z")  # 23:59 PST on the 20th
    assert f.commit_before("o", "r", "main", due) == ("c2", "2026-11-21T01:00:00Z")
    assert calls[0]["until"] == "2026-11-21T07:59:00Z" and calls[0]["sha"] == "main"
    assert f.commit_before("o", "r", "main", parse_time("2026-11-01T00:00:00")) is None


def test_class_set_renders_the_deadline_commit_and_lists_who_is_missing(forge, monkeypatch):
    forge.repos = ["bracket-hw-maya", "bracket-hw-sam", "bracket-hw-lee", "other-repo"]
    for r in forge.repos:
        forge.files[r] = {"bracket.sc": SC + r.encode()}
    forge.files["bracket-hw-lee"] = {"README.md": b"nothing yet"}
    forge.commits = {"bracket-hw-maya": [("m2", "2026-11-21T09:00:00Z"), ("m1", "2026-11-20T20:00:00Z")],
                     "bracket-hw-sam": [("s1", "2026-11-22T09:00:00Z")],
                     "bracket-hw-lee": [("l1", "2026-11-19T09:00:00Z")]}
    from sklent.features.inputs import add_class
    out = add_class("https://github.com/school", prefix="bracket-hw-", deadline="2026-11-20T23:59:00-08:00",
                    roster=["maya, Maya R.", "sam", "lee", "kim"], title="Bracket HW", auto_render=False, scan=False)
    sid = out["source"]["id"]
    assert out["source"]["url"] == "https://github.com/school?prefix=bracket-hw-"
    msg = jobs.scan(sid)
    assert "3 repo(s)" in msg  # other-repo isn't in the class
    ds = service.list_designs(source_id=sid)
    assert [(d["repo"], d["commit"]) for d in ds] == [("school/bracket-hw-maya", "m1")]
    assert ds[0]["ref"] == "main@2026-11-21T07:59Z"
    assert ds[0]["due"]["after_due"] is True and ds[0]["due"]["committed_at"] == "2026-11-20T20:00:00Z"
    view = classes.class_view(sid)
    status = {s["student"]: s["status"] for s in view["students"]}
    assert status == {"maya": "submitted", "sam": "late", "lee": "empty", "kim": "missing"}
    assert view["submitted"] == 1 and view["expected"] == 4
    assert view["missing"] == ["sam", "lee", "kim"]
    assert view["students"][0]["display"] == "Maya R."
    assert view["title"] == "Bracket HW" and view["deadline"] == "2026-11-21T07:59:00+00:00"

    # a later scan keeps the snapshot; a later push doesn't change what renders
    forge.commits["bracket-hw-maya"].insert(0, ("m3", "2026-11-25T09:00:00Z"))
    jobs.scan(sid)
    assert [d["commit"] for d in service.list_designs(source_id=sid)] == ["m1"]


def test_class_api_and_validation(forge, client):
    if True:
        c = client
        bad = c.post("/api/classes", json={"url": "https://github.com/school", "prefix": "hw-", "deadline": "soon"},
                     headers=H)
        assert bad.status_code == 422 and "ISO 8601" in bad.json()["detail"]
        assert c.get("/api/sources", headers=H).json() == []  # nothing stored on a bad request
        r = c.post("/api/classes", json={"url": "https://github.com/school", "prefix": "hw-",
                                         "roster": "maya\nsam\n", "scan": False}, headers=H)
        assert r.status_code == 201
        sid = r.json()["source"]["id"]
        assert [x["source_id"] for x in c.get("/api/classes", headers=H).json()] == [sid]
        r = c.put(f"/api/sources/{sid}/class", json={"deadline": "2026-12-01T17:00:00Z", "scan": False}, headers=H)
        assert r.json()["class"]["deadline"] == "2026-12-01T17:00:00+00:00"
        assert r.json()["class"]["roster"] == ["maya", "sam"]
        assert c.get(f"/api/sources/{sid}/class", headers=H).json()["expected"] == 2


# ---------------------------------------------------------------- F18: viewer tokens

def mcp_call(c, headers, method, params=None):
    return c.post("/mcp", headers={**headers, "Accept": "application/json, text/event-stream"},
                  json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def test_viewer_tokens_are_hashed_listed_and_revoked():
    t = tokens.create("Freshman build team")
    assert t["token"].startswith("skv") and len(t["token"]) == 35 and t["token"].isalnum()
    with db.connect() as conn:
        stored = conn.execute("SELECT * FROM inputs_viewer_tokens").fetchone()
    assert t["token"] not in json.dumps(dict(stored))
    assert tokens.lookup(t["token"])["name"] == "Freshman build team"
    assert tokens.list_tokens()[0]["last_used_at"]
    assert "token" not in tokens.list_tokens()[0]
    tokens.revoke(t["id"])
    assert tokens.lookup(t["token"]) is None
    with pytest.raises(ValueError):
        tokens.create("  ")


def test_viewer_can_browse_and_download_but_not_change_anything(forge, monkeypatch, settings, client):
    forge.files["r"] = {"case.sc": SC}
    fake_render(monkeypatch)
    if True:
        c = client
        made = c.post("/api/tokens", json={"name": "Students"}, headers=H)
        assert made.status_code == 201
        v = {"Authorization": f"Bearer {made.json()['token']}"}
        src = c.post("/api/sources", json={"url": "https://github.com/o/r", "scan": False, "auto_render": False},
                     headers=H).json()
        jobs.scan(src["source"]["id"])
        d = service.list_designs()[0]
        jobs.render(d["id"])
        d = service.list_designs()[0]

        assert c.get("/api/whoami", headers=v).json() == {"role": "viewer", "name": "Students"}
        assert c.get("/api/whoami", headers=H).json()["role"] == "admin"
        assert c.get("/api/designs", headers=v).status_code == 200
        assert c.get("/api/settings", headers=v).status_code == 200
        assert c.get(d["files"][0]["url"], headers=v).content == b"png"
        c.cookies.set("sk_token", made.json()["token"])
        assert c.get(d["files"][0]["url"]).status_code == 200  # <img> tags ride the cookie
        c.cookies.clear()
        for method, path, body in [("post", "/api/sources", {"url": "https://github.com/o/x"}),
                                   ("post", f"/api/designs/{d['id']}/render", {}),
                                   ("put", "/api/settings", {"palette": "white"}),
                                   ("delete", f"/api/sources/{src['source']['id']}", None),
                                   ("post", "/api/render-url", {"url": "https://github.com/o/x"}),
                                   ("post", "/api/tokens", {"name": "more"})]:
            r = c.request(method.upper(), path, json=body, headers=v)
            assert r.status_code == 403, (method, path, r.status_code)
        assert c.get("/api/tokens", headers=v).status_code == 403
        assert c.get("/api/tokens", headers=H).json()[0]["name"] == "Students"

        assert mcp_call(c, v, "tools/list").status_code == 200
        ok = mcp_call(c, v, "tools/call", {"name": "list_designs", "arguments": {}})
        assert ok.status_code == 200 and "error" not in ok.json()
        ok = mcp_call(c, v, "tools/call", {"name": "list_class_submissions",
                                           "arguments": {"source_id": src["source"]["id"]}})
        assert ok.status_code == 200  # read-only by annotation
        for name, args in [("render_url", {"url": "https://github.com/o/x"}), ("set_render_settings", {}),
                           ("cancel_job", {"job_id": 1}), ("post_review_comment", {"source_id": "x"}),
                           ("some_future_tool", {})]:
            r = mcp_call(c, v, "tools/call", {"name": name, "arguments": args})
            assert r.status_code == 403 and "can only read" in r.json()["error"]["message"], name
        assert mcp_call(c, H, "tools/call", {"name": "list_designs", "arguments": {}}).status_code == 200

        tid = made.json()["id"]
        assert c.delete(f"/api/tokens/{tid}", headers=H).json()["revoked_at"]
        assert c.get("/api/designs", headers=v).status_code == 401


def test_mcp_lists_the_new_tools(client):
    names = {t["name"] for t in mcp_call(client, H, "tools/list").json()["result"]["tools"]}
    assert {"add_class_source", "list_class_submissions", "review_comment", "post_review_comment",
            "get_design_inputs"} <= names


# ---------------------------------------------------------------- CLI

def test_cli_tokens(capsys):
    from sklent.cli import main
    assert main(["token", "create", "Lab TV"]) == 0
    token = capsys.readouterr().out.strip()
    assert tokens.lookup(token)["name"] == "Lab TV"
    main(["token", "list"])
    tid = capsys.readouterr().out.split()[0]
    assert main(["token", "revoke", tid]) == 0
    assert tokens.lookup(token) is None
    assert main(["token", "revoke", "nope"]) == 1


def test_cli_render_takes_settings_and_local_config(tmp_path, monkeypatch, capsys):
    from sklent import render
    (tmp_path / ".git").mkdir()
    (tmp_path / ".sklent.yaml").write_text("settings: {palette: white, seconds: 6}\nlicence: MIT\n")
    design = tmp_path / "robot.step"
    design.write_bytes(STEP)
    seen = {}

    def fake(design, out_dir, stem, opts, progress, processes=None, settings=None):
        seen.update(opts=opts, settings=settings, stem=stem)
        return [], {"bodies": 1}

    monkeypatch.setattr(render, "render_set", fake)
    from sklent.cli import main
    assert main(["render", str(design), str(tmp_path / "out"), "--seconds", "4",
                 "--settings", '{"styles": ["shaded"], "views_exploded": true}']) == 0
    out = json.loads(capsys.readouterr().out)
    assert seen["opts"].palette == "white" and seen["opts"].seconds == 4 and seen["opts"].styles == ["shaded"]
    assert seen["settings"]["views_exploded"] is True and seen["stem"] == "robot"
    assert out["report"]["inputs"] == {"format": "step"} and out["report"]["config"]["licence"] == "MIT"
    assert main(["render", str(tmp_path / "x.scad"), str(tmp_path / "out")]) == 2
    assert main(["render", str(design), str(tmp_path / "out"), "--settings", "[1]"]) == 2


def test_parse_time_defaults_to_utc():
    assert parse_time("2026-11-20T23:59:00") == datetime(2026, 11, 20, 23, 59, tzinfo=UTC)


# ---------------------------------------------------------------- web

def test_inputs_web_modules_and_css_follow_the_design_rules():
    import re

    import test_tokens as tt
    web = tt.WEB
    features = (web / "js" / "features.js").read_text()
    for name in ("inputs-access", "inputs-sources", "inputs-classes"):
        js = web / "js" / "features" / f"{name}.js"
        assert f"import './features/{name}.js';" in features
        for names, target in re.findall(r"^import\s+\{([^}]+)\}\s+from\s+'(\.[^']+)'", js.read_text(), re.M):
            src = (js.parent / target).resolve()
            assert src.is_file(), f"{name} imports {target}"
            for n in (x.strip() for x in names.split(",")):
                exported = re.search(rf"export (async )?(function|const|let) {n}\b", src.read_text())
                assert exported, f"{target} has no {n}"
    css = (web / "css" / "features" / "inputs.css").read_text()
    assert '<link rel="stylesheet" href="/static/css/features/inputs.css" />' in (web / "index.html").read_text()
    known = tt._defined(tt.KIST.read_text()) | tt._defined(tt.SK.read_text())
    used = set(re.findall(r"var\((--[a-z0-9-]+)", tt._strip_comments(css)))
    assert used <= known, sorted(used - known)
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\b(white|black|red|green|blue|gray|grey)\b")
    for prop, value in tt._declarations(css):
        assert prop.startswith("--") or not colour.search(value), (prop, value)
    for line in css.splitlines():
        m = re.search(r"font-size:\s*([^;]+)", line)
        assert not m or re.fullmatch(r"var\(--(sk-)?fs-[a-z0-9-]+\)", m.group(1).strip()), line
    blocks = re.findall(r"([^{}]+)\{", tt._strip_comments(css))
    selectors = [x.strip() for block in blocks for x in block.split(",")]
    ours = ("body[data-sk-role", ".sk-inputs-", ".sheet-section .sk-inputs-")
    assert len(selectors) > 20 and [x for x in selectors if not x.startswith(ours)] == []
