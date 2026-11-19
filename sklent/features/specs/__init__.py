"""Specs and sheets (Sklent 0.2, area S): spec card (F2), BOM card (F8), engineering view
sheet (F11), dimension callout still (F21), contact sheet (F27) and assembly step images (F30).

Render steps (order 50–79, all on the open design, after the stills):
- 50 `specs-spec`: `spec.json` always; the spec card still when `specs_card` (default on)
- 55 `specs-bom`: `bom.csv`, `bom.json`, the BOM sheet when `specs_bom` (default on) and there
  is something to list (components, several bodies, or a bom.yaml)
- 60 `specs-views`: the views sheet PNG + PDF when `specs_views` (default on)
- 62 `specs-dimensions`: the dimension still when `specs_dimensions` (default on)
- 70 `specs-assembly`: assembly step images + assembly.md when `specs_assembly` (default off)
- 79 `specs-cleanup`: removes the steps' scratch screenshots

Set files (style `specs`, variant names agreed with the other areas): `spec-card`,
`bom-csv`, `bom-sheet`, `views-sheet`, `views-sheet-pdf`, `dimensions`, `assembly-<n>`,
`assembly-md`. Sidecars in the set folder: `spec.json`, `bom.json`, `assembly.json`.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from mcp.server.mcpserver import Image
from PIL import Image as PILImage

from sklent import jobs, sets, steps

from . import assembly, bom, contact, draw, meta, ortho, spec, views

log = logging.getLogger("sklent.specs")

STYLE = "specs"
VARIANTS = ("spec-card", "bom-csv", "bom-sheet", "views-sheet", "views-sheet-pdf", "dimensions", "assembly-md")

# ---------------------------------------------------------------- settings

DEFAULTS: dict[str, Any] = {
    "specs_card": True,
    "specs_material": "",
    "specs_bom": True,
    "specs_bom_file": "bom.yaml",
    "specs_views": True,
    "specs_dimensions": True,
    "specs_assembly": False,
    "specs_assembly_max_steps": 20,
}


def _bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _material(v: Any) -> str:
    v = "" if v is None else str(v).strip()
    if len(v) > 64 or any(c in v for c in "\n\r\t"):
        raise ValueError("specs_material must be a material name (material.list), up to 64 characters")
    return v


def _bom_file(v: Any) -> str:
    v = "" if v is None else str(v).strip()
    if len(v) > 200 or ".." in v.split("/") or "\\" in v:
        raise ValueError("specs_bom_file must be a relative path inside the repo")
    return v


def _steps_cap(v: Any) -> int:
    n = int(v)
    if not 1 <= n <= 60:
        raise ValueError("specs_assembly_max_steps must be 1 to 60")
    return n


for _key, _validate in (("specs_card", _bool), ("specs_material", _material), ("specs_bom", _bool),
                        ("specs_bom_file", _bom_file), ("specs_views", _bool), ("specs_dimensions", _bool),
                        ("specs_assembly", _bool), ("specs_assembly_max_steps", _steps_cap)):
    jobs.register_setting(_key, DEFAULTS[_key], _validate)


def setting(ctx, key: str) -> Any:
    return (ctx.settings or {}).get(key, DEFAULTS[key])


def wanted(ctx, key: str, variant: str) -> bool:
    """On by its setting; and when the render's `outputs` list (V's F17) names any specs
    variant, only the variants it names."""
    if not _bool(setting(ctx, key)):
        return False
    outs = (ctx.settings or {}).get("outputs")
    if isinstance(outs, list | tuple) and any(str(o) in VARIANTS or str(o).startswith("assembly-") for o in outs):
        return variant in outs
    return True


# ---------------------------------------------------------------- shared state per render

def _state(ctx) -> dict[str, Any]:
    st = ctx.__dict__.get("_sk_specs")
    if st is None:
        st = {}
        ctx.__dict__["_sk_specs"] = st
        st["row"] = meta.design_row(ctx)
        st["cfg"] = meta.config(st["row"].get("id"))
    return st


def _shooter(ctx) -> ortho.Shooter:
    st = _state(ctx)
    if "shooter" not in st:
        st["shooter"] = ortho.Shooter(ctx.sc, ctx.out_dir, box(ctx))
    return st["shooter"]


def box(ctx) -> tuple[list[float], list[float]]:
    """The world bounds of the placed bodies (from the spec step's `measure`), else the render's
    box (definition-level: a component placed away from its origin isn't in it)."""
    b = _state(ctx).get("box")
    return b if b else ctx.box


def _spec(ctx) -> dict[str, Any]:
    """The spec the first step built, or the facts we have without SolidCraft."""
    st = _state(ctx)
    if st.get("spec"):
        return st["spec"]
    row = st["row"]
    lo, hi = box(ctx)
    path = row.get("path") or ctx.design.name
    return {"title": path.rsplit("/", 1)[-1].rsplit(".", 1)[0], "path": path,
            "repo": f"{row['owner']}/{row['repo']}" if row.get("owner") else None, "ref": row.get("ref"),
            "commit": row.get("commit_sha"), "blob": row.get("blob_sha"), "licence": meta.licence(st["cfg"]),
            "units": "mm", "bounds_mm": [list(lo), list(hi)], "bodies": len(ctx.bodies),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}


def _paint(ctx, colour: str, opacity: float = 1.0) -> None:
    ctx.sc.paint(ctx.bodies, colour, opacity)


def _summary(ctx) -> dict[str, Any]:
    return ctx.report.setdefault("specs", {})


# ---------------------------------------------------------------- steps

def step_spec(ctx) -> None:
    st = _state(ctx)
    data = spec.build_spec(ctx, st["row"], st["cfg"])
    st["spec"] = data
    st["box"] = (list(data["bounds_mm"][0]), list(data["bounds_mm"][1]))
    sets.write_json(ctx.out_dir, "spec.json", data)
    _summary(ctx)["spec"] = {k: data.get(k) for k in ("mass_g", "material", "volume_mm3", "components")}
    if not wanted(ctx, "specs_card", "spec-card"):
        return
    ctx.progress(0.706, "spec card")
    _paint(ctx, ctx.palette.shaded)
    k = 2048 / 2048
    area = (round((2048 - 760 - 3 * 32) * k), round((1152 - 4 * 32) * k))
    pic, _ = spec.picture(_shooter(ctx), area)
    name = f"{ctx.stem}-spec-card.png"
    spec.render_card(data, pic, ctx.out_dir / name)
    ctx.add(name, style=STYLE, variant="spec-card", width=2048, height=1152)


def step_bom(ctx) -> None:
    st = _state(ctx)
    rows = bom.model_rows(ctx.sc)
    visible = [b for b in ctx.info if b.get("visible") is not False]
    if not rows and len(visible) > 1:
        rows = bom.body_rows(ctx.info)
    # bom.yaml: inline in .sklent.yaml, a path from it, or the setting's file name
    cfg_bom = meta.pick(st["cfg"], "bom", "bom_yaml")
    data: Any = None
    origin = None
    if isinstance(cfg_bom, list | dict):
        data, origin = cfg_bom, ".sklent.yaml"
    else:
        rel = str(cfg_bom) if cfg_bom else str(setting(ctx, "specs_bom_file") or "")
        local = Path(ctx.design).parent / rel if rel else None
        if local and rel and local.is_file() and local.resolve().is_relative_to(Path(ctx.design).parent.resolve()):
            data, origin = local.read_bytes(), rel
        elif rel and (cfg_bom or rows):  # only ask the forge for designs that have a BOM to merge into
            data = meta.fetch_repo_file(st["row"], rel)
            origin = rel if data is not None else None
    extra, currency, warnings = bom.parse_yaml(data)
    warnings += bom.unmatched(rows, extra)
    if not rows and not [e for e in extra if not e["match"]]:
        _summary(ctx)["bom"] = {"skipped": "a single part with no components and no bom.yaml"}
        return
    merged = bom.merge(rows, extra)
    doc = {"rows": merged, "summary": bom.summary(merged, currency), "bom_yaml": origin, "warnings": warnings}
    sets.write_json(ctx.out_dir, "bom.json", doc)
    _summary(ctx)["bom"] = {**doc["summary"], "bom_yaml": origin, "warnings": warnings}
    if wanted(ctx, "specs_bom", "bom-csv"):
        name = f"{ctx.stem}-bom.csv"
        (ctx.out_dir / name).write_text(bom.to_csv(merged))
        ctx.add(name, style=STYLE, variant="bom-csv", guard=False)
    if wanted(ctx, "specs_bom", "bom-sheet"):
        ctx.progress(0.707, "parts sheet")
        name = f"{ctx.stem}-bom-sheet.png"
        bom.render_sheet(doc, _spec(ctx), ctx.out_dir / name)
        ctx.add(name, style=STYLE, variant="bom-sheet", width=2048, height=1152)


def _views_screenshots(ctx, _spec_unused=None) -> list:
    ctx.progress(0.708, "views sheet")
    from sklent.palette import get as palette

    _paint(ctx, palette("white").shaded)
    try:
        png, pdf = f"{ctx.stem}-views-sheet.png", f"{ctx.stem}-views-sheet.pdf"
        info = views.render_views_sheet(_shooter(ctx), _spec(ctx), ctx.out_dir / png, ctx.out_dir / pdf)
    finally:
        ctx.restore()
    _summary(ctx)["views"] = info
    w, h = views.A3
    if wanted(ctx, "specs_views", "views-sheet"):
        ctx.add(png, style=STYLE, variant="views-sheet", width=w, height=h)
    else:
        (ctx.out_dir / png).unlink(missing_ok=True)
    if wanted(ctx, "specs_views", "views-sheet-pdf"):
        ctx.add(pdf, style=STYLE, variant="views-sheet-pdf", width=w, height=h, guard=False)
    else:
        (ctx.out_dir / pdf).unlink(missing_ok=True)
    return []


ortho.register_sheet_backend("screenshots", _views_screenshots)


def step_views(ctx) -> None:
    name, backend = ortho.sheet_backend(ctx.sc)
    _summary(ctx)["views_backend"] = name
    assert backend is not None
    backend(ctx, _spec(ctx))


def step_dimensions(ctx) -> None:
    ctx.progress(0.709, "dimensions")
    from sklent.palette import get as palette

    _paint(ctx, palette("white").shaded)
    name = f"{ctx.stem}-dimensions-2048.png"
    try:
        info = views.render_dimensions(_shooter(ctx), _spec(ctx), ctx.out_dir / name)
    finally:
        ctx.restore()
    _summary(ctx)["dimensions"] = info
    ctx.add(name, style=STYLE, variant="dimensions", width=2048, height=1536)


def step_assembly(ctx) -> None:
    st = _state(ctx)
    structure = assembly.structure(ctx.sc)
    cfg_steps = meta.pick(st["cfg"], "assembly.steps", "assembly_steps")
    unknown: list[str] = []
    if isinstance(cfg_steps, list) and cfg_steps:
        plan, unknown = assembly.steps_from_config(structure, cfg_steps)
        source = ".sklent.yaml"
    else:
        plan, source = assembly.default_steps(structure), "component order"
    cap = int(setting(ctx, "specs_assembly_max_steps"))
    info: dict[str, Any] = {"steps": len(plan), "from": source, "unknown": unknown}
    _summary(ctx)["assembly"] = info
    if len(plan) < 2:
        info["skipped"] = "not an assembly (fewer than two steps)"
        return
    if len(plan) > cap:
        info["skipped"] = f"{len(plan)} steps is over specs_assembly_max_steps ({cap}); list steps in .sklent.yaml"
        return
    ctx.progress(0.71, "assembly steps")
    size = (1600, 1200)
    cam = assembly.fit_camera(box(ctx), size, ctx.pitch)
    try:
        shots = assembly.run_steps(ctx, structure, plan, ctx.stem, cam, size)
    finally:
        ctx.restore()
    for s in shots:
        ctx.add(s["file"], style=STYLE, variant=f"assembly-{s['n']}", width=size[0], height=size[1])
    md = f"{ctx.stem}-assembly.md"
    (ctx.out_dir / md).write_text(assembly.buildup(_spec(ctx).get("title") or ctx.stem, shots, _spec(ctx)))
    ctx.add(md, style=STYLE, variant="assembly-md", guard=False)
    sets.write_json(ctx.out_dir, "assembly.json", {"from": source, "unknown": unknown, "steps": shots,
                                                  "markdown": md})


def step_cleanup(ctx) -> None:
    st = ctx.__dict__.get("_sk_specs") or {}
    sh = st.get("shooter")
    if sh is not None:
        _summary(ctx)["screenshots"] = {"count": sh.shots, **{k: round(v, 2) for k, v in sh.timings.items()}}
    shutil.rmtree(Path(ctx.out_dir) / "_specs", ignore_errors=True)


steps.register_step("specs-spec", step_spec, order=50)
steps.register_step("specs-bom", step_bom, order=55, when=lambda c: _bool(setting(c, "specs_bom")))
steps.register_step("specs-views", step_views, order=60,
                    when=lambda c: any(wanted(c, "specs_views", v) for v in ("views-sheet", "views-sheet-pdf")))
steps.register_step("specs-dimensions", step_dimensions, order=62,
                    when=lambda c: wanted(c, "specs_dimensions", "dimensions"))
steps.register_step("specs-assembly", step_assembly, order=70, when=lambda c: _bool(setting(c, "specs_assembly")))
steps.register_step("specs-cleanup", step_cleanup, order=79)


# ---------------------------------------------------------------- tables

SCHEMA = """
CREATE TABLE IF NOT EXISTS specs_contact_sheets (
    source_id TEXT NOT NULL,
    key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    designs INTEGER NOT NULL,
    pages INTEGER NOT NULL,
    kist_items TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (source_id, key)
);
"""


# ---------------------------------------------------------------- REST

router = APIRouter()


def _set_json(design_id: str, name: str) -> Any:
    try:
        jobs.get_design(design_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    s = sets.latest_set(design_id)
    data = sets.read_json(s["dir"], name) if s else None
    if data is None:
        raise HTTPException(404, f"design {design_id} has no {name} (render it with this feature on)")
    return data


@router.get("/designs/{design_id}/spec")
def get_spec(design_id: str):
    return _set_json(design_id, "spec.json")


@router.get("/designs/{design_id}/bom")
def get_bom(design_id: str):
    return _set_json(design_id, "bom.json")


@router.get("/designs/{design_id}/assembly")
def get_assembly(design_id: str):
    return _set_json(design_id, "assembly.json")


def _contact(source_id: str) -> dict:
    try:
        return contact.build(source_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0] if exc.args else exc)) from exc
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc


def contact_out(res: dict, kist_items: list | None = None) -> dict[str, Any]:
    base = f"/api/sources/{res['source_id']}/contact-sheet"
    return {"source_id": res["source_id"], "key": res["key"], "designs": res["designs"], "pages": res["pages"],
            "png": [f"{base}.png?page={i}" for i in range(1, res["pages"] + 1)], "pdf": f"{base}.pdf",
            "kist_items": kist_items or []}


def file_contact_in_kist(res: dict) -> list[dict]:
    """File the sheet's pages and PDF into Kist once per key (no-op with Kist off)."""
    from sklent import db
    from sklent.config import get_settings
    from sklent.kist import Kist

    with db.connect() as conn:
        row = conn.execute("SELECT kist_items FROM specs_contact_sheets WHERE source_id = ? AND key = ?",
                           [res["source_id"], res["key"]]).fetchone()
    if row and json.loads(row["kist_items"]):
        return json.loads(row["kist_items"])
    items: list[dict] = []
    kist = Kist()
    if kist.enabled:
        src = res["source"]
        path = [get_settings().kist_root_folder, src["owner"]] + ([src["repo"]] if src.get("repo") else [])
        folder_id = kist.ensure_folder(path)
        tags = ["solidcraft", f"repo:{src['owner']}/{src['repo']}" if src.get("repo") else f"owner:{src['owner']}",
                "format:contact-sheet"]
        notes = f"contact sheet of {res['designs']} designs in {src.get('label') or src.get('url')}, made by sklent"
        for f in [*res["png"], res["pdf"]]:
            item = kist.upload(f, folder_id=folder_id, tags=tags, notes=notes, source_url=src.get("url") or "")
            items.append({"id": item["id"], "file": f.name})
    with db.connect() as conn:
        conn.execute("INSERT INTO specs_contact_sheets (source_id, key, created_at, designs, pages, kist_items) "
                     "VALUES (?,?,?,?,?,?) ON CONFLICT(source_id, key) DO UPDATE SET kist_items = excluded.kist_items",
                     [res["source_id"], res["key"], db.now(), res["designs"], res["pages"], json.dumps(items)])
    return items


@router.post("/sources/{source_id}/contact-sheet")
def make_contact_sheet(source_id: str):
    res = _contact(source_id)
    try:
        items = file_contact_in_kist(res)
    except Exception as exc:  # Kist down: the sheet is still there to download
        log.warning("contact sheet for %s not filed in Kist: %s", source_id, exc)
        items = []
    return contact_out(res, items)


@router.get("/sources/{source_id}/contact-sheet.png")
def contact_sheet_png(source_id: str, page: int = 1):
    res = _contact(source_id)
    if not 1 <= page <= res["pages"]:
        raise HTTPException(404, f"the contact sheet has {res['pages']} page(s)")
    return FileResponse(res["png"][page - 1], media_type="image/png",
                        headers={"Cache-Control": "private, max-age=60"})


@router.get("/sources/{source_id}/contact-sheet.pdf")
def contact_sheet_pdf(source_id: str):
    res = _contact(source_id)
    return FileResponse(res["pdf"], media_type="application/pdf", filename=f"contact-sheet-{source_id}.pdf",
                        headers={"Cache-Control": "private, max-age=60"})


# ---------------------------------------------------------------- MCP

def register_mcp(mcp) -> None:

    @mcp.tool(name="get_design_spec", description=(
        "A design's spec (from its newest render): envelope bounds_mm/size_mm, volume, mass and material "
        "(only when a material is known), bodies, components, user parameters, commit, blob and licence."))
    def _get_design_spec(design_id: str) -> dict[str, Any]:
        return _mcp(lambda: get_spec(design_id))

    @mcp.tool(name="get_bom", description=(
        "A design's bill of materials: rows {item, qty, name, part_number, kind make|buy, source, supplier, url, "
        "price, total} from SolidCraft's assembly.bom merged with the repo's bom.yaml, plus a summary."))
    def _get_bom(design_id: str) -> dict[str, Any]:
        return _mcp(lambda: get_bom(design_id))

    @mcp.tool(name="make_contact_sheet", description=(
        "Make (or reuse) a contact sheet of every rendered design in a source: hero stills with mono labels and a "
        "title block, as PNG pages (3840x2160, 24 designs each) and one PDF. Files it into Kist when Kist is on. "
        "Returns download URL paths on this server."))
    def _make_contact_sheet(source_id: str) -> dict[str, Any]:
        return _mcp(lambda: make_contact_sheet(source_id))

    @mcp.tool(name="view_sheet", description=(
        "See one of a design's sheets: variant spec-card | bom-sheet | views-sheet | dimensions | assembly-<n>; "
        "size 256-2048 (default 1280)."))
    def view_sheet(design_id: str, variant: str = "spec-card", size: int = 1280) -> Image:
        from sklent import service

        d = jobs.get_design(design_id)
        f = next((f["file"] for f in d["files"] if f["variant"] == variant and f["file"].endswith(".png")), None)
        if f is None:
            raise ValueError(f"design {design_id} has no {variant} sheet")
        size = min(max(size, 256), 2048)
        with PILImage.open(service.file_path(design_id, f)) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "PNG")
        return Image(data=buf.getvalue(), format="png")


def _mcp(fn):
    try:
        return fn()
    except HTTPException as exc:
        raise ValueError(exc.detail) from exc


__all__ = ["DEFAULTS", "VARIANTS", "assembly", "bom", "contact", "draw", "ortho", "spec", "views"]
