"""Part colours. Renders are always cool grey or white, never a design's own colours.

Two layers make that a guarantee rather than a hope:

1. Before rendering, every body is painted with the palette's colour (`paint`), which
   overrides body, component and material looks.
2. After rendering, `clamp` desaturates any pixel that is still noticeably coloured
   (per-face paint, imported STEP face colours, anything SolidCraft adds later) into the
   palette's cool grey. The background gradient and the palette colours sit well under
   the threshold, so on a normal render it changes nothing.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Palette:
    name: str
    label: str
    shaded: str  # solid body colour
    wireframe: str  # see-through body tint behind the edges


PALETTES = {
    "cool-grey": Palette("cool-grey", "Cool grey", shaded="#a7b0ba", wireframe="#8a96a3"),
    "white": Palette("white", "White", shaded="#e9edf1", wireframe="#c9d1da"),
}

# Chroma (max channel − min channel, 0..1) above this counts as colour. Absolute chroma,
# not HSV saturation: SolidCraft's dark slate edge lines (40, 44, 52) have a high relative
# saturation but almost no colour. Reference points: edges 0.05, both palettes and the
# background gradient ≤ 0.08; pale pink 0.16, pale yellow 0.24, red 0.67.
CHROMA_LIMIT = 0.12
# The cool cast a clamped pixel keeps, so it sits with the rest of the grey render.
COOL_TINT = np.array([0.97, 1.0, 1.05], dtype=np.float32)


def get(name: str) -> Palette:
    try:
        return PALETTES[name]
    except KeyError:
        raise ValueError(f"palette must be one of {', '.join(PALETTES)}") from None


def _saturated(rgb: np.ndarray) -> np.ndarray:
    return (rgb.max(axis=2) - rgb.min(axis=2)) > CHROMA_LIMIT


def colour_fraction(path: Path) -> float:
    """Share of pixels that are visibly coloured (0..1)."""
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    return float(_saturated(rgb).mean())


def clamp(path: Path) -> float:
    """Desaturate coloured pixels in place; returns the share of pixels changed."""
    with Image.open(path) as im:
        mode = im.mode
        arr = np.asarray(im.convert("RGBA" if "A" in mode else "RGB"), dtype=np.float32) / 255.0
    rgb = arr[..., :3]
    mask = _saturated(rgb)
    share = float(mask.mean())
    if share == 0:
        return 0.0
    luma = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    grey = np.clip(luma[..., None] * COOL_TINT, 0, 1)
    rgb[mask] = grey[mask]
    out = (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
    Image.fromarray(out, "RGBA" if arr.shape[2] == 4 else "RGB").save(path)
    return share
