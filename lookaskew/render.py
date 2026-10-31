"""One design → a render set: shaded and wireframe turntables in every delivery format,
plus square social and high-resolution stills.

The wireframe look comes from painting every body fully see-through: SolidCraft then
draws a faint glass with every B-rep edge, hidden ones included. (Headless capture
ignores `view.visual_style`; see docs/spike.md.)
"""

import math
import os
import shutil
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import palette as palettes
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


def render_set(design: Path, out_dir: Path, stem: str, opts: RenderOptions,
               progress: Progress = lambda f, m: None) -> tuple[list[Output], dict]:
    """Render everything into out_dir. Returns the outputs and a small report."""
    opts.validate()
    pal = palettes.get(opts.palette)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_frames"
    pitch = math.radians(opts.pitch_deg)
    n = opts.frames
    yaws = [STILL_YAW + 2 * math.pi * i / n for i in range(n)]
    outputs: list[Output] = []
    report: dict = {"options": asdict(opts), "clamped": {}}

    progress(0.01, "opening design")
    with SolidCraft(design, out_dir) as sc:
        bodies = sc.bodies()
        if not bodies:
            raise SolidCraftError("the design has no solid bodies to render")
        box = sc.bounds()
        if box is None:
            raise SolidCraftError("could not measure the design's bounding box")
        report["bodies"] = len(bodies)
        report["bounds_mm"] = box
        sample = yaws[:: max(1, n // 72)]
        aspects = {"land": (1920, 1080), "vert": (1080, 1920)}
        fits = {k: fit_distance(*box, w, h, pitch, sample, margin=1.08) for k, (w, h) in aspects.items()}

        total = len(opts.styles) * (2 * n + 2)
        done = 0
        for style in opts.styles:
            if style == "shaded":
                sc.paint(bodies, pal.shaded, 1.0)
            else:
                sc.paint(bodies, pal.wireframe, 0.0)
            for key, (w, h) in aspects.items():
                d = work / f"{style}_{key}"
                d.mkdir(parents=True, exist_ok=True)
                target, dist = fits[key]
                for i, yaw in enumerate(yaws):
                    sc.screenshot(d / f"f{i:04d}.png", camera(target, yaw, pitch, dist), w, h)
                    done += 1
                    if i % 20 == 0:
                        progress(0.05 + 0.65 * done / total, f"{style} {key} frame {i + 1}/{n}")
            stills = {"social": (opts.social_size, opts.social_size),
                      "hires": (opts.hires_width, opts.hires_height)}
            for variant, (w, h) in stills.items():
                target, dist = fit_distance(*box, w, h, pitch, [STILL_YAW], margin=1.04)
                name = (f"{stem}-{style}-social-{w}.png" if variant == "social"
                        else f"{stem}-{style}-hires-{w}x{h}.png")
                sc.screenshot(out_dir / name, camera(target, STILL_YAW, pitch, dist), w, h)
                outputs.append(Output(name, style, variant, w, h))
                done += 1

    # Colour guard: nothing leaves here in a design's own colours.
    progress(0.72, "checking colours")
    for style in opts.styles:
        frames = sorted((work / f"{style}_land").glob("*.png")) + sorted(
            (work / f"{style}_vert").glob("*.png"))
        stills = [out_dir / o.file for o in outputs if o.style == style]
        report["clamped"][style] = round(clamp_all(frames, stills), 5)

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

    shutil.rmtree(work, ignore_errors=True)
    order = {"1080p": 0, "reel": 1, "discord": 2, "gif": 3, "social": 4, "hires": 5}
    outputs.sort(key=lambda o: (STYLES.index(o.style), order[o.variant]))
    progress(1.0, "rendered")
    return outputs, report
