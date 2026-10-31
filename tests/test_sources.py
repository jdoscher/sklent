import httpx
import pytest

from sklent.sources import (
    Forge,
    SourceError,
    excluded,
    in_scope,
    is_design_path,
    looks_like_design,
    parse_source,
)

GH, FJ = "https://github.com", "https://forge.example.com"


@pytest.mark.parametrize("url, expect", [
    ("https://github.com/jdoscher", ("github", GH, "account", "jdoscher", None, None, None)),
    ("github.com/tl/sc", ("github", GH, "repo", "tl", "sc", None, None)),
    ("tl/sc", ("github", GH, "repo", "tl", "sc", None, None)),
    ("https://github.com/o/r.git", ("github", GH, "repo", "o", "r", None, None)),
    ("git@github.com:o/r.git", ("github", GH, "repo", "o", "r", None, None)),
    ("https://github.com/o/r/blob/main/parts/case.sc", ("github", GH, "repo", "o", "r", "main", "parts/case.sc")),
    ("https://github.com/o/r/tree/dev/parts", ("github", GH, "repo", "o", "r", "dev", "parts")),
    ("https://forge.example.com/jay", ("forgejo", FJ, "account", "jay", None, None, None)),
    ("https://forge.example.com/jay/p/src/branch/main/a/b.sc", ("forgejo", FJ, "repo", "jay", "p", "main", "a/b.sc")),
    ("ssh://git@192.0.2.10:2222/jay/parts.git", ("forgejo", FJ, "repo", "jay", "parts", None, None)),
    ("git@forge.example.com:jay/parts.git", ("forgejo", FJ, "repo", "jay", "parts", None, None)),
])
def test_parse_source(url, expect):
    s = parse_source(url)
    assert (s.provider, s.host, s.kind, s.owner, s.repo, s.ref, s.path) == expect


@pytest.mark.parametrize("url, host", [
    ("ssh://git@192.0.2.10:2222/jay/parts.git", "https://192.0.2.10"),
    ("git@git.example.net:jay/parts.git", "https://git.example.net"),
])
def test_ssh_url_without_configured_forgejo(url, host, monkeypatch):
    from sklent import config

    monkeypatch.setenv("SK_FORGEJO_URL", "")
    config.get_settings.cache_clear()
    s = parse_source(url)
    assert (s.provider, s.host, s.owner, s.repo) == ("forgejo", host, "jay", "parts")


def test_parse_source_rejects_junk():
    for bad in ("", "https://github.com/", "https://github.com/o/r/issues/4"):
        with pytest.raises(SourceError):
            parse_source(bad)


def test_canonical_url_round_trips():
    for url in ("https://github.com/o/r/tree/main/parts", "https://forge.example.com/jay/p/src/branch/dev/x.sc"):
        s = parse_source(url)
        assert parse_source(s.canonical_url) == s


def test_design_filters():
    assert is_design_path("a/Case.SC") and is_design_path("x.solidcraft")
    assert not is_design_path("a.scad")
    assert excluded("tests/fixtures/a.sc", ["tests"])
    assert excluded("crates/x/tests/a.sc", ["tests"])
    assert not excluded("tests.sc", ["tests"])
    assert excluded("docs/old/a.sc", ["docs/old/*"])
    # chosen on purpose: the scope itself is never excluded, only what's below it
    assert not excluded("tests/designs/pi.sc", ["tests"], "tests/designs/pi.sc")
    assert not excluded("tests/designs/pi.sc", ["tests"], "tests/designs")
    assert excluded("parts/tests/x.sc", ["tests"], "parts")
    assert in_scope("parts/a.sc", "parts") and in_scope("parts/a.sc", "parts/a.sc")
    assert not in_scope("partsx/a.sc", "parts")


def test_looks_like_design():
    assert looks_like_design(b'{\n"format":"solidcraft/21",\n')
    assert looks_like_design(b"PK\x03\x04rest")
    assert not looks_like_design(b"(\n SinOsc.ar(440)\n).play;")  # SuperCollider


def test_forgejo_token_only_goes_to_its_own_host():
    sent = {}

    def handler(request: httpx.Request):
        sent[request.url.host] = request.headers.get("authorization")
        return httpx.Response(200, json={"owner": {"login": "o"}, "name": "r", "default_branch": "main"})

    for host in ("https://forge.example.com", "https://elsewhere.example.org"):
        Forge("forgejo", host, httpx.Client(transport=httpx.MockTransport(handler))).repo_info("o", "r")
    assert sent["forge.example.com"] == "token forgejo-secret"
    assert sent["elsewhere.example.org"] is None
