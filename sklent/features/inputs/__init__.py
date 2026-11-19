"""Inputs and access (Sklent 0.2, area P): STEP/STL/3MF inputs (F3), linked multi-file
assemblies (F14), `.sklent.yaml` repo config (F25), branch/PR/tag renders with a review
comment (F12), class sets with due-date snapshots (F28) and read-only viewer tokens (F18).

Discovery lives in `sklent.sources` and `sklent.jobs.scan`; the repo config in
`sklent.repo_config`; the token check in `sklent.auth`. This package holds the tables,
the REST routes, the MCP tools, the render hooks and the design JSON extras.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from ... import db, jobs, repo_config, solidcraft
from ...sources import SourceError, design_format
from . import classes, links, refs, tokens

SCHEMA = "\n".join([repo_config.SCHEMA, links.SCHEMA, refs.SCHEMA, classes.SCHEMA, tokens.SCHEMA])
MIGRATE = tokens.migrate


# ---------------------------------------------------------------- settings

def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError("expected true or false")
    return v


def _url(v: Any) -> str:
    v = str(v or "").strip().rstrip("/")
    if v and not v.startswith(("http://", "https://")):
        raise ValueError("inputs_public_url must start with http:// or https://")
    return v


jobs.register_setting("inputs_step", True, _bool)          # scans find .step/.stp files
jobs.register_setting("inputs_mesh", True, _bool)          # scans find .stl/.3mf files
jobs.register_setting("inputs_review_post", False, _bool)  # allow posting review comments to the forge
jobs.register_setting("inputs_public_url", "", _url)       # this server's URL, for links in review comments


def formats_from_settings(settings: dict) -> list[str]:
    out = ["sc"]
    if settings.get("inputs_step", True):
        out.append("step")
    if settings.get("inputs_mesh", True):
        out += ["stl", "3mf"]
    return out


# ---------------------------------------------------------------- render hooks

if links.allow_paths not in solidcraft.ALLOW_PATH_HOOKS:
    solidcraft.ALLOW_PATH_HOOKS.append(links.allow_paths)
if links.on_open not in solidcraft.OPEN_HOOKS:
    solidcraft.OPEN_HOOKS.append(links.on_open)


# ---------------------------------------------------------------- design JSON

def design_extra(d: dict) -> dict[str, Any]:
    """Extra keys on a design's JSON: format, inputs (linked files), config (from
    `.sklent.yaml`), ref (PR/branch/tag) and due (a class set's snapshot)."""
    out: dict[str, Any] = {"format": design_format(d["path"]) or "sc", "inputs": None, "config": None,
                           "ref_info": None, "due": None}
    try:
        r = links.row(d["id"])
        if r and (r["deps"] or r["notes"]):
            out["inputs"] = {"links": r["deps"], "notes": r["notes"]}
        cfg = repo_config.get(d["id"])
        out["config"] = cfg or None
        with db.connect() as conn:
            source = db.row(conn.execute("SELECT * FROM sources WHERE id = ?", [d["source_id"]]).fetchone())
        out["ref_info"] = refs.ref_info(source)
        opts = classes.options(d["source_id"]) if source else {}
        if opts.get("deadline"):
            sub = classes.submission_for(d["source_id"], d["owner"], d["repo"]) or {}
            out["due"] = {"deadline": opts["deadline"], "committed_at": sub.get("committed_at"),
                          "after_due": bool(sub.get("after_due"))}
    except Exception:  # noqa: BLE001 - extras never break the design listing
        pass
    return out


# ---------------------------------------------------------------- REST

router = APIRouter()


def _base_url(request: Request) -> str:
    return jobs.get_all_settings().get("inputs_public_url") or str(request.base_url).rstrip("/")


def _source_or_404(source_id: str) -> dict:
    try:
        return jobs.get_source(source_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


@router.get("/whoami")
def whoami(request: Request):
    """Who this token is: role admin (SK_TOKEN) or viewer (a viewer token, read-only)."""
    st = request.scope.get("state") or {}
    return {"role": st.get("sk_role", "admin"), "name": st.get("sk_viewer")}


@router.get("/designs/{design_id}/inputs")
def design_inputs(design_id: str):
    try:
        d = jobs.get_design(design_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    return design_extra(d)


@router.get("/sources/{source_id}/review-comment")
def get_review_comment(source_id: str, request: Request, design: str | None = None):
    _source_or_404(source_id)
    out = refs.review_comment(source_id, _base_url(request), [design] if design else None)
    out["post_enabled"] = bool(jobs.get_all_settings().get("inputs_review_post"))
    return out


@router.post("/sources/{source_id}/review-comment")
def post_review_comment(source_id: str, request: Request):
    _source_or_404(source_id)
    try:
        return refs.post_review_comment(source_id, _base_url(request))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc


class ClassCreate(BaseModel):
    url: str
    prefix: str | None = None
    deadline: str | None = None
    roster: list[str] | str | None = None
    title: str | None = None
    auto_render: bool = True
    scan: bool = True


class ClassPatch(BaseModel):
    title: str | None = None
    deadline: str | None = None
    roster: list[str] | str | None = None
    scan: bool = True


def add_class(url: str, prefix: str | None = None, deadline: str | None = None, roster: Any = None,
              title: str | None = None, auto_render: bool = True, scan: bool = True) -> dict:
    from urllib.parse import urlencode

    from ...sources import parse_source

    spec = parse_source(url)
    if spec.kind != "account" and prefix:
        raise SourceError("a class set's URL is an account or organisation (the prefix picks its repos)")
    if prefix and not spec.prefix:
        url = f"{spec.canonical_url}?{urlencode({'prefix': prefix.strip()})}"
    deadline_clean = classes.clean_deadline(deadline)  # check before anything is stored
    roster_clean = classes.clean_roster(roster)
    source = jobs.add_source(url, auto_render)
    classes.set_options(source["id"], title=title or "", deadline=deadline_clean or "", roster=roster_clean)
    job = jobs.enqueue("scan", source_id=source["id"]) if scan else None
    return {"source": source, "job": job, "class": classes.class_view(source["id"])}


@router.post("/classes", status_code=201)
def create_class(body: ClassCreate):
    try:
        return add_class(body.url, body.prefix, body.deadline, body.roster, body.title, body.auto_render, body.scan)
    except (SourceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/classes")
def list_classes():
    with db.connect() as conn:
        srcs = db.rows(conn.execute("SELECT * FROM sources ORDER BY created_at").fetchall())
    return [classes.class_view(s["id"]) for s in srcs if classes.is_class(s)]


@router.get("/sources/{source_id}/class")
def get_class(source_id: str):
    _source_or_404(source_id)
    return classes.class_view(source_id)


@router.put("/sources/{source_id}/class")
def put_class(source_id: str, body: ClassPatch):
    _source_or_404(source_id)
    try:
        classes.set_options(source_id, title=body.title, deadline=body.deadline, roster=body.roster)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = jobs.enqueue("scan", source_id=source_id) if body.scan else None
    return {"class": classes.class_view(source_id), "job": job}


class TokenCreate(BaseModel):
    name: str
    scope: str = "viewer"  # viewer | helper (a render helper's token, 0.2.1)


@router.get("/tokens")
def list_viewer_tokens():
    return tokens.list_tokens()


@router.post("/tokens", status_code=201)
def create_viewer_token(body: TokenCreate):
    try:
        return tokens.create(body.name, body.scope)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/tokens/{token_id}")
def revoke_viewer_token(token_id: str):
    try:
        return tokens.revoke(token_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


# ---------------------------------------------------------------- MCP

READ = ToolAnnotations(readOnlyHint=True)


def register_mcp(mcp) -> None:
    @mcp.tool(description=(
        "Add a class set: an account or organisation URL plus a repo-name prefix (GitHub Classroom's "
        "`<assignment>-<username>` repos). Optional deadline (ISO 8601: each repo renders its last commit at "
        "or before it), roster (usernames, `username, Display name`, or repo patterns with *) and title. "
        "Scans it now."))
    def add_class_source(url: str, prefix: str | None = None, deadline: str | None = None,
                         roster: list[str] | None = None, title: str | None = None,
                         auto_render: bool = True) -> dict[str, Any]:
        return add_class(url, prefix, deadline, roster, title, auto_render)

    @mcp.tool(annotations=READ, description=(
        "A class set's submissions: every student on the roster (or every repo found) with status "
        "submitted|empty|late|missing, the commit rendered (the last one at or before the deadline), whether "
        "they pushed after it, and the names with no submission."))
    def list_class_submissions(source_id: str) -> dict[str, Any]:
        jobs.get_source(source_id)
        return classes.class_view(source_id)

    @mcp.tool(annotations=READ, description=(
        "Markdown for a review comment on a source's renders (a pull request source shows before/after "
        "stills against the base branch when Sklent has it). Image links use the inputs_public_url setting. "
        "Nothing is posted; paste it yourself, or use post_review_comment when posting is switched on."))
    def review_comment(source_id: str) -> dict[str, Any]:
        jobs.get_source(source_id)
        base = jobs.get_all_settings().get("inputs_public_url") or ""
        return refs.review_comment(source_id, base)

    @mcp.tool(description=(
        "Post the review comment on the source's pull request through the forge API with the server's "
        "GitHub/Forgejo token. Refused unless the inputs_review_post setting is on (default off)."))
    def post_review_comment(source_id: str) -> dict[str, Any]:
        base = jobs.get_all_settings().get("inputs_public_url") or ""
        return refs.post_review_comment(source_id, base)

    @mcp.tool(annotations=READ, description=(
        "A design's inputs: its format (sc, step, stl, 3mf), the linked design files fetched with it, "
        "its merged .sklent.yaml config, and its ref (pull request, branch, tag) or due-date snapshot."))
    def get_design_inputs(design_id: str) -> dict[str, Any]:
        return design_extra(jobs.get_design(design_id))
