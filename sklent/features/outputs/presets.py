"""F6 output presets: named size and aspect profiles cut from a render set on demand
(Pillow for stills, ffmpeg for clips), cached in the set's folder under `presets/`.

A preset is {name, label, width, height, format, max_mb, fill, anchor, seconds, enabled}:
- format: jpg | png | webp | pdf (a still) or mp4 | gif (the turntable, silent)
- max_mb: the site's upload cap; quality (stills) or bitrate (clips) steps down to fit
- fill: the most of the frame's width or height the part may take (0.2 to 1)
- anchor: center, or left/right to keep the part on one third (space for thumbnail text)
- seconds: clip length cap (the turntable's own length when empty)

The defaults and where their numbers come from (checked 2026-11-18):
- Printables / MakerWorld cover, 4:3 at 2000 px wide: Printables' cover is 4:3, people
  upload 2000 px wide (forum.prusa3d.com "Printables model cover photo aspect ratio
  question"); MakerWorld's web cover crops a 4:3 picture further, so the part keeps a
  wide margin (forum.bambulab.com "What's the correct photo size/aspect ratio for
  MakerWorld", r/BambuLab 1cufv9i).
- Cults video: at most 800×800 and under 10 MB (cults3d.com/en/pages/advice-publishing-3d-file).
- YouTube thumbnail: 1280×720, under 2 MB (support.google.com/youtube/answer/72431; Hopper HQ).
- LinkedIn 4:5: 1080×1350 (sendible.com/insights/linkedin-post-size).
- GitHub social preview: 1280×640, under 1 MB (docs.github.com, "Customizing your
  repository's social media preview").
- Handshake documents: 1 MB or less (support.joinhandshake.com/hc/en-us/articles/218692648),
  so a one-page PDF of the hero still.
- Instagram portrait 4:5: 1080×1350 (help.instagram.com/1631821640426723).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import brand, media
from .common import (
    OutputError,
    commit_of,
    design,
    exports_dir,
    key_of,
    kist_file,
    lock,
    meta,
    settings,
    stem_of,
    the_set,
    write_zip,
)

STILL_FORMATS = ("jpg", "png", "webp", "pdf")
CLIP_FORMATS = ("mp4", "gif")
ANCHORS = ("center", "left", "right")

DEFAULT_PRESETS: list[dict[str, Any]] = [
    {"name": "cover-4x3", "label": "Printables / MakerWorld cover", "width": 2000, "height": 1500,
     "format": "jpg", "max_mb": None, "fill": 0.72, "anchor": "center", "seconds": None, "enabled": True},
    {"name": "cults-800", "label": "Cults video", "width": 800, "height": 800, "format": "mp4",
     "max_mb": 10, "fill": 0.85, "anchor": "center", "seconds": None, "enabled": True},
    {"name": "youtube-thumb", "label": "YouTube thumbnail", "width": 1280, "height": 720, "format": "jpg",
     "max_mb": 2, "fill": 0.85, "anchor": "left", "seconds": None, "enabled": True},
    {"name": "linkedin-4x5", "label": "LinkedIn 4:5", "width": 1080, "height": 1350, "format": "jpg",
     "max_mb": None, "fill": 0.8, "anchor": "center", "seconds": None, "enabled": True},
    {"name": "github-social", "label": "GitHub social preview", "width": 1280, "height": 640, "format": "jpg",
     "max_mb": 1, "fill": 0.8, "anchor": "center", "seconds": None, "enabled": True},
    {"name": "handshake", "label": "Handshake (PDF, 1 MB)", "width": 1650, "height": 1275, "format": "pdf",
     "max_mb": 1, "fill": 0.75, "anchor": "center", "seconds": None, "enabled": True},
    {"name": "instagram-4x5", "label": "Instagram 4:5", "width": 1080, "height": 1350, "format": "jpg",
     "max_mb": None, "fill": 0.8, "anchor": "center", "seconds": None, "enabled": True},
]

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _clean_one(p: Any) -> dict[str, Any]:
    if not isinstance(p, dict):
        raise ValueError("each preset is an object")
    name = str(p.get("name", "")).strip().lower()
    if not NAME.match(name):
        raise ValueError(f"preset name {name!r}: lowercase letters, digits and dashes, up to 40")
    fmt = str(p.get("format", "jpg")).lower().replace("jpeg", "jpg")
    if fmt not in STILL_FORMATS + CLIP_FORMATS:
        raise ValueError(f"{name}: format must be one of {', '.join(STILL_FORMATS + CLIP_FORMATS)}")
    try:
        width, height = int(p.get("width")), int(p.get("height"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: width and height are whole pixels") from exc
    top = 1920 if fmt in CLIP_FORMATS else 8192
    if not (64 <= width <= top and 64 <= height <= top):
        raise ValueError(f"{name}: width and height must be 64 to {top} px")
    max_mb = p.get("max_mb")
    if max_mb in ("", None):
        max_mb = None
    else:
        max_mb = float(max_mb)
        if not 0.05 <= max_mb <= 500:
            raise ValueError(f"{name}: max_mb must be 0.05 to 500")
    fill = float(p.get("fill") or 0.8)
    if not 0.2 <= fill <= 1:
        raise ValueError(f"{name}: fill must be 0.2 to 1")
    anchor = p.get("anchor") or "center"
    if anchor not in ANCHORS:
        raise ValueError(f"{name}: anchor must be center, left or right")
    seconds = p.get("seconds")
    seconds = None if seconds in ("", None) else float(seconds)
    if seconds is not None and not 1 <= seconds <= 60:
        raise ValueError(f"{name}: seconds must be 1 to 60")
    label = str(p.get("label") or name)[:60]
    return {"name": name, "label": label, "width": width, "height": height, "format": fmt, "max_mb": max_mb,
            "fill": round(fill, 3), "anchor": anchor, "seconds": seconds, "enabled": bool(p.get("enabled", True))}


def validate(value: Any) -> list[dict[str, Any]]:
    """The `outputs_presets` setting: a list of presets (or its JSON text)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError("outputs_presets must be a list of presets") from exc
    if not isinstance(value, list) or len(value) > 40:
        raise ValueError("outputs_presets must be a list of up to 40 presets")
    out = [_clean_one(p) for p in value]
    names = [p["name"] for p in out]
    if len(set(names)) != len(names):
        raise ValueError("preset names must be unique")
    return out


def all_presets() -> list[dict[str, Any]]:
    return settings().get("outputs_presets") or DEFAULT_PRESETS


def get_preset(name: str) -> dict[str, Any]:
    p = next((p for p in all_presets() if p["name"] == name), None)
    if p is None:
        raise OutputError(f"no preset {name}", 404)
    return p


def _dir(s: dict) -> Path:
    d = Path(s["dir"]) / "presets"
    d.mkdir(exist_ok=True)
    return d


def _index(s: dict) -> dict:
    try:
        return json.loads((_dir(s) / "index.json").read_text())
    except (OSError, ValueError):
        return {}


def _save_index(s: dict, idx: dict) -> None:
    (_dir(s) / "index.json").write_text(json.dumps(idx, indent=2))


def file_name(d: dict, p: dict) -> str:
    return f"{stem_of(d)}-{p['name']}-{p['width']}x{p['height']}.{p['format']}"


def entry(design_id: str, set_id: str | None, p: dict, made: dict | None) -> dict:
    url = f"/api/designs/{design_id}/outputs/presets/{p['name']}/file"
    if set_id:
        url += f"?set_id={set_id}"
    return {**p, "made": bool(made), "url": url if made else None, "file": made.get("file") if made else None,
            "bytes": made.get("bytes") if made else None, "fits": made.get("fits") if made else None,
            "kist_item_id": made.get("kist_item_id") if made else None}


def list_for(design_id: str, set_id: str | None = None) -> dict:
    s = the_set(design_id, set_id)
    idx = _index(s)
    cfg = brand.config()
    out = []
    for p in all_presets():
        made = idx.get(p["name"])
        if made and (made.get("key") != _key(s, p, cfg) or not (_dir(s) / made["file"]).is_file()):
            made = None
        out.append(entry(design_id, set_id, p, made))
    return {"design_id": design_id, "set_id": s["id"], "brand": bool(cfg), "presets": out}


def _key(s: dict, p: dict, cfg: dict | None) -> str:
    return key_of(p, cfg, s.get("blob_sha"), s.get("rendered_at"))


def make(design_id: str, name: str, set_id: str | None = None) -> dict:
    """Make one preset (or reuse the cached copy), file it into Kist when Kist is on,
    and return its entry: {..preset, made, url, file, bytes, fits}."""
    d = design(design_id)
    s = the_set(design_id, set_id)
    p = get_preset(name)
    cfg = brand.config()
    key = _key(s, p, cfg)
    with lock(f"preset:{s['dir']}:{name}"):
        idx = _index(s)
        made = idx.get(name)
        out = _dir(s) / file_name(d, p)
        if not (made and made.get("key") == key and out.is_file()):
            max_bytes = int(p["max_mb"] * 1e6) if p["max_mb"] else None
            aspect = p["width"] / p["height"]
            if p["format"] in CLIP_FORMATS:
                src = media.video_source(s, aspect)
                fps = ((s.get("report") or {}).get("options") or {}).get("fps") or 30
                res = media.derive_clip(src, out, p["width"], p["height"], p["format"], max_bytes=max_bytes,
                                        fill=p["fill"], seconds=p["seconds"], fps=fps, cfg=cfg,
                                        info=media.card_info(d, s, meta(design_id)["title"]))
            else:
                src, sheet = media.still_source(s, aspect)
                res = media.derive_still(src, out, p["width"], p["height"], p["format"], max_bytes=max_bytes,
                                         fill=p["fill"], anchor=p["anchor"], sheet=sheet, cfg=cfg)
            if made and made.get("file") != out.name:
                (_dir(s) / made["file"]).unlink(missing_ok=True)
            made = {**res, "file": out.name, "key": key}
            idx[name] = made
            _save_index(s, idx)
        item = kist_file(d, s, out, f"size-{name}")
        if item and made.get("kist_item_id") != item:
            made["kist_item_id"] = item
            idx = _index(s)
            idx[name] = made
            _save_index(s, idx)
    return entry(design_id, set_id, p, made)


def file_path(design_id: str, name: str, set_id: str | None = None) -> Path:
    e = make(design_id, name, set_id)
    s = the_set(design_id, set_id)
    return _dir(s) / e["file"]


def zip_all(design_id: str, set_id: str | None = None, with_set: bool = False) -> Path:
    """"Download all": every enabled preset (made now if missing) in one zip, plus the
    set's own files with `with_set`."""
    d = design(design_id)
    s = the_set(design_id, set_id)
    entries: list[tuple[str, Path | str]] = []
    made = []
    for p in all_presets():
        if not p["enabled"]:
            continue
        e = make(design_id, p["name"], set_id)
        made.append(e)
        entries.append((f"presets/{e['file']}", _dir(s) / e["file"]))
    if with_set:
        for f in s.get("files") or []:
            src = Path(s["dir"]) / f["file"]
            if src.is_file():
                entries.append((f"set/{f['file']}", src))
    summary = {"design": f"{d['owner']}/{d['repo']}:{d['path']}", "commit": commit_of(d, s),
               "presets": [{k: e[k] for k in ("name", "label", "file", "width", "height", "format", "bytes", "max_mb",
                                               "fits")} for e in made]}
    entries.append(("presets.json", json.dumps(summary, indent=2)))
    suffix = "-all" if with_set else "-presets"
    return write_zip(exports_dir(s) / f"{stem_of(d)}{suffix}.zip", entries)
