"""F26 Kist review board: a design's (or a source's) render set laid out as a Kist board,
and, only when asked, a Kist share link to that board with guest proofing.

Kist v2.0.0 API used (kist/api/boards.py, shares.py, proofing.py):
- POST /api/boards {name, item_ids, layout: grid}: a board with those items in order;
  DELETE /api/boards/{id} moves it to Kist's trash.
- POST /api/shares {target_kind: board, target_id, title, password?, expires_in_days,
  allow_download}: a public /s/<slug> page (needs a write-scoped Kist token);
  POST /api/shares/{id}/revoke ends it.
- PATCH /api/shares/{id}/proofing {enabled: true}: guests can pick, heart and comment;
  their feedback lands in Kist's Feedback inbox.

Outbound rule: the board stays inside your Kist. A share link is public (anyone with the
URL), so it is off by default (`outputs_review_share_links`), made only by an explicit
click or tool call, never automatically, and can be revoked.
"""

from __future__ import annotations

from typing import Any

import httpx

from ... import db, jobs, sets
from ...kist import Kist, KistError
from . import photos
from .common import OutputError, commit_of, design, kist_items_for, log, stem_of, the_set

SETTINGS = {
    "outputs_review_share_links": (False, bool),
    "outputs_review_proofing": (True, bool),
    "outputs_review_share_days": (30, lambda v: _days(v)),
    "outputs_review_allow_download": (False, bool),
}


def _days(v: Any) -> int:
    v = int(v)
    if not 0 <= v <= 365:
        raise ValueError("outputs_review_share_days must be 0 (never expires) to 365")
    return v


def register() -> None:
    for key, (default, validate) in SETTINGS.items():
        jobs.register_setting(key, default, validate)


def _kist(kist: Kist | None = None) -> Kist:
    kist = kist or Kist()
    if not kist.enabled:
        raise OutputError("Kist is off (SK_KIST_URL is empty), so there is no board to make", 409)
    return kist


def _call(kist: Kist, method: str, path: str, **kw) -> dict:
    try:
        r = kist.http.request(method, f"{kist.url}/api{path}", **kw)
    except httpx.HTTPError as exc:
        raise OutputError(f"Kist didn't answer: {exc}", 502) from exc
    if r.status_code >= 400:
        raise OutputError(f"Kist {method} {path}: {r.status_code} {r.text[:300]}", 502)
    return r.json() if r.content else {}


# ---------------------------------------------------------------- what goes on a board

ORDER = {"photo": 0, "social": 1, "hires": 2, "1080p": 3, "reel": 4, "gif": 5, "discord": 6}


def design_item_ids(design_id: str, set_id: str | None = None) -> list[str]:
    """Kist items of a design's set, in a review order: real photos, stills, clips, then
    everything else (feature outputs, exported copies), shaded before wireframe."""
    d = design(design_id)
    s = the_set(design_id, set_id)
    files = {f["file"]: f for f in s.get("files") or []}
    items = []
    for it in d.get("kist_items") or []:
        f = files.get(it["file"], {})
        items.append((ORDER.get(f.get("variant"), 7), 0 if f.get("style") == "shaded" else 1, it["file"], it["id"]))
    for it in kist_items_for(design_id, s["id"]):
        items.append((8, 0, it["file"], it["item_id"]))
    ph = [(0, i, p["name"], p["kist_item_id"]) for i, p in enumerate(photos.list_photos(design_id))
          if p.get("kist_item_id")]
    seen, out = set(), []
    for *_, item_id in sorted(ph) + sorted(items):
        if item_id and item_id not in seen:
            seen.add(item_id)
            out.append(item_id)
    return out


def source_item_ids(source_id: str) -> list[str]:
    """One item per rendered design of a source: its shaded square still (or first item)."""
    jobs.get_source(source_id)
    with db.connect() as conn:
        ds = db.rows(conn.execute("SELECT * FROM designs WHERE source_id = ? AND status != 'removed' ORDER BY path",
                                  [source_id]).fetchall())
    out = []
    for d in ds:
        s = sets.latest_set(d["id"])
        if not s or not d.get("kist_items"):
            continue
        files = {f["file"]: f for f in s.get("files") or []}
        best = sorted(d["kist_items"], key=lambda it: (
            ORDER.get(files.get(it["file"], {}).get("variant"), 7),
            0 if files.get(it["file"], {}).get("style") == "shaded" else 1))
        if best:
            out.append(best[0]["id"])
    return out


# ---------------------------------------------------------------- records

def _latest(scope: str, target_id: str) -> dict | None:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM outputs_review WHERE scope = ? AND target_id = ? ORDER BY created_at DESC, "
                         "rowid DESC LIMIT 1", [scope, target_id]).fetchone()
    return dict(r) if r else None


def _out(r: dict | None, kist: Kist | None = None) -> dict:
    s = jobs.get_all_settings()
    k = kist or Kist()
    base = {"kist_on": k.enabled, "share_links_allowed": bool(s.get("outputs_review_share_links")),
            "proofing": bool(s.get("outputs_review_proofing")), "share_days": s.get("outputs_review_share_days"),
            "allow_download": bool(s.get("outputs_review_allow_download")),
            "kist_url": k.url or None}
    if not r:
        return {**base, "board": None, "share": None}
    board = {"id": r["board_id"], "name": r["board_name"], "items": r["items"], "set_id": r["set_id"],
             "url": f"{k.url}/board/{r['board_id']}" if k.url else None, "created_at": r["created_at"]} \
        if r["board_id"] else None
    share = None
    if r["share_id"]:
        share = {"id": r["share_id"], "url": r["share_url"], "expires_at": r["share_expires_at"],
                 "proofing": bool(r["proofing"]), "shared_at": r["shared_at"], "revoked_at": r["revoked_at"],
                 "active": not r["revoked_at"]}
    return {**base, "board": board, "share": share}


def get(scope: str, target_id: str) -> dict:
    _target(scope, target_id)
    return _out(_latest(scope, target_id))


def _target(scope: str, target_id: str) -> str:
    """The board's name, checking the target exists."""
    if scope == "design":
        d = design(target_id)
        s = the_set(target_id)
        return f"{d['repo']} / {stem_of(d)} @ {commit_of(d, s)[:7]}"
    if scope == "source":
        src = jobs.get_source(target_id)
        return f"{src['repo'] or src['owner']} (all designs)"
    raise OutputError("scope is design or source", 422)


# ---------------------------------------------------------------- board

def make_board(scope: str, target_id: str, *, kist: Kist | None = None) -> dict:
    """Lay the set out as a Kist board (a new one per set; the same set again returns the
    board already made, unless it was deleted in Kist)."""
    kist = _kist(kist)
    name = _target(scope, target_id)
    set_id = the_set(target_id)["id"] if scope == "design" else None
    ids = design_item_ids(target_id) if scope == "design" else source_item_ids(target_id)
    if not ids:
        raise OutputError("nothing of this set is in Kist yet: render it with Kist on first", 409)
    prev = _latest(scope, target_id)
    if prev and prev["board_id"] and prev["set_id"] == set_id and prev["items"] == len(ids):
        r = kist.http.get(f"{kist.url}/api/boards/{prev['board_id']}")
        if r.status_code == 200 and not r.json().get("deleted_at"):
            return _out(prev, kist)
    board = _call(kist, "POST", "/boards", json={"name": name[:200], "item_ids": ids[:500], "layout": "grid"})
    rid = db.new_id()
    with db.connect() as conn:
        conn.execute("INSERT INTO outputs_review (id, scope, target_id, set_id, board_id, board_name, items, "
                     "created_at) VALUES (?,?,?,?,?,?,?,?)",
                     [rid, scope, target_id, set_id, board["id"], board.get("name", name), min(len(ids), 500),
                      db.now()])
    return _out(_latest(scope, target_id), kist)


def delete_board(scope: str, target_id: str, *, kist: Kist | None = None) -> dict:
    """Revoke the share (if any) and move the board to Kist's trash."""
    kist = _kist(kist)
    r = _latest(scope, target_id)
    if not r or not r["board_id"]:
        raise OutputError("no board for this", 404)
    if r["share_id"] and not r["revoked_at"]:
        revoke(scope, target_id, kist=kist)
    resp = kist.http.delete(f"{kist.url}/api/boards/{r['board_id']}")
    if resp.status_code not in (200, 404):
        raise OutputError(f"Kist DELETE board: {resp.status_code} {resp.text[:200]}", 502)
    with db.connect() as conn:
        conn.execute("UPDATE outputs_review SET board_id = NULL WHERE id = ?", [r["id"]])
    return _out(_latest(scope, target_id), kist)


# ---------------------------------------------------------------- share link

def create_share(scope: str, target_id: str, *, password: str | None = None, kist: Kist | None = None) -> dict:
    """Make a public Kist share link to the board, with guest proofing if the setting
    says so. Refused unless `outputs_review_share_links` is on. Only ever called from an
    explicit request: nothing creates a share link on its own."""
    s = jobs.get_all_settings()
    if not s.get("outputs_review_share_links"):
        raise OutputError("share links are off: turn on Settings → Review → Share links first. A share link is "
                          "a public page on your Kist that anyone with the URL can open.", 403)
    kist = _kist(kist)
    r = _latest(scope, target_id)
    if not r or not r["board_id"] or (scope == "design" and r["set_id"] != the_set(target_id)["id"]):
        make_board(scope, target_id, kist=kist)
        r = _latest(scope, target_id)
    assert r is not None
    if r["share_id"] and not r["revoked_at"]:
        return _out(r, kist)
    body = {"target_kind": "board", "target_id": r["board_id"], "title": (r["board_name"] or "")[:200],
            "expires_in_days": s.get("outputs_review_share_days", 30),
            "allow_download": bool(s.get("outputs_review_allow_download"))}
    if password:
        body["password"] = password
    share = _call(kist, "POST", "/shares", json=body)
    proofing = False
    if s.get("outputs_review_proofing"):
        try:
            _call(kist, "PATCH", f"/shares/{share['id']}/proofing", json={"enabled": True})
            proofing = True
        except OutputError as exc:
            log.warning("turning on proofing for share %s failed: %s", share["id"], exc)
    with db.connect() as conn:
        conn.execute("UPDATE outputs_review SET share_id = ?, share_url = ?, share_expires_at = ?, proofing = ?, "
                     "shared_at = ?, revoked_at = NULL WHERE id = ?",
                     [share["id"], share.get("url"), str(share.get("expires_at") or "") or None, int(proofing),
                      db.now(), r["id"]])
    return _out(_latest(scope, target_id), kist)


def revoke(scope: str, target_id: str, *, kist: Kist | None = None) -> dict:
    kist = _kist(kist)
    r = _latest(scope, target_id)
    if not r or not r["share_id"]:
        raise OutputError("no share link to revoke", 404)
    resp = kist.http.post(f"{kist.url}/api/shares/{r['share_id']}/revoke")
    if resp.status_code not in (200, 404):
        raise OutputError(f"Kist revoke: {resp.status_code} {resp.text[:200]}", 502)
    with db.connect() as conn:
        conn.execute("UPDATE outputs_review SET revoked_at = ? WHERE id = ?", [db.now(), r["id"]])
    return _out(_latest(scope, target_id), kist)


def share_link(design_id: str) -> str | None:
    """The live Kist share link for a design's review board, or None. Never creates one.
    (The cross-feature hook P's review comment calls.)"""
    try:
        r = _latest("design", design_id)
    except Exception:  # noqa: BLE001 - a hook must not break its caller
        return None
    if not r or not r["share_url"] or r["revoked_at"]:
        return None
    exp = r.get("share_expires_at")
    if exp:
        from datetime import UTC, datetime  # noqa: PLC0415
        try:
            when = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when < datetime.now(UTC):
                return None
        except ValueError:
            pass
    return r["share_url"]


__all__ = ["KistError", "create_share", "delete_board", "get", "make_board", "revoke", "share_link"]
