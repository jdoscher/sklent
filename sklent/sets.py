"""Render sets on disk: the one place features look sets up.

A render set is a folder `<renders_dir>/<design id>/<blob12>/` holding the files listed
in its `set.json` (and, for the newest set, the design's `files`) and a `report.json`.
Since revision history (F1) every rendered version of a design keeps its own set, one per
blob (a commit that didn't change the file renders nothing new). Phase-2 features read
sets through these helpers only.

Owned by the revisions feature (f-revisions). The signatures of `latest_set`, `get_set`,
`list_sets`, `read_json` and `write_json` stay.

A set dict:
    {id, design_id, dir: Path, files: [Output dicts], report: dict | None,
     commit_sha, blob_sha, rendered_at, commit: {sha, message, author, date} | None,
     tags: [git tag names whose tree holds this blob], kist_items: [{id, file, ...}],
     kist_folder_id, current: bool}

`set.json` in each folder holds the same minus `dir`, `report` and `current`. Sets from
before F1 have no `set.json`; the design row describes the newest one, and the render
that replaces it writes one (`ensure_meta`).

Folders whose names start with `.` (a render in progress, `.<blob12>.rendering`) or `_`
(caches such as `_compare/`) are not sets.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import db
from .config import get_settings
from .service import render_folder

log = logging.getLogger("sklent")

META = "set.json"


def _design(design_id: str) -> dict | None:
    with db.connect() as conn:
        return db.row(conn.execute("SELECT * FROM designs WHERE id = ?", [design_id]).fetchone())


def design_dir(design_id: str) -> Path:
    return get_settings().renders_dir / design_id


def staging_dir(design_id: str, set_id: str) -> Path:
    """Where a render of `set_id` is written until it completes (`promote` moves it)."""
    return design_dir(design_id) / f".{set_id}.rendering"


def set_id_for(blob_sha: str) -> str:
    return blob_sha[:12]


# ---------------------------------------------------------------- reading

def _from_design_row(d: dict, folder: Path) -> dict[str, Any]:
    """A set described by the design row (the newest one, or one from before F1)."""
    unchanged = d.get("rendered_sha") and d.get("rendered_sha") == d.get("blob_sha")
    return {
        "id": folder.name,
        "design_id": d["id"],
        "blob_sha": d.get("rendered_sha") or d.get("blob_sha"),
        # the scanned commit holds this blob only while the file hasn't changed since
        "commit_sha": d.get("commit_sha") if unchanged else None,
        "head_sha": d.get("commit_sha") if unchanged else None,
        "ref": d.get("ref"),
        "path": d.get("path"),
        "rendered_at": d.get("rendered_at"),
        "files": d.get("files") or [],
        "kist_folder_id": d.get("kist_folder_id"),
        "kist_items": d.get("kist_items") or [],
        "commit": None,
        "tags": [],
        "legacy": True,
    }


def _load(d: dict, folder: Path, current: Path | None) -> dict[str, Any] | None:
    meta = read_json(folder, META)
    is_current = current is not None and folder.name == current.name
    if not isinstance(meta, dict):
        if not is_current:
            return None  # a folder nothing describes
        meta = _from_design_row(d, folder)
    elif is_current and d.get("files"):
        # the design row is the truth for the newest set's files and Kist items
        meta = {**meta, "files": d["files"], "kist_items": d.get("kist_items") or meta.get("kist_items") or []}
    out = {
        "id": folder.name,
        "design_id": d["id"],
        "commit_sha": None, "blob_sha": None, "rendered_at": None, "commit": None, "tags": [],
        "kist_items": [], "kist_folder_id": None, "files": [],
        **{k: v for k, v in meta.items() if k not in ("dir", "report", "current")},
    }
    out["dir"] = folder
    out["report"] = read_json(folder, "report.json")
    out["current"] = is_current
    return out


def _when(s: dict) -> datetime:
    for v in ((s.get("commit") or {}).get("date"), s.get("rendered_at")):
        if v:
            try:
                t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                return t if t.tzinfo else t.replace(tzinfo=UTC)
            except ValueError:
                pass
    return datetime.min.replace(tzinfo=UTC)


def latest_set(design_id: str) -> dict[str, Any] | None:
    """The newest set (the one the design shows): {id, design_id, dir: Path, files: [Output
    dicts], report: dict | None, commit_sha, blob_sha, rendered_at, ...}. None before a
    first render."""
    d = _design(design_id)
    if not d or not d.get("render_dir"):
        return None
    folder = render_folder(d)
    if folder is None or not folder.is_dir():
        return None
    s = _load(d, folder, folder)
    if s is not None and not s.get("commit_sha"):
        s["commit_sha"] = d.get("rendered_sha") or d.get("commit_sha")  # pre-F1 shape
    return s


def get_set(design_id: str, set_id: str | None = None) -> dict[str, Any] | None:
    """A set by id (its folder name); None or "latest" means the newest."""
    if set_id in (None, "", "latest"):
        return latest_set(design_id)
    for s in list_sets(design_id):
        if s["id"] == set_id:
            return s
    return None


def list_sets(design_id: str) -> list[dict[str, Any]]:
    """Every kept set, newest first (by the date of the commit that made the version,
    else when it was rendered). The set the design shows has `current: True`."""
    d = _design(design_id)
    if not d:
        return []
    current = render_folder(d) if d.get("render_dir") else None
    root = design_dir(design_id)
    folders = [p for p in root.iterdir() if p.is_dir() and p.name[:1] not in "._"] if root.is_dir() else []
    if current is not None and current.is_dir() and all(f.name != current.name for f in folders):
        folders.append(current)  # a data dir that moved: render_folder found it elsewhere
    out = [s for f in folders if (s := _load(d, f, current)) is not None]
    out.sort(key=lambda s: (_when(s), s.get("rendered_at") or ""), reverse=True)
    return out


def summary(d: dict) -> dict[str, Any]:
    """Cheap facts for the design JSON: how many sets are kept, how many are tagged, and
    the current set's tags."""
    root = design_dir(d["id"])
    current = Path(d["render_dir"]).name if d.get("render_dir") else None
    n = tagged = 0
    tags: list[str] = []
    if root.is_dir():
        for p in root.iterdir():
            if p.is_dir() and p.name[:1] not in "._":
                meta = read_json(p, META)
                if isinstance(meta, dict) or p.name == current:
                    n += 1
                    t = (meta or {}).get("tags") or [] if isinstance(meta, dict) else []
                    tagged += bool(t)
                    if p.name == current:
                        tags = list(t)
    return {"count": n, "tagged": tagged, "tags": tags}


def file_path(design_id: str, set_id: str, name: str) -> Path:
    """A file of any kept set. KeyError when the set or the file isn't there."""
    s = get_set(design_id, set_id)
    if s is None or name not in {f["file"] for f in s["files"]}:
        raise KeyError(f"design {design_id} has no file {name} in set {set_id}")
    return s["dir"] / name


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


# ---------------------------------------------------------------- writing

def write_meta(folder: Path, meta: dict[str, Any]) -> Path:
    clean = {k: v for k, v in meta.items() if k not in ("dir", "report", "current")}
    return write_json(folder, META, clean)


def ensure_meta(design: dict) -> dict[str, Any] | None:
    """Give the design's current set a set.json if it has none (sets from before F1), so
    it is still described once the design row moves on to a newer set."""
    if not design.get("render_dir"):
        return None
    folder = render_folder(design)
    if folder is None or not folder.is_dir():
        return None
    meta = read_json(folder, META)
    if isinstance(meta, dict):
        return meta
    meta = _from_design_row(design, folder)
    write_meta(folder, meta)
    return meta


def update_meta(folder: Path, **changes: Any) -> dict[str, Any]:
    meta = read_json(folder, META)
    meta = {**(meta if isinstance(meta, dict) else {}), **changes}
    write_meta(folder, meta)
    return meta


def promote(stage: Path, final: Path) -> Path:
    """Swap a finished render in for the set of the same version (a forced re-render), or
    put it in place. The old folder stays until the new one is in place."""
    final.parent.mkdir(parents=True, exist_ok=True)
    old = final.with_name(f".{final.name}.old")
    shutil.rmtree(old, ignore_errors=True)
    if final.exists():
        final.rename(old)
    stage.rename(final)
    shutil.rmtree(old, ignore_errors=True)
    return final


def discard(stage: Path) -> None:
    shutil.rmtree(stage, ignore_errors=True)


# ---------------------------------------------------------------- keep policy

def parse_keep(value: Any) -> int | None:
    """`revisions_keep`: how many of the newest untagged sets stay on disk (tagged ones
    always do). "all" (or 0) keeps every set: returns None."""
    if value in (None, "", "all", 0, "0"):
        return None
    n = int(value)
    if n < 1:
        raise ValueError("revisions_keep must be 'all' or 1 or more")
    return n


def to_prune(sets_: list[dict], keep: Any) -> list[dict]:
    """The sets the keep policy drops, from a newest-first list: never the current one,
    never a tagged one; untagged ones after the newest `keep`."""
    n = parse_keep(keep)
    if n is None:
        return []
    untagged = [s for s in sets_ if not s.get("tags")]
    kept = 0
    drop = []
    for s in untagged:
        if s.get("current"):
            kept += 1
            continue
        if kept < n:
            kept += 1
        else:
            drop.append(s)
    return drop


def prune(design_id: str, keep: Any, kist=None) -> list[str]:
    """Delete the sets the keep policy drops from disk. Their Kist items stay unless a
    Kist client is given (revisions_prune_kist), which trashes them (restorable from
    Kist's trash), except items a kept set shares (Kist files identical bytes once).
    Returns the ids pruned."""
    all_ = list_sets(design_id)
    drop = to_prune(all_, keep)
    dropped = {s["id"] for s in drop}
    shared = {i["id"] for s in all_ if s["id"] not in dropped for i in s.get("kist_items") or []}
    gone = []
    for s in drop:
        if kist is not None:
            for item in s.get("kist_items") or []:
                if item["id"] in shared:
                    continue
                try:
                    kist.trash(item["id"])
                except Exception as exc:  # noqa: BLE001 - keep pruning the disk
                    log.warning("could not trash Kist item %s: %s", item.get("id"), exc)
        shutil.rmtree(s["dir"], ignore_errors=True)
        gone.append(s["id"])
    return gone


# ---------------------------------------------------------------- forge history
#
# Read-only forge calls for the revision labels: the commit that made a version, the
# tags whose tree holds it, and the commits between two versions. They take a
# `sources.Forge` and never fail a render: on any error they return None / [].

def _forge_json(forge, path: str) -> Any:
    return forge._get(path).json()


def _commit_out(c: dict) -> dict[str, Any]:
    commit = c.get("commit") or {}
    author = commit.get("author") or {}
    login = (c.get("author") or {}).get("login")
    return {"sha": c.get("sha"), "message": (commit.get("message") or "").strip(),
            "author": login or author.get("name"), "date": author.get("date")}


def path_commits(forge, owner: str, repo: str, head: str, path: str, limit: int = 30) -> list[dict]:
    """Commits that touched `path`, newest first, from `head` back."""
    o, r = quote(owner), quote(repo)
    if forge.provider == "github":
        q = f"/repos/{o}/{r}/commits?sha={quote(head, safe='')}&path={quote(path)}&per_page={min(limit, 100)}"
    else:
        q = (f"/repos/{o}/{r}/commits?sha={quote(head, safe='')}&path={quote(path)}&limit={min(limit, 50)}"
             "&stat=false&verification=false&files=false")
    return [_commit_out(c) for c in _forge_json(forge, q)][:limit]


def commit_info(forge, owner: str, repo: str, head: str, path: str) -> dict[str, Any] | None:
    """The newest commit at or before `head` that changed `path`: the commit that made
    this version of the file."""
    try:
        commits = path_commits(forge, owner, repo, head, path, limit=1)
    except Exception as exc:  # noqa: BLE001
        log.info("no commit info for %s/%s:%s: %s", owner, repo, path, exc)
        return None
    return commits[0] if commits else None


def repo_tags(forge, owner: str, repo: str, limit: int = 30) -> list[dict]:
    """[{name, sha}] for the newest tags."""
    o, r = quote(owner), quote(repo)
    q = f"/repos/{o}/{r}/tags?per_page={limit}" if forge.provider == "github" else f"/repos/{o}/{r}/tags?limit={limit}"
    out = []
    for t in _forge_json(forge, q)[:limit]:
        sha = (t.get("commit") or {}).get("sha") or t.get("id")
        if t.get("name") and sha:
            out.append({"name": t["name"], "sha": sha})
    return out


def blob_at(forge, owner: str, repo: str, ref: str, path: str) -> str | None:
    """The blob sha of `path` at `ref`, or None when it isn't there."""
    o, r = quote(owner), quote(repo)
    try:
        data = _forge_json(forge, f"/repos/{o}/{r}/contents/{quote(path)}?ref={quote(ref, safe='')}")
    except Exception:  # noqa: BLE001 - a tag from before the file existed
        return None
    return data.get("sha") if isinstance(data, dict) else None


def tags_by_blob(forge, design: dict, limit: int = 30) -> dict[str, list[str]]:
    """{blob sha: [tag names]} for the repo's newest tags, with each tag's blob of the
    design's path cached in `<design dir>/_tags.json` (a tag's commit doesn't change, so
    one lookup each)."""
    cache_dir = design_dir(design["id"])
    cache = read_json(cache_dir, "_tags.json")
    cache = cache if isinstance(cache, dict) else {}
    out: dict[str, list[str]] = {}
    try:
        tags = repo_tags(forge, design["owner"], design["repo"], limit)
    except Exception as exc:  # noqa: BLE001
        log.info("no tags for %s/%s: %s", design["owner"], design["repo"], exc)
        return out
    changed = False
    for t in tags:
        key = f"{t['sha']}:{design['path']}"
        if key not in cache:
            cache[key] = blob_at(forge, design["owner"], design["repo"], t["sha"], design["path"])
            changed = True
        blob = cache[key]
        if blob:
            out.setdefault(blob, []).append(t["name"])
    if changed:
        cache_dir.mkdir(parents=True, exist_ok=True)
        write_json(cache_dir, "_tags.json", cache)
    return out


def refresh_tags(forge, design: dict) -> dict[str, list[str]]:
    """Re-label every kept set of a design with the tags that point at its version."""
    by_blob = tags_by_blob(forge, design)
    for s in list_sets(design["id"]):
        tags = by_blob.get(s.get("blob_sha") or "", [])
        if (s.get("tags") or []) != tags and (s["dir"] / META).exists():
            update_meta(s["dir"], tags=tags)
    return by_blob


def changelog(forge, design: dict, base: dict, head: dict, limit: int = 100) -> dict[str, Any]:
    """Commits that changed the design's file after `base`'s version, up to and including
    `head`'s: {commits: [...], complete: bool}. `complete` is False when `base`'s commit
    wasn't found within `limit` (or isn't known)."""
    head_sha = head.get("commit_sha") or head.get("head_sha")
    if not head_sha:
        return {"commits": [], "complete": False, "error": "the newer set's commit isn't known"}
    commits = path_commits(forge, design["owner"], design["repo"], head_sha, design["path"], limit)
    stop = base.get("commit_sha")
    out, complete = [], False
    for c in commits:
        if stop and c["sha"] and (c["sha"].startswith(stop) or stop.startswith(c["sha"])):
            complete = True
            break
        out.append(c)
    return {"commits": out, "complete": complete}
