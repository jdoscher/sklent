"""F27 contact sheet: every design of a source on one page (PNG, and a PDF with a page per
24 designs), each as its hero still with mono labels, under a title block.

Built on demand from the newest sets (through `sklent.sets`), cached under
`<data>/contact-sheets/<source id>/<key>/` where the key changes whenever a design's set
does. Filed into Kist (when Kist is on) only when asked through the POST endpoint, once per
key, tagged `format:contact-sheet`.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from . import draw

PAGE = (3840, 2160)  # a projector slide; the PDF is the same pages at 10 px/mm
PER_PAGE = 24
HERO_ORDER = [("shaded", "hero"), (None, "hero"), ("shaded", "social"), ("wireframe", "social")]


def hero_file(files: list[dict]) -> dict | None:
    for style, variant in HERO_ORDER:
        f = next((f for f in files if f.get("variant") == variant and (style is None or f.get("style") == style)), None)
        if f:
            return f
    return next((f for f in files if str(f.get("file", "")).lower().endswith(".png")), None)


def entries(source_id: str) -> list[dict[str, Any]]:
    """The source's designs that have a set, with the hero still's path."""
    from sklent import service, sets

    out = []
    for d in service.list_designs(source_id=source_id):
        s = sets.latest_set(d["id"])
        if not s:
            continue
        f = hero_file(s["files"])
        if not f or not (s["dir"] / f["file"]).is_file():
            continue
        commit = (d.get("spec") or {}).get("commit") or d.get("commit") or ""
        out.append({"id": d["id"], "name": d["name"], "path": d["path"], "repo": d["repo"],
                    "commit": commit[:7], "rendered_at": s.get("rendered_at"),
                    "report": s.get("report") or {}, "spec": (d.get("spec") or {}), "hero": s["dir"] / f["file"]})
    out.sort(key=lambda e: (e["repo"], e["path"]))
    return out


def cache_key(items: list[dict]) -> str:
    raw = json.dumps([(e["id"], e["rendered_at"], e["hero"].name) for e in items])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def folder(source_id: str, key: str) -> Path:
    from sklent.config import get_settings

    return get_settings().data_dir / "contact-sheets" / source_id / key


def label_line(e: dict) -> str:
    spec, rep = e["spec"], e["report"]
    env = draw.envelope(spec.get("bounds_mm") or rep.get("bounds_mm"))
    bodies = spec.get("bodies", rep.get("bodies"))
    parts = [f"{env} mm" if env else None,
             (f"{bodies:,} body" if bodies == 1 else f"{bodies:,} bodies") if bodies is not None else None,
             e["commit"] or None]
    return "  ·  ".join(p for p in parts if p)


def render_page(source: dict, items: list[dict], page: int, pages: int, total: int, path: Path) -> None:
    W, H = PAGE
    s = draw.Sheet(W, H, unit=2)
    inset = 48
    x0, y0, x1, y1 = s.frame(inset)
    lab, val, title = 22, 30, 64
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    cells = [
        draw.Cell("Title", f"{source.get('label') or source.get('url')}\n{source.get('url') or ''}", wide=True,
                  kind="serif"),
        draw.Cell("Designs", f"{total:,}"),
        draw.Cell("Date", when),
    ]
    tb_w = 1240
    tb_h = draw.title_block_height(cells, label_size=lab, value_size=val, title_size=title)
    pad = 40
    gx0, gy0, gx1, gy1 = x0 + pad, y0 + pad, x1 - pad, y1 - pad
    n = len(items)
    # the grid sits above the title block's band; columns and rows give the largest cells
    gy1 -= tb_h
    best = None
    for cols in range(1, 9):
        rows = max(1, math.ceil(n / cols))
        cw, ch = (gx1 - gx0) / cols, (gy1 - gy0) / rows
        side = min(cw - 24, ch - 110)
        if best is None or side > best[0]:
            best = (side, cols, rows, cw, ch)
    _, cols, rows, cw, ch = best
    fname = draw.font("ui", 30, 500)
    fdata = draw.font("mono", 22)
    for i, e in enumerate(items):
        r, c = divmod(i, cols)
        cx, cy = gx0 + c * cw, gy0 + r * ch
        img_h = ch - 110
        side = int(min(cw - 24, img_h))
        with Image.open(e["hero"]) as im:
            im = im.convert("RGB")
            im.thumbnail((side, side), Image.Resampling.LANCZOS)
            s.paste(im, (cx + (cw - im.width) / 2, cy + (img_h - im.height) / 2))
        tx = cx + 12
        avail = int(cw - 24)
        s.text((tx, cy + img_h + 18), draw.ellipsize(fname, e["name"], avail), fname)
        s.text((tx, cy + img_h + 62), draw.ellipsize(fdata, label_line(e), avail), fdata, s.ink.dim)
    corner = f"Sheet {page:02d} / {pages:02d}"
    draw.title_block(s, (x1 - tb_w, y0, x1, y1), cells, label_size=lab, value_size=val, title_size=title, corner=corner)
    s.save(path)


def build(source_id: str) -> dict[str, Any]:
    """Make (or reuse) the source's contact sheet. Raises KeyError for an unknown source and
    LookupError when no design of it has been rendered yet."""
    from sklent import jobs, service

    src = jobs.get_source(source_id)
    source = next((x for x in service.list_sources() if x["id"] == source_id), {**src, "label": src.get("url")})
    items = entries(source_id)
    if not items:
        raise LookupError("no rendered designs in this source yet")
    key = cache_key(items)
    out = folder(source_id, key)
    pages = math.ceil(len(items) / PER_PAGE)
    pngs = [out / f"contact-sheet-{p:02d}.png" for p in range(1, pages + 1)]
    pdf = out / "contact-sheet.pdf"
    if not (all(p.is_file() for p in pngs) and pdf.is_file()):
        out.mkdir(parents=True, exist_ok=True)
        for p in range(pages):
            render_page(source, items[p * PER_PAGE:(p + 1) * PER_PAGE], p + 1, pages, len(items), pngs[p])
        ims = [Image.open(p).convert("RGB") for p in pngs]
        ims[0].save(pdf, "PDF", resolution=254.0, save_all=True, append_images=ims[1:],
                    title=f"{source.get('label')} contact sheet")
        for im in ims:
            im.close()
        # keep only the newest sheet for the source
        for old in out.parent.iterdir():
            if old != out and old.is_dir():
                for f in old.iterdir():
                    f.unlink(missing_ok=True)
                old.rmdir()
    return {"source_id": source_id, "key": key, "designs": len(items), "pages": pages, "png": pngs, "pdf": pdf,
            "source": source}
