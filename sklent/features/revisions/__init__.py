"""Revisions (F1) and the build-history timelapse (F29).

F1: every rendered version of a design keeps its own render set (one per blob, labelled
with the commit that made it and any git tags that point at it), instead of the newest
replacing the rest. Kist items are never trashed by a re-render; new ones are filed as
Kist versions (`version_of` + stack) of the previous set's items, and every item carries
`rev:<commit10>`. The keep policy prunes old untagged sets from disk only.

REST (under /api):
    GET /designs/{id}/sets                       every kept set, newest first
    GET /designs/{id}/sets/{set}                 one set
    GET /designs/{id}/sets/{set}/files/{name}    a file of any kept set
    GET /designs/{id}/compare?a=&b=&style=&variant=&frame=
                                                 pixel compare of two sets (a older, b newer)
    GET /designs/{id}/compare/diff.png?...       the changed-pixel mask (alpha)
    GET /designs/{id}/compare/frame.png?set=&style=&variant=&frame=
                                                 one frame of a set's video, as PNG
    GET /designs/{id}/compare/composite.png?...  older | newer | changes, for agents
    GET /designs/{id}/changelog?base=&head=      commits that changed the file in between

MCP: list_sets, compare_sets, view_compare.
"""

from __future__ import annotations

import io
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from mcp.server.mcpserver import Image
from PIL import Image as PILImage

from ... import jobs, sets
from ...service import render_report
from ...sources import Forge
from . import compare, timelapse

# ---------------------------------------------------------------- settings


def _keep(v: Any) -> int:
    if v in ("all", "", None):
        return 0
    try:
        n = int(v)
    except (TypeError, ValueError) as exc:
        raise ValueError("revisions_keep must be a number of sets (0 = keep all)") from exc
    if not 0 <= n <= 10000:
        raise ValueError("revisions_keep must be 0 (keep all) to 10000")
    return n


def _bounded(lo: int, hi: int, name: str):
    def check(v: Any) -> int:
        n = int(v)
        if not lo <= n <= hi:
            raise ValueError(f"{name} must be {lo} to {hi}")
        return n
    return check


jobs.register_setting("revisions_keep", 10, _keep)
jobs.register_setting("revisions_prune_kist", False, bool)
jobs.register_setting("revisions_timelapse", False, bool)
jobs.register_setting("revisions_timelapse_max_features", 200,
                      _bounded(2, 10000, "revisions_timelapse_max_features"))
jobs.register_setting("revisions_timelapse_max_bodies", 100,
                      _bounded(1, 100000, "revisions_timelapse_max_bodies"))
timelapse.register()

# ---------------------------------------------------------------- shapes


def set_out(s: dict) -> dict[str, Any]:
    base = f"/api/designs/{s['design_id']}/sets/{s['id']}/files/"
    files = []
    for f in s["files"]:
        p = s["dir"] / f["file"]
        files.append({**f, "url": base + f["file"], "bytes": p.stat().st_size if p.is_file() else None})

    def pick(style: str, variant: str) -> str | None:
        return next((f["url"] for f in files if f["style"] == style and f["variant"] == variant), None)

    commit = s.get("commit") or {}
    return {
        "id": s["id"],
        "design_id": s["design_id"],
        "current": bool(s.get("current")),
        "blob": s.get("blob_sha"),
        "commit": (s.get("commit_sha") or "")[:10] or None,
        "commit_sha": s.get("commit_sha"),
        "message": (commit.get("message") or "").split("\n", 1)[0] or None,
        "author": commit.get("author"),
        "date": commit.get("date"),
        "rendered_at": s.get("rendered_at"),
        "tags": s.get("tags") or [],
        "palette": s.get("palette") or ((s.get("report") or {}).get("options") or {}).get("palette"),
        "thumb_url": pick("shaded", "social") or pick("wireframe", "social"),
        "files": files,
        "kist_items": s.get("kist_items") or [],
        "report": render_report(s["dir"]),
    }


def _sets(design_id: str) -> list[dict]:
    try:
        jobs.get_design(design_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    return sets.list_sets(design_id)


def _pair(design_id: str, a: str | None, b: str | None) -> tuple[dict, dict]:
    """(older, newer). Defaults: b = the current set, a = the next older one."""
    all_ = _sets(design_id)
    if len(all_) < 2 and not (a and b):
        raise HTTPException(409, "this design has only one kept set; render a newer version to compare")
    by_id = {s["id"]: s for s in all_}
    sb = by_id.get(b) if b else next((s for s in all_ if s.get("current")), all_[0] if all_ else None)
    if sb is None:
        raise HTTPException(404, f"no set {b}")
    if a:
        sa = by_id.get(a)
        if sa is None:
            raise HTTPException(404, f"no set {a}")
    else:
        older = [s for s in all_[all_.index(sb) + 1:]] or [s for s in all_ if s is not sb]
        sa = older[0]
    if sa["id"] == sb["id"]:
        raise HTTPException(422, "pick two different sets")
    return sa, sb


def _compare(design_id: str, a: str | None, b: str | None, style: str, variant: str,
             frame: int | None) -> tuple[dict, dict, dict]:
    sa, sb = _pair(design_id, a, b)
    try:
        d = compare.diff(sa, sb, style, variant, frame)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
    return sa, sb, d


def compare_out(design_id: str, a: str | None, b: str | None, style: str = "shaded",
                variant: str = "hires", frame: int | None = None) -> dict[str, Any]:
    sa, sb, d = _compare(design_id, a, b, style, variant, frame)
    q = f"a={sa['id']}&b={sb['id']}&style={style}&variant={variant}" + (f"&frame={frame}" if frame is not None else "")
    root = f"/api/designs/{design_id}"
    fa, fb = compare.pick(sa, style, variant), compare.pick(sb, style, variant)
    assert fa is not None and fb is not None  # diff() found both
    video = fa["file"].lower().endswith(compare.VIDEO)

    def img(s: dict, f: dict) -> str:
        if video:
            return f"{root}/compare/frame.png?set={s['id']}&style={style}&variant={variant}&frame={frame or 0}"
        return f"{root}/sets/{s['id']}/files/{f['file']}"

    return {
        "a": set_out(sa), "b": set_out(sb),
        "style": style, "variant": variant, "frame": frame if video else None,
        "frames": compare.frame_count(sb, fb) if video else None,
        "a_url": img(sa, fa), "b_url": img(sb, fb),
        "diff_url": f"{root}/compare/diff.png?{q}",
        "composite_url": f"{root}/compare/composite.png?{q}",
        "changed": d["changed"], "changed_pct": d["changed_pct"], "bbox": d["bbox"],
        "width": d["width"], "height": d["height"],
        "reframed": compare.reframed(sa, sb),
        "choices": compare.common_files(sa, sb),
    }


_log_cache: dict[tuple, tuple[float, dict]] = {}


def changelog_out(design_id: str, base: str | None, head: str | None) -> dict[str, Any]:
    sa, sb = _pair(design_id, base, head)
    key = (design_id, sa["id"], sa.get("commit_sha"), sb["id"], sb.get("commit_sha"))
    hit = _log_cache.get(key)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    design = jobs.get_design(design_id)
    source = jobs.get_source(design["source_id"])
    try:
        log = sets.changelog(Forge(source["provider"], source["host"]), design, sa, sb)
    except Exception as exc:  # noqa: BLE001 - offline forge, rate limit: say so
        return {"base": sa["id"], "head": sb["id"], "commits": [], "complete": False,
                "error": f"the forge didn't answer: {exc}"[:300]}
    out = {"base": sa["id"], "head": sb["id"], **log}
    _log_cache[key] = (time.monotonic(), out)
    return out


# ---------------------------------------------------------------- REST

router = APIRouter()


@router.get("/designs/{design_id}/sets")
def list_sets_api(design_id: str):
    return [set_out(s) for s in _sets(design_id)]


@router.get("/designs/{design_id}/sets/{set_id}")
def get_set_api(design_id: str, set_id: str):
    _sets(design_id)
    s = sets.get_set(design_id, set_id)
    if s is None:
        raise HTTPException(404, f"no set {set_id}")
    return set_out(s)


@router.get("/designs/{design_id}/sets/{set_id}/files/{name}")
def set_file(design_id: str, set_id: str, name: str):
    try:
        path = sets.file_path(design_id, set_id, name)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/designs/{design_id}/compare")
def compare_api(design_id: str, a: str | None = None, b: str | None = None, style: str = "shaded",
                variant: str = "hires", frame: int | None = None):
    return compare_out(design_id, a, b, style, variant, frame)


@router.get("/designs/{design_id}/compare/diff.png")
def compare_diff(design_id: str, a: str | None = None, b: str | None = None, style: str = "shaded",
                 variant: str = "hires", frame: int | None = None):
    _, _, d = _compare(design_id, a, b, style, variant, frame)
    return FileResponse(d["mask"], media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/designs/{design_id}/compare/frame.png")
def compare_frame(design_id: str, set: str, style: str = "shaded", variant: str = "1080p",  # noqa: A002
                  frame: int = 0):
    _sets(design_id)
    s = sets.get_set(design_id, set)
    if s is None:
        raise HTTPException(404, f"no set {set}")
    try:
        path = compare.image_of(s, style, variant, frame)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/designs/{design_id}/compare/composite.png")
def compare_composite(design_id: str, a: str | None = None, b: str | None = None, style: str = "shaded",
                      variant: str = "hires", frame: int | None = None, width: int = 1600):
    sa, sb = _pair(design_id, a, b)
    try:
        path = compare.composite(sa, sb, style, variant, frame, min(max(width, 320), 4096))
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/designs/{design_id}/changelog")
def changelog_api(design_id: str, base: str | None = None, head: str | None = None):
    return changelog_out(design_id, base, head)


# ---------------------------------------------------------------- MCP


def register_mcp(mcp) -> None:
    @mcp.tool(description=(
        "Every kept render set (revision) of a design, newest first: set id, the commit that made "
        "that version (sha, message, author, date), git tags pointing at it, when it was rendered, "
        "whether it is the current one, and its files with download URL paths (same token). "
        "Older sets stay when a design changes; the keep policy (revisions_keep) prunes old "
        "untagged ones."))
    def list_sets(design_id: str) -> list[dict[str, Any]]:
        out = [set_out(s) for s in _sets(design_id)]
        for s in out:
            s["files"] = [{k: f[k] for k in ("file", "style", "variant", "width", "height", "url")} for f in s["files"]]
            s.pop("kist_items", None)
        return out

    @mcp.tool(description=(
        "Compare two render sets of a design (a = older, b = newer set id; defaults: the current "
        "set against the one before it). Uses the same still (variant social|hires) or the same "
        "frame of a turntable (variant 1080p|reel|discord|gif with frame=n) from both sets. "
        "Returns the share of pixels that changed, their bounding box (fractions of the image), "
        "image URL paths for both, a changed-pixel mask and a side-by-side composite, plus the "
        "commit messages between the two versions from the forge. reframed=true means the "
        "envelope changed, so the two stills are framed differently."))
    def compare_sets(design_id: str, a: str | None = None, b: str | None = None, style: str = "shaded",
                     variant: str = "hires", frame: int | None = None) -> dict[str, Any]:
        out = compare_out(design_id, a, b, style, variant, frame)
        out["changelog"] = changelog_out(design_id, out["a"]["id"], out["b"]["id"])
        for k in ("a", "b"):
            out[k] = {x: out[k][x] for x in ("id", "commit", "message", "date", "tags", "rendered_at", "current")}
        return out

    @mcp.tool(description=(
        "See a compare of two render sets as one picture: older | newer | changed pixels in "
        "ink on a faded copy of the newer. Same arguments as compare_sets; size 320-2048."))
    def view_compare(design_id: str, a: str | None = None, b: str | None = None, style: str = "shaded",
                     variant: str = "hires", frame: int | None = None, size: int = 1600) -> Image:
        sa, sb = _pair(design_id, a, b)
        path = compare.composite(sa, sb, style, variant, frame, min(max(size, 320), 2048))
        with PILImage.open(path) as im:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "PNG")
        return Image(data=buf.getvalue(), format="png")
