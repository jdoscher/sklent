"""F8 BOM card: the model's bill of materials (`assembly.bom`), merged with an optional
`bom.yaml` of bought parts, as `bom.csv` (a set file, filed in Kist), `bom.json` (in the set
folder) and a BOM sheet still.

`bom.yaml` (the path comes from `.sklent.yaml` `bom:`, else the `specs_bom_file` setting,
relative to the design's folder; `bom:` may also hold the list inline):

    currency: EUR            # optional, printed after totals
    parts:                   # or a bare list
      - name: M3x8 socket head cap screw
        qty: 8
        supplier: Example Fasteners
        url: https://example.com/m3x8
        price: 0.12          # per unit
        part_number: ISO4762-M3x8
      - match: Arm           # enrich a model row (by its name or part number) instead
        supplier: Workshop
        notes: print in PETG

Model rows are "make" unless SolidCraft says `bom_type: purchased`; bom.yaml rows that
match no model row are "buy". Nothing here is fetched from the suppliers' sites.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any

from . import draw

COLUMNS = ["item", "qty", "name", "part_number", "kind", "source", "supplier", "url", "price", "total",
           "description", "notes"]


def model_rows(sc) -> list[dict[str, Any]]:
    reply = sc.execute("assembly.bom", levels="flat", group_by=["part_number"]) or {}
    out = []
    for r in reply.get("rows") or []:
        if r.get("bom_type") == "reference":
            continue
        out.append({
            "qty": int(r.get("count") or 1),
            "name": r.get("definition") or r.get("part_number") or "part",
            "part_number": r.get("part_number") or "",
            "kind": "buy" if r.get("bom_type") == "purchased" else "make",
            "source": "model",
            "description": r.get("description") or "",
        })
    return out


def body_rows(info: list[dict]) -> list[dict[str, Any]]:
    """A design with no components: its visible bodies are the parts to make."""
    out = []
    for b in info:
        if b.get("visible") is False:
            continue
        bb = b.get("bbox") or {}
        size = draw.envelope([bb["min"], bb["max"]]) if bb.get("min") and bb.get("max") else ""
        out.append({"qty": 1, "name": b.get("name") or "body", "part_number": "", "kind": "make", "source": "model",
                    "description": f"{size} mm" if size else ""})
    return out


def parse_yaml(data: bytes | str | list | dict | None) -> tuple[list[dict], str | None, list[str]]:
    """bom.yaml → (entries, currency, warnings). Accepts the file's bytes, or the parsed value
    when `.sklent.yaml` holds the list inline."""
    warnings: list[str] = []
    if data is None:
        return [], None, warnings
    doc: Any = data
    if isinstance(data, bytes | str):
        try:
            import yaml
        except ImportError:  # pragma: no cover - pyyaml ships with uvicorn[standard]
            return [], None, ["pyyaml is not installed; bom.yaml skipped"]
        try:
            doc = yaml.safe_load(data)
        except yaml.YAMLError as exc:
            return [], None, [f"bom.yaml: {str(exc).splitlines()[0]}"]
    currency = None
    if isinstance(doc, dict):
        currency = doc.get("currency")
        doc = doc.get("parts") or doc.get("items") or doc.get("bom") or []
    if not isinstance(doc, list):
        return [], None, ["bom.yaml: expected a list of parts"]
    entries = []
    for i, e in enumerate(doc, 1):
        if not isinstance(e, dict) or not (e.get("name") or e.get("match")):
            warnings.append(f"bom.yaml entry {i}: needs a name")
            continue
        try:
            qty = int(e.get("qty", e.get("quantity", 1)) or 1)
        except (TypeError, ValueError):
            warnings.append(f"bom.yaml entry {i}: qty is not a number")
            qty = 1
        price = e.get("price")
        try:
            price = float(price) if price not in (None, "") else None
            if price is not None and not math.isfinite(price):
                price = None
        except (TypeError, ValueError):
            warnings.append(f"bom.yaml entry {i}: price is not a number")
            price = None
        url = str(e.get("url") or "")
        if url and not url.startswith(("https://", "http://")):
            warnings.append(f"bom.yaml entry {i}: url must be http(s)")
            url = ""
        entries.append({
            "match": str(e.get("match") or ""),
            "name": str(e.get("name") or e.get("match")),
            "qty": max(1, qty),
            "part_number": str(e.get("part_number") or e.get("mpn") or ""),
            "kind": str(e.get("kind") or "") if e.get("kind") in ("make", "buy") else "",
            "supplier": str(e.get("supplier") or ""),
            "url": url,
            "price": price,
            "description": str(e.get("description") or ""),
            "notes": str(e.get("notes") or ""),
            "_qty_given": "qty" in e or "quantity" in e,
        })
    return entries, (str(currency) if currency else None), warnings


def merge(model: list[dict], extra: list[dict]) -> list[dict[str, Any]]:
    rows = [dict(r) for r in model]
    key = lambda s: str(s or "").strip().casefold()  # noqa: E731
    for e in extra:
        want = key(e["match"] or e["name"])
        hit = next((r for r in rows
                    if r["source"] == "model" and want and want in (key(r["name"]), key(r["part_number"]))), None)
        if hit is None and e["match"]:
            continue  # an enrichment that matched nothing (reported by the caller)
        if hit is not None:
            for k in ("supplier", "url", "price", "notes"):
                if e.get(k) not in (None, ""):
                    hit[k] = e[k]
            if e["part_number"] and not hit["part_number"]:
                hit["part_number"] = e["part_number"]
            if e["kind"]:
                hit["kind"] = e["kind"]
            if e["description"] and not hit.get("description"):
                hit["description"] = e["description"]
            hit["source"] = "model+bom.yaml"
            continue
        rows.append({"qty": e["qty"], "name": e["name"], "part_number": e["part_number"], "kind": e["kind"] or "buy",
                     "source": "bom.yaml", "supplier": e["supplier"], "url": e["url"], "price": e["price"],
                     "description": e["description"], "notes": e["notes"]})
    for i, r in enumerate(rows, 1):
        r["item"] = i
        for k in COLUMNS:
            r.setdefault(k, None if k in ("price", "total") else "")
        r["total"] = round(r["qty"] * r["price"], 4) if isinstance(r.get("price"), int | float) else None
    return [{k: r[k] for k in COLUMNS} for r in rows]


def unmatched(model: list[dict], extra: list[dict]) -> list[str]:
    """`match:` entries in bom.yaml that name no model row."""
    key = lambda s: str(s or "").strip().casefold()  # noqa: E731
    names = {key(r["name"]) for r in model} | {key(r["part_number"]) for r in model if r["part_number"]}
    return [f"bom.yaml: match {e['match']!r} names no part in the model" for e in extra
            if e["match"] and key(e["match"]) not in names]


def summary(rows: list[dict], currency: str | None) -> dict[str, Any]:
    priced = [r["total"] for r in rows if r["total"] is not None]
    return {
        "lines": len(rows),
        "parts": sum(r["qty"] for r in rows),
        "make": sum(r["qty"] for r in rows if r["kind"] == "make"),
        "buy": sum(r["qty"] for r in rows if r["kind"] == "buy"),
        "total_price": round(sum(priced), 2) if priced else None,
        "priced_lines": len(priced),
        "currency": currency,
    }


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r[k] is None else r[k]) for k in COLUMNS})
    return buf.getvalue()


def fmt_price(v: float | None, currency: str | None = None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}" + (f" {currency}" if currency else "")


def render_sheet(bom: dict, spec: dict, path, *, width: int = 2048, height: int = 1152) -> None:
    """The parts list as a sheet: numbered rows in mono, make/buy, supplier and price, the
    totals, and the title block (ISO 5457: a parts list sits above the title block)."""
    from .spec import title_cells

    rows: list[dict] = bom["rows"]
    s = draw.Sheet(width, height)
    k = width / 2048
    inset = round(32 * k)
    x0, y0, x1, y1 = s.frame(inset)
    lab, val = round(17 * k), round(24 * k)
    pad = round(26 * k)
    tb_w = round(760 * k)
    cells = title_cells(spec, extra=[draw.Cell("Sheet", "Parts list", wide=True, kind="ui")])
    tb_top = y1 - draw.title_block_height(cells, label_size=lab, value_size=val, title_size=round(52 * k))
    # columns: no, qty, name, part number, make/buy, supplier, price
    cols = [("No", 70), ("Qty", 80), ("Name", 560), ("Part number", 330), ("Make/buy", 150), ("Supplier", 330),
            ("Each", 150), ("Line", 170)]
    scale_w = (x1 - x0 - 2 * pad) / sum(w for _, w in cols)
    xs, x = [], x0 + pad
    for _, w in cols:
        xs.append(x)
        x += w * scale_w
    y = y0 + pad
    s.caps((x0 + pad, y), f"Parts  ·  {bom['summary']['lines']} lines, {bom['summary']['parts']} pieces", lab)
    y += round(lab * 2.4)
    for (name, _), cx in zip(cols, xs, strict=True):
        s.caps((cx, y), name, lab)
    y += round(lab * 1.6)
    s.hline(x0 + pad, x1 - pad, y, s.ink.frame)
    row_h = round(val * 1.75)
    bottom = tb_top - pad - round(val * 2.4)  # room for the totals line
    fit_rows = max(1, int((bottom - y) // row_h))
    shown = rows if len(rows) <= fit_rows else rows[: fit_rows - 1]
    fm, fu = draw.font("mono", val), draw.font("ui", val)
    cur = bom["summary"].get("currency")
    for r in shown:
        ty = y + round(row_h * 0.25)
        vals = [(f"{r['item']:02d}", fm), (str(r["qty"]), fm), (r["name"], fu), (r["part_number"] or "—", fm),
                (r["kind"], fu), (r["supplier"] or "—", fu), (fmt_price(r["price"]), fm), (fmt_price(r["total"]), fm)]
        for i, ((v, f), cx) in enumerate(zip(vals, xs, strict=True)):
            wcol = (xs[i + 1] - cx - 12 * k) if i + 1 < len(xs) else (x1 - pad - cx)
            s.text((cx, ty), draw.ellipsize(f, v, int(wcol)), f, s.ink.dim if v == "—" else s.ink.text)
        y += row_h
        s.hline(x0 + pad, x1 - pad, y, s.ink.rule)
    if len(shown) < len(rows):
        s.text((xs[2], y + round(row_h * 0.25)), f"+{len(rows) - len(shown)} more in bom.csv", fu, s.ink.dim)
        y += row_h
    sm = bom["summary"]
    tot = f"make {sm['make']} · buy {sm['buy']}"
    if sm.get("total_price") is not None:
        tot += f" · priced lines {fmt_price(sm['total_price'], cur)}"
        if sm["priced_lines"] < sm["lines"]:
            tot += f" ({sm['priced_lines']} of {sm['lines']} lines priced)"
    s.text((x0 + pad, max(y + pad, tb_top - pad - val)), tot, fm, s.ink.dim)
    draw.title_block(s, (x1 - tb_w, y0, x1, y1), cells, label_size=lab, value_size=val, title_size=round(52 * k))
    s.save(path)
