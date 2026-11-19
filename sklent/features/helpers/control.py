"""Where this server renders (0.2.1): the renderer setting, the GPU process cap, quiet
hours, and when the host takes a queued render while render helpers are around.

Settings (stored with the render settings, `PUT /api/settings`):
- `render_device`: gpu | software | off. Default: env SK_RENDERER (gpu). `software` runs
  SolidCraft on Mesa lavapipe (the CPU, no GPU at all); `off` never renders here, so
  render jobs wait for helpers (scans, filing and the UI carry on).
- `render_gpu_processes` (1): the most SolidCraft processes on the GPU at once in gpu
  mode. In software mode the cap is SK_RENDER_PROCESSES.
- `render_quiet_hours` ("" = none, e.g. "22:00-07:00", the host's local time: set TZ) and
  `render_quiet_mode`: wait (default: the host takes no render, helpers do) or software.
- `helpers_fallback_minutes` (30; 0 = never): with a helper seen lately, the host takes a
  render only once it has waited this long.
- `helpers_seen_window` (10 min): a helper counts as around if it asked for work this recently.
- `helpers_require_same_solidcraft` (true), `helpers_max_attempts` (2), `helpers_lease_seconds` (300).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from ... import db, jobs
from ...config import get_settings

DEVICES = ("gpu", "software", "off")
QUIET_MODES = ("wait", "software")
_HOURS = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


def _device(v: Any) -> str:
    v = str(v or "").strip().lower()
    if v not in DEVICES:
        raise ValueError(f"render_device must be one of {', '.join(DEVICES)}")
    return v


def env_device() -> str:
    v = (get_settings().renderer or "gpu").strip().lower()
    return v if v in DEVICES else "gpu"


def _int(lo: int, hi: int, name: str):
    def check(v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int | float) or int(v) != v or not lo <= v <= hi:
            raise ValueError(f"{name} must be a whole number from {lo} to {hi}")
        return int(v)
    return check


def parse_hours(v: Any) -> tuple[int, int] | None:
    """'22:00-07:00' -> (1320, 420) minutes after midnight; '' -> None. Raises ValueError."""
    v = str(v or "").strip()
    if not v:
        return None
    m = _HOURS.match(v)
    if not m:
        raise ValueError("render_quiet_hours looks like 22:00-07:00 (24-hour, local time), or empty")
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise ValueError("render_quiet_hours: hours 0-23, minutes 0-59")
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if start == end:
        raise ValueError("render_quiet_hours: start and end are the same")
    return start, end


def _hours(v: Any) -> str:
    span = parse_hours(v)
    if span is None:
        return ""
    return f"{span[0] // 60:02d}:{span[0] % 60:02d}-{span[1] // 60:02d}:{span[1] % 60:02d}"


def _quiet_mode(v: Any) -> str:
    v = str(v or "").strip().lower()
    if v not in QUIET_MODES:
        raise ValueError(f"render_quiet_mode must be one of {', '.join(QUIET_MODES)}")
    return v


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError("expected true or false")
    return v


jobs.register_setting("render_device", env_device, _device)
jobs.register_setting("render_gpu_processes", 1, _int(1, 16, "render_gpu_processes"))
jobs.register_setting("render_quiet_hours", "", _hours)
jobs.register_setting("render_quiet_mode", "wait", _quiet_mode)
jobs.register_setting("helpers_fallback_minutes", 30, _int(0, 10080, "helpers_fallback_minutes"))
jobs.register_setting("helpers_seen_window", 10, _int(1, 1440, "helpers_seen_window"))
jobs.register_setting("helpers_require_same_solidcraft", True, _bool)
jobs.register_setting("helpers_max_attempts", 2, _int(1, 10, "helpers_max_attempts"))
jobs.register_setting("helpers_lease_seconds", 300, _int(60, 3600, "helpers_lease_seconds"))


def local_now() -> datetime:
    """The host's local time (the container's TZ)."""
    return datetime.now().astimezone()


def quiet_active(hours: Any, now: datetime | None = None) -> bool:
    try:
        span = parse_hours(hours)
    except ValueError:
        return False
    if span is None:
        return False
    now = now or local_now()
    t = now.hour * 60 + now.minute
    start, end = span
    return start <= t < end if start < end else (t >= start or t < end)


def helper_seen_since(minutes: int) -> bool:
    cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    try:
        with db.connect() as conn:
            # a helper refused for its SolidCraft version can't take a job: it doesn't count
            return conn.execute("SELECT 1 FROM helpers WHERE last_seen >= ? AND refused IS NULL LIMIT 1",
                                [cutoff]).fetchone() is not None
    except Exception:  # noqa: BLE001 - no table yet
        return False


def host_plan(now: datetime | None = None) -> dict[str, Any]:
    """Whether (and how) this server may take queued renders now:
    {take: all | none | older, before (for older), renderer, processes, device, quiet,
    reason (why it holds back, for the UI), helper_seen}."""
    s = jobs.get_all_settings()
    device = s.get("render_device") or env_device()
    quiet = quiet_active(s.get("render_quiet_hours"), now)
    renderer = "software" if device == "software" else "gpu"
    plan: dict[str, Any] = {"device": device, "quiet": quiet, "quiet_mode": s.get("render_quiet_mode"),
                            "reason": None, "helper_seen": False}
    if device == "off":
        plan.update(take="none", reason="Rendering is off here: helpers only")
    elif quiet and s.get("render_quiet_mode") != "software":
        plan.update(take="none", reason="Quiet hours: helpers only")
    else:
        if quiet:
            renderer = "software"
        seen = helper_seen_since(int(s.get("helpers_seen_window") or 10))
        plan["helper_seen"] = seen
        fallback = int(s.get("helpers_fallback_minutes") or 0)
        if not seen:
            plan["take"] = "all"
        elif fallback <= 0:
            plan.update(take="none", reason="Helpers take every render (fallback off)")
        else:
            before = (datetime.now(UTC) - timedelta(minutes=fallback)).isoformat(timespec="seconds")
            plan.update(take="older", before=before,
                        reason=f"Helpers first: this server takes a render after {fallback} min")
    if quiet and plan["take"] != "none" and s.get("render_quiet_mode") == "software":
        plan["reason"] = "Quiet hours: software rendering here"
    plan["renderer"] = renderer
    plan["processes"] = (int(s.get("render_gpu_processes") or 1) if renderer == "gpu"
                         else get_settings().render_processes)
    return plan


if host_plan not in jobs.HOST_GATE:
    jobs.HOST_GATE.append(host_plan)
