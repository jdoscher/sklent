"""F5 project page export: a static, self-contained HTML folder (zipped) for one design
or a whole source: hero, gallery (real photos first), turntable, spec (S's spec.json when
present), BOM, the print files, licence and commit, in Sklent's drafting look. It works
offline (relative paths, vendored OFL fonts, no scripts, nothing fetched) and is only
ever downloaded: Sklent never hosts or posts it.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from string import Template

from ... import db, jobs, sets
from ...config import get_settings
from . import brand, filepack, media, photos
from .common import (
    OutputError,
    commit_of,
    design,
    envelope_mm,
    exports_dir,
    fmt_envelope,
    hero_file,
    kist_file,
    lock,
    meta,
    path_of,
    report_of,
    safe,
    spec_of,
    stem_of,
    still_files,
    the_set,
    write_zip,
)
from .listing import _bom_rows, _spec_lines

HERE = Path(__file__).resolve().parent
FONTS = HERE.parents[1] / "web" / "fonts"
FONT_FILES = ("inter-latin-wght-normal.woff2", "instrument-serif-latin-400-normal.woff2",
              "jetbrains-mono-latin-wght-normal.woff2", "OFL-Inter.txt", "OFL-InstrumentSerif.txt",
              "OFL-JetBrainsMono.txt")
e = html.escape


def _css(fonts: str) -> str:
    return Template((HERE / "templates" / "page.css").read_text()).safe_substitute(fonts=fonts)


def _fonts_into(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for f in FONT_FILES:
        if (FONTS / f).is_file():
            shutil.copyfile(FONTS / f, folder / f)


def _still(src: Path, out: Path, cfg: dict | None, max_long: int = 1800, photo: bool = False) -> Path:
    """A downscaled JPEG copy, watermarked if the brand says so (photos only if allowed)."""
    use = cfg if (cfg and (not photo or cfg.get("photos", True))) else None
    media.resize_photo(src, out, max_long=max_long, cfg={**use, "photos": True} if use else None)
    return out


def _design_folder(d: dict, s: dict, folder: Path, *, fonts: str, cfg: dict | None, include_files: bool,
                   hide_source: bool | None, back: str | None = None) -> dict:
    """Write one design's page into `folder` (index.html + assets/ + files/)."""
    m = meta(d["id"])
    hide = m["hide_source"] if hide_source is None else hide_source
    m = {**m, "hide_source": hide}
    assets = folder / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    gallery: list[tuple[str, str]] = []
    for i, (p, path) in enumerate(photos.photo_paths(d["id"]), 1):
        _still(path, assets / f"photo-{i:02d}.jpg", cfg, photo=True)
        gallery.append((f"assets/photo-{i:02d}.jpg", p.get("caption") or "Photo of a real print"))
    for i, f in enumerate(still_files(s), 1):
        if f["variant"] == "hires":
            continue  # the square still is the same view, smaller
        _still(path_of(s, f), assets / f"render-{i:02d}.jpg", cfg)  # type: ignore[arg-type]
        cap = f"CAD render · {f['variant']} · {f.get('style') or ''}".rstrip(" ·")
        gallery.append((f"assets/render-{i:02d}.jpg", cap))
    hero = gallery[0][0] if gallery else None
    hf = hero_file(s)
    if hero is None and hf:
        _still(path_of(s, hf), assets / "hero.jpg", cfg)  # type: ignore[arg-type]
        hero = "assets/hero.jpg"
    video = None
    try:
        src = media.video_source(s, 16 / 9)
        if brand.has_watermark(cfg) or (cfg and (cfg["title_card"] or cfg["end_card"])):
            media.derive_clip(src, assets / "turntable.mp4", 1280, 720, "mp4", fill=0.85, cfg=cfg,
                              info=media.card_info(d, s, m["title"]),
                              fps=((s.get("report") or {}).get("options") or {}).get("fps") or 30)
        else:
            shutil.copyfile(src, assets / "turntable.mp4")
        video = "assets/turntable.mp4"
    except OutputError:
        pass
    spec = spec_of(s)
    if spec:
        (folder / "spec.json").write_text(json.dumps(spec, indent=2))
    files_rows: list[tuple[str, int, str]] = []
    fp = filepack.info(d["id"], s["id"])
    if include_files and fp.get("made"):
        built = filepack.build(d["id"], s["id"], file_kist=False)
        (folder / "files").mkdir(exist_ok=True)
        for part in built["parts"]:
            shutil.copyfile(exports_dir(s) / part["file"], folder / "files" / part["file"])
            files_rows.append((f"files/{part['file']}", part["bytes"], part["sha256"]))
    elif fp.get("made"):
        files_rows = [(f["file"], f["bytes"], f["sha256"]) for f in fp["files"]]
    body = _design_html(d, s, m, hero=hero, gallery=gallery, video=video, files=files_rows,
                        linked=include_files, back=back)
    (folder / "index.html").write_text(_doc(m["title"], body, fonts))
    return {"title": m["title"], "hero": hero}


def _doc(title: str, body: str, fonts: str) -> str:
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="generator" content="sklent">\n<title>{e(title)}</title>\n'
            f"<style>\n{_css(fonts)}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n")


def _design_html(d: dict, s: dict, m: dict, *, hero: str | None, gallery: list[tuple[str, str]], video: str | None,
                 files: list[tuple[str, int, str]], linked: bool, back: str | None) -> str:
    commit = commit_of(d, s)[:10]
    out = ['<main class="sheet">']
    if back:
        out.append(f'<p class="note"><a href="{e(back)}">← all designs</a></p>')
    sub = f"{d['owner']}/{d['repo']} · {d['path']}" if not m["hide_source"] else d["path"].rsplit("/", 1)[-1]
    out.append(f'<header class="head"><h1>{e(m["title"])}</h1><p class="sub">{e(sub)}</p></header>')
    if m.get("summary"):
        out.append(f'<p class="summary">{e(m["summary"])}</p>')
    if hero:
        alt = "Photo of a real print" if hero.startswith("assets/photo") else f"CAD render of {m['title']}"
        out.append(f'<figure class="hero"><img src="{e(hero)}" alt="{e(alt)}"></figure>')
    if len(gallery) > 1:
        out.append("<h2>Pictures</h2><section class=\"gallery\">")
        out += [f'<figure><img src="{e(src)}" alt="{e(cap)}" loading="lazy"><figcaption>{e(cap)}</figcaption></figure>'
                for src, cap in gallery[1:]]
        out.append("</section>")
    if video:
        out.append('<h2>Turntable</h2><section class="turntable">'
                   f'<video src="{e(video)}" autoplay muted loop playsinline controls></video></section>')
    spec_rows = _spec_lines(d, s, m)
    bom = _bom_rows(s)
    out.append('<section class="cols"><div><h2>Spec</h2><dl>')
    for k, v in spec_rows:
        v_html = f'<a href="{e(v)}">{e(v)}</a>' if v.startswith("https://") else e(v)
        out.append(f"<dt>{e(k)}</dt><dd>{v_html}</dd>")
    out.append("</dl></div>")
    if bom:
        out.append('<div><h2>Parts and hardware</h2><table><tr><th>qty</th><th>part</th><th>supplier</th></tr>')
        for b in bom:
            sup = e(str(b["supplier"]))
            if b["url"]:
                sup = f'<a href="{e(b["url"])}">{sup or "link"}</a>'
            out.append(f'<tr><td class="n">{e(str(b["qty"]))}</td><td>{e(str(b["name"]))}</td><td>{sup}</td></tr>')
        out.append("</table></div>")
    out.append("</section>")
    if files:
        out.append('<h2>Files</h2><table><tr><th>file</th><th>size</th><th>sha256</th></tr>')
        for name, size, digest in files:
            label = f'<a href="{e(name)}" download>{e(name.rsplit("/", 1)[-1])}</a>' if linked else e(name)
            out.append(f'<tr><td>{label}</td><td class="n">{size / 1e6:.1f} MB</td>'
                       f'<td class="n">{e(digest[:16])}…</td></tr>')
        out.append("</table>")
    if m.get("print_notes"):
        out.append(f'<h2>Print notes</h2><p class="notes">{e(m["print_notes"])}</p>')
    env = fmt_envelope(envelope_mm(s))
    bodies = report_of(s).get("bodies")
    cells = [("w4 t", "Title", m["title"]),
             ("w2", "Source", "—" if m["hide_source"] else f"{d['owner']}/{d['repo']} @ {d['ref']}"),
             ("", "Commit", commit or "—"), ("", "Date", str(s.get("rendered_at") or "")[:10] or "—"),
             ("w2", "Envelope", env or "—"), ("", "Bodies", f"{bodies:,}" if bodies else "—"),
             ("", "Licence", m["licence"] or "not set"),
             ("w4", "Made with", "Sklent: SolidCraft renders, CAD files exported from the same commit")]
    out.append('<footer class="tb">' + "".join(
        f'<div class="{c}"><span class="k">{e(k)}</span><span class="v">{e(v)}</span></div>' for c, k, v in cells)
        + "</footer>")
    out.append("</main>")
    return "\n".join(out)


def build_design(design_id: str, set_id: str | None = None, *, include_files: bool = True,
                 hide_source: bool | None = None) -> dict:
    d = design(design_id)
    s = the_set(design_id, set_id)
    stem = stem_of(d)
    cfg = brand.config()
    with lock(f"page:{s['dir']}"):
        work = exports_dir(s) / "_page"
        shutil.rmtree(work, ignore_errors=True)
        root = work / f"{stem}-page"
        _fonts_into(root / "assets" / "fonts")
        _design_folder(d, s, root, fonts="assets/fonts", cfg=cfg, include_files=include_files,
                       hide_source=hide_source)
        entries = [(str(p.relative_to(work)), p) for p in sorted(root.rglob("*")) if p.is_file()]
        z = write_zip(exports_dir(s) / f"{stem}-page.zip", entries)
        shutil.rmtree(work, ignore_errors=True)
        item = kist_file(d, s, z, "page")
    url = f"/api/designs/{design_id}/outputs/exports/{z.name}" + (f"?set_id={set_id}" if set_id else "")
    return {"design_id": design_id, "set_id": s["id"], "file": z.name, "url": url, "bytes": z.stat().st_size,
            "files": len(entries), "kist_item_id": item}


def source_dir(source_id: str) -> Path:
    p = get_settings().data_dir / "outputs" / "sources" / safe(source_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_source(source_id: str, *, include_files: bool = False, hide_source: bool = False) -> dict:
    """One page for a whole source: a grid of its rendered designs, each linking to its own
    page inside the same folder. Print files are left out by default (size)."""
    src = jobs.get_source(source_id)
    with db.connect() as conn:
        ds = db.rows(conn.execute("SELECT * FROM designs WHERE source_id = ? AND status != 'removed' "
                                  "ORDER BY path", [source_id]).fetchall())
    cfg = brand.config()
    name = safe("-".join(x for x in (src["owner"], src["repo"]) if x))
    out_dir = source_dir(source_id)
    with lock(f"source-page:{source_id}"):
        work = out_dir / "_page"
        shutil.rmtree(work, ignore_errors=True)
        root = work / f"{name}-page"
        _fonts_into(root / "assets" / "fonts")
        cards = []
        used: set[str] = set()
        for d in ds:
            s = sets.latest_set(d["id"])
            if s is None:
                continue
            slug = stem_of(d)
            if slug in used:
                slug = f"{slug}-{d['id'][:6]}"
            used.add(slug)
            info = _design_folder(d, s, root / "designs" / slug, fonts="../../assets/fonts", cfg=cfg,
                                  include_files=include_files, hide_source=hide_source, back="../../index.html")
            hero = f"designs/{slug}/{info['hero']}" if info["hero"] else None
            cards.append((slug, info["title"], hero, fmt_envelope(envelope_mm(s)), d["path"]))
        if not cards:
            shutil.rmtree(work, ignore_errors=True)
            raise OutputError("this source has no rendered designs yet", 404)
        label = "/".join(x for x in (src["owner"], src["repo"], src["path"]) if x)
        body = ['<main class="sheet">', f'<header class="head"><h1>{e(src["repo"] or src["owner"])}</h1>'
                f'<p class="sub">{e("" if hide_source else label)} · {len(cards)} designs</p></header>',
                '<section class="grid">']
        for slug, title, hero, env, path in cards:
            img = f'<img src="{e(hero)}" alt="{e(title)}" loading="lazy">' if hero else ""
            body.append(f'<a href="designs/{e(slug)}/index.html">{img}<div class="name">{e(title)}</div>'
                        f'<div class="sub">{e(env or path)}</div></a>')
        body += ["</section>", '<footer class="tb"><div class="w4"><span class="k">Made with</span>'
                 '<span class="v">Sklent: SolidCraft renders, exported for offline viewing</span></div></footer>',
                 "</main>"]
        (root / "index.html").write_text(_doc(src["repo"] or src["owner"], "\n".join(body), "assets/fonts"))
        entries = [(str(p.relative_to(work)), p) for p in sorted(root.rglob("*")) if p.is_file()]
        z = write_zip(out_dir / f"{name}-page.zip", entries)
        shutil.rmtree(work, ignore_errors=True)
    return {"source_id": source_id, "file": z.name, "url": f"/api/sources/{source_id}/outputs/page.zip",
            "bytes": z.stat().st_size, "designs": len(cards), "files": len(entries)}


def source_zip(source_id: str) -> Path:
    jobs.get_source(source_id)
    zs = sorted(source_dir(source_id).glob("*-page.zip"))
    if not zs:
        build_source(source_id)
        zs = sorted(source_dir(source_id).glob("*-page.zip"))
    return zs[0]
