"""One design → a render set: shaded and wireframe turntables in every delivery format,
plus square social and high-resolution stills.

The wireframe look comes from painting every body fully see-through: SolidCraft then
draws a faint glass with every B-rep edge, hidden ones included. (Headless capture
ignores `view.visual_style`; see docs/spike.md.)
"""

import math
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import palette as palettes
from .config import get_settings
from .solidcraft import SolidCraft, SolidCraftError

STYLES = ("shaded", "wireframe")
FOV = 0.5  # vertical field of view, radians (~29°): a gentle perspective
STILL_YAW = -math.pi / 4  # front-right, the isometric side


@dataclass
class RenderOptions:
    palette: str = "cool-grey"
    seconds: float = 8.0
    fps: int = 30
    pitch_deg: float = 24.0
    hires_width: int = 3840
    hires_height: int = 2160
    social_size: int = 2048
    gif_width: int = 640
    gif_fps: int = 15
    styles: list[str] = field(default_factory=lambda: list(STYLES))

    def validate(self) -> "RenderOptions":
        palettes.get(self.palette)
        if not 2 <= self.seconds <= 30:
            raise ValueError("seconds must be 2 to 30")
        if self.fps not in (24, 25, 30, 60):
            raise ValueError("fps must be 24, 25, 30 or 60")
        if not 0 <= self.pitch_deg <= 80:
            raise ValueError("pitch_deg must be 0 to 80")
        for v in (self.hires_width, self.hires_height, self.social_size):
            if not 256 <= v <= 8192:
                raise ValueError("still sizes must be 256 to 8192 pixels")
        if not 160 <= self.gif_width <= 1280:
            raise ValueError("gif_width must be 160 to 1280")
        if not 5 <= self.gif_fps <= 30:
            raise ValueError("gif_fps must be 5 to 30")
        if not self.styles or any(s not in STYLES for s in self.styles):
            raise ValueError(f"styles must be some of {', '.join(STYLES)}")
        return self

    @property
    def frames(self) -> int:
        return round(self.seconds * self.fps)


@dataclass
class Output:
    file: str
    style: str
    variant: str  # 1080p | reel | discord | gif | social | hires
    width: int
    height: int


Progress = Callable[[float, str], None]


# ---------------------------------------------------------------- framing

def _basis(yaw: float, pitch: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Forward, right and up of SolidCraft's orbit camera (docs/mcp.md)."""
    to_eye = np.array([-math.sin(yaw) * math.cos(pitch), -math.cos(yaw) * math.cos(pitch),
                       math.sin(pitch)])
    f = -to_eye
    r = np.array([math.cos(yaw), -math.sin(yaw), 0.0])
    u = np.cross(r, f)
    return f, r, u


def fit_distance(lo: list[float], hi: list[float], width: int, height: int, pitch: float,
                 yaws: list[float], margin: float) -> tuple[list[float], float]:
    """Target and one camera distance that keep the whole box in frame at every yaw."""
    lo_a, hi_a = np.array(lo, float), np.array(hi, float)
    target = (lo_a + hi_a) / 2
    corners = np.array([[x, y, z] for x in (lo_a[0], hi_a[0]) for y in (lo_a[1], hi_a[1])
                        for z in (lo_a[2], hi_a[2])]) - target
    tan_v = math.tan(FOV / 2)
    tan_h = tan_v * width / height
    radius = float(np.linalg.norm(hi_a - lo_a) / 2) or 1.0
    need = radius * 1.05  # the eye stays outside the part
    for yaw in yaws:
        f, r, u = _basis(yaw, pitch)
        depth = corners @ f
        need = max(need,
                   float(np.max(np.abs(corners @ r) * margin / tan_h - depth)),
                   float(np.max(np.abs(corners @ u) * margin / tan_v - depth)))
    return target.tolist(), need


def camera(target: list[float], yaw: float, pitch: float, distance: float) -> dict:
    return {"target": target, "yaw": yaw, "pitch": pitch, "distance": distance, "fov": FOV}


# ---------------------------------------------------------------- encoding

def _ff(*args: str) -> None:
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-600:]}")


X264 = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-preset", "slow"]


def encode(frames: Path, out: Path, fps: int, *, crf: int, vf: str | None = None,
           max_kbps: int | None = None) -> None:
    args = ["-framerate", str(fps), "-i", str(frames / "f%04d.png")]
    if vf:
        args += ["-vf", vf]
    args += [*X264, "-crf", str(crf)]
    if max_kbps:
        args += ["-maxrate", f"{max_kbps}k", "-bufsize", f"{max_kbps * 2}k"]
    _ff(*args, str(out))


def encode_gif(frames: Path, out: Path, fps: int, gif_fps: int, width: int) -> None:
    graph = (f"fps={gif_fps},scale={width}:-1:flags=lanczos,split[a][b];"
             "[a]palettegen=max_colors=128:stats_mode=diff[p];"
             "[b][p]paletteuse=dither=bayer:bayer_scale=4")
    _ff("-framerate", str(fps), "-i", str(frames / "f%04d.png"), "-vf", graph, str(out))


def discord_kbps(seconds: float) -> int:
    """Stay under Discord's 10 MB upload limit with room for the container."""
    return int(min(2500, 9 * 8000 / seconds))


# ---------------------------------------------------------------- the set

def clamp_all(frames: list[Path], stills: list[Path], every: int = 4) -> float:
    """Check every still and every `every`-th frame; if any carries colour, grey out all of
    them. (A face that shows for fewer than `every` frames is under 6° of turn.)"""
    workers = min(12, os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        found = max(pool.map(palettes.colour_fraction, [*stills, *frames[::every]]), default=0.0)
        if found == 0:
            return 0.0
        return max(pool.map(palettes.clamp, [*stills, *frames]), default=0.0)


# ---------------------------------------------------------------- frames, in parallel
#
# SolidCraft spends ~0.55 s of CPU per headless screenshot on a 2,000-body design, at any
# resolution, and one process uses one core. So big designs render with several processes,
# each loading the design once and pulling chunks of frames from a shared queue. Small
# designs (a few ms a frame) stay in one process: loading another would cost more than it saves.

FAN_OUT_MS = 50  # fan out only when a frame takes longer than this
PROBE_FRAMES = 8  # frames rendered in the first process before deciding
CHUNK = 12  # frames per work unit: one style and aspect, so a chunk needs at most one repaint
MEMORY_SHARE = 0.85  # of MemAvailable that extra processes may use
LOAD_PAYBACK = 1.5  # fan out only if one process has this many load times of frames left


@dataclass(frozen=True)
class _Frame:
    style: str
    key: str  # land | vert
    index: int
    yaw: float


def _chunks(frames: list[_Frame], size: int) -> list[list[_Frame]]:
    out: list[list[_Frame]] = []
    for f in frames:
        if out and len(out[-1]) < size and (out[-1][0].style, out[-1][0].key) == (f.style, f.key):
            out[-1].append(f)
        else:
            out.append([f])
    return out


def _rss_bytes(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def _mem_available() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def extra_processes(wanted: int, frame_ms: float, frames_left: int, load_s: float,
                    rss: int | None, available: int | None) -> int:
    """How many processes to add to the first one. None for fast frames, or when the first
    process would finish the remaining frames before another one has loaded the design
    (it would only wait); otherwise no more than free memory holds at the first process's
    size (SELENE-functional: 6.7 GB each)."""
    if wanted <= 1 or frame_ms <= FAN_OUT_MS:
        return 0
    if frames_left * frame_ms / 1000 < LOAD_PAYBACK * load_s:
        return 0
    extra = wanted - 1
    if rss and available:
        extra = min(extra, int(available * MEMORY_SHARE // rss))
    return max(0, extra)


class _Pool:
    """Frame workers sharing one queue; the first failure stops them all."""

    def __init__(self, sc_first: SolidCraft, open_sc: Callable[[], SolidCraft], bodies: list[str],
                 pal, cams: dict, dirs: dict, total: int, tick: Callable[[int, int], None]):
        self.queue: queue.SimpleQueue[list[_Frame]] = queue.SimpleQueue()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.errors: list[BaseException] = []
        self.procs: list[SolidCraft] = [sc_first]
        self.open_sc, self.bodies, self.pal, self.cams, self.dirs = open_sc, bodies, pal, cams, dirs
        self.total, self.tick, self.done = total, tick, 0
        self.painted: dict[int, str] = {}

    def render(self, sc: SolidCraft, chunk: list[_Frame]) -> None:
        style = chunk[0].style
        if self.painted.get(id(sc)) != style:
            if style == "shaded":
                sc.paint(self.bodies, self.pal.shaded, 1.0)
            else:
                sc.paint(self.bodies, self.pal.wireframe, 0.0)
            self.painted[id(sc)] = style
        for f in chunk:
            if self.stop.is_set():
                return
            target, dist, w, h, pitch = self.cams[f.key]
            sc.screenshot(self.dirs[(f.style, f.key)] / f"f{f.index:04d}.png",
                          camera(target, f.yaw, pitch, dist), w, h)
            with self.lock:
                self.done += 1
                done, workers = self.done, len(self.procs)
            self.tick(done, workers)

    def fail(self, exc: BaseException) -> None:
        with self.lock:
            if self.stop.is_set():
                return  # a worker killed by the stop, not a new failure
            self.errors.append(exc)
            self.stop.set()
            procs = list(self.procs)
        for sc in procs:
            sc.kill()

    def drain(self, sc: SolidCraft) -> None:
        try:
            while not self.stop.is_set():
                try:
                    chunk = self.queue.get_nowait()
                except queue.Empty:
                    return
                self.render(sc, chunk)
        except BaseException as exc:  # noqa: BLE001 - reported through fail()
            self.fail(exc)

    def extra(self) -> None:
        try:
            sc = self.open_sc()
        except BaseException as exc:  # noqa: BLE001
            self.fail(exc)
            return
        with self.lock:
            stopped = self.stop.is_set()
            if not stopped:
                self.procs.append(sc)
        if stopped:
            sc.kill()
            return
        try:
            self.drain(sc)
        finally:
            sc.close()


def render_set(design: Path, out_dir: Path, stem: str, opts: RenderOptions,
               progress: Progress = lambda f, m: None,
               processes: int | None = None,
               settings: dict | None = None) -> tuple[list[Output], dict]:
    """Render everything into out_dir. Returns the outputs and a small report.

    `processes` caps the SolidCraft processes used for frames (default: the
    SK_RENDER_PROCESSES setting); see FAN_OUT_MS for when more than one is used."""
    opts.validate()
    if processes is None:
        processes = get_settings().render_processes
    pal = palettes.get(opts.palette)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_frames"
    pitch = math.radians(opts.pitch_deg)
    n = opts.frames
    yaws = [STILL_YAW + 2 * math.pi * i / n for i in range(n)]
    outputs: list[Output] = []
    report: dict = {"options": asdict(opts), "clamped": {}}
    timings: dict[str, float] = {}
    clock = time.monotonic()

    def open_sc() -> SolidCraft:
        return SolidCraft(design, out_dir)

    progress(0.01, "opening design")
    with open_sc() as sc:
        info = sc.bodies()
        bodies = [b["name"] for b in info]
        if not bodies:
            raise SolidCraftError("the design has no solid bodies to render")
        box = sc.bounds(info)
        if box is None:
            raise SolidCraftError("the design has no visible bodies to frame")
        timings["load"] = time.monotonic() - clock
        report["bodies"] = len(bodies)
        report["hidden_bodies"] = sum(1 for b in info if b.get("visible") is False)
        report["bounds_mm"] = box
        sample = yaws[:: max(1, n // 72)]
        aspects = {"land": (1920, 1080), "vert": (1080, 1920)}
        cams = {}
        for k, (w, h) in aspects.items():
            target, dist = fit_distance(*box, w, h, pitch, sample, margin=1.08)
            cams[k] = (target, dist, w, h, pitch)
        dirs = {}
        for style in opts.styles:
            for k in aspects:
                dirs[(style, k)] = work / f"{style}_{k}"
                dirs[(style, k)].mkdir(parents=True, exist_ok=True)

        frames = [_Frame(style, k, i, yaw) for style in opts.styles for k in aspects
                  for i, yaw in enumerate(yaws)]
        total = len(frames)

        def tick(done: int, workers: int) -> None:
            if done % 20 == 0 or done == total:
                progress(0.05 + 0.65 * done / total,
                         f"frame {done}/{total}" + (f" ({workers} processes)" if workers > 1 else ""))

        pool = _Pool(sc, open_sc, bodies, pal, cams, dirs, total, tick)
        clock = time.monotonic()
        # Probe: the first frame pays the geometry upload, so time the ones after it.
        probe, rest = frames[:PROBE_FRAMES], frames[PROBE_FRAMES:]
        pool.render(sc, probe[:1])
        t0 = time.monotonic()
        pool.render(sc, probe[1:])
        frame_ms = 1000 * (time.monotonic() - t0) / max(1, len(probe) - 1)
        extra = extra_processes(processes, frame_ms, len(rest), timings["load"],
                                _rss_bytes(sc.proc.pid), _mem_available())
        report["frame_ms"] = round(frame_ms, 1)
        report["processes"] = 1 + extra
        for chunk in _chunks(rest, CHUNK):
            pool.queue.put(chunk)
        threads = [threading.Thread(target=pool.extra, daemon=True, name=f"solidcraft-{i + 1}")
                   for i in range(extra)]
        for t in threads:
            t.start()
        pool.drain(sc)
        for t in threads:
            t.join()
        if pool.errors:
            raise pool.errors[0]
        timings["frames"] = time.monotonic() - clock

        clock = time.monotonic()
        for style in opts.styles:
            sc.paint(bodies, pal.shaded if style == "shaded" else pal.wireframe,
                     1.0 if style == "shaded" else 0.0)
            stills = {"social": (opts.social_size, opts.social_size),
                      "hires": (opts.hires_width, opts.hires_height)}
            for variant, (w, h) in stills.items():
                target, dist = fit_distance(*box, w, h, pitch, [STILL_YAW], margin=1.04)
                name = (f"{stem}-{style}-social-{w}.png" if variant == "social"
                        else f"{stem}-{style}-hires-{w}x{h}.png")
                sc.screenshot(out_dir / name, camera(target, STILL_YAW, pitch, dist), w, h)
                outputs.append(Output(name, style, variant, w, h))
        timings["stills"] = time.monotonic() - clock

        # Feature steps (sklent.steps): exploded views, sections, specs ... on the same process.
        from . import steps as _steps
        extra_guard: list[Path] = []
        if _steps.registered():
            clock = time.monotonic()
            progress(0.705, "extra views")
            ctx = _steps.StepContext(sc=sc, design=design, out_dir=out_dir, stem=stem, opts=opts,
                                     info=info, bodies=bodies, box=box, palette=pal, pitch=pitch,
                                     report=report, settings=dict(settings or asdict(opts)),
                                     progress=progress)
            _steps.run_all(ctx)
            outputs.extend(ctx.added)
            extra_guard = [p for p in ctx.guard if p.exists()]
            timings["steps"] = time.monotonic() - clock

    clock = time.monotonic()
    # Colour guard: nothing leaves here in a design's own colours.
    progress(0.72, "checking colours")
    for style in opts.styles:
        frames = sorted((work / f"{style}_land").glob("*.png")) + sorted(
            (work / f"{style}_vert").glob("*.png"))
        stills = [out_dir / o.file for o in outputs if o.style == style and o.variant in ("social", "hires")]
        stills += [p for p in extra_guard if any(o.file == p.name and o.style == style for o in outputs)]
        report["clamped"][style] = round(clamp_all(frames, stills), 5)
    other = [p for p in extra_guard if not any(o.file == p.name and o.style in opts.styles for o in outputs)]
    if other:
        report["clamped"]["extra"] = round(clamp_all([], other), 5)

    kbps = discord_kbps(opts.seconds)
    for si, style in enumerate(opts.styles):
        land, vert = work / f"{style}_land", work / f"{style}_vert"
        progress(0.75 + 0.24 * si / len(opts.styles), f"encoding {style}")
        jobs = [
            (f"{stem}-{style}-1080p.mp4", "1080p", 1920, 1080,
             lambda o, land=land: encode(land, o, opts.fps, crf=18)),
            (f"{stem}-{style}-reel-1080x1920.mp4", "reel", 1080, 1920,
             lambda o, vert=vert: encode(vert, o, opts.fps, crf=20)),
            (f"{stem}-{style}-discord-640p.mp4", "discord", 1138, 640,
             lambda o, land=land: encode(land, o, opts.fps, crf=24, vf="scale=-2:640:flags=lanczos",
                              max_kbps=kbps)),
            (f"{stem}-{style}.gif", "gif", opts.gif_width, round(opts.gif_width * 9 / 16),
             lambda o, land=land: encode_gif(land, o, opts.fps, opts.gif_fps, opts.gif_width)),
        ]
        for name, variant, w, h, run in jobs:
            run(out_dir / name)
            outputs.append(Output(name, style, variant, w, h))

    timings["guard_and_encode"] = time.monotonic() - clock
    report["timings_s"] = {k: round(v, 1) for k, v in timings.items()}
    shutil.rmtree(work, ignore_errors=True)
    order = {"1080p": 0, "reel": 1, "discord": 2, "gif": 3, "social": 4, "hires": 5}
    outputs.sort(key=lambda o: (STYLES.index(o.style) if o.style in STYLES else len(STYLES),
                                order.get(o.variant, len(order))))
    progress(1.0, "rendered")
    return outputs, report
