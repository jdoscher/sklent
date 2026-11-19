"""Linked designs (F14) and input formats (F3) at render time.

A SolidCraft assembly can link parts saved in other files (`component.insert_design`);
the design stores each link as a path relative to its own folder (`links: {component:
{path: "parts/lid.sc"}}` in the JSON, or in a packaged design's `document.json`) and keeps
a copy of the linked bodies. Before a render, `fetch_design` downloads the design and every
file it links (and what those link, up to MAX_LINKED files) at the same commit, into the
job's work folder in the repo's own layout, so the relative paths resolve. When the
SolidCraft process opens the design, `on_open` asks it which links changed since the
design last read them and updates those (`component.update_links`), so the render shows
the parts as they are at that commit. A link that can't be fetched keeps the saved copy,
with a note in the render report.

Change detection follows the links: a design with links is keyed by an "assembly blob",
a hash of its own blob and its linked files' blobs, so editing `parts/lid.sc` re-renders
every assembly that uses it.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import posixpath
import zipfile
from pathlib import Path
from typing import Any

from ... import db
from ...sources import SourceError, design_format, git_blob_sha, looks_like_design

log = logging.getLogger("sklent")

MAX_LINKED = 64  # files fetched for one design
SIDE = ".sklent.json"  # next to the fetched design: how to open it (read by on_open)
FORMAT_LABEL = {"sc": "SolidCraft design", "step": "STEP file", "stl": "STL mesh", "3mf": "3MF file"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS inputs_designs (
    design_id TEXT PRIMARY KEY,
    format TEXT,
    own_blob TEXT,
    deps TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);
"""


# ---------------------------------------------------------------- reading links

def design_links(data: bytes) -> list[str]:
    """The relative paths a SolidCraft design links to (empty for none)."""
    try:
        if data[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(data))
            name = next((n for n in z.namelist() if n.rsplit("/", 1)[-1] == "document.json"), None)
            if not name:
                return []
            data = z.read(name)
        if b'"links"' not in data:
            return []
        doc = json.loads(data)
    except (zipfile.BadZipFile, ValueError, KeyError, OSError):
        return []
    links = doc.get("links") if isinstance(doc, dict) else None
    entries = links.values() if isinstance(links, dict) else links if isinstance(links, list) else []
    out = []
    for e in entries:
        p = e.get("path") if isinstance(e, dict) else e if isinstance(e, str) else None
        if isinstance(p, str) and p and p not in out:
            out.append(p)
    return out


def resolve_link(design_path: str, link: str) -> str | None:
    """A link (relative to the design's folder) as a repo path; None when it is absolute
    or leaves the repo."""
    if link.startswith("/") or (len(link) > 1 and link[1] == ":") or link.startswith("\\"):
        return None
    folder = design_path.rsplit("/", 1)[0] if "/" in design_path else ""
    p = posixpath.normpath(posixpath.join(folder, link.replace("\\", "/")))
    return None if p.startswith("../") or p == ".." else p


def assembly_blob(own: str, deps: list[dict]) -> str:
    """The change key of a design with links: its own blob plus each linked file's."""
    if not deps:
        return own
    h = hashlib.sha1(f"sklent-assembly\n{own}\n".encode())
    for d in sorted(deps, key=lambda d: d["path"]):
        h.update(f"{d['path']} {d.get('blob') or 'missing'}\n".encode())
    return h.hexdigest()


# ---------------------------------------------------------------- the table

def row(design_id: str) -> dict | None:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM inputs_designs WHERE design_id = ?", [design_id]).fetchone()
    if not r:
        return None
    out = dict(r)
    out["deps"] = json.loads(out["deps"] or "[]")
    out["notes"] = json.loads(out["notes"] or "[]")
    return out


def scan_blob(design_id: str | None, own: str, tree_shas: dict[str, str]) -> str:
    """At a scan: the key for a design whose own blob is `own`, with the links it had at
    its last render looked up in the scanned tree."""
    r = row(design_id) if design_id else None
    if not r or not r["deps"]:
        return own
    return assembly_blob(own, [{"path": d["path"], "blob": tree_shas.get(d["path"])} for d in r["deps"]])


def note_scan(conn, design_id: str, own: str) -> None:
    """Remember a design's own blob (on the scan's connection)."""
    conn.execute("UPDATE inputs_designs SET own_blob = ? WHERE design_id = ?", [own, design_id])


def depends_on(host: str, owner: str, repo: str, path: str, changed: set[str]) -> bool:
    """Whether a design at this path links (at any of its renders) to one of `changed`."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT i.deps FROM inputs_designs i JOIN designs d ON d.id = i.design_id JOIN sources s ON "
            "s.id = d.source_id WHERE s.host = ? AND d.owner = ? AND d.repo = ? AND d.path = ?",
            [host, owner, repo, path]).fetchall()
    return any(d["path"] in changed for r in rows for d in json.loads(r["deps"] or "[]"))


# ---------------------------------------------------------------- fetching

def fetch_design(forge, settings, design: dict, work: Path, progress=lambda f, m: None,
                 config: dict | None = None, check=looks_like_design) -> tuple[Path, dict]:
    """Download a design (and the files it links) into `work`. Returns the local path of
    the design and the design row, whose blob_sha may have become its assembly blob.
    `check(data, path)` vets the downloaded bytes."""
    path, commit = design["path"], design["commit_sha"]
    max_bytes = settings.max_design_mb * 2**20
    fmt = design_format(path) or "sc"
    data = forge.fetch(design["owner"], design["repo"], commit, path, max_bytes)
    if not check(data, path):
        raise SourceError(f"{path} is not a {FORMAT_LABEL.get(fmt, 'design')}")
    root = work / "repo"
    local = root / path
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)

    deps: list[dict] = []
    notes: list[str] = []
    if fmt == "sc":
        queue: list[tuple[str, bytes]] = [(path, data)]
        seen = {path}
        total = len(data)
        while queue:
            here, content = queue.pop(0)
            for link in design_links(content):
                target = resolve_link(here, link)
                if target is None:
                    notes.append(f"{here}: the link {link} points outside the repo; its saved copy is used")
                    continue
                if target in seen:
                    continue
                seen.add(target)
                if len(deps) >= MAX_LINKED:
                    notes.append(f"more than {MAX_LINKED} linked files; the rest use their saved copies")
                    queue.clear()
                    break
                progress(0.005, f"downloading linked {target.rsplit('/', 1)[-1]}")
                try:
                    dep = forge.fetch(design["owner"], design["repo"], commit, target, max_bytes)
                except SourceError as exc:
                    deps.append({"path": target, "blob": None, "missing": True})
                    notes.append(f"{target}: {exc}; the saved copy is used")
                    continue
                total += len(dep)
                if total > 4 * max_bytes:
                    raise SourceError(f"{path} and its linked designs add up to more than "
                                      f"{4 * max_bytes // 2**20} MB")
                (root / target).parent.mkdir(parents=True, exist_ok=True)
                (root / target).write_bytes(dep)
                deps.append({"path": target, "blob": git_blob_sha(dep)})
                if design_format(target) == "sc":
                    queue.append((target, dep))

    side: dict[str, Any] = {}
    up = (config or {}).get("up")
    if fmt == "step" and up in ("y", "z"):
        side["up"] = up
    if deps:
        side["links"] = [d["path"] for d in deps]
    if side:
        (local.parent / (local.name + SIDE)).write_text(json.dumps(side))

    prev = row(design["id"])
    own = (prev or {}).get("own_blob") or design["blob_sha"]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO inputs_designs (design_id, format, own_blob, deps, notes, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(design_id) DO UPDATE SET format = excluded.format, own_blob = excluded.own_blob, "
            "deps = excluded.deps, notes = excluded.notes, updated_at = excluded.updated_at",
            [design["id"], fmt, own, json.dumps(deps), json.dumps(notes), db.now()])
        key = assembly_blob(own, deps)
        if key != design["blob_sha"]:
            db.update(conn, "designs", design["id"], blob_sha=key)
            design = {**design, "blob_sha": key}
    return local, design


# ---------------------------------------------------------------- SolidCraft hooks

_open_results: dict[str, dict] = {}
_links_cache: dict[tuple[str, float], list[str]] = {}


def _local_links(design: Path) -> list[str]:
    if design_format(design.name) != "sc":
        return []
    try:
        key = (str(design), design.stat().st_mtime)
    except OSError:
        return []
    if key not in _links_cache:
        try:
            _links_cache[key] = design_links(design.read_bytes())
        except OSError:
            _links_cache[key] = []
    return _links_cache[key]


def _side(design: Path) -> dict:
    try:
        return json.loads((design.parent / (design.name + SIDE)).read_text())
    except (OSError, ValueError):
        return {}


def allow_paths(design: Path) -> list[Path]:
    """Folders a SolidCraft process for this design must be allowed to read: the common
    folder of the design and the files it links (`../parts/x.sc`)."""
    targets = [(design.parent / link).resolve() for link in _local_links(design)
               if not link.startswith("/")]
    if not targets:
        return []
    import os

    common = Path(os.path.commonpath([str(design.parent.resolve()), *[str(t.parent) for t in targets]]))
    return [common] if common != design.parent.resolve() else []


def on_open(sc, design: Path) -> None:
    """Run in every SolidCraft process just after it opened a design: re-open a Y-up
    STEP file standing up, and read linked designs that changed since it saved them."""
    result: dict[str, Any] = {}
    side = _side(design)
    if side.get("up") == "y":
        sc.tool("open", path=str(design), up="y")
        result["up"] = "y"
    if _local_links(design):
        try:
            links = (sc.execute("component.links") or {}).get("links", [])
        except Exception as exc:  # noqa: BLE001 - never fail a render over links
            result["links_error"] = str(exc)[:300]
            links = []
        stale = [lk["component"] for lk in links if lk.get("found") and lk.get("changed")]
        result["links"] = [{"path": lk.get("path"), "found": bool(lk.get("found")), "changed": bool(lk.get("changed"))}
                           for lk in links]
        if stale:
            try:
                reply = sc.execute("component.update_links", components=stale) or {}
                result["updated"] = len(stale)
                if isinstance(reply, dict) and reply.get("failed"):
                    result["failed"] = reply["failed"]
            except Exception as exc:  # noqa: BLE001
                result["update_error"] = str(exc)[:300]
                log.warning("updating linked designs of %s failed: %s", design.name, exc)
    if result:
        _open_results[str(design)] = result


def report_for(design: Path) -> dict:
    """What the inputs did for one render (`report["inputs"]` in report.json): the
    format, whether it is a mesh, a Y-up STEP re-opened standing, and the links read."""
    fmt = design_format(design.name) or "sc"
    out: dict[str, Any] = {"format": fmt}
    if fmt in ("stl", "3mf"):
        out["mesh"] = True
    out.update(_open_results.pop(str(design), {}))
    return out
