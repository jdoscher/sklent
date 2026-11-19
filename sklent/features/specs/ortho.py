"""Orthographic views from headless SolidCraft, on paper.

Camera maths (checked on 0.44.1, pi-case): with `fov: 0` the visible half-height is
0.4 × distance, so an image H px tall shows 0.8 × distance mm and the scale is
`H / (0.8 × distance)` px per mm. To draw at a chosen scale, set
`distance = H / (0.8 × scale)`. Standard views (third angle, Z up):
- front: yaw 0, pitch 0 (looking along +Y): X right, Z up
- top: yaw 0, pitch 90°: X right, Y up
- right: yaw -90°, pitch 0 (looking along -X): Y right, Z up
- iso: yaw -45°, pitch 35.26°

Headless screenshots always sit on the light theme gradient and the gradient doesn't depend
on the camera, so one screenshot of empty space per image size (the plate) lets
`draw.cutout` lift the part onto paper exactly, with no colour keying.

Drawings: SolidCraft 0.45 adds `drawing.*` (true projected edges, hidden lines, title blocks,
SVG). `drawing_support()` feature-detects it through the command catalog; a sheet backend
for it can be registered with `register_sheet_backend("drawings", fn)` once Sklent pins a
release that has it. 0.2 always uses screenshots.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

from . import draw

ISO_PITCH = math.atan(1 / math.sqrt(2))  # 35.264°: the isometric elevation
VIEWS: dict[str, tuple[float, float]] = {
    "front": (0.0, 0.0),
    "top": (0.0, math.pi / 2),
    "right": (-math.pi / 2, 0.0),
    "iso": (-math.pi / 4, ISO_PITCH),
}
HALF_HEIGHT_PER_DISTANCE = 0.4
MAX_SHOT = 4096  # px, the largest screenshot side we ask for


def basis(yaw: float, pitch: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Forward, right and up of SolidCraft's orbit camera (as render._basis)."""
    to_eye = np.array([-math.sin(yaw) * math.cos(pitch), -math.cos(yaw) * math.cos(pitch), math.sin(pitch)])
    f = -to_eye
    r = np.array([math.cos(yaw), -math.sin(yaw), 0.0])
    u = np.cross(r, f)
    return f, r, u


def corners(lo, hi) -> np.ndarray:
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)


def extent(lo, hi, view: str) -> tuple[float, float, float]:
    """(width, height, depth) of the box seen from a view, in mm."""
    f, r, u = basis(*VIEWS[view])
    c = corners(lo, hi)
    span = lambda v: float(np.ptp(c @ v))  # noqa: E731
    return span(r), span(u), span(f)


def distance_for(height_px: int, scale: float) -> float:
    return height_px / (2 * HALF_HEIGHT_PER_DISTANCE * scale)


def camera(lo, hi, view: str, height_px: int, scale: float) -> dict:
    yaw, pitch = VIEWS[view]
    target = ((np.array(lo, float) + np.array(hi, float)) / 2).tolist()
    return {"target": target, "yaw": yaw, "pitch": pitch, "distance": distance_for(height_px, scale), "fov": 0}


class Shooter:
    """Screenshots on one open design: cut-out views at an exact scale, with the plates
    (empty background per image size) cached."""

    def __init__(self, sc, out_dir: Path, box, tag: str = "specs"):
        self.sc = sc
        self.work = Path(out_dir) / f"_{tag}"
        self.work.mkdir(parents=True, exist_ok=True)
        self.lo, self.hi = box
        self._plates: dict[tuple[int, int], Path] = {}
        self.timings: dict[str, float] = {}
        self.shots = 0

    def _shot(self, path: Path, cam: dict, w: int, h: int) -> None:
        t0 = time.monotonic()
        self.sc.screenshot(path, cam, w, h)
        self.shots += 1
        self.timings["screenshots"] = self.timings.get("screenshots", 0.0) + time.monotonic() - t0

    def plate(self, w: int, h: int) -> Path:
        """The background alone at this size: the camera looks at empty space well clear of
        the part (the gradient is the same for every camera)."""
        key = (w, h)
        if key not in self._plates:
            lo, hi = np.array(self.lo, float), np.array(self.hi, float)
            size = float(np.linalg.norm(hi - lo)) or 1.0
            away = (hi + size * 4 + 1000.0).tolist()
            path = self.work / f"plate-{w}x{h}.png"
            self._shot(path, {"target": away, "yaw": 0.0, "pitch": 0.0, "distance": size, "fov": 0}, w, h)
            self._plates[key] = path
        return self._plates[key]

    def view(self, view: str, scale: float, *, pad: int = 12, name: str | None = None) -> tuple:
        """The part from a standard view at `scale` px/mm, cut out onto transparency and
        trimmed to the box's projection plus `pad`. Returns (RGBA image, info) where info
        has the scale and where the box's projected corners fall in the image."""
        w_mm, h_mm, d_mm = extent(self.lo, self.hi, view)
        w = max(16, math.ceil(w_mm * scale) + 2 * pad)
        h = max(16, math.ceil(h_mm * scale) + 2 * pad)
        # The orthographic camera still clips near and far relative to its distance (a 0.44.1
        # iso shot at distance ~70 mm lost parts 40 mm behind the target), and distance is tied
        # to height and scale: so shoot taller, with the eye well clear of the whole box, and
        # crop back afterwards.
        diag = float(np.linalg.norm(np.array(self.hi, float) - np.array(self.lo, float)))
        need_h = math.ceil(2 * HALF_HEIGHT_PER_DISTANCE * scale * (1.5 * diag + 10))
        shot_w, shot_h = w, min(MAX_SHOT, max(h, need_h))
        if shot_h % 2 != h % 2:
            shot_h = min(MAX_SHOT, shot_h + 1)
        cam = camera(self.lo, self.hi, view, shot_h, scale)
        path = self.work / f"{name or view}-{shot_w}x{shot_h}.png"
        self._shot(path, cam, shot_w, shot_h)
        t0 = time.monotonic()
        shot, plate = Image.open(path), Image.open(self.plate(shot_w, shot_h))
        if shot_h != h:  # crop first: the cut-out's cost follows the pixels it looks at
            top = (shot_h - h) // 2
            shot, plate = shot.crop((0, top, w, top + h)), plate.crop((0, top, w, top + h))
        im = draw.cutout(shot, plate)
        self.timings["cutout"] = self.timings.get("cutout", 0.0) + time.monotonic() - t0
        # the box's projection is centred: its edges in image px
        bx0 = (w - w_mm * scale) / 2
        by0 = (h - h_mm * scale) / 2
        info = {"view": view, "scale": scale, "size_mm": [w_mm, h_mm], "depth_mm": d_mm,
                "box_px": [bx0, by0, bx0 + w_mm * scale, by0 + h_mm * scale], "camera": cam,
                "image": [w, h], "measured_px": draw.opaque_box(im)}
        return im, info


# ---------------------------------------------------------------- scales

PAPER_PX_PER_MM = 8.0  # the views sheet is A3 at 8 px/mm (203 dpi)
# ISO 5455 recommended scales, as model mm per paper mm inverted (paper/model)
ISO_SCALES = [50, 20, 10, 5, 2, 1, 1 / 2, 1 / 5, 1 / 10, 1 / 20, 1 / 50, 1 / 100, 1 / 200, 1 / 500, 1 / 1000,
              1 / 2000, 1 / 5000, 1 / 10000]


def scale_label(ratio: float) -> str:
    """1 → '1:1', 0.5 → '1:2', 2 → '2:1'."""
    if ratio >= 1:
        return f"{ratio:g}:1"
    return f"1:{1 / ratio:g}"


def best_scale(fits: Callable[[float], bool]) -> float:
    """The largest ISO scale ratio (paper:model) at which `fits(px_per_mm)` holds."""
    for ratio in ISO_SCALES:
        if fits(ratio * PAPER_PX_PER_MM):
            return ratio
    return ISO_SCALES[-1]


# ---------------------------------------------------------------- drawings seam (SolidCraft >= 0.45)

def drawing_support(sc) -> bool:
    """True when this SolidCraft has the drawing commands (0.45+). Feature-detected through
    the command catalog (`describe_command`), never by version number."""
    try:
        sc.tool("describe_command", id="drawing.create")
        return True
    except Exception:
        return False


SheetBackend = Callable[..., list]
_BACKENDS: dict[str, SheetBackend] = {}


def register_sheet_backend(name: str, fn: SheetBackend) -> None:
    """`fn(ctx, sheet_spec) -> list[render.Output]` renders the views sheet. "screenshots" is
    built in; a "drawings" backend (drawing.create + drawing.export) is used when it is
    registered and `drawing_support(ctx.sc)` is true."""
    _BACKENDS[name] = fn


def sheet_backend(sc) -> tuple[str, SheetBackend | None]:
    if "drawings" in _BACKENDS and drawing_support(sc):
        return "drawings", _BACKENDS["drawings"]
    return "screenshots", _BACKENDS.get("screenshots")
