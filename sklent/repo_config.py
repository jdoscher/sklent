"""Per-repo settings from `.sklent.yaml` (F25).

A repo can carry `.sklent.yaml` (or `.sklent.yml`) at its root or in any folder. Every
config file in a folder above a design applies to it, the nearest one last, so a
folder's file refines the repo's. Paths and globs in a file are relative to its folder.

    name: Sensor mount family          # the project's name
    licence: CERN-OHL-S-2.0            # also `license`
    include: ["parts/**", "assemblies/*.sc"]
    exclude: ["parts/old/**"]
    formats: [sc, step]                # which inputs a scan finds (sc, step, stl, 3mf)
    presets: [printables, youtube-thumbnail]
    bom: bom.yaml                      # bought parts, for the BOM card
    material: PETG                     # for mass
    highlight: [Lid]                   # bodies or components shown solid, the rest x-ray
    up: y                              # STEP files with Y up
    settings:                          # render setting overrides for these designs
      palette: white
      seconds: 6
      styles: [shaded]
      views_exploded: true             # any feature toggle (a boolean setting)
    steps:                             # assembly steps, in order
      - {title: Base, parts: [Base]}
      - {title: Lid and fan, parts: [Lid, Fan]}
    designs:                           # per design (a path or glob from this folder)
      parts/case.sc:
        title: Pi case
        highlight: [Lid]
        settings: {palette: cool-grey}
      "old/*.stl": {exclude: true}

The file is read with `yaml.safe_load` at the scanned commit and checked: a key that is
wrong is dropped and reported (on the scan job and in `design.config.errors`), never
fatal. Only palette, seconds, styles and the boolean feature settings can be overridden,
and the palette is still one of Sklent's greys.

Other features read a design's merged config through `get(design_id) -> dict`; it is `{}`
when there is none. Keys: name, title, licence, material, bom (a repo path), presets,
highlight, steps, up, formats, settings, plus `from` ([{path, blob}] of the files used,
with `commit`) and `errors`.
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import db

CONFIG_NAMES = (".sklent.yaml", ".sklent.yml")
MAX_BYTES = 256 * 1024
BASE_OVERRIDES = ("palette", "seconds", "styles")
FORMAT_ALIASES = {"sc": ["sc"], "solidcraft": ["sc"], "step": ["step"], "stp": ["step"],
                  "stl": ["stl"], "3mf": ["3mf"], "mesh": ["stl", "3mf"]}
STR_KEYS = ("name", "title", "licence", "material", "bom", "up")
LIST_KEYS = ("include", "exclude", "presets", "highlight", "formats")
DESIGN_KEYS = {"title", "licence", "material", "bom", "up", "presets", "highlight", "settings", "steps",
               "exclude"}
KNOWN = set(STR_KEYS) | set(LIST_KEYS) | {"license", "settings", "steps", "designs"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS inputs_repo_configs (
    host TEXT NOT NULL, owner TEXT NOT NULL, repo TEXT NOT NULL, path TEXT NOT NULL, blob TEXT NOT NULL,
    data TEXT NOT NULL, errors TEXT NOT NULL DEFAULT '[]', fetched_at TEXT NOT NULL,
    PRIMARY KEY (host, owner, repo, path, blob)
);
CREATE TABLE IF NOT EXISTS inputs_design_configs (
    design_id TEXT PRIMARY KEY,
    config TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


# ---------------------------------------------------------------- parsing

def _strs(value: Any, key: str, errors: list[str]) -> list[str] | None:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str | int | float) for v in value):
        return [str(v) for v in value]
    errors.append(f"{key}: expected a list of strings")
    return None


def _steps(value: Any, errors: list[str]) -> list[dict] | None:
    if not isinstance(value, list):
        errors.append("steps: expected a list")
        return None
    out = []
    for i, st in enumerate(value, 1):
        if isinstance(st, dict):
            parts = st.get("parts", st.get("add", []))
            parts = [parts] if isinstance(parts, str) else parts
            if isinstance(parts, list) and parts and all(isinstance(p, str) for p in parts):
                out.append({"title": str(st.get("title") or st.get("name") or f"Step {i}"), "parts": parts,
                            **({"notes": str(st["notes"])} if st.get("notes") else {})})
                continue
        errors.append(f"steps[{i}]: expected {{title, parts: [names]}}")
    return out


def _clean(raw: dict, errors: list[str], where: str = "") -> dict:
    """Keep the keys we understand, in the shapes we expect."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        k = "licence" if key == "license" else key
        label = f"{where}{key}"
        if k in STR_KEYS:
            if isinstance(value, str | int | float) and not isinstance(value, bool):
                out[k] = str(value)
                if k == "up" and out[k] not in ("y", "z"):
                    errors.append(f"{label}: must be y or z")
                    del out[k]
            else:
                errors.append(f"{label}: expected text")
        elif k in LIST_KEYS:
            v = _strs(value, label, errors)
            if v is not None and k == "formats":
                fmts: list[str] = []
                for f in v:
                    if f.lower() in FORMAT_ALIASES:
                        fmts += [x for x in FORMAT_ALIASES[f.lower()] if x not in fmts]
                    else:
                        errors.append(f"{label}: unknown format {f!r} (sc, step, stl, 3mf)")
                v = fmts
            if v is not None:
                out[k] = v
        elif k == "settings":
            if isinstance(value, dict):
                out[k] = dict(value)
            else:
                errors.append(f"{label}: expected a mapping")
        elif k == "steps":
            v = _steps(value, errors)
            if v is not None:
                out[k] = v
        elif k == "exclude" and isinstance(value, bool):
            out[k] = value
        elif k == "designs" and not where:
            if not isinstance(value, dict):
                errors.append("designs: expected a mapping of path or glob to settings")
                continue
            designs = {}
            for pattern, entry in value.items():
                if not isinstance(entry, dict):
                    errors.append(f"designs.{pattern}: expected a mapping")
                    continue
                unknown = set(entry) - DESIGN_KEYS - {"license"}
                for u in sorted(unknown):
                    errors.append(f"designs.{pattern}.{u}: unknown key (ignored)")
                designs[str(pattern)] = _clean({k2: v2 for k2, v2 in entry.items() if k2 not in unknown},
                                               errors, f"designs.{pattern}.")
            out["designs"] = designs
        else:
            errors.append(f"{label}: unknown key (ignored)")
    return out


def parse(text: bytes | str) -> tuple[dict, list[str]]:
    """A `.sklent.yaml` file → (cleaned mapping, error messages). Never raises."""
    if isinstance(text, bytes):
        if len(text) > MAX_BYTES:
            return {}, [f"larger than {MAX_BYTES // 1024} KB; ignored"]
        text = text.decode("utf-8", "replace")
    try:
        import yaml
    except ImportError:  # pragma: no cover - pyyaml is a dependency
        return {}, ["pyyaml is not installed; .sklent.yaml ignored"]
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {}, [f"not valid YAML: {str(exc).splitlines()[0][:200]}"]
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, ["expected a mapping at the top level"]
    errors: list[str] = []
    return _clean(raw, errors), errors


# ---------------------------------------------------------------- matching

@lru_cache(maxsize=512)
def _glob_re(pattern: str) -> re.Pattern:
    """`**` crosses folders, `*` and `?` don't; a pattern without a slash matches the name
    in any folder unless it starts with `/` or `./` (this folder only); a folder name
    (`old/`) matches everything below it."""
    p = pattern.strip()
    anchored = p.startswith(("/", "./"))
    p = (p[2:] if p.startswith("./") else p).lstrip("/")
    if p.endswith("/"):
        p += "**"
    if "/" not in p.rstrip("*") and not anchored:
        p = "**/" + p
    out, i = "", 0
    while i < len(p):
        if p.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif p.startswith("**", i):
            out += ".*"
            i += 2
        elif p[i] == "*":
            out += "[^/]*"
            i += 1
        elif p[i] == "?":
            out += "[^/]"
            i += 1
        elif p[i] == "[":
            j = p.find("]", i)
            if j < 0:
                out += re.escape(p[i])
                i += 1
            else:
                out += fnmatch.translate(p[i:j + 1])[4:-3]
                i = j + 1
        else:
            out += re.escape(p[i])
            i += 1
    return re.compile(f"(?s:{out})\\Z", re.IGNORECASE)


def glob_match(path: str, pattern: str) -> bool:
    return bool(_glob_re(pattern).match(path))


def config_paths(paths: list[str]) -> list[str]:
    return sorted(p for p in paths if p.rsplit("/", 1)[-1] in CONFIG_NAMES)


def _folder(config_path: str) -> str:
    return config_path.rsplit("/", 1)[0] if "/" in config_path else ""


def chain(design_path: str, configs: list[str]) -> list[str]:
    """The config files that apply to a design, the repo root's first."""
    out = []
    for c in configs:
        f = _folder(c)
        if not f or design_path.startswith(f + "/"):
            out.append(c)
    return sorted(out, key=lambda c: (_folder(c).count("/") + bool(_folder(c)), c))


def _repo_path(folder: str, rel: str) -> str | None:
    p = posixpath.normpath(posixpath.join(folder, rel)) if folder else posixpath.normpath(rel)
    return None if p.startswith("..") or p.startswith("/") else p


def resolve(design_path: str, files: dict[str, dict]) -> dict:
    """Merge the config files above a design. `files` maps a config's repo path to
    {"data", "errors", "blob"}. Returns {} when no file applies; else the merged keys
    plus `included` (False when an include/exclude rule leaves the design out), `from`
    and `errors`."""
    applied = chain(design_path, list(files))
    if not applied:
        return {}
    merged: dict[str, Any] = {"included": True, "settings": {}, "from": [], "errors": []}

    def take(entry: dict, folder: str) -> None:
        for k, v in entry.items():
            if k in ("include", "exclude", "designs"):
                continue
            if k == "settings":
                merged["settings"].update(v)
            elif k == "bom":
                p = _repo_path(folder, v)
                if p:
                    merged["bom"] = p
                else:
                    merged["errors"].append(f"bom: {v} is outside the repo")
            else:
                merged[k] = v

    for cpath in applied:
        cfg = files[cpath]
        data, folder = cfg.get("data") or {}, _folder(cpath)
        rel = design_path[len(folder) + 1:] if folder else design_path
        merged["from"].append({"path": cpath, "blob": cfg.get("blob")})
        merged["errors"] += [f"{cpath}: {e}" for e in cfg.get("errors") or []]
        if "include" in data and not any(glob_match(rel, g) for g in data["include"]):
            merged["included"] = False
        if any(glob_match(rel, g) for g in data.get("exclude", [])):
            merged["included"] = False
        take(data, folder)
        for pattern, entry in (data.get("designs") or {}).items():
            if glob_match(rel, pattern) or rel == pattern:
                if entry.get("exclude") is True:
                    merged["included"] = False
                take({k: v for k, v in entry.items() if k != "exclude"}, folder)
    clean, errs = clean_settings(merged["settings"])
    merged["settings"] = clean
    merged["errors"] += errs
    return merged


def clean_settings(settings: dict) -> tuple[dict, list[str]]:
    """Keep the overrides a repo may make: palette, seconds, styles, and any boolean
    feature setting (`jobs.register_setting` with a bool default), each validated. The
    inputs area's own settings (formats, review posting) are server-side only."""
    from dataclasses import asdict

    from . import jobs
    from .render import RenderOptions

    out: dict[str, Any] = {}
    errors: list[str] = []
    for k, v in settings.items():
        if k in BASE_OVERRIDES:
            try:
                RenderOptions(**{**asdict(RenderOptions()), k: v}).validate()
                out[k] = v
            except (ValueError, TypeError, KeyError) as exc:
                errors.append(f"settings.{k}: {exc}")
        elif (k in jobs._EXTRA and isinstance(jobs._EXTRA[k][0], bool)
              and not k.startswith(("inputs_", "render_", "helpers_"))):  # server-side only
            validate = jobs._EXTRA[k][1]
            try:
                out[k] = validate(v) if validate else bool(v)
            except (ValueError, TypeError) as exc:
                errors.append(f"settings.{k}: {exc}")
        else:
            errors.append(f"settings.{k}: not a setting a repo can change")
    return out, errors


# ---------------------------------------------------------------- storage

def load(forge, host: str, owner: str, repo: str, commit: str, tree: list,
         max_bytes: int = MAX_BYTES) -> dict[str, dict]:
    """Every config file in a scanned tree (sources.TreeFile entries at `commit`), parsed.
    Cached by blob SHA, so an unchanged file isn't fetched again."""
    out: dict[str, dict] = {}
    for f in tree:
        if f.path.rsplit("/", 1)[-1] not in CONFIG_NAMES:
            continue
        with db.connect() as conn:
            hit = conn.execute("SELECT data, errors FROM inputs_repo_configs WHERE host = ? AND owner = ? AND "
                               "repo = ? AND path = ? AND blob = ?", [host, owner, repo, f.path, f.sha]).fetchone()
        if hit:
            out[f.path] = {"data": json.loads(hit["data"]), "errors": json.loads(hit["errors"]), "blob": f.sha}
            continue
        try:
            raw = forge.fetch(owner, repo, commit, f.path, max_bytes)
            data, errors = parse(raw)
        except Exception as exc:  # noqa: BLE001 - a config that can't be read is reported, not fatal
            data, errors = {}, [f"could not read: {exc}"]
        out[f.path] = {"data": data, "errors": errors, "blob": f.sha}
        with db.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO inputs_repo_configs (host, owner, repo, path, blob, data, errors,"
                         " fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                         [host, owner, repo, f.path, f.sha, json.dumps(data), json.dumps(errors), db.now()])
    return out


def store(design_id: str, config: dict, commit: str | None = None) -> None:
    """Remember a design's merged config from the latest scan (or drop it)."""
    with db.connect() as conn:
        if not config:
            conn.execute("DELETE FROM inputs_design_configs WHERE design_id = ?", [design_id])
            return
        conn.execute("INSERT INTO inputs_design_configs (design_id, config, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(design_id) DO UPDATE SET config = excluded.config, updated_at = excluded.updated_at",
                     [design_id, json.dumps({**config, "commit": commit}), db.now()])


# A render helper has no database: it sets the claimed design's config here (from the
# server's settings snapshot) before rendering, and `get` answers from it.
OVERRIDES: dict[str, dict] = {}


def get(design_id: str) -> dict:
    """A design's merged `.sklent.yaml` config ({} when its repo has none)."""
    if design_id in OVERRIDES:
        return OVERRIDES[design_id]
    try:
        with db.connect() as conn:
            r = conn.execute("SELECT config FROM inputs_design_configs WHERE design_id = ?", [design_id]).fetchone()
    except Exception:  # noqa: BLE001 - the table exists only with the inputs feature loaded
        return {}
    return json.loads(r["config"]) if r else {}


def render_overrides(design_id: str) -> dict:
    """The render settings a design's repo config overrides (already validated)."""
    return dict(get(design_id).get("settings") or {})


def for_local(design: Path, stop: Path | None = None) -> dict:
    """The merged config for a design file on disk (`sklent render`): every
    `.sklent.yaml` from the design's folder up to `stop`, the git root, or `/`."""
    design = design.resolve()
    folders = []
    d = design.parent
    while True:
        folders.append(d)
        if (stop and d == stop.resolve()) or (d / ".git").exists() or d.parent == d:
            break
        d = d.parent
    root = folders[-1]
    files = {}
    for f in folders:
        for name in CONFIG_NAMES:
            p = f / name
            if p.is_file():
                data, errors = parse(p.read_bytes())
                files[str((f / name).relative_to(root)).replace("\\", "/")] = {"data": data, "errors": errors,
                                                                              "blob": None}
    return resolve(str(design.relative_to(root)).replace("\\", "/"), files)
