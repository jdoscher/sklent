"""F11 engineering view sheet and F21 dimension callout still.

F11: front, top and right orthographic views (third-angle layout, one ISO 5455 scale on A3)
plus an isometric view, in the white palette, cut out onto paper, with a 1 px frame and the
title block; PNG and a one-page PDF (A3 landscape). No hidden lines in 0.2: SolidCraft's
headless screenshot draws visible edges only. When SolidCraft has `drawing.*` (0.45+) a
"drawings" sheet backend can replace this one (see `ortho.register_sheet_backend`).

F21: the front view with the overall width and height drawn as ISO 129-1 dimension lines
and the depth noted. The numbers are the measured bounding box; the lines sit exactly on its
projected edges because the camera is orthographic at a known scale (px/mm =
H / (0.8 × distance)), and the cut-out's opaque extent is checked against it.
"""

from __future__ import annotations

import math
from typing import Any

from . import draw, ortho
from .spec import title_cells

A3 = (3360, 2376)  # 420 × 297 mm at 8 px/mm


def views_layout(lo, hi, avail_w: float, avail_h: float, gap: float, label: float) -> tuple[float, float]:
    """(ratio, px/mm): the largest ISO scale at which top over front, right of front, fits."""
    x, y, z = (hi[i] - lo[i] for i in range(3))

    def fits(s: float) -> bool:
        w = (x + y) * s + gap
        h = (y + z) * s + gap + 2 * label
        return w <= avail_w and h <= avail_h

    ratio = ortho.best_scale(fits)
    return ratio, ratio * ortho.PAPER_PX_PER_MM


def render_views_sheet(shooter: ortho.Shooter, spec: dict, png_path, pdf_path) -> dict[str, Any]:
    W, H = A3
    s = draw.Sheet(W, H, unit=2)
    inset = 80  # 10 mm
    x0, y0, x1, y1 = s.frame(inset)
    lab, val, title = 18, 26, 52
    tb_w = 1440  # 180 mm, ISO 7200
    lo, hi = shooter.lo, shooter.hi
    cells_probe = title_cells(spec, extra=_sheet_cells("1:1", lo, hi), units=False)
    tb_top = y1 - draw.title_block_height(cells_probe, label_size=lab, value_size=val, title_size=title)
    m = 40
    gap, label_h = 120.0, 48.0
    ax0, ay0, ax1, ay1 = x0 + m, y0 + m, x1 - m, tb_top - m
    ratio, sc = views_layout(lo, hi, ax1 - ax0, ay1 - ay0, gap, label_h)
    pad = 12
    front, fi = shooter.view("front", sc, pad=pad, name="sheet-front")
    top, ti = shooter.view("top", sc, pad=pad, name="sheet-top")
    right, ri = shooter.view("right", sc, pad=pad, name="sheet-right")
    X, Y, Z = (hi[i] - lo[i] for i in range(3))
    block_w = (X + Y) * sc + gap
    block_h = (Y + Z) * sc + gap + label_h
    bx = ax0 + max(0.0, (ax1 - ax0 - block_w) / 2)
    by = ay0 + max(0.0, (ay1 - ay0 - block_h - label_h) / 2)
    # box corners of each view on the sheet (pads are inside the images)
    top_box = (bx, by)
    front_box = (bx, by + Y * sc + gap + label_h)
    right_box = (bx + X * sc + gap, front_box[1])
    s.paste(top, (top_box[0] - ti["box_px"][0], top_box[1] - ti["box_px"][1]))
    s.paste(front, (front_box[0] - fi["box_px"][0], front_box[1] - fi["box_px"][1]))
    s.paste(right, (right_box[0] - ri["box_px"][0], right_box[1] - ri["box_px"][1]))
    s.caps((top_box[0], top_box[1] + Y * sc + 18), "Top", lab)
    s.caps((front_box[0], front_box[1] + Z * sc + 18), "Front", lab)
    s.caps((right_box[0], right_box[1] + Z * sc + 18), "Right", lab)
    # the isometric view: the space right of the top view, at its own scale
    iso_area = (right_box[0], ay0, ax1, front_box[1] - label_h)
    iw, ih, _ = ortho.extent(lo, hi, "iso")
    aw, ah = iso_area[2] - iso_area[0], iso_area[3] - iso_area[1] - label_h
    iso_scale = 0.9 * min(aw / max(iw, 1e-6), ah / max(ih, 1e-6)) if aw > 40 and ah > 40 else 0
    iso_info = None
    if iso_scale > 0:
        iso_scale = min(iso_scale, sc * 1.5)
        iso, iso_info = shooter.view("iso", iso_scale, pad=pad, name="sheet-iso")
        ix = iso_area[0] + (aw - iw * iso_scale) / 2
        iy = iso_area[1] + (ah - ih * iso_scale) / 2
        s.paste(iso, (ix - iso_info["box_px"][0], iy - iso_info["box_px"][1]))
        same = abs(iso_scale - sc) < 1e-6
        s.caps((ix, iy + ih * iso_scale + 18), "Isometric" + ("" if same else "  ·  not to scale"), lab)
    # notes, bottom left beside the title block
    fm = draw.font("ui", 26)
    notes = [
        f"Third-angle projection. Scale {ortho.scale_label(ratio)} on A3 (420 × 297 mm).",
        "Dimensions in millimetres. Views are SolidCraft renders: visible edges only, no hidden lines.",
    ]
    ny = y1 - 40 - len(notes) * 40
    for line in notes:
        s.text((x0 + 40, ny), line, fm, s.ink.dim)
        ny += 40
    cells = title_cells(spec, extra=_sheet_cells(ortho.scale_label(ratio), lo, hi), units=False)
    draw.title_block(s, (x1 - tb_w, y0, x1, y1), cells, label_size=lab, value_size=val, title_size=title)
    s.save(png_path)
    s.im.save(pdf_path, "PDF", resolution=ortho.PAPER_PX_PER_MM * 25.4, title=f"{spec.get('title')} views")
    return {"scale": ortho.scale_label(ratio), "px_per_mm": sc,
            "iso_px_per_mm": iso_info["scale"] if iso_info else None,
            "views": {"front": _check(fi), "top": _check(ti), "right": _check(ri)}}


def _sheet_cells(scale: str, lo, hi) -> list[draw.Cell]:
    env = draw.envelope([lo, hi])
    return [
        draw.Cell("Scale", scale),
        draw.Cell("Projection", "third angle"),
        draw.Cell("Envelope", f"{env} mm" if env else None),
    ]


def _check(info: dict) -> dict[str, Any]:
    """How the cut-out's opaque extent compares with the box projection (px)."""
    bx0, by0, bx1, by1 = info["box_px"]
    m = info.get("measured_px")
    out = {"expected_px": [round(bx1 - bx0, 1), round(by1 - by0, 1)], "measured_px": None}
    if m:
        out["measured_px"] = [m[2] - m[0], m[3] - m[1]]
    return out


# ---------------------------------------------------------------- F21

def render_dimensions(shooter: ortho.Shooter, spec: dict, path, *, width: int = 2048, height: int = 1536) -> dict:
    s = draw.Sheet(width, height)
    k = width / 2048
    inset = round(32 * k)
    x0, y0, x1, y1 = s.frame(inset)
    lo, hi = shooter.lo, shooter.hi
    X, Y, Z = (hi[i] - lo[i] for i in range(3))
    head = round(150 * k)  # title and envelope line
    foot = round(120 * k)  # depth note
    dim_room = round(150 * k)  # left and bottom, for the dimension lines
    ax0, ay0 = x0 + dim_room + round(40 * k), y0 + head
    ax1, ay1 = x1 - round(110 * k), y1 - foot - dim_room
    scale = min((ax1 - ax0) / max(X, 1e-6), (ay1 - ay0) / max(Z, 1e-6))
    scale = min(scale, 400.0)
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    im, info = shooter.view("front", scale, pad=12, name="dims-front")
    bw, bh = X * scale, Z * scale
    bx = ax0 + (ax1 - ax0 - bw) / 2
    by = ay0 + (ay1 - ay0 - bh) / 2
    s.paste(im, (bx - info["box_px"][0], by - info["box_px"][1]))
    size = round(34 * k)
    off = round(70 * k)
    s.dimension((bx, by + bh), (bx + bw, by + bh), "below", off, f"{draw.fmt_mm(X)} mm", size)
    s.dimension((bx, by), (bx, by + bh), "left", off, f"{draw.fmt_mm(Z)} mm", size)
    # heading: the name in the title voice, the envelope in the spec voice
    s.text((x0 + round(40 * k), y0 + round(34 * k)), spec.get("title") or "—",
           draw.fit("serif", round(64 * k), spec.get("title") or "—", x1 - x0 - round(80 * k)))
    env = draw.envelope([lo, hi])
    s.text((x0 + round(40 * k), y0 + round(106 * k)), f"{env} mm  ·  W × D × H" if env else "—",
           draw.font("mono", round(26 * k)), s.ink.dim)
    note = f"Depth {draw.fmt_mm(Y)} mm (front to back). Front view, orthographic; overall sizes of the bounding box."
    s.text((x0 + round(40 * k), y1 - round(70 * k)), note, draw.font("ui", round(26 * k)), s.ink.dim)
    s.save(path)
    chk = _check(info)
    return {"px_per_mm": scale, "width_mm": X, "height_mm": Z, "depth_mm": Y, **chk}
