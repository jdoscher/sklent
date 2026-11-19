"""Class sets and due-date snapshots (F28).

A class set is an account/org source with a repo-name prefix, the way GitHub Classroom
names an assignment's repos (`bracket-hw-<username>`): the source URL carries
`?prefix=bracket-hw-`. Any source can carry a deadline (ISO 8601): each repo then renders
the newest commit at or before it (by committer date), and later pushes show as
"changed after due" without re-rendering. A roster (GitHub usernames, `username, Display
name`, or repo-name patterns with `*`) lists who is expected, so the set shows who has
no submission.
"""

from __future__ import annotations

import fnmatch
import json
from datetime import UTC
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ... import db
from ...sources import parse_time

SCHEMA = """
CREATE TABLE IF NOT EXISTS inputs_source_options (
    source_id TEXT PRIMARY KEY,
    title TEXT,
    deadline TEXT,
    roster TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inputs_submissions (
    source_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    commit_sha TEXT,
    committed_at TEXT,
    head_sha TEXT,
    designs INTEGER NOT NULL DEFAULT 0,
    scanned_at TEXT NOT NULL,
    PRIMARY KEY (source_id, owner, repo)
);
"""


def prefix_of(source: dict) -> str | None:
    q = parse_qs(urlsplit(source.get("url") or "").query)
    return (q.get("prefix") or [None])[0]


def clean_deadline(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        return parse_time(value).astimezone(UTC).isoformat(timespec="seconds")
    except ValueError as exc:
        raise ValueError(f"deadline must be an ISO 8601 date-time: {exc}") from exc


def clean_roster(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list):
        raise ValueError("roster must be a list of usernames or patterns")
    out = []
    for v in value:
        v = str(v).strip()
        if v and not v.startswith("#") and v.lower() not in ("username", "username, display name"):
            out.append(v)
    return out


def options(source_id: str) -> dict:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM inputs_source_options WHERE source_id = ?", [source_id]).fetchone()
    if not r:
        return {"title": None, "deadline": None, "roster": []}
    return {"title": r["title"], "deadline": r["deadline"], "roster": json.loads(r["roster"] or "[]")}


def set_options(source_id: str, *, title: str | None = None, deadline: str | None = None,
                roster: Any = None) -> dict:
    cur = options(source_id)
    new = {"title": cur["title"] if title is None else (title.strip() or None),
           "deadline": cur["deadline"] if deadline is None else clean_deadline(deadline),
           "roster": cur["roster"] if roster is None else clean_roster(roster)}
    with db.connect() as conn:
        conn.execute("INSERT INTO inputs_source_options (source_id, title, deadline, roster, updated_at) "
                     "VALUES (?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET title = excluded.title, "
                     "deadline = excluded.deadline, roster = excluded.roster, updated_at = excluded.updated_at",
                     [source_id, new["title"], new["deadline"], json.dumps(new["roster"]), db.now()])
    return new


def due_ref(ref: str, deadline: str) -> str:
    """The design key of a snapshot: `main@2026-11-20T23:59Z` (separate from main's own row)."""
    return f"{ref}@{parse_time(deadline).astimezone(UTC).strftime('%Y-%m-%dT%H:%MZ')}"


def record(source_id: str, owner: str, repo: str, commit: str | None, committed_at: str | None,
           head: str | None, designs: int) -> None:
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO inputs_submissions (source_id, owner, repo, commit_sha, committed_at,"
                     " head_sha, designs, scanned_at) VALUES (?,?,?,?,?,?,?,?)",
                     [source_id, owner, repo, commit, committed_at, head, designs, db.now()])


def forget_others(source_id: str, keep: set[tuple[str, str]]) -> None:
    with db.connect() as conn:
        for r in conn.execute("SELECT owner, repo FROM inputs_submissions WHERE source_id = ?", [source_id]).fetchall():
            if (r["owner"], r["repo"]) not in keep:
                conn.execute("DELETE FROM inputs_submissions WHERE source_id = ? AND owner = ? AND repo = ?",
                             [source_id, r["owner"], r["repo"]])


def submission_for(source_id: str, owner: str, repo: str) -> dict | None:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM inputs_submissions WHERE source_id = ? AND owner = ? AND repo = ?",
                         [source_id, owner, repo]).fetchone()
    if not r:
        return None
    out = dict(r)
    out["after_due"] = bool(out["head_sha"] and out["commit_sha"] and out["head_sha"] != out["commit_sha"])
    return out


def is_class(source: dict, opts: dict | None = None) -> bool:
    opts = opts or options(source["id"])
    return bool(prefix_of(source) or opts["roster"] or opts["deadline"])


def _student(entry: str) -> tuple[str, str]:
    """`user` or `user, Display Name[, section]` → (user, display)."""
    parts = [p.strip() for p in entry.split(",")]
    return parts[0], (parts[1] if len(parts) > 1 and parts[1] else parts[0])


def class_view(source_id: str) -> dict[str, Any]:
    """A class set: every expected student (roster) or every repo found, with what they
    handed in by the deadline."""
    from ... import jobs

    source = jobs.get_source(source_id)
    opts = options(source_id)
    prefix = prefix_of(source) or ""
    with db.connect() as conn:
        subs = [dict(r) for r in conn.execute(
            "SELECT * FROM inputs_submissions WHERE source_id = ? ORDER BY repo", [source_id]).fetchall()]
        counts = {(r["owner"], r["repo"]): (r["n"], r["rendered"]) for r in conn.execute(
            "SELECT owner, repo, COUNT(*) n, SUM(status = 'rendered') rendered FROM designs WHERE source_id = ? AND "
            "status != 'removed' GROUP BY 1, 2", [source_id]).fetchall()}
    by_repo = {s["repo"].lower(): s for s in subs}
    seen_repos = {(o, r) for o, r in counts}
    for o, r in seen_repos:  # sources without a deadline record nothing at scan; count designs instead
        by_repo.setdefault(r.lower(), {"owner": o, "repo": r, "commit_sha": None, "committed_at": None,
                                       "head_sha": None, "designs": counts[(o, r)][0]})

    def entry(student: str, display: str, sub: dict | None) -> dict:
        if sub is None:
            status = "missing"
        elif opts["deadline"] and not sub.get("commit_sha"):
            status = "late"
        elif not sub.get("designs"):
            status = "empty"
        else:
            status = "submitted"
        n, rendered = counts.get((sub["owner"], sub["repo"]), (0, 0)) if sub else (0, 0)
        return {"student": student, "display": display, "repo": sub["repo"] if sub else None,
                "commit": (sub or {}).get("commit_sha"), "committed_at": (sub or {}).get("committed_at"),
                "after_due": bool(sub and sub.get("head_sha") and sub.get("commit_sha")
                                  and sub["head_sha"] != sub["commit_sha"]),
                "designs": n, "rendered": rendered or 0, "status": status}

    students = []
    used: set[str] = set()
    for item in opts["roster"]:
        if any(c in item for c in "*?["):
            hits = [k for k in by_repo if fnmatch.fnmatch(k, item.lower())]
            used.update(hits)
            students.append(entry(item, item, by_repo[hits[0]] if hits else None))
            continue
        user, display = _student(item)
        u = user.lower()
        key = next((k for k in by_repo if k == f"{prefix}{u}".lower() or k.endswith(f"-{u}") or k == u), None)
        if key:
            used.add(key)
        students.append(entry(user, display, by_repo.get(key) if key else None))
    extra = [k for k in sorted(by_repo) if k not in used]
    if not opts["roster"]:
        for k in extra:
            name = by_repo[k]["repo"]
            student = name[len(prefix):] if prefix and name.lower().startswith(prefix.lower()) else name
            students.append(entry(student, student, by_repo[k]))
        extra = []
    submitted = sum(1 for s in students if s["status"] == "submitted")
    return {"source_id": source_id, "title": opts["title"] or (prefix.rstrip("-_ ") or source["owner"]),
            "owner": source["owner"], "prefix": prefix or None, "deadline": opts["deadline"],
            "roster": opts["roster"], "expected": len(students), "submitted": submitted,
            "missing": [s["display"] for s in students if s["status"] != "submitted"],
            "students": students, "unlisted": [by_repo[k]["repo"] for k in extra]}
