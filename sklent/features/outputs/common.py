"""Shared plumbing for the outputs area: the design and set being exported, its listing
metadata, image helpers (finding the part in a render, cropping to an aspect), and
filing derived files into Kist.

Every exported copy lives under the set's own folder (`<set>/presets/`, `<set>/exports/`),
so it belongs to one commit and goes away with that set. Real print photos and the
brand mark are not tied to a set: they live under `<data dir>/outputs/`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from ... import db, jobs, sets
from ...config import get_settings
from ...kist import Kist, KistError

try:  # P's per-repo config (.sklent.yaml); everything works without it
    from ... import repo_config  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - depends on the integration
    repo_config = None

log = logging.getLogger("sklent.outputs")

# Variants that are documents (sheets, cards), not renders: fit them whole, never crop.
SHEET_VARIANTS = ("spec-card", "bom-sheet", "views-sheet", "dimensions", "config-lineup", "plate",
                  "contact-sheet")
VIDEO_EXT = (".mp4", ".mov", ".webm")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


class OutputError(RuntimeError):
    """A request the outputs area can't serve (bad input, nothing rendered, Kist off)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- designs and sets

def design(design_id: str) -> dict:
    return jobs.get_design(design_id)  # KeyError for an unknown id


def stem_of(d: dict) -> str:
    """The file stem the render used for this design (`jobs.slug` of the file name)."""
    name = d["path"].rsplit("/", 1)[-1]
    return jobs.slug(name.rsplit(".", 1)[0])


def the_set(design_id: str, set_id: str | None = None) -> dict:
    """The set to export (newest by default), through `sklent.sets` only."""
    design(design_id)
    s = sets.get_set(design_id, set_id)
    if s is None:
        raise OutputError("this design has no rendered set yet" if not set_id else f"no set {set_id}", 404)
    return s


def settings() -> dict[str, Any]:
    return jobs.get_all_settings()


def files_of(s: dict, variant: str | None = None, style: str | None = None) -> list[dict]:
    """The set's files, optionally by variant and style, that exist on disk."""
    out = []
    for f in s.get("files") or []:
        if variant is not None and f.get("variant") != variant:
            continue
        if style is not None and f.get("style") != style:
            continue
        if (Path(s["dir"]) / f["file"]).is_file():
            out.append(f)
    return out


def path_of(s: dict, f: dict | None) -> Path | None:
    return Path(s["dir"]) / f["file"] if f else None


def first(s: dict, *choices: tuple[str, str | None]) -> dict | None:
    """The first file matching one of (variant, style) in order."""
    for variant, style in choices:
        found = files_of(s, variant, style)
        if found:
            return found[0]
    return None


def hero_file(s: dict) -> dict | None:
    """The still that stands for the design: the shaded social square, else any still."""
    f = first(s, ("social", "shaded"), ("hires", "shaded"), ("hero", None), ("social", None), ("hires", None))
    if f:
        return f
    return next((f for f in files_of(s) if f["file"].lower().endswith(IMAGE_EXT)), None)


def still_files(s: dict) -> list[dict]:
    """Every still in the set, in a gallery order: shaded before wireframe, the built-in
    stills first, then whatever feature steps added (V's exploded/section/..., S's sheets),
    generically by variant: nothing here names another area's outputs except to order."""
    stills = [f for f in files_of(s) if f["file"].lower().endswith(IMAGE_EXT)]
    rank = {"social": 0, "hires": 1}
    style_rank = {"shaded": 0, "wireframe": 1}
    return sorted(stills, key=lambda f: (rank.get(f["variant"], 2), style_rank.get(f.get("style"), 2), f["file"]))


def commit_of(d: dict, s: dict) -> str:
    """The commit a set was rendered from. (sets.latest_set's commit_sha can carry the blob
    sha, because the design row's rendered_sha is the blob; fall back to the design's commit.)"""
    c = s.get("commit_sha") or ""
    if not c or c == s.get("blob_sha") or c == d.get("blob_sha"):
        c = d.get("commit_sha") or c
    return c or ""


def report_of(s: dict) -> dict:
    return s.get("report") or {}


def spec_of(s: dict) -> dict | None:
    """S's spec.json for this set, when the specs feature wrote one."""
    spec = sets.read_json(Path(s["dir"]), "spec.json")
    return spec if isinstance(spec, dict) else None


def bom_of(s: dict) -> list[dict] | None:
    """S's bom.json rows, when present (a list, or {rows: [...]})."""
    bom = sets.read_json(Path(s["dir"]), "bom.json")
    if isinstance(bom, dict):
        bom = bom.get("rows") or bom.get("items")
    return bom if isinstance(bom, list) and bom else None


def envelope_mm(s: dict) -> list[float] | None:
    spec = spec_of(s) or {}
    box = spec.get("bounds_mm") or report_of(s).get("bounds_mm")
    try:
        return [round(abs(box[1][i] - box[0][i]), 1) for i in range(3)]
    except (TypeError, IndexError, KeyError):
        return None


def fmt_envelope(env: list[float] | None) -> str:
    if not env:
        return ""
    return " × ".join(f"{v:.0f}" if v >= 100 else f"{v:.1f}".rstrip("0").rstrip(".") for v in env) + " mm"


# ---------------------------------------------------------------- listing metadata

META_FIELDS = ("title", "summary", "licence", "print_notes", "tags")


def repo_cfg(design_id: str) -> dict:
    """P's `.sklent.yaml` values for this design ({} without the feature or on any error)."""
    if repo_config is None:
        return {}
    try:
        cfg = repo_config.get(design_id) or {}
    except Exception as exc:  # noqa: BLE001 - a broken config never breaks an export
        log.warning("repo_config.get(%s) failed: %s", design_id, exc)
        return {}
    return cfg if isinstance(cfg, dict) else {}


def meta(design_id: str) -> dict[str, Any]:
    """Title, summary, licence, print notes and tags for exports. Each comes from, in
    order of precedence: what was typed for this design in Sklent, the repo's
    `.sklent.yaml` (title, licence/license, description/summary, print_notes, tags), then
    defaults (the file stem; the `outputs_licence` setting). `from` says which won."""
    d = design(design_id)
    cfg = repo_cfg(design_id)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM outputs_meta WHERE design_id = ?", [design_id]).fetchone()
    own = dict(row) if row else {}
    if own.get("tags"):
        own["tags"] = json.loads(own["tags"])
    repo = {
        "title": cfg.get("title"),
        "summary": cfg.get("summary") or cfg.get("description"),
        "licence": cfg.get("licence") or cfg.get("license"),
        "print_notes": cfg.get("print_notes") or cfg.get("print"),
        "tags": cfg.get("tags"),
    }
    defaults = {"title": stem_of(d), "summary": "", "licence": settings().get("outputs_licence") or "",
                "print_notes": "", "tags": []}
    out: dict[str, Any] = {"from": {}}
    for k in META_FIELDS:
        for origin, src in (("design", own), ("repo", repo), ("default", defaults)):
            v = src.get(k)
            if v not in (None, "", []):
                if k == "print_notes" and not isinstance(v, str):
                    v = "\n".join(f"{a}: {b}" for a, b in v.items()) if isinstance(v, dict) else str(v)
                if k == "tags" and isinstance(v, str):
                    v = [t.strip() for t in v.split(",") if t.strip()]
                out[k], out["from"][k] = v, origin
                break
        else:
            out[k], out["from"][k] = defaults[k], "default"
    out["hide_source"] = bool(own.get("hide_source"))
    return out


def set_meta(design_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    design(design_id)
    allowed = set(META_FIELDS) | {"hide_source"}
    bad = set(changes) - allowed
    if bad:
        raise OutputError(f"unknown fields: {', '.join(sorted(bad))}", 422)
    clean: dict[str, Any] = {}
    for k, v in changes.items():
        if k == "tags":
            if isinstance(v, str):
                v = [t.strip() for t in v.split(",") if t.strip()]
            if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
                raise OutputError("tags must be a list of strings", 422)
            clean[k] = json.dumps(v[:30])
        elif k == "hide_source":
            clean[k] = int(bool(v))
        else:
            if v is not None and not isinstance(v, str):
                raise OutputError(f"{k} must be text", 422)
            clean[k] = (v or "")[:20000] or None
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO outputs_meta (design_id, updated_at) VALUES (?, ?)", [design_id, db.now()])
        if clean:
            cols = ", ".join(f"{k} = ?" for k in clean)
            conn.execute(f"UPDATE outputs_meta SET {cols}, updated_at = ? WHERE design_id = ?",
                         [*clean.values(), db.now(), design_id])
    return meta(design_id)


# Licence ids people pick on Printables/Thingiverse/Cults, with where the full text lives.
LICENCE_URLS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
    "CC-BY-NC-SA-4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "CC-BY-ND-4.0": "https://creativecommons.org/licenses/by-nd/4.0/",
    "CC-BY-NC-ND-4.0": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "MIT": "https://opensource.org/license/mit",
    "Apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0",
    "GPL-3.0": "https://www.gnu.org/licenses/gpl-3.0.html",
    "CERN-OHL-S-2.0": "https://ohwr.org/cern_ohl_s_v2.txt",
    "CERN-OHL-W-2.0": "https://ohwr.org/cern_ohl_w_v2.txt",
    "CERN-OHL-P-2.0": "https://ohwr.org/cern_ohl_p_v2.txt",
}


def licence_text(licence: str, title: str, owner: str) -> str:
    """LICENSE.txt for a pack: a notice naming the licence and where its full text is.
    A licence that isn't a known id is taken as the licence text itself."""
    if not licence:
        return (f"{title}\n\nNo licence was set for this design. Unless the author says otherwise, "
                "all rights are reserved.\n")
    key = next((k for k in LICENCE_URLS if k.lower() == licence.strip().lower()), None)
    if key:
        return (f"{title} by {owner}\n\nLicensed under {key}.\nFull text: {LICENCE_URLS[key]}\n")
    return licence if licence.endswith("\n") else licence + "\n"


# ---------------------------------------------------------------- files

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def lock(key: str) -> threading.Lock:
    """One lock per output being built, so two requests don't encode the same file at once."""
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def key_of(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe(name: str) -> str:
    return SAFE.sub("-", name).strip("-.") or "file"


def exports_dir(s: dict) -> Path:
    p = Path(s["dir"]) / "exports"
    p.mkdir(exist_ok=True)
    return p


def export_path(s: dict, name: str) -> Path:
    """A file under the set's exports/ folder, by a plain name (no folders)."""
    if not name or name != safe(name) or name.startswith("."):
        raise OutputError("bad file name", 404)
    p = Path(s["dir"]) / "exports" / name
    if not p.is_file():
        raise OutputError(f"no export {name}", 404)
    return p


def write_zip(out: Path, entries: Iterable[tuple[str, Path | bytes | str]]) -> Path:
    """A zip from (name in zip, file path | bytes | text). Media is stored, text deflated."""
    tmp = out.with_suffix(out.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as z:
        for arc, src in entries:
            stored = isinstance(src, Path) and src.suffix.lower() in (".mp4", ".png", ".jpg", ".jpeg", ".gif",
                                                                     ".webp", ".zip", ".3mf", ".woff2")
            kind = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            if isinstance(src, Path):
                z.write(src, arc, compress_type=kind)
            else:
                z.writestr(arc, src.encode() if isinstance(src, str) else src, compress_type=kind)
    tmp.replace(out)
    return out


# ---------------------------------------------------------------- images

def load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            bg.alpha_composite(im)
            return bg.convert("RGB")
        return im.convert("RGB")


def part_box(arr: np.ndarray, threshold: int = 14) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of the part in a render, by difference from the background.

    SolidCraft's headless background is a smooth vertical gradient, so each row's
    background is the median of that row's outer columns. Rows and columns with only a
    pixel or two of difference are noise. The whole frame when nothing stands out."""
    h, w = arr.shape[:2]
    a = arr.astype(np.int16)
    edge = max(2, w // 200)
    strips = np.concatenate([a[:, :edge], a[:, -edge:]], axis=1)
    bg = np.median(strips, axis=1)  # (h, 3)
    diff = np.abs(a - bg[:, None, :]).max(axis=2)
    mask = diff > threshold
    rows = np.where(mask.sum(axis=1) > max(2, w // 800))[0]
    cols = np.where(mask.sum(axis=0) > max(2, h // 800))[0]
    if rows.size == 0 or cols.size == 0:
        return 0, 0, w, h
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def frame_window(box: tuple[int, int, int, int], aspect: float, fill: float, anchor: str = "center"
                 ) -> tuple[float, float, float, float]:
    """A window of `aspect` (w/h) around the part box where the part takes at most `fill`
    of the width and height. anchor left/right puts the part's centre on that third and
    leaves the other side free (thumbnail text space)."""
    x0, y0, x1, y1 = box
    pw, ph = max(1, x1 - x0), max(1, y1 - y0)
    fill = min(max(fill, 0.2), 1.0)
    side = 1.0 if anchor == "center" else 2 / 3
    ww = max(pw / (fill * side), ph / fill * aspect)
    wh = ww / aspect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = {"center": cx - ww / 2, "left": cx - ww / 3, "right": cx - 2 * ww / 3}.get(anchor, cx - ww / 2)
    return left, cy - wh / 2, ww, wh


def crop_pad(img: Image.Image, window: tuple[float, float, float, float], mode: str = "edge") -> Image.Image:
    """Cut a window out of an image; parts of it outside the image are filled by
    smearing the edge (renders: the gradient carries on) or with the corner colour
    (sheets: a frame line isn't smeared)."""
    left, top, ww, wh = (int(round(v)) for v in window)
    w, h = img.size
    pad_l, pad_t = max(0, -left), max(0, -top)
    pad_r, pad_b = max(0, left + ww - w), max(0, top + wh - h)
    if pad_l or pad_t or pad_r or pad_b:
        arr = np.asarray(img)
        if mode == "edge":
            arr = np.pad(arr, ((pad_t, pad_b), (pad_l, pad_r), (0, 0)), mode="edge")
        else:
            corner = arr[1, 1] if arr.shape[0] > 1 and arr.shape[1] > 1 else arr[0, 0]
            out = np.empty((h + pad_t + pad_b, w + pad_l + pad_r, 3), dtype=arr.dtype)
            out[:] = corner
            out[pad_t:pad_t + h, pad_l:pad_l + w] = arr
            arr = out
        img = Image.fromarray(arr)
        left, top = left + pad_l, top + pad_t
    return img.crop((left, top, left + ww, top + wh))


def fit_image(img: Image.Image, width: int, height: int, *, fill: float = 0.8, anchor: str = "center",
              sheet: bool = False) -> Image.Image:
    """The image at exactly width × height: a render is framed on the part (`fill`,
    `anchor`); a sheet is fitted whole with its corner colour around it."""
    aspect = width / height
    if sheet:
        w, h = img.size
        if w / h > aspect:
            ww, wh = w, w / aspect
        else:
            ww, wh = h * aspect, h
        window = ((w - ww) / 2, (h - wh) / 2, ww, wh)
        out = crop_pad(img, window, mode="corner")
    else:
        box = part_box(np.asarray(img))
        out = crop_pad(img, frame_window(box, aspect, fill, anchor), mode="edge")
    return out.resize((width, height), Image.LANCZOS)


def save_image(img: Image.Image, path: Path, fmt: str, max_bytes: int | None = None) -> dict:
    """Save as jpg/png/webp/pdf, stepping JPEG/WebP quality down to fit `max_bytes`.
    Returns {bytes, quality, fits}."""
    fmt = fmt.lower()
    img = img.convert("RGB")
    if fmt in ("png",):
        img.save(path, "PNG", optimize=True)
        n = path.stat().st_size
        return {"bytes": n, "quality": None, "fits": max_bytes is None or n <= max_bytes}
    qualities = [92, 88, 84, 80, 75, 70, 64, 58, 50, 42]
    kind = {"jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "pdf": "PDF"}[fmt]
    q = qualities[0]
    for q in qualities:
        if kind == "PDF":
            # Pillow embeds RGB as JPEG (DCTDecode) at this quality; 150 dpi page size
            img.save(path, "PDF", resolution=150.0, quality=q)
        else:
            img.save(path, kind, quality=q, optimize=True) if kind == "JPEG" else img.save(path, kind, quality=q)
        n = path.stat().st_size
        if max_bytes is None or n <= max_bytes:
            return {"bytes": n, "quality": q, "fits": True}
    return {"bytes": path.stat().st_size, "quality": q, "fits": False}


# ---------------------------------------------------------------- Kist

def kist_tags(d: dict, s: dict, variant: str, style: str | None = None) -> list[str]:
    """Kist tags in the render's scheme (jobs._render) plus `format:<variant>`."""
    palette = ((report_of(s).get("options") or {}).get("palette")) or settings().get("palette")
    tags = ["solidcraft", f"repo:{d['owner']}/{d['repo']}", f"design:{stem_of(d)}", f"palette:{palette}",
            f"format:{variant}"]
    commit = commit_of(d, s)
    if commit:
        tags.append(f"rev:{commit[:10]}")
    if style:
        tags.append(f"style:{style}")
    return tags


def kist_folder(kist: Kist, d: dict) -> str:
    if d.get("kist_folder_id"):
        return d["kist_folder_id"]
    return kist.ensure_folder([get_settings().kist_root_folder, d["owner"], d["repo"], stem_of(d)])


def kist_file(d: dict, s: dict, path: Path, variant: str, *, style: str | None = None,
              kist: Kist | None = None, extra_tags: list[str] | None = None) -> str | None:
    """File one exported copy into the design's Kist folder, once per content: the same
    file with the same bytes is not uploaded again; a rebuilt copy replaces (trashes) the
    previous upload of that file name for this set. Returns the item id, or None when
    Kist is off or the upload failed (logged; an export never fails on Kist)."""
    kist = kist or Kist()
    if not kist.enabled:
        return None
    digest = sha256(path)
    set_id = s["id"]
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM outputs_kist WHERE design_id = ? AND set_id = ? AND file = ?",
                           [d["id"], set_id, path.name]).fetchone()
    if row and row["sha256"] == digest:
        return row["item_id"]
    try:
        tags = kist_tags(d, s, variant, style) + (extra_tags or [])
        notes = f"{d['owner']}/{d['repo']}:{d['path']} at {commit_of(d, s)[:10]}, exported by sklent"
        item = kist.upload(path, folder_id=kist_folder(kist, d), tags=tags, notes=notes, source_url=d["html_url"])
        if row and row["item_id"] != item["id"]:
            kist.trash(row["item_id"])
    except (KistError, OSError, ValueError) as exc:
        log.warning("filing %s into Kist failed: %s", path.name, exc)
        return None
    except Exception as exc:  # noqa: BLE001 - httpx transport errors and the like
        log.warning("filing %s into Kist failed: %s", path.name, exc)
        return None
    with db.connect() as conn:
        conn.execute("INSERT INTO outputs_kist (design_id, set_id, file, sha256, item_id, variant, created_at) "
                     "VALUES (?,?,?,?,?,?,?) ON CONFLICT(design_id, set_id, file) DO UPDATE SET "
                     "sha256 = excluded.sha256, item_id = excluded.item_id, variant = excluded.variant",
                     [d["id"], set_id, path.name, digest, item["id"], variant, db.now()])
    return item["id"]


def kist_items_for(design_id: str, set_id: str) -> list[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT file, item_id, variant FROM outputs_kist WHERE design_id = ? AND set_id = ? ORDER BY created_at",
            [design_id, set_id]).fetchall()]


SCHEMA = """
CREATE TABLE IF NOT EXISTS outputs_meta (
    design_id TEXT PRIMARY KEY,
    title TEXT,
    summary TEXT,
    licence TEXT,
    print_notes TEXT,
    tags TEXT,
    hide_source INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outputs_kist (
    design_id TEXT NOT NULL,
    set_id TEXT NOT NULL,
    file TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    item_id TEXT NOT NULL,
    variant TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (design_id, set_id, file)
);
CREATE TABLE IF NOT EXISTS outputs_photos (
    id TEXT PRIMARY KEY,
    design_id TEXT NOT NULL,
    file TEXT NOT NULL,
    name TEXT,
    caption TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    width INTEGER,
    height INTEGER,
    bytes INTEGER,
    sha256 TEXT,
    kist_item_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outputs_photos_design ON outputs_photos(design_id, position);
CREATE TABLE IF NOT EXISTS outputs_review (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,              -- design | source
    target_id TEXT NOT NULL,
    set_id TEXT,
    board_id TEXT,
    board_name TEXT,
    items INTEGER NOT NULL DEFAULT 0,
    share_id TEXT,
    share_url TEXT,
    share_expires_at TEXT,
    proofing INTEGER NOT NULL DEFAULT 0,
    shared_at TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outputs_review_target ON outputs_review(scope, target_id, created_at);
"""
