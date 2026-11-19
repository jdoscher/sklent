# sklent

Point it at a GitHub or Forgejo account, repo, folder or file, and it renders every
[SolidCraft](https://github.com/tangency-labs/solidcraft) design it finds into a media set,
then files the set into a [Kist](https://github.com/jdoscher/kist) folder.

For each design, in a **shaded** and a **wireframe** (x-ray) style:

| file | size | for |
|---|---|---|
| `<design>-<style>-1080p.mp4` | 1920×1080 | turntable movie |
| `<design>-<style>-reel-1080x1920.mp4` | 1080×1920 | Instagram reels / stories |
| `<design>-<style>-discord-640p.mp4` | 1138×640, < 10 MB | Discord |
| `<design>-<style>.gif` | 640 px wide | anywhere |
| `<design>-<style>-social-2048.png` | 2048×2048 | social posts |
| `<design>-<style>-hires-3840x2160.png` | 3840×2160 | the web |

Parts are always rendered in **cool grey** or **white** (a setting), never in a design's own
colours: every body is repainted before rendering, and a colour guard greys out any pixel
that still carries colour (per-face paint, imported STEP colours).

In Kist, each set lands in `SolidCraft/<owner>/<repo>/<design>`, tagged `solidcraft`,
`repo:<owner>/<repo>`, `design:<name>`, `style:<shaded|wireframe>`, `format:<variant>` and
`palette:<name>`, with the file's URL at the rendered commit as its source. Re-rendering
trashes the previous set's items (restorable from Kist's trash).

## How it works

- **Discovery** uses the forges' git-tree APIs; nothing is cloned. `.sc` and `.solidcraft`
  files are found with their blob SHAs, so a re-scan renders only what changed. Folders
  named `tests`, `test`, `fixtures` and `corpus` are skipped by default (per-source `exclude`).
- **Rendering** drives `solidcraft-cli mcp --headless` over stdio: the design loads once,
  then each frame is a `screenshot` with an orbit camera. The camera distance is fitted so
  the bounding box stays in frame at every angle, separately for landscape and portrait.
- **Encoding** is ffmpeg (H.264, `+faststart`; palette-optimised GIFs).
- **Big designs render in parallel.** SolidCraft spends a fixed amount of CPU per headless
  frame (~0.55 s on a 2,000-body assembly, at any resolution), on one core. After the first
  8 frames, if a frame takes over 50 ms and enough frames are left to repay another load,
  up to `SK_RENDER_PROCESSES` processes share the remaining frames, capped by free memory at
  the first process's size. Small parts stay in one process. Each set's `report.json` has
  the frame time, process count and per-step timings.
- One worker renders one design at a time; a scheduler re-scans sources every
  `SK_SCAN_INTERVAL_MINUTES`.

## Running it

Needs Docker and, for speed, a GPU visible as `/dev/dri` (Intel/AMD via Mesa Vulkan).
Without one, SolidCraft falls back to software Vulkan: same pictures, slower.

```bash
cp .env.example .env    # set SK_TOKEN, SK_KIST_URL / SK_KIST_TOKEN, forge tokens
docker compose up -d --build
```

Open `http://<host>:8090`, paste the token, then paste a URL and press **Render**:

- `https://github.com/<owner>`: every non-fork, non-archived repo
- `https://github.com/<owner>/<repo>` or `…/tree/<branch>/<folder>`
- `https://github.com/<owner>/<repo>/blob/<branch>/<path>.sc`: one design
- the same shapes on Forgejo (`…/src/branch/<branch>/<path>`), and SSH clone URLs

Hovering a tile plays its turntable; clicking it opens the design as a drawing sheet: the
file at its true pixel size, a numbered schedule of every file with downloads, and a title
block (source and commit, revision, date, palette, envelope in mm, bodies). The UI uses
Kist 2.0's design system (gallery grey by default; dark and light under **Appearance**)
and works on a phone (the menu opens filters, sources and jobs). See `docs/design.md`.

A design that is only on disk can be rendered without the app:

```bash
docker compose run --rm app sklent render /data/some.sc /data/out --palette white
```

### Configuration (`.env`)

| variable | default | |
|---|---|---|
| `SK_TOKEN` | | **Required.** Token for the UI, API and MCP (16+ chars) |
| `SK_PORT` | `8090` | Host port |
| `SK_DATA` | `./data` | Database and local render sets |
| `SK_KIST_URL`, `SK_KIST_TOKEN` | | Kist to file sets into; empty URL keeps renders local |
| `SK_KIST_ROOT_FOLDER` | `SolidCraft` | Top-level Kist folder |
| `SK_GITHUB_TOKEN` | | Private repos, and a higher API rate limit |
| `SK_FORGEJO_URL`, `SK_FORGEJO_TOKEN` | | Your Forgejo; the token is only sent to that host |
| `SK_SCAN_INTERVAL_MINUTES` | `360` | Periodic re-scan; `0` turns it off |
| `SK_RENDER_PROCESSES` | `4` | Most SolidCraft processes per design (see below) |
| `SK_RENDER_GID` | `992` | Group owning `/dev/dri/renderD128` on the host |

Render settings (palette, length, frame rate, camera pitch, still and GIF sizes, styles)
are in the UI's **Settings** and the MCP `set_render_settings` tool.

## Outputs and publishing

Everything that turns a render set into something to upload or hand over, under the
drawing sheet's **Publish** pages. Sklent packages; it never posts. Exported copies live
with their set (`<set>/presets/`, `<set>/exports/`), so they belong to one commit, and with
Kist on each one is also filed in the design's Kist folder (same tags plus
`format:<variant>`, e.g. `format:size-cover-4x3`, `format:pack-etsy`, `format:page`). The
filed render set itself is never changed.

- **Output presets** (F6). Named sizes cut from the set on demand and framed on the part
  (Pillow for stills, ffmpeg for clips), each stepped down until it fits its site's cap.
  Defaults: Printables/MakerWorld cover 2000×1500 (4:3), Cults video 800×800 under 10 MB,
  YouTube thumbnail 1280×720 under 2 MB with the part on the left third, LinkedIn and
  Instagram 1080×1350 (4:5), GitHub social preview 1280×640 under 1 MB, Handshake one-page
  PDF under 1 MB. Edit the list under **Output presets → Presets and brand**. **Download all**
  zips them (optionally with the set).
- **Print and release file pack** (F7, `outputs_filepack`, off). A render step exports STEP,
  3MF and STL from the very design the pictures came from: the whole design up to
  `outputs_filepack_body_budget` bodies (64), one STL per body in a zip, and above the
  budget only STEP plus per-body STLs (a 1,418-body 3MF takes about 19 minutes). Hidden
  bodies and names matching `outputs_filepack_exclude` (bought hardware such as `M3*`) are
  left out. The pack zip adds `README.md`, `LICENSE.txt` and `manifest.json` (sha256 of
  every file) and can be split into standalone zips, e.g. Etsy's 5 files × 20 MB.
- **Project page** (F5). A static HTML folder (zipped) for a design or a whole source:
  hero, pictures with real photos first, turntable, spec (`spec.json` when present), parts
  (`bom.json` when present), files, licence and commit, in the drafting look. No scripts,
  nothing fetched, fonts included: it works offline. Optionally without the source link.
- **Listing packs** (F13). One zip per marketplace (Printables, MakerWorld, Thingiverse,
  Cults, Etsy): pictures in upload order cut to the site's sizes, the clips it takes, the
  print files split to its limits, `listing.md` filled from the spec, BOM, licence and print
  notes (Etsy also gets a plain-text `description.txt`), and `pack.json` listing every file
  with the rule it was checked against and where the rule comes from.
- **Real photos and "ready to list"** (F19). Upload photos of the printed part per design
  (EXIF and GPS removed; never cropped or repainted). They lead every pack and page. Each
  marketplace gets a checklist (real photos, licence, print files, sizes); it informs and
  never blocks. A tile shows `photos n/N` once a design has photos.
- **Brand** (F23, off). A watermark (text or an uploaded PNG mark), title and end cards on
  clips, applied only to exported copies.
- **Kist review board** (F26). With Kist on, a design's set (or one still per design of a
  source) becomes a Kist board, real photos first. A **share link** to it, with Kist's guest
  proofing, is a public page on your Kist: it needs `outputs_review_share_links` on, is
  made only when you click (and confirm), expires (30 days), and can be revoked.

Marketplace rules (checked 2026-11-18; sites change them): Etsy photos at least 2,000 px on
the short side, up to 10 photos and one 5–15 s video under 100 MB, the first photo of the
real item, digital files 5 × 20 MB
([images](https://help.etsy.com/hc/en-us/articles/115015663347),
[image policy](https://www.etsy.com/legal/policy/listing-image-requirements/253962679005),
[digital files](https://help.etsy.com/hc/en-us/articles/115015628347)); MakerWorld at least
three real printed images, real-photo cover recommended
([upload guidelines](https://wiki.bambulab.com/en/makerworld/tutorials/model-upload-guidelines));
Printables 4:3 cover ([Prusa forum](https://forum.prusa3d.com/forum/english-forum-general-discussion-announcements-and-releases/printables-model-cover-photo-aspect-ratio-question/));
Cults videos at most 800×800 and 10 MB ([advice](https://cults3d.com/en/pages/advice-publishing-3d-file));
Thingiverse publishes no limits and recommends a photo of the print
([guide](https://www.thingiverse.com/blog?p=how-to-upload-your-first-thing)); YouTube
thumbnails 1280×720 under 2 MB ([help](https://support.google.com/youtube/answer/72431));
GitHub social preview 1280×640 under 1 MB ([docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview));
Handshake documents 1 MB ([help](https://support.joinhandshake.com/hc/en-us/articles/218692648));
LinkedIn 1080×1350 ([Sendible](https://www.sendible.com/insights/linkedin-post-size)).

Listing details (title, summary, licence, print notes, tags) come from the design's
**Listing packs** page, else the repo's `.sklent.yaml` (`title`, `licence`/`license`,
`description`, `print_notes`, `tags`, and `print_exclude` for the file pack), else the file
name and the `outputs_licence` setting.

| setting | default | |
|---|---|---|
| `outputs_presets` | the seven above | Preset list: `{name, label, width, height, format (jpg/png/webp/pdf/mp4/gif), max_mb, fill, anchor (center/left/right), seconds, enabled}` |
| `outputs_filepack` | `false` | Export STEP/3MF/STL during renders |
| `outputs_filepack_formats` | `step, 3mf, stl` | Which formats |
| `outputs_filepack_body_budget` | `64` | Whole-design mesh and 3MF up to this many bodies |
| `outputs_filepack_max_parts` | `2000` | Most per-body STLs |
| `outputs_filepack_per_body` | `true` | Per-body STLs for multi-body designs below the budget too |
| `outputs_filepack_quality` | `standard` | Mesh quality: standard, fine, finest |
| `outputs_filepack_exclude` | none | Body name patterns to leave out |
| `outputs_marketplaces` | all five | Marketplaces checked and packed |
| `outputs_licence` | none | Licence when neither the design nor the repo sets one |
| `outputs_brand_text` | none | Watermark text |
| `outputs_brand_mark` | `false` | Use the uploaded PNG mark |
| `outputs_brand_position`, `_opacity`, `_size` | `bottom-right`, `0.6`, `12` % | Where and how strong |
| `outputs_brand_photos` | `true` | Mark real photos in packs too |
| `outputs_brand_title_card`, `_end_card` | `false` | Cards on exported clips |
| `outputs_brand_card_text`, `_card_seconds` | none, `1.5` | End-card line, card length |
| `outputs_review_share_links` | `false` | Allow Kist share links (public pages) |
| `outputs_review_proofing` | `true` | Guest proofing on share links |
| `outputs_review_share_days` | `30` | Expiry (0 = never) |
| `outputs_review_allow_download` | `false` | Guests may download |

These are render settings (UI **Settings**, `GET/PUT /api/settings`); there are no new
environment variables.

## MCP

A streamable-HTTP MCP endpoint at `/mcp`, with the same bearer token:

```bash
claude mcp add --transport http sklent http://<host>:8090/mcp \
  --header "Authorization: Bearer $SK_TOKEN"
```

| tool | |
|---|---|
| `render_url` | Scan a URL now and queue renders; returns job ids |
| `wait_for_job`, `job_status`, `list_jobs` | Follow progress |
| `cancel_job` | Drop a queued job, or stop a running render (its SolidCraft processes are killed) |
| `get_render_set` | Files, sizes, download paths, Kist folder and item ids |
| `view_render` | See a still (image content) |
| `add_source`, `list_sources`, `scan_source`, `list_designs`, `render_design` | Finer control |
| `get_render_settings`, `set_render_settings` | Palette, length, sizes |
| `get_outputs` | A design's presets, print files, photos, listing details, readiness and Kist board |
| `make_output_preset` | Make one preset or all enabled ones; returns download paths and whether each fits |
| `build_file_pack` | The print pack zip (README, licence, manifest), optionally split (`split_mb`) |
| `export_project_page` | Offline HTML page for a design or a source (zip) |
| `build_listing_pack`, `listing_readiness`, `listing_text` | Marketplace packs, the checklist, the listing text |
| `set_listing_details` | Title, summary, licence, print notes, tags |
| `attach_photo`, `list_photos` | Real print photos (base64 in) |
| `make_review_board`, `create_share_link`, `revoke_share_link` | Kist board; public share link only when the setting allows and the user asks |

With Kist's own MCP connected as well, an agent can go on to browse, view and tag the
filed sets there.

## API

`/api/sources`, `/api/designs`, `/api/designs/{id}/render`, `/api/designs/{id}/files/{name}`,
`/api/render-url`, `/api/jobs`, `POST /api/jobs/{id}/cancel`, `/api/settings`, `/api/status`;
see `sklent/api.py`. Outputs (`sklent/features/outputs`): `/api/designs/{id}/outputs` (summary),
`…/outputs/meta`, `…/outputs/presets[/{name}[/file]]`, `…/outputs/presets.zip`,
`…/outputs/filepack`, `…/outputs/exports/{file}`, `…/outputs/page[.zip]`,
`…/outputs/listing[/{market}[/text]]`, `…/outputs/photos[/{photo}[/file]]`,
`…/outputs/review[/board|/share]`, the same `page` and `review` routes under
`/api/sources/{id}/outputs/`, and `/api/outputs/{brand,brand/mark,brand/preview,readiness,marketplaces,presets/defaults}`.

Each design carries `blob` (its file's git blob SHA, the sheet's revision) and `report`:
`{bodies, hidden_bodies, bounds_mm, palette, frame_ms, processes, timings_s}` from its newest
render set's `report.json` (`bounds_mm` is `[[x, y, z] min, [x, y, z] max]`; `palette` is the
one that set was rendered with), or `null` before the first render.

## Limits

- Designs are fetched as single files. A design that links parts from other files in its
  repo isn't supported yet.
- SolidCraft's headless renderer ignores `view.visual_style`, so the wireframe style is an
  x-ray: see-through bodies with every edge (see `docs/spike.md`).

MIT licensed.
