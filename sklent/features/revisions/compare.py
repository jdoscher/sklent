"""Pixel compare between two render sets (F1): the same still, or the same turntable
frame, from both sets, and a mask of the pixels that changed.

The mask is a PNG whose alpha marks changed pixels (black, opaque) and is clear
elsewhere. The web UI uses it as a CSS mask over a block of the theme's ink colour, so
changes show in the ink colour of whichever theme is on, never in a hue; the MCP
composite paints them in near-black on a faded grey copy of the newer still.

Each set's stills are framed to that version's own bounding box, so when the envelope
changed between versions the framing differs too; `compare()` says so (`reframed`).
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ... import sets
from ...render import ffmpeg

THRESHOLD = 24  # of 255, on any channel: under this is renderer noise (the spike saw <0.07 % of pixels move)
VIDEO = (".mp4", ".gif")
INK = (24, 24, 24)


def pick(s: dict, style: str, variant: str) -> dict | None:
    return next((f for f in s["files"] if f["style"] == style and f["variant"] == variant), None)


def common_files(a: dict, b: dict) -> list[dict]:
    """(style, variant) pairs both sets have, with whether they are stills or videos."""
    have = {(f["style"], f["variant"]) for f in b["files"]}
    out = []
    for f in a["files"]:
        if (f["style"], f["variant"]) in have:
            out.append({"style": f["style"], "variant": f["variant"],
                        "kind": "video" if f["file"].lower().endswith(VIDEO) else "still"})
    return out


def _cache_dir(design_id: str) -> Path:
    d = sets.design_dir(design_id) / "_compare"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(*parts: Any) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def frame_count(s: dict, f: dict) -> int | None:
    opts = (s.get("report") or {}).get("options") or {}
    if f["file"].lower().endswith(".gif"):
        if opts.get("seconds") and opts.get("gif_fps"):
            return round(opts["seconds"] * opts["gif_fps"])
    elif opts.get("seconds") and opts.get("fps"):
        return round(opts["seconds"] * opts["fps"])
    return None


def image_of(s: dict, style: str, variant: str, frame: int | None = None) -> Path:
    """The picture to compare: a still as is, or one frame of a video (cached)."""
    f = pick(s, style, variant)
    if f is None:
        raise KeyError(f"set {s['id']} has no {style} {variant}")
    src = s["dir"] / f["file"]
    if not src.is_file():
        raise KeyError(f"set {s['id']} is missing {f['file']}")
    if not f["file"].lower().endswith(VIDEO):
        return src
    n = frame_count(s, f)
    frame = max(0, int(frame or 0))
    if n:
        frame = min(frame, n - 1)
    out = _cache_dir(s["design_id"]) / f"frame-{_key(src, src.stat().st_mtime_ns, frame)}.png"
    if not out.is_file():
        r = subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(src), "-vf",
                            f"select=eq(n\\,{frame})", "-frames:v", "1", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not out.is_file():
            raise RuntimeError(f"could not read frame {frame} of {f['file']}: {r.stderr.strip()[-300:]}")
    return out


def _load(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    with Image.open(path) as im:
        im = im.convert("RGB")
        if size and im.size != size:
            im = im.resize(size, Image.Resampling.LANCZOS)
        return np.asarray(im, dtype=np.int16)


def changed_mask(a: Path, b: Path, threshold: int = THRESHOLD) -> np.ndarray:
    """Boolean HxW at b's size: True where a and b differ by more than `threshold` on any
    channel, grown by one pixel so hairline changes stay visible."""
    with Image.open(b) as im:
        size = im.size
    pa, pb = _load(a, size), _load(b, size)
    m = (np.abs(pa - pb).max(axis=2) > threshold)
    grown = m.copy()
    grown[1:, :] |= m[:-1, :]
    grown[:-1, :] |= m[1:, :]
    grown[:, 1:] |= m[:, :-1]
    grown[:, :-1] |= m[:, 1:]
    return grown


def stats(mask: np.ndarray) -> dict[str, Any]:
    h, w = mask.shape
    changed = float(mask.mean()) if mask.size else 0.0
    ys, xs = np.nonzero(mask)
    bbox = None
    if len(xs):
        bbox = [round(xs.min() / w, 4), round(ys.min() / h, 4), round((xs.max() + 1) / w, 4),
                round((ys.max() + 1) / h, 4)]
    return {"changed": round(changed, 6), "changed_pct": round(100 * changed, 3), "bbox": bbox,
            "width": w, "height": h}


def mask_png(mask: np.ndarray, out: Path) -> Path:
    alpha = (mask * 255).astype(np.uint8)
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[..., 3] = alpha
    Image.fromarray(rgba, "RGBA").save(out, optimize=True)
    return out


def diff(a: dict, b: dict, style: str = "shaded", variant: str = "hires",
         frame: int | None = None) -> dict[str, Any]:
    """Compare set `a` (older) with `b` (newer): stats plus the mask's cache path."""
    pa, pb = image_of(a, style, variant, frame), image_of(b, style, variant, frame)
    key = _key(pa, pa.stat().st_mtime_ns, pb, pb.stat().st_mtime_ns)
    cache = _cache_dir(b["design_id"])
    out = cache / f"diff-{key}.png"
    meta = cache / f"diff-{key}.json"
    st = sets.read_json(cache, meta.name)
    if not out.is_file() or not isinstance(st, dict):
        mask = changed_mask(pa, pb)
        mask_png(mask, out)
        st = stats(mask)
        sets.write_json(cache, meta.name, st)
    return {**st, "mask": out, "a_image": pa, "b_image": pb}


def composite(a: dict, b: dict, style: str = "shaded", variant: str = "hires",
              frame: int | None = None, width: int = 1600) -> Path:
    """One PNG for an agent: older | newer | changes (ink on a faded copy of the newer)."""
    d = diff(a, b, style, variant, frame)
    out = d["mask"].with_name(d["mask"].stem.replace("diff-", "composite-") + f"-{width}.png")
    if out.is_file():
        return out
    with Image.open(d["b_image"]) as im:
        size = im.size
    pa, pb = _load(d["a_image"], size).astype(np.uint8), _load(d["b_image"], size).astype(np.uint8)
    with Image.open(d["mask"]) as m:
        mask = np.asarray(m)[..., 3] > 0
    grey = pb.mean(axis=2, keepdims=True)
    faded = (255 - (255 - grey) * 0.25).repeat(3, axis=2).astype(np.uint8)
    faded[mask] = INK
    gap = max(8, size[0] // 80)
    canvas = Image.new("RGB", (size[0] * 3 + gap * 2, size[1]), (255, 255, 255))
    for i, arr in enumerate((pa, pb, faded)):
        canvas.paste(Image.fromarray(arr, "RGB"), (i * (size[0] + gap), 0))
    canvas.thumbnail((width, width))
    canvas.save(out, optimize=True)
    return out


def reframed(a: dict, b: dict) -> bool:
    """True when the two versions' envelopes differ, so their stills are framed differently."""
    ba = (a.get("report") or {}).get("bounds_mm")
    bb = (b.get("report") or {}).get("bounds_mm")
    if not ba or not bb:
        return False
    return any(abs(x - y) > 1e-3 for ca, cb in zip(ba, bb, strict=False) for x, y in zip(ca, cb, strict=False))
