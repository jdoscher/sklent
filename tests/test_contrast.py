"""WCAG contrast over every text/surface pair the UI uses, in all three themes.

A port of Kist's web/src/contrast.ts (the same maths, parser and PAIRS), run on the
vendored css/kist-tokens.css, plus the pairs Sklent adds on top (U1/U2 reviews).
4.5 = text (WCAG 1.4.3); 3 = UI parts, focus rings and large text (1.4.11).
"""

import re
from pathlib import Path

import pytest

TOKENS = Path(__file__).resolve().parents[1] / "sklent" / "web" / "css" / "kist-tokens.css"
THEMES = ("dark", "light", "gallery")


def parse_hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    full = "".join(c * 2 for c in h) if len(h) == 3 else h[:6]
    return tuple(int(full[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(rgb: tuple[int, int, int]) -> float:
    def lin(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(parse_hex(a)), luminance(parse_hex(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def parse_themes(css: str) -> dict[str, dict[str, str]]:
    """`[data-theme='x'] { --name: #hex; }` blocks -> tokens per theme (Kist's parseThemes)."""
    out: dict[str, dict[str, str]] = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        names = re.findall(r"data-theme='([a-z]+)'", sel)
        if not names:
            continue
        found = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", body))
        for n in names:
            out.setdefault(n, {}).update(found)
    return out


# Kist v2.0.0's PAIRS (web/src/contrast.ts), unchanged
KIST_PAIRS = [
    ("text", "bg", 4.5, "body text"),
    ("text", "bg-raised", 4.5, "text on panels"),
    ("text", "bg-hover", 4.5, "text on buttons"),
    ("text", "bg-active", 4.5, "text on pressed buttons"),
    ("text-dim", "bg", 4.5, "secondary text"),
    ("text-dim", "bg-raised", 4.5, "secondary text on panels"),
    ("text-dim", "bg-hover", 4.5, "secondary text on hover"),
    ("text", "chrome", 4.5, "text in the top bar and side panels"),
    ("text-dim", "chrome", 4.5, "secondary text in the top bar and side panels"),
    ("accent", "chrome", 4.5, "links in the top bar and side panels"),
    ("accent", "bg", 4.5, "links"),
    ("accent", "bg-raised", 4.5, "links on panels"),
    ("on-accent", "accent", 4.5, "label on an accent fill (pick stamps, badges)"),
    ("on-accent", "accent-hover", 4.5, "label on an accent fill, hover"),
    ("on-primary", "primary", 4.5, "primary button label"),
    ("on-primary", "primary-hover", 4.5, "primary button label, hover"),
    ("primary-line", "chrome", 3, "primary button edge in the top bar"),
    ("primary-line", "bg", 3, "primary button edge"),
    ("primary-line", "bg-float", 3, "primary button edge in dialogs"),
    ("text", "accent-soft", 4.5, "selected row / chip text"),
    ("present-text", "present-grey", 4.5, "Present: caption title on the grey surround"),
    ("present-text-dim", "present-grey", 4.5, "Present: caption credit on the grey surround"),
    ("present-text", "present-black", 4.5, "Present: caption title on the black surround"),
    ("present-text-dim", "present-black", 4.5, "Present: caption credit on the black surround"),
    ("soft-dim", "accent-soft", 4.5, "counts on a selected row"),
    ("selected-line", "accent-soft", 3, "selected-row outline"),
    ("selected-line", "bg-active", 3, "pressed-toggle outline"),
    ("selected-line", "chrome", 3, "selected outline against the chrome"),
    ("selected-line", "float-hover", 3, "active palette row outline"),
    ("selected-line", "phone-fill", 3, "phone: pressed toggle outline"),
    ("preview-dim", "preview-soft", 3, "selected outline in the preview and compare"),
    ("preview-dim", "preview-active", 3, "pressed-toggle outline in the preview"),
    ("field-border", "bg", 3, "field outline"),
    ("field-border", "bg-raised", 3, "field outline on panels"),
    ("focus", "bg", 3, "focus ring"),
    ("focus", "bg-raised", 3, "focus ring on panels"),
    ("star", "bg-raised", 3, "rating stars"),
    ("danger", "bg", 4.5, "error text"),
    ("danger", "bg-raised", 4.5, "error text on panels"),
    ("danger-on", "danger-bg", 4.5, "server banner"),
    ("success", "bg-raised", 3, "done marker"),
    ("warn", "bg-raised", 3, "warning icon"),
    ("info", "bg-raised", 4.5, "info text"),
    ("canvas-text", "canvas", 4.5, "grid heading on the canvas"),
    ("canvas-dim", "canvas", 4.5, "grid counts on the canvas"),
    ("canvas-focus", "canvas", 3, "tile focus ring"),
    ("field-border", "canvas", 3, "edge of a stack's second sheet on the canvas"),
    ("accent", "bg-active", 3, "bar on a pressed toggle / selected section"),
    ("chip-text", "chip-bg", 4.5, "tag / folder / board chips"),
    ("text-dim", "chip-bg", 4.5, "counts on chips"),
    ("on-accent", "canvas-focus", 4.5, "tile selection check"),
    ("text", "phone-fill", 4.5, "phone: filled controls (top bar row two, sheet actions)"),
    ("danger", "phone-fill", 3, "phone: the sheet's Trash icon"),
    ("text", "phone-sunken", 4.5, "phone: search pill text"),
    ("text-dim", "phone-sunken", 4.5, "phone: search pill placeholder"),
    ("preview-text", "preview-capsule", 4.5, "phone preview: capsule buttons"),
    ("preview-star", "preview-capsule", 3, "phone preview: stars in their capsule"),
    ("text", "bg-float", 4.5, "text on menus, dialogs, palette"),
    ("text-dim", "bg-float", 4.5, "secondary text on menus and dialogs"),
    ("accent", "bg-float", 4.5, "links on menus and dialogs"),
    ("focus", "bg-float", 3, "focus ring on menus and dialogs"),
    ("field-border", "bg-float", 3, "field outline in dialogs"),
    ("danger", "bg-float", 4.5, "error text in dialogs"),
    ("text", "float-hover", 4.5, "hovered / active menu row"),
    ("text-dim", "float-hover", 4.5, "secondary text on a hovered menu row"),
    ("accent", "float-hover", 3, "active-row bar in the palette"),
    ("preview-text", "preview-bg", 4.5, "text in the full-screen preview"),
    ("preview-dim", "preview-bg", 4.5, "secondary text in the preview"),
    ("preview-accent", "preview-bg", 4.5, "links and focus ring in the preview"),
    ("preview-text", "preview-raised", 4.5, "preview buttons"),
    ("preview-text", "preview-hover", 4.5, "preview buttons, hover"),
    ("preview-text", "preview-active", 4.5, "preview buttons, pressed"),
    ("preview-accent", "preview-raised", 3, "focus ring on preview buttons"),
    ("preview-line", "preview-bg", 3, "field outline in the preview"),
    ("preview-on-accent", "preview-accent", 4.5, "primary button in the preview"),
    ("preview-text", "preview-panel", 4.5, "notes panel text"),
    ("preview-dim", "preview-panel", 4.5, "notes panel secondary text"),
    ("preview-danger", "preview-panel", 4.5, "error text in the notes panel"),
    ("preview-text", "preview-soft", 4.5, "selected chip in the preview"),
    ("preview-soft-dim", "preview-soft", 4.5, "counts on a selected chip in the preview"),
]

# Sklent's own text/surface pairs (sklent/web/css): everything Kist's list doesn't cover
SKLENT_PAIRS = [
    ("canvas-text", "tile-wait", 4.5, "words and progress % on a tile still waiting for its render"),
    ("danger", "canvas", 4.5, "a failed design's reason in its label strip"),
    ("text", "canvas", 4.5, "the filter field's text on the canvas"),
    ("text-dim", "canvas", 4.5, "the filter field's placeholder on the canvas"),
    ("field-border", "chrome", 3, "the URL field outline and the status dot's ring in the top bar"),
    ("success", "chrome", 3, "Kist status dot: connected"),
    ("danger", "chrome", 3, "Kist status dot: unreachable; a source's error icon"),
    ("danger", "chrome", 4.5, "a failed job's state word in the sidebar"),
    ("selected-line", "bg-float", 3, "the chosen palette's outline in settings"),
    ("text", "accent-soft", 4.5, "the chosen palette and theme rows"),
    ("preview-dim", "preview-hover", 4.5, "sheet schedule: sizes on a hovered row"),
    ("preview-danger", "preview-bg", 4.5, "sheet: the failure reason"),
    ("preview-text", "preview-capsule", 4.5, "phone sheet: the close capsule"),
    ("danger-on", "danger-bg", 4.5, "the Remove button in the confirm dialog"),
]


@pytest.fixture(scope="module")
def themes() -> dict[str, dict[str, str]]:
    t = parse_themes(TOKENS.read_text())
    assert set(THEMES) <= set(t), f"themes found: {sorted(t)}"
    return t


def test_the_port_matches_kists_maths():
    assert round(contrast("#ffffff", "#000000"), 2) == 21.0
    assert round(contrast("#f5f5f5", "#5c5c5c"), 2) == 6.13  # U1's "title 6.13" in gallery
    assert parse_hex("#fff") == (255, 255, 255)
    assert parse_hex("#ffffff47") == (255, 255, 255)  # alpha ignored, as Kist does


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("fg,bg,minimum,what", KIST_PAIRS + SKLENT_PAIRS)
def test_pair(themes, theme, fg, bg, minimum, what):
    t = themes[theme]
    assert fg in t and bg in t, f"{theme}: missing --{fg if fg not in t else bg}"
    ratio = contrast(t[fg], t[bg])
    assert ratio >= minimum, f"{theme}: --{fg} on --{bg} ({what}) is {ratio:.2f}, needs {minimum}"


def test_known_failures_stay_designed_out(themes):
    """U1/U2 measured these failing in gallery; the CSS must not use them for text."""
    g = themes["gallery"]
    assert contrast(g["canvas-dim"], g["tile-wait"]) < 4.5
    assert contrast(g["danger"], g["tile-wait"]) < 4.5
    css = "\n".join(p.read_text() for p in sorted(TOKENS.parent.rglob("*.css")) if p.name != TOKENS.name)
    # the waiting tile's placeholder text is --canvas-text, never --canvas-dim or --danger
    block = re.search(r"\.fig \.placeholder \{([^}]*)\}", css)
    assert block and "var(--canvas-text)" in block.group(1)
