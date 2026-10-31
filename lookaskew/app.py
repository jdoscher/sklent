import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db, jobs
from .api import router
from .auth import BearerTokenMiddleware, check_token
from .config import get_settings
from .mcp_server import mcp, mcp_http_app

WEB = Path(__file__).resolve().parent / "web"
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


app = FastAPI(title="look-askew", version=__version__, lifespan=lifespan)
app.include_router(router, prefix="/api")
app.mount("/mcp", mcp_http_app)
app.add_middleware(BearerTokenMiddleware)
app.add_middleware(McpPathRewrite)
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
