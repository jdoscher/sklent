"""Outputs and publishing (Sklent 0.2, area O): everything that turns a render set into
something to upload or hand over, without ever uploading it.

- F6 output presets (presets.py): named size/aspect profiles, cached under `<set>/presets/`.
- F7 print and release file pack (filepack.py): a render step exporting STEP/3MF/STL from
  the same commit, plus README, licence and manifest; split for Etsy's 5 × 20 MB.
- F5 project page export (page.py): a static, offline HTML folder per design or source.
- F13 listing packs and text (listing.py): a zip per marketplace checked against its rules.
- F19 real photo slots (photos.py) and the "ready to list" checklist (listing.readiness).
- F23 brand presets (brand.py): watermark, title and end cards on exported copies only.
- F26 Kist review board (review.py): a set as a Kist board; a share link only on click.

Cross-feature hook: `share_link(design_id) -> str | None` (P's review comment).
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import brand, filepack, listing, page, photos, presets, review
from .common import SCHEMA, OutputError, design, exports_dir, meta, set_meta, the_set
from .review import share_link

__all__ = ["SCHEMA", "register_mcp", "router", "share_link"]


def _register_settings() -> None:
    from ... import jobs
    jobs.register_setting("outputs_presets", presets.DEFAULT_PRESETS, presets.validate)
    brand.register()
    filepack.register()  # also the render step "outputs-filepack" (order 90)
    listing.register()
    review.register()


_register_settings()

router = APIRouter(tags=["outputs"])


def _guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except OutputError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0] if exc.args else exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _download(path, name: str | None = None) -> FileResponse:
    return FileResponse(path, filename=name, headers={"Cache-Control": "private, no-cache"})


# ---------------------------------------------------------------- summary and metadata

def summary(design_id: str, set_id: str | None = None) -> dict[str, Any]:
    """Everything the detail sheet's outputs sections show, in one call."""
    d = design(design_id)
    out: dict[str, Any] = {"design_id": design_id, "meta": meta(design_id), "photos": photos.list_photos(design_id),
                           "readiness": listing.readiness(design_id, set_id)["markets"],
                           "review": review.get("design", design_id) if d["render_dir"] else None,
                           "brand": brand.config() is not None}
    try:
        s = the_set(design_id, set_id)
    except OutputError:
        return {**out, "set_id": None, "presets": [], "filepack": None, "exports": []}
    ex = exports_dir(s)
    exports = sorted(({"file": p.name, "bytes": p.stat().st_size,
                       "url": f"/api/designs/{design_id}/outputs/exports/{p.name}"}
                      for p in ex.iterdir() if p.is_file() and p.suffix == ".zip"), key=lambda x: x["file"])
    return {**out, "set_id": s["id"], "presets": presets.list_for(design_id, set_id)["presets"],
            "filepack": filepack.info(design_id, set_id), "exports": exports}


@router.get("/designs/{design_id}/outputs")
def get_outputs(design_id: str, set_id: str | None = None):
    return _guard(summary, design_id, set_id)


class MetaBody(BaseModel):
    title: str | None = None
    summary: str | None = None
    licence: str | None = None
    print_notes: str | None = None
    tags: list[str] | str | None = None
    hide_source: bool | None = None


@router.get("/designs/{design_id}/outputs/meta")
def get_meta(design_id: str):
    return _guard(meta, design_id)


@router.put("/designs/{design_id}/outputs/meta")
def put_meta(design_id: str, body: MetaBody):
    return _guard(set_meta, design_id, body.model_dump(exclude_unset=True))


@router.get("/outputs/marketplaces")
def marketplaces():
    return {k: {kk: vv for kk, vv in v.items()} for k, v in listing.MARKETS.items()}


@router.get("/outputs/readiness")
def readiness_all():
    """Per design with photos: {photos, needed, site} for tile badges."""
    return listing.badge_summary()


# ---------------------------------------------------------------- F6 presets

@router.get("/outputs/presets/defaults")
def preset_defaults():
    return presets.DEFAULT_PRESETS


@router.get("/designs/{design_id}/outputs/presets")
def list_presets(design_id: str, set_id: str | None = None):
    return _guard(presets.list_for, design_id, set_id)


@router.post("/designs/{design_id}/outputs/presets/{name}")
def make_preset(design_id: str, name: str, set_id: str | None = None):
    return _guard(presets.make, design_id, name, set_id)


@router.get("/designs/{design_id}/outputs/presets/{name}/file")
def preset_file(design_id: str, name: str, set_id: str | None = None, download: bool = False):
    path = _guard(presets.file_path, design_id, name, set_id)
    return _download(path, path.name if download else None)


@router.get("/designs/{design_id}/outputs/presets.zip")
def presets_zip(design_id: str, set_id: str | None = None, set: bool = False):  # noqa: A002
    path = _guard(presets.zip_all, design_id, set_id, set)
    return _download(path, path.name)


# ---------------------------------------------------------------- F7 file pack

class PackBody(BaseModel):
    split_mb: float | None = None


@router.get("/designs/{design_id}/outputs/filepack")
def get_filepack(design_id: str, set_id: str | None = None):
    return _guard(filepack.info, design_id, set_id)


@router.post("/designs/{design_id}/outputs/filepack")
def build_filepack(design_id: str, body: PackBody | None = None, set_id: str | None = None):
    split = body.split_mb if body else None
    if split is not None and not 1 <= split <= 2000:
        raise HTTPException(422, "split_mb must be 1 to 2000")
    return _guard(filepack.build, design_id, set_id, split)


@router.get("/designs/{design_id}/outputs/exports/{name}")
def export_file(design_id: str, name: str, set_id: str | None = None):
    from .common import export_path
    s = _guard(the_set, design_id, set_id)
    return _download(_guard(export_path, s, name), name)


# ---------------------------------------------------------------- F5 page

class PageBody(BaseModel):
    include_files: bool = True
    hide_source: bool | None = None


@router.post("/designs/{design_id}/outputs/page")
def build_page(design_id: str, body: PageBody | None = None, set_id: str | None = None):
    b = body or PageBody()
    return _guard(page.build_design, design_id, set_id, include_files=b.include_files, hide_source=b.hide_source)


@router.get("/designs/{design_id}/outputs/page.zip")
def page_zip(design_id: str, set_id: str | None = None, files: bool = True, source: bool = True):
    r = _guard(page.build_design, design_id, set_id, include_files=files, hide_source=None if source else True)
    s = _guard(the_set, design_id, set_id)
    return _download(exports_dir(s) / r["file"], r["file"])


@router.post("/sources/{source_id}/outputs/page")
def build_source_page(source_id: str, body: PageBody | None = None):
    b = body or PageBody(include_files=False)
    return _guard(page.build_source, source_id, include_files=b.include_files, hide_source=bool(b.hide_source))


@router.get("/sources/{source_id}/outputs/page.zip")
def source_page_zip(source_id: str, rebuild: bool = False):
    if rebuild:
        _guard(page.build_source, source_id)
    path = _guard(page.source_zip, source_id)
    return _download(path, path.name)


# ---------------------------------------------------------------- F13 listing, F19 readiness

@router.get("/designs/{design_id}/outputs/listing")
def get_readiness(design_id: str, set_id: str | None = None):
    return _guard(listing.readiness, design_id, set_id)


@router.get("/designs/{design_id}/outputs/listing/{market}/text")
def get_listing_text(design_id: str, market: str, set_id: str | None = None, plain: bool | None = None):
    text = _guard(listing.listing_text, design_id, set_id, market, plain)
    return Response(text, media_type="text/markdown; charset=utf-8")


@router.post("/designs/{design_id}/outputs/listing/{market}")
def build_listing(design_id: str, market: str, set_id: str | None = None):
    return _guard(listing.build, design_id, market, set_id)


# ---------------------------------------------------------------- F19 photos

@router.get("/designs/{design_id}/outputs/photos")
def get_photos(design_id: str):
    return _guard(photos.list_photos, design_id)


@router.post("/designs/{design_id}/outputs/photos", status_code=201)
async def post_photo(design_id: str, request: Request, name: str = "", caption: str = ""):
    """The request body is the image file itself (JPEG, PNG or WebP), up to 30 MB."""
    data = await request.body()
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(_guard, photos.add_photo, design_id, data, name, caption)


class PhotoPatch(BaseModel):
    caption: str | None = None
    position: int | None = None


@router.patch("/designs/{design_id}/outputs/photos/{photo_id}")
def patch_photo(design_id: str, photo_id: str, body: PhotoPatch):
    return _guard(photos.update_photo, design_id, photo_id, body.caption, body.position)


@router.delete("/designs/{design_id}/outputs/photos/{photo_id}")
def delete_photo(design_id: str, photo_id: str):
    _guard(photos.delete_photo, design_id, photo_id)
    return {"deleted": photo_id}


@router.get("/designs/{design_id}/outputs/photos/{photo_id}/file")
def photo_file(design_id: str, photo_id: str):
    return _download(_guard(photos.photo_file, design_id, photo_id))


# ---------------------------------------------------------------- F23 brand

@router.get("/outputs/brand")
def get_brand():
    return {"config": brand.config(), "mark": brand.mark_info()}


@router.put("/outputs/brand/mark")
async def put_mark(request: Request):
    data = await request.body()
    return _guard(brand.save_mark, data)


@router.delete("/outputs/brand/mark")
def delete_mark():
    brand.mark_path().unlink(missing_ok=True)
    return {"mark": None}


@router.get("/outputs/brand/mark")
def get_mark():
    p = brand.mark_path()
    if not p.is_file():
        raise HTTPException(404, "no mark uploaded")
    return _download(p)


@router.get("/outputs/brand/preview")
def brand_preview(kind: str = "watermark", design_id: str | None = None):
    """A small PNG of the watermark, title card or end card as set now."""
    import io

    from PIL import Image

    cfg = brand.config() or {k.removeprefix("outputs_brand_"): v for k, (v, _) in brand.SETTINGS.items()}
    info = {"title": "Design title", "envelope": "95 × 66 × 32 mm", "bodies": "1 body", "commit": "0123456789",
            "repo": "owner/repo"}
    if design_id:
        try:
            from . import media
            d = design(design_id)
            info = media.card_info(d, the_set(design_id), meta(design_id)["title"])
        except (KeyError, OutputError):
            pass
    if kind in ("title", "end"):
        img = brand.card(960, 540, kind, info, cfg)
    elif kind == "watermark":
        img = brand.watermark(Image.new("RGB", (960, 540), (236, 239, 243)), cfg)
    else:
        raise HTTPException(422, "kind is watermark, title or end")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- F26 review

class ShareBody(BaseModel):
    password: str | None = None


def _review_routes(scope: str, prefix: str) -> None:
    @router.get(f"{prefix}/outputs/review", name=f"review_{scope}")
    def get_review(target_id: str):
        return _guard(review.get, scope, target_id)

    @router.post(f"{prefix}/outputs/review/board", name=f"review_board_{scope}")
    def post_board(target_id: str):
        return _guard(review.make_board, scope, target_id)

    @router.delete(f"{prefix}/outputs/review/board", name=f"review_board_delete_{scope}")
    def delete_board(target_id: str):
        return _guard(review.delete_board, scope, target_id)

    @router.post(f"{prefix}/outputs/review/share", name=f"review_share_{scope}")
    def post_share(target_id: str, body: ShareBody | None = None):
        return _guard(review.create_share, scope, target_id, password=(body.password if body else None) or None)

    @router.delete(f"{prefix}/outputs/review/share", name=f"review_revoke_{scope}")
    def delete_share(target_id: str):
        return _guard(review.revoke, scope, target_id)


_review_routes("design", "/designs/{target_id}")
_review_routes("source", "/sources/{target_id}")


# ---------------------------------------------------------------- MCP

def register_mcp(mcp) -> None:
    def call(fn, *a, **k):
        try:
            return fn(*a, **k)
        except OutputError as exc:
            raise ValueError(str(exc)) from exc

    @mcp.tool(description=(
        "Outputs for a design's newest render set: listing details (title, summary, licence, print notes), "
        "real print photos, output presets (made or not, with download paths), the print file pack, export zips, "
        "the per-marketplace 'ready to list' checklist and the Kist review board. Nothing here posts anywhere."))
    def get_outputs(design_id: str) -> dict[str, Any]:
        return call(summary, design_id)

    @mcp.tool(description=(
        "Make output presets for a design: sized copies of its render set for a site (default presets: "
        "cover-4x3 Printables/MakerWorld cover, cults-800 video, youtube-thumb, linkedin-4x5, github-social, "
        "handshake PDF, instagram-4x5; the list is the outputs_presets setting). preset empty = every enabled "
        "preset. Returns each file's download path (same token), size and whether it fits the site's cap."))
    def make_output_preset(design_id: str, preset: str | None = None) -> list[dict[str, Any]]:
        names = [preset] if preset else [p["name"] for p in presets.all_presets() if p["enabled"]]
        return [call(presets.make, design_id, n) for n in names]

    @mcp.tool(description=(
        "Build the print and release file pack of a design: the STEP/3MF/STL SolidCraft exported from the same "
        "commit as the renders (needs the outputs_filepack setting on before the render), with README.md, "
        "LICENSE.txt and manifest.json (sha256 sums). split_mb splits it into standalone zips of at most that "
        "size (Etsy: 20). Returns the zip download paths."))
    def build_file_pack(design_id: str, split_mb: float | None = None) -> dict[str, Any]:
        return call(filepack.build, design_id, None, split_mb)

    @mcp.tool(description=(
        "Export a static, offline project page (HTML folder, zipped) for one design (design_id) or a whole source "
        "(source_id): hero, gallery with real photos first, turntable, spec, BOM, files, licence and commit. "
        "Download only; it is never hosted or posted. hide_source drops the repo URL and commit link."))
    def export_project_page(design_id: str | None = None, source_id: str | None = None, include_files: bool = True,
                            hide_source: bool = False) -> dict[str, Any]:
        if bool(design_id) == bool(source_id):
            raise ValueError("give design_id or source_id")
        if design_id:
            return call(page.build_design, design_id, None, include_files=include_files,
                        hide_source=hide_source or None)
        return call(page.build_source, source_id, include_files=include_files, hide_source=hide_source)

    @mcp.tool(description=(
        "Build a listing pack for one marketplace (printables, makerworld, thingiverse, cults, etsy): a zip with "
        "the pictures in upload order (real photos first, renders cut to the site's sizes), the clips it takes, "
        "the print files (split where the site caps them), listing.md and pack.json with every rule checked. "
        "Nothing is posted."))
    def build_listing_pack(design_id: str, marketplace: str) -> dict[str, Any]:
        return call(listing.build, design_id, marketplace)

    @mcp.tool(description="Per marketplace, the 'ready to list' checklist for a design: real photos, licence, "
                          "print files, sizes. Informs only; packs are built either way.")
    def listing_readiness(design_id: str) -> dict[str, Any]:
        return call(listing.readiness, design_id)

    @mcp.tool(description="The listing text (Markdown; plain for Etsy) for a design and marketplace, filled from "
                          "the spec, BOM, licence and print notes.")
    def listing_text(design_id: str, marketplace: str = "printables") -> str:
        return call(listing.listing_text, design_id, None, marketplace)

    @mcp.tool(description=(
        "Set a design's listing details used by packs and pages: title, summary, licence (an SPDX id such as "
        "CC-BY-4.0, or the text), print_notes, tags. These win over the repo's .sklent.yaml."))
    def set_listing_details(design_id: str, title: str | None = None, summary: str | None = None,
                            licence: str | None = None, print_notes: str | None = None,
                            tags: list[str] | None = None) -> dict[str, Any]:
        changes = {k: v for k, v in {"title": title, "summary": summary, "licence": licence,
                                     "print_notes": print_notes, "tags": tags}.items() if v is not None}
        return call(set_meta, design_id, changes)

    @mcp.tool(description=(
        "Attach a real print photo to a design (JPEG, PNG or WebP as base64). Photos go first in listing packs "
        "and project pages, are never repainted, and have EXIF (GPS) removed. Filed into Kist when Kist is on."))
    def attach_photo(design_id: str, image_base64: str, name: str = "", caption: str = "") -> dict[str, Any]:
        try:
            data = base64.b64decode(image_base64, validate=True)
        except ValueError as exc:
            raise ValueError("image_base64 isn't base64") from exc
        return call(photos.add_photo, design_id, data, name, caption)

    @mcp.tool(description="A design's real print photos, in order, with download paths.")
    def list_photos(design_id: str) -> list[dict[str, Any]]:
        return call(photos.list_photos, design_id)

    @mcp.tool(description=(
        "Lay a design's (design_id) or a source's (source_id) render set out as a board in Kist (Kist must be on). "
        "The board stays inside Kist; nothing is shared."))
    def make_review_board(design_id: str | None = None, source_id: str | None = None) -> dict[str, Any]:
        scope, target = _scope(design_id, source_id)
        return call(review.make_board, scope, target)

    @mcp.tool(description=(
        "Create a PUBLIC Kist share link to a design's or source's review board, with guest proofing (picks and "
        "comments) if outputs_review_proofing is on. Refused unless the outputs_review_share_links setting is on. "
        "Anyone with the link can open it until it expires or is revoked. Only call this when the user asks."))
    def create_share_link(design_id: str | None = None, source_id: str | None = None,
                          password: str | None = None) -> dict[str, Any]:
        scope, target = _scope(design_id, source_id)
        return call(review.create_share, scope, target, password=password)

    @mcp.tool(description="Revoke a design's or source's Kist share link.")
    def revoke_share_link(design_id: str | None = None, source_id: str | None = None) -> dict[str, Any]:
        scope, target = _scope(design_id, source_id)
        return call(review.revoke, scope, target)


def _scope(design_id: str | None, source_id: str | None) -> tuple[str, str]:
    if bool(design_id) == bool(source_id):
        raise ValueError("give design_id or source_id")
    return ("design", design_id) if design_id else ("source", source_id)  # type: ignore[return-value]
