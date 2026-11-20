# Publishing

Everything that turns a render set into something to upload or hand over lives under the
drawing sheet's **Publish** pages. **Sklent packages; it never posts.** Exported copies live
with their set (`<set>/presets/`, `<set>/exports/`), so they belong to one commit, and with
Kist on each is also filed in the design's Kist folder (the same tags plus `format:<variant>`,
e.g. `format:size-cover-4x3`, `format:pack-etsy`, `format:page`). The filed render set itself
is never changed.

## Output presets

Named sizes cut from the set on demand and framed on the part (Pillow for stills, ffmpeg for
clips), each stepped down until it fits its site's cap. Edit the list under **Output presets →
Presets and brand**; **Download all** zips them, optionally with the set.

| preset | size | limit |
|---|---|---|
| Printables / MakerWorld cover | 2000×1500 (4:3) | |
| Cults video | 800×800 MP4 | under 10 MB |
| YouTube thumbnail | 1280×720, the part on the left third | under 2 MB |
| LinkedIn 4:5, Instagram 4:5 | 1080×1350 | |
| GitHub social preview | 1280×640 | under 1 MB |
| Handshake | one-page PDF | under 1 MB |

## Print and release file pack

`outputs_filepack`, **off** by default. A render step exports STEP, 3MF and STL from the very
design the pictures came from: the whole design up to `outputs_filepack_body_budget` bodies
(64), one STL per body in a zip, and above the budget only STEP plus per-body STLs (a
1,418-body 3MF takes about 19 minutes). Hidden bodies and names matching
`outputs_filepack_exclude` (bought hardware such as `M3*`) are left out. The pack zip adds
`README.md`, `LICENSE.txt` and `manifest.json` (the SHA-256 of every file) and can be split
into standalone zips, e.g. Etsy's 5 files of 20 MB.

## Project page

A static HTML folder (zipped) for a design or a whole source: hero, pictures with real photos
first, turntable, spec, parts, files, licence and commit, in the drafting look. No scripts,
nothing fetched, fonts included: it works offline. Optionally without the source link.

## Listing packs

One zip per marketplace (Printables, MakerWorld, Thingiverse, Cults, Etsy): the pictures in
upload order cut to the site's sizes, the clips it takes, the print files split to its limits,
`listing.md` filled from the spec, BOM, licence and print notes (Etsy also gets a plain-text
`description.txt`), and `pack.json` listing every file with the rule it was checked against
and where that rule comes from.

Listing details (title, summary, licence, print notes, tags) come from the design's **Listing
packs** page, else the repo's `.sklent.yaml` (`title`, `licence`/`license`, `description`,
`print_notes`, `tags`, and `print_exclude` for the file pack), else the file name and the
`outputs_licence` setting.

The marketplace rules were checked on 2026-11-18, and sites change them; the README lists the
sources for each.

## Real photos and "ready to list"

Upload photos of the printed part per design. EXIF, GPS included, is removed; photos are
never cropped or repainted. They lead every pack and page. Each marketplace gets a checklist
(real photos, licence, print files, sizes) that informs and never blocks. A tile shows
`photos n/N` once a design has photos.

## Brand

**Off** by default. A watermark (text or an uploaded PNG mark), plus title and end cards on
clips, applied only to exported copies, never to the render set.

## Kist review board

With [Kist](kist.md) on, a design's set (or one still per design of a source) becomes a Kist
board, real photos first. A **share link** to it, with Kist's guest proofing, is a public page
on your Kist: it needs `outputs_review_share_links` on, is made only when you click and
confirm, expires (30 days by default) and can be revoked.

## Settings

| setting | default | |
|---|---|---|
| `outputs_presets` | seven presets | The preset list above |
| `outputs_filepack` | off | Export STEP/3MF/STL during renders |
| `outputs_filepack_formats` | `step, 3mf, stl` | |
| `outputs_filepack_body_budget`, `outputs_filepack_max_parts` | `64`, `2000` | Whole-design 3MF/STL up to this many bodies; per-body STLs are skipped above the second |
| `outputs_filepack_per_body`, `outputs_filepack_quality`, `outputs_filepack_exclude` | on, `standard`, none | One STL per body; mesh quality (`standard`, `fine`, `finest`); names left out |
| `outputs_marketplaces` | all five | Marketplaces checked and packed |
| `outputs_licence` | `""` | Licence when neither the design nor the repo sets one |
| `outputs_brand_text`, `_mark`, `_position`, `_opacity`, `_size`, `_photos` | none, off, `bottom-right`, `0.6`, `12` %, on | Watermark on exported copies only |
| `outputs_brand_title_card`, `_end_card`, `_card_text`, `_card_seconds` | off, off, none, `1.5` | Cards on exported clips |
| `outputs_review_share_links` | off | Allow Kist share links (made only on a click) |
| `outputs_review_proofing`, `_share_days`, `_allow_download` | on, `30`, off | Share link details |

There are no environment variables for publishing.
