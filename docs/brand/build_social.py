"""Build Sklent's social preview card (GitHub "Social preview", og:image).

    python docs/brand/build_social.py      # docs/brand/social-preview.png

1280 x 640 on solid #131312 (GitHub: PNG under 1 MB; a solid background because some apps
show transparency badly). Left: the Section mark, the wordmark, the tagline and the proof
line; right: a real render (docs/assets/outputs/still-social.webp, the pi-case design from
tangency-labs/solidcraft, Apache-2.0) on a faint 24 px drafting grid. Words and mark stay
inside the centre 1100 x 540, which every platform shows uncropped.

Needs Pillow and fontTools with brotli (the fonts are the site's woff2 files):
    uv run --no-project --with pillow --with fonttools --with brotli python docs/brand/build_social.py
"""

from __future__ import annotations

import io
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "docs/assets/fonts"
OUT = ROOT / "docs/brand/social-preview.png"
RENDER = ROOT / "docs/assets/outputs/still-social.webp"

W, H = 1280, 640
SAFE_X, SAFE_Y = (W - 1100) // 2, (H - 540) // 2  # 90, 50
BG = (0x13, 0x13, 0x12)
INK = (0xEC, 0xEA, 0xE4)   # text on dark (Kist's palette)
DIM = (0x9C, 0x9A, 0x93)   # text-dim on dark
LINE = (0x2A, 0x2A, 0x28)  # the grid: ink at about 6 % on the background
TILE = (0x3A, 0x3A, 0x3A)  # the app tile
TAGLINE = "Your CAD repo, as a showcase."
PROOF = "Turntables, sheets and listing packs. Self-hosted."

# The Section mark on Kist's 64-unit grid (docs/brand/sklent.svg), four pieces; the cut
# corners' r0.5 is below a pixel at this size, so the pieces are plain polygons and only the
# square's outer r2 corners are rounded (by a mask).
PIECES = [
    [(8, 8), (28, 8), (8, 28)],
    [(35, 8), (52, 8), (8, 52), (8, 35)],
    [(56, 12), (56, 29), (29, 56), (12, 56)],
    [(56, 36), (56, 56), (36, 56)],
]


def font(name: str, size: int, wght: int | None = None) -> ImageFont.FreeTypeFont:
    tt = TTFont(str(FONTS / name))
    tt.flavor = None
    buf = io.BytesIO()
    tt.save(buf)
    f = ImageFont.truetype(io.BytesIO(buf.getvalue()), size)
    if wght is not None:
        try:
            f.set_variation_by_axes([wght])
        except OSError:
            pass
    return f


def mark(size: int, colour, tile=None) -> Image.Image:
    """The mark at `size` px, drawn 8x and scaled down; on the app tile when `tile` is set
    (part spans 16-48 of 64, as in icon-tile.svg)."""
    s = 8
    big = size * s
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if tile:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=14 / 64 * big, fill=tile)
        lo, hi = 16, 48
    else:
        lo, hi = 8, 56
    k = (hi - lo) / 48 * big / 64

    def p(x, y):
        return ((lo + (x - 8) * (hi - lo) / 48) / 64 * big, (lo + (y - 8) * (hi - lo) / 48) / 64 * big)

    part = Image.new("L", (big, big), 0)
    pd = ImageDraw.Draw(part)
    for poly in PIECES:
        pd.polygon([p(x, y) for x, y in poly], fill=255)
    clip = Image.new("L", (big, big), 0)
    ImageDraw.Draw(clip).rounded_rectangle((*p(8, 8), *p(56, 56)), radius=2 * k, fill=255)
    part = Image.composite(part, Image.new("L", (big, big), 0), clip)
    im.paste(Image.new("RGBA", (big, big), colour), (0, 0), part)
    return im.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    card = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(card)

    # right: the render on a drafting grid, bleeding off the right edge
    x0 = 690
    for x in range(x0, W, 24):
        d.line([(x, 0), (x, H)], fill=LINE)
    for y in range(0, H, 24):
        d.line([(x0, y), (W, y)], fill=LINE)
    side = 480
    r = Image.open(RENDER).convert("RGB").resize((side, side), Image.Resampling.LANCZOS)
    m = Image.new("L", (side, side), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, side - 1, side - 1), radius=14, fill=255)
    rx, ry = W - SAFE_X - side, (H - side) // 2
    card.paste(r, (rx, ry), m)
    d.rounded_rectangle((rx, ry, rx + side - 1, ry + side - 1), radius=14, outline=(0x3A, 0x3A, 0x38))

    # left: mark + wordmark, tagline, proof
    lx = SAFE_X + 4
    icon = mark(112, (255, 255, 255, 255), TILE)
    card.paste(icon, (lx, 150), icon)
    word = font("instrument-serif-latin-400-normal.woff2", 128)
    d.text((lx + 140, 150 + 56), "sklent", font=word, fill=INK, anchor="lm")
    tag = font("instrument-serif-latin-400-normal.woff2", 50)
    d.text((lx + 2, 150 + 112 + 70), TAGLINE, font=tag, fill=INK, anchor="ls")
    proof = font("inter-latin-wght-normal.woff2", 22, 400)
    d.text((lx + 4, 150 + 112 + 122), PROOF, font=proof, fill=DIM, anchor="ls")
    mono = font("jetbrains-mono-latin-wght-normal.woff2", 18, 400)
    d.text((lx + 4, H - SAFE_Y - 6), "sklent.app", font=mono, fill=DIM, anchor="ls")

    card.save(OUT, optimize=True)
    print(OUT, card.size, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
