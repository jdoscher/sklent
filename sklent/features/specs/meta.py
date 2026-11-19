"""What a step knows about the design beyond the open file: the database row (repo, ref,
commit, blob, path, source URL) and the repo's `.sklent.yaml` (licence, title, material,
`bom.yaml` path, assembly steps).

Steps don't get the design id from the render seam, so it comes from, in order:
1. `ctx.settings["design"]`: a dict with any of id, owner, repo, ref, path, commit_sha,
   blob_sha, html_url, provider, host (the integrator may pass it in `jobs._render`);
2. the set folder: `<renders_dir>/<design id>/<set>/` (how jobs lays sets out), looked up
   in the database;
3. nothing (`sklent render` on a local file): the file name stands in for the title.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("sklent.specs")

try:  # P's .sklent.yaml reader (F25); every feature must work without it
    from sklent import repo_config  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - depends on the integration
    repo_config = None


def design_row(ctx) -> dict[str, Any]:
    given = (ctx.settings or {}).get("design")
    if isinstance(given, dict) and given:
        return dict(given)
    try:
        from sklent import db
        from sklent.config import get_settings

        renders = get_settings().renders_dir.resolve()
        out = Path(ctx.out_dir).resolve()
        if renders not in out.parents:
            return {}
        rel = out.relative_to(renders).parts
        if not rel:
            return {}
        with db.connect() as conn:
            row = db.row(conn.execute(
                "SELECT d.*, s.provider, s.host FROM designs d LEFT JOIN sources s ON s.id = d.source_id "
                "WHERE d.id = ?", [rel[0]]).fetchone())
        return row or {}
    except Exception as exc:  # no database (local render) or an older schema
        log.debug("no design row for %s: %s", ctx.out_dir, exc)
        return {}


def config(design_id: str | None) -> dict[str, Any]:
    """The design's `.sklent.yaml` settings through P's `repo_config.get`, or {}."""
    if not design_id or repo_config is None:
        return {}
    try:
        cfg = repo_config.get(design_id)
    except Exception as exc:  # a broken file must not break the render
        log.warning("repo_config.get(%s) failed: %s", design_id, exc)
        return {}
    return cfg if isinstance(cfg, dict) else {}


def pick(cfg: dict, *keys: str) -> Any:
    """The first present key, with dotted paths ('bom.path') into nested dicts."""
    for key in keys:
        node: Any = cfg
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if node not in (None, "", [], {}):
            return node
    return None


def licence(cfg: dict) -> str | None:
    v = pick(cfg, "licence", "license", "spdx")
    if isinstance(v, dict):
        v = v.get("spdx") or v.get("name") or v.get("id")
    return str(v) if v else None


# A render helper has no forge token: it sets this to fetch through the server
# (fn(row, rel_path, max_bytes) -> bytes | None).
REPO_FILE_HOOK: list = []


def fetch_repo_file(row: dict, rel_path: str, max_bytes: int = 1 << 20) -> bytes | None:
    """A small file from the design's repo at the rendered commit, or None. `rel_path` is
    relative to the design's folder unless it starts with '/' (the repo root)."""
    for hook in REPO_FILE_HOOK:
        return hook(row, rel_path, max_bytes)
    if not row.get("owner") or not row.get("provider") or not rel_path:
        return None
    from sklent.sources import Forge, SourceError

    folder = row.get("path", "").rpartition("/")[0]
    path = rel_path.lstrip("/") if rel_path.startswith("/") or not folder else f"{folder}/{rel_path}"
    try:
        return Forge(row["provider"], row["host"]).fetch(row["owner"], row["repo"],
                                                       row.get("commit_sha") or row.get("ref"), path, max_bytes)
    except (SourceError, OSError, KeyError) as exc:
        log.info("no %s in %s/%s: %s", path, row.get("owner"), row.get("repo"), exc)
        return None
    except Exception as exc:  # httpx errors and the like
        log.info("fetching %s failed: %s", path, exc)
        return None
