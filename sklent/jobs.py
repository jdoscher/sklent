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
    PULL_REF,
    Forge,
    SourceError,
    SourceSpec,
    drop_mesh_exports,
    excluded,
    in_scope,
    is_design_path,
    looks_like_design,
    parse_source,
    parse_time,
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


def _repo_overrides(design_id: str | None) -> dict[str, Any]:
    """A design's render settings from its repo's `.sklent.yaml` (validated there)."""
    if not design_id:
        return {}
    try:
        from .repo_config import render_overrides
    except ImportError:
        return {}
    return render_overrides(design_id)


def get_options(design_id: str | None = None) -> RenderOptions:
    """The render options; with a design id, its repo config's overrides applied."""
    saved = {**_saved(), **_repo_overrides(design_id)}
    known = {f.name for f in fields(RenderOptions)}
    return RenderOptions(**{k: v for k, v in saved.items() if k in known})


def get_all_settings(design_id: str | None = None) -> dict[str, Any]:
    """RenderOptions plus every registered feature setting (defaults filled in); with a
    design id, its repo config's overrides applied."""
    saved = {**_saved(), **_repo_overrides(design_id)}
    out = asdict(get_options(design_id))
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

def _scan_inputs():
    """The inputs feature (repo config, links, PRs, class sets), or None without it."""
    try:
        from .features import inputs
    except ImportError:
        return None
    return inputs


def scan(source_id: str, progress=lambda f, m: None) -> str:
    """Find a source's designs at its ref (or at its deadline), note what changed, and
    queue renders when the source auto-renders."""
    source = get_source(source_id)
    forge = Forge(source["provider"], source["host"])
    inputs = _scan_inputs()
    errors: list[str] = []
    notes: list[str] = []
    opts = inputs.classes.options(source_id) if inputs else {}
    deadline = parse_time(opts["deadline"]) if opts.get("deadline") else None
    prefix = inputs.classes.prefix_of(source) if inputs else None
    if source["kind"] == "account":
        repos = [r for r in forge.list_repos(source["owner"]) if not r.fork and not r.archived]
        if prefix:
            repos = [r for r in repos if r.name.lower().startswith(prefix.lower())]
    else:
        repos = [forge.repo_info(source["owner"], source["repo"])]
    pull = PULL_REF.match(source["ref"] or "")
    settings = get_all_settings()
    formats = inputs.formats_from_settings(settings) if inputs else None
    seen: set[str] = set()
    submissions: set[tuple[str, str]] = set()
    found = changed = 0
    for i, repo in enumerate(repos):
        progress(i / max(1, len(repos)), f"scanning {repo.owner}/{repo.name}")
        ref = source["ref"] or repo.default_branch
        key_ref = ref
        when = head = None
        try:
            changed_paths: set[str] | None = None
            if pull and inputs:
                info = forge.pull(repo.owner, repo.name, int(pull.group(1)))
                sha = info["head_sha"]
                try:
                    changed_paths = set(forge.pull_files(repo.owner, repo.name, info["number"]))
                except SourceError as exc:
                    notes.append(f"couldn't list the pull request's files ({exc}); every design renders")
                inputs.refs.store_pull(source_id, info, changed_paths)
            elif deadline:
                head = forge.resolve(repo.owner, repo.name, ref)
                hit = forge.commit_before(repo.owner, repo.name, ref, deadline)
                key_ref = inputs.classes.due_ref(ref, opts["deadline"]) if inputs else ref
                submissions.add((repo.owner, repo.name))
                if hit is None:
                    if inputs:
                        inputs.classes.record(source_id, repo.owner, repo.name, None, None, head, 0)
                    continue
                sha, when = hit
            else:
                sha = forge.resolve(repo.owner, repo.name, ref)
            tree = forge.tree(repo.owner, repo.name, sha)
            configs = (inputs.repo_config.load(forge, source["host"], repo.owner, repo.name, sha, tree)
                       if inputs else {})
            exports = drop_mesh_exports([f.path for f in tree])
            files = []
            for f in tree:
                if not (is_design_path(f.path) and in_scope(f.path, source["path"])
                        and not excluded(f.path, source["exclude"], source["path"])):
                    continue
                cfg = inputs.repo_config.resolve(f.path, configs) if configs else {}
                chosen = f.path == source["path"]  # a source naming one file renders it as it is
                if not chosen:
                    if not is_design_path(f.path, cfg.get("formats") or formats) or f.path in exports:
                        continue
                    if cfg and not cfg["included"]:
                        continue
                files.append((f, cfg))
            if changed_paths is not None:
                files = [(f, cfg) for f, cfg in files if f.path in changed_paths or inputs.links.depends_on(
                    source["host"], repo.owner, repo.name, f.path, changed_paths)]
            for cpath, c in configs.items():
                notes += [f"{repo.name}/{cpath}: {e}" for e in c.get("errors") or []]
        except (SourceError, OSError) as exc:
            errors.append(f"{repo.owner}/{repo.name}: {exc}")
            continue
        tree_shas = {f.path: f.sha for f in tree}
        later: list[tuple[str, dict]] = []
        with db.connect() as conn:
            for f, cfg in files:
                found += 1
                # One row per design and ref even when sources overlap (an account and one of
                # its repos): the source that scanned it last owns it, so it renders once.
                existing = conn.execute(
                    "SELECT d.* FROM designs d JOIN sources s ON s.id = d.source_id WHERE s.host = ?"
                    " AND d.owner = ? AND d.repo = ? AND d.path = ? AND d.ref = ?",
                    [source["host"], repo.owner, repo.name, f.path, key_ref]).fetchone()
                url = forge.blob_url(repo.owner, repo.name, sha, f.path)
                if existing is None:
                    did = db.new_id()
                    conn.execute(
                        "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha,"
                        " commit_sha, size, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [did, source_id, repo.owner, repo.name, key_ref, f.path, url, f.sha, sha, f.size,
                         db.now()])
                    changed += 1
                else:
                    did = existing["id"]
                    blob = inputs.links.scan_blob(did, f.sha, tree_shas) if inputs else f.sha
                    if inputs:
                        inputs.links.note_scan(conn, did, f.sha)
                    new_blob = existing["blob_sha"] != blob
                    changed += new_blob
                    status = existing["status"]
                    if new_blob or status == "removed":
                        status = "rendered" if existing["rendered_sha"] == blob else "new"
                    db.update(conn, "designs", did, source_id=source_id, ref=key_ref, html_url=url, blob_sha=blob,
                              commit_sha=sha, size=f.size, status=status, updated_at=db.now())
                seen.add(did)
                later.append((did, cfg))
        if inputs:
            for did, cfg in later:
                inputs.repo_config.store(did, {k: v for k, v in cfg.items() if k != "included"}, sha)
            if deadline:
                inputs.classes.record(source_id, repo.owner, repo.name, sha, when, head, len(files))
    if inputs and deadline and not errors:
        inputs.classes.forget_others(source_id, submissions)
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
    if notes:
        uniq = list(dict.fromkeys(notes))
        msg += f"; {len(uniq)} note(s): " + "; ".join(uniq[:5])[:1500]
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
            # the inputs step may have re-keyed the design (linked files): clean up that set
            _undo_cancelled_render({**design, "blob_sha": get_design(design_id)["blob_sha"]})
            raise JobCancelled(f"render of {design['path']} was cancelled") from exc
        with db.connect() as conn:
            db.update(conn, "designs", design_id, status="failed", error=str(exc)[:2000],
                      updated_at=db.now())
        raise
    return result


def _undo_cancelled_render(design: dict) -> None:
    """Drop a cancelled render's partial set and put the design back as it was. A forced
    re-render of an unchanged file writes into the same folder as the previous set, which
    is cleared when the render starts, so that set is gone too."""
    settings = get_settings()
    out_dir = settings.renders_dir / design["id"] / design["blob_sha"][:12]
    shutil.rmtree(out_dir, ignore_errors=True)
    shutil.rmtree(settings.work_dir / design["id"], ignore_errors=True)
    fields_: dict[str, Any] = {"updated_at": db.now(), "error": design["error"]}
    if design["render_dir"] and Path(design["render_dir"]).name == out_dir.name:
        fields_.update(render_dir=None, files=[], rendered_sha=None)
        design = {**design, "render_dir": None, "files": []}
    fields_["status"] = _status_without_job(design)
    with db.connect() as conn:
        db.update(conn, "designs", design["id"], **fields_)


def _render(settings, source: dict, design: dict, progress) -> str:
    forge = Forge(source["provider"], source["host"])
    progress(0.0, "downloading design")
    work = settings.work_dir / design["id"]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    filename = design["path"].rsplit("/", 1)[-1]
    inputs = _scan_inputs()
    if inputs:  # the design plus the files it links, in the repo's layout (F3, F14)
        local, design = inputs.links.fetch_design(forge, settings, design, work, progress,
                                                  inputs.repo_config.get(design["id"]), looks_like_design)
    else:
        data = forge.fetch(design["owner"], design["repo"], design["commit_sha"], design["path"],
                           settings.max_design_mb * 2**20)
        if not looks_like_design(data, design["path"]):
            raise SourceError(f"{design['path']} is not a SolidCraft design")
        local = work / filename
        local.write_bytes(data)

    stem = slug(filename.rsplit(".", 1)[0])
    out_dir = settings.renders_dir / design["id"] / design["blob_sha"][:12]
    shutil.rmtree(out_dir, ignore_errors=True)
    opts = get_options(design["id"])
    outputs, report = render_set(local, out_dir, stem, opts,
                                 lambda f, m: progress(0.02 + 0.88 * f, m),
                                 settings=get_all_settings(design["id"]))
    if inputs:
        report["inputs"] = inputs.links.report_for(local)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    shutil.rmtree(work, ignore_errors=True)

    kist = Kist()
    folder_id, items = design["kist_folder_id"], []
    if kist.enabled:
        progress(0.92, "filing into Kist")
        folder_id = kist.ensure_folder([settings.kist_root_folder, design["owner"], design["repo"], stem])
        base_tags = ["solidcraft", f"repo:{design['owner']}/{design['repo']}", f"design:{stem}",
                     f"palette:{opts.palette}"]
        notes = (f"{design['owner']}/{design['repo']}:{design['path']} at "
                 f"{design['commit_sha'][:10]}, rendered by sklent")
        for o in outputs:
            item = kist.upload(out_dir / o.file, folder_id=folder_id,
                               tags=[*base_tags, f"style:{o.style}", f"format:{o.variant}"],
                               notes=notes, source_url=design["html_url"])
            items.append({"id": item["id"], "file": o.file})
        new_ids = {i["id"] for i in items}
        for old in design["kist_items"]:
            if old["id"] not in new_ids:
                kist.trash(old["id"])

    # keep only the newest set on disk
    for old in (settings.renders_dir / design["id"]).iterdir():
        if old != out_dir and old.is_dir():
            shutil.rmtree(old, ignore_errors=True)

    with db.connect() as conn:
        db.update(conn, "designs", design["id"], status="rendered", rendered_sha=design["blob_sha"],
                  rendered_at=db.now(), render_dir=str(out_dir), files=[asdict(o) for o in outputs],
                  kist_folder_id=folder_id, kist_items=items, error=None, updated_at=db.now())
    where = f" and filed {len(items)} in Kist" if items else ""
    return f"rendered {plural(len(outputs), 'file')} ({plural(report['bodies'], 'body', 'bodies')}){where}"


def plural(n: int, one: str, many: str | None = None) -> str:
    """`1 body`, `2 bodies`, `1,418 bodies`."""
    return f"{n:,} {one if n == 1 else (many or one + 's')}"
