"""Pillow layouts for the views area: the configuration lineup (F10) and the plate (F16).

Neutral greys only (they pass the colour guard), the vendored fonts (JetBrains Mono for
labels, as the UI's spec voice), and nothing drawn over a part: labels sit under each
cell. The plate's 10 mm grid is a real measure: the plate is an orthographic still at a
known scale.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parents[2] / "web" / "fonts"
PAPER = (244, 245, 247)
INK = (58, 58, 58)
DIM = (120, 124, 130)
HAIR = (201, 204, 209)
# The plate sits on a mid-light bed so white parts (render jobs draw no edges) still read.
BED = (212, 216, 221)
GRID = (201, 205, 210)
GRID_10 = (186, 191, 197)
EDGE = (96, 102, 110)  # the part's silhouette on the plate: render jobs draw no edges


def outlined(im: Image.Image) -> Image.Image:
    """An RGBA part with a 1 px silhouette line just outside it (its true outline in an
    orthographic plan view), so a white part reads on the bed."""
    out = Image.new("RGBA", (im.width + 2, im.height + 2), (0, 0, 0, 0))
    out.paste(im, (1, 1))
    solid = out.getchannel("A").point(lambda v: 255 if v > 24 else 0)
    ring = ImageChops.subtract(solid.filter(ImageFilter.MaxFilter(3)), solid)
    out.paste(Image.new("RGBA", out.size, (*EDGE, 255)), (0, 0), ring)
    return out


def font(size: int, face: str = "jetbrains-mono") -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for p in sorted(FONTS.glob(f"{face}*.woff2")):
        try:
            return ImageFont.truetype(str(p), size)
        except OSError:  # a Pillow without WOFF2 (brotli) support
            break
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, f) -> int:
    return int(draw.textlength(text, font=f))


def _fit_text(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> str:
    if _text_w(draw, text, f) <= width:
        return text
    while text and _text_w(draw, text + "…", f) > width:
        text = text[:-1]
    return text + "…"


def lineup(cells: list[tuple[Path, str, str]], out: Path, *, per_row: int = 4, cell: int = 640,
           title: str = "") -> tuple[int, int]:
    """Stills side by side at one scale (they share a camera), each with a mono label
    (name) and a dim sub-label (values). Returns the image size."""
    cols = min(per_row, max(1, len(cells)))
    rows = math.ceil(len(cells) / cols)
    pad, gap, lab = 48, 24, 64
    top = 72 if title else pad
    w = pad * 2 + cols * cell + (cols - 1) * gap
    h = top + pad + rows * (cell + lab) + (rows - 1) * gap
    sheet = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(sheet)
    f1, f2 = font(22), font(16)
    if title:
        d.text((pad, 28), title, fill=INK, font=font(24))
    for i, (path, name, sub) in enumerate(cells):
        r, c = divmod(i, cols)
        x = pad + c * (cell + gap)
        y = top + r * (cell + lab + gap)
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((cell, cell))
            sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=HAIR, width=1)
        d.text((x, y + cell + 10), _fit_text(d, name, f1, cell), fill=INK, font=f1)
        if sub:
            d.text((x, y + cell + 38), _fit_text(d, sub, f2, cell), fill=DIM, font=f2)
    sheet.save(out)
    return w, h


def plate(cells: list[tuple[Path, str, str]], out: Path, *, px_per_mm: float, width: int = 2400,
          title: str = "") -> tuple[int, int]:
    """Transparent per-part ortho stills (all at `px_per_mm`) packed in rows on a sheet
    with a 10 mm grid (1 mm minor lines when they are at least 6 px apart)."""
    pad, gap, lab = 64, 48, 56
    top = 88 if title else pad
    ims = []
    for path, name, sub in cells:
        im = Image.open(path).convert("RGBA")
        bbox = im.getchannel("A").getbbox()
        if bbox:
            im = outlined(im.crop(bbox))
        ims.append((im, name, sub))
    width = max(width, max((im.width for im, _, _ in ims), default=0) + 2 * pad)
    # shelf packing, tallest first
    order = sorted(range(len(ims)), key=lambda i: -ims[i][0].height)
    placed, x, y, shelf = {}, pad, top, 0
    for i in order:
        im = ims[i][0]
        cw = max(im.width, 220)
        if x > pad and x + cw > width - pad:
            x, y, shelf = pad, y + shelf + lab + gap, 0
        placed[i] = (x, y)
        x += cw + gap
        shelf = max(shelf, im.height)
    height = y + shelf + lab + pad
    used = max((px + max(ims[i][0].width, 220) for i, (px, _) in placed.items()), default=0) + pad
    width = max(min(width, used), 960 if title else 0)  # no empty acres beside a few parts
    sheet = Image.new("RGB", (width, height), BED)
    d = ImageDraw.Draw(sheet)
    minor = px_per_mm >= 6
    step = px_per_mm * (1 if minor else 10)
    k = 0
    while k * step < max(width, height):
        v = k * step
        major = (not minor) or k % 10 == 0
        colour = GRID_10 if major else GRID
        if v < width:
            d.line([(v, 0), (v, height)], fill=colour, width=1)
        if v < height:
            d.line([(0, v), (width, v)], fill=colour, width=1)
        k += 1
    f1, f2 = font(20), font(15)
    if title:
        d.rectangle([0, 0, width, top - 24], fill=BED)
        d.text((pad, 30), title, fill=INK, font=font(24))
    for i, (im, name, sub) in enumerate(ims):
        px, py = placed[i]
        sheet.paste(im, (px, py), im)
        cw = max(im.width, 220)
        d.rectangle([px, py + im.height + 6, px + cw, py + im.height + lab - 4], fill=BED)
        d.text((px, py + im.height + 8), _fit_text(d, name, f1, cw), fill=INK, font=f1)
        if sub:
            d.text((px, py + im.height + 32), _fit_text(d, sub, f2, cw), fill=DIM, font=f2)
    sheet.save(out)
    return width, height
