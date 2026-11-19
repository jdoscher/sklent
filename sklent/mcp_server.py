"""MCP interface: streamable-HTTP endpoint at /mcp, same bearer token as the API.

The usual agent flow is one call: `render_url` with a GitHub or Forgejo URL (an
account, repo, folder or single design file). It scans, queues the renders, and
returns job ids; `wait_for_job` blocks until one finishes, `get_render_set` lists
the files (and their Kist item ids), and `view_render` shows the result.
"""

import asyncio
import io
from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage

from . import __version__, jobs, service

mcp = MCPServer(
    name="sklent",
    instructions=(
        "sklent renders SolidCraft CAD designs found in GitHub/Forgejo repositories into "
        "turntable videos (1080p, vertical reel, Discord 640p), GIFs and stills, in shaded and "
        "wireframe styles, always in cool grey or white, and files each set into a Kist folder "
        "(SolidCraft/<owner>/<repo>/<design>). Start with render_url, then wait_for_job, then "
        "get_render_set or view_render."
    ),
    version=__version__,
)


@mcp.tool(description=(
    "Render every SolidCraft design (.sc/.solidcraft) at a GitHub or Forgejo URL: an account "
    "(all its repos), a repo, a folder (tree/…, src/branch/…) or one file (blob/…). Adds the "
    "URL as a source (kept for periodic re-scans), scans it now, and queues renders for new or "
    "changed designs (all of them with force=true). Returns the scan summary and job ids."))
def render_url(url: str, force: bool = False) -> dict[str, Any]:
    return service.render_url(url, force)


@mcp.tool(description="Add a GitHub/Forgejo account, repo, folder or file URL as a source "
                      "without rendering yet (auto_render=false) or with (default).")
def add_source(url: str, auto_render: bool = True, scan: bool = True) -> dict[str, Any]:
    source = jobs.add_source(url, auto_render)
    job = jobs.enqueue("scan", source_id=source["id"]) if scan else None
    return {"source": source, "job": job}


@mcp.tool(description="List sources with their design counts.")
def list_sources() -> list[dict[str, Any]]:
    return service.list_sources()


@mcp.tool(description="Queue a re-scan of a source; changed designs render if auto_render is on.")
def scan_source(source_id: str) -> dict[str, Any]:
    jobs.get_source(source_id)
    return jobs.enqueue("scan", source_id=source_id)


@mcp.tool(description=(
    "List discovered designs. status filters to new|queued|rendering|rendered|failed; query "
    "matches path, repo or owner. Each design lists its rendered files."))
def list_designs(source_id: str | None = None, status: str | None = None,
                 query: str | None = None) -> list[dict[str, Any]]:
    out = service.list_designs(source_id, status, query)
    for d in out:  # keep the listing small; get_render_set has the files
        d["files"] = len(d["files"])
        d.pop("kist_items", None)
    return out


@mcp.tool(description="Queue a render of one design (force=true re-renders an unchanged one).")
def render_design(design_id: str, force: bool = False) -> dict[str, Any]:
    jobs.get_design(design_id)
    return jobs.enqueue("render", design_id=design_id, force=force)


@mcp.tool(description="A job's status, progress (0-1), message and error.")
def job_status(job_id: int) -> dict[str, Any]:
    return service.get_job(job_id)


@mcp.tool(description="Recent jobs, newest first; active=true for only queued and running ones.")
def list_jobs(limit: int = 20, active: bool = False) -> list[dict[str, Any]]:
    return service.list_jobs(min(limit, 200), active)


@mcp.tool(description=(
    "Cancel a queued or running job. A queued job is dropped; a running render has its "
    "SolidCraft processes killed. The job ends as cancelled and its design goes back to the "
    "status it had. Fails for a job that already finished."))
def cancel_job(job_id: int) -> dict[str, Any]:
    return jobs.cancel(job_id)


@mcp.tool(description=(
    "Wait until a job is done, failed or cancelled (up to timeout_s, max 600) and return it. A render of "
    "a simple part takes under a minute; large assemblies several minutes."))
async def wait_for_job(job_id: int, timeout_s: int = 300) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + min(max(timeout_s, 1), 600)
    while True:
        job = service.get_job(job_id)
        if job["status"] in ("done", "failed", "cancelled") or asyncio.get_running_loop().time() > deadline:
            return job
        await asyncio.sleep(2)


@mcp.tool(description=(
    "A design's render set: every file (style shaded|wireframe; variant 1080p|reel|discord|gif|"
    "social|hires; size; download URL path on this server, same token) and the Kist folder and "
    "item ids it was filed under."))
def get_render_set(design_id: str) -> dict[str, Any]:
    return service.design_out(jobs.get_design(design_id))


@mcp.tool(description="See a rendered still: style shaded or wireframe; size 256-2048 (default 1024).")
def view_render(design_id: str, style: str = "shaded", size: int = 1024) -> Image:
    path = service.file_path(design_id, next(
        (f["file"] for f in jobs.get_design(design_id)["files"]
         if f["style"] == style and f["variant"] == "social"), "") or "-")
    size = min(max(size, 256), 2048)
    with PILImage.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, "PNG")
    return Image(data=buf.getvalue(), format="png")


@mcp.tool(description="Current render settings: palette (cool-grey|white), seconds, fps, pitch, "
                      "still sizes, GIF size, styles.")
def get_render_settings() -> dict[str, Any]:
    return asdict(jobs.get_options())


@mcp.tool(description=(
    "Change render settings for future renders. palette is cool-grey or white (parts are never "
    "rendered in other colours); seconds 2-30; fps 24/25/30/60; pitch_deg 0-80; hires_width/"
    "hires_height and social_size 256-8192; gif_width 160-1280; styles some of shaded, wireframe."))
def set_render_settings(palette: str | None = None, seconds: float | None = None,
                        fps: int | None = None, pitch_deg: float | None = None,
                        hires_width: int | None = None, hires_height: int | None = None,
                        social_size: int | None = None, gif_width: int | None = None,
                        styles: list[str] | None = None) -> dict[str, Any]:
    changes = {k: v for k, v in locals().items() if v is not None}
    return asdict(jobs.set_options(changes))


def _register_features() -> None:
    from . import features
    features.register_mcp(mcp)


# Every tool is classified here. Read-only tools get ToolAnnotations(readOnlyHint=True), the
# mark auth.viewer_may_call accepts for viewer tokens; every other tool writes, renders,
# builds files or reaches out (Kist, the forge) and answers 403 to a viewer. A new tool
# must be added to one of the two sets (tests/test_integration.py checks it).
READ_ONLY_TOOLS = frozenset({
    # core
    "list_sources", "list_designs", "job_status", "list_jobs", "wait_for_job", "get_render_set",
    "view_render", "get_render_settings",
    # revisions (R)
    "list_sets", "compare_sets", "view_compare",
    # inputs (P)
    "list_class_submissions", "review_comment", "get_design_inputs",
    # views (V)
    "get_views", "view_output",
    # specs (S)
    "get_design_spec", "get_bom", "view_sheet",
    # outputs (O)
    "get_outputs", "listing_readiness", "listing_text", "list_photos",
})
WRITE_TOOLS = frozenset({
    "render_url", "add_source", "scan_source", "render_design", "cancel_job", "set_render_settings",
    "add_class_source", "post_review_comment",
    "quick_check", "render_outputs", "set_highlight", "set_views_settings",
    "make_contact_sheet",
    "make_output_preset", "build_file_pack", "export_project_page", "build_listing_pack",
    "set_listing_details", "attach_photo", "make_review_board", "create_share_link", "revoke_share_link",
})


def _annotate() -> None:
    from mcp.types import ToolAnnotations

    for name in READ_ONLY_TOOLS | WRITE_TOOLS:
        tool = mcp._tool_manager.get_tool(name)
        if tool is None:
            continue
        old = tool.annotations
        tool.annotations = ToolAnnotations(
            title=getattr(old, "title", None), readOnlyHint=name in READ_ONLY_TOOLS,
            destructiveHint=getattr(old, "destructiveHint", None) if name in WRITE_TOOLS else None)


_register_features()
_annotate()


mcp_http_app = mcp.streamable_http_app(
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
)
