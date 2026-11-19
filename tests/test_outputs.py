"""Outputs and publishing (area O): presets, brand, file pack, listing packs, photos,
project pages and the Kist review board. SolidCraft is faked; ffmpeg runs for real when
it is installed (clips are skipped without it)."""

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sklent import db, jobs, sets, steps
from sklent.features import outputs
from sklent.features.outputs import brand, common, filepack, listing, page, photos, presets, review
from sklent.kist import Kist

H = {"Authorization": "Bearer test-token-0123456789"}
FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


# ---------------------------------------------------------------- fixtures

def _render_like(w: int, h: int, box: tuple[int, int, int, int], shade: int = 120) -> Image.Image:
    """A SolidCraft-like still: a vertical light gradient with a grey part."""
    top, bottom = np.array([240, 243, 247]), np.array([200, 206, 214])
    t = np.linspace(0, 1, h)[:, None]
    row = (top * (1 - t) + bottom * t).astype(np.uint8)
    arr = np.repeat(row[:, None, :], w, axis=1)
    x0, y0, x1, y1 = box
    arr[y0:y1, x0:x1] = shade
    return Image.fromarray(arr)


def _clip(path: Path, w: int, h: int) -> None:
    frames = path.parent / f"_f_{path.stem}"
    frames.mkdir()
    for i in range(12):
        x = w // 3 + i * 4
        _render_like(w, h, (x, h // 3, x + w // 4, 2 * h // 3)).save(frames / f"f{i:04d}.png")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "6", "-i", str(frames / "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    shutil.rmtree(frames)


@pytest.fixture
def made(settings):
    """A rendered design with a set on disk: stills (and clips with ffmpeg)."""
    src = jobs.add_source("https://github.com/o/r")
    did = db.new_id()
    out = settings.renders_dir / did / ("b" * 12)
    out.mkdir(parents=True)
    files = []
    for style, shade in (("shaded", 120), ("wireframe", 200)):
        _render_like(1024, 1024, (380, 420, 640, 600), shade).save(out / f"case-{style}-social-1024.png")
        files.append({"file": f"case-{style}-social-1024.png", "style": style, "variant": "social",
                      "width": 1024, "height": 1024})
        _render_like(1600, 900, (650, 330, 950, 570), shade).save(out / f"case-{style}-hires-1600x900.png")
        files.append({"file": f"case-{style}-hires-1600x900.png", "style": style, "variant": "hires",
                      "width": 1600, "height": 900})
    # a sheet another area added (S's spec card): fitted whole, never cropped
    sheet = Image.new("RGB", (1200, 675), (250, 250, 250))
    sheet.save(out / "case-spec-card.png")
    files.append({"file": "case-spec-card.png", "style": "shaded", "variant": "spec-card", "width": 1200,
                  "height": 675})
    if FFMPEG:
        _clip(out / "case-shaded-1080p.mp4", 640, 360)
        files.append({"file": "case-shaded-1080p.mp4", "style": "shaded", "variant": "1080p", "width": 640,
                      "height": 360})
        _clip(out / "case-shaded-reel-1080x1920.mp4", 360, 640)
        files.append({"file": "case-shaded-reel-1080x1920.mp4", "style": "shaded", "variant": "reel",
                      "width": 360, "height": 640})
    report = {"options": {"palette": "cool-grey", "fps": 30, "seconds": 2}, "bodies": 3, "hidden_bodies": 0,
              "bounds_mm": [[0, 0, 0], [95, 66, 32]]}
    (out / "report.json").write_text(json.dumps(report))
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha, commit_sha, status,"
            " render_dir, files, rendered_sha, rendered_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [did, src["id"], "o", "r", "main", "parts/case.sc", "https://github.com/o/r/blob/c/parts/case.sc",
             "b" * 40, "c" * 40, "rendered", str(out), json.dumps(files), "b" * 40, db.now(), db.now()])
    return SimpleNamespace(id=did, dir=out, source_id=src["id"], files=files)


@pytest.fixture
def client():
    from sklent.app import app
    return TestClient(app)


def _photo_bytes(w=2400, h=1800, exif_gps=True) -> bytes:
    img = Image.new("RGB", (w, h), (170, 110, 80))
    buf = io.BytesIO()
    exif = Image.Exif()
    if exif_gps:
        exif[0x8825] = {2: (37.0, 46.0, 0.0)}  # GPSInfo: latitude
        exif[0x010F] = "PhoneMaker"
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


# ---------------------------------------------------------------- framing

def test_part_box_and_window():
    img = _render_like(800, 600, (300, 200, 500, 380))
    box = common.part_box(np.asarray(img))
    assert abs(box[0] - 300) <= 2 and abs(box[1] - 200) <= 2 and abs(box[2] - 500) <= 2 and abs(box[3] - 380) <= 2
    left, top, ww, wh = common.frame_window(box, 4 / 3, 0.5)
    assert ww / wh == pytest.approx(4 / 3)
    assert 200 / ww <= 0.5 + 1e-6 and 180 / wh <= 0.5 + 1e-6
    assert left + ww / 2 == pytest.approx(400, abs=2)  # centred
    lft = common.frame_window(box, 16 / 9, 0.8, "left")
    assert lft[0] + lft[2] / 3 == pytest.approx(400, abs=2)  # the part's centre on the left third


def test_fit_pads_outside_the_image_with_the_gradient():
    img = _render_like(400, 400, (150, 150, 250, 250))
    out = common.fit_image(img, 800, 200, fill=0.9)  # much wider than the source: padded at the sides
    arr = np.asarray(out)
    assert out.size == (800, 200)
    assert abs(int(arr[100, 2, 0]) - int(arr[100, 400, 0])) < 40 or arr[100, 2, 0] > 150  # no black bars
    assert arr[:, :5].min() > 150


# ---------------------------------------------------------------- F6 presets

def test_preset_validation():
    assert presets.validate(presets.DEFAULT_PRESETS) == presets.DEFAULT_PRESETS
    with pytest.raises(ValueError):
        presets.validate([{"name": "Bad Name", "width": 10, "height": 10}])
    with pytest.raises(ValueError):
        presets.validate([{"name": "a", "width": 100, "height": 100, "format": "bmp"}])
    with pytest.raises(ValueError):
        presets.validate([{"name": "a", "width": 100, "height": 100}, {"name": "a", "width": 100, "height": 100}])
    one = presets.validate(json.dumps([{"name": "x", "width": "640", "height": 480, "max_mb": ""}]))
    assert one[0]["width"] == 640 and one[0]["max_mb"] is None and one[0]["format"] == "jpg"


def test_still_presets_are_sized_cached_and_in_a_zip(made, client):
    r = client.get(f"/api/designs/{made.id}/outputs/presets", headers=H)
    assert r.status_code == 200 and {p["name"] for p in r.json()["presets"]} >= {"cover-4x3", "github-social"}
    assert not any(p["made"] for p in r.json()["presets"])
    e = client.post(f"/api/designs/{made.id}/outputs/presets/github-social", headers=H).json()
    assert e["made"] and e["fits"] and e["bytes"] <= 1_000_000
    path = made.dir / "presets" / e["file"]
    with Image.open(path) as im:
        assert im.size == (1280, 640)
    mtime = path.stat().st_mtime_ns
    again = client.post(f"/api/designs/{made.id}/outputs/presets/github-social", headers=H).json()
    assert again["file"] == e["file"] and path.stat().st_mtime_ns == mtime  # cached
    r = client.get(e["url"], headers=H)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    pdf = presets.make(made.id, "handshake")
    assert pdf["file"].endswith(".pdf") and (made.dir / "presets" / pdf["file"]).read_bytes()[:4] == b"%PDF"
    assert pdf["bytes"] <= 1_000_000
    jobs.set_options({"outputs_presets": [p for p in presets.DEFAULT_PRESETS if p["format"] != "mp4"]})
    z = client.get(f"/api/designs/{made.id}/outputs/presets.zip?set=true", headers=H)
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "presets.json" in names and any(n.startswith("set/") for n in names)
    assert sum(n.startswith("presets/") for n in names) == len(presets.DEFAULT_PRESETS) - 1
    assert client.post(f"/api/designs/{made.id}/outputs/presets/nope", headers=H).status_code == 404


def test_presets_need_a_rendered_set(settings, client):
    src = jobs.add_source("https://github.com/o/r2")
    did = db.new_id()
    with db.connect() as conn:
        conn.execute("INSERT INTO designs (id, source_id, owner, repo, ref, path, html_url, blob_sha, updated_at)"
                     " VALUES (?,?,?,?,?,?,?,?,?)",
                     [did, src["id"], "o", "r2", "main", "a.sc", "u", "x" * 40, db.now()])
    assert client.post(f"/api/designs/{did}/outputs/presets/cover-4x3", headers=H).status_code == 404
    assert client.get(f"/api/designs/{did}/outputs", headers=H).json()["presets"] == []


@needs_ffmpeg
def test_clip_presets_fit_their_caps(made):
    e = presets.make(made.id, "cults-800")
    out = made.dir / "presets" / e["file"]
    assert e["fits"] and out.stat().st_size <= 10e6
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out)], capture_output=True, text=True).stderr
    assert "800x800" in probe and "Audio" not in probe
    jobs.set_options({"outputs_presets": [{"name": "tiny-gif", "width": 320, "height": 320, "format": "gif",
                                           "max_mb": 0.2}]})
    g = presets.make(made.id, "tiny-gif")
    assert g["file"].endswith(".gif") and g["bytes"] <= 200_000


# ---------------------------------------------------------------- F23 brand

def test_brand_is_off_by_default_and_marks_copies_only(made):
    assert brand.config() is None
    before = {f["file"]: common.sha256(made.dir / f["file"]) for f in made.files}
    plain = presets.make(made.id, "cover-4x3")
    jobs.set_options({"outputs_brand_text": "shop.example", "outputs_brand_position": "bottom-right"})
    cfg = brand.config()
    assert cfg and cfg["text"] == "shop.example"
    marked = presets.make(made.id, "cover-4x3")
    assert marked["file"] == plain["file"]  # rebuilt in place: the brand is part of the cache key
    with Image.open(made.dir / "presets" / marked["file"]) as im:
        arr = np.asarray(im.convert("L")).astype(int)
    corner, centre_top = arr[-160:, -400:], arr[:60, 700:1000]
    assert corner.min() < 120  # the dark text in the corner
    assert centre_top.min() > 150  # nothing elsewhere
    after = {f["file"]: common.sha256(made.dir / f["file"]) for f in made.files}
    assert before == after  # the filed set is never touched
    with pytest.raises(ValueError):
        jobs.set_options({"outputs_brand_position": "middle"})


def test_brand_mark_upload_and_cards(made, client):
    png = io.BytesIO()
    Image.new("RGBA", (200, 80), (30, 30, 30, 255)).save(png, "PNG")
    r = client.put("/api/outputs/brand/mark", content=png.getvalue(), headers=H)
    assert r.status_code == 200 and r.json()["width"] == 200
    assert client.put("/api/outputs/brand/mark", content=b"not an image", headers=H).status_code == 422
    jobs.set_options({"outputs_brand_mark": True, "outputs_brand_title_card": True, "outputs_brand_end_card": True,
                      "outputs_brand_card_text": "Example Shop"})
    for kind in ("watermark", "title", "end"):
        r = client.get(f"/api/outputs/brand/preview?kind={kind}&design_id={made.id}", headers=H)
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = brand.card(640, 360, "title", {"title": "Case", "envelope": "95 × 66 × 32 mm"}, brand.config())
    assert img.size == (640, 360)
    assert client.delete("/api/outputs/brand/mark", headers=H).json() == {"mark": None}
    assert brand.config()["mark"] is False


@needs_ffmpeg
def test_cards_lengthen_a_branded_clip(made):
    plain = presets.make(made.id, "cults-800")
    jobs.set_options({"outputs_brand_text": "x", "outputs_brand_title_card": True, "outputs_brand_end_card": True,
                      "outputs_brand_card_seconds": 1})
    p = presets.get_preset("cults-800")
    from sklent.features.outputs import media
    s = common.the_set(made.id)
    out = made.dir / "presets" / "branded.mp4"
    res = media.derive_clip(media.video_source(s, 1), out, p["width"], p["height"], "mp4", max_bytes=10_000_000,
                            cfg=brand.config(), info={"title": "Case"})
    assert res["seconds"] == pytest.approx(2 + 2, abs=0.2) and plain["made"]


# ---------------------------------------------------------------- F7 file pack (render step)

class ExportSC:
    def __init__(self):
        self.calls = []

    def execute(self, command, **params):
        self.calls.append((command, params))
        Path(params["path"]).write_bytes(f"solid {params.get('bodies')} {params['format']}\n".encode() * 200)

    def paint(self, *a):
        pass


def _ctx(tmp_path, bodies, settings, hidden=()):
    info = [{"name": b, "visible": b not in hidden} for b in bodies]
    return steps.StepContext(sc=ExportSC(), design=tmp_path / "d.sc", out_dir=tmp_path, stem="kit", opts=None,
                             info=info, bodies=list(bodies), box=([0, 0, 0], [1, 1, 1]), palette=None, pitch=0.4,
                             report={}, settings=settings)


def test_filepack_step_is_registered_off_by_default():
    step = next(s for s in steps.registered() if s.name == "outputs-filepack")
    assert 90 <= step.order <= 99
    assert jobs.get_all_settings()["outputs_filepack"] is False


def test_filepack_step_small_design(tmp_path):
    ctx = _ctx(tmp_path, ["Base", "Lid", "M3x8 screw", "Ref"], {"outputs_filepack": True,
                                                                  "outputs_filepack_exclude": ["m3*"]},
               hidden=("Ref",))
    filepack.export_step(ctx)
    variants = {o.variant: o.file for o in ctx.added}
    assert variants == {"step": "kit.step", "3mf": "kit.3mf", "stl": "kit.stl", "stl-parts": "kit-stl-parts.zip"}
    assert all(o.style == "files" for o in ctx.added) and not ctx.guard  # meshes skip the colour guard
    whole = [p for c, p in ctx.sc.calls if p["path"].endswith("kit.step")][0]
    assert whole["bodies"] == ["Base", "Lid"]  # hidden and excluded bodies left out
    zipped = zipfile.ZipFile(tmp_path / "kit-stl-parts.zip").namelist()
    assert sorted(zipped) == ["stl/Base.stl", "stl/Lid.stl"]
    car = json.loads((tmp_path / filepack.SIDECAR).read_text())
    assert car["bodies"] == 2 and car["excluded"] == ["M3x8 screw"] and car["hidden_left_out"] == 1
    assert all(len(f["sha256"]) == 64 for f in car["files"])
    assert not (tmp_path / "_parts").exists()


def test_filepack_step_big_design_goes_per_body_and_skips_3mf(tmp_path):
    bodies = [f"B{i}" for i in range(10)]
    ctx = _ctx(tmp_path, bodies, {"outputs_filepack": True, "outputs_filepack_body_budget": 5})
    filepack.export_step(ctx)
    variants = {o.variant for o in ctx.added}
    assert variants == {"step", "stl-parts"}  # no 3MF, no whole STL above the budget
    car = json.loads((tmp_path / filepack.SIDECAR).read_text())
    assert any("3MF skipped" in s for s in car["skipped"])
    whole = [p for c, p in ctx.sc.calls if p["path"].endswith("kit.step")][0]
    assert "bodies" not in whole  # nothing left out: the whole design as SolidCraft has it


def test_filepack_build_readme_manifest_and_split(made, client):
    # files a filepack step would have written into this set
    big = np.random.default_rng(1).integers(0, 255, 1_300_000, dtype=np.uint8).tobytes()  # incompressible
    for name in ("case.step", "case.stl"):
        (made.dir / name).write_bytes(big)
    car = {"bodies": 3, "excluded": [], "skipped": [], "files": [
        {"file": n, "format": n.rsplit(".", 1)[1], "variant": n.rsplit(".", 1)[1], "bytes": len(big),
         "sha256": common.sha256(made.dir / n)} for n in ("case.step", "case.stl")]}
    sets.write_json(made.dir, filepack.SIDECAR, car)
    jobs.set_options({"outputs_licence": "CC-BY-4.0"})
    one = client.post(f"/api/designs/{made.id}/outputs/filepack", headers=H, json={}).json()
    assert len(one["parts"]) == 1
    z = zipfile.ZipFile(made.dir / "exports" / one["parts"][0]["file"])
    assert {"README.md", "LICENSE.txt", "manifest.json", "files/case.step", "files/case.stl"} <= set(z.namelist())
    man = json.loads(z.read("manifest.json"))
    assert man["commit"] == "c" * 40 and man["licence"] == "CC-BY-4.0"
    assert {f["path"]: f["sha256"] for f in man["files"]}["files/case.step"] == common.sha256(made.dir / "case.step")
    assert "creativecommons.org/licenses/by/4.0" in z.read("LICENSE.txt").decode()
    assert "`cccccccccc`" in z.read("README.md").decode()
    split = filepack.build(made.id, None, 2)  # 2 MB parts: one file each
    assert len(split["parts"]) == 2 and split["fits"]
    assert all(p["bytes"] <= 2e6 for p in split["parts"])
    assert not (made.dir / "exports" / one["parts"][0]["file"]).exists()  # replaced by the parts
    r = client.get(split["parts"][1]["url"], headers=H)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    r = client.get(f"/api/designs/{made.id}/outputs/exports/..%2Fsklent.db", headers=H)
    assert b"SQLite" not in r.content[:16]
    for bad in ("../sklent.db", ".hidden", "a/b.zip", ""):
        with pytest.raises(common.OutputError):
            common.export_path(common.the_set(made.id), bad)


def test_filepack_info_when_off(made):
    info = filepack.info(made.id)
    assert info["made"] is False and "off" in info["skipped"][0]


# ---------------------------------------------------------------- F19 photos

def test_photos_upload_strip_exif_order_delete(made, client):
    r = client.post(f"/api/designs/{made.id}/outputs/photos?name=a.jpg&caption=first", content=_photo_bytes(),
                    headers=H)
    assert r.status_code == 201
    a = r.json()
    with Image.open(photos.photo_file(made.id, a["id"])) as im:
        assert not im.getexif().get(0x8825) and not im.getexif().get(0x010F)
    b = client.post(f"/api/designs/{made.id}/outputs/photos?name=b.jpg", content=_photo_bytes(1200, 900),
                    headers=H).json()
    assert [p["id"] for p in photos.list_photos(made.id)] == [a["id"], b["id"]]
    client.patch(f"/api/designs/{made.id}/outputs/photos/{b['id']}", json={"position": 0}, headers=H)
    assert [p["id"] for p in photos.list_photos(made.id)] == [b["id"], a["id"]]
    assert client.post(f"/api/designs/{made.id}/outputs/photos", content=b"nope", headers=H).status_code == 422
    assert client.get(b["url"], headers=H).status_code == 200
    assert client.delete(f"/api/designs/{made.id}/outputs/photos/{b['id']}", headers=H).status_code == 200
    assert [p["id"] for p in photos.list_photos(made.id)] == [a["id"]]
    assert client.get("/api/outputs/readiness", headers=H).json()[made.id]["photos"] == 1


def test_readiness_per_marketplace(made):
    r = listing.readiness(made.id)["markets"]
    assert set(r) == set(listing.MARKETS)
    mw = {c["rule"]: c for c in r["makerworld"]["checks"]}
    assert mw["Real print photos: 0 of 3"]["ok"] is False and mw["Real print photos: 0 of 3"]["required"]
    assert r["makerworld"]["ready"] is False and r["etsy"]["ready"] is False
    for _ in range(3):
        photos.add_photo(made.id, _photo_bytes(), "p.jpg")
    common.set_meta(made.id, {"licence": "CC-BY-4.0"})
    r = listing.readiness(made.id)["markets"]
    assert r["makerworld"]["ready"] and r["etsy"]["ready"] and r["printables"]["ready"]


# ---------------------------------------------------------------- F13 listing packs

def test_listing_pack_orders_photos_first_and_checks_rules(made, client):
    photos.add_photo(made.id, _photo_bytes(), "p.jpg")
    common.set_meta(made.id, {"title": "Desk case", "summary": "A case.", "licence": "CC-BY-4.0",
                              "print_notes": "PETG, 0.2 mm, no supports"})
    sets.write_json(made.dir, "bom.json", [{"name": "M3x8 SHCS", "qty": 4, "supplier": "Shop",
                                            "url": "https://shop.example/m3"}])
    r = client.post(f"/api/designs/{made.id}/outputs/listing/printables", headers=H)
    assert r.status_code == 200, r.text
    pack = r.json()
    z = zipfile.ZipFile(made.dir / "exports" / pack["file"])
    images = sorted(n for n in z.namelist() if n.startswith("images/"))
    assert images[0].startswith("images/01-photo-") and "render" in images[1]
    assert any("spec-card" in n for n in images)  # other areas' stills ride along generically
    with Image.open(io.BytesIO(z.read(images[1]))) as im:
        assert im.size == (2000, 1500)
    text = z.read("listing.md").decode()
    assert "# Desk case" in text and "CC-BY-4.0" in text and "M3x8 SHCS" in text and "PETG" in text
    assert "95 × 66 × 32 mm" in text
    meta = json.loads(z.read("pack.json"))
    assert meta["posted"] is False and meta["sources"] and all("rule" in f for f in meta["files"])


def test_etsy_pack_needs_a_real_photo_and_is_plain_text(made):
    jobs.set_options({"outputs_presets": presets.DEFAULT_PRESETS})
    if not FFMPEG:
        pytest.skip("the Etsy pack makes a clip")
    pack = listing.build(made.id, "etsy")
    z = zipfile.ZipFile(made.dir / "exports" / pack["file"])
    assert "00-REAL-PHOTOS-NEEDED.txt" in z.namelist() and "description.txt" in z.namelist()
    desc = z.read("description.txt").decode()
    assert "**" not in desc and "#" not in desc.splitlines()[0]
    imgs = [n for n in z.namelist() if n.startswith("images/")]
    with Image.open(io.BytesIO(z.read(imgs[0]))) as im:
        assert min(im.size) >= 2000
    assert pack["ready"] is False
    vid = next(f for f in pack["files"] if f["kind"] == "video")
    assert vid["bytes"] <= 100e6 and "5-15 s" in vid["rule"]
    assert vid["fits"] is False and pack["all_fit"] is False  # the test clip is 2 s: under Etsy's 5 s


def test_listing_text_endpoint(made, client):
    r = client.get(f"/api/designs/{made.id}/outputs/listing/etsy/text", headers=H)
    assert r.status_code == 200 and "DETAILS" in r.text
    assert client.get(f"/api/designs/{made.id}/outputs/listing/ebay/text", headers=H).status_code == 404


# ---------------------------------------------------------------- F5 pages

def test_design_page_is_self_contained(made, client):
    common.set_meta(made.id, {"title": "<script>alert(1)</script> case"})
    photos.add_photo(made.id, _photo_bytes(), "p.jpg", "On the desk")
    r = client.get(f"/api/designs/{made.id}/outputs/page.zip", headers=H)
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    root = names[0].split("/")[0]
    html = z.read(f"{root}/index.html").decode()
    assert "<script>" not in html and "&lt;script&gt;" in html
    for ref in __import__("re").findall(r'(?:src|href)="([^"]+)"', html):
        assert ref.startswith("https://github.com/") or f"{root}/{ref}" in names  # every local ref ships
    assert 'src="http' not in html and "@import" not in html
    assert f"{root}/assets/fonts/OFL-Inter.txt" in names
    assert html.index("assets/photo-01.jpg") < html.index("assets/render-")  # the real photo leads
    hidden = page.build_design(made.id, hide_source=True)
    z2 = zipfile.ZipFile(made.dir / "exports" / hidden["file"])
    assert "github.com" not in z2.read(f"{root}/index.html").decode()


def test_source_page(made, client):
    r = client.post(f"/api/sources/{made.source_id}/outputs/page", headers=H, json={})
    assert r.status_code == 200 and r.json()["designs"] == 1
    z = client.get(f"/api/sources/{made.source_id}/outputs/page.zip", headers=H)
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert any(n.endswith("designs/case/index.html") for n in names)


# ---------------------------------------------------------------- metadata

def test_meta_precedence(made, monkeypatch):
    m = common.meta(made.id)
    assert m["title"] == "case" and m["from"]["title"] == "default"
    fake = SimpleNamespace(get=lambda did: {"title": "Repo title", "license": "MIT", "print_notes": {"layer": "0.2"}})
    monkeypatch.setattr(common, "repo_config", fake)
    m = common.meta(made.id)
    assert (m["title"], m["licence"], m["print_notes"]) == ("Repo title", "MIT", "layer: 0.2")
    common.set_meta(made.id, {"title": "Mine"})
    assert common.meta(made.id)["title"] == "Mine"
    monkeypatch.setattr(common, "repo_config", SimpleNamespace(get=lambda did: 1 / 0))
    assert common.meta(made.id)["title"] == "Mine"  # a broken repo config doesn't break exports
    with pytest.raises(common.OutputError):
        common.set_meta(made.id, {"colour": "red"})


# ---------------------------------------------------------------- Kist: filing and F26

class FakeKist:
    """Kist's REST API, the parts used here (kist/api/items, folders, boards, shares, proofing)."""

    def __init__(self):
        self.items, self.boards, self.shares, self.calls = [], {}, {}, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, m = request.url.path, request.method
        self.calls.append((m, path))
        if path == "/api/folders" and m == "GET":
            return httpx.Response(200, json=[])
        if path == "/api/folders":
            body = json.loads(request.content)
            return httpx.Response(201, json={"id": f"f-{body['name']}", **body})
        if path == "/api/items" and m == "POST":
            iid = f"i{len(self.items)}"
            self.items.append({"id": iid, "body": request.content})
            return httpx.Response(201, json={"item": {"id": iid}})
        if path.startswith("/api/items/") and m == "DELETE":
            return httpx.Response(200, json={})
        if path == "/api/boards" and m == "POST":
            body = json.loads(request.content)
            bid = f"b{len(self.boards)}"
            self.boards[bid] = body
            return httpx.Response(201, json={"id": bid, "name": body["name"]})
        if path.startswith("/api/boards/") and m == "GET":
            return httpx.Response(200 if path.rsplit("/", 1)[1] in self.boards else 404, json={"deleted_at": None})
        if path.startswith("/api/boards/") and m == "DELETE":
            return httpx.Response(200, json={"status": "trashed"})
        if path == "/api/shares" and m == "POST":
            body = json.loads(request.content)
            sid = f"s{len(self.shares)}"
            self.shares[sid] = {**body, "proofing": False}
            return httpx.Response(201, json={"id": sid, "url": f"https://kist.example.com/s/slug{sid}",
                                             "expires_at": "2099-01-01T00:00:00Z"})
        if path.endswith("/proofing") and m == "PATCH":
            self.shares[path.split("/")[3]]["proofing"] = json.loads(request.content)["enabled"]
            return httpx.Response(200, json={"enabled": True})
        if path.endswith("/revoke"):
            return httpx.Response(200, json={"status": "revoked"})
        return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture
def kist(monkeypatch, made):
    fake = FakeKist()
    real = Kist

    def make(*a, **k):
        return real(url="https://kist.example.com", token="t", client=httpx.Client(transport=httpx.MockTransport(fake)))

    for mod in (common, photos, review):
        monkeypatch.setattr(mod, "Kist", make)
    with db.connect() as conn:  # the render filed its set (jobs._render)
        items = [{"id": f"r-{f['file']}", "file": f["file"]} for f in made.files]
        db.update(conn, "designs", made.id, kist_folder_id="folder-1", kist_items=items)
    return fake


def test_exports_land_in_kist_once(made, kist):
    e = presets.make(made.id, "cover-4x3")
    assert e["kist_item_id"] == "i0"
    presets.make(made.id, "cover-4x3")
    assert len(kist.items) == 1  # same bytes: not uploaded again
    body = kist.items[0]["body"].decode("latin-1")
    assert "format:size-cover-4x3" in body and "rev:cccccccccc" in body and "design:case" in body


def test_review_board_and_share_link(made, kist, client):
    photos.add_photo(made.id, _photo_bytes(), "p.jpg")
    r = client.post(f"/api/designs/{made.id}/outputs/review/board", headers=H)
    assert r.status_code == 200, r.text
    board = kist.boards["b0"]
    assert board["item_ids"][0] == "i0"  # the real photo first
    assert board["item_ids"][1] == "r-case-shaded-social-1024.png"
    assert outputs.share_link(made.id) is None
    r = client.post(f"/api/designs/{made.id}/outputs/review/share", headers=H, json={})
    assert r.status_code == 403 and "public" in r.json()["detail"]  # off by default
    assert not kist.shares
    jobs.set_options({"outputs_review_share_links": True})
    share = client.post(f"/api/designs/{made.id}/outputs/review/share", headers=H, json={}).json()["share"]
    assert share["active"] and share["proofing"]
    assert kist.shares["s0"]["target_kind"] == "board" and kist.shares["s0"]["target_id"] == "b0"
    assert kist.shares["s0"]["proofing"] is True and kist.shares["s0"]["allow_download"] is False
    assert outputs.share_link(made.id) == "https://kist.example.com/s/slugs0"
    client.delete(f"/api/designs/{made.id}/outputs/review/share", headers=H)
    assert outputs.share_link(made.id) is None
    assert client.delete(f"/api/designs/{made.id}/outputs/review/board", headers=H).json()["board"] is None


def test_review_needs_kist(made, client):
    r = client.post(f"/api/designs/{made.id}/outputs/review/board", headers=H)
    assert r.status_code == 409 and "Kist is off" in r.json()["detail"]
    assert client.get(f"/api/designs/{made.id}/outputs/review", headers=H).json()["kist_on"] is False


def test_source_board_takes_one_still_per_design(made, kist, client):
    r = client.post(f"/api/sources/{made.source_id}/outputs/review/board", headers=H)
    assert r.status_code == 200
    assert kist.boards["b0"]["item_ids"] == ["r-case-shaded-social-1024.png"]


# ---------------------------------------------------------------- wiring

def test_module_is_wired_in():
    from sklent import features
    from sklent.mcp_server import mcp
    assert "outputs" in features.MODULES
    tools = {t.name for t in __import__("asyncio").run(mcp.list_tools())}
    assert {"get_outputs", "make_output_preset", "build_file_pack", "export_project_page", "build_listing_pack",
            "listing_readiness", "listing_text", "set_listing_details", "attach_photo", "list_photos",
            "make_review_board", "create_share_link", "revoke_share_link"} <= tools
    s = jobs.get_all_settings()
    assert s["outputs_filepack"] is False and s["outputs_review_share_links"] is False
    assert s["outputs_brand_text"] == "" and s["outputs_presets"] == presets.DEFAULT_PRESETS


def test_summary_endpoint(made, client):
    r = client.get(f"/api/designs/{made.id}/outputs", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["set_id"] == "b" * 12 and body["filepack"]["made"] is False and "etsy" in body["readiness"]
