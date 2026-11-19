"""Read-only viewer tokens (F18) and render helper tokens (0.2.1).

The admin token (SK_TOKEN) can do everything. A viewer token, made in Settings → Tokens
(or `sklent token create NAME`), can browse, view and download: every GET under /api
except the token list, and the MCP tools that only read. It can't render, add or change
sources, change settings or call an MCP tool that writes. Tokens are random 35-character
strings (`skv` + 32 letters and digits), shown once; only their SHA-256 is stored.
Revoking one stops it at once.

A token's `scope` is `viewer` (the above) or `helper`: a render helper's token
(`skh` + 32), which may call only the helper protocol (`/api/helpers/claim` and
`/api/helpers/jobs/...`); every other route and all of MCP answer 403 to it.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta

from ... import db

PREFIX = "skv"
PREFIXES = {"viewer": "skv", "helper": "skh"}
SCOPES = tuple(PREFIXES)
ALPHABET = string.ascii_letters + string.digits

SCHEMA = """
CREATE TABLE IF NOT EXISTS inputs_viewer_tokens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    hint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    scope TEXT NOT NULL DEFAULT 'viewer'
);
"""


def migrate(conn) -> None:
    """0.2.1: tokens made before scopes are viewer tokens."""
    db.add_columns(conn, "inputs_viewer_tokens", {"scope": "TEXT NOT NULL DEFAULT 'viewer'"})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(name: str, scope: str = "viewer") -> dict:
    """A new viewer (or helper) token. The returned `token` is the only time it is shown."""
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise ValueError("a token needs a name (up to 80 characters)")
    if scope not in PREFIXES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    token = PREFIXES[scope] + "".join(secrets.choice(ALPHABET) for _ in range(32))
    tid = db.new_id()
    row = {"id": tid, "name": name, "hint": f"{token[:7]}…{token[-4:]}", "created_at": db.now(), "scope": scope}
    with db.connect() as conn:
        conn.execute("INSERT INTO inputs_viewer_tokens (id, name, hash, hint, created_at, scope) VALUES (?,?,?,?,?,?)",
                     [tid, name, _hash(token), row["hint"], row["created_at"], scope])
    return {**row, "token": token, "last_used_at": None, "revoked_at": None}


def list_tokens() -> list[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, name, hint, created_at, last_used_at, revoked_at, scope FROM inputs_viewer_tokens "
            "ORDER BY revoked_at IS NOT NULL, created_at DESC").fetchall()]


def revoke(token_id: str) -> dict:
    with db.connect() as conn:
        n = conn.execute("UPDATE inputs_viewer_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                         [db.now(), token_id]).rowcount
        r = conn.execute("SELECT id, name, hint, created_at, last_used_at, revoked_at, scope "
                         "FROM inputs_viewer_tokens WHERE id = ?", [token_id]).fetchone()
    if r is None:
        raise KeyError(f"no token {token_id}")
    return {**dict(r), "changed": bool(n)}


def lookup(token: str) -> dict | None:
    """The live token with this value ({id, name, scope}), or None. Marks it used (at most
    every 5 min)."""
    if not token.startswith(tuple(PREFIXES.values())):
        return None
    try:
        with db.connect() as conn:
            r = conn.execute("SELECT id, name, last_used_at, scope FROM inputs_viewer_tokens WHERE hash = ? AND "
                             "revoked_at IS NULL", [_hash(token)]).fetchone()
            if r is None:
                return None
            last = r["last_used_at"]
            if not last or datetime.fromisoformat(last) < datetime.now(UTC) - timedelta(minutes=5):
                conn.execute("UPDATE inputs_viewer_tokens SET last_used_at = ? WHERE id = ?", [db.now(), r["id"]])
    except Exception:  # noqa: BLE001 - no table (feature off) means no viewer tokens
        return None
    scope = r["scope"] if r["scope"] in PREFIXES else "viewer"
    if not token.startswith(PREFIXES[scope]):  # a token works only in the scope it was made for
        return None
    return {"id": r["id"], "name": r["name"], "scope": scope}
