"""Operations shared by the REST API and the MCP tools, with their output shapes."""

import shutil
from pathlib import Path
from typing import Any

from . import db, jobs
from .config import get_settings
from .kist import Kist
from .palette import PALETTES

KIND_ORDER = ["1080p", "reel", "discord", "gif", "social", "hires"]


def render_folder(d: dict) -> Path | None:
    """The design's newest render set on disk.

    The stored path is absolute, so a data dir that moved (a restored backup, a copy
    mounted somewhere else) leaves it pointing nowhere; then the same set is looked
    up under this server's renders dir, where it was written as <id>/<blob12>."""
    if not d["render_dir"]:
        return None
    stored = Path(d["render_dir"])
    if stored.is_dir():
        return stored
    moved = get_settings().renders_dir / d["id"] / stored.name
    return moved if moved.is_dir() else stored


def design_out(d: dict) -> dict[str, Any]:
    name = d["path"].rsplit("/", 1)[-1]
    base = f"/api/designs/{d['id']}/files/"
    folder = render_folder(d)

    def size(name: str) -> int | None:
        p = folder / name if folder else None
        return p.stat().st_size if p and p.is_file() else None

    files = [{**f, "url": base + f["file"], "bytes": size(f["file"])} for f in d["files"]]

    def pick(style: str, variant: str) -> str | None:
        return next((f["url"] for f in files if f["style"] == style and f["variant"] == variant), None)

    return {
        "id": d["id"],
        "source_id": d["source_id"],
        "name": name,
        "repo": f"{d['owner']}/{d['repo']}",
        "path": d["path"],
        "ref": d["ref"],
        "html_url": d["html_url"],
        "status": d["status"],
        "stale": d["status"] == "rendered" and d["rendered_sha"] != d["blob_sha"],
        "commit": (d["commit_sha"] or "")[:10],
        "rendered_at": d["rendered_at"],
        "error": d["error"],
        "thumb_url": pick("shaded", "social"),
        "gif_url": pick("shaded", "gif"),
        "files": files,
        "kist_folder_id": d["kist_folder_id"],
        "kist_items": d["kist_items"],
    }


def source_out(s: dict, counts: dict[str, dict[str, int]]) -> dict[str, Any]:
    c = counts.get(s["id"], {})
    return {
        **{k: s[k] for k in ("id", "url", "provider", "kind", "owner", "repo", "ref", "path",
                             "exclude", "created_at", "scanned_at", "last_error")},
        "auto_render": bool(s["auto_render"]),
        "label": "/".join(x for x in (s["owner"], s["repo"], s["path"]) if x),
        "designs": sum(v for k, v in c.items() if k != "removed"),
        "rendered": c.get("rendered", 0),
        "failed": c.get("failed", 0),
    }


def list_sources() -> list[dict]:
    with db.connect() as conn:
        srcs = db.rows(conn.execute("SELECT * FROM sources ORDER BY created_at").fetchall())
        counts: dict[str, dict[str, int]] = {}
        for r in conn.execute("SELECT source_id, status, COUNT(*) n FROM designs GROUP BY 1, 2"):
            counts.setdefault(r["source_id"], {})[r["status"]] = r["n"]
    return [source_out(s, counts) for s in srcs]


def list_designs(source_id: str | None = None, status: str | None = None,
                 query: str | None = None, include_removed: bool = False) -> list[dict]:
    sql, args = "SELECT * FROM designs WHERE 1=1", []
    if source_id:
        sql += " AND source_id = ?"
        args.append(source_id)
    if status:
        sql += " AND status = ?"
        args.append(status)
    elif not include_removed:
        sql += " AND status != 'removed'"
    if query:
        sql += " AND (path LIKE ? OR repo LIKE ? OR owner LIKE ?)"
        args += [f"%{query}%"] * 3
    sql += " ORDER BY COALESCE(rendered_at, updated_at) DESC"
    with db.connect() as conn:
        return [design_out(d) for d in db.rows(conn.execute(sql, args).fetchall())]


def list_jobs(limit: int = 50, active_only: bool = False) -> list[dict]:
    sql = ("SELECT j.*, d.path AS design_path, d.owner || '/' || d.repo AS design_repo, "
           "s.url AS source_url FROM jobs j LEFT JOIN designs d ON d.id = j.design_id "
           "LEFT JOIN sources s ON s.id = j.source_id")
    if active_only:
        sql += " WHERE j.status IN ('queued', 'running')"
    sql += " ORDER BY j.id DESC LIMIT ?"
    with db.connect() as conn:
        return db.rows(conn.execute(sql, [limit]).fetchall())


def get_job(job_id: int) -> dict:
    with db.connect() as conn:
        r = db.row(conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone())
    if r is None:
        raise KeyError(f"no job {job_id}")
    return r


def delete_source(source_id: str) -> None:
    jobs.get_source(source_id)
    with db.connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM designs WHERE source_id = ?", [source_id])]
        conn.execute("DELETE FROM jobs WHERE status = 'queued' AND (source_id = ? OR design_id IN "
                     f"({','.join('?' * len(ids)) or 'NULL'}))", [source_id, *ids])
        conn.execute("DELETE FROM sources WHERE id = ?", [source_id])
    for i in ids:
        shutil.rmtree(get_settings().renders_dir / i, ignore_errors=True)


def render_url(url: str, force: bool = False) -> dict:
    """Add (or reuse) the source for a URL, scan it now, and queue its designs."""
    source = jobs.add_source(url)
    summary = jobs.scan(source["id"])
    queued = []
    for d in list_designs(source_id=source["id"]):
        if force or d["status"] in ("new", "failed") or d["stale"]:
            queued.append(jobs.enqueue("render", design_id=d["id"], force=force))
        elif d["status"] == "queued":
            queued.extend(j for j in list_jobs(200, active_only=True) if j["design_id"] == d["id"])
    return {"source": jobs.get_source(source["id"]), "scan": summary,
            "jobs": [{"id": j["id"], "design_id": j["design_id"], "status": j["status"]} for j in queued]}


def file_path(design_id: str, name: str) -> Path:
    d = jobs.get_design(design_id)
    if not d["render_dir"] or name not in {f["file"] for f in d["files"]}:
        raise KeyError(f"design {design_id} has no file {name}")
    return render_folder(d) / name  # type: ignore[operator]


def status() -> dict:
    s = get_settings()
    kist = Kist()
    return {
        "kist": {"url": s.kist_url or None, "reachable": kist.health() if kist.enabled else False,
                 "root_folder": s.kist_root_folder},
        "github_token": bool(s.github_token),
        "forgejo": {"url": s.forgejo_url, "token": bool(s.forgejo_token)},
        "scan_interval_minutes": s.scan_interval_minutes,
        "palettes": [{"name": p.name, "label": p.label, "shaded": p.shaded} for p in PALETTES.values()],
    }
