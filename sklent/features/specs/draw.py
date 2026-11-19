"""Drafting primitives for the specs sheets, drawn with Pillow in the U2 look.

Paper and ink come from Kist's light theme (the vendored `web/css/kist-tokens.css`), so a
printed sheet matches the app: the page is `--bg`, values are `--text`, labels `--text-dim`,
the one 3:1 frame line is `--field-border` and cell rules are `--text` mixed 28 % into the
page (`--sk-sheet-rule`). Type is the app's three faces (vendored in `web/fonts`): Inter for
words, JetBrains Mono for spec values, Instrument Serif for titles.

The truth rule holds here too: every line either carries a measured value or separates two
real things, and a field with no data shows "—".
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WEB = Path(__file__).resolve().parents[2] / "web"
FONTS = WEB / "fonts"
TOKENS = WEB / "css" / "kist-tokens.css"

# Fallbacks equal to Kist v2.0.0's light theme, used only if the token file can't be read.
_FALLBACK = {"bg": "#faf9f6", "text": "#1c1b19", "text-dim": "#5f5d57", "field-border": "#8a877f"}

Rgb = tuple[int, int, int]


def _hex(v: str) -> Rgb:
    v = v.strip().lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


@lru_cache
def light_tokens() -> dict[str, str]:
    """The `[data-theme='light']` custom properties of the vendored Kist tokens."""
    out = dict(_FALLBACK)
    try:
        css = TOKENS.read_text()
    except OSError:
        return out
    m = re.search(r"\[data-theme='light'\]\s*\{(.*?)\}", css, re.S)
    if m:
        for name, value in re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", m.group(1)):
            out[name] = value
    return out


def mix(a: Rgb, b: Rgb, t: float) -> Rgb:
    """`color-mix(in srgb, a t, b)`."""
    return tuple(round(a[i] * t + b[i] * (1 - t)) for i in range(3))  # type: ignore[return-value]


@dataclass(frozen=True)
class Ink:
    paper: Rgb
    text: Rgb
    dim: Rgb
    frame: Rgb
    rule: Rgb


@lru_cache
def ink() -> Ink:
    t = light_tokens()
    paper, text = _hex(t["bg"]), _hex(t["text"])
    return Ink(paper=paper, text=text, dim=_hex(t["text-dim"]), frame=_hex(t["field-border"]),
               rule=mix(text, paper, 0.28))


# ---------------------------------------------------------------- type

FACES = {
    "ui": "inter-latin-wght-normal.woff2",
    "mono": "jetbrains-mono-latin-wght-normal.woff2",
    "serif": "instrument-serif-latin-400-normal.woff2",
}


@lru_cache(maxsize=64)
def font(face: str, size: int, weight: int = 400) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A vendored face at a pixel size; variable faces take a weight. Falls back to Pillow's
    default font if the woff2 can't be loaded (a FreeType without brotli)."""
    try:
        f = ImageFont.truetype(str(FONTS / FACES[face]), max(6, int(size)))
        if face in ("ui", "mono"):
            try:
                f.set_variation_by_axes([weight])
            except (OSError, ValueError):
                pass
        return f
    except OSError:
        return ImageFont.load_default(max(6, int(size)))


def text_w(f, s: str) -> int:
    left, _, right, _ = f.getbbox(s)
    return int(right - left)


def fit(f_face: str, size: int, s: str, width: int, weight: int = 400, min_size: int = 8):
    """The largest size up to `size` at which `s` fits in `width` px."""
    while size > min_size and text_w(font(f_face, size, weight), s) > width:
        size -= 1
    return font(f_face, size, weight)


def ellipsize(f, s: str, width: int) -> str:
    if text_w(f, s) <= width:
        return s
    while s and text_w(f, s + "…") > width:
        s = s[:-1]
    return s + "…"


def fmt_mm(v: float | None) -> str:
    """'95', '32.5', '0.8': millimetres to 0.1 mm, without a trailing .0."""
    if v is None:
        return "—"
    v = abs(v)
    return f"{v:.0f}" if v >= 100 else f"{v:.1f}".rstrip("0").rstrip(".")


def fmt_num(v: float | None, digits: int = 3) -> str:
    """A value to `digits` significant figures with thousands separators."""
    if v is None:
        return "—"
    if v == 0:
        return "0"
    mag = math.floor(math.log10(abs(v)))
    dec = max(0, digits - 1 - mag)
    return f"{v:,.{dec}f}"


def envelope(bounds) -> str | None:
    """[[x,y,z],[x,y,z]] → '95 × 66 × 32' (W × D × H, mm)."""
    if not bounds or len(bounds) != 2:
        return None
    return " × ".join(fmt_mm(bounds[1][i] - bounds[0][i]) for i in range(3))


# ---------------------------------------------------------------- the sheet

class Sheet:
    """A page: paper, one frame, hairlines, text and dimension lines.

    `u` is the line unit in px (1 px up to 1,600 px wide, 2 px on an A3 sheet), so every
    line is one narrow width and the hierarchy is tone, not weight (U2)."""

    def __init__(self, width: int, height: int, *, unit: int | None = None):
        self.ink = ink()
        self.im = Image.new("RGB", (width, height), self.ink.paper)
        self.d = ImageDraw.Draw(self.im)
        self.w, self.h = width, height
        self.u = unit or max(1, round(max(width, height) / 1700))

    # lines
    def hline(self, x0: float, x1: float, y: float, colour: Rgb | None = None) -> None:
        self.d.rectangle([round(x0), round(y), round(x1), round(y) + self.u - 1], fill=colour or self.ink.rule)

    def vline(self, x: float, y0: float, y1: float, colour: Rgb | None = None) -> None:
        self.d.rectangle([round(x), round(y0), round(x) + self.u - 1, round(y1)], fill=colour or self.ink.rule)

    def line(self, p0, p1, colour: Rgb | None = None) -> None:
        self.d.line([tuple(map(round, p0)), tuple(map(round, p1))], fill=colour or self.ink.dim, width=self.u)

    def rect(self, box, colour: Rgb | None = None) -> None:
        x0, y0, x1, y1 = box
        c = colour or self.ink.frame
        self.hline(x0, x1, y0, c)
        self.hline(x0, x1, y1 - self.u + 1, c)
        self.vline(x0, y0, y1, c)
        self.vline(x1 - self.u + 1, y0, y1, c)

    def frame(self, inset: int) -> tuple[int, int, int, int]:
        """The sheet's one frame (the 3:1 line), inset from the edge; returns its box."""
        box = (inset, inset, self.w - inset, self.h - inset)
        self.rect(box, self.ink.frame)
        return box

    # text
    def text(self, xy, s: str, f, colour: Rgb | None = None, anchor: str = "la") -> None:
        self.d.text((round(xy[0]), round(xy[1])), s, font=f, fill=colour or self.ink.text, anchor=anchor)

    def caps(self, xy, s: str, size: int, colour: Rgb | None = None, anchor: str = "la") -> None:
        """A caps label: Inter 600, the title-block and section-label voice."""
        self.text(xy, s.upper(), font("ui", size, 600), colour or self.ink.dim, anchor)

    def rotated_text(self, center, s: str, f, colour: Rgb | None = None) -> None:
        """Text reading bottom-to-top (ISO 129: a vertical dimension is read from the right)."""
        tw = text_w(f, s) + 4
        asc, desc = f.getmetrics() if hasattr(f, "getmetrics") else (f.size, 0)
        tile = Image.new("RGBA", (tw, asc + desc + 4), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((2, 2), s, font=f, fill=(*(colour or self.ink.text), 255))
        tile = tile.rotate(90, expand=True)
        self.im.paste(tile, (round(center[0] - tile.width / 2), round(center[1] - tile.height / 2)), tile)

    # images
    def paste(self, im: Image.Image, xy) -> None:
        if im.mode == "RGBA":
            self.im.paste(im, (round(xy[0]), round(xy[1])), im)
        else:
            self.im.paste(im, (round(xy[0]), round(xy[1])))

    # dimension lines (ISO 129-1)
    def dimension(self, a, b, side: str, offset: float, label: str, size: int) -> None:
        """A dimension between feature points a and b (px), drawn `offset` px away on `side`
        (above|below for a horizontal measure, left|right for a vertical one): extension
        lines start a small gap off the feature and run ~8 line widths past the dimension
        line; oblique-stroke terminators; the value in mono above (or left of) the line."""
        u = self.u
        gap, over, tick = 4 * u, 8 * u, 5 * u
        f = font("mono", size, 400)
        c = self.ink.dim
        if side in ("above", "below"):
            sgn = -1 if side == "above" else 1
            y = (min(a[1], b[1]) if sgn < 0 else max(a[1], b[1])) + sgn * offset
            for x, yf in (a, b):
                self.line((x, yf + sgn * gap), (x, y + sgn * over), c)
            self.line((a[0] - over, y), (b[0] + over, y), c)
            for x in (a[0], b[0]):
                self.line((x - tick, y + tick), (x + tick, y - tick), self.ink.text)
            self.text(((a[0] + b[0]) / 2, y - max(3 * u, round(size * 0.3))), label, f, self.ink.text, anchor="mb")
        else:
            sgn = -1 if side == "left" else 1
            x = (min(a[0], b[0]) if sgn < 0 else max(a[0], b[0])) + sgn * offset
            for xf, yy in (a, b):
                self.line((xf + sgn * gap, yy), (x + sgn * over, yy), c)
            self.line((x, a[1] - over), (x, b[1] + over), c)
            for yy in (a[1], b[1]):
                self.line((x - tick, yy + tick), (x + tick, yy - tick), self.ink.text)
            th = f.getbbox(label)[3]
            self.rotated_text((x - max(3 * u, round(size * 0.3)) - th / 2, (a[1] + b[1]) / 2), label, f, self.ink.text)

    def save(self, path: Path, **kw) -> Path:
        self.im.save(path, **kw)
        return path


# ---------------------------------------------------------------- the title block

@dataclass
class Cell:
    label: str
    value: str | None
    wide: bool = False
    kind: str = "mono"  # mono | serif (the title) | ui


def _rows(cells: Iterable[Cell]) -> list[list[Cell]]:
    """Halves pair up two to a row; a half left alone takes the whole row."""
    rows: list[list[Cell]] = []
    pending: list[Cell] = []
    for c in cells:
        if c.wide:
            if pending:
                rows.append(pending)
                pending = []
            rows.append([c])
        else:
            pending.append(c)
            if len(pending) == 2:
                rows.append(pending)
                pending = []
    if pending:
        rows.append(pending)
    return rows


def _row_h(r: list[Cell], label_size: int, value_size: int, title_size: int) -> int:
    pad = round(label_size * 0.9)
    lab_h = round(label_size * 1.35)
    if r[0].kind == "serif":
        return pad + lab_h + round(title_size * 1.2) + round(value_size * 1.25) + pad
    return pad + lab_h + round(value_size * 1.2) + pad


def title_block_height(cells: Iterable[Cell], *, label_size: int, value_size: int, title_size: int) -> int:
    return sum(_row_h(r, label_size, value_size, title_size) for r in _rows(cells))


def title_block(sheet: Sheet, box: tuple[int, int, int, int], cells: Iterable[Cell], *,
                label_size: int, value_size: int, title_size: int, corner: str | None = None) -> int:
    """An ISO 7200-style block sitting on the bottom of `box`: a caps label over each value,
    cells split by hairlines, the block's top and left edges in the frame tone. `corner`
    goes in the title cell's top right (`Sheet 01 / 03`). Returns the block's top y."""
    x0, _, x1, y1 = box
    rows = _rows(cells)
    pad = round(label_size * 0.9)
    lab_h = round(label_size * 1.35)
    total = sum(_row_h(r, label_size, value_size, title_size) for r in rows)
    y = top = y1 - total
    sheet.hline(x0, x1, y, sheet.ink.frame)
    sheet.vline(x0, y, y1, sheet.ink.frame)
    for i, r in enumerate(rows):
        h = _row_h(r, label_size, value_size, title_size)
        if i:
            sheet.hline(x0, x1, y, sheet.ink.rule)
        cols = [(x0, x1)] if len(r) == 1 else [(x0, (x0 + x1) // 2), ((x0 + x1) // 2, x1)]
        for (cx0, cx1), c in zip(cols, r, strict=False):
            if cx0 != x0:
                sheet.vline(cx0, y, y + h, sheet.ink.rule)
            sheet.caps((cx0 + pad, y + pad), c.label, label_size)
            if c.kind == "serif" and i == 0 and corner:
                sheet.caps((cx1 - pad, y + pad), corner, label_size, anchor="ra")
            vy = y + pad + lab_h
            avail = cx1 - cx0 - 2 * pad
            if c.kind == "serif":
                title, _, sub = (c.value or "—").partition("\n")
                f = fit("serif", title_size, title, avail)
                sheet.text((cx0 + pad, vy), ellipsize(f, title, avail), f)
                if sub:
                    fs = font("mono", round(value_size * 0.85))
                    sheet.text((cx0 + pad, vy + round(title_size * 1.2)), ellipsize(fs, sub, avail), fs,
                               sheet.ink.dim)
            else:
                f = font("mono" if c.kind == "mono" else "ui", value_size)
                v = c.value if c.value not in (None, "") else "—"
                sheet.text((cx0 + pad, vy), ellipsize(f, v, avail), f)
        y += h
    return top


# ---------------------------------------------------------------- render cut-outs

def cutout(shot: Path | Image.Image, plate: Path | Image.Image, *, tol: int = 6, soft: int = 28) -> Image.Image:
    """The part from a SolidCraft screenshot as RGBA, without its background.

    Headless screenshots always sit on the theme's gradient and have no alpha (see
    docs/spike.md). A screenshot of the same size with nothing in front of the camera
    (the `plate`) is exactly that gradient, so the background is every pixel equal to the
    plate (within `tol`) and connected to the image border; enclosed pixels count only when
    they match it almost exactly (a hole through the part). The 1 px rim gets a soft alpha
    from its distance to the plate, so edges don't keep a gradient fringe."""
    a = np.asarray((Image.open(shot) if isinstance(shot, Path) else shot).convert("RGB"), dtype=np.int16)
    p = np.asarray((Image.open(plate) if isinstance(plate, Path) else plate).convert("RGB"), dtype=np.int16)
    if a.shape != p.shape:
        raise ValueError("shot and plate differ in size")
    diff = np.abs(a - p).max(axis=2)
    near = diff <= tol
    h, w = near.shape
    m = np.zeros((h + 2, w + 2), np.uint8)
    m[1:-1, 1:-1] = np.where(near, 255, 0)
    m[0, :] = m[-1, :] = 255
    m[:, 0] = m[:, -1] = 255
    mi = Image.fromarray(m, "L")
    ImageDraw.floodfill(mi, (0, 0), 128, thresh=0)
    reg = np.asarray(mi)[1:-1, 1:-1]
    bg = (reg == 128) | (diff <= 2)
    rim = np.asarray(Image.fromarray(np.where(bg, 255, 0).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(3))) > 0
    alpha = np.where(bg, 0.0, 1.0)
    edge = rim & ~bg
    alpha[edge] = np.clip((diff[edge] - 2) / soft, 0.0, 1.0)
    af = alpha[..., None]
    # un-blend the plate from the rim so the colour is the part's, not the gradient's
    rgb = np.where(af > 0.02, (a - (1 - af) * p) / np.maximum(af, 0.02), a)
    out = np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def opaque_box(im: Image.Image) -> tuple[int, int, int, int] | None:
    """The bounding box (x0, y0, x1, y1 exclusive) of pixels at least half opaque."""
    a = np.asarray(im.getchannel("A")) >= 128
    ys, xs = np.where(a)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
