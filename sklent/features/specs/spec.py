"""F2 spec card: `spec.json` plus a 2048×1152 title-block still.

`spec.json` (in the set folder, read with `sets.read_json(set["dir"], "spec.json")`):
    version, title, path, repo, ref, commit, blob, source_url, licence, units,
    bounds_mm [[x,y,z] min, max], size_mm [x, y, z], volume_mm3, area_mm2,
    mass_g, material, density_g_cm3, bodies, hidden_bodies, open_bodies,
    components, occurrences, parameters [{name, value, unit, expression, comment}],
    palette, solidcraft, generated_at

Mass is reported only when a material is known: one set by `.sklent.yaml` (`material:`) or
the `specs_material` setting (assigned with `material.assign` for this render only), or
materials the design itself gives its bodies. SolidCraft's "Default" material doesn't count.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import draw, meta, ortho

SPEC_VERSION = 1
MEASURE_MAX_BODIES = 300  # `measure` on SELENE (1,418 bodies) takes ~23 s; skip it above this


def _visible(info: list[dict]) -> list[dict]:
    return [b for b in info if b.get("visible") is not False]


def _sum(values) -> float | None:
    vals = [v for v in values if isinstance(v, int | float)]
    return float(sum(vals)) if vals else None


def components_summary(sc) -> tuple[int, int, list[dict]]:
    """(component definitions, placements, the raw component list) from `component.list`."""
    try:
        reply = sc.execute("component.list") or {}
    except Exception:
        return 0, 0, []
    comps = reply.get("components") or []
    defs = sum(1 for c in comps if c.get("id") not in (0, None))  # the root (0) is the design itself
    occ = sum(len(c.get("children") or []) for c in comps)
    return defs, occ, comps


def world_bodies(sc, info: list[dict]) -> tuple[list[dict], dict] | None:
    """Every placed body in world coordinates from `measure` (a component placed twice is two
    bodies, `ArmBody` and `ArmBody (Arm:2)`), minus the ones the design hides. None above
    MEASURE_MAX_BODIES: there, `inspect_design`'s definition-level boxes have to do."""
    if len(info) > MEASURE_MAX_BODIES:
        return None
    full = sc.tool("measure") or {}
    try:
        names = sc.tool("measure", names_only=True) or {}
    except Exception:
        names = {}
    definition = {b.get("name"): b.get("definition") for b in names.get("bodies") or []}
    hidden = {b.get("name") for b in info if b.get("visible") is False}
    rows = [b for b in full.get("bodies") or []
            if b.get("visible") is not False and (definition.get(b.get("name")) or b.get("name")) not in hidden]
    return rows, full.get("total") or {}


def bounds_of(rows: list[dict]) -> tuple[list[float], list[float]] | None:
    lo = hi = None
    for b in rows:
        bb = b.get("bbox") or {}
        if bb.get("min") and bb.get("max"):
            lo = list(bb["min"]) if lo is None else [min(a, c) for a, c in zip(lo, bb["min"], strict=True)]
            hi = list(bb["max"]) if hi is None else [max(a, c) for a, c in zip(hi, bb["max"], strict=True)]
    return (lo, hi) if lo is not None and hi is not None else None


def mass_and_material(rows: list[dict] | None, material: str | None, volume_mm3: float | None,
                      density_of) -> dict[str, Any]:
    """Mass only when a material is known: the one assigned for this render, or materials the
    design gives its bodies (SolidCraft's placeholder "Default" doesn't count)."""
    out: dict[str, Any] = {"mass_g": None, "material": material or None, "density_g_cm3": None}
    if rows is None:  # too big to measure: density × volume for an assigned material
        if material and volume_mm3:
            dens = density_of(material)
            if dens:
                out["density_g_cm3"] = dens
                out["mass_g"] = volume_mm3 / 1000.0 * dens
        return out
    mats = {b.get("material") for b in rows if b.get("material")}
    real = mats - {"Default", None}
    if not material and not real:
        return out
    out["mass_g"] = _sum(b.get("mass_g") for b in rows if b.get("closed") is not False)
    if not material:
        out["material"] = next(iter(real)) if len(mats) == 1 else "mixed"
    dens = {b.get("density_g_cm3") for b in rows if b.get("density_g_cm3")}
    out["density_g_cm3"] = next(iter(dens)) if len(dens) == 1 else None
    return out


def build_spec(ctx, row: dict, cfg: dict) -> dict[str, Any]:
    """The spec dict; also sets `spec["_box"]`, the world bounds the views should frame."""
    sc = ctx.sc
    vis = _visible(ctx.info)
    try:
        doc = sc.tool("inspect_design", bodies=False, sketches=False, joints=False, timeline=False) or {}
    except Exception:
        doc = {}
    try:
        version = (sc.tool("version") or {}).get("version")
    except Exception:
        version = None
    params = [{k: p.get(k) for k in ("name", "value", "unit", "expression", "comment")}
              for p in doc.get("params") or [] if not p.get("model")]
    material = meta.pick(cfg, "material", "spec.material") or (ctx.settings or {}).get("specs_material") or None
    warnings = []
    if material:
        try:
            sc.execute("material.assign", bodies=[b["name"] for b in vis], material=str(material))
        except Exception as exc:  # an unknown material name: no mass rather than no spec
            warnings.append(f"material {material!r}: {str(exc)[:200]}")
            material = None
    world = world_bodies(sc, ctx.info)
    rows = world[0] if world else None
    box = (bounds_of(rows) if rows else None) or ctx.box
    pool = rows if rows is not None else vis
    closed = [b for b in pool if b.get("closed") is not False]
    volume = _sum(b.get("volume_mm3") for b in closed)
    defs, occ, _ = components_summary(sc)

    def density_of(name: str):
        mats = (sc.execute("material.list") or {}).get("materials", [])
        return next((m.get("density_g_cm3") for m in mats if m.get("name") == name), None)

    massinfo = mass_and_material(rows, material, volume, density_of)
    path = row.get("path") or ctx.design.name
    title = meta.pick(cfg, "title", "spec.title") or path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    lo, hi = box
    return {
        "version": SPEC_VERSION,
        "title": str(title),
        "path": path,
        "repo": f"{row['owner']}/{row['repo']}" if row.get("owner") else None,
        "ref": row.get("ref"),
        "commit": row.get("commit_sha"),
        "blob": row.get("blob_sha"),
        "source_url": row.get("html_url"),
        "licence": meta.licence(cfg),
        "units": doc.get("units") or "mm",
        "bounds_mm": [[round(v, 4) for v in lo], [round(v, 4) for v in hi]],
        "size_mm": [round(hi[i] - lo[i], 4) for i in range(3)],
        "volume_mm3": volume,
        "area_mm2": _sum(b.get("area_mm2") for b in pool),
        **massinfo,
        "bodies": len(pool),
        "hidden_bodies": len(ctx.info) - len(vis),
        "open_bodies": len(pool) - len(closed),
        "components": defs,
        "occurrences": occ,
        "parameters": params,
        "palette": getattr(ctx.palette, "name", None),
        "solidcraft": version,
        "measured": "placed bodies (measure)" if rows is not None else "definitions (inspect_design)",
        "warnings": warnings,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- the card

def fmt_value(v: float) -> str:
    """A parameter value: '85', '2.5', '0.125', '12,000'."""
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.4f}".rstrip("0").rstrip(".")


def fmt_mass(g: float | None) -> str | None:
    if g is None:
        return None
    return f"{g / 1000:.3g} kg" if g >= 1000 else (f"{g:.1f} g" if g < 10 else f"{g:,.0f} g")


def spec_rows(spec: dict) -> list[tuple[str, str]]:
    """The spec list's (label, value) rows, data only."""
    env = draw.envelope(spec.get("bounds_mm"))
    rows = [("Envelope  W × D × H", f"{env} mm" if env else "—")]
    v = spec.get("volume_mm3")
    rows.append(("Volume", f"{draw.fmt_num(v / 1000)} cm³" if v else "—"))
    mass = fmt_mass(spec.get("mass_g"))
    rows.append(("Mass", f"{mass} · {spec.get('material')}" if mass else "— no material set"))
    b = spec.get("bodies") or 0
    extra = []
    if spec.get("hidden_bodies"):
        extra.append(f"{spec['hidden_bodies']} hidden")
    if spec.get("open_bodies"):
        extra.append(f"{spec['open_bodies']} open")
    rows.append(("Bodies", f"{b:,}" + (f" ({', '.join(extra)})" if extra else "")))
    if spec.get("components"):
        n, placed = spec["components"], spec.get("occurrences") or 0
        rows.append(("Components", f"{n:,} part{'s' if n != 1 else ''} · {placed:,} placed"))
    return rows


def title_cells(spec: dict, *, extra: list[draw.Cell] | None = None, units: bool = True) -> list[draw.Cell]:
    src = None
    if spec.get("repo"):
        src = f"{spec['repo']} @ {spec.get('ref') or '—'} · {(spec.get('commit') or '')[:7] or '—'}"
    date = ((spec.get("generated_at") or "")[:16].replace("T", " ") + " UTC") if spec.get("generated_at") else None
    cells = [
        draw.Cell("Title", f"{spec.get('title') or '—'}\n{spec.get('path') or ''}", wide=True, kind="serif"),
        draw.Cell("Source", src, wide=True),
        draw.Cell("Rev", (spec.get("blob") or "")[:7] or None),
        draw.Cell("Date", date),
        draw.Cell("Licence", spec.get("licence")),
    ]
    if units:
        cells.append(draw.Cell("Units", spec.get("units") or "mm"))
    return cells + (extra or [])


def render_card(spec: dict, picture, path, *, width: int = 2048, height: int = 1152) -> None:
    """The card: the part (a cut-out, no marks on it) on the left; the spec list and the
    title block on the right."""
    s = draw.Sheet(width, height)
    k = width / 2048
    inset = round(32 * k)
    x0, y0, x1, y1 = s.frame(inset)
    col_w = round(760 * k)
    cx = x1 - col_w
    s.vline(cx, y0, y1, s.ink.rule)
    # picture area
    if picture is not None:
        pw, ph = picture.size
        ax0, ay0, ax1, ay1 = x0 + inset, y0 + inset, cx - inset, y1 - inset
        s.paste(picture, (ax0 + (ax1 - ax0 - pw) / 2, ay0 + (ay1 - ay0 - ph) / 2))
    # spec list
    lab, val = round(17 * k), round(30 * k)
    pad = round(26 * k)
    y = y0 + pad
    s.caps((cx + pad, y), "Spec", lab)
    s.hline(cx + pad + draw.text_w(draw.font("ui", lab, 600), "SPEC") + round(12 * k), x1 - pad, y + lab * 0.6)
    y += round(lab * 2.2)
    avail = col_w - 2 * pad
    for label, value in spec_rows(spec):
        s.caps((cx + pad, y), label, lab)
        f = draw.fit("mono", val, value, avail)
        s.text((cx + pad, y + round(lab * 1.45)), value, f)
        y += round(lab * 1.45 + val * 1.55)
    params = spec.get("parameters") or []
    cells = title_cells(spec)
    tb_h = draw.title_block_height(cells, label_size=lab, value_size=round(24 * k), title_size=round(52 * k))
    if params:
        s.caps((cx + pad, y), f"Parameters ({len(params)})", lab)
        y += round(lab * 1.6)
        fp = draw.font("mono", round(22 * k))
        line_h = round(22 * k * 1.45)
        room = (y1 - tb_h - pad) - y
        shown = max(0, room // line_h)
        for i, p in enumerate(params[:shown]):
            if i == shown - 1 and len(params) > shown:
                s.text((cx + pad, y), f"+{len(params) - shown + 1} more", fp, s.ink.dim)
                break
            unit = p.get("unit") or ""
            v = p.get("value")
            vs = fmt_value(v) if isinstance(v, int | float) else str(p.get("expression") or "—")
            line = f"{p.get('name')} = {vs}{(' ' + unit) if unit and unit != 'none' else ''}"
            s.text((cx + pad, y), draw.ellipsize(fp, line, avail), fp)
            y += line_h
    draw.title_block(s, (cx, y0, x1, y1), cells, label_size=lab, value_size=round(24 * k), title_size=round(52 * k))
    s.save(path)


def picture(shooter: ortho.Shooter, area: tuple[int, int], view: str = "iso") -> tuple:
    """The part from `view`, as large as fits `area` (px) with a margin."""
    w_mm, h_mm, _ = ortho.extent(shooter.lo, shooter.hi, view)
    scale = 0.86 * min(area[0] / max(w_mm, 1e-6), area[1] / max(h_mm, 1e-6))
    scale = min(scale, 400.0)  # a sub-millimetre part shouldn't ask for a giant zoom
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    return shooter.view(view, scale, name=f"card-{view}")
