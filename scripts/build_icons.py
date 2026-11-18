#!/usr/bin/env python3
"""Build Sklent's icon kit from its mark: the S in a ring (Jay, Nov 2026), white on
Kist's #3A3A3A app tile (UI 16a), so the two apps sit together on a home screen.

    python scripts/build_icons.py

Writes into sklent/web/: favicon.svg (the tile), icon-mono.svg (the mark alone, for
`purpose: monochrome`), favicon-32.png, favicon.ico (16/32/48), apple-touch-icon.png
(180), icon-192.png, icon-512.png and icon-maskable-512.png (the mark inside the
maskable safe zone on a full-bleed tile). Needs only Pillow (a sklent dependency): the
mark is drawn from the same construction as the SVG, 8x supersampled.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path(__file__).resolve().parents[1] / "sklent" / "web"

TILE = "#3A3A3A"  # Kist's app tile
MARK = "#FFFFFF"
# on Kist's 64-unit construction: a ring of radius 22 (4 wide) and the S stroke
RING_R, RING_W = 22.0, 4.0
S_PATH = ("M40 23.5c-1.5-3-4.5-4.5-8-4.5-4.5 0-7.5 2.6-7.5 6.2 0 8.3 15.5 4.6 15.5 13.3"
          " 0 3.6-3.3 6.5-8 6.5-3.7 0-6.8-1.8-8.3-4.8")
S_SCALE, S_SHIFT_Y, S_W = 0.906, -0.25, 5.52
CORNER = 14  # tile corner on 64 units


def svg(tile: bool, color: str = MARK) -> str:
    bg = f'<rect width="64" height="64" rx="{CORNER}" fill="{TILE}"/>' if tile else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' + bg
            + f'<circle cx="32" cy="32" r="{RING_R:g}" fill="none" stroke="{color}" stroke-width="{RING_W:g}"/>'
            + f'<g transform="translate(32 32) scale({S_SCALE}) translate(-32 {-32 + S_SHIFT_Y:g})">'
            + f'<path d="{S_PATH}" fill="none" stroke="{color}" stroke-width="{S_W}" stroke-linecap="round"/>'
            + "</g></svg>\n")


def s_points(steps: int = 24) -> list[tuple[float, float]]:
    """The S path (M + relative cubic `c` segments) flattened to points, in 64-unit space."""
    nums = [float(n) for n in re.findall(r"-?\d*\.?\d+", S_PATH)]
    x, y = nums[0], nums[1]
    pts = [(x, y)]
    rest = nums[2:]
    for i in range(0, len(rest), 6):
        x1, y1, x2, y2, x3, y3 = rest[i:i + 6]
        p0, p1, p2, p3 = (x, y), (x + x1, y + y1), (x + x2, y + y2), (x + x3, y + y3)
        for k in range(1, steps + 1):
            t = k / steps
            mt = 1 - t
            pts.append((mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
                        mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]))
        x, y = p3
    # the SVG's transform: about the centre, scaled, nudged up
    return [(32 + (px - 32) * S_SCALE, 32 + (py - 32 + S_SHIFT_Y) * S_SCALE) for px, py in pts]


def raster(size: int, *, tile: bool = True, mark_scale: float = 1.0, full_bleed: bool = False) -> Image.Image:
    ss = 8
    n = size * ss
    u = n / 64  # pixels per unit
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if tile:
        if full_bleed:
            d.rectangle([0, 0, n, n], fill=TILE)
        else:
            d.rounded_rectangle([0, 0, n - 1, n - 1], radius=CORNER * u, fill=TILE)

    def at(p):  # mark space -> pixels, scaled about the centre
        return ((32 + (p[0] - 32) * mark_scale) * u, (32 + (p[1] - 32) * mark_scale) * u)

    r_out = (RING_R + RING_W / 2) * mark_scale * u
    r_in = (RING_R - RING_W / 2) * mark_scale * u
    c = n / 2
    d.ellipse([c - r_out, c - r_out, c + r_out, c + r_out], fill=MARK)
    d.ellipse([c - r_in, c - r_in, c + r_in, c + r_in], fill=TILE if tile else (0, 0, 0, 0))
    w = S_W * S_SCALE * mark_scale * u
    pts = [at(p) for p in s_points()]
    # a round brush stamped along the path: a clean stroke with round caps and joins
    step = max(1.0, w / 10)
    for a, b in zip(pts, pts[1:], strict=False):
        dist = math.dist(a, b)
        for k in range(int(dist / step) + 1):
            t = k * step / dist if dist else 0
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=MARK)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    (WEB / "favicon.svg").write_text(svg(tile=True))
    (WEB / "icon-mono.svg").write_text(svg(tile=False, color="#000000"))
    raster(32).save(WEB / "favicon-32.png")
    raster(48).save(WEB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    # iOS draws its own corners and shows transparency as black: a full-bleed tile
    raster(180, full_bleed=True).save(WEB / "apple-touch-icon.png")
    raster(192).save(WEB / "icon-192.png")
    raster(512).save(WEB / "icon-512.png")
    # maskable: the mark inside the 80 % safe circle on a full-bleed tile
    raster(512, full_bleed=True, mark_scale=0.8 * 64 / (2 * (RING_R + RING_W / 2)) * 0.9).save(
        WEB / "icon-maskable-512.png")
    print("wrote", ", ".join(sorted(p.name for p in WEB.glob("*") if p.suffix in (".png", ".ico", ".svg"))))


if __name__ == "__main__":
    main()
