from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__, db, jobs, service
from .render import RenderOptions
from .sources import SourceError

router = APIRouter()


class SourceCreate(BaseModel):
    url: str
    auto_render: bool = True
    exclude: list[str] | None = None
    scan: bool = True


class SourcePatch(BaseModel):
    auto_render: bool | None = None
    exclude: list[str] | None = None


class RenderRequest(BaseModel):
    force: bool = False


class RenderUrl(BaseModel):
    url: str
    force: bool = False


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(404, str(exc.args[0] if exc.args else exc))


@router.get("/health")
def health():
    return {"ok": True, "version": __version__}


@router.get("/status")
def status():
    return service.status()


@router.get("/sources")
def list_sources():
    return service.list_sources()


@router.post("/sources", status_code=201)
def add_source(body: SourceCreate):
    try:
        source = jobs.add_source(body.url, body.auto_render, body.exclude)
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = jobs.enqueue("scan", source_id=source["id"]) if body.scan else None
    return {"source": source, "job": job}


@router.patch("/sources/{source_id}")
def patch_source(source_id: str, body: SourcePatch):
    try:
        jobs.get_source(source_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    changes: dict[str, Any] = body.model_dump(exclude_unset=True)
    if "auto_render" in changes:
        changes["auto_render"] = int(changes["auto_render"])
    with db.connect() as conn:
        db.update(conn, "sources", source_id, **changes)
    return jobs.get_source(source_id)


@router.delete("/sources/{source_id}")
def delete_source(source_id: str):
    try:
        service.delete_source(source_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    return {"deleted": source_id}


@router.post("/sources/{source_id}/scan")
def scan_source(source_id: str):
    try:
        jobs.get_source(source_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    return jobs.enqueue("scan", source_id=source_id)


@router.get("/designs")
def list_designs(source_id: str | None = None, status: str | None = None, q: str | None = None):
    return service.list_designs(source_id, status, q)


@router.get("/designs/{design_id}")
def get_design(design_id: str):
    try:
        return service.design_out(jobs.get_design(design_id))
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.post("/designs/{design_id}/render")
def render_design(design_id: str, body: RenderRequest | None = None):
    try:
        jobs.get_design(design_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    return jobs.enqueue("render", design_id=design_id, force=bool(body and body.force))


@router.get("/designs/{design_id}/files/{name}")
def design_file(design_id: str, name: str):
    try:
        path = service.file_path(design_id, name)
    except KeyError as exc:
        raise _not_found(exc) from exc
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/render-url")
def render_url(body: RenderUrl):
    try:
        return service.render_url(body.url, body.force)
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/jobs")
def list_jobs(limit: int = 50, active: bool = False):
    return service.list_jobs(min(limit, 500), active)


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    try:
        return service.get_job(job_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/settings")
def get_render_settings():
    return asdict(jobs.get_options())


@router.put("/settings")
def put_render_settings(body: dict[str, Any]):
    try:
        opts: RenderOptions = jobs.set_options(body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return asdict(opts)
