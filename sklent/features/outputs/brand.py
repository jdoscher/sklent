"""F23 brand presets: an optional watermark (text or a PNG mark), title card and end
card, applied only to exported copies (presets, listing packs, project pages), never to
the filed render set. Everything is off until a setting turns it on.

Settings (`jobs.register_setting`, stored with the render settings):
  outputs_brand_text      ""            watermark text, e.g. a shop name or URL
  outputs_brand_mark      False         use the uploaded PNG mark (PUT /api/outputs/brand/mark)
  outputs_brand_position  bottom-right  bottom-right | bottom-left | top-right | top-left | center
  outputs_brand_opacity   0.6           0.1 to 1
  outputs_brand_size      12            mark width (or text height × 6) as % of the image width
  outputs_brand_photos    True          also mark real print photos in packs and pages
  outputs_brand_title_card False        videos open on a title card (name, size, commit)
  outputs_brand_end_card  False         videos close on an end card (outputs_brand_card_text)
  outputs_brand_card_text ""            end-card line (shop, channel or URL)
  outputs_brand_card_seconds 1.5        each card's length

Cards use the drafting look: paper, a 1 px frame and a small title block, set in the
vendored Inter and JetBrains Mono (OFL).
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ... import jobs
from ...config import get_settings
from .common import OutputError, sha256

FONTS = Path(__file__).resolve().parents[2] / "web" / "fonts"
POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left", "center")
MAX_MARK_BYTES = 2 * 2**20

# Paper and ink for cards: the light theme's sheet, as plain colours (exported pixels,
# not UI CSS, so the web token rule doesn't apply).
PAPER = (246, 246, 244)
INK = (40, 40, 40)
RULE = (150, 150, 150)
MUTED = (110, 110, 110)


def _clamp(lo: float, hi: float, cast=float):
    def check(v: Any):
        try:
            v = cast(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"must be a number from {lo} to {hi}") from exc
        if not lo <= v <= hi:
            raise ValueError(f"must be from {lo} to {hi}")
        return v
    return check


def _text(limit: int):
    def check(v: Any) -> str:
        v = "" if v is None else str(v)
        if len(v) > limit:
            raise ValueError(f"at most {limit} characters")
        return v.strip()
    return check


def _choice(options):
    def check(v: Any) -> str:
        if v not in options:
            raise ValueError(f"must be one of {', '.join(options)}")
        return v
    return check


SETTINGS = {
    "outputs_brand_text": ("", _text(80)),
    "outputs_brand_mark": (False, bool),
    "outputs_brand_position": ("bottom-right", _choice(POSITIONS)),
    "outputs_brand_opacity": (0.6, _clamp(0.1, 1.0)),
    "outputs_brand_size": (12, _clamp(3, 40)),
    "outputs_brand_photos": (True, bool),
    "outputs_brand_title_card": (False, bool),
    "outputs_brand_end_card": (False, bool),
    "outputs_brand_card_text": ("", _text(120)),
    "outputs_brand_card_seconds": (1.5, _clamp(0.5, 5.0)),
}


def register() -> None:
    for key, (default, validate) in SETTINGS.items():
        jobs.register_setting(key, default, validate)


def mark_path() -> Path:
    return get_settings().data_dir / "outputs" / "brand" / "mark.png"


def save_mark(data: bytes) -> dict:
    """Store a PNG (or any image Pillow reads) as the brand mark, as RGBA PNG."""
    if not data:
        raise OutputError("empty upload", 422)
    if len(data) > MAX_MARK_BYTES:
        raise OutputError("the mark must be at most 2 MB", 413)
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            im = im.convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - Pillow raises many kinds
        raise OutputError(f"not an image: {exc}", 422) from exc
    if max(im.size) > 4096:
        im.thumbnail((4096, 4096))
    p = mark_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    im.save(p, "PNG")
    return mark_info()


def mark_info() -> dict | None:
    p = mark_path()
    if not p.is_file():
        return None
    with Image.open(p) as im:
        return {"width": im.width, "height": im.height, "bytes": p.stat().st_size, "sha256": sha256(p)[:16]}


def config(settings: dict | None = None) -> dict | None:
    """The brand to apply, or None when nothing is turned on."""
    s = settings if settings is not None else jobs.get_all_settings()
    cfg = {k.removeprefix("outputs_brand_"): s.get(k, d) for k, (d, _) in SETTINGS.items()}
    if cfg["mark"] and not mark_path().is_file():
        cfg["mark"] = False
    if not (cfg["text"] or cfg["mark"] or cfg["title_card"] or cfg["end_card"]):
        return None
    if cfg["mark"]:
        cfg["mark_sha"] = sha256(mark_path())[:16]
    return cfg


def has_watermark(cfg: dict | None) -> bool:
    return bool(cfg and (cfg["text"] or cfg["mark"]))


# ---------------------------------------------------------------- type

@lru_cache(maxsize=32)
def font(face: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A vendored face at a pixel size: ui (Inter), data (JetBrains Mono), display
    (Instrument Serif). Falls back to Pillow's built-in face if FreeType can't read WOFF2."""
    files = {"ui": "inter-latin-wght-normal.woff2", "data": "jetbrains-mono-latin-wght-normal.woff2",
             "display": "instrument-serif-latin-400-normal.woff2"}
    try:
        return ImageFont.truetype(str(FONTS / files[face]), size)
    except OSError:
        return ImageFont.load_default(size=size)


# ---------------------------------------------------------------- watermark

def _mark_layer(width: int, height: int, cfg: dict) -> Image.Image:
    """A transparent width × height layer holding the mark, placed and faded."""
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    margin = round(min(width, height) * 0.035)
    target_w = max(24, round(width * cfg["size"] / 100))
    if cfg["mark"]:
        with Image.open(mark_path()) as m:
            m = m.convert("RGBA")
            scale = target_w / m.width
            m = m.resize((target_w, max(1, round(m.height * scale))), Image.LANCZOS)
    else:
        px = max(10, round(target_w / 6))
        f = font("ui", px)
        box = ImageDraw.Draw(layer).textbbox((0, 0), cfg["text"], font=f)
        tw, th = int(box[2] - box[0]), int(box[3] - box[1])
        pad = max(4, px // 3)
        m = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
        d = ImageDraw.Draw(m)
        # ink on a soft paper chip: legible on the light render background and on photos
        d.rounded_rectangle((0, 0, m.width - 1, m.height - 1), radius=pad, fill=(*PAPER, 170))
        d.text((pad - box[0], pad - box[1]), cfg["text"], font=f, fill=(*INK, 255))
    alpha = m.getchannel("A").point(lambda a: round(a * cfg["opacity"]))
    m.putalpha(alpha)
    pos = cfg["position"]
    x = margin if "left" in pos else width - m.width - margin
    y = margin if "top" in pos else height - m.height - margin
    if pos == "center":
        x, y = (width - m.width) // 2, (height - m.height) // 2
    layer.alpha_composite(m, (max(0, x), max(0, y)))
    return layer


def watermark(img: Image.Image, cfg: dict | None) -> Image.Image:
    """The image with the watermark burned in (unchanged when there is none)."""
    if not has_watermark(cfg):
        return img
    base = img.convert("RGBA")
    base.alpha_composite(_mark_layer(base.width, base.height, cfg))
    return base.convert("RGB")


def overlay_png(width: int, height: int, cfg: dict, out: Path) -> Path:
    """The watermark as a full-frame RGBA PNG, for ffmpeg's overlay on videos."""
    _mark_layer(width, height, cfg).save(out, "PNG")
    return out


# ---------------------------------------------------------------- cards

def card(width: int, height: int, kind: str, info: dict, cfg: dict) -> Image.Image:
    """A title or end card: paper, a 1 px frame, the title in the display face and a
    mono line of facts (size, commit) in a small title block; the end card carries the
    brand line instead. Never drawn over a render."""
    img = Image.new("RGB", (width, height), PAPER)
    d = ImageDraw.Draw(img)
    m = round(min(width, height) * 0.05)
    d.rectangle((m, m, width - 1 - m, height - 1 - m), outline=INK, width=1)
    if kind == "title":
        title = info.get("title") or ""
        size = max(18, round(height * 0.11))
        f = font("display", size)
        while d.textlength(title, font=f) > width - 4 * m and size > 14:
            size = round(size * 0.9)
            f = font("display", size)
        d.text((2 * m, height * 0.36), title, font=f, fill=INK, anchor="ls")
        facts = "  ·  ".join(x for x in (info.get("envelope"), info.get("bodies"), info.get("commit")) if x)
        fd = font("data", max(10, round(height * 0.032)))
        # title block: a ruled strip along the bottom of the frame
        top = height - m - round(height * 0.12)
        d.line((m, top, width - 1 - m, top), fill=RULE, width=1)
        d.text((2 * m, (top + height - m) / 2), facts, font=fd, fill=INK, anchor="lm")
        if info.get("repo"):
            small = font("ui", max(10, round(height * 0.03)))
            d.text((width - 2 * m, (top + height - m) / 2), info["repo"], font=small,
                   fill=MUTED, anchor="rm")
    else:
        line = cfg.get("card_text") or cfg.get("text") or info.get("title") or ""
        if cfg.get("mark"):
            with Image.open(mark_path()) as mk:
                mk = mk.convert("RGBA")
                w = round(width * 0.22)
                mk = mk.resize((w, max(1, round(mk.height * w / mk.width))), Image.LANCZOS)
                base = img.convert("RGBA")
                base.alpha_composite(mk, ((width - mk.width) // 2, round(height * 0.42 - mk.height)))
                img = base.convert("RGB")
                d = ImageDraw.Draw(img)
        size = max(16, round(height * 0.07))
        f = font("ui", size)
        while d.textlength(line, font=f) > width - 4 * m and size > 12:
            size = round(size * 0.9)
            f = font("ui", size)
        d.text((width / 2, height * 0.58), line, font=f, fill=INK, anchor="mm")
    return img


def card_png(width: int, height: int, kind: str, info: dict, cfg: dict, out: Path) -> Path:
    card(width, height, kind, info, cfg).save(out, "PNG")
    return out
