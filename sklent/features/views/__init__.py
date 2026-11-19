"""Views and render modes (Sklent 0.2, area V).

F17 quick check and per-render outputs, F24 shot presets and edit-ready masters, F4
exploded view, F9 section cut, F10 configuration lineup, F20 "my part" highlight, F22
motion-study clips, F15 transparent stills and studio hero, F16 plate view and bed-fit
badge.

The turntable-side pieces (the quick-check still, `RenderOptions.outputs`, shot presets,
masters, the highlight turntable) live in `sklent/render.py`; the rest are render steps
(`steps.py`). This package registers the settings, the steps, the REST routes
(`/api/designs/{id}/views…`, `/api/views/beds`) and the MCP tools, and holds two small
tables: a design's pending render request and its highlight list.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from ... import db, jobs
from ...render import CORE_OUTPUTS, RenderOptions
from . import beds as bedlib
from . import steps as _steps

SCHEMA = """
CREATE TABLE IF NOT EXISTS views_requests (
    design_id TEXT PRIMARY KEY,
    request TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS views_designs (
    design_id TEXT PRIMARY KEY,
    highlight TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);
"""


# ---------------------------------------------------------------- settings

def _bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _number(lo: float, hi: float, integer: bool = False):
    def check(v: Any):
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"must be a number from {lo:g} to {hi:g}") from None
        if not lo <= x <= hi:
            raise ValueError(f"must be from {lo:g} to {hi:g}")
        return int(x) if integer else x
    return check


def _master_seconds(v: Any) -> float:
    x = _number(0, 60)(v)
    if 0 < x < 2:
        raise ValueError("views_master_seconds must be 0 (the turntable's length) or 2 to 60")
    return x


def _text(v: Any) -> str:
    return str(v or "").strip()[:200]


SETTINGS: dict[str, tuple[Any, Any, str]] = {
    # key: (default, validator, what it does)
    "views_shot_half_orbit": (False, _bool, "half orbit that eases onto the iso angle"),
    "views_shot_push_in": (False, _bool, "slow push-in on the iso angle"),
    "views_shot_top_to_iso": (False, _bool, "from straight down to the iso angle"),
    "views_shot_low_angle": (False, _bool, "low hero angle, a 60° pass"),
    "views_shot_seconds": (6.0, _number(2, 12), "length of each shot preset"),
    "views_master_4k": (False, _bool, "3840×2160 H.264 turntable master"),
    "views_master_zip": (False, _bool, "3840×2160 PNG sequence, zipped"),
    "views_master_prores": (False, _bool, "3840×2160 ProRes 422 HQ master"),
    "views_master_seconds": (0.0, _master_seconds, "master length, up to 60 s (0 = the turntable's)"),
    "views_exploded": (False, _bool, "exploded still and explode animation (2+ components)"),
    "views_explode_scale": (1.0, _number(0.2, 3), "automatic explode distance"),
    "views_section": (False, _bool, "section-cut stills through the centre"),
    "views_configs": (True, _bool, "one still per configuration plus a lineup"),
    "views_configs_max": (8, _number(2, 24, integer=True), "most configurations rendered"),
    "views_motion": (True, _bool, "a clip per motion study"),
    "views_motion_max": (6, _number(1, 24, integer=True), "most motion studies rendered"),
    "views_transparent": (False, _bool, "transparent PNG stills"),
    "views_hero": (False, _bool, "path-traced studio hero (CPU, slow on big designs)"),
    "views_hero_timeout": (900, _number(30, 3600, integer=True), "longest the hero may take"),
    "views_plate": (False, _bool, "plate view: parts laid flat, top-down ortho"),
    "views_bedfit": (True, _bool, "bed-fit badge on tiles"),
    "views_bed": (bedlib.DEFAULT_BED, _text, "the bed the badge checks against"),
    "views_beds": (bedlib.DEFAULT_BEDS, bedlib.clean_beds, "printer beds, 'Name XxYxZ; …' in mm"),
}

for _key, (_default, _check, _) in SETTINGS.items():
    jobs.register_setting(_key, _default, _check)
    _steps.DEFAULTS[_key] = _default
_steps.register()


def defaults() -> dict[str, Any]:
    return {k: d for k, (d, _, _) in SETTINGS.items()}


# ---------------------------------------------------------------- per-render requests (F17)

def clean_request(outputs: list[str] | None = None, preview_only: bool = False,
                  settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a per-render choice: core `outputs` (empty or preview_only: the quick
    check only) and feature-setting overrides (any registered setting key)."""
    req: dict[str, Any] = {}
    if preview_only:
        req["outputs"] = []
    elif outputs is not None:
        req["outputs"] = RenderOptions(outputs=list(outputs)).validate().outputs
    over = {}
    for k, v in (settings or {}).items():
        if k not in jobs._EXTRA:
            raise ValueError(f"{k} is not a feature setting")
        check = jobs._EXTRA[k][1]
        over[k] = check(v) if check else v
    if over:
        req["settings"] = over
    return req


def save_request(design_id: str, req: dict[str, Any]) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO views_requests (design_id, request, created_at) VALUES (?,?,?) "
                     "ON CONFLICT(design_id) DO UPDATE SET request = excluded.request, "
                     "created_at = excluded.created_at", [design_id, json.dumps(req), db.now()])


def pending_request(design_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        r = conn.execute("SELECT request FROM views_requests WHERE design_id = ?", [design_id]).fetchone()
    return json.loads(r["request"]) if r else None


def take_request(design_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        r = conn.execute("DELETE FROM views_requests WHERE design_id = ? RETURNING request",
                         [design_id]).fetchone()
    return json.loads(r["request"]) if r else None


def drop_request(design_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM views_requests WHERE design_id = ?", [design_id])


# ---------------------------------------------------------------- highlight (F20)

def get_highlight(design_id: str) -> list[str]:
    with db.connect() as conn:
        r = conn.execute("SELECT highlight FROM views_designs WHERE design_id = ?", [design_id]).fetchone()
    return json.loads(r["highlight"]) if r else []


def set_highlight(design_id: str, names: list[str]) -> list[str]:
    clean = []
    for n in names or []:
        n = str(n).strip()
        if n and n not in clean:
            clean.append(n[:200])
    if len(clean) > 200:
        raise ValueError("at most 200 highlight names")
    with db.connect() as conn:
        conn.execute("INSERT INTO views_designs (design_id, highlight, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(design_id) DO UPDATE SET highlight = excluded.highlight, "
                     "updated_at = excluded.updated_at", [design_id, json.dumps(clean), db.now()])
    return clean


def repo_highlight(design_id: str) -> list[str]:
    """`highlight:` from the repo's .sklent.yaml (P's sklent.repo_config), if present."""
    try:
        from ... import repo_config  # type: ignore[attr-defined]
    except ImportError:
        return []
    try:
        cfg = repo_config.get(design_id) or {}
    except Exception:  # noqa: BLE001 - a broken config never stops a render
        return []
    hl = cfg.get("highlight") or []
    if isinstance(hl, str):
        hl = [hl]
    return [str(x) for x in hl if str(x).strip()]


def highlight_for(design_id: str) -> tuple[list[str], str | None]:
    """The design's highlight list and where it came from: the UI's per-design choice
    wins over .sklent.yaml."""
    mine = get_highlight(design_id)
    if mine:
        return mine, "design"
    repo = repo_highlight(design_id)
    return (repo, ".sklent.yaml") if repo else ([], None)


# ---------------------------------------------------------------- the hook jobs._render calls

def render_overrides(design_id: str, opts: RenderOptions, settings: dict[str, Any]
                     ) -> tuple[RenderOptions, dict[str, Any]]:
    """Apply a design's pending render request (outputs, setting overrides; consumed) and
    its highlight list to the options and settings of the render about to run."""
    settings = dict(settings)
    req = take_request(design_id) or {}
    if "outputs" in req:
        opts = dataclasses.replace(opts, outputs=list(req["outputs"])).validate()
        settings["outputs"] = list(opts.outputs)
    settings.update(req.get("settings") or {})
    names, _ = highlight_for(design_id)
    if names:
        settings["views_highlight_names"] = names
    return opts, settings


from .api import register_mcp, router  # noqa: E402  (routes use the helpers above)

__all__ = ["SCHEMA", "router", "register_mcp", "render_overrides", "CORE_OUTPUTS", "defaults"]
