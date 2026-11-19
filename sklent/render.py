"""One design → a render set: a quick-check still first, then shaded and wireframe
turntables in every delivery format, square social and high-resolution stills, and (when
turned on) shot presets, edit-ready masters and a "my part" highlight.

The wireframe look comes from painting every body fully see-through: SolidCraft then
draws a faint glass with every B-rep edge, hidden ones included. (Headless capture
ignores `view.visual_style`; see docs/spike.md.)

Which files a render makes:
- `RenderOptions.outputs` picks the core ones (CORE_OUTPUTS). An empty list is a quick
  check: the preview still only.
- The quick-check still (`<stem>-preview.png`, variant `preview`) is always made first,
  right after the design loads, so the UI can show it while the rest renders.
- Feature settings (`views_*`, registered by `sklent.features.views`) add shot presets,
  4K masters and the highlight turntable here; the other views are render steps
  (`sklent.steps`). Each reads its setting from the `settings` dict, so `render_set`
  works without the feature module (the CLI, tests).
"""

import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

import numpy as np

from . import palette as palettes
from .config import get_settings
from .solidcraft import SolidCraft, SolidCraftError, gpu_info

STYLES = ("shaded", "wireframe")
FOV = 0.5  # vertical field of view, radians (~29°): a gentle perspective
STILL_YAW = -math.pi / 4  # front-right, the isometric side
ORTHO_HALF = 0.4  # SolidCraft's ortho camera (fov 0) shows ±0.4 × distance vertically

# The core outputs a render can make; RenderOptions.outputs picks some of them.
CORE_OUTPUTS = ("1080p", "reel", "discord", "gif", "social", "hires")
LAND_OUTPUTS = ("1080p", "discord", "gif")  # made from the landscape frames
PREVIEW_SIZE = 1024
# Shot presets (F24): the orbit is the turntable itself; these are extra clips.
SHOTS = ("half-orbit", "push-in", "top-to-iso", "low-angle")
MASTER_SIZE = (3840, 2160)
MASTER_MAX_S = 60.0
# A master bigger than this isn't kept: Kist's default upload cap is 4 GiB, and a file
# that fails to file would fail the whole render. (60 s of 4K PNGs of a big assembly.)
MASTER_MAX_BYTES = int(3.5 * 2**30)
HIGHLIGHT = "highlight"  # the paint mode (and Output.style) of "my part" renders


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
    outputs: list[str] = field(default_factory=lambda: list(CORE_OUTPUTS))

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
        if not isinstance(self.outputs, list) or any(o not in CORE_OUTPUTS for o in self.outputs):
            raise ValueError(f"outputs must be a list of some of {', '.join(CORE_OUTPUTS)} "
                             "(empty: the quick-check still only)")
        self.outputs = [o for o in CORE_OUTPUTS if o in self.outputs]  # canonical order, no repeats
        return self

    @property
    def frames(self) -> int:
        return round(self.seconds * self.fps)


@dataclass
class Output:
    file: str
    style: str
    variant: str  # preview | 1080p | reel | discord | gif | social | hires | feature variants
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


def yaw_towards(dx: float, dy: float) -> float:
    """The orbit yaw that puts the eye on the (dx, dy) side of the target."""
    return math.atan2(-dx, -dy)


def ortho_fit(lo: list[float], hi: list[float], width: int, height: int, yaw: float, pitch: float,
              margin: float = 1.08) -> dict:
    """An orthographic camera (fov 0) that frames the box from (yaw, pitch). The visible
    half-height is ORTHO_HALF × distance, so the scale is height / (2 · 0.4 · distance) px/mm."""
    lo_a, hi_a = np.array(lo, float), np.array(hi, float)
    target = (lo_a + hi_a) / 2
    corners = np.array([[x, y, z] for x in (lo_a[0], hi_a[0]) for y in (lo_a[1], hi_a[1])
                        for z in (lo_a[2], hi_a[2])]) - target
    _, r, u = _basis(yaw, pitch)
    half_w = float(np.max(np.abs(corners @ r))) or 1.0
    half_h = float(np.max(np.abs(corners @ u))) or 1.0
    half = max(half_h, half_w * height / width) * margin
    return {"target": target.tolist(), "yaw": yaw, "pitch": pitch, "distance": half / ORTHO_HALF, "fov": 0}


def ortho_scale(cam: dict, height: int) -> float:
    """Pixels per mm of an orthographic camera at an image height."""
    return height / (2 * ORTHO_HALF * cam["distance"])


def ease(t: float) -> float:
    """Ease in and out (cosine), 0..1 → 0..1."""
    return 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, t)))


def shot_path(shot: str, box: tuple[list[float], list[float]], pitch: float, n: int,
              width: int = 1920, height: int = 1080) -> list[tuple[tuple[float, ...], float, float, float]]:
    """Per-frame (target, yaw, pitch, distance) of a shot preset, eased in and out. Every
    frame is fitted to the bounding box, so the part stays in frame through the move."""
    lo, hi = box
    out = []
    ts = [i / max(1, n - 1) for i in range(n)]
    if shot == "half-orbit":  # half a turn that settles on the hero (iso) angle
        yaws = [STILL_YAW - math.pi * (1 - ease(t)) for t in ts]
        target, dist = fit_distance(lo, hi, width, height, pitch, yaws[:: max(1, n // 36)], 1.08)
        return [(tuple(target), y, pitch, dist) for y in yaws]
    if shot == "push-in":  # a slow dolly in on the hero angle, with a little drift
        target, dist = fit_distance(lo, hi, width, height, pitch, [STILL_YAW], 1.04)
        for t in ts:
            e = ease(t)
            out.append((tuple(target), STILL_YAW + math.radians(12) * (1 - e), pitch, dist * (1.7 - 0.7 * e)))
        return out
    if shot == "top-to-iso":  # straight down, then tilt to the iso angle
        top = math.radians(89.5)
        for t in ts:
            p = top + (pitch - top) * ease(t)
            target, dist = fit_distance(lo, hi, width, height, p, [STILL_YAW], 1.08)
            out.append((tuple(target), STILL_YAW, p, dist))
        return out
    if shot == "low-angle":  # a low hero angle, a slow 60° pass
        low = math.radians(6)
        yaws = [STILL_YAW - math.pi / 6 + (math.pi / 3) * ease(t) for t in ts]
        target, dist = fit_distance(lo, hi, width, height, low, yaws[:: max(1, n // 36)], 1.08)
        return [(tuple(target), y, low, dist) for y in yaws]
    raise ValueError(f"unknown shot {shot!r}; one of {', '.join(SHOTS)}")


def match_bodies(names: list[str], patterns: list[str]) -> list[str]:
    """Bodies whose name matches any pattern (exact or a glob such as `Arm*`)."""
    pats = [p for p in (patterns or []) if isinstance(p, str) and p.strip()]
    return [n for n in names if any(n == p or fnmatchcase(n, p) for p in pats)]


_INSTANCE = re.compile(r"^(?P<definition>.+) \((?P<component>[^()]+):(?P<n>\d+)\)$")


def world_bodies(sc: SolidCraft, info: list[dict] | None = None) -> list[dict]:
    """inspect_design's bodies with their bounding boxes where they are placed.

    inspect_design measures a component's bodies in the component's own frame, so a part
    a joint turns (a hinge leaf standing up) would be framed where it was modelled, and
    cropped. `measure {summary}` gives each placed body's box in the world; it replaces the
    bbox by name. A component placed more than once shows up in `measure` as more bodies
    (`ArmBody`, `ArmBody (Arm:2)`): those extra placements go into their definition's
    `placed` list, so `placed_bounds` frames every instance where it really sits. If
    `measure` fails, inspect_design's boxes stand."""
    info = sc.bodies() if info is None else info
    try:
        rows = (sc.tool("measure", summary=True) or {}).get("bodies", [])
    except Exception:  # noqa: BLE001 - a refinement of the framing never fails a render
        return info
    by_name = {b.get("name"): b for b in info}
    extra = [r for r in rows if r.get("name") not in by_name]
    definition: dict[str, str] = {}
    if extra:  # instances beyond the first: which definition each one places
        try:
            definition = {r.get("name"): r.get("definition") for r in
                          (sc.tool("measure", names_only=True) or {}).get("bodies", []) if r.get("definition")}
        except Exception:  # noqa: BLE001 - fall back to the "Body (Component:n)" naming
            definition = {}
    for r in rows:
        box = r.get("bbox") or {}
        if not (box.get("min") and box.get("max")):
            continue
        name = r.get("name")
        if name in by_name:
            by_name[name]["bbox"] = box
            continue
        m = _INSTANCE.match(name or "")
        owner = by_name.get(definition.get(name) or (m.group("definition") if m else None))
        if owner is not None:
            owner.setdefault("placed", []).append(box)
        elif r.get("visible") is not False and info:  # an unknown placed body still has to be in frame
            host = next((b for b in info if b.get("visible") is not False), info[0])
            host.setdefault("placed", []).append(box)
    return info


def placed_bounds(info: list[dict]) -> tuple[list[float], list[float]] | None:
    """The union of every visible body's box and its extra placements (world_bodies)."""
    flat = []
    for b in info:
        flat.append(b)
        flat += [{"bbox": box, "visible": b.get("visible")} for box in b.get("placed") or []]
    return SolidCraft.bounds(flat)


# ---------------------------------------------------------------- encoding

def ffmpeg() -> str:
    """The ffmpeg to run (SK_FFMPEG; a full path on a Mac helper)."""
    return get_settings().ffmpeg or "ffmpeg"


def host_name() -> str:
    """This machine's name in report.json (SK_HOST_NAME, else the host name)."""
    import socket

    return get_settings().host_name or socket.gethostname() or "host"


def _ff(*args: str) -> None:
    r = subprocess.run([ffmpeg(), "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-600:]}")


X264 = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-preset", "slow"]


def encode(frames: Path, out: Path, fps: int, *, crf: int, vf: str | None = None,
           max_kbps: int | None = None, pattern: str = "f%04d.png", start: int = 0) -> None:
    args = ["-framerate", str(fps), "-start_number", str(start), "-i", str(frames / pattern)]
    if vf:
        args += ["-vf", vf]
    args += [*X264, "-crf", str(crf)]
    if max_kbps:
        args += ["-maxrate", f"{max_kbps}k", "-bufsize", f"{max_kbps * 2}k"]
    _ff(*args, str(out))


def encode_gif(frames: Path, out: Path, fps: int, gif_fps: int, width: int,
               pattern: str = "f%04d.png", start: int = 0) -> None:
    graph = (f"fps={gif_fps},scale={width}:-1:flags=lanczos,split[a][b];"
             "[a]palettegen=max_colors=128:stats_mode=diff[p];"
             "[b][p]paletteuse=dither=bayer:bayer_scale=4")
    _ff("-framerate", str(fps), "-start_number", str(start), "-i", str(frames / pattern),
        "-vf", graph, str(out))


def encode_prores(frames: Path, out: Path, fps: int) -> None:
    """ProRes 422 HQ (prores_ks profile 3), 10-bit 4:2:2: an edit-ready intermediate."""
    _ff("-framerate", str(fps), "-i", str(frames / "f%04d.png"), "-c:v", "prores_ks",
        "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-vendor", "apl0", str(out))


def zip_frames(frames: Path, out: Path) -> None:
    """The PNG sequence as a zip (stored: PNGs don't compress further)."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for p in sorted(frames.glob("*.png")):
            z.write(p, f"{out.stem}/{p.name}")


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
    style: str  # the paint: shaded | wireframe | highlight
    key: str  # the frame folder and size: land | vert | master | shot-<name>
    index: int
    yaw: float
    cam: tuple | None = None  # (target, yaw, pitch, distance) for moving-camera shots


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


def paint_style(sc: SolidCraft, bodies: list[str], pal, style: str, highlight: list[str] | None = None) -> None:
    """Paint every body for a style. `highlight`: the chosen bodies solid, the rest x-ray."""
    if style == HIGHLIGHT:
        chosen = set(highlight or [])
        rest = [b for b in bodies if b not in chosen]
        if rest:
            sc.paint(rest, pal.wireframe, 0.0)
        if chosen:
            sc.paint([b for b in bodies if b in chosen], pal.shaded, 1.0)
    elif style == "shaded":
        sc.paint(bodies, pal.shaded, 1.0)
    else:
        sc.paint(bodies, pal.wireframe, 0.0)


class _Pool:
    """Frame workers sharing one queue; the first failure stops them all."""

    def __init__(self, sc_first: SolidCraft, open_sc: Callable[[], SolidCraft], bodies: list[str],
                 pal, cams: dict, dirs: dict, total: int, tick: Callable[[int, int], None],
                 highlight: list[str] | None = None):
        self.queue: queue.SimpleQueue[list[_Frame]] = queue.SimpleQueue()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.errors: list[BaseException] = []
        self.procs: list[SolidCraft] = [sc_first]
        self.open_sc, self.bodies, self.pal, self.cams, self.dirs = open_sc, bodies, pal, cams, dirs
        self.total, self.tick, self.done = total, tick, 0
        self.highlight = highlight or []
        self.painted: dict[int, str] = {}

    def render(self, sc: SolidCraft, chunk: list[_Frame]) -> None:
        style = chunk[0].style
        if self.painted.get(id(sc)) != style:
            paint_style(sc, self.bodies, self.pal, style, self.highlight)
            self.painted[id(sc)] = style
        for f in chunk:
            if self.stop.is_set():
                return
            target, dist, w, h, pitch = self.cams[f.key]
            cam = camera(list(f.cam[0]), f.cam[1], f.cam[2], f.cam[3]) if f.cam else \
                camera(target, f.yaw, pitch, dist)
            sc.screenshot(self.dirs[(f.style, f.key)] / f"f{f.index:04d}.png", cam, w, h)
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


# ---------------------------------------------------------------- what to make

@dataclass
class Plan:
    """Which frame sequences and stills a render makes, from the options and settings."""
    land: bool
    vert: bool
    stills: list[str]  # social | hires
    shots: list[str]
    shot_seconds: float
    master: list[str]  # mp4 | zip | prores
    master_seconds: float
    highlight: list[str]  # patterns; matched against body names at render time


def _num(v, default: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, x))


def plan(opts: RenderOptions, settings: dict | None) -> Plan:
    s = settings or {}
    outs = opts.outputs
    master = [k for k, key in (("mp4", "views_master_4k"), ("zip", "views_master_zip"),
                               ("prores", "views_master_prores")) if s.get(key)]
    secs = _num(s.get("views_master_seconds"), 0.0, 0.0, MASTER_MAX_S)
    return Plan(
        land=any(o in outs for o in LAND_OUTPUTS),
        vert="reel" in outs,
        stills=[o for o in ("social", "hires") if o in outs],
        shots=[sh for sh in SHOTS if s.get("views_shot_" + sh.replace("-", "_"))],
        shot_seconds=_num(s.get("views_shot_seconds"), 6.0, 2.0, 12.0),
        master=master,
        master_seconds=secs if secs > 0 else opts.seconds,
        highlight=[str(x) for x in (s.get("views_highlight_names") or []) if str(x).strip()],
    )


def render_set(design: Path, out_dir: Path, stem: str, opts: RenderOptions,
               progress: Progress = lambda f, m: None,
               processes: int | None = None,
               settings: dict | None = None, renderer: str | None = None,
               host: str | None = None) -> tuple[list[Output], dict]:
    """Render everything into out_dir. Returns the outputs and a small report.

    `processes` caps the SolidCraft processes used for frames (default: the
    SK_RENDER_PROCESSES setting); see FAN_OUT_MS for when more than one is used.
    `settings` is the full settings dict (RenderOptions plus registered feature keys).
    `renderer` is gpu (default) or software (Mesa lavapipe: no GPU at all); the report
    records what SolidCraft actually landed on (`renderer`, `adapter`) and `host`."""
    opts.validate()
    if processes is None:
        processes = get_settings().render_processes
    pal = palettes.get(opts.palette)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_frames"
    pitch = math.radians(opts.pitch_deg)
    n = opts.frames
    yaws = [STILL_YAW + 2 * math.pi * i / n for i in range(n)]
    pl = plan(opts, settings)
    outputs: list[Output] = []
    report: dict = {"options": asdict(opts), "clamped": {}}
    used = gpu_info(renderer)
    report["renderer"] = used["renderer"]
    report["adapter"] = used.get("adapter")
    report["host"] = host or host_name()
    timings: dict[str, float] = {}
    clock = time.monotonic()
    sc_args = {"renderer": renderer} if renderer and renderer != "gpu" else {}

    def open_sc() -> SolidCraft:
        return SolidCraft(design, out_dir, **sc_args)

    progress(0.01, "opening design")
    with open_sc() as sc:
        info = sc.bodies()
        bodies = [b["name"] for b in info]
        if not bodies:
            raise SolidCraftError("the design has no solid bodies to render")
        timings["load"] = time.monotonic() - clock
        clock = time.monotonic()
        info = world_bodies(sc, info)  # boxes where the parts are placed (joints, components)
        timings["measure"] = time.monotonic() - clock
        # The turntable, stills, preview and every step frame this one world box.
        box = placed_bounds(info)
        if box is None:
            raise SolidCraftError("the design has no visible bodies to frame")
        report["bodies"] = len(bodies)
        report["hidden_bodies"] = sum(1 for b in info if b.get("visible") is False)
        report["bounds_mm"] = box

        # Quick check (F17): one shaded iso still, guarded, before anything else.
        clock = time.monotonic()
        paint_style(sc, bodies, pal, "shaded")
        target, dist = fit_distance(*box, PREVIEW_SIZE, PREVIEW_SIZE, pitch, [STILL_YAW], margin=1.04)
        preview = f"{stem}-preview.png"
        sc.screenshot(out_dir / preview, camera(target, STILL_YAW, pitch, dist), PREVIEW_SIZE, PREVIEW_SIZE)
        report["clamped"]["preview"] = round(clamp_all([], [out_dir / preview]), 5)
        outputs.append(Output(preview, "shaded", "preview", PREVIEW_SIZE, PREVIEW_SIZE))
        timings["preview"] = time.monotonic() - clock
        progress(0.03, "quick check ready")

        highlight = match_bodies(bodies, pl.highlight) if pl.highlight else []
        if pl.highlight:
            hl: dict = {"patterns": pl.highlight, "bodies": highlight}
            if not highlight:
                hl["skipped"] = "no body matches the highlight names"
            report["highlight"] = hl

        sample = yaws[:: max(1, n // 72)]
        sizes = {"land": (1920, 1080), "vert": (1080, 1920), "master": MASTER_SIZE}
        cams = {}
        for k, (w, h) in sizes.items():
            target, dist = fit_distance(*box, w, h, pitch, sample, margin=1.08)
            cams[k] = (target, dist, w, h, pitch)

        frames: list[_Frame] = []
        for style in opts.styles:
            for k, on in (("land", pl.land), ("vert", pl.vert)):
                if on:
                    frames += [_Frame(style, k, i, yaw) for i, yaw in enumerate(yaws)]
        if pl.master:
            nm = round(pl.master_seconds * opts.fps)
            m_yaws = [STILL_YAW + 2 * math.pi * i / nm for i in range(nm)]  # loops: no repeat frame
            frames += [_Frame(style, "master", i, y) for style in opts.styles for i, y in enumerate(m_yaws)]
        ns = round(pl.shot_seconds * opts.fps)
        for shot in pl.shots:
            cams[f"shot-{shot}"] = (cams["land"][0], cams["land"][1], 1920, 1080, pitch)
            path = shot_path(shot, box, pitch, ns)
            frames += [_Frame(style, f"shot-{shot}", i, c[1], c) for style in opts.styles
                       for i, c in enumerate(path)]
        if highlight:
            frames += [_Frame(HIGHLIGHT, "land", i, yaw) for i, yaw in enumerate(yaws)]
        dirs = {}
        for f in frames:
            if (f.style, f.key) not in dirs:
                dirs[(f.style, f.key)] = work / f"{f.style}_{f.key}"
                dirs[(f.style, f.key)].mkdir(parents=True, exist_ok=True)
        total = len(frames)

        def tick(done: int, workers: int) -> None:
            if done % 20 == 0 or done == total:
                progress(0.05 + 0.65 * done / total,
                         f"frame {done}/{total}" + (f" ({workers} processes)" if workers > 1 else ""))

        pool = _Pool(sc, open_sc, bodies, pal, cams, dirs, total, tick, highlight)
        clock = time.monotonic()
        report["frame_ms"] = None
        report["processes"] = 1
        if frames:
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
        stills = {"social": (opts.social_size, opts.social_size),
                  "hires": (opts.hires_width, opts.hires_height)}
        for style in opts.styles:
            if not pl.stills:
                break
            paint_style(sc, bodies, pal, style)
            for variant in pl.stills:
                w, h = stills[variant]
                target, dist = fit_distance(*box, w, h, pitch, [STILL_YAW], margin=1.04)
                name = (f"{stem}-{style}-social-{w}.png" if variant == "social"
                        else f"{stem}-{style}-hires-{w}x{h}.png")
                sc.screenshot(out_dir / name, camera(target, STILL_YAW, pitch, dist), w, h)
                outputs.append(Output(name, style, variant, w, h))
        if highlight:  # the "my part" still (F20), at the high-res size
            paint_style(sc, bodies, pal, HIGHLIGHT, highlight)
            w, h = opts.hires_width, opts.hires_height
            target, dist = fit_distance(*box, w, h, pitch, [STILL_YAW], margin=1.04)
            name = f"{stem}-highlight-{w}x{h}.png"
            sc.screenshot(out_dir / name, camera(target, STILL_YAW, pitch, dist), w, h)
            outputs.append(Output(name, HIGHLIGHT, "highlight", w, h))
        timings["stills"] = time.monotonic() - clock

        # Feature steps (sklent.steps): exploded views, sections, specs ... on the same process.
        from . import steps as _steps
        extra_guard: list[Path] = []
        if _steps.registered() and not (settings or {}).get("quick_check"):
            clock = time.monotonic()
            progress(0.705, "extra views")
            paint_style(sc, bodies, pal, "shaded")  # steps start from the shaded look
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
    guarded: set[str] = {preview}
    for style in [*opts.styles, *([HIGHLIGHT] if highlight else [])]:
        frames_of = [p for (st, _), d in dirs.items() if st == style for p in sorted(d.glob("*.png"))]
        mine = [out_dir / o.file for o in outputs
                if o.style == style and o.file not in guarded and o.file.endswith(".png")
                and (o.variant in ("social", "hires", "highlight")
                     or any(p.name == o.file for p in extra_guard))]
        guarded.update(p.name for p in mine)
        if frames_of or mine:
            report["clamped"][style] = round(clamp_all(frames_of, mine), 5)
    other = [p for p in extra_guard if p.name not in guarded]
    if other:
        report["clamped"]["extra"] = round(clamp_all([], other), 5)

    kbps = discord_kbps(opts.seconds)
    jobs: list[tuple[str, str, str, int, int, Callable[[Path], None]]] = []
    for style in opts.styles:
        land, vert = work / f"{style}_land", work / f"{style}_vert"
        core = {
            "1080p": (f"{stem}-{style}-1080p.mp4", 1920, 1080,
                      lambda o, land=land: encode(land, o, opts.fps, crf=18)),
            "reel": (f"{stem}-{style}-reel-1080x1920.mp4", 1080, 1920,
                     lambda o, vert=vert: encode(vert, o, opts.fps, crf=20)),
            "discord": (f"{stem}-{style}-discord-640p.mp4", 1138, 640,
                        lambda o, land=land: encode(land, o, opts.fps, crf=24,
                                                    vf="scale=-2:640:flags=lanczos", max_kbps=kbps)),
            "gif": (f"{stem}-{style}.gif", opts.gif_width, round(opts.gif_width * 9 / 16),
                    lambda o, land=land: encode_gif(land, o, opts.fps, opts.gif_fps, opts.gif_width)),
        }
        for variant in ("1080p", "reel", "discord", "gif"):
            if variant in opts.outputs:
                name, w, h, run = core[variant]
                jobs.append((name, style, variant, w, h, run))
        for shot in pl.shots:
            d = work / f"{style}_shot-{shot}"
            jobs.append((f"{stem}-{style}-{shot}-1080p.mp4", style, f"preset-{shot}", 1920, 1080,
                         lambda o, d=d: encode(d, o, opts.fps, crf=18)))
        md = work / f"{style}_master"
        mw, mh = MASTER_SIZE
        if "mp4" in pl.master:
            jobs.append((f"{stem}-{style}-master-{mw}x{mh}.mp4", style, "master-4k", mw, mh,
                         lambda o, md=md: encode(md, o, opts.fps, crf=16)))
        if "prores" in pl.master:
            jobs.append((f"{stem}-{style}-master-{mw}x{mh}-prores.mov", style, "prores", mw, mh,
                         lambda o, md=md: encode_prores(md, o, opts.fps)))
        if "zip" in pl.master:
            jobs.append((f"{stem}-{style}-frames-{mw}x{mh}.zip", style, "frames-zip", mw, mh,
                         lambda o, md=md: zip_frames(md, o)))
    if highlight:
        hd = work / f"{HIGHLIGHT}_land"
        jobs.append((f"{stem}-highlight-1080p.mp4", HIGHLIGHT, "highlight-turntable", 1920, 1080,
                     lambda o, hd=hd: encode(hd, o, opts.fps, crf=18)))
    for i, (name, style, variant, w, h, run) in enumerate(jobs):
        progress(0.75 + 0.24 * i / len(jobs), f"encoding {variant} {style}")
        run(out_dir / name)
        size = (out_dir / name).stat().st_size if (out_dir / name).exists() else 0
        if variant in ("master-4k", "prores", "frames-zip") and size > MASTER_MAX_BYTES:
            (out_dir / name).unlink()
            report.setdefault("skipped", {})[name] = (
                f"{size / 2**30:.1f} GB is over the {MASTER_MAX_BYTES / 2**30:.1f} GB a file may be; "
                "shorten views_master_seconds")
            continue
        outputs.append(Output(name, style, variant, w, h))

    timings["guard_and_encode"] = time.monotonic() - clock
    report["timings_s"] = {k: round(v, 1) for k, v in timings.items()}
    shutil.rmtree(work, ignore_errors=True)
    order = {"preview": -1, "1080p": 0, "reel": 1, "discord": 2, "gif": 3, "social": 4, "hires": 5}
    outputs.sort(key=lambda o: (STYLES.index(o.style) if o.style in STYLES else len(STYLES),
                                order.get(o.variant, len(order))))
    progress(1.0, "rendered")
    return outputs, report
