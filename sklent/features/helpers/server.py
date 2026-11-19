"""The render helper protocol, server side (0.2.1).

A helper (`sklent helper`, another machine with SolidCraft) asks for work with a helper
token and renders it there; this server keeps scans, downloads from the forge, filing into
Kist and the revision history.

- `POST /api/helpers/claim` {name, solidcraft_version, renderer, gpu, mem_gb, max_bodies?}:
  204 when there is nothing to do, 409 when the helper's SolidCraft differs from this
  server's, else {job, design, settings_snapshot, design_file, stem, lease_s}. The job is
  the oldest queued render; it is leased to the helper for `helpers_lease_seconds`.
- `GET /api/helpers/jobs/{id}/inputs.tar`: the design and the files it links.
- `GET /api/helpers/jobs/{id}/repo-file?path=`: a small file from the design's repo (a
  step's bom.yaml), fetched by this server, so a helper needs no forge token.
- `POST /api/helpers/jobs/{id}/progress` {fraction, message}: renews the lease;
  answers {cancel} (true once the job was cancelled or taken away).
- `POST /api/helpers/jobs/{id}/result`: a tar of the finished stage folder whose first
  member is `.sklent-manifest.json` {outputs: [Output], files: {name: size}}; every other
  member must be a plain file listed there. Then `jobs.finish_render` files it.
- `POST /api/helpers/jobs/{id}/fail` {error, retry?}: retry=true (the helper was stopped)
  requeues the job while attempts remain; otherwise the render failed.
- A lease that runs out requeues the job (at most `helpers_max_attempts` claims, then failed).

Every job call carries the helper's name (`?name=`): a job answers only to the helper that
claimed it, with the token it claimed it with.
"""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
import tempfile
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from ... import db, jobs, sets, solidcraft
from ...config import get_settings
from ...render import Output

log = logging.getLogger("sklent.helpers")

MANIFEST = ".sklent-manifest.json"
NAME_MAX = 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS helpers (
    name TEXT PRIMARY KEY,
    token_id TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    version TEXT,
    renderer TEXT,
    gpu TEXT,
    mem_gb REAL,
    max_bodies INTEGER,
    jobs_done INTEGER NOT NULL DEFAULT 0,
    jobs_failed INTEGER NOT NULL DEFAULT 0,
    current_job INTEGER,
    last_error TEXT,
    refused TEXT
);
CREATE TABLE IF NOT EXISTS helper_leases (
    job_id INTEGER PRIMARY KEY,
    helper TEXT NOT NULL,
    token_id TEXT,
    design_id TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    snapshot TEXT NOT NULL DEFAULT '{}',
    design_file TEXT,
    claimed_at TEXT NOT NULL
);
"""


class Refused(Exception):
    """A claim refused with 409 (a different SolidCraft)."""


class NotYours(Exception):
    """The job isn't leased to this helper (cancelled, requeued, or someone else's)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def clean_name(name: Any) -> str:
    name = str(name or "").strip()
    if not name or len(name) > NAME_MAX or any(c in name for c in "/\\\n\r\t"):
        raise ValueError(f"a helper needs a name (up to {NAME_MAX} characters, no slashes)")
    return name


def _setting(key: str) -> Any:
    return jobs.get_all_settings().get(key)


# ---------------------------------------------------------------- registry

def note_seen(name: str, token_id: str | None, info: dict[str, Any]) -> None:
    now = _iso(_now())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO helpers (name, token_id, first_seen, last_seen, version, renderer, gpu, mem_gb, max_bodies) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET token_id = excluded.token_id, "
            "last_seen = excluded.last_seen, version = excluded.version, renderer = excluded.renderer, "
            "gpu = excluded.gpu, mem_gb = excluded.mem_gb, max_bodies = excluded.max_bodies",
            [name, token_id, now, now, info.get("solidcraft_version"), info.get("renderer"), info.get("gpu"),
             info.get("mem_gb"), info.get("max_bodies")])


def _touch(name: str, **changes: Any) -> None:
    changes["last_seen"] = _iso(_now())
    sets_ = ", ".join(f"{k} = ?" for k in changes)
    with db.connect() as conn:
        conn.execute(f"UPDATE helpers SET {sets_} WHERE name = ?", [*changes.values(), name])


def list_helpers() -> list[dict[str, Any]]:
    window = int(_setting("helpers_seen_window") or 10)
    cutoff = _iso(_now() - timedelta(minutes=window))
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM helpers ORDER BY last_seen DESC").fetchall()]
        for r in rows:
            r["active"] = r["last_seen"] >= cutoff
            r.pop("token_id", None)
            job = conn.execute(
                "SELECT j.id, j.progress, j.message, d.path FROM jobs j LEFT JOIN designs d ON d.id = j.design_id "
                "WHERE j.status = 'running' AND j.helper = ? ORDER BY j.id LIMIT 1", [r["name"]]).fetchone()
            r["current"] = dict(job) if job else None
            r["current_job"] = job["id"] if job else None
    return rows


def host_version() -> str | None:
    return solidcraft.version()


# ---------------------------------------------------------------- leases

def _lease(conn, job_id: int) -> dict | None:
    r = conn.execute("SELECT l.*, j.status, j.attempts, j.design_id AS jdesign, j.helper AS jhelper "
                     "FROM helper_leases l JOIN jobs j ON j.id = l.job_id WHERE l.job_id = ?", [job_id]).fetchone()
    return dict(r) if r else None


def own(job_id: int, name: str, token_id: str | None) -> dict:
    """The lease of a job this helper holds (still running), or NotYours."""
    with db.connect() as conn:
        lease = _lease(conn, job_id)
    if (not lease or lease["status"] != "running" or lease["jhelper"] != name or lease["helper"] != name
            or (lease["token_id"] and token_id and lease["token_id"] != token_id)):
        raise NotYours(f"job {job_id} is not running on {name}")
    return lease


def still_ours(job_id: int, name: str) -> bool:
    with db.connect() as conn:
        r = conn.execute("SELECT 1 FROM jobs WHERE id = ? AND status = 'running' AND helper = ?",
                         [job_id, name]).fetchone()
    return r is not None


def _work(design_id: str) -> Path:
    return get_settings().work_dir / design_id


def _drop_lease(job_id: int, design_id: str | None, *, keep_stage: bool = False) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM helper_leases WHERE job_id = ?", [job_id])
        conn.execute("UPDATE helpers SET current_job = NULL WHERE current_job = ?", [job_id])
    if design_id:
        with db.connect() as conn:  # another render of the design may have its work folder now
            busy = conn.execute("SELECT 1 FROM jobs WHERE status = 'running' AND design_id = ? AND id != ?",
                                [design_id, job_id]).fetchone()
        if busy:
            return
        shutil.rmtree(_work(design_id), ignore_errors=True)
        if not keep_stage:
            try:
                d = jobs.get_design(design_id)
                sets.discard(sets.staging_dir(design_id, sets.set_id_for(d["blob_sha"])))
            except KeyError:
                pass


def requeue(job_id: int, why: str) -> bool:
    """Put a helper's running job back in the queue (it keeps its age and its attempts)."""
    with db.connect() as conn:
        lease = _lease(conn, job_id)
        n = conn.execute("UPDATE jobs SET status = 'queued', started_at = NULL, helper = NULL, progress = 0, "
                         "message = ? WHERE id = ? AND status = 'running'", [why[:500], job_id]).rowcount
        if n and lease:
            conn.execute("UPDATE designs SET status = 'queued' WHERE id = ? AND status = 'rendering'",
                         [lease["design_id"]])
    _drop_lease(job_id, lease["design_id"] if lease else None)
    jobs._wake.set()
    return bool(n)


def fail_job(job_id: int, error: str, helper: str | None = None) -> bool:
    """A helper's render failed: the job and its design are failed with the error."""
    with db.connect() as conn:
        lease = _lease(conn, job_id)
        n = conn.execute("UPDATE jobs SET status = 'failed', finished_at = ?, error = ? WHERE id = ? "
                         "AND status = 'running'", [db.now(), error[:2000], job_id]).rowcount
        if helper:
            conn.execute("UPDATE helpers SET jobs_failed = jobs_failed + 1, last_error = ? WHERE name = ?",
                         [error[:500], helper])
    if n and lease:
        try:
            jobs.render_failed(lease["design_id"], error)
        except KeyError:
            pass
    _drop_lease(job_id, lease["design_id"] if lease else None)
    return bool(n)


def reap_expired() -> int:
    """Requeue (or, after `helpers_max_attempts` claims, fail) helper jobs whose lease ran
    out, and forget leases of jobs that ended (cancelled while a helper had them)."""
    now = _iso(_now())
    max_attempts = int(_setting("helpers_max_attempts") or 2)
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT l.job_id, l.helper, l.design_id, l.lease_until, j.status, j.attempts FROM helper_leases l "
            "LEFT JOIN jobs j ON j.id = l.job_id").fetchall()]
    n = 0
    for r in rows:
        if r["status"] != "running":
            _drop_lease(r["job_id"], r["design_id"], keep_stage=True)
            continue
        if r["lease_until"] >= now:
            continue
        n += 1
        why = f"render helper {r['helper']} stopped answering (its lease ran out)"
        log.warning("job %s: %s", r["job_id"], why)
        _touch_quiet(r["helper"], last_error=why)
        if (r["attempts"] or 0) < max_attempts:
            requeue(r["job_id"], why + "; queued again")
        else:
            fail_job(r["job_id"], f"{why}, after {r['attempts']} attempts")
    return n


def _touch_quiet(name: str, **changes: Any) -> None:
    sets_ = ", ".join(f"{k} = ?" for k in changes)
    with db.connect() as conn:
        conn.execute(f"UPDATE helpers SET {sets_} WHERE name = ?", [*changes.values(), name])


if reap_expired not in jobs.HOUSEKEEPING:
    jobs.HOUSEKEEPING.append(reap_expired)


# ---------------------------------------------------------------- claim

def _too_big(design_id: str, max_bodies: int | None) -> bool:
    if not max_bodies:
        return False
    s = sets.latest_set(design_id)
    bodies = ((s or {}).get("report") or {}).get("bodies")
    return bool(bodies and bodies > max_bodies)


def claim(name: str, token_id: str | None, info: dict[str, Any]) -> dict | None:
    """Lease the oldest queued render to this helper and prepare its inputs. None when
    there is nothing for it. Raises Refused for a different SolidCraft."""
    name = clean_name(name)
    note_seen(name, token_id, info)
    reap_expired()
    mine = host_version()
    theirs = str(info.get("solidcraft_version") or "").strip()
    if _setting("helpers_require_same_solidcraft") and mine and theirs != mine:
        why = (f"this server runs SolidCraft {mine} and {name} runs {theirs or 'an unknown version'}; "
               "renders must match, so install the same version on the helper "
               "(or turn off helpers_require_same_solidcraft)")
        _touch_quiet(name, refused=why)
        raise Refused(why)
    _touch_quiet(name, refused=None)
    lease_s = int(_setting("helpers_lease_seconds") or 300)
    skipped: list[int] = []
    for _ in range(20):
        now = _now()
        not_in = f" AND id NOT IN ({','.join('?' * len(skipped))})" if skipped else ""
        with db.connect() as conn:
            job = db.row(conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ?, helper = ?, attempts = attempts + 1, "
                "progress = 0, message = ? WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND "
                f"kind = 'render' AND {jobs.NOT_BUSY}{not_in} ORDER BY id LIMIT 1) RETURNING *",
                [_iso(now), name, f"claimed by {name}", *skipped]).fetchone())
            if job is None:
                return None
            if _too_big(job["design_id"], info.get("max_bodies")):
                conn.execute("UPDATE jobs SET status = 'queued', started_at = NULL, helper = NULL, "
                             "attempts = attempts - 1, message = '' WHERE id = ?", [job["id"]])
                skipped.append(job["id"])
                continue
            conn.execute("INSERT OR REPLACE INTO helper_leases (job_id, helper, token_id, design_id, lease_until, "
                         "claimed_at) VALUES (?,?,?,?,?,?)",
                         [job["id"], name, token_id, job["design_id"], _iso(now + timedelta(seconds=lease_s)),
                          _iso(now)])
            conn.execute("UPDATE helpers SET current_job = ? WHERE name = ?", [job["id"], name])
        out = _prepare(job, name, lease_s)
        if out is not None:
            return out
    return None


def _prepare(job: dict, name: str, lease_s: int) -> dict | None:
    """Download the claimed job's design here (the server has the forge tokens) and
    snapshot its settings. None when the job ended here (already rendered, or failed)."""
    design_id = job["design_id"]
    try:
        design = jobs.get_design(design_id)
    except KeyError:
        fail_job(job["id"], f"no design {design_id}")
        return None
    if not job["force"] and design["rendered_sha"] == design["blob_sha"]:
        with db.connect() as conn:
            db.update(conn, "designs", design_id, status="rendered")
            conn.execute("UPDATE jobs SET status = 'done', finished_at = ?, progress = 1, message = ? "
                         "WHERE id = ? AND status = 'running'",
                         [db.now(), "already rendered at this version", job["id"]])
        _drop_lease(job["id"], design_id, keep_stage=True)
        return None
    with db.connect() as conn:
        db.update(conn, "designs", design_id, status="rendering", error=None, updated_at=db.now())
    try:
        local, _opts, snapshot = jobs.prepare_render(design)
    except Exception as exc:  # noqa: BLE001 - as a host render: the job fails with the reason
        log.warning("preparing job %s for %s failed: %s", job["id"], name, exc)
        fail_job(job["id"], str(exc) or exc.__class__.__name__)
        return None
    try:
        from ..inputs import repo_config
        snapshot["_repo_config"] = repo_config.get(design_id)
    except Exception:  # noqa: BLE001
        snapshot["_repo_config"] = {}
    work = _work(design_id)
    design_file = local.relative_to(work).as_posix()
    with db.connect() as conn:
        conn.execute("UPDATE helper_leases SET snapshot = ?, design_file = ? WHERE job_id = ?",
                     [json.dumps(snapshot), design_file, job["id"]])
        current = db.row(conn.execute("SELECT * FROM jobs WHERE id = ?", [job["id"]]).fetchone())
    if not current or current["status"] != "running" or current["helper"] != name:
        _drop_lease(job["id"], design_id, keep_stage=True)  # cancelled while we downloaded
        return None
    d = jobs.design_of(snapshot)
    stem = jobs.slug(d["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0])
    return {"job": current, "design": snapshot["design"], "settings_snapshot": snapshot,
            "design_file": design_file, "stem": stem, "set_id": sets.set_id_for(d["blob_sha"]),
            "lease_s": lease_s}


# ---------------------------------------------------------------- inputs

def inputs_tar(job_id: int, name: str, token_id: str | None) -> Path:
    """A tar of the job's work folder (the design, its linked files, sidecars)."""
    lease = own(job_id, name, token_id)
    work = _work(lease["design_id"])
    if not work.is_dir():
        raise NotYours(f"job {job_id} has no inputs any more")
    fd, tmp = tempfile.mkstemp(prefix=f"inputs-{job_id}-", suffix=".tar", dir=get_settings().work_dir)
    with open(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w") as tar:
        for p in sorted(work.rglob("*")):
            if p.is_file() and not p.is_symlink():
                tar.add(p, arcname=p.relative_to(work).as_posix(), recursive=False)
    return Path(tmp)


def repo_file(job_id: int, name: str, token_id: str | None, path: str) -> bytes | None:
    lease = own(job_id, name, token_id)
    snapshot = json.loads(lease["snapshot"] or "{}")
    row = snapshot.get("design") or {}
    from ..specs import meta
    return meta.fetch_repo_file(row, path)


# ---------------------------------------------------------------- progress, fail

def progress(job_id: int, name: str, token_id: str | None, fraction: float, message: str) -> dict:
    try:
        own(job_id, name, token_id)
    except NotYours:
        with db.connect() as conn:
            gone = conn.execute("SELECT l.design_id FROM helper_leases l JOIN jobs j ON j.id = l.job_id "
                                "WHERE l.job_id = ? AND l.helper = ? AND j.status != 'running'",
                                [job_id, name]).fetchone()
        if gone:  # cancelled: clean up what we prepared for it
            _drop_lease(job_id, gone["design_id"], keep_stage=True)
        _touch_quiet(name, last_seen=_iso(_now()), current_job=None)
        return {"cancel": True}
    lease_s = int(_setting("helpers_lease_seconds") or 300)
    f = min(1.0, max(0.0, float(fraction or 0)))
    with db.connect() as conn:
        conn.execute("UPDATE helper_leases SET lease_until = ? WHERE job_id = ?",
                     [_iso(_now() + timedelta(seconds=lease_s)), job_id])
        conn.execute("UPDATE jobs SET progress = ?, message = ? WHERE id = ? AND status = 'running'",
                     [round(0.02 + 0.86 * f, 3), str(message or "")[:500], job_id])
    _touch(name, current_job=job_id)
    return {"cancel": False}


def fail(job_id: int, name: str, token_id: str | None, error: str, retry: bool = False) -> dict:
    try:
        lease = own(job_id, name, token_id)
    except NotYours:
        return {"ignored": True}
    error = str(error or "the helper failed")[:2000]
    # a helper that was stopped isn't in trouble: only a real failure is its last error
    _touch(name, current_job=None, **({} if retry else {"last_error": error[:500]}))
    max_attempts = int(_setting("helpers_max_attempts") or 2)
    if retry and (lease["attempts"] or 0) < max_attempts:
        requeue(job_id, f"{name}: {error}; queued again")
        return {"requeued": True}
    fail_job(job_id, f"{name}: {error}" if retry else error, helper=name)
    return {"requeued": False}


# ---------------------------------------------------------------- result

class BadUpload(ValueError):
    pass


def _safe(name: str) -> str:
    p = PurePosixPath(name)
    if not name or p.is_absolute() or any(part in ("", "..") for part in p.parts) or "\\" in name:
        raise BadUpload(f"unsafe path in the upload: {name!r}")
    return p.as_posix().removeprefix("./")


def _outputs(raw: Any, files: dict[str, int]) -> list[Output]:
    known = {f.name for f in fields(Output)}
    if not isinstance(raw, list):
        raise BadUpload("the manifest's outputs must be a list")
    out = []
    for o in raw:
        if not isinstance(o, dict) or set(o) - known or not {"file", "style", "variant"} <= set(o):
            raise BadUpload(f"bad output in the manifest: {str(o)[:200]}")
        o = {**o, "file": _safe(str(o["file"]))}
        if o["file"] not in files:
            raise BadUpload(f"output {o['file']} is not in the upload")
        out.append(Output(file=o["file"], style=str(o["style"]), variant=str(o["variant"]),
                          width=int(o.get("width") or 0), height=int(o.get("height") or 0)))
    return out


def unpack_result(tar_path: Path, stage: Path) -> tuple[list[Output], dict]:
    """Check an uploaded stage tar against its manifest and unpack it into `stage`. Every
    member must be a plain file (or folder) at a safe relative path, listed in the manifest
    with its size; every listed file must be there. Returns the outputs and the report."""
    with tarfile.open(tar_path, "r:*") as tar:
        members = tar.getmembers()
        if not members or members[0].name.removeprefix("./") != MANIFEST or not members[0].isfile():
            raise BadUpload(f"the upload must start with {MANIFEST}")
        fh = tar.extractfile(members[0])
        try:
            manifest = json.loads(fh.read(4 << 20) if fh else b"")
        except ValueError as exc:
            raise BadUpload(f"{MANIFEST} is not JSON") from exc
        listed = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(listed, dict):
            raise BadUpload("the manifest needs files: {name: size}")
        files = {_safe(str(k)): int(v) for k, v in listed.items()}
        seen: dict[str, tarfile.TarInfo] = {}
        for m in members[1:]:
            name = _safe(m.name)
            if m.isdir():
                continue
            if not m.isfile():
                raise BadUpload(f"{name}: only plain files may be uploaded")
            if name not in files:
                raise BadUpload(f"{name} is not in the manifest")
            if m.size != files[name]:
                raise BadUpload(f"{name}: {m.size} bytes, the manifest says {files[name]}")
            if name in seen:
                raise BadUpload(f"{name} is in the upload twice")
            seen[name] = m
        missing = set(files) - set(seen)
        if missing:
            raise BadUpload(f"missing from the upload: {', '.join(sorted(missing)[:5])}")
        if "report.json" not in files:
            raise BadUpload("the upload has no report.json")
        outputs = _outputs(manifest.get("outputs"), files)
        sets.discard(stage)
        stage.mkdir(parents=True)
        root = stage.resolve()
        for name, m in seen.items():
            target = (stage / name).resolve()
            if root not in target.parents:
                raise BadUpload(f"unsafe path in the upload: {name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            with open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)  # type: ignore[arg-type]
    try:
        report = json.loads((stage / "report.json").read_text())
    except ValueError as exc:
        raise BadUpload("report.json is not JSON") from exc
    if not isinstance(report, dict) or "bodies" not in report:
        raise BadUpload("report.json has no bodies count")
    return outputs, report


def accept_result(job_id: int, name: str, token_id: str | None, tar_path: Path) -> dict:
    """File a helper's finished set: unpack and check it, then `jobs.finish_render`."""
    lease = own(job_id, name, token_id)
    design_id = lease["design_id"]
    snapshot = json.loads(lease["snapshot"] or "{}")
    if not snapshot.get("design"):
        raise NotYours(f"job {job_id} was never prepared")
    design = jobs.design_of(snapshot)
    stage = sets.staging_dir(design_id, sets.set_id_for(design["blob_sha"]))
    try:
        outputs, report = unpack_result(tar_path, stage)
    except BadUpload as exc:
        sets.discard(stage)
        fail_job(job_id, f"{name} sent a bad result: {exc}", helper=name)
        raise
    report["host"] = name  # where it was rendered, as this server knows it
    (stage / "report.json").write_text(json.dumps(report, indent=2))
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET progress = 0.9, message = 'filing' WHERE id = ? AND status = 'running'",
                     [job_id])

    def cancelled() -> bool:
        return not still_ours(job_id, name)

    def prog(f: float, m: str) -> None:
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET progress = ?, message = ? WHERE id = ? AND status = 'running'",
                         [round(f, 3), m, job_id])

    try:
        message = jobs.finish_render(design, stage, outputs, report, prog, settings=snapshot, cancelled=cancelled)
    except jobs.JobCancelled:
        jobs._undo_cancelled_render({**jobs.get_design(design_id), "blob_sha": design["blob_sha"]})
        _drop_lease(job_id, design_id, keep_stage=True)
        raise NotYours(f"job {job_id} was cancelled") from None
    except Exception as exc:
        if cancelled():
            jobs._undo_cancelled_render({**jobs.get_design(design_id), "blob_sha": design["blob_sha"]})
            _drop_lease(job_id, design_id, keep_stage=True)
            raise NotYours(f"job {job_id} was cancelled") from exc
        fail_job(job_id, str(exc) or exc.__class__.__name__, helper=name)
        raise
    with db.connect() as conn:
        n = conn.execute("UPDATE jobs SET status = 'done', finished_at = ?, progress = 1, message = ?, error = NULL "
                         "WHERE id = ? AND status = 'running'", [db.now(), message, job_id]).rowcount
        conn.execute("UPDATE helpers SET jobs_done = jobs_done + 1, last_error = NULL WHERE name = ?", [name])
    _drop_lease(job_id, design_id, keep_stage=True)
    _touch(name, current_job=None)
    return {"done": bool(n), "message": message}
