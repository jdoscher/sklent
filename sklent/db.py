"""SQLite state: sources, discovered designs, the job queue, and render settings.

Single user, one process: a fresh connection per unit of work is plenty, and WAL
keeps the web API reading while the worker writes.
"""

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,          -- github | forgejo
    host TEXT NOT NULL,
    kind TEXT NOT NULL,              -- account | repo
    owner TEXT NOT NULL,
    repo TEXT,
    ref TEXT,
    path TEXT,                       -- a file or folder inside the repo, or NULL
    exclude TEXT NOT NULL DEFAULT '[]',
    auto_render INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    scanned_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS designs (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    ref TEXT NOT NULL,
    path TEXT NOT NULL,
    html_url TEXT NOT NULL,
    blob_sha TEXT NOT NULL,
    commit_sha TEXT,
    size INTEGER,
    status TEXT NOT NULL DEFAULT 'new',  -- new | queued | rendering | rendered | failed | removed
    rendered_sha TEXT,
    rendered_at TEXT,
    render_dir TEXT,
    files TEXT NOT NULL DEFAULT '[]',
    kist_folder_id TEXT,
    kist_items TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (source_id, owner, repo, path)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                  -- scan | render
    source_id TEXT,
    design_id TEXT,
    force INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

JSON_COLUMNS = {"exclude", "files", "kist_items"}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return secrets.token_hex(6)


def _connect() -> sqlite3.Connection:
    path = get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


LEGACY_DB_NAME = "look-askew.db"  # the app was called look-askew until 2026-10-31


def _adopt_legacy_db() -> None:
    """Rename a look-askew.db left by the old name, once, so existing state carries over."""
    path = get_settings().db_path
    legacy = path.with_name(LEGACY_DB_NAME)
    if path.exists() or not legacy.exists():
        return
    for suffix in ("", "-wal", "-shm"):
        old = legacy.with_name(legacy.name + suffix)
        if old.exists():
            old.rename(path.with_name(path.name + suffix))


def init() -> None:
    _adopt_legacy_db()
    with connect() as conn:
        conn.executescript(SCHEMA)
        # A job the process died during will never finish; requeue it.
        conn.execute("UPDATE jobs SET status = 'queued', started_at = NULL WHERE status = 'running'")
        conn.execute("UPDATE designs SET status = 'queued' WHERE status = 'rendering'")


def row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    out = dict(r)
    for key in JSON_COLUMNS & out.keys():
        out[key] = json.loads(out[key] or "[]")
    return out


def rows(rs: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row(r) for r in rs]  # type: ignore[misc]


def update(conn: sqlite3.Connection, table: str, id_: Any, **fields: Any) -> None:
    if not fields:
        return
    values = [json.dumps(v) if k in JSON_COLUMNS else v for k, v in fields.items()]
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values, id_])
