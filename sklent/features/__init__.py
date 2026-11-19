"""Phase-2 feature modules (Sklent 0.2).

Each feature area is one module (or package) in this folder, listed in MODULES with ONE
line. Importing a module registers its pieces through the seams:
- render steps: `sklent.steps.register_step(...)`
- render settings: `sklent.jobs.register_setting(...)`
- tables: a module-level `SCHEMA` string (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT
  EXISTS only), run by `db.init()`
- migrations: a module-level `MIGRATE(conn)` for columns an older database lacks
  (`db.add_columns`), run by `db.init()` after the schemas
- REST: a module-level `router` (fastapi.APIRouter), mounted under /api
- MCP: a module-level `register_mcp(mcp)` that adds tools with `@mcp.tool(...)`
- set storage helpers: `sklent.sets`
"""

import importlib
from types import ModuleType

MODULES: list[str] = [
    "revisions",
    "inputs",
    "views",
    "specs",  # S: spec card, BOM, views sheet, dimensions, contact sheet, assembly steps
    "outputs",  # O: outputs and publishing (F5 F6 F7 F13 F19 F23 F26)
    "helpers",  # 0.2.1: render control (GPU/software/off, quiet hours) and render helpers
]

_loaded: list[ModuleType] = []


def load() -> list[ModuleType]:
    if not _loaded:
        for name in MODULES:
            _loaded.append(importlib.import_module(f"{__name__}.{name}"))
    return _loaded


def schemas() -> list[str]:
    return [m.SCHEMA for m in load() if getattr(m, "SCHEMA", None)]


def migrations() -> list:
    return [m.MIGRATE for m in load() if getattr(m, "MIGRATE", None)]


def routers() -> list:
    return [m.router for m in load() if getattr(m, "router", None) is not None]


def register_mcp(mcp) -> None:
    for m in load():
        hook = getattr(m, "register_mcp", None)
        if hook:
            hook(mcp)
