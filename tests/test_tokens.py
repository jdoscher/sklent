"""The design-system guards: the vendored Kist tokens haven't drifted, Sklent's CSS
uses only tokens (no colours of its own), and every font size is on the type scale."""

import hashlib
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "sklent" / "web"
CSS = WEB / "css"
KIST = CSS / "kist-tokens.css"
LOCK = CSS / "kist-tokens.lock.json"
SK = CSS / "sk-tokens.css"
TOKEN_FILES = {KIST.name, SK.name}


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _defined(css: str) -> set[str]:
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", _strip_comments(css)))


def _declarations(css: str):
    """(property, value) for every declaration in every leaf block."""
    for body in re.findall(r"\{([^{}]*)\}", _strip_comments(css)):
        for decl in body.split(";"):
            if ":" in decl:
                prop, value = decl.split(":", 1)
                yield prop.strip(), value.strip()


def _area_css() -> dict[str, str]:
    return {str(p.relative_to(CSS)): p.read_text() for p in sorted(CSS.rglob("*.css")) if p.name not in TOKEN_FILES}


def test_vendored_kist_tokens_match_the_pinned_hash():
    lock = json.loads(LOCK.read_text())
    digest = hashlib.sha256(KIST.read_bytes()).hexdigest()
    assert digest == lock["sha256"], (
        "css/kist-tokens.css differs from its pinned copy. Never edit it by hand: run "
        "scripts/sync_kist_tokens.py <kist checkout>, which rewrites it and the lock.")
    head = KIST.read_text()[:400]
    assert lock["kist_tag"] in head and lock["kist_commit"] in head


def test_the_sync_script_reproduces_the_copy_from_a_kist_checkout(tmp_path):
    """Rebuild from a fake checkout made of the copy's own two sources: same bytes out."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync", WEB.parents[1] / "scripts" / "sync_kist_tokens.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)  # type: ignore[union-attr]
    text = KIST.read_text()
    after_scale = text.split("/* ---- web/src/styles.css :root scale ---- */\n", 1)[1]
    scale, themes = after_scale.split("\n/* ---- web/src/themes.css ---- */\n", 1)
    src = tmp_path / "web" / "src"
    src.mkdir(parents=True)
    (src / "styles.css").write_text("/* header */\n" + scale + "\n* {\n  box-sizing: border-box;\n}\n")
    (src / "themes.css").write_text(themes)
    lock = json.loads(LOCK.read_text())
    sync.kist_version = lambda _k: (lock["kist_tag"], lock["kist_commit"])
    body, new_lock = sync.build(tmp_path)
    assert body == text and new_lock["sha256"] == lock["sha256"]


def test_sk_tokens_define_only_sk_names_from_kist_tokens():
    names = _defined(SK.read_text())
    assert names and all(n.startswith("--sk-") for n in names), sorted(n for n in names if not n.startswith("--sk-"))
    known = _defined(KIST.read_text()) | names
    used = set(re.findall(r"var\((--[a-z0-9-]+)", _strip_comments(SK.read_text())))
    assert used <= known, sorted(used - known)
    for prop, value in _declarations(SK.read_text()):
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", value), f"{prop}: {value}"


def test_every_var_used_in_web_css_exists():
    known = _defined(KIST.read_text()) | _defined(SK.read_text())
    for name, css in _area_css().items():
        used = set(re.findall(r"var\((--[a-z0-9-]+)", _strip_comments(css)))
        local = _defined(css)
        assert used <= known | local, f"{name}: undefined {sorted(used - known - local)}"
        assert not {n for n in local if not n.startswith("--sk-")}, f"{name} defines tokens; put them in sk-tokens.css"


def test_no_colours_outside_the_token_files():
    colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\b(white|black|red|green|blue|gray|grey)\b")
    for name, css in _area_css().items():
        for prop, value in _declarations(css):
            if prop.startswith("--") or prop in ("font-family", "content", "animation", "grid-template-areas"):
                continue
            assert not colour.search(value), f"{name}: `{prop}: {value}` — use a Kist token or an --sk-* one"


def test_font_sizes_are_on_the_type_scale():
    """Kist's type-scale rule: --fs-1..6 (or Sklent's --sk-fs-*). An exception needs a
    `type-scale: allow` comment on the same line (16 px phone fields: iOS zooms smaller ones)."""
    for name, css in _area_css().items():
        for line in css.splitlines():
            m = re.search(r"font-size:\s*([^;]+)", line)
            if not m or "type-scale: allow" in line:
                continue
            assert re.fullmatch(r"var\(--(sk-)?fs-[a-z0-9-]+\)|inherit", m.group(1).strip()), f"{name}: {line.strip()}"


def test_fonts_ship_with_their_licences():
    fonts = WEB / "fonts"
    for woff, lic in [("inter-latin-wght-normal.woff2", "OFL-Inter.txt"),
                      ("instrument-serif-latin-400-normal.woff2", "OFL-InstrumentSerif.txt"),
                      ("jetbrains-mono-latin-wght-normal.woff2", "OFL-JetBrainsMono.txt")]:
        assert (fonts / woff).stat().st_size > 10_000
        assert "SIL Open Font License" in (fonts / lic).read_text()
    assert "ISC License" in (WEB / "js" / "LICENSE-lucide.txt").read_text()
