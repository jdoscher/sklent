"""Phase-2 feature modules (Sklent 0.2).

Each feature area is one module (or package) in this folder, listed in MODULES with ONE
line. Importing a module registers its pieces through the seams:
- render steps: `sklent.steps.register_step(...)`
- render settings: `sklent.jobs.register_setting(...)`
- tables: a module-level `SCHEMA` string (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT
  EXISTS only), run by `db.init()`
- REST: a module-level `router` (fastapi.APIRouter), mounted under /api
- MCP: a module-level `register_mcp(mcp)` that adds tools with `@mcp.tool(...)`
- set storage helpers: `sklent.sets`
"""

import importlib
from types import ModuleType

MODULES: list[str] = [
    "specs",  # S: spec card, BOM, views sheet, dimensions, contact sheet, assembly steps
]

_loaded: list[ModuleType] = []


def load() -> list[ModuleType]:
    if not _loaded:
        for name in MODULES:
            _loaded.append(importlib.import_module(f"{__name__}.{name}"))
    return _loaded


def schemas() -> list[str]:
    return [m.SCHEMA for m in load() if getattr(m, "SCHEMA", None)]


def routers() -> list:
    return [m.router for m in load() if getattr(m, "router", None) is not None]


def register_mcp(mcp) -> None:
    for m in load():
        hook = getattr(m, "register_mcp", None)
        if hook:
            hook(mcp)
