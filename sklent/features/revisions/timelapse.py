"""Build-history timelapse (F29): the part building itself feature by feature.

A render step (order 80, setting `revisions_timelapse`, off by default). It moves the
timeline marker through the feature history (`timeline.rollback {position: n}`), takes
one still per step from a fixed iso camera that frames the finished part, holds on the
finished part, and encodes the stills to an MP4 and a GIF. Nothing is drawn on the
frames (the truth rule), and they pass the colour guard like every other frame.

Every step is a rebuild, so a big design is skipped above a body or feature budget
(`revisions_timelapse_max_bodies`, `revisions_timelapse_max_features`), with the reason
in `report["timelapse"]`.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from ... import render, steps

STEP_S = 0.4  # each history step shows this long
HOLD_S = 1.5  # then the finished part holds this long
OUT_FPS = 30
SIZE = (1920, 1080)
GIF_FPS = 10


def _features(ctx: steps.StepContext) -> int:
    r = ctx.sc.execute("timeline.rollback", position="end")
    if not isinstance(r, dict) or not isinstance(r.get("features"), int):
        raise RuntimeError(f"timeline.rollback gave no feature count: {str(r)[:200]}")
    return r["features"]


def budget(ctx: steps.StepContext) -> str | None:
    """Why the design is too big for a timelapse, or None."""
    max_bodies = int(ctx.settings.get("revisions_timelapse_max_bodies") or 100)
    if len(ctx.bodies) > max_bodies:
        return (f"skipped: {len(ctx.bodies):,} bodies is over the timelapse budget of "
                f"{max_bodies:,} (revisions_timelapse_max_bodies); every history step is a rebuild")
    return None


def encode(frames: Path, out_mp4: Path, out_gif: Path, gif_width: int) -> None:
    rate = f"1/{STEP_S}"
    hold = f"tpad=stop_mode=clone:stop_duration={HOLD_S}"
    render._ff("-framerate", rate, "-i", str(frames / "f%04d.png"),
               "-vf", f"fps={OUT_FPS},{hold}", *render.X264, "-crf", "18", str(out_mp4))
    graph = (f"fps={GIF_FPS},{hold},scale={gif_width}:-1:flags=lanczos,split[a][b];"
             "[a]palettegen=max_colors=128:stats_mode=diff[p];"
             "[b][p]paletteuse=dither=bayer:bayer_scale=4")
    render._ff("-framerate", rate, "-i", str(frames / "f%04d.png"), "-vf", graph, str(out_gif))


def run(ctx: steps.StepContext) -> None:
    t0 = time.monotonic()
    info: dict[str, Any] = {}
    ctx.report["timelapse"] = info
    why = budget(ctx)
    if why:
        info["skipped"] = why
        return
    n = _features(ctx)
    info["features"] = n
    max_features = int(ctx.settings.get("revisions_timelapse_max_features") or 200)
    if n > max_features:
        info["skipped"] = (f"skipped: {n:,} features is over the timelapse budget of {max_features:,} "
                           "(revisions_timelapse_max_features)")
        return
    if n < 2:
        info["skipped"] = f"skipped: the history has {n} feature{'s' if n != 1 else ''}, nothing to build up"
        return

    w, h = SIZE
    yaw = render.STILL_YAW
    target, dist = render.fit_distance(*ctx.box, w, h, ctx.pitch, [yaw], margin=1.08)
    cam = render.camera(target, yaw, ctx.pitch, dist)
    frames = ctx.out_dir / "_timelapse"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    ctx.restore("shaded")
    try:
        for i, pos in enumerate(range(1, n + 1)):
            ctx.sc.execute("timeline.rollback", position=pos)
            ctx.sc.screenshot(frames / f"f{i:04d}.png", cam, w, h)
            ctx.progress(0.705, f"timelapse {pos}/{n}")
    finally:
        ctx.sc.execute("timeline.rollback", position="end")
        ctx.restore()
    shots = sorted(frames.glob("f*.png"))
    # bodies made part-way through the history may carry the design's own colours
    info["clamped"] = round(render.clamp_all(shots, [], every=1), 5)
    mp4 = f"{ctx.stem}-timelapse-1080p.mp4"
    gif = f"{ctx.stem}-timelapse.gif"
    gif_w = int(getattr(ctx.opts, "gif_width", 640) or 640)
    try:
        encode(frames, ctx.out_dir / mp4, ctx.out_dir / gif, gif_w)
    finally:
        shutil.rmtree(frames, ignore_errors=True)
    ctx.add(mp4, style="shaded", variant="timelapse", width=w, height=h, guard=False)
    ctx.add(gif, style="shaded", variant="timelapse-gif", width=gif_w, height=round(gif_w * h / w), guard=False)
    info.update(frames=len(shots), seconds=round(len(shots) * STEP_S + HOLD_S, 1),
                s=round(time.monotonic() - t0, 1))


def register() -> None:
    steps.register_step("timelapse", run, order=80,
                        when=lambda ctx: ctx.enabled("revisions_timelapse"))

