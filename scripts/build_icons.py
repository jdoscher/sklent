#!/usr/bin/env python3
"""Build Sklent's icon kit from its mark: "Section" (Jay, 2026-11-19).

The mark is a square part cut open by three 45-degree hatch gaps (ISO 128's section
hatch, "/" direction), leaving four solid pieces. It is built like Kist's Corners mark,
so the two sit together as a suite:
- Kist's 64-unit grid, solid filled shapes only (no strokes), so iOS tinting and
  single-colour use work unchanged;
- Kist's "stamped" radii: r2 on the part's outer corners, r0.5 on the cut corners;
- the same three sizes: the bare mark GLYPH (part 8-56), the app tile APP (16-48) and the
  small tab tile TAB (12-52), white on Kist's #3A3A3A tile.

    python scripts/build_icons.py

Writes into sklent/web/:
- favicon.svg: the bare mark in ink that follows the browser's light/dark scheme,
  #2B2B2B / #ECEAE4 (a #3A3A3A tile vanishes on dark browser chrome);
- icon-mono.svg: black, for `purpose: monochrome`;
- mark.svg: the bare mark in `currentColor`, for inline use;
- favicon-32.png and favicon.ico (16/32/48): the TAB tile, each size drawn at that size;
- apple-touch-icon.png (180, full bleed), icon-192.png and icon-512.png (APP tile);
- icon-maskable-512.png: the APP mark at 0.8 on a full-bleed tile, inside the safe circle.
Also writes the SVG masters to docs/brand/. It needs only Pillow (a sklent dependency):
shapes are filled polygons with their fillets flattened, drawn 8x supersampled.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "sklent" / "web"
BRAND = ROOT / "docs" / "brand"

TILE = "#3A3A3A"  # Kist's app tile
MARK = "#FFFFFF"
INK_LIGHT, INK_DARK = "#2B2B2B", "#ECEAE4"  # Kist's ink on light and dark browser chrome
R_OUT, R_IN = 2.0, 0.5
GAP = 6.0  # hatch gap measured along an edge (about 4.2 units across, ~1 px at 16 px)
FRAMES = {"glyph": (8, 56), "app": (16, 48), "tab": (12, 52)}
TILE_RX = {"app": 14, "tab": 12}


def fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def _corners(pts, radii):
    """For each corner: (tangent point a, tangent point b, radius, centre, sweep)."""
    n = len(pts)
    out = []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        r = radii[i]
        v1 = (p0[0] - p1[0], p0[1] - p1[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        u1, u2 = (v1[0] / l1, v1[1] / l1), (v2[0] / l2, v2[1] / l2)
        ang = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))
        t = r / math.tan(ang / 2)
        a = (p1[0] + u1[0] * t, p1[1] + u1[1] * t)
        b = (p1[0] + u2[0] * t, p1[1] + u2[1] * t)
        bis = (u1[0] + u2[0], u1[1] + u2[1])
        bl = math.hypot(*bis)
        dist = r / math.sin(ang / 2)
        centre = (p1[0] + bis[0] / bl * dist, p1[1] + bis[1] / bl * dist)
        cross = -u1[0] * u2[1] + u1[1] * u2[0]
        out.append((a, b, r, centre, 1 if cross > 0 else 0))
    return out


def path_d(pts, radii) -> str:
    """Closed polygon with corner i rounded by radii[i], as SVG path data."""
    parts = []
    for i, (a, b, r, _c, sweep) in enumerate(_corners(pts, radii)):
        parts.append(f"{'M' if i == 0 else 'L'}{fmt(a[0])} {fmt(a[1])}"
                     f"A{fmt(r)} {fmt(r)} 0 0 {sweep} {fmt(b[0])} {fmt(b[1])}")
    return "".join(parts) + "Z"


def polygon(pts, radii, steps: int = 12) -> list[tuple[float, float]]:
    """The same outline with each fillet flattened to points (for Pillow)."""
    out = []
    for a, b, r, c, _sweep in _corners(pts, radii):
        a0 = math.atan2(a[1] - c[1], a[0] - c[0])
        a1 = math.atan2(b[1] - c[1], b[0] - c[0])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi  # the short way round
        for k in range(steps + 1):
            t = a0 + da * k / steps
            out.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
    return out


def _clip(poly, a, b, c):
    """Keep the part of poly where a*x + b*y <= c."""
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        fp, fq = a * p[0] + b * p[1] - c, a * q[0] + b * q[1] - c
        if fp <= 1e-9:
            out.append(p)
        if (fp < -1e-9 and fq > 1e-9) or (fp > 1e-9 and fq < -1e-9):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def pieces(f0: float, f1: float) -> list[tuple[list, list]]:
    """The four solid pieces of the part f0..f1: [(points, radii), ...]."""
    s, c = f1 - f0, f0 + f1
    cuts = [c - s / 2, c, c + s / 2]  # the anti-diagonal and +-s/2 either side
    bounds = [-1e9] + [v for k in cuts for v in (k - GAP / 2, k + GAP / 2)] + [1e9]
    sq = [(f0, f0), (f1, f0), (f1, f1), (f0, f1)]
    out = []
    for i in range(0, len(bounds), 2):
        p = _clip(_clip(sq, 1, 1, bounds[i + 1]), -1, -1, -bounds[i])
        if len(p) >= 3:
            out.append((p, [R_OUT if x in (f0, f1) and y in (f0, f1) else R_IN for x, y in p]))
    return out


def mark_d(size: str) -> str:
    return "".join(path_d(p, r) for p, r in pieces(*FRAMES[size]))


def svg(body: str, extra: str = "") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{extra}{body}</svg>\n'


def tile_svg(size: str, full_bleed: bool = False, scale: float = 1.0) -> str:
    bg = (f'<rect width="64" height="64" fill="{TILE}"/>' if full_bleed
          else f'<rect width="64" height="64" rx="{TILE_RX[size]}" fill="{TILE}"/>')
    d = mark_d(size)
    if scale != 1.0:
        return svg(f'<g transform="translate(32 32) scale({fmt(scale)}) translate(-32 -32)">'
                   f'<path fill="{MARK}" d="{d}"/></g>', bg)
    return svg(f'<path fill="{MARK}" d="{d}"/>', bg)


def raster(size_px: int, size: str, *, tile: bool = True, full_bleed: bool = False,
           scale: float = 1.0) -> Image.Image:
    ss = 8
    n = size_px * ss
    u = n / 64
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if tile:
        if full_bleed:
            d.rectangle([0, 0, n, n], fill=TILE)
        else:
            d.rounded_rectangle([0, 0, n - 1, n - 1], radius=TILE_RX[size] * u, fill=TILE)
    for pts, radii in pieces(*FRAMES[size]):
        poly = [((32 + (x - 32) * scale) * u, (32 + (y - 32) * scale) * u) for x, y in polygon(pts, radii)]
        d.polygon(poly, fill=MARK)
    return img.resize((size_px, size_px), Image.Resampling.LANCZOS)


def main() -> None:
    glyph = mark_d("glyph")
    favicon = svg(f'<path class="m" d="{glyph}"/>',
                  f'<style>.m{{fill:{INK_LIGHT}}}@media (prefers-color-scheme:dark){{.m{{fill:{INK_DARK}}}}}</style>')
    (WEB / "favicon.svg").write_text(favicon)
    (WEB / "icon-mono.svg").write_text(svg(f'<path fill="#000000" d="{glyph}"/>'))
    (WEB / "mark.svg").write_text(svg(f'<path fill="currentColor" d="{glyph}"/>'))

    BRAND.mkdir(parents=True, exist_ok=True)
    (BRAND / "sklent.svg").write_text(svg(f'<path fill="{INK_LIGHT}" d="{glyph}"/>'))
    (BRAND / "sklent-light.svg").write_text(svg(f'<path fill="#FFFFFF" d="{glyph}"/>'))
    (BRAND / "sklent-dark.svg").write_text(svg(f'<path fill="#1C1B19" d="{glyph}"/>'))
    (BRAND / "icon-tile.svg").write_text(tile_svg("app"))
    (BRAND / "icon-tab.svg").write_text(tile_svg("tab"))
    (BRAND / "icon-fullbleed.svg").write_text(tile_svg("app", full_bleed=True))
    (BRAND / "icon-maskable.svg").write_text(tile_svg("app", full_bleed=True, scale=0.8))

    raster(32, "tab").save(WEB / "favicon-32.png")
    frames = [raster(s, "tab") for s in (16, 32, 48)]  # each drawn at its own size
    frames[-1].save(WEB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=frames[:-1])
    # iOS draws its own corners and shows transparency as black: a full-bleed tile
    raster(180, "app", full_bleed=True).save(WEB / "apple-touch-icon.png")
    raster(192, "app").save(WEB / "icon-192.png")
    raster(512, "app").save(WEB / "icon-512.png")
    # maskable: the APP mark at 0.8 (corners 18.1 units from the centre, inside the 25.6 safe circle)
    raster(512, "app", full_bleed=True, scale=0.8).save(WEB / "icon-maskable-512.png")
    print("wrote favicon.svg, icon-mono.svg, mark.svg, favicon-32.png, favicon.ico, apple-touch-icon.png,"
          " icon-192.png, icon-512.png, icon-maskable-512.png and docs/brand/*.svg")


if __name__ == "__main__":
    main()
