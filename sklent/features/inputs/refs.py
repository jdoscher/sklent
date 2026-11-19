"""Branch, tag and pull request renders (F12), and the review comment.

A source's ref can be a branch, a tag, a commit or `pull/<n>`. Designs are keyed by
source + ref, so a PR's designs are separate rows (and sets) from the default branch's.
A PR source renders only the design files the PR adds or changes, plus assemblies that
link a changed file.

`review_comment(source_id, base_url)` builds a Markdown block for the PR thread: each
rendered design's still (after, and before from the base branch when Sklent has it), its
envelope and body count, and links to the turntable GIF and the set. Images point at
this server's file URLs (they need its token), or the link goes to a Kist share link when
the outputs feature hands one over (`sklent.features.outputs.share_link`). Nothing is
posted unless the `inputs_review_post` setting is on AND someone presses Post (or calls
`post_review_comment`); then it is one comment through the forge's API with the
server's GitHub/Forgejo token.
"""

from __future__ import annotations

import json
from typing import Any

from ... import db
from ...sources import PULL_REF

SCHEMA = """
CREATE TABLE IF NOT EXISTS inputs_pulls (
    source_id TEXT PRIMARY KEY,
    number INTEGER NOT NULL,
    title TEXT, state TEXT, html_url TEXT,
    head_sha TEXT, head_ref TEXT, base_sha TEXT, base_ref TEXT,
    files TEXT,
    posted_at TEXT, posted_url TEXT,
    updated_at TEXT NOT NULL
);
"""


def store_pull(source_id: str, info: dict, files: set[str] | None) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO inputs_pulls (source_id, number, title, state, html_url, head_sha, head_ref, base_sha,"
            " base_ref, files, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
            "number = excluded.number, title = excluded.title, state = excluded.state, html_url = excluded.html_url,"
            " head_sha = excluded.head_sha, head_ref = excluded.head_ref, base_sha = excluded.base_sha,"
            " base_ref = excluded.base_ref, files = excluded.files, updated_at = excluded.updated_at",
            [source_id, info["number"], info.get("title"), info.get("state"), info.get("html_url"),
             info.get("head_sha"), info.get("head_ref"), info.get("base_sha"), info.get("base_ref"),
             json.dumps(sorted(files)) if files is not None else None, db.now()])


def pull_of(source_id: str) -> dict | None:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM inputs_pulls WHERE source_id = ?", [source_id]).fetchone()
    if not r:
        return None
    out = dict(r)
    out["files"] = json.loads(out["files"]) if out["files"] else None
    return out


def ref_info(source: dict | None) -> dict | None:
    """What the UI shows for a design's ref: None for the default branch, else
    {kind: pull|ref|due, label, ...}."""
    if not source or not source.get("ref"):
        return None
    m = PULL_REF.match(source["ref"])
    if m:
        p = pull_of(source["id"]) or {}
        return {"kind": "pull", "number": int(m.group(1)), "label": f"PR #{m.group(1)}",
                "title": p.get("title") or "", "url": p.get("html_url") or "", "state": p.get("state") or "",
                "head_ref": p.get("head_ref") or "", "base_ref": p.get("base_ref") or ""}
    ref = source["ref"]
    return {"kind": "ref", "label": ref[:12] if len(ref) == 40 else ref}


# ---------------------------------------------------------------- the review comment

def _envelope(report: dict | None) -> str | None:
    b = (report or {}).get("bounds_mm")
    if not b:
        return None
    return " × ".join(f"{abs(hi - lo):.1f}".rstrip("0").rstrip(".") for lo, hi in zip(b[0], b[1], strict=False))


def _file(d: dict, variant: str, style: str = "shaded") -> dict | None:
    return next((f for f in d.get("files") or [] if f.get("variant") == variant and f.get("style") == style), None)


def _share_link(design_id: str) -> str | None:
    try:
        from ..outputs import share_link  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return share_link(design_id)
    except Exception:  # noqa: BLE001 - a share link is optional
        return None


def _base_design(d: dict, source: dict, pull: dict | None) -> dict | None:
    """The same file rendered from the base branch (or the default branch), if Sklent has it."""
    from ... import service

    with db.connect() as conn:
        rows = db.rows(conn.execute(
            "SELECT d.* FROM designs d JOIN sources s ON s.id = d.source_id WHERE s.host = ? AND d.owner = ? AND "
            "d.repo = ? AND d.path = ? AND d.id != ? AND d.status = 'rendered' ORDER BY d.rendered_at DESC",
            [source["host"], d["owner"], d["repo"], d["path"], d["id"]]).fetchall())
    want = (pull or {}).get("base_ref")
    pick = next((r for r in rows if want and r["ref"] == want), None) or next(
        (r for r in rows if not PULL_REF.match(r["ref"] or "") and "@" not in (r["ref"] or "")), None)
    return service.design_out(pick) if pick else None


def review_comment(source_id: str, base_url: str, design_ids: list[str] | None = None) -> dict[str, Any]:
    """The Markdown to paste into a review, for a source's rendered designs."""
    from ... import jobs, service

    source = jobs.get_source(source_id)
    m = PULL_REF.match(source.get("ref") or "")
    pull = (pull_of(source_id) or {"number": int(m.group(1))}) if m else None
    base_url = base_url.rstrip("/")
    designs = service.list_designs(source_id=source_id)
    if design_ids:
        designs = [d for d in designs if d["id"] in design_ids]
    with db.connect() as conn:
        raw = {r["id"]: db.row(r) for r in conn.execute(
            "SELECT * FROM designs WHERE source_id = ?", [source_id]).fetchall()}

    def url(d: dict, f: dict | None) -> str | None:
        return f"{base_url}{f['url']}" if f and f.get("url") else None

    if pull:
        head = f"### Sklent renders · PR #{pull['number']}" + (f" · {pull['title']}" if pull.get("title") else "")
        sub = (f"`{(pull.get('head_sha') or '')[:7]}` on `{pull.get('head_ref') or '?'}` → "
               f"`{pull.get('base_ref') or '?'}`")
    else:
        label = source.get("ref") or "default branch"
        head = f"### Sklent renders · {source['owner']}/{source['repo'] or ''} @ {label}".rstrip("/ ")
        sub = ""
    lines = [head, ""]
    if sub:
        lines += [sub, ""]
    shown = 0
    for d in designs:
        lines.append(f"#### `{d['path']}`")
        if d["status"] != "rendered":
            why = f": {d['error']}" if d.get("error") else ""
            lines += [f"_{d['status']}{why}_", ""]
            continue
        shown += 1
        share = _share_link(d["id"])
        still = url(d, _file(d, "social"))
        gif = url(d, _file(d, "gif"))
        target = share or still
        before = _base_design(raw[d["id"]], source, pull) if pull else None
        after_label = f"After · PR #{pull['number']} `{d['commit']}`" if pull else f"`{d['commit']}`"
        if before:
            b_still = url(before, _file(before, "social"))
            b_target = _share_link(before["id"]) or b_still
            lines += [f"| Before · {before['ref']} `{before['commit']}` | {after_label} |", "|---|---|",
                      f"| [![before]({b_still})]({b_target}) | [![after]({still})]({target}) |", ""]
        else:
            lines += [f"[![{d['name']}]({still})]({target})", ""]
        facts = []
        env_after, env_before = _envelope(d.get("report")), _envelope((before or {}).get("report"))
        if env_after:
            facts.append(f"{env_before} mm → {env_after} mm" if env_before and env_before != env_after
                         else f"{env_after} mm")
        bodies = (d.get("report") or {}).get("bodies")
        if bodies is not None:
            b0 = ((before or {}).get("report") or {}).get("bodies")
            word = "body" if bodies == 1 else "bodies"
            facts.append(f"{b0} → {bodies} {word}" if b0 is not None and b0 != bodies else f"{bodies} {word}")
        if gif:
            facts.append(f"[turntable GIF]({gif})")
        if share:
            facts.append(f"[full set]({share})")
        if facts:
            lines += [" · ".join(facts), ""]
    lines.append("<sub>Rendered by Sklent in grey; perspective views, not to scale.</sub>")
    return {"markdown": "\n".join(lines).strip() + "\n", "designs": len(designs), "rendered": shown,
            "pull": pull, "base_url": base_url}


def post_review_comment(source_id: str, base_url: str) -> dict[str, Any]:
    """Post the review comment on the source's pull request. Refused unless the
    `inputs_review_post` setting is on."""
    from ... import jobs
    from ...sources import Forge, SourceError

    if not jobs.get_all_settings().get("inputs_review_post"):
        raise PermissionError("posting review comments is off (Settings → Review → Post to the forge)")
    source = jobs.get_source(source_id)
    m = PULL_REF.match(source.get("ref") or "")
    if not m:
        raise SourceError("only a pull request source can be commented on")
    body = review_comment(source_id, base_url)["markdown"]
    url = Forge(source["provider"], source["host"]).post_comment(source["owner"], source["repo"], int(m.group(1)),
                                                                   body)
    with db.connect() as conn:
        conn.execute("UPDATE inputs_pulls SET posted_at = ?, posted_url = ? WHERE source_id = ?",
                     [db.now(), url, source_id])
    return {"posted": True, "url": url}
