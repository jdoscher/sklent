"""The work: scanning sources for designs and rendering them, one job at a time.

A single worker thread runs the queue (there is one GPU), and a scheduler thread
re-scans sources on an interval so pushes to a repo turn into fresh renders.
"""

import json
import logging
import re
import shutil
import threading
import time
import traceback
from dataclasses import asdict, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import db
from .config import get_settings
from .kist import Kist
from .render import RenderOptions, render_set
from .solidcraft import kill_all
from .sources import (
    DEFAULT_EXCLUDE,
    Forge,
    SourceError,
    SourceSpec,
    excluded,
    in_scope,
    is_design_path,
    looks_like_design,
    parse_source,
)

log = logging.getLogger("sklent")
_wake = threading.Event()
# Cancelling a running job: the worker's progress callback and render() check these.
_cancel_lock = threading.Lock()
_cancelled: set[int] = set()
_running: dict[str, int | None] = {"job": None}


class JobCancelled(Exception):
    """Raised inside a running job once someone cancelled it."""


def _cancel_requested() -> bool:
    with _cancel_lock:
        return _running["job"] is not None and _running["job"] in _cancelled


# ---------------------------------------------------------------- settings

# Feature settings beyond RenderOptions: registered by feature modules, stored in the same
# 'render' row, validated by their own function. `register_setting("exploded", False, bool)`.
_EXTRA: dict[str, tuple[Any, Any]] = {}


def register_setting(key: str, default: Any, validate: Any = None) -> None:
    """Add a render setting. `validate(value)` returns the cleaned value or raises ValueError."""
    if key in {f.name for f in fields(RenderOptions)}:
        raise ValueError(f"{key} is a RenderOptions field")
    _EXTRA[key] = (default, validate)


def _saved() -> dict[str, Any]:
    with db.connect() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key = 'render'").fetchone()
    return json.loads(r["value"]) if r else {}


def get_options() -> RenderOptions:
    saved = _saved()
    known = {f.name for f in fields(RenderOptions)}
    return RenderOptions(**{k: v for k, v in saved.items() if k in known})


def get_all_settings() -> dict[str, Any]:
    """RenderOptions plus every registered feature setting (defaults filled in)."""
    saved = _saved()
    out = asdict(get_options())
    for key, (default, _) in _EXTRA.items():
        out[key] = saved.get(key, default)
    return out


def set_options(changes: dict[str, Any]) -> RenderOptions:
    known = {f.name for f in fields(RenderOptions)}
    unknown = set(changes) - known - set(_EXTRA)
    if unknown:
        raise ValueError(f"unknown render options: {', '.join(sorted(unknown))}")
    base = {k: v for k, v in changes.items() if k in known}
    opts = RenderOptions(**{**asdict(get_options()), **base}).validate()
    saved = _saved()
    extras = {k: saved[k] for k in _EXTRA if k in saved}
    for k, v in changes.items():
        if k in _EXTRA:
            validate = _EXTRA[k][1]
            extras[k] = validate(v) if validate else v
    with db.connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('render', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     [json.dumps({**asdict(opts), **extras})])
    return opts


# ---------------------------------------------------------------- sources

def add_source(url: str, auto_render: bool = True, exclude: list[str] | None = None) -> dict:
    spec = parse_source(url)
    with db.connect() as conn:
        existing = conn.execute("SELECT * FROM sources WHERE url = ?", [spec.canonical_url]).fetchone()
        if existing:
            return db.row(existing)  # type: ignore[return-value]
        sid = db.new_id()
        conn.execute(
            "INSERT INTO sources (id, url, provider, host, kind, owner, repo, ref, path, exclude,"
            " auto_render, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [sid, spec.canonical_url, spec.provider, spec.host, spec.kind, spec.owner, spec.repo,
             spec.ref, spec.path, json.dumps(DEFAULT_EXCLUDE if exclude is None else exclude),
             int(auto_render), db.now()])
        return db.row(conn.execute("SELECT * FROM sources WHERE id = ?", [sid]).fetchone())  # type: ignore[return-value]


def get_source(source_id: str) -> dict:
    with db.connect() as conn:
        r = db.row(conn.execute("SELECT * FROM sources WHERE id = ?", [source_id]).fetchone())
    if r is None:
        raise KeyError(f"no source {source_id}")
    return r


def get_design(design_id: str) -> dict:
    with db.connect() as conn:
        r = db.row(conn.execute("SELECT * FROM designs WHERE id = ?", [design_id]).fetchone())
    if r is None:
        raise KeyError(f"no design {design_id}")
    return r


def spec_of(source: dict) -> SourceSpec:
    return SourceSpec(source["provider"], source["host"], source["kind"], source["owner"],
                      source["repo"], source["ref"], source["path"])


# ---------------------------------------------------------------- queue

def enqueue(kind: str, *, source_id: str | None = None, design_id: str | None = None,
            force: bool = False) -> dict:
    with db.connect() as conn:
        dup = conn.execute(
            "SELECT * FROM jobs WHERE kind = ? AND status = 'queued' AND "
            "source_id IS ? AND design_id IS ?", [kind, source_id, design_id]).fetchone()
        if dup:
            if force and not dup["force"]:
                conn.execute("UPDATE jobs SET force = 1 WHERE id = ?", [dup["id"]])
            job_id = dup["id"]
        else:
            job_id = conn.execute(
                "INSERT INTO jobs (kind, source_id, design_id, force, created_at) VALUES (?,?,?,?,?)",
                [kind, source_id, design_id, int(force), db.now()]).lastrowid
            if design_id:
                conn.execute("UPDATE designs SET status = 'queued' WHERE id = ? AND status != 'rendering'",
                             [design_id])
        job = db.row(conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone())
    _wake.set()
    return job  # type: ignore[return-value]


def _claim() -> dict | None:
    with db.connect() as conn:
        r = conn.execute(
            "UPDATE jobs SET status = 'running', started_at = ? WHERE id = "
            "(SELECT id FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1) RETURNING *",
            [db.now()]).fetchone()
        return db.row(r)


def _progress(job_id: int):
    last = [0.0]

    def report(fraction: float, message: str) -> None:
        if _cancel_requested():
            raise JobCancelled(f"job {job_id} was cancelled")
        if time.monotonic() - last[0] < 0.5 and fraction < 1:
            return
        last[0] = time.monotonic()
        with db.connect() as conn:
            db.update(conn, "jobs", job_id, progress=round(fraction, 3), message=message)
    return report


def _finish(job_id: int, error: str | None = None, message: str | None = None) -> None:
    fields_: dict[str, Any] = {"status": "failed" if error else "done", "finished_at": db.now(),
                               "error": error}
    if not error:
        fields_["progress"] = 1.0
    if message is not None:
        fields_["message"] = message
    with db.connect() as conn:
        db.update(conn, "jobs", job_id, **fields_)


def run_job(job: dict) -> None:
    with _cancel_lock:
        _running["job"] = job["id"]
    try:
        if job["kind"] == "scan":
            msg = scan(job["source_id"], _progress(job["id"]))
        else:
            msg = render(job["design_id"], bool(job["force"]), _progress(job["id"]))
        if _cancel_requested():
            raise JobCancelled(f"job {job['id']} was cancelled")
        _finish(job["id"], message=msg)
    except Exception as exc:  # noqa: BLE001 — a job's failure is recorded, never fatal
        if _cancel_requested():
            log.info("job %s cancelled", job["id"])
        else:
            log.warning("job %s failed: %s\n%s", job["id"], exc, traceback.format_exc())
            _finish(job["id"], error=str(exc) or exc.__class__.__name__)
    finally:
        with _cancel_lock:
            _running["job"] = None
            _cancelled.discard(job["id"])


def _status_without_job(design: dict) -> str:
    """What a design's status is once a queued or running render of it is called off."""
    if design["render_dir"] and design["files"]:
        return "rendered"
    return "failed" if design["error"] else "new"


def cancel(job_id: int) -> dict:
    """Call off a job. A queued one is dropped; a running one has its SolidCraft
    processes killed (frames stop at once; an encode in progress stops at its next
    progress report). Either way the job ends as `cancelled` and its design goes back
    to the status it had. Raises KeyError for an unknown job, ValueError for a
    finished one."""
    with db.connect() as conn:
        job: dict = {}
        for _ in range(3):  # the worker may claim a queued job between our read and write
            job = db.row(conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone()) or {}
            if not job:
                raise KeyError(f"no job {job_id}")
            if job["status"] not in ("queued", "running"):
                raise ValueError(f"job {job_id} is already {job['status']}")
            if job["status"] == "running":
                with _cancel_lock:  # before the row changes, so the worker can't finish it
                    _cancelled.add(job_id)
            changed = conn.execute(
                "UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ? AND status = ?",
                [db.now(), job_id, job["status"]]).rowcount
            if changed:
                break
        else:
            raise ValueError(f"job {job_id} kept changing state; try again")
        with _cancel_lock:
            ours = _running["job"] == job_id  # this process's worker is running it
        if job["design_id"] and not ours:
            # nothing will unwind it (queued, or a row left running by another process):
            # put the design back here
            d = db.row(conn.execute("SELECT * FROM designs WHERE id = ?", [job["design_id"]]).fetchone())
            if d and d["status"] in ("queued", "rendering"):
                db.update(conn, "designs", d["id"], status=_status_without_job(d))
    if ours:
        kill_all()
    with db.connect() as conn:
        return db.row(conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone())  # type: ignore[return-value]


def worker_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        job = _claim()
        if job is None:
            _wake.wait(2)
            _wake.clear()
            continue
        run_job(job)


def scheduler_loop(stop: threading.Event) -> None:
    interval = get_settings().scan_interval_minutes
    while interval > 0 and not stop.wait(60):
        cutoff = (datetime.now(UTC) - timedelta(minutes=interval)).isoformat(timespec="seconds")
        with db.connect() as conn:
            due = conn.execute("SELECT id FROM sources WHERE scanned_at IS NULL OR scanned_at < ?",
                               [cutoff]).fetchall()
        for r in due:
            enqueue("scan", source_id=r["id"])


# ---------------------------------------------------------------- scan

def scan(source_id: str, progress=lambda f, m: None) -> str:
    source = get_source(source_id)
    forge = Forge(source["provider"], source["host"])
    errors: list[str] = []
    if source["kind"] == "account":
        repos = [r for r in forge.list_repos(source["owner"]) if not r.fork and not r.archived]
    else:
        repos = [forge.repo_info(source["owner"], source["repo"])]
    seen: set[str] = set()
    found = changed = 0
    for i, repo in enumerate(repos):
        progress(i / max(1, len(repos)), f"scanning {repo.owner}/{repo.name}")
        try:
            ref = source["ref"] or repo.default_branch
            sha = forge.resolve(repo.owner, repo.name, ref)
            files = [f for f in forge.tree(repo.owner, repo.name, sha)
                     if is_design_path(f.path) and in_scope(f.path, source["path"])
                     and not excluded(f.path, source["exclude"], source["path"])]
        except (SourceError, OSError) as exc:
            errors.append(f"{repo.owner}/{repo.name}: {exc}")
            continue
        with db.connect() as conn:
            for f in files:
                found += 1
                # One row per design even when sources overlap (an account and one of its
                # repos): the source that scanned it last owns it, so it renders once.
                existing = conn.execute(
                    "SELECT d.* FROM designs d JOIN sources s ON s.id = d.source_id WHERE s.host = ?"
                    " AND d.owner = ? AND d.repo = ? AND d.path = ?",
                    [source["host"], repo.owner, repo.name, f.path]).fetchone()
                url = forge.blob_url(repo.owner, repo.name, sha, f.path)
                if existing is None:
                    did = db.new_id()
                    conn.execute(
                        "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha,"
                        " commit_sha, size, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [did, source_id, repo.owner, repo.name, ref, f.path, url, f.sha, sha, f.size,
                         db.now()])
                    changed += 1
                else:
                    did = existing["id"]
                    new_blob = existing["blob_sha"] != f.sha
                    changed += new_blob
                    status = existing["status"]
                    if new_blob or status == "removed":
                        status = "rendered" if existing["rendered_sha"] == f.sha else "new"
                    db.update(conn, "designs", did, source_id=source_id, ref=ref, html_url=url, blob_sha=f.sha,
                              commit_sha=sha, size=f.size, status=status, updated_at=db.now())
                seen.add(did)
    with db.connect() as conn:
        for r in conn.execute("SELECT id FROM designs WHERE source_id = ? AND status != 'removed'",
                              [source_id]).fetchall():
            if r["id"] not in seen and not errors:
                db.update(conn, "designs", r["id"], status="removed", updated_at=db.now())
        db.update(conn, "sources", source_id, scanned_at=db.now(),
                  last_error="; ".join(errors)[:2000] or None)
        todo = conn.execute(
            "SELECT id FROM designs WHERE source_id = ? AND status = 'new'", [source_id]).fetchall()
    queued = 0
    if source["auto_render"]:
        for r in todo:
            enqueue("render", design_id=r["id"])
            queued += 1
    msg = f"{len(repos)} repo(s), {found} design(s), {changed} new or changed, {queued} queued"
    if errors:
        msg += f"; {len(errors)} repo error(s)"
    return msg


# ---------------------------------------------------------------- render

def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "design"


def render(design_id: str, force: bool = False, progress=lambda f, m: None) -> str:
    settings = get_settings()
    design = get_design(design_id)
    if not force and design["rendered_sha"] == design["blob_sha"]:
        with db.connect() as conn:
            db.update(conn, "designs", design_id, status="rendered")
        return "already rendered at this version"
    source = get_source(design["source_id"])
    with db.connect() as conn:
        db.update(conn, "designs", design_id, status="rendering", error=None, updated_at=db.now())
    try:
        result = _render(settings, source, design, progress)
    except Exception as exc:
        if _cancel_requested():
            _undo_cancelled_render(design)
            raise JobCancelled(f"render of {design['path']} was cancelled") from exc
        from . import sets
        sets.discard(sets.staging_dir(design_id, sets.set_id_for(design["blob_sha"])))
        with db.connect() as conn:
            db.update(conn, "designs", design_id, status="failed", error=str(exc)[:2000],
                      updated_at=db.now())
        raise
    return result


def _undo_cancelled_render(design: dict) -> None:
    """Drop a cancelled render's partial set and put the design back as it was. A render
    writes into a staging folder and only replaces the set of the same version once it
    has finished, so a cancelled forced re-render leaves the previous set in place."""
    from . import sets

    settings = get_settings()
    sets.discard(sets.staging_dir(design["id"], sets.set_id_for(design["blob_sha"])))
    shutil.rmtree(settings.work_dir / design["id"], ignore_errors=True)
    fields_: dict[str, Any] = {"updated_at": db.now(), "error": design["error"]}
    if design["render_dir"] and not Path(design["render_dir"]).is_dir() and sets.latest_set(design["id"]) is None:
        fields_.update(render_dir=None, files=[], rendered_sha=None)
        design = {**design, "render_dir": None, "files": []}
    fields_["status"] = _status_without_job(design)
    with db.connect() as conn:
        db.update(conn, "designs", design["id"], **fields_)


def _render(settings, source: dict, design: dict, progress) -> str:
    """Render the design's current version into its own set (F1: one set per version,
    older sets kept), file it into Kist as new versions of the previous set's items, then
    apply the keep policy."""
    from . import sets

    forge = Forge(source["provider"], source["host"])
    progress(0.0, "downloading design")
    data = forge.fetch(design["owner"], design["repo"], design["commit_sha"], design["path"],
                       settings.max_design_mb * 2**20)
    if not looks_like_design(data):
        raise SourceError(f"{design['path']} is not a SolidCraft design")
    work = settings.work_dir / design["id"]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    filename = design["path"].rsplit("/", 1)[-1]
    local = work / filename
    local.write_bytes(data)

    stem = slug(filename.rsplit(".", 1)[0])
    set_id = sets.set_id_for(design["blob_sha"])
    out_dir = settings.renders_dir / design["id"] / set_id
    # Written aside and swapped in when done, so a failed or cancelled re-render of the
    # same version never leaves the design without its set.
    stage = sets.staging_dir(design["id"], set_id)
    sets.discard(stage)
    opts = get_options()
    all_settings = get_all_settings()
    outputs, report = render_set(local, stage, stem, opts,
                                 lambda f, m: progress(0.02 + 0.86 * f, m),
                                 settings=all_settings)
    (stage / "report.json").write_text(json.dumps(report, indent=2))
    shutil.rmtree(work, ignore_errors=True)

    # The set's labels: the commit that made this version of the file, and git tags.
    commit = sets.commit_info(forge, design["owner"], design["repo"], design["commit_sha"], design["path"])
    commit_sha = (commit or {}).get("sha") or design["commit_sha"]
    previous = sets.ensure_meta(design)  # the set shown until now (before F1: no set.json)
    meta: dict[str, Any] = {
        "id": set_id, "design_id": design["id"], "blob_sha": design["blob_sha"],
        "commit_sha": commit_sha, "head_sha": design["commit_sha"], "ref": design["ref"],
        "path": design["path"], "rendered_at": db.now(), "files": [asdict(o) for o in outputs],
        "commit": commit, "tags": [], "palette": opts.palette,
        "kist_folder_id": design["kist_folder_id"], "kist_items": [],
    }

    kist = Kist()
    folder_id, items = design["kist_folder_id"], []
    kist_notes: list[str] = []
    if kist.enabled:
        progress(0.9, "filing into Kist")
        folder_id = kist.ensure_folder([settings.kist_root_folder, design["owner"], design["repo"], stem])
        base_tags = ["solidcraft", f"repo:{design['owner']}/{design['repo']}", f"design:{stem}",
                     f"palette:{opts.palette}", f"rev:{commit_sha[:10]}"]
        notes = (f"{design['owner']}/{design['repo']}:{design['path']} at "
                 f"{commit_sha[:10]}, rendered by sklent")
        before = {(i.get("style"), i.get("variant")): i["id"] for i in (previous or {}).get("kist_items") or []}
        by_file = {f["file"]: f for f in (previous or {}).get("files") or []}
        for i in (previous or {}).get("kist_items") or []:  # items from before F1 carry no style
            f = by_file.get(i.get("file"))
            if f and (f["style"], f["variant"]) not in before:
                before[(f["style"], f["variant"])] = i["id"]
        _tag_legacy_items(kist, previous, kist_notes)
        for o in outputs:
            item = kist.upload(stage / o.file, folder_id=folder_id,
                               tags=[*base_tags, f"style:{o.style}", f"format:{o.variant}"],
                               notes=notes, source_url=design["html_url"])
            items.append({"id": item["id"], "file": o.file, "style": o.style, "variant": o.variant})
            old = before.get((o.style, o.variant))
            if old and old != item["id"]:
                try:
                    kist.file_version(item["id"], old)
                except Exception as exc:  # noqa: BLE001 - the item is filed; the link is a bonus
                    kist_notes.append(f"version link {o.file}: {exc}"[:200])
        meta.update(kist_folder_id=folder_id, kist_items=items)
    if kist_notes:
        report["kist"] = kist_notes
        (stage / "report.json").write_text(json.dumps(report, indent=2))

    sets.write_meta(stage, meta)
    progress(0.97, "keeping the set")
    if _cancel_requested():
        raise JobCancelled(f"render of {design['path']} was cancelled")
    sets.promote(stage, out_dir)
    with db.connect() as conn:
        db.update(conn, "designs", design["id"], status="rendered", rendered_sha=design["blob_sha"],
                  rendered_at=meta["rendered_at"], render_dir=str(out_dir), files=meta["files"],
                  kist_folder_id=folder_id, kist_items=items, error=None, updated_at=db.now())

    # Labels and the keep policy never fail a finished render.
    try:
        sets.refresh_tags(forge, {**design, "kist_items": items})
    except Exception as exc:  # noqa: BLE001
        log.info("tags for %s: %s", design["path"], exc)
    pruned: list[str] = []
    try:
        pruned = sets.prune(design["id"], all_settings.get("revisions_keep", 10),
                            kist if kist.enabled and all_settings.get("revisions_prune_kist") else None)
    except Exception as exc:  # noqa: BLE001
        log.warning("keep policy for %s: %s", design["path"], exc)
    where = f" and filed {len(items)} in Kist" if items else ""
    tail = f"; pruned {plural(len(pruned), 'older set')}" if pruned else ""
    return f"rendered {plural(len(outputs), 'file')} ({plural(report['bodies'], 'body', 'bodies')}){where}{tail}"


def _tag_legacy_items(kist: Kist, previous: dict | None, notes: list[str]) -> None:
    """Items filed before revisions have no `rev:` tag; give them the commit their notes
    name, so every item carries one, and record it on their set."""
    if not previous or previous.get("commit_sha") and not previous.get("legacy"):
        return
    items = previous.get("kist_items") or []
    if not items:
        return
    try:
        commit = previous.get("commit_sha") or kist.commit_of(items[0]["id"])
        if not commit:
            return
        for i in items:
            kist.add_tags(i["id"], [f"rev:{commit[:10]}"])
        from . import sets
        folder = get_settings().renders_dir / previous["design_id"] / previous["id"]
        if folder.is_dir():
            meta = sets.read_json(folder, sets.META) or {}
            if not meta.get("commit_sha") or len(meta["commit_sha"]) < 40:
                sets.update_meta(folder, commit_sha=meta.get("commit_sha") or commit, legacy=False)
            else:
                sets.update_meta(folder, legacy=False)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"rev tag on older items: {exc}"[:200])


def plural(n: int, one: str, many: str | None = None) -> str:
    """`1 body`, `2 bodies`, `1,418 bodies`."""
    return f"{n:,} {one if n == 1 else (many or one + 's')}"
