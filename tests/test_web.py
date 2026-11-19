"""The web shell holds together without a JS toolchain: every asset index.html names
is served, every ES-module import resolves, the phase-2 seams are exported, and code
is served for revalidation so an upgrade never runs stale modules."""

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from sklent.app import app

WEB = Path(__file__).resolve().parents[1] / "sklent" / "web"


def _client() -> TestClient:
    return TestClient(app)  # no lifespan: no worker or MCP session needed for static files


def test_every_asset_in_index_html_is_served():
    html = (WEB / "index.html").read_text()
    refs = set(re.findall(r'(?:href|src)="(/[^"]+)"', html))
    assert any(r.startswith("/static/js/main.js") for r in refs)
    c = _client()
    for ref in sorted(refs):
        r = c.get(ref)
        assert r.status_code == 200, ref


def test_module_imports_resolve():
    for js in (WEB / "js").rglob("*.js"):
        for target in re.findall(r"^\s*import\s+(?:[^'\"]+\s+from\s+)?['\"](\.[^'\"]+)['\"]", js.read_text(), re.M):
            assert (js.parent / target).resolve().is_file(), f"{js.name} imports {target}"


def test_code_is_revalidated_and_typed():
    c = _client()
    r = c.get("/static/js/main.js")
    assert r.headers["cache-control"] == "no-cache"
    assert "javascript" in r.headers["content-type"]
    assert c.get("/static/css/base.css").headers["cache-control"] == "no-cache"
    m = c.get("/static/manifest.webmanifest")
    assert m.headers["content-type"].startswith("application/manifest+json")
    for icon in json.loads(m.text)["icons"]:
        assert c.get(icon["src"]).status_code == 200, icon["src"]


def test_phase_two_seams_are_exported():
    seams = {
        "detail.js": ["registerDetailSection", "registerTitleBlockField", "openDetail"],
        "sidebar.js": ["registerSidebarSection"],
        "tiles.js": ["registerTileBadge"],
        "settings.js": ["registerSettingsGroup"],
        "api.js": ["api"],
    }
    for name, fns in seams.items():
        src = (WEB / "js" / name).read_text()
        for fn in fns:
            assert re.search(rf"export (async )?function {fn}\(", src), f"{name} must export {fn}"
    assert "import './features.js';" in (WEB / "js" / "main.js").read_text()


def test_no_inline_script_or_hex_in_markup_besides_theme_color():
    html = (WEB / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "scripts are files (CSP-friendly)"
    hexes = re.findall(r"#[0-9a-fA-F]{6}\b", html)
    assert hexes == ["#5C5C5C"]  # the theme-color meta, rewritten by theme-init.js
