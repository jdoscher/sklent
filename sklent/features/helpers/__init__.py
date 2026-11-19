"""Render control and render helpers (Sklent 0.2.1).

- `control`: the Rendering settings (renderer gpu/software/off, GPU process cap, quiet
  hours, helper fallback) and the host's claim gate (`jobs.HOST_GATE`).
- `server`: the helper protocol (claim, inputs, progress, result, fail, leases) and the
  helper registry.
- `client`: `sklent helper`, the loop a helper machine runs (no database, no data dir).

REST (admin token unless noted): `GET /api/helpers` (the registry), `GET /api/render-state`
(admin and viewers: what the host does now, for the UI), and the helper protocol under
`/api/helpers/claim` and `/api/helpers/jobs/{id}/...` (helper tokens and the admin token).
MCP: `list_helpers` (read-only, admin).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ...config import get_settings
from . import control, server

SCHEMA = server.SCHEMA

router = APIRouter()


def _who(request: Request) -> tuple[str | None, str | None]:
    st = request.scope.get("state") or {}
    return st.get("sk_role"), st.get("sk_token_id")


class Claim(BaseModel):
    name: str
    solidcraft_version: str | None = None
    renderer: str | None = None
    gpu: str | None = None
    mem_gb: float | None = None
    max_bodies: int | None = None


class Progress(BaseModel):
    fraction: float = 0
    message: str = ""


class Fail(BaseModel):
    error: str = ""
    retry: bool = False


@router.get("/helpers")
def get_helpers():
    """Every helper that ever asked for work: last seen, version, renderer, current job, done count."""
    return server.list_helpers()


@router.get("/render-state")
def render_state():
    """What this server does with renders now: device, quiet hours, whether it holds back
    for helpers (`reason`, e.g. "Quiet hours: helpers only"), helpers active."""
    plan = control.host_plan()
    helpers = server.list_helpers()
    return {
        "device": plan["device"], "renderer": plan["renderer"], "processes": plan["processes"],
        "quiet": plan["quiet"], "quiet_mode": plan["quiet_mode"], "take": plan["take"],
        "reason": plan["reason"], "helpers_active": sum(1 for h in helpers if h["active"]),
        "solidcraft_version": server.host_version(),
    }


@router.post("/helpers/claim")
def claim(body: Claim, request: Request):
    _, token_id = _who(request)
    try:
        out = server.claim(body.name, token_id, body.model_dump())
    except server.Refused as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if out is None:
        return Response(status_code=204)
    return out


def _job_call(fn, *args):
    try:
        return fn(*args)
    except server.NotYours as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/helpers/jobs/{job_id}/inputs.tar")
def job_inputs(job_id: int, name: str, request: Request):
    _, token_id = _who(request)
    path = _job_call(server.inputs_tar, job_id, name, token_id)
    return FileResponse(path, media_type="application/x-tar", filename=f"job-{job_id}-inputs.tar",
                        background=BackgroundTask(path.unlink, missing_ok=True))


@router.get("/helpers/jobs/{job_id}/repo-file")
def job_repo_file(job_id: int, name: str, path: str, request: Request):
    _, token_id = _who(request)
    data = _job_call(server.repo_file, job_id, name, token_id, path)
    if data is None:
        raise HTTPException(404, f"no {path} in the design's repo")
    return Response(data, media_type="application/octet-stream")


@router.post("/helpers/jobs/{job_id}/progress")
def job_progress(job_id: int, name: str, body: Progress, request: Request):
    _, token_id = _who(request)
    return server.progress(job_id, name, token_id, body.fraction, body.message)


@router.post("/helpers/jobs/{job_id}/fail")
def job_fail(job_id: int, name: str, body: Fail, request: Request):
    _, token_id = _who(request)
    return server.fail(job_id, name, token_id, body.error, body.retry)


@router.post("/helpers/jobs/{job_id}/result")
async def job_result(job_id: int, name: str, request: Request):
    """The finished stage folder as a tar (first member `.sklent-manifest.json`)."""
    _, token_id = _who(request)
    try:
        await run_in_threadpool(server.own, job_id, name, token_id)
    except server.NotYours as exc:
        raise HTTPException(409, str(exc)) from exc
    work = get_settings().work_dir
    work.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f"result-{job_id}-", suffix=".tar", dir=work)
    path = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                if chunk:
                    await asyncio.to_thread(fh.write, chunk)
        try:
            return await run_in_threadpool(server.accept_result, job_id, name, token_id, path)
        except server.BadUpload as exc:
            raise HTTPException(422, str(exc)) from exc
        except server.NotYours as exc:
            raise HTTPException(409, str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)


def register_mcp(mcp) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True), description=(
        "Render helpers (other machines that render for this server): name, last seen, active (seen in the "
        "last helpers_seen_window minutes), SolidCraft version, renderer, GPU, memory, current job, jobs "
        "done and failed, last error, and why a claim was refused. Plus render_state: whether this server "
        "renders now (device, quiet hours) or leaves renders to helpers."))
    def list_helpers() -> dict[str, Any]:
        return {"helpers": server.list_helpers(), "render_state": render_state()}
