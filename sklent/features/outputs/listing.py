"""F13 listing packs and listing text, and F19's "ready to list" checklist.

For each marketplace profile, a zip holding the pictures in upload order (real print
photos first, then renders cut to the site's sizes), the clips the site takes, the print
files (split where the site caps file sizes), `listing.md` filled from
`templates/listing.md` with the spec, BOM, licence and print notes, and `pack.json` with
every file and the rule it was checked against. Nothing is posted anywhere.

The rules, with their sources (checked 2026-11-18; sites change these, so each rule
names where it came from in pack.json):
- Etsy: photos at least 2,000 px on the shortest side, 4:3 or 1:1 (help.etsy.com
  115015663347); up to 10 photos and one 5-15 s video, at most 100 MB, sound removed
  (same page; lzypod.com etsy-listing-video-requirements); the first photo must show the
  actual item, so renders can't lead (etsy.com/legal/policy/listing-image-requirements);
  digital downloads: at most 5 files of 20 MB (help.etsy.com 115015628347).
- MakerWorld: at least three real printed images from different angles, and a real photo
  is the recommended cover; a rendered cover must closely match the print
  (wiki.bambulab.com/en/makerworld/tutorials/model-upload-guidelines; makerworld.com
  community post 1447793); GIFs up to 30 MB (note.com/yuri_lilium_log, upload memo).
- Printables: 4:3 cover, 2000 px wide is common practice (forum.prusa3d.com cover aspect
  thread); a licence is chosen at upload (layer.works, how to post on Printables); photos
  of real prints are what downloaders trust (r/prusa3d 1fq86vt).
- Thingiverse: publishes no size limits; it recommends at least one image of the final
  printed part (thingiverse.com/blog?p=how-to-upload-your-first-thing).
- Cults: model videos at most 800×800 and under 10 MB; real print photos reassure buyers
  (cults3d.com/en/pages/advice-publishing-3d-file).
"""

from __future__ import annotations

import json
from pathlib import Path
from string import Template
from typing import Any

from . import brand, filepack, media, photos
from .common import (
    SHEET_VARIANTS,
    OutputError,
    bom_of,
    commit_of,
    design,
    envelope_mm,
    exports_dir,
    fmt_envelope,
    kist_file,
    lock,
    meta,
    path_of,
    report_of,
    settings,
    spec_of,
    stem_of,
    still_files,
    the_set,
    write_zip,
)

TEMPLATE = Path(__file__).resolve().parent / "templates" / "listing.md"

MARKETS: dict[str, dict[str, Any]] = {
    "printables": {
        "label": "Printables", "image": (2000, 1500), "fill": 0.72, "max_images": None, "min_short": None,
        "photos_required": 0, "photos_recommended": 1, "photo_first": "recommended", "video": None, "gif": None,
        "split_mb": None, "max_files": None, "licence_required": True, "plain_text": False,
        "sources": ["https://forum.prusa3d.com/forum/english-forum-general-discussion-announcements-and-releases/"
                    "printables-model-cover-photo-aspect-ratio-question/",
                    "https://layer.works/2022/10/30/how-to-post-a-model-on-printables-com/"],
    },
    "makerworld": {
        "label": "MakerWorld", "image": (2000, 1500), "fill": 0.65, "max_images": None, "min_short": None,
        "photos_required": 3, "photos_recommended": 3, "photo_first": "recommended", "video": None,
        "gif": {"width": 640, "max_mb": 30}, "split_mb": None, "max_files": None, "licence_required": True,
        "plain_text": False,
        "sources": ["https://wiki.bambulab.com/en/makerworld/tutorials/model-upload-guidelines",
                    "https://makerworld.com/en/community/post/1447793"],
    },
    "thingiverse": {
        "label": "Thingiverse", "image": (2000, 1500), "fill": 0.72, "max_images": None, "min_short": None,
        "photos_required": 0, "photos_recommended": 1, "photo_first": "recommended", "video": None, "gif": None,
        "split_mb": None, "max_files": None, "licence_required": True, "plain_text": False,
        "sources": ["https://www.thingiverse.com/blog?p=how-to-upload-your-first-thing"],
    },
    "cults": {
        "label": "Cults", "image": (2000, 1500), "fill": 0.72, "max_images": None, "min_short": None,
        "photos_required": 0, "photos_recommended": 1, "photo_first": "recommended",
        "video": {"width": 800, "height": 800, "max_mb": 10, "seconds": None},
        "gif": {"width": 640, "max_mb": 10}, "split_mb": None, "max_files": None, "licence_required": True,
        "plain_text": False,
        "sources": ["https://cults3d.com/en/pages/advice-publishing-3d-file"],
    },
    "etsy": {
        "label": "Etsy", "image": (2667, 2000), "fill": 0.72, "max_images": 10, "min_short": 2000,
        "photos_required": 1, "photos_recommended": 1, "photo_first": "required",
        "video": {"width": 1920, "height": 1080, "max_mb": 100, "seconds": 15, "min_seconds": 5},
        "gif": None, "split_mb": 20, "max_files": 5, "licence_required": False, "plain_text": True,
        "sources": ["https://help.etsy.com/hc/en-us/articles/115015663347",
                    "https://www.etsy.com/legal/policy/listing-image-requirements/253962679005",
                    "https://help.etsy.com/hc/en-us/articles/115015628347"],
    },
}


def _markets(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, list) or any(x not in MARKETS for x in v):
        raise ValueError(f"outputs_marketplaces must be some of {', '.join(MARKETS)}")
    return [m for m in MARKETS if m in v]


SETTINGS = {
    "outputs_marketplaces": (list(MARKETS), _markets),
    "outputs_licence": ("", lambda v: str(v or "").strip()[:200]),
}


def register() -> None:
    from ... import jobs
    for key, (default, validate) in SETTINGS.items():
        jobs.register_setting(key, default, validate)


def market(name: str) -> dict:
    if name not in MARKETS:
        raise OutputError(f"no marketplace {name}; one of {', '.join(MARKETS)}", 404)
    return {"name": name, **MARKETS[name]}


# ---------------------------------------------------------------- readiness (F19)

def _last_pack(s: dict, name: str) -> dict | None:
    p = Path(s["dir"]) / "exports" / f"pack-{name}.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def readiness(design_id: str, set_id: str | None = None, names: list[str] | None = None) -> dict:
    """Per marketplace: a checklist [{rule, ok, required, detail}] and `ready` (every
    required rule met). ok is None when it can only be known by building the pack. The
    check informs; it never blocks a pack."""
    design(design_id)
    try:
        s: dict | None = the_set(design_id, set_id)
    except OutputError:
        s = None
    ph = photos.list_photos(design_id)
    m = meta(design_id)
    names = names or settings().get("outputs_marketplaces") or list(MARKETS)
    fp = filepack.info(design_id, set_id) if s else {"made": False}
    out = {}
    for name in names:
        mk = market(name)
        checks: list[dict] = []

        def add(rule: str, ok: bool | None, required: bool, detail: str = "", checks: list[dict] = checks) -> None:
            checks.append({"rule": rule, "ok": ok, "required": required, "detail": detail})

        add("Rendered set", s is not None, True, "" if s else "render the design first")
        need = mk["photos_required"] or mk["photos_recommended"]
        if need:
            add(f"Real print photos: {len(ph)} of {need}", len(ph) >= need, bool(mk["photos_required"]),
                "required by the site" if mk["photos_required"] else "recommended: buyers trust prints over renders")
        if mk["photo_first"]:
            add("First image is a real photo", bool(ph), mk["photo_first"] == "required",
                "packs put photos before renders")
        if mk["min_short"] and ph:
            small = [p["name"] for p in ph if min(p["width"] or 0, p["height"] or 0) < mk["min_short"]]
            add(f"Photos at least {mk['min_short']:,} px on the short side", not small, False,
                f"smaller: {', '.join(small[:5])}" if small else "")
        if mk["licence_required"]:
            add("Licence chosen", bool(m["licence"]), True,
                m["licence"] or "set one on the design, in .sklent.yaml, or in Settings")
        add("Description", bool(m["summary"]), False, "" if m["summary"] else "add a summary")
        add("Print files from this commit", bool(fp.get("made")), False,
            "" if fp.get("made") else "turn on Settings → Print files and re-render")
        if mk["split_mb"] and fp.get("made"):
            last = _last_pack(s, name) if s else None
            fits = last.get("files_fit") if last else None
            add(f"Print files fit {mk['max_files']} × {mk['split_mb']} MB", fits, True,
                "checked when the pack is built" if fits is None else "")
        ready = all(c["ok"] for c in checks if c["required"])
        out[name] = {"label": mk["label"], "ready": ready, "checks": checks, "sources": mk["sources"]}
    return {"design_id": design_id, "photos": len(ph), "markets": out}


def badge_summary() -> dict[str, dict]:
    """For tiles: each design with photos, how many it has against the strictest enabled
    site's requirement, e.g. {id: {photos: 1, needed: 3, site: 'MakerWorld'}}."""
    names = settings().get("outputs_marketplaces") or list(MARKETS)
    need = max((MARKETS[n]["photos_required"] for n in names), default=0)
    site = next((MARKETS[n]["label"] for n in names if MARKETS[n]["photos_required"] == need), "")
    return {did: {"photos": n, "needed": need, "site": site} for did, n in photos.counts().items()}


# ---------------------------------------------------------------- listing text

def _spec_lines(d: dict, s: dict, m: dict) -> list[tuple[str, str]]:
    spec = spec_of(s) or {}
    r = report_of(s)
    rows: list[tuple[str, str]] = []
    env = fmt_envelope(envelope_mm(s))
    if env:
        rows.append(("Size (W × D × H)", env))
    bodies = spec.get("bodies") if isinstance(spec.get("bodies"), int) else r.get("bodies")
    if bodies:
        rows.append(("Parts", f"{bodies:,}"))
    mass = spec.get("mass_g") or (spec.get("mass_kg") * 1000 if spec.get("mass_kg") else None)
    if mass:
        rows.append(("Mass", f"{mass:,.1f} g" + (f" ({spec['material']})" if spec.get("material") else "")))
    params = spec.get("parameters")
    if isinstance(params, dict) and params:
        rows.append(("Parameters", ", ".join(f"{k} = {v}" for k, v in list(params.items())[:12])))
    elif isinstance(params, list) and params:
        rows.append(("Parameters", ", ".join(
            f"{p.get('name')} = {p.get('value', p.get('expr', ''))}" for p in params[:12] if isinstance(p, dict))))
    rows.append(("Licence", m["licence"] or "not set"))
    commit = commit_of(d, s)[:10]
    rows.append(("Version", f"commit {commit}, rendered {str(s.get('rendered_at') or '')[:10]}"))
    if not m.get("hide_source"):
        rows.append(("Source", d["html_url"]))
    return rows


def _bom_rows(s: dict) -> list[dict]:
    rows = bom_of(s) or []
    out = []
    for r in rows[:60]:
        if not isinstance(r, dict):
            continue
        out.append({"qty": r.get("qty") or r.get("count") or r.get("quantity") or 1,
                    "name": r.get("name") or r.get("definition") or r.get("part_number") or r.get("description") or "",
                    "supplier": r.get("supplier") or "", "url": r.get("url") or ""})
    return out


def listing_text(design_id: str, set_id: str | None = None, name: str = "printables", plain: bool | None = None) -> str:
    """listing.md for a marketplace (or plain text for Etsy-style descriptions)."""
    d = design(design_id)
    s = the_set(design_id, set_id)
    mk = market(name)
    m = meta(design_id)
    fp = filepack.info(design_id, set_id)
    details = "\n".join(f"- **{k}:** {v}" for k, v in _spec_lines(d, s, m))
    files = ""
    if fp.get("made"):
        names = {"step": "STEP (for CAD: edit or remix)", "3mf": "3MF (for slicers)", "stl": "STL (whole design)",
                 "stl-parts": "STL per part (zip)"}
        files = "## What's in the files\n\n" + "\n".join(
            f"- `{f['file']}`: {names.get(f['variant'], f['variant'])}" for f in fp["files"]) + "\n\n"
        if fp.get("excluded"):
            files = files[:-1] + f"Bought hardware isn't in the print files: {', '.join(fp['excluded'][:20])}.\n\n"
    bom = _bom_rows(s)
    bom_section = ""
    if bom:
        bom_section = "## Parts and hardware\n\n| qty | part | supplier |\n|---|---|---|\n" + "\n".join(
            f"| {b['qty']} | {b['name']} | {_supplier_md(b)} |" for b in bom) + "\n\n"
    notes = f"## Print notes\n\n{m['print_notes']}\n\n" if m.get("print_notes") else ""
    pictures = ("Photos of a real print come first. The grey pictures are CAD renders of the same commit as the "
                "files: they show the shape and size, not the colour or finish of a print.")
    tags = ("Tags: " + ", ".join(m["tags"])) if m.get("tags") else ""
    text = Template(TEMPLATE.read_text()).safe_substitute(
        title=m["title"], summary=m["summary"] or "", details=details, files_section=files, bom_section=bom_section,
        notes_section=notes, pictures=pictures, tags_line=tags)
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip() + "\n"
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    if plain if plain is not None else mk["plain_text"]:
        text = _plain(text)
    return text


def _supplier_md(b: dict) -> str:
    return f"[{b['supplier'] or 'link'}]({b['url']})" if b["url"] else str(b["supplier"])


def _plain(md: str) -> str:
    """Markdown to the plain text a description box takes (Etsy shows no Markdown)."""
    out = []
    for line in md.splitlines():
        line = line.replace("**", "").replace("`", "")
        if line.startswith("#"):
            line = line.lstrip("#").strip().upper()
        if line.startswith("|---"):
            continue
        if line.startswith("|"):
            line = " · ".join(c.strip() for c in line.strip("|").split("|"))
        out.append(line)
    return "\n".join(out).strip() + "\n"


# ---------------------------------------------------------------- the pack

def build(design_id: str, name: str, set_id: str | None = None) -> dict:
    d = design(design_id)
    s = the_set(design_id, set_id)
    mk = market(name)
    m = meta(design_id)
    cfg = brand.config()
    stem = stem_of(d)
    work = exports_dir(s) / f"_pack-{name}"
    with lock(f"pack:{s['dir']}:{name}"):
        import shutil
        shutil.rmtree(work, ignore_errors=True)
        (work / "images").mkdir(parents=True)
        files: list[dict] = []
        n = 0
        w, h = mk["image"]
        # real photos first, as they are (scaled down only)
        for p, path in photos.photo_paths(design_id):
            n += 1
            out = work / "images" / f"{n:02d}-photo-{p['id']}.jpg"
            res = media.resize_photo(path, out, min_short=mk["min_short"], cfg=cfg)
            files.append({**res, "path": f"images/{out.name}", "kind": "photo",
                          "rule": f"shortest side ≥ {mk['min_short']} px" if mk["min_short"] else "real print photo"})
        # renders: the cover, then every other still the set carries (V's and S's too)
        seen = set()
        for f in _gallery(s):
            if mk["max_images"] and n >= mk["max_images"]:
                break
            key = (f["variant"], f.get("style"))
            if key in seen:
                continue
            seen.add(key)
            n += 1
            label = f"{f['variant']}-{f.get('style') or 'still'}"
            out = work / "images" / f"{n:02d}-render-{label}.jpg"
            sheet = f["variant"] in SHEET_VARIANTS
            res = media.derive_still(path_of(s, f), out, w, h, "jpg", fill=mk["fill"], sheet=sheet, cfg=cfg)
            files.append({**res, "path": f"images/{out.name}", "kind": "render", "variant": f["variant"],
                          "rule": f"{w}×{h} ({_ratio(w, h)})"})
        skipped_images = max(0, len(_gallery(s)) - len(seen)) if mk["max_images"] else 0
        info = media.card_info(d, s, m["title"])
        fps = ((s.get("report") or {}).get("options") or {}).get("fps") or 30
        if mk["video"]:
            v = mk["video"]
            (work / "video").mkdir()
            out = work / "video" / f"{stem}-{name}.mp4"
            res = media.derive_clip(media.video_source(s, v["width"] / v["height"]), out, v["width"], v["height"],
                                    "mp4", max_bytes=int(v["max_mb"] * 1e6), seconds=v.get("seconds"), fps=fps,
                                    cfg=cfg, info=info)
            ok_len = res["seconds"] >= v.get("min_seconds", 0) and (
                not v.get("seconds") or res["seconds"] <= v["seconds"] + 0.05)
            files.append({**res, "path": f"video/{out.name}", "kind": "video", "fits": res["fits"] and ok_len,
                          "rule": f"≤ {v['width']}×{v['height']}, ≤ {v['max_mb']} MB, silent"
                                  + (f", {v.get('min_seconds', 0)}-{v['seconds']} s" if v.get("seconds") else "")})
        if mk["gif"]:
            g = mk["gif"]
            (work / "video").mkdir(exist_ok=True)
            out = work / "video" / f"{stem}-{name}.gif"
            res = media.derive_clip(media.video_source(s, 16 / 9), out, g["width"], round(g["width"] * 9 / 16), "gif",
                                    max_bytes=int(g["max_mb"] * 1e6), fill=0.9, fps=fps, cfg=cfg, info=info)
            files.append({**res, "path": f"video/{out.name}", "kind": "gif", "rule": f"≤ {g['max_mb']} MB"})
        # print files
        fp_note = None
        files_fit = None
        fp = filepack.info(design_id, set_id)
        if fp.get("made"):
            pack = filepack.build(design_id, set_id, mk["split_mb"], file_kist=False)
            (work / "files").mkdir()
            for part in pack["parts"]:
                src = exports_dir(s) / part["file"]
                dst = work / "files" / part["file"]
                shutil.copyfile(src, dst)
                files.append({"path": f"files/{part['file']}", "kind": "files", "bytes": part["bytes"],
                              "fits": not mk["split_mb"] or part["bytes"] <= mk["split_mb"] * 1e6,
                              "rule": f"≤ {mk['split_mb']} MB each" if mk["split_mb"] else "print files"})
            files_fit = (not mk["max_files"] or len(pack["parts"]) <= mk["max_files"]) and pack["fits"]
            if mk["max_files"] and len(pack["parts"]) > mk["max_files"]:
                fp_note = f"{len(pack['parts'])} files: the site takes at most {mk['max_files']}"
        else:
            fp_note = "no print files in this set (Settings → Print files, then re-render)"
        text = listing_text(design_id, set_id, name, plain=False)
        (work / "listing.md").write_text(text)
        if mk["plain_text"]:
            (work / "description.txt").write_text(_plain(text))
        ready = readiness(design_id, set_id, [name])["markets"][name]
        missing_photos = (mk["photos_required"] or 0) - len(photos.list_photos(design_id))
        if missing_photos > 0:
            (work / "00-REAL-PHOTOS-NEEDED.txt").write_text(
                f"{mk['label']} needs {mk['photos_required']} real photo(s) of the printed object; this pack has "
                f"{mk['photos_required'] - missing_photos}. Add them in Sklent (the design's Photos section) and "
                "rebuild, or put them first when you upload.\n")
        pack = {"marketplace": name, "label": mk["label"], "design": f"{d['owner']}/{d['repo']}:{d['path']}",
                "commit": commit_of(d, s), "brand": bool(cfg), "files": files, "files_fit": files_fit,
                "notes": [x for x in (fp_note, f"{skipped_images} more stills left out: the site takes "
                                               f"{mk['max_images']} images" if skipped_images else None) if x],
                "all_fit": all(f.get("fits", True) for f in files) and files_fit is not False,
                "checklist": ready["checks"], "ready": ready["ready"], "sources": mk["sources"],
                "posted": False}
        (work / "pack.json").write_text(json.dumps(pack, indent=2))
        entries = [(str(p.relative_to(work)), p) for p in sorted(work.rglob("*")) if p.is_file()]
        zname = f"{stem}-{name}-listing.zip"
        z = write_zip(exports_dir(s) / zname, entries)
        (exports_dir(s) / f"pack-{name}.json").write_text(json.dumps(pack, indent=2))
        shutil.rmtree(work, ignore_errors=True)
        item = kist_file(d, s, z, f"pack-{name}")
    url = f"/api/designs/{design_id}/outputs/exports/{zname}" + (f"?set_id={set_id}" if set_id else "")
    return {**pack, "file": zname, "url": url, "bytes": z.stat().st_size, "kist_item_id": item}


def _gallery(s: dict) -> list[dict]:
    """Renders for a pack: the shaded square first (the cover), then the rest."""
    stills = still_files(s)
    return [f for f in stills if f["variant"] != "hires" or not any(
        g["variant"] == "social" and g.get("style") == f.get("style") for g in stills)]


def _ratio(w: int, h: int) -> str:
    from math import gcd
    g = gcd(w, h)
    return f"{w // g}:{h // g}"
