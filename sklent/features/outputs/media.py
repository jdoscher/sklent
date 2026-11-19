"""Derived media: stills and clips cut from a render set to a target size, framed on the
part, with the brand applied. Used by output presets (F6), listing packs (F13) and
project pages (F5). Pillow for stills, ffmpeg for clips; nothing calls SolidCraft.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import brand
from .common import (
    SHEET_VARIANTS,
    OutputError,
    commit_of,
    envelope_mm,
    files_of,
    first,
    fit_image,
    fmt_envelope,
    frame_window,
    load_rgb,
    part_box,
    path_of,
    report_of,
    save_image,
    still_files,
)


def _ff(*args: str) -> None:
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise OutputError(f"ffmpeg failed: {r.stderr.strip()[-600:]}", 500)


def card_info(d: dict, s: dict, title: str) -> dict:
    r = report_of(s)
    bodies = r.get("bodies")
    return {"title": title, "envelope": fmt_envelope(envelope_mm(s)),
            "bodies": f"{bodies:,} {'body' if bodies == 1 else 'bodies'}" if bodies else "",
            "commit": commit_of(d, s)[:10], "repo": f"{d['owner']}/{d['repo']}"}


# ---------------------------------------------------------------- stills

def still_source(s: dict, aspect: float) -> tuple[Path, bool]:
    """The best still to cut a target aspect from: the shaded square for squarish and
    portrait targets, the 16:9 high-res still for wide ones. (path, is_sheet)."""
    square = first(s, ("social", "shaded"), ("social", None))
    wide = first(s, ("hires", "shaded"), ("hires", None))
    pick = (wide or square) if aspect >= 1.4 else (square or wide)
    if pick is None:
        stills = still_files(s)
        if not stills:
            raise OutputError("the set has no still to work from", 404)
        pick = stills[0]
    return path_of(s, pick), pick["variant"] in SHEET_VARIANTS  # type: ignore[return-value]


def derive_still(src: Path, out: Path, width: int, height: int, fmt: str, *, max_bytes: int | None = None,
                 fill: float = 0.8, anchor: str = "center", sheet: bool = False, cfg: dict | None = None,
                 photo: bool = False) -> dict:
    img = fit_image(load_rgb(src), width, height, fill=fill, anchor=anchor, sheet=sheet or photo)
    if cfg and (not photo or cfg.get("photos", True)):
        img = brand.watermark(img, cfg)
    saved = save_image(img, out, fmt, max_bytes)
    return {"file": out.name, "width": width, "height": height, **saved}


def resize_photo(src: Path, out: Path, *, min_short: int | None = None, max_long: int = 4000,
                 fmt: str = "jpg", max_bytes: int | None = None, cfg: dict | None = None) -> dict:
    """A real photo for a pack: never cropped or repainted, only scaled down to
    `max_long`, EXIF dropped (no GPS leaves), and watermarked if the brand says so."""
    img = load_rgb(src)
    if max(img.size) > max_long:
        img.thumbnail((max_long, max_long), Image.LANCZOS)
    if cfg and cfg.get("photos", True):
        img = brand.watermark(img, cfg)
    saved = save_image(img, out, fmt, max_bytes)
    short = min(img.size)
    return {"file": out.name, "width": img.width, "height": img.height, **saved,
            "fits": saved["fits"] and (min_short is None or short >= min_short)}


# ---------------------------------------------------------------- clips

def video_source(s: dict, aspect: float) -> Path:
    land = first(s, ("1080p", "shaded"), ("1080p", None))
    vert = first(s, ("reel", "shaded"), ("reel", None))
    pick = (vert or land) if aspect < 0.8 else (land or vert)
    if pick is None:
        anyv = next((f for f in files_of(s) if f["file"].lower().endswith(".mp4")), None)
        if anyv is None:
            raise OutputError("the set has no turntable video to work from", 404)
        pick = anyv
    return path_of(s, pick)  # type: ignore[return-value]


def _probe(src: Path) -> tuple[int, int, float]:
    """Width, height and duration from ffmpeg's own banner (ffprobe isn't always installed)."""
    import re
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src)], capture_output=True, text=True)
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr)
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not size:
        raise OutputError(f"can't read {src.name}: {r.stderr.strip()[-200:]}", 500)
    seconds = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]) if dur else 0.0
    return int(size[1]), int(size[2]), seconds


def motion_box(src: Path, w: int, h: int) -> tuple[int, int, int, int]:
    """The part's box over the whole clip: the union of the boxes of frames sampled
    twice a second (a turntable sweeps a wider box than any one frame)."""
    with tempfile.TemporaryDirectory(prefix="sk-out-") as tmp:
        _ff("-i", str(src), "-vf", "fps=2,scale=iw/4:-2", str(Path(tmp) / "s%03d.png"))
        boxes = []
        for p in sorted(Path(tmp).glob("s*.png")):
            arr = np.asarray(Image.open(p).convert("RGB"))
            sx, sy = w / arr.shape[1], h / arr.shape[0]
            x0, y0, x1, y1 = part_box(arr)
            boxes.append((x0 * sx, y0 * sy, x1 * sx, y1 * sy))
    if not boxes:
        return 0, 0, w, h
    return (int(min(b[0] for b in boxes)), int(min(b[1] for b in boxes)),
            int(max(b[2] for b in boxes)) + 1, int(max(b[3] for b in boxes)) + 1)


def _frame_filter(w: int, h: int, window: tuple[float, float, float, float], width: int, height: int,
                  fps: int) -> str:
    left, top, ww, wh = (int(round(v)) for v in window)
    pl, pt = max(0, -left), max(0, -top)
    pr, pb = max(0, left + ww - w), max(0, top + wh - h)
    chain = ["format=gbrp"]
    if pl or pt or pr or pb:
        # extend the canvas, then smear the edge pixels into it (the background gradient
        # carries on instead of a flat border)
        chain.append(f"pad=w=iw+{pl + pr}:h=ih+{pt + pb}:x={pl}:y={pt}")
        chain.append(f"fillborders=left={pl}:right={pr}:top={pt}:bottom={pb}:mode=smear")
    chain.append(f"crop={ww}:{wh}:{left + pl}:{top + pt}")
    chain.append(f"scale={width}:{height}:flags=lanczos,setsar=1,fps={fps}")
    return ",".join(chain)


def derive_clip(src: Path, out: Path, width: int, height: int, fmt: str, *, max_bytes: int | None = None,
                fill: float = 0.85, seconds: float | None = None, fps: int | None = None,
                cfg: dict | None = None, info: dict | None = None, gif_fps: int = 15) -> dict:
    """An MP4 (silent, H.264) or GIF of the turntable at width × height, framed on the
    part's box over the clip, trimmed to `seconds`, with the brand's watermark and cards,
    and stepped down until it fits `max_bytes`."""
    w, h, duration = _probe(src)
    fps = fps or 30
    clip = min(duration or seconds or 8.0, seconds or duration or 8.0)
    window = frame_window(motion_box(src, w, h), width / height, fill)
    width, height = width - width % 2, height - height % 2
    with tempfile.TemporaryDirectory(prefix="sk-out-") as tmp:
        tmpd = Path(tmp)
        inputs = ["-t", f"{clip:.3f}", "-i", str(src)]
        graph = [f"[0:v]{_frame_filter(w, h, window, width, height, fps)}[m]"]
        last = "m"
        n = 1
        if brand.has_watermark(cfg):
            inputs += ["-i", str(brand.overlay_png(width, height, cfg, tmpd / "wm.png"))]  # type: ignore[arg-type]
            graph.append(f"[{last}][{n}:v]overlay=0:0,format=yuv420p[w]")
            last, n = "w", n + 1
        else:
            graph.append(f"[{last}]format=yuv420p[w]")
            last = "w"
        parts = []
        total = clip
        for kind in ("title", "end"):
            if cfg and cfg.get(f"{kind}_card"):
                card = brand.card_png(width, height, kind, info or {}, cfg, tmpd / f"{kind}.png")
                secs = float(cfg.get("card_seconds", 1.5))
                inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{secs:.3f}", "-i", str(card)]
                graph.append(f"[{n}:v]scale={width}:{height},setsar=1,fps={fps},format=yuv420p[c{kind}]")
                parts.append((kind, f"c{kind}"))
                total += secs
                n += 1
        if parts:
            order = [p for k, p in parts if k == "title"] + [last] + [p for k, p in parts if k == "end"]
            graph.append("".join(f"[{p}]" for p in order) + f"concat=n={len(order)}:v=1:a=0[out]")
            last = "out"
        if fmt == "gif":
            return _gif(inputs, graph, last, out, width, height, max_bytes, gif_fps)
        kbps = None
        if max_bytes:
            kbps = int(max_bytes * 8 / 1000 / max(total, 0.5) * 0.88)
        for _attempt in range(4):
            args = [*inputs, "-filter_complex", ";".join(graph), "-map", f"[{last}]", "-an",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-preset", "slow"]
            if kbps:
                args += ["-crf", "20", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k"]
            else:
                args += ["-crf", "18"]
            _ff(*args, str(out))
            size = out.stat().st_size
            if not max_bytes or size <= max_bytes or not kbps:
                break
            kbps = int(kbps * 0.75 * max_bytes / size)
        size = out.stat().st_size
        return {"file": out.name, "width": width, "height": height, "bytes": size, "seconds": round(total, 2),
                "fits": not max_bytes or size <= max_bytes}


def _gif(inputs: list[str], graph: list[str], last: str, out: Path, width: int, height: int,
         max_bytes: int | None, gif_fps: int) -> dict:
    gw, gfps = width, gif_fps
    for _ in range(5):
        g = [*graph, f"[{last}]fps={gfps},scale={gw}:-1:flags=lanczos,split[a][b];"
                     "[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4[g]"]
        _ff(*inputs, "-filter_complex", ";".join(g), "-map", "[g]", str(out))
        size = out.stat().st_size
        if not max_bytes or size <= max_bytes:
            break
        gw, gfps = max(160, int(gw * 0.8)) // 2 * 2, max(8, gfps - 2)
    size = out.stat().st_size
    return {"file": out.name, "width": gw, "height": round(gw * height / width), "bytes": size,
            "fits": not max_bytes or size <= max_bytes}


def copy_file(src: Path, out: Path) -> Path:
    shutil.copyfile(src, out)
    return out
