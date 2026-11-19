import logging
import mimetypes
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db, features, jobs
from .api import router
from .auth import BearerTokenMiddleware, check_token
from .config import get_settings
from .mcp_server import mcp, mcp_http_app

WEB = Path(__file__).resolve().parent / "web"
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")  # some hosts map .js to text/plain; modules need JS
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    check_token(settings.token)
    for d in (settings.data_dir, settings.renders_dir, settings.work_dir):
        d.mkdir(parents=True, exist_ok=True)
    db.init()
    stop = threading.Event()
    threads = [threading.Thread(target=jobs.worker_loop, args=(stop,), daemon=True, name="worker"),
               threading.Thread(target=jobs.scheduler_loop, args=(stop,), daemon=True, name="scheduler")]
    for t in threads:
        t.start()
    async with mcp.session_manager.run():
        yield
    stop.set()


class McpPathRewrite:
    """Starlette mounts match /mcp/* but not bare /mcp; clients POST to /mcp."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


class WebFiles(StaticFiles):
    """The web UI is native ES modules with no build step, so module URLs carry no
    version: have browsers revalidate code and styles (a cheap 304) instead of reusing
    a stale copy after an upgrade. Fonts and images keep the default caching."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.endswith((".js", ".css", ".html", ".webmanifest", ".json")):
            response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="sklent", version=__version__, lifespan=lifespan)
app.include_router(router, prefix="/api")
for _r in features.routers():
    app.include_router(_r, prefix="/api")
app.mount("/mcp", mcp_http_app)
app.add_middleware(BearerTokenMiddleware)
app.add_middleware(McpPathRewrite)
app.mount("/static", WebFiles(directory=WEB), name="static")


# Browsers and bookmark services ask for these at the site root regardless of the
# <link> tags, so serve the real icons there instead of the SPA's index.html.
ROOT_ICONS = {
    "favicon.ico": "favicon.ico",
    "favicon.svg": "favicon.svg",
    "apple-touch-icon.png": "apple-touch-icon.png",
    "apple-touch-icon-precomposed.png": "apple-touch-icon.png",
}


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path in ROOT_ICONS:
        return FileResponse(WEB / ROOT_ICONS[path], headers={"Cache-Control": "public, max-age=86400"})
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
