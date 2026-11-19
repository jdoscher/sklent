"""The views area's render steps (order 10–49). Each one runs on the open SolidCraft process
after the turntable frames and stills, puts the design back the way it found it, and
records what it did (or why it skipped) in `report["views"][<step>]`.

| step | order | setting (default) | variants |
|---|---|---|---|
| facts | 10 | always | (views.json: per-part sizes, configurations, studies) |
| exploded | 12 | views_exploded (off) | exploded, explode-anim |
| section | 20 | views_section (off) | section |
| motion | 25 | views_motion (on) | motion-<study> |
| configs | 30 | views_configs (on) | config-lineup, config-<n> |
| transparent | 40 | views_transparent (off) | transparent |
| hero | 42 | views_hero (off) | hero |
| plate | 48 | views_plate (off) | plate |
"""

from __future__ import annotations

import math
import re
import shutil
import time
from pathlib import Path

from ... import render as R
from ...sets import write_json
from ...solidcraft import SolidCraft, SolidCraftError
from ...steps import StepContext, register_step
from . import beds as bedlib
from . import sheets

DEFAULTS: dict = {}  # filled by the package from its registered settings
PLATE_MAX_PARTS = 60
STILL = (2048, 2048)


def setting(ctx: StepContext, key: str):
    return ctx.settings.get(key, DEFAULTS.get(key))


def note(ctx: StepContext, step: str, **data) -> None:
    ctx.report.setdefault("views", {}).setdefault(step, {}).update(data)


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-").lower() or "x"


def _try(sc, command: str, **params):
    try:
        return sc.execute(command, **params) or {}
    except SolidCraftError:
        return {}


# ---------------------------------------------------------------- render jobs

class TooBig(RuntimeError):
    """A render job refused the scene (the triangle budget, see-through bodies)."""


def render_job(sc, path: Path, width: int, height: int, cam: dict, *, method: str = "raster",
               transparent: bool = True, budget: str | None = None, background=(255, 255, 255),
               timeout: float = 900) -> dict:
    """`render.start` → poll `render.status` → `render.export`: a still from SolidCraft's
    CPU renderer, straight-alpha RGBA when `transparent`. Raises TooBig when the scene is
    refused (raster caps scenes at 262,144 triangles; raytrace refuses see-through bodies)."""
    job: dict = {"method": method, "transparent_background": transparent}
    if budget:
        job["options"] = {"budget": budget}
    try:
        r = sc.execute("render.start", settings={"width": width, "height": height, "camera": cam,
                                                 "background": list(background), "job": job})
    except SolidCraftError as exc:
        raise TooBig(str(exc).split(": ", 1)[-1][:300]) from exc
    if r.get("error"):
        raise TooBig(str(r["error"])[:300])
    t0 = time.monotonic()
    while True:
        st = sc.execute("render.status", job=r["job"])
        phase = (st.get("progress") or {}).get("phase")
        if phase == "completed":
            break
        if phase in ("failed", "cancelled") or st.get("error"):
            raise TooBig(str(st.get("error") or phase)[:300])
        if time.monotonic() - t0 > timeout:
            _try(sc, "render.cancel", job=r["job"])
            raise TooBig(f"the render job took over {timeout:.0f} s")
        time.sleep(0.2)
    sc.execute("render.export", job=r["job"], path=str(path), overwrite=True)
    return {"s": round(time.monotonic() - t0, 1)}


def _frames_to_clips(ctx: StepContext, folder: Path, base: str, variant: str, fps: int,
                     width: int, height: int) -> list[str]:
    """Guard and encode a SolidCraft frame folder (frame-0001.png …) into MP4 + GIF."""
    frames = sorted(folder.glob("frame-*.png"))
    if not frames:
        raise SolidCraftError(f"no frames in {folder.name}")
    clamped = R.clamp_all(frames, [])
    if clamped:
        note(ctx, variant, clamped=round(clamped, 5))
    mp4, gif = f"{base}.mp4", f"{base}.gif"
    R.encode(folder, ctx.out_dir / mp4, fps, crf=18, pattern="frame-%04d.png", start=1)
    R.encode_gif(folder, ctx.out_dir / gif, fps, min(fps, ctx.opts.gif_fps), ctx.opts.gif_width,
                 pattern="frame-%04d.png", start=1)
    ctx.add(mp4, variant=variant, width=width, height=height, guard=False)
    ctx.add(gif, variant=variant, width=ctx.opts.gif_width,
            height=round(ctx.opts.gif_width * height / width), guard=False)
    return [mp4, gif]


# ---------------------------------------------------------------- facts (always)

def facts(ctx: StepContext) -> None:
    """views.json in the set: per-part sizes (the bed-fit badge), and which views the
    design has material for. Cheap: no pictures."""
    t = _try(ctx.sc, "config.table")
    m = _try(ctx.sc, "motion.list")
    e = _try(ctx.sc, "explode.list")
    data = {
        "parts": bedlib.part_sizes(ctx.info),
        "configurations": [r.get("name") for r in t.get("rows") or []],
        "active_configuration": t.get("active"),
        "motion_studies": [s.get("name") for s in m.get("studies") or []],
        "explode_views": len(e.get("views") or []),
        "bodies": [b["name"] for b in ctx.info],
    }
    write_json(ctx.out_dir, "views.json", data)


# ---------------------------------------------------------------- F4 exploded

def _grown(box, moves: list[list[float]]) -> tuple[list[float], list[float]]:
    """The assembled box grown by every move: a box that holds the exploded parts (each
    part moves by its translate, so it stays inside box + translate)."""
    lo, hi = list(box[0]), list(box[1])
    for t in moves:
        for i in range(3):
            lo[i] = min(lo[i], box[0][i] + t[i])
            hi[i] = max(hi[i], box[1][i] + t[i])
    return lo, hi


def exploded(ctx: StepContext) -> None:
    sc = ctx.sc
    saved = (_try(sc, "explode.list").get("views") or [])
    if saved:
        v = saved[0]
        view = v.get("name") or v.get("id")
        moves = [m[1] for m in v.get("moves") or [] if isinstance(m, list) and len(m) == 2]
        note(ctx, "exploded", view=view, source="saved")
    else:
        scale = float(setting(ctx, "views_explode_scale") or 1.0)
        try:
            r = sc.execute("explode.create", name="Sklent exploded", scale=scale)
        except SolidCraftError as exc:
            note(ctx, "exploded", skipped=str(exc).split("available right now: ")[-1][:300])
            return
        view = r.get("name") or r.get("view")
        moves = [m["translate"] for m in r.get("moves") or []]
        note(ctx, "exploded", view=view, source="automatic", scale=scale)
    box = _grown(ctx.box, moves)
    w, h = ctx.opts.hires_width, ctx.opts.hires_height
    try:
        sc.execute("explode.show", view=view)
        ctx.restore()
        target, dist = R.fit_distance(*box, w, h, ctx.pitch, [R.STILL_YAW], margin=1.06)
        still = f"{ctx.stem}-exploded-{w}x{h}.png"
        sc.screenshot(ctx.out_dir / still, R.camera(target, R.STILL_YAW, ctx.pitch, dist), w, h)
        ctx.add(still, variant="exploded", width=w, height=h)
        # the animation: assembled → exploded → assembled
        seconds = 4.0
        samples = int(seconds * ctx.opts.fps) | 1  # odd: exploded on the middle frame
        aw, ah = 1920, 1080
        target, dist = R.fit_distance(*box, aw, ah, ctx.pitch, [R.STILL_YAW], margin=1.08)
        folder = ctx.out_dir / "_explode"
        shutil.rmtree(folder, ignore_errors=True)
        ctx.progress(0.71, "exploded view animation")
        sc.execute("motion.export_animation", view=view, back=True, path=str(folder), samples=samples,
                   width=aw, height=ah, grid=False, axes=False, fps=min(50, ctx.opts.fps),
                   camera=R.camera(target, R.STILL_YAW, ctx.pitch, dist))
        _frames_to_clips(ctx, folder, f"{ctx.stem}-explode-1080p", "explode-anim", ctx.opts.fps, aw, ah)
        shutil.rmtree(folder, ignore_errors=True)
    finally:
        _try(sc, "explode.show")


# ---------------------------------------------------------------- F9 section

def section_plane(box) -> dict:
    """The cut for a design: through the centre, containing its longest axis and the
    vertical (or, for a tall part, its longer horizontal axis). Returns the inspect.section
    params and the cameras' yaws (perspective from the kept side, ortho face-on)."""
    lo, hi = box
    size = [hi[i] - lo[i] for i in range(3)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    longest = max(range(3), key=lambda i: size[i])
    along_x = longest == 0 or (longest == 2 and size[0] >= size[1])
    if along_x:  # plane XZ at the centre's y; hide the front half (-Y) and look from the front
        return {"plane": "XZ", "at": f"{c[1]:.4f}", "flip": True, "axis": "Y",
                "yaw": R.STILL_YAW, "ortho_yaw": 0.0, "label": f"XZ at y = {c[1]:.1f} mm"}
    # plane YZ at the centre's x; it hides +X, so look from the +X side
    return {"plane": "YZ", "at": f"{c[0]:.4f}", "flip": False, "axis": "X",
            "yaw": R.yaw_towards(1.0, -0.6), "ortho_yaw": R.yaw_towards(1.0, 0.0),
            "label": f"YZ at x = {c[0]:.1f} mm"}


def section(ctx: StepContext) -> None:
    sc = ctx.sc
    cut = section_plane(ctx.box)
    params = {"plane": cut["plane"], "at": cut["at"], "hatch": True}
    if cut["flip"]:
        params["flip"] = True
    try:
        sc.execute("inspect.section", **params)
        w, h = ctx.opts.hires_width, ctx.opts.hires_height
        target, dist = R.fit_distance(*ctx.box, w, h, ctx.pitch, [cut["yaw"]], margin=1.04)
        name = f"{ctx.stem}-section-{w}x{h}.png"
        sc.screenshot(ctx.out_dir / name, R.camera(target, cut["yaw"], ctx.pitch, dist), w, h)
        ctx.add(name, variant="section", width=w, height=h)
        cam = R.ortho_fit(*ctx.box, w, h, cut["ortho_yaw"], 0.0, margin=1.1)
        name = f"{ctx.stem}-section-ortho-{w}x{h}.png"
        sc.screenshot(ctx.out_dir / name, cam, w, h)
        ctx.add(name, variant="section", width=w, height=h)
        note(ctx, "section", plane=cut["label"], ortho_px_per_mm=round(R.ortho_scale(cam, h), 4))
    finally:
        _try(sc, "inspect.section", clear=True)


# ---------------------------------------------------------------- F22 motion studies

def motion(ctx: StepContext) -> None:
    sc = ctx.sc
    studies = (_try(sc, "motion.list").get("studies") or [])[: int(setting(ctx, "views_motion_max") or 6)]
    if not studies:
        note(ctx, "motion", skipped="the design has no motion studies")
        return
    aw, ah = 1920, 1080
    target, dist = R.fit_distance(*ctx.box, aw, ah, ctx.pitch, [R.STILL_YAW], margin=1.25)
    done = []
    for st in studies:
        name = st.get("name") or f"study {st.get('id')}"
        folder = ctx.out_dir / f"_motion-{slug(name)}"
        shutil.rmtree(folder, ignore_errors=True)
        ctx.progress(0.712, f"motion study {name}")
        r = sc.execute("motion.export_animation", study=st.get("id", name), path=str(folder),
                       width=aw, height=ah, grid=False, axes=False,
                       camera=R.camera(target, R.STILL_YAW, ctx.pitch, dist))
        _frames_to_clips(ctx, folder, f"{ctx.stem}-motion-{slug(name)}-1080p", f"motion-{slug(name)}",
                         int(r.get("fps") or 20), aw, ah)
        shutil.rmtree(folder, ignore_errors=True)
        done.append({"study": name, "frames": r.get("frames")})
    note(ctx, "motion", studies=done)


# ---------------------------------------------------------------- F10 configurations

def _values_label(values: dict) -> str:
    out = []
    for k, v in (values or {}).items():
        if k.startswith("suppress:"):
            if str(v).lower() == "true":
                out.append("−" + k.split(":", 1)[1])
        else:
            out.append(f"{k.split(':', 1)[-1]}={v}")
    return " ".join(out)


def configs(ctx: StepContext) -> None:
    sc = ctx.sc
    table = _try(sc, "config.table")
    rows = table.get("rows") or []
    if len(rows) < 2:
        note(ctx, "configs", skipped="the design has no configurations")
        return
    cap = int(setting(ctx, "views_configs_max") or 8)
    active = table.get("active") or rows[0].get("name")
    rows = rows[:cap]
    boxes = []
    try:
        for row in rows:  # pass 1: every row's extent, so all share one camera (one scale)
            sc.execute("config.activate", row=row.get("id", row.get("name")))
            boxes.append(SolidCraft.bounds(R.world_bodies(sc)))
        known = [b for b in boxes if b]
        lo = [min(b[0][i] for b in known) for i in range(3)]
        hi = [max(b[1][i] for b in known) for i in range(3)]
        w, h = STILL
        target, dist = R.fit_distance(lo, hi, w, h, ctx.pitch, [R.STILL_YAW], margin=1.06)
        cam = R.camera(target, R.STILL_YAW, ctx.pitch, dist)
        cells = []
        for i, row in enumerate(rows, 1):  # pass 2: one still per row
            ctx.progress(0.714, f"configuration {row.get('name')}")
            sc.execute("config.activate", row=row.get("id", row.get("name")))
            names = [b["name"] for b in sc.bodies()]
            sc.paint(names, ctx.palette.shaded, 1.0)
            name = f"{ctx.stem}-config-{i}-{slug(row.get('name'))}.png"
            sc.screenshot(ctx.out_dir / name, cam, w, h)
            ctx.add(name, variant=f"config-{i}", width=w, height=h)
            cells.append((ctx.out_dir / name, str(row.get("name")), _values_label(row.get("values"))))
        R.clamp_all([], [c[0] for c in cells])  # guard the cells before they go on the lineup
        name = f"{ctx.stem}-config-lineup.png"
        lw, lh = sheets.lineup(cells, ctx.out_dir / name, title=f"{ctx.stem} · configurations · one scale")
        ctx.add(name, variant="config-lineup", width=lw, height=lh)
        note(ctx, "configs", rows=[r.get("name") for r in rows], active=active,
             capped=len(table.get("rows") or []) > cap)
    finally:
        _try(sc, "config.activate", row=active)
        ctx.restore()


# ---------------------------------------------------------------- F15 transparent and hero

def transparent(ctx: StepContext) -> None:
    sizes = [(ctx.opts.social_size, ctx.opts.social_size), (ctx.opts.hires_width, ctx.opts.hires_height)]
    ctx.restore()
    method, how = "raster", None
    for w, h in sizes:
        target, dist = R.fit_distance(*ctx.box, w, h, ctx.pitch, [R.STILL_YAW], margin=1.04)
        cam = R.camera(target, R.STILL_YAW, ctx.pitch, dist)
        name = f"{ctx.stem}-transparent-{w}x{h}.png"
        try:
            r = render_job(ctx.sc, ctx.out_dir / name, w, h, cam, method=method)
        except TooBig as exc:
            if method != "raster":
                raise
            # raster caps scenes at 262,144 triangles; the studio raytrace budget takes 2 M
            how = f"raster refused ({exc}); used cpu_raytrace (studio)"
            method = "cpu_raytrace"
            try:
                r = render_job(ctx.sc, ctx.out_dir / name, w, h, cam, method=method, budget="studio")
            except TooBig as exc2:
                note(ctx, "transparent", skipped=f"the scene is too big for the CPU renderer: {exc2}")
                return
        ctx.add(name, variant="transparent", width=w, height=h)
        note(ctx, "transparent", method=method, **({"note": how} if how else {}),
             **{f"s_{w}x{h}": r["s"]})


def hero(ctx: StepContext) -> None:
    w, h = ctx.opts.hires_width, ctx.opts.hires_height
    ctx.restore()
    target, dist = R.fit_distance(*ctx.box, w, h, ctx.pitch, [R.STILL_YAW], margin=1.06)
    name = f"{ctx.stem}-hero-{w}x{h}.png"
    ctx.progress(0.716, "studio hero (path traced)")
    try:
        r = render_job(ctx.sc, ctx.out_dir / name, w, h, R.camera(target, R.STILL_YAW, ctx.pitch, dist),
                       method="cpu_raytrace", budget="studio",
                       timeout=float(setting(ctx, "views_hero_timeout") or 900))
    except TooBig as exc:
        note(ctx, "hero", skipped=f"the scene is too big for the studio budget: {exc}")
        return
    ctx.add(name, variant="hero", width=w, height=h)
    note(ctx, "hero", method="cpu_raytrace", budget="studio", s=r["s"])


# ---------------------------------------------------------------- F16 plate

def _plate_view(size: list[float]) -> tuple[float, float, int, int]:
    """(yaw, pitch, u axis, v axis) looking along the part's thinnest axis: the part as
    it would lie on that side, seen from above."""
    thin = min(range(3), key=lambda i: size[i])
    if thin == 2:
        return 0.0, math.pi / 2, 0, 1  # top-down: X right, Y up
    if thin == 1:
        return 0.0, 0.0, 0, 2  # from -Y: X right, Z up
    return R.yaw_towards(1.0, 0.0), 0.0, 1, 2  # from +X: Y right, Z up


def plate(ctx: StepContext) -> None:
    sc = ctx.sc
    parts = [b for b in ctx.info if b.get("visible") is not False and (b.get("bbox") or {}).get("min")]
    groups: dict[tuple, list[dict]] = {}
    for b in parts:  # identical parts share a cell: "×4"
        size = [b["bbox"]["max"][i] - b["bbox"]["min"][i] for i in range(3)]
        key = (tuple(round(v, 2) for v in sorted(size)), round(float(b.get("volume_mm3") or 0), 1))
        groups.setdefault(key, []).append(b)
    if len(groups) > PLATE_MAX_PARTS:
        note(ctx, "plate", skipped=f"{len(groups)} different parts; the plate shows up to {PLATE_MAX_PARTS}")
        return
    longest = max(max(b["bbox"]["max"][i] - b["bbox"]["min"][i] for i in range(3)) for b in parts)
    s = min(12.0, 900.0 / max(longest, 1e-6))  # px per mm, shared by every part
    hidden = {b["name"] for b in ctx.info if b.get("visible") is False}
    folder = ctx.out_dir / "_plate"
    folder.mkdir(exist_ok=True)
    cells, how = [], set()
    try:
        ctx.restore()
        for gi, members in enumerate(groups.values()):
            b = members[0]
            lo, hi = b["bbox"]["min"], b["bbox"]["max"]
            size = [hi[i] - lo[i] for i in range(3)]
            yaw, pitch, u, v = _plate_view(size)
            pad = 12
            w = max(32, math.ceil(size[u] * s) + 2 * pad)
            h = max(32, math.ceil(size[v] * s) + 2 * pad)
            cam = {"target": [(lo[i] + hi[i]) / 2 for i in range(3)], "yaw": yaw, "pitch": pitch,
                   "distance": h / (2 * R.ORTHO_HALF * s), "fov": 0}
            iso = sc.execute("browser.visibility", visible=True, items=[b["name"]], isolate=True) or {}
            vis = iso.get("visibility") or {}
            changed = set(vis.get("hidden_bodies") or []) != hidden or bool(vis.get("hidden_occurrences"))
            path = folder / f"p{gi:03d}.png"
            try:
                render_job(sc, path, w, h, cam, method="raster")
                how.add("raster")
            except TooBig:
                sc.screenshot(path, cam, w, h)  # big scene: the viewport's background stays
                how.add("screenshot")
            finally:
                if changed:
                    sc.execute("edit.undo")
            count = f" ×{len(members)}" if len(members) > 1 else ""
            cells.append((path, f"{b['name']}{count}", f"{size[u]:.1f} × {size[v]:.1f} mm"))
        R.clamp_all([], [c[0] for c in cells])
        name = f"{ctx.stem}-plate.png"
        pw, ph = sheets.plate(cells, ctx.out_dir / name, px_per_mm=s,
                              title=f"{ctx.stem} · parts on their thinnest side (a guess) · 10 mm grid")
        ctx.add(name, variant="plate", width=pw, height=ph)
        note(ctx, "plate", parts=len(parts), cells=len(cells), px_per_mm=round(s, 3), method=sorted(how))
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        now = {b["name"]: b.get("visible") for b in sc.bodies()}
        wrong = [n for n, vis in now.items() if (vis is False) != (n in hidden)]
        if wrong:  # the undo didn't put visibility back: set it by hand
            show = [n for n in wrong if n not in hidden]
            if show:
                _try(sc, "browser.visibility", visible=True, items=show)
            back = [n for n in wrong if n in hidden]
            if back:
                _try(sc, "browser.visibility", visible=False, items=back)
            note(ctx, "plate", visibility_fixed=wrong[:20])


def register() -> None:
    register_step("views-facts", facts, order=10)
    register_step("views-exploded", exploded, order=12,
                  when=lambda c: bool(setting(c, "views_exploded")) and len(c.bodies) > 1)
    register_step("views-section", section, order=20, when=lambda c: bool(setting(c, "views_section")))
    register_step("views-motion", motion, order=25, when=lambda c: bool(setting(c, "views_motion")))
    register_step("views-configs", configs, order=30, when=lambda c: bool(setting(c, "views_configs")))
    register_step("views-transparent", transparent, order=40,
                  when=lambda c: bool(setting(c, "views_transparent")))
    register_step("views-hero", hero, order=42, when=lambda c: bool(setting(c, "views_hero")))
    register_step("views-plate", plate, order=48, when=lambda c: bool(setting(c, "views_plate")))
