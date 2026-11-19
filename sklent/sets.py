"""Render sets on disk: the one place features look sets up.

A render set is a folder `<renders_dir>/<design id>/<blob12>/` holding the files listed
in the design's `files` and a `report.json`. Phase-2 features read sets through these
helpers only, so revision history (F1, which keeps older sets) can change how sets are
stored and listed without touching every feature.

Owned by the revisions feature (f-revisions). It may add functions and extend
`list_sets`/`get_set`, but these signatures stay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import db
from .service import render_folder


def _design(design_id: str) -> dict | None:
    with db.connect() as conn:
        return db.row(conn.execute("SELECT * FROM designs WHERE id = ?", [design_id]).fetchone())


def latest_set(design_id: str) -> dict[str, Any] | None:
    """The newest set: {id, design_id, dir: Path, files: [Output dicts], report: dict | None,
    commit_sha, blob_sha, rendered_at}. None before a first render."""
    d = _design(design_id)
    if not d or not d.get("render_dir"):
        return None
    folder = render_folder(d)
    if folder is None or not folder.is_dir():
        return None
    return {
        "id": folder.name,
        "design_id": design_id,
        "dir": folder,
        "files": d.get("files") or [],
        "report": read_json(folder, "report.json"),
        "commit_sha": d.get("rendered_sha") or d.get("commit_sha"),
        "blob_sha": d.get("blob_sha"),
        "rendered_at": d.get("rendered_at"),
    }


def get_set(design_id: str, set_id: str | None = None) -> dict[str, Any] | None:
    """A set by id (its folder name); None or "latest" means the newest."""
    if set_id in (None, "", "latest"):
        return latest_set(design_id)
    for s in list_sets(design_id):
        if s["id"] == set_id:
            return s
    return None


def list_sets(design_id: str) -> list[dict[str, Any]]:
    """Every kept set, newest first. Before F1, only the newest set is kept."""
    s = latest_set(design_id)
    return [s] if s else []


def read_json(folder: Path, name: str) -> Any:
    p = folder / name
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def write_json(folder: Path, name: str, data: Any) -> Path:
    p = folder / name
    p.write_text(json.dumps(data, indent=2))
    return p
