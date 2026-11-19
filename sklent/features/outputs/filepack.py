"""F7 print and release file pack: STEP, 3MF and STL exported by SolidCraft from the very
design the renders came from (same commit, same blob), plus a README, a licence and a
manifest with sha256 sums. Off by default (`outputs_filepack`).

The render step (order 90, after V, S and R's steps) exports while the design is open:
- STEP of the whole design: fast even for big assemblies (SELENE, 1,418 bodies: 1.4 s).
- 3MF of the whole design, skipped above `outputs_filepack_body_budget` bodies: a
  1,418-body 3MF took 19 minutes (SolidCraft 0.44 spike, Q12).
- STL: the whole design as one file up to the budget; per body (in one zip) for multi-body
  designs, and only per body above the budget ("per body when the whole design is big").
Hidden bodies (reference geometry, alternates) and bodies matching
`outputs_filepack_exclude` (bought hardware such as `M3*`, `insert*`) are left out.

The pack itself (zip with README.md, LICENSE.txt, manifest.json) is built on demand, and
split into standalone zips of at most N MB when a target needs it: Etsy takes at most five
digital files of 20 MB each (help.etsy.com/hc/en-us/articles/115015628347).
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import zipfile
import zlib
from pathlib import Path
from typing import Any

from ... import jobs, sets, steps
from .common import (
    OutputError,
    commit_of,
    design,
    envelope_mm,
    exports_dir,
    fmt_envelope,
    kist_file,
    licence_text,
    lock,
    meta,
    repo_cfg,
    safe,
    sha256,
    stem_of,
    the_set,
    write_zip,
)

FORMATS = ("step", "3mf", "stl")
QUALITIES = ("standard", "fine", "finest")
SIDECAR = "filepack.json"
VARIANTS = ("step", "3mf", "stl", "stl-parts")


def _formats(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, list) or not v or any(x not in FORMATS for x in v):
        raise ValueError(f"outputs_filepack_formats must be some of {', '.join(FORMATS)}")
    return [f for f in FORMATS if f in v]


def _globs(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v) or len(v) > 50:
        raise ValueError("outputs_filepack_exclude must be a list of name patterns")
    return v


def _int(lo: int, hi: int):
    def check(v: Any) -> int:
        v = int(v)
        if not lo <= v <= hi:
            raise ValueError(f"must be {lo} to {hi}")
        return v
    return check


def _quality(v: Any) -> str:
    if v not in QUALITIES:
        raise ValueError(f"outputs_filepack_quality must be one of {', '.join(QUALITIES)}")
    return v


SETTINGS = {
    "outputs_filepack": (False, bool),
    "outputs_filepack_formats": (list(FORMATS), _formats),
    "outputs_filepack_body_budget": (64, _int(1, 5000)),
    "outputs_filepack_max_parts": (2000, _int(1, 10000)),
    "outputs_filepack_per_body": (True, bool),
    "outputs_filepack_quality": ("standard", _quality),
    "outputs_filepack_exclude": ([], _globs),
}


def register() -> None:
    for key, (default, validate) in SETTINGS.items():
        jobs.register_setting(key, default, validate)
    steps.register_step("outputs-filepack", export_step, order=90,
                        when=lambda ctx: ctx.enabled("outputs_filepack"))


# ---------------------------------------------------------------- the render step

def _design_id(ctx: steps.StepContext) -> str | None:
    """A served render writes to <renders>/<design id>/<blob12>; the CLI writes anywhere.
    A served render (or a render helper's) also carries the design row in the settings."""
    given = (ctx.settings.get("design") or {}) if isinstance(ctx.settings.get("design"), dict) else {}
    if given.get("id"):
        return given["id"]
    from ...config import get_settings
    if not get_settings().db_path.is_file():
        return None  # a one-off CLI render: no database, and don't create one
    try:
        jobs.get_design(ctx.out_dir.parent.name)
        return ctx.out_dir.parent.name
    except Exception:  # noqa: BLE001 - not a served render
        return None


def _excluded(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name.lower(), p.lower()) for p in patterns)


def export_step(ctx: steps.StepContext) -> None:
    s = ctx.settings
    formats = s.get("outputs_filepack_formats") or list(FORMATS)
    budget = int(s.get("outputs_filepack_body_budget") or 64)
    max_parts = int(s.get("outputs_filepack_max_parts") or 2000)
    quality = s.get("outputs_filepack_quality") or "standard"
    patterns = list(s.get("outputs_filepack_exclude") or [])
    did = _design_id(ctx)
    if did:
        extra = repo_cfg(did).get("print_exclude") or []
        patterns += [extra] if isinstance(extra, str) else list(extra)
    visible = [b["name"] for b in ctx.info if b.get("visible") is not False]
    parts = [b for b in visible if not _excluded(b, patterns)]
    hidden = len(ctx.bodies) - len(visible)
    left_out = [b for b in visible if b not in parts]
    sidecar: dict[str, Any] = {"bodies": len(parts), "hidden_left_out": hidden, "excluded": left_out[:200],
                               "quality": quality, "files": [], "skipped": []}
    if not parts:
        sidecar["skipped"].append("no visible bodies to export after the exclude patterns")
        sets.write_json(ctx.out_dir, SIDECAR, sidecar)
        return
    subset = parts if (hidden or left_out) else None  # None: the whole design, as SolidCraft has it
    stem = ctx.stem

    def export(name: str, fmt: str, bodies: list[str] | None, variant: str, add: bool = True) -> Path:
        path = ctx.out_dir / name
        params: dict[str, Any] = {"path": str(path), "format": fmt}
        if bodies is not None:
            params["bodies"] = bodies
        if fmt in ("stl", "3mf"):
            params["quality"] = quality
        ctx.sc.execute("file.export", **params)
        if not path.is_file():
            raise RuntimeError(f"SolidCraft wrote no {name}")
        if add:
            ctx.add(name, style="files", variant=variant, guard=False)
            sidecar["files"].append({"file": name, "format": fmt, "variant": variant,
                                     "bodies": len(bodies) if bodies is not None else len(parts),
                                     "bytes": path.stat().st_size, "sha256": sha256(path)})
        return path

    big = len(parts) > budget
    if "step" in formats:
        ctx.progress(0.71, "exporting STEP")
        export(f"{stem}.step", "step", subset, "step")
    if "3mf" in formats:
        if big:
            sidecar["skipped"].append(
                f"3MF skipped: {len(parts):,} bodies is above the budget of {budget:,} "
                "(a 1,418-body 3MF took 19 minutes); the STEP and per-body STLs carry the geometry")
        else:
            ctx.progress(0.712, "exporting 3MF")
            export(f"{stem}.3mf", "3mf", subset, "3mf")
    if "stl" in formats:
        if not big:
            ctx.progress(0.714, "exporting STL")
            export(f"{stem}.stl", "stl", subset, "stl")
        per_body = len(parts) > 1 and (big or s.get("outputs_filepack_per_body", True))
        if per_body and len(parts) > max_parts:
            sidecar["skipped"].append(f"per-body STLs skipped: {len(parts):,} bodies is above "
                                      f"outputs_filepack_max_parts ({max_parts:,})")
        elif per_body:
            folder = ctx.out_dir / "_parts"
            folder.mkdir(exist_ok=True)
            names: dict[str, int] = {}
            written = []
            for i, body in enumerate(parts):
                if i % 25 == 0:
                    ctx.progress(0.715, f"exporting STL {i + 1}/{len(parts)}")
                base = safe(body)[:80]
                n = names.get(base, 0)
                names[base] = n + 1
                fname = f"{base}.stl" if n == 0 else f"{base}-{n + 1}.stl"
                path = folder / fname
                ctx.sc.execute("file.export", path=str(path), format="stl", bodies=[body], quality=quality)
                written.append((body, path))
            zname = f"{stem}-stl-parts.zip"
            with zipfile.ZipFile(ctx.out_dir / zname, "w", zipfile.ZIP_DEFLATED) as z:
                for _body, path in written:
                    if path.is_file():
                        z.write(path, f"stl/{path.name}")
            sidecar["parts"] = [{"body": b, "file": f"stl/{p.name}", "bytes": p.stat().st_size,
                                 "sha256": sha256(p)} for b, p in written if p.is_file()]
            shutil.rmtree(folder, ignore_errors=True)
            ctx.add(zname, style="files", variant="stl-parts", guard=False)
            zp = ctx.out_dir / zname
            sidecar["files"].append({"file": zname, "format": "zip", "variant": "stl-parts", "bodies": len(written),
                                     "bytes": zp.stat().st_size, "sha256": sha256(zp)})
    sets.write_json(ctx.out_dir, SIDECAR, sidecar)
    ctx.report.setdefault("outputs", {})["filepack"] = {
        "files": [f["file"] for f in sidecar["files"]], "skipped": sidecar["skipped"]}


# ---------------------------------------------------------------- the pack

def info(design_id: str, set_id: str | None = None) -> dict:
    """What the set's file pack holds: {files, parts, skipped, ...} from the step's sidecar,
    or {enabled: false} when the set was rendered without it."""
    s = the_set(design_id, set_id)
    car = sets.read_json(Path(s["dir"]), SIDECAR)
    on = bool(jobs.get_all_settings().get("outputs_filepack"))
    if not car:
        return {"design_id": design_id, "set_id": s["id"], "made": False, "setting_on": on, "files": [],
                "skipped": [] if on else ["the file pack is off (Settings → Print files); "
                                          "turn it on and re-render to export STEP/3MF/STL"]}
    base = f"/api/designs/{design_id}/files/"
    files = [{**f, "url": base + f["file"]} for f in car.get("files", []) if (Path(s["dir"]) / f["file"]).is_file()]
    return {"design_id": design_id, "set_id": s["id"], "made": True, "setting_on": on, **car, "files": files}


def _readme(d: dict, s: dict, m: dict, listing: list[tuple[str, str, int]], car: dict) -> str:
    env = fmt_envelope(envelope_mm(s))
    commit = commit_of(d, s)
    lines = [f"# {m['title']}", ""]
    if m.get("summary"):
        lines += [m["summary"], ""]
    lines += ["## About these files", "",
              f"- Exported by SolidCraft from `{d['path']}` at commit `{commit[:10]}`, "
              "the same version as the renders.",
              f"- Rendered: {s.get('rendered_at') or ''}"]
    if env:
        lines.append(f"- Overall size: {env}")
    lines.append(f"- Parts: {car.get('bodies', 0)}")
    if car.get("excluded"):
        lines.append(f"- Left out (bought hardware): {', '.join(car['excluded'][:20])}")
    if not m.get("hide_source"):
        lines.append(f"- Source: {d['html_url']}")
    lines.append(f"- Licence: {m['licence'] or 'not set (all rights reserved)'}")
    if m.get("print_notes"):
        lines += ["", "## Print notes", "", m["print_notes"]]
    lines += ["", "## Files", "", "| file | bytes | sha256 |", "|---|---|---|"]
    lines += [f"| {name} | {size:,} | `{digest[:16]}…` |" for name, digest, size in listing]
    lines += ["", "Full sums are in manifest.json. Units are millimetres.", ""]
    return "\n".join(lines)


def _entries(d: dict, s: dict) -> tuple[list[tuple[str, Path]], dict]:
    car = sets.read_json(Path(s["dir"]), SIDECAR) or {}
    out: list[tuple[str, Path]] = []
    for f in car.get("files", []):
        p = Path(s["dir"]) / f["file"]
        if p.is_file():
            out.append((f"files/{f['file']}", p))
    return out, car


def _compressed_size(p: Path) -> int:
    if p.suffix.lower() in (".zip", ".3mf"):
        return p.stat().st_size
    c = zlib.compressobj(6)
    n = 0
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            n += len(c.compress(chunk))
    return n + len(c.flush())


def build(design_id: str, set_id: str | None = None, split_mb: float | None = None, *,
          file_kist: bool = True) -> dict:
    """The pack zip (or zips of at most split_mb each). Returns {parts: [{file, url, bytes,
    sha256}], fits, notes}. Each part is a standalone zip; README, LICENSE and the manifest
    go in the first, and the manifest says which part holds each file."""
    d = design(design_id)
    s = the_set(design_id, set_id)
    files, car = _entries(d, s)
    if not files:
        raise OutputError("this set has no print files: turn on Settings → Print files and re-render", 404)
    m = meta(design_id)
    stem = stem_of(d)
    commit = commit_of(d, s)
    listing = [(arc, sha256(p), p.stat().st_size) for arc, p in files]
    licence = licence_text(m["licence"], m["title"], d["owner"])
    readme = _readme(d, s, m, listing, car)
    limit = int(split_mb * 1e6 * 0.98) if split_mb else None
    groups: list[list[tuple[str, Path]]] = [[]]
    notes: list[str] = []
    if limit:
        sized = sorted(((arc, p, _compressed_size(p)) for arc, p in files), key=lambda t: -t[2])
        room: list[int] = []
        groups = []
        for arc, p, n in sized:
            if n > limit:
                notes.append(f"{arc} is {n / 1e6:.1f} MB compressed, over the {split_mb:g} MB limit by itself")
            for i, left in enumerate(room):
                if n <= left:
                    groups[i].append((arc, p))
                    room[i] -= n
                    break
            else:
                groups.append([(arc, p)])
                room.append(limit - n - 64_000)  # README/LICENSE/manifest headroom
    else:
        groups = [files]
    where = {arc: i + 1 for i, g in enumerate(groups) for arc, _ in g}
    manifest = {"design": f"{d['owner']}/{d['repo']}:{d['path']}", "commit": commit, "blob": s.get("blob_sha"),
                "rendered_at": s.get("rendered_at"), "title": m["title"], "licence": m["licence"] or None,
                "units": "mm", "bodies": car.get("bodies"), "skipped": car.get("skipped", []),
                "files": [{"path": arc, "bytes": size, "sha256": digest, "part": where[arc]}
                          for arc, digest, size in listing]
                + [{"path": "README.md", "sha256": _sha_text(readme), "part": 1},
                   {"path": "LICENSE.txt", "sha256": _sha_text(licence), "part": 1}],
                "parts": len(groups)}
    out_parts = []
    key = f"filepack:{s['dir']}"
    with lock(key):
        for old in exports_dir(s).glob(f"{stem}-print-files*.zip"):
            old.unlink(missing_ok=True)
        for i, g in enumerate(groups):
            name = (f"{stem}-print-files.zip" if len(groups) == 1
                    else f"{stem}-print-files-part{i + 1}of{len(groups)}.zip")
            entries: list[tuple[str, Path | str]] = list(g)
            if i == 0:
                entries = [("README.md", readme), ("LICENSE.txt", licence),
                           ("manifest.json", json.dumps(manifest, indent=2)), *entries]
            p = write_zip(exports_dir(s) / name, entries)
            item = kist_file(d, s, p, "filepack") if file_kist else None
            url = f"/api/designs/{design_id}/outputs/exports/{name}" + (f"?set_id={set_id}" if set_id else "")
            out_parts.append({"file": name, "url": url, "bytes": p.stat().st_size, "sha256": sha256(p),
                              "kist_item_id": item})
    fits = all(p["bytes"] <= split_mb * 1e6 for p in out_parts) if split_mb else True
    return {"design_id": design_id, "set_id": s["id"], "parts": out_parts, "split_mb": split_mb, "fits": fits,
            "notes": notes, "manifest": manifest}


def _sha_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()
