"""Extra render steps: the seam that phase-2 features plug into.

A step runs inside `render.render_set` while the design is open in SolidCraft. It runs after
the turntable frames and the stills, before the colour guard and the encodes. It can call
any SolidCraft tool through `ctx.sc` and add files to the set with `ctx.add(...)`.

    from sklent import steps

    def exploded(ctx: steps.StepContext) -> None:
        ctx.sc.execute("explode.create", name="sk", scale=1.5)
        ...
        ctx.add("pi-case-exploded.png", style="shaded", variant="exploded", width=2048, height=2048)

    steps.register_step("exploded", exploded, order=20, when=lambda ctx: ctx.enabled("exploded"))

Rules:
- A step that fails must not fail the render. The error is recorded in
  `report["steps"][name]` and the set ships without that step's files. A step that must
  stop the render can raise `StepFatal`.
- Images a step adds with `guard=True` (the default for .png files) go through the colour
  guard like every other still, so nothing leaves in a design's own colours.
- After painting or hiding bodies, or changing the explode state, a section or a
  configuration, a step must put them back with `ctx.restore()`. It re-paints every body
  in the style's look and shows them all. Steps run one after another in `order`, on the
  same SolidCraft process.
- `ctx.settings` holds the full render settings dict (it includes keys phase-2 features
  added). `ctx.enabled(key)` is True when `settings[key]` is truthy.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class StepFatal(RuntimeError):
    """Raised by a step to fail the whole render."""


@dataclass
class Step:
    name: str
    run: Callable[[StepContext], None]
    order: int = 100
    when: Callable[[StepContext], bool] = lambda ctx: True


@dataclass
class StepContext:
    sc: Any  # solidcraft.SolidCraft
    design: Path
    out_dir: Path
    stem: str
    opts: Any  # render.RenderOptions
    info: list[dict]  # inspect_design bodies
    bodies: list[str]
    box: tuple[list[float], list[float]]
    palette: Any  # palette.Palette
    pitch: float  # radians
    report: dict
    settings: dict = field(default_factory=dict)
    progress: Callable[[float, str], None] = lambda f, m: None
    added: list[Any] = field(default_factory=list)  # render.Output
    guard: list[Path] = field(default_factory=list)

    def enabled(self, key: str) -> bool:
        return bool(self.settings.get(key))

    def add(self, file: str, *, style: str = "shaded", variant: str, width: int = 0, height: int = 0,
            guard: bool | None = None) -> None:
        from .render import Output

        self.added.append(Output(file, style, variant, width, height))
        if guard if guard is not None else file.lower().endswith(".png"):
            self.guard.append(self.out_dir / file)

    def restore(self, style: str = "shaded") -> None:
        pal = self.palette
        self.sc.paint(self.bodies, pal.shaded if style == "shaded" else pal.wireframe,
                      1.0 if style == "shaded" else 0.0)


_STEPS: dict[str, Step] = {}


def register_step(name: str, run: Callable[[StepContext], None], *, order: int = 100,
                  when: Callable[[StepContext], bool] | None = None) -> None:
    _STEPS[name] = Step(name, run, order, when or (lambda ctx: True))


def unregister_step(name: str) -> None:
    _STEPS.pop(name, None)


def registered() -> list[Step]:
    return sorted(_STEPS.values(), key=lambda s: (s.order, s.name))


def run_all(ctx: StepContext) -> None:
    results: dict[str, dict] = ctx.report.setdefault("steps", {})
    for step in registered():
        try:
            if not step.when(ctx):
                continue
        except Exception as exc:  # a broken `when` skips the step
            results[step.name] = {"ok": False, "error": f"when: {exc}"}
            continue
        t0 = time.monotonic()
        before, gbefore = len(ctx.added), len(ctx.guard)
        try:
            step.run(ctx)
            results[step.name] = {"ok": True, "s": round(time.monotonic() - t0, 1),
                                  "files": [o.file for o in ctx.added[before:]]}
        except StepFatal:
            raise
        except Exception as exc:
            del ctx.added[before:]
            del ctx.guard[gbefore:]
            results[step.name] = {"ok": False, "s": round(time.monotonic() - t0, 1),
                                  "error": str(exc)[:500],
                                  "trace": traceback.format_exc(limit=3)[-800:]}
            try:
                ctx.restore()
            except Exception:
                pass
