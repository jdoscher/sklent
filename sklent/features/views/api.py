"""REST routes and MCP tools of the views area."""

import io
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from mcp.server.mcpserver import Image
from PIL import Image as PILImage
from pydantic import BaseModel

from ... import jobs, sets
from ...config import get_settings
from ...render import CORE_OUTPUTS, SHOTS
from . import beds as bedlib

router = APIRouter()

VIEW_VARIANTS = ("preview", "exploded", "explode-anim", "section", "config-lineup", "config-<n>",
                 "highlight", "highlight-turntable", "motion-<study>", "transparent", "hero", "plate",
                 "master-4k", "frames-zip", "prores", *(f"preset-{s}" for s in SHOTS))


def _views_pkg():
    import importlib
    return importlib.import_module("sklent.features.views")


# ---------------------------------------------------------------- data

def preview_file(design: dict) -> Path | None:
    """The newest quick-check still of a design: the one a running render just made, or
    the latest set's."""
    folder = get_settings().renders_dir / design["id"]
    found = sorted(folder.glob("*/*-preview.png"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if folder.is_dir() else []
    return found[0] if found else None


_facts_cache: dict[Path, tuple[float, Any]] = {}


def set_facts(design_id: str) -> tuple[dict | None, dict | None]:
    """(views.json, report["views"]) of the latest set."""
    s = sets.latest_set(design_id)
    if not s:
        return None, None
    p = Path(s["dir"]) / "views.json"
    facts = None
    if p.is_file():
        mtime = p.stat().st_mtime
        hit = _facts_cache.get(p)
        if hit and hit[0] == mtime:
            facts = hit[1]
        else:
            facts = sets.read_json(Path(s["dir"]), "views.json")
            _facts_cache[p] = (mtime, facts)
    return facts, (s.get("report") or {}).get("views")


def _parts(design_id: str, facts: dict | None) -> list[dict]:
    if facts and facts.get("parts"):
        return facts["parts"]
    s = sets.latest_set(design_id)  # an older set: one body's envelope is its size
    rep = (s or {}).get("report") or {}
    b = rep.get("bounds_mm")
    if b and rep.get("bodies") == 1:
        return [{"name": "body", "size": [b[1][i] - b[0][i] for i in range(3)]}]
    return []


def bed_fit(design_id: str, facts: dict | None, settings: dict | None = None) -> dict | None:
    st = settings or jobs.get_all_settings()
    if not st.get("views_bedfit", True):
        return None
    try:
        beds = bedlib.parse_beds(st.get("views_beds") or bedlib.DEFAULT_BEDS)
    except ValueError:
        beds = bedlib.parse_beds(bedlib.DEFAULT_BEDS)
    return bedlib.bed_fit(_parts(design_id, facts), beds, st.get("views_bed"))


def design_views(d: dict, settings: dict | None = None) -> dict[str, Any]:
    """The small `views` block on every design in the API: the quick-check still's URL (also
    while the render runs) and the bed-fit badge's data."""
    p = preview_file(d)
    facts, _ = set_facts(d["id"])
    return {
        "preview_url": f"/api/designs/{d['id']}/views/preview?v={int(p.stat().st_mtime)}" if p else None,
        "bed_fit": bed_fit(d["id"], facts, settings),
    }


def views_info(design_id: str) -> dict[str, Any]:
    pkg = _views_pkg()
    d = jobs.get_design(design_id)
    st = jobs.get_all_settings()
    facts, notes = set_facts(design_id)
    names, source = pkg.highlight_for(design_id)
    try:
        beds = bedlib.parse_beds(st.get("views_beds") or bedlib.DEFAULT_BEDS)
    except ValueError:
        beds = []
    return {
        "design_id": design_id,
        **design_views(d, st),
        "beds": beds,
        "bed": st.get("views_bed"),
        "highlight": {"names": names, "source": source},
        "request": pkg.pending_request(design_id),
        "facts": {k: (facts or {}).get(k) for k in ("configurations", "active_configuration",
                                                       "motion_studies", "explode_views")},
        "bodies": ((facts or {}).get("bodies") or [])[:500],
        "notes": notes,
        "outputs": list(CORE_OUTPUTS),
        "settings": {k: st.get(k) for k in pkg.SETTINGS},
    }


def queue_render(design_id: str, outputs: list[str] | None = None, preview_only: bool = False,
                 settings: dict[str, Any] | None = None) -> dict[str, Any]:
    pkg = _views_pkg()
    jobs.get_design(design_id)
    req = pkg.clean_request(outputs, preview_only, settings)
    if req:
        pkg.save_request(design_id, req)
    else:
        pkg.drop_request(design_id)
    job = jobs.enqueue("render", design_id=design_id, force=True)
    return {"job": job, "request": req}


# ---------------------------------------------------------------- REST

class RenderChoice(BaseModel):
    outputs: list[str] | None = None
    preview_only: bool = False
    settings: dict[str, Any] | None = None


class Highlight(BaseModel):
    names: list[str]


def _404(exc: KeyError) -> HTTPException:
    return HTTPException(404, str(exc.args[0] if exc.args else exc))


@router.get("/designs/{design_id}/views")
def get_views(design_id: str):
    try:
        return views_info(design_id)
    except KeyError as exc:
        raise _404(exc) from exc


@router.get("/designs/{design_id}/views/preview")
def get_preview(design_id: str):
    try:
        d = jobs.get_design(design_id)
    except KeyError as exc:
        raise _404(exc) from exc
    p = preview_file(d)
    if p is None:
        raise HTTPException(404, "no quick-check still yet")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.post("/designs/{design_id}/views/render")
def post_render(design_id: str, body: RenderChoice):
    try:
        return queue_render(design_id, body.outputs, body.preview_only, body.settings)
    except KeyError as exc:
        raise _404(exc) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/designs/{design_id}/views/highlight")
def get_highlight(design_id: str):
    try:
        jobs.get_design(design_id)
    except KeyError as exc:
        raise _404(exc) from exc
    names, source = _views_pkg().highlight_for(design_id)
    return {"names": names, "source": source}


@router.put("/designs/{design_id}/views/highlight")
def put_highlight(design_id: str, body: Highlight):
    try:
        jobs.get_design(design_id)
        names = _views_pkg().set_highlight(design_id, body.names)
    except KeyError as exc:
        raise _404(exc) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"names": names, "source": "design" if names else None}


@router.get("/views/beds")
def get_beds():
    st = jobs.get_all_settings()
    return {"beds": bedlib.parse_beds(st.get("views_beds") or bedlib.DEFAULT_BEDS),
            "bed": st.get("views_bed"), "badge": bool(st.get("views_bedfit", True))}


# ---------------------------------------------------------------- MCP

def register_mcp(mcp) -> None:
    from ... import service

    @mcp.tool(description=(
        "Quick check: queue a render of a design that makes only one shaded iso still (a few "
        "seconds after the design loads). It replaces this commit's set with that still; render "
        "again with render_outputs for the full set."))
    def quick_check(design_id: str) -> dict[str, Any]:
        return queue_render(design_id, preview_only=True)

    @mcp.tool(description=(
        "Queue a render with a chosen set of outputs. outputs: some of 1080p, reel, discord, gif, "
        "social, hires (omit for the saved setting; [] = quick-check still only). settings: feature "
        "toggles for this render only, e.g. {\"views_exploded\": true, \"views_section\": true, "
        "\"views_shot_push_in\": true, \"views_master_4k\": true, \"views_hero\": true}. A quick-check "
        "still is always made first."))
    def render_outputs(design_id: str, outputs: list[str] | None = None,
                       settings: dict[str, Any] | None = None) -> dict[str, Any]:
        return queue_render(design_id, outputs, False, settings)

    @mcp.tool(description=(
        "A design's views: the quick-check still URL, bed fit against the configured printer beds "
        "(largest part, fits/too big, which beds fit), its configurations, motion studies and "
        "exploded views, the highlight list, notes from the last render (skipped views and why) "
        "and the views settings."))
    def get_views(design_id: str) -> dict[str, Any]:
        return views_info(design_id)

    @mcp.tool(description=(
        "Set a design's \"my part\" highlight: body names or globs (e.g. [\"Upper arm*\", \"Gripper\"]). "
        "Those render solid and the rest x-ray, as an extra still and turntable on the next render. "
        "[] clears it (a .sklent.yaml highlight then applies, if any)."))
    def set_highlight(design_id: str, names: list[str]) -> dict[str, Any]:
        jobs.get_design(design_id)
        return {"names": _views_pkg().set_highlight(design_id, names)}

    @mcp.tool(description=(
        "See any still of a design's set by file name or variant (preview, exploded, section, "
        "config-lineup, highlight, transparent, hero, plate, ...); variant preview also works while "
        "a render runs. size 256-2048."))
    def view_output(design_id: str, variant: str = "preview", file: str | None = None,
                    size: int = 1024) -> Image:
        d = jobs.get_design(design_id)
        if variant == "preview" and not file:
            path = preview_file(d)
            if path is None:
                raise ValueError("no quick-check still yet")
        else:
            name = file or next((f["file"] for f in d["files"] if f["variant"] == variant
                                 and f["file"].endswith(".png")), None)
            if not name:
                raise ValueError(f"no still with variant {variant}")
            path = service.file_path(design_id, name)
        size = min(max(size, 256), 2048)
        with PILImage.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "PNG")
        return Image(data=buf.getvalue(), format="png")

    @mcp.tool(description=(
        "Change the views settings for future renders: outputs (core outputs list) and any views_* "
        "key (see get_views().settings), e.g. {\"views_exploded\": true, \"views_bed\": \"Prusa MK4\"}."))
    def set_views_settings(changes: dict[str, Any]) -> dict[str, Any]:
        bad = [k for k in changes if not (k == "outputs" or k.startswith("views_"))]
        if bad:
            raise ValueError(f"not a views setting: {', '.join(bad)}")
        jobs.set_options(changes)
        st = jobs.get_all_settings()
        return {k: st[k] for k in st if k == "outputs" or k.startswith("views_")}
