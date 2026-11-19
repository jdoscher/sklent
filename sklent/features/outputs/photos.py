"""F19 real photo slots: photos of the actual print, uploaded per design, kept in the
data dir (and filed into Kist when Kist is on, tagged `kind:photo`), ordered first in
listing packs and project pages. Photos are never repainted or cropped; EXIF (GPS
included) is dropped when they're stored, with the camera's rotation applied first.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

from ... import db
from ...config import get_settings
from ...kist import Kist
from .common import OutputError, design, kist_folder, kist_tags, log, sha256

MAX_BYTES = 30 * 2**20
MAX_PHOTOS = 40
KINDS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def folder(design_id: str) -> Path:
    p = get_settings().data_dir / "outputs" / "photos" / design_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _out(r: dict) -> dict:
    return {**{k: r[k] for k in ("id", "design_id", "name", "caption", "position", "width", "height", "bytes",
                                 "kist_item_id", "created_at")},
            "url": f"/api/designs/{r['design_id']}/outputs/photos/{r['id']}/file"}


def list_photos(design_id: str) -> list[dict]:
    design(design_id)
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM outputs_photos WHERE design_id = ? ORDER BY position, created_at",
                            [design_id]).fetchall()
    return [_out(dict(r)) for r in rows]


def photo_paths(design_id: str) -> list[tuple[dict, Path]]:
    """(photo, file) in order, skipping any whose file went missing."""
    out = []
    for p in list_photos(design_id):
        with db.connect() as conn:
            f = conn.execute("SELECT file FROM outputs_photos WHERE id = ?", [p["id"]]).fetchone()["file"]
        path = folder(design_id) / f
        if path.is_file():
            out.append((p, path))
    return out


def add_photo(design_id: str, data: bytes, name: str = "", caption: str = "") -> dict:
    d = design(design_id)
    if not data:
        raise OutputError("empty upload", 422)
    if len(data) > MAX_BYTES:
        raise OutputError("a photo must be at most 30 MB", 413)
    if len(list_photos(design_id)) >= MAX_PHOTOS:
        raise OutputError(f"at most {MAX_PHOTOS} photos per design", 409)
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.load()
            im = ImageOps.exif_transpose(im)
    except Exception as exc:  # noqa: BLE001
        raise OutputError(f"not an image Sklent can read (JPEG, PNG or WebP): {exc}", 422) from exc
    if fmt not in KINDS:
        raise OutputError("photos must be JPEG, PNG or WebP", 415)
    ext = KINDS[fmt]
    pid = db.new_id()
    path = folder(design_id) / f"{pid}.{ext}"
    # re-encoding drops EXIF, GPS included; JPEG at high quality keeps the photo honest
    if ext == "jpg":
        im.convert("RGB").save(path, "JPEG", quality=94)
    elif ext == "png":
        im.save(path, "PNG")
    else:
        im.save(path, "WEBP", quality=94)
    with db.connect() as conn:
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM outputs_photos WHERE design_id = ?",
                           [design_id]).fetchone()[0]
        conn.execute("INSERT INTO outputs_photos (id, design_id, file, name, caption, position, width, height, bytes,"
                     " sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     [pid, design_id, path.name, (name or path.name)[:200], (caption or "")[:500], pos, im.width,
                      im.height, path.stat().st_size, sha256(path), db.now()])
    _file_in_kist(d, pid, path)
    return next(p for p in list_photos(design_id) if p["id"] == pid)


def _file_in_kist(d: dict, pid: str, path: Path) -> None:
    kist = Kist()
    if not kist.enabled:
        return
    try:
        s = {"id": "photos", "commit_sha": d.get("commit_sha"), "report": None}
        tags = [t for t in kist_tags(d, s, "photo") if not t.startswith(("palette:", "rev:"))] + ["kind:photo"]
        item = kist.upload(path, folder_id=kist_folder(kist, d), tags=tags,
                           notes=f"Real print photo of {d['owner']}/{d['repo']}:{d['path']}, attached in sklent",
                           source_url=d["html_url"])
    except Exception as exc:  # noqa: BLE001 - Kist is optional
        log.warning("filing photo %s into Kist failed: %s", pid, exc)
        return
    with db.connect() as conn:
        conn.execute("UPDATE outputs_photos SET kist_item_id = ? WHERE id = ?", [item["id"], pid])


def _row(design_id: str, pid: str) -> dict:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM outputs_photos WHERE id = ? AND design_id = ?", [pid, design_id]).fetchone()
    if r is None:
        raise OutputError(f"no photo {pid}", 404)
    return dict(r)


def photo_file(design_id: str, pid: str) -> Path:
    r = _row(design_id, pid)
    p = folder(design_id) / r["file"]
    if not p.is_file():
        raise OutputError("the photo's file is missing", 404)
    return p


def update_photo(design_id: str, pid: str, caption: str | None = None, position: int | None = None) -> list[dict]:
    """Change a caption, or move a photo to `position` (0 = first) and renumber the rest."""
    _row(design_id, pid)
    with db.connect() as conn:
        if caption is not None:
            conn.execute("UPDATE outputs_photos SET caption = ? WHERE id = ?", [caption[:500], pid])
        if position is not None:
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM outputs_photos WHERE design_id = ? ORDER BY position, created_at", [design_id])]
            ids.remove(pid)
            ids.insert(max(0, min(int(position), len(ids))), pid)
            for i, x in enumerate(ids):
                conn.execute("UPDATE outputs_photos SET position = ? WHERE id = ?", [i, x])
    return list_photos(design_id)


def delete_photo(design_id: str, pid: str) -> None:
    r = _row(design_id, pid)
    (folder(design_id) / r["file"]).unlink(missing_ok=True)
    with db.connect() as conn:
        conn.execute("DELETE FROM outputs_photos WHERE id = ?", [pid])
    if r.get("kist_item_id"):
        kist = Kist()
        if kist.enabled:
            try:
                kist.trash(r["kist_item_id"])  # restorable from Kist's trash
            except Exception as exc:  # noqa: BLE001
                log.warning("trashing photo %s in Kist failed: %s", pid, exc)


def counts() -> dict[str, int]:
    with db.connect() as conn:
        return {r[0]: r[1] for r in conn.execute("SELECT design_id, COUNT(*) FROM outputs_photos GROUP BY 1")}
