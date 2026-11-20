# sklent

<p>
  <a href="https://sklent.app"><img alt="Docs" src="https://img.shields.io/badge/docs-sklent.app-1C1B19"></a>
  <a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-1C1B19"></a>
</p>

**Docs: [sklent.app](https://sklent.app)** (install, outputs, revisions, publishing, render helpers, MCP).

Point it at a GitHub or Forgejo account, repo, folder, file, branch, tag or pull request, and
it renders every [SolidCraft](https://github.com/tangency-labs/solidcraft) design (and every
STEP, STL and 3MF file) it finds into a media set, then files the set into a
[Kist](https://github.com/jdoscher/kist) folder.

## What's new in 0.2.1

- **GPU control.** Settings → **Rendering** picks where this server renders: on the GPU
  (default, at most `render_gpu_processes` SolidCraft processes at once, default 1), in
  software (Mesa lavapipe on the CPU: no GPU load at all), or off. Quiet hours (e.g.
  `22:00-07:00`) either hold renders for helpers or switch to software.
- **Render helpers.** Another machine with SolidCraft (a Linux box with
  `docker-compose.helper.yml`, or natively on a Mac) can take every render; this server keeps
  scans, filing into Kist and the revision history. See [Render helpers](#render-helpers).
- Each set's `report.json` and the drawing sheet's title block say where it was rendered
  (`renderer: gpu|software`, `host`).

### Upgrading from 0.2.0

Rebuild the image (`docker compose up -d --build`); the database gains its new columns and
tables on start. Nothing changes until you change it: the renderer stays `gpu`, but **at most
one SolidCraft process now uses the GPU at once** (`render_gpu_processes`, default 1;
0.2.0 used up to `SK_RENDER_PROCESSES` for big designs). Raise it in Settings → Rendering
if the GPU isn't shared. Set `TZ` in `.env` before you use quiet hours.

## What's new in 0.2

| area | what you get | on by default |
|---|---|---|
| Design | Kist 2.0's design system: gallery/dark/light, drawing-sheet detail view, phone layout | yes |
| Inputs | STEP/STL/3MF designs, linked multi-file assemblies, `.sklent.yaml`, branch/tag/PR renders, class sets with deadlines, read-only viewer tokens | STEP and mesh scanning on; posting review comments off |
| Revisions | every version keeps its set; compare, filmstrip, changelog; Kist version links; build-history timelapse | history on; timelapse off |
| Views | quick check, per-render outputs, shot presets, masters, exploded, section, configurations, highlight, motion studies, transparent, studio hero, plate, bed fit | quick check, configurations, motion studies, bed fit |
| Specs | `spec.json` and spec card, BOM, engineering views sheet (PNG/PDF), dimension callout, contact sheet, assembly steps | all but assembly steps |
| Outputs | marketplace presets, print file pack, project page, listing packs, real photos, brand, Kist review board and share link | presets/pages/packs on demand; file pack, brand and share links off |

### Upgrading from 0.1

- **Older sets are now kept.** A re-render adds a set for the new version instead of
  replacing the old one, and older Kist items stay (tagged `rev:<commit>`, linked as
  versions). Untagged versions beyond `revisions_keep` (10) are pruned from disk, never from
  Kist unless `revisions_prune_kist` is on.
- **SolidCraft 0.44.1** (from 0.28.0): rebuild the image (`docker compose up -d --build`).
- **New optional settings** (`views_*`, `specs_*`, `outputs_*`, `revisions_*`, `inputs_*`)
  live in the app's Settings, not `.env`; see the table under
  [Configuration](#configuration). Nothing new is outbound unless you turn it on.

## Renders

For each design, in a **shaded** and a **wireframe** (x-ray) style:

| file | size | for |
|---|---|---|
| `<design>-<style>-1080p.mp4` | 1920×1080 | turntable movie |
| `<design>-<style>-reel-1080x1920.mp4` | 1080×1920 | Instagram reels / stories |
| `<design>-<style>-discord-640p.mp4` | 1138×640, < 10 MB | Discord |
| `<design>-<style>.gif` | 640 px wide | anywhere |
| `<design>-<style>-social-2048.png` | 2048×2048 | social posts |
| `<design>-<style>-hires-3840x2160.png` | 3840×2160 | the web |

Every render starts with a **quick check**: one shaded iso still (`<design>-preview.png`,
1024×1024) made seconds after the design loads and shown on its tile while the rest
renders. Which of the six files above a render makes is a setting (**Outputs**) and can be
chosen per render on the design's sheet; none at all is a quick check on its own. A quick
check of a design that already has a set is kept beside it (`<design>/quick/`) and never
replaces the full set.

### Views and render modes

Off unless noted; each is a render setting (`views_*`) and can also be turned on for one
render. Extra files land in the set, in Kist (`format:<variant>`) and on the design's sheet.

| variant | file | what | setting (default) |
|---|---|---|---|
| `preview` | `<design>-preview.png` | quick-check still, made first | always |
| `preset-<shot>` | `<design>-<style>-<shot>-1080p.mp4` | shot presets: `half-orbit` (eases onto the iso angle), `push-in`, `top-to-iso`, `low-angle`; eased in and out, every frame fitted to the part | `views_shot_half_orbit`, `…_push_in`, `…_top_to_iso`, `…_low_angle` (off); `views_shot_seconds` (6) |
| `master-4k`, `prores`, `frames-zip` | `<design>-<style>-master-3840x2160.mp4` / `-prores.mov` / `-frames-3840x2160.zip` | edit-ready masters: 4K H.264, ProRes 422 HQ, the PNG sequence; an exact loop (no repeated frame), up to 60 s | `views_master_4k`, `views_master_prores`, `views_master_zip` (off); `views_master_seconds` (0 = the turntable's length) |
| `exploded`, `explode-anim` | `<design>-exploded-3840x2160.png`, `<design>-explode-1080p.mp4` + `.gif` | the design's first saved exploded view, else SolidCraft's automatic one; the animation comes apart and goes back together. Needs two or more components | `views_exploded` (off), `views_explode_scale` (1) |
| `section` | `<design>-section-3840x2160.png`, `-section-ortho-…` | a cut through the centre containing the longest axis, with filled, hatched caps; a 3/4 view and a face-on orthographic one | `views_section` (off) |
| `config-<n>`, `config-lineup` | `<design>-config-<n>-<row>.png`, `<design>-config-lineup.png` | one still per configuration row, all at one scale, and a lineup with the row names | `views_configs` (on; only designs with 2+ rows), `views_configs_max` (8) |
| `motion-<study>` | `<design>-motion-<study>-1080p.mp4` + `.gif` | each motion study played | `views_motion` (on; only designs with studies), `views_motion_max` (6) |
| `highlight`, `highlight-turntable` | `<design>-highlight-3840x2160.png`, `<design>-highlight-1080p.mp4` | "my part": the named bodies solid, the rest x-ray | per design: names or globs on the sheet's **My part**, else `highlight:` in `.sklent.yaml` |
| `transparent` | `<design>-transparent-<w>x<h>.png` | RGBA stills at the social and high-res sizes (SolidCraft's CPU renderer) | `views_transparent` (off) |
| `hero` | `<design>-hero-3840x2160.png` | path-traced studio still with alpha (`cpu_raytrace`, studio budget); skipped, with the reason, when the scene is too big | `views_hero` (off), `views_hero_timeout` (900 s) |
| `plate` | `<design>-plate.png` | every distinct part laid on its thinnest side (a guess, labelled so), top-down orthographic at one scale, on a 10 mm grid, `×n` for repeats | `views_plate` (off) |

A **bed-fit badge** on each tile (`fits 256³`, or `> 180³`) checks every part's bounding
box, in any axis-aligned orientation, against a named bed: `views_bed` (default
`Bambu Lab X1/P1/A1`) from `views_beds` (default `Bambu Lab A1 mini 180x180x180; Bambu Lab
X1/P1/A1 256x256x256; Prusa MK4 250x210x220; Prusa Core One 250x220x270`); `views_bedfit`
(on) shows it. Views that can't apply (one component, no studies, a scene over the
renderer's budget) are skipped and the sheet's **Views** section says why.

Parts are always rendered in **cool grey** or **white** (a setting), never in a design's own
colours: every body is repainted before rendering, and a colour guard greys out any pixel
that still carries colour (per-face paint, imported STEP colours).

In Kist, each set lands in `SolidCraft/<owner>/<repo>/<design>`, tagged `solidcraft`,
`repo:<owner>/<repo>`, `design:<name>`, `style:<shaded|wireframe>`, `format:<variant>` and
`palette:<name>` and `rev:<commit10>` (the commit that made that version of the file), with
the file's URL at the rendered commit as its source. A new version never trashes the
previous one's items: each new item is linked `version_of` the item it follows and stacked
with it as the cover, so Kist's versions list and compare work on the chain and links to
older items keep working (see **Revisions**). Renders of a pull request or another branch
or tag file into their own subfolder, `<design>/pr-<n>` or `<design>/@<branch>`, tagged
`ref:pr-<n>` or `ref:<branch>`.

## Revisions

Every rendered version of a design keeps its own render set (one per blob: a commit that
didn't change the file has nothing new to render), labelled with the commit that made it
(message, author, date, from the forge) and any git tags whose tree holds it. Re-rendering
the same version (Re-render, `force`) replaces only that version's set, and only once the new
one has finished: a cancelled or failed re-render leaves the old set in place.

- **Keep policy:** every tagged version stays; of the untagged ones, the newest
  `revisions_keep` (default 10; `0` keeps all) stay on disk and older ones are pruned. Pruning
  never touches Kist unless `revisions_prune_kist` is on (default off), which trashes the
  pruned versions' items (restorable from Kist's trash).
- **Compare** (a sheet in the drawing sheet, under Revisions): two versions as a slider, side
  by side, or **Changes**: the pixels that differ, drawn in the sheet's ink over a faded copy
  of the newer one (numpy, from the matching stills; never a hue). It works on any still, or
  on the same frame of any turntable. Each version's stills are framed to its own envelope,
  so when the envelope changed the compare says part of the difference is framing. Below it,
  the commits that changed the file in between, from the forge API.
- **Filmstrip:** one still per kept version along a hairline timeline, with mono commit and
  date and any tags; choosing one compares it with the current version.
- Tiles show `N rev` when more than one version is kept.

### Build-history timelapse

With `revisions_timelapse` on (default off), each render also makes
`<design>-timelapse-1080p.mp4` and `<design>-timelapse.gif`: the part building itself feature
by feature (`timeline.rollback` through the history, one still per step from a fixed iso
camera, then a hold on the finished part). Nothing is drawn on the frames. Every step is a
rebuild, so designs over `revisions_timelapse_max_bodies` (100) bodies or
`revisions_timelapse_max_features` (200) features are skipped, with the reason in the set's
`report.json` (`timelapse.skipped`).

## How it works

- **Discovery** uses the forges' git-tree APIs; nothing is cloned. `.sc` and `.solidcraft`
  files (plus `.step`/`.stp`, `.stl` and `.3mf`, see [Inputs](#inputs-and-access)) are found
  with their blob SHAs, so a re-scan renders only what changed. Folders named `tests`,
  `test`, `fixtures` and `corpus` are skipped by default (per-source `exclude`).
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
- `https://github.com/<owner>/<repo>/blob/<branch>/<path>.sc`: one design (or `.step`, `.stl`, `.3mf`)
- `…/pull/<n>` (GitHub) or `…/pulls/<n>` (Forgejo): the designs a pull request changes
- `…/tree/<tag>`, `…/releases/tag/<tag>`, `…/commit/<sha>`: a tag or commit
- `https://github.com/<org>?prefix=<repo prefix>`: a class set (see below)
- the same shapes on Forgejo (`…/src/branch/<branch>/<path>`), and SSH clone URLs

Hovering a tile plays its turntable; clicking it opens the design as a drawing sheet: the
file at its true pixel size, a numbered schedule of every file with downloads, and a title
block (source and commit, revision, date, palette, envelope in mm, bodies). The UI uses
Kist 2.0's design system (gallery grey by default; dark and light under **Appearance**)
and works on a phone (the menu opens filters, sources and jobs). See `docs/design.md`.

A design that is only on disk can be rendered without the app:

```bash
docker compose run --rm app sklent render /data/some.sc /data/out --palette white
docker compose run --rm app sklent render /data/robot.step /data/out \
  --settings '{"styles": ["shaded"], "specs_assembly": true}'   # any render or feature setting
docker compose run --rm app sklent render /data/arm.sc /data/out --outputs 1080p,gif --highlight 'Arm*'
```

`sklent render` applies the `.sklent.yaml` files in the folders above the design (up to the
git root; `--config PATH` names one, `--config none` skips them), then `--palette` /
`--seconds`, then `--settings`, `--outputs` (`''` = quick check only) and `--highlight`.

### Configuration

Server settings go in `.env`:

| variable | default | |
|---|---|---|
| `SK_TOKEN` | | **Required.** Admin token for the UI, API and MCP (16+ chars) |
| `SK_PORT` | `8090` | Host port |
| `SK_DATA` | `./data` | Database and local render sets |
| `SK_KIST_URL`, `SK_KIST_TOKEN` | | Kist to file sets into; empty URL keeps renders local |
| `SK_KIST_ROOT_FOLDER` | `SolidCraft` | Top-level Kist folder |
| `SK_GITHUB_TOKEN` | | Private repos, and a higher API rate limit (without one GitHub allows 60 API calls an hour, a handful of designs' first renders) |
| `SK_FORGEJO_URL`, `SK_FORGEJO_TOKEN` | | Your Forgejo; the token is only sent to that host |
| `SK_SCAN_INTERVAL_MINUTES` | `360` | Periodic re-scan; `0` turns it off |
| `SK_RENDER_PROCESSES` | `4` | Most SolidCraft processes per design (see below) |
| `SK_RENDER_GID` | `992` | Group owning `/dev/dri/renderD128` on the host |
| `SK_RENDERER` | `gpu` | Where this server renders: `gpu`, `software` (Mesa lavapipe) or `off` (helpers only); Settings → Rendering overrides it |
| `TZ` | `UTC` | The time zone of quiet hours |
| `SK_HOST_NAME` | the host name (`server` in a container) | This machine's name in `report.json` and the title block |
| `SK_SOLIDCRAFT_CLI`, `SK_FFMPEG` | `solidcraft-cli`, `ffmpeg` | The programs, for a native helper (full paths on a Mac) |
| `SK_LVP_ICD` | found under `/usr/share/vulkan/icd.d` | Mesa lavapipe's Vulkan ICD, for software rendering |

Render and feature settings live in the app: the UI's **Settings**, `GET/PUT
/api/settings`, MCP `set_render_settings` / `set_views_settings`, and per repo in
`.sklent.yaml` (`settings:`). Every key, with its default:

| setting | default | |
|---|---|---|
| `palette` | `cool-grey` | `cool-grey` or `white`; parts are never rendered in their own colours |
| `seconds`, `fps`, `pitch_deg` | `8`, `30`, `24` | Turntable length, frame rate, camera pitch |
| `hires_width` × `hires_height`, `social_size`, `gif_width`, `gif_fps` | `3840×2160`, `2048`, `640`, `15` | Still and GIF sizes |
| `styles` | `shaded, wireframe` | Which looks to render |
| `outputs` | all six | Which of `1080p`, `reel`, `discord`, `gif`, `social`, `hires`; none = quick check only |
| `inputs_step`, `inputs_mesh` | on, on | Scans find `.step`/`.stp`, and `.stl`/`.3mf` (exports next to a `.sc` skipped) |
| `inputs_review_post` | off | Allow **Post** of a review comment to the pull request (only ever on a click) |
| `inputs_public_url` | `""` | This server's URL for links in review comments (empty: the address the page uses) |
| `revisions_keep` | `10` | Untagged versions kept on disk besides every tagged one; `0` keeps all |
| `revisions_prune_kist` | off | Also trash pruned versions' Kist items (off keeps every Kist link working) |
| `revisions_timelapse` | off | Build-history timelapse MP4 and GIF |
| `revisions_timelapse_max_features`, `_max_bodies` | `200`, `100` | Skip the timelapse above these |
| `views_shot_half_orbit`, `_push_in`, `_top_to_iso`, `_low_angle` | off | Shot presets; `views_shot_seconds` (6) |
| `views_master_4k`, `views_master_prores`, `views_master_zip` | off | Edit-ready masters; `views_master_seconds` (0 = the turntable's length) |
| `views_exploded` | off | Exploded still and animation; `views_explode_scale` (1) |
| `views_section` | off | Section cut through the centre |
| `views_configs` | on | Configuration stills and lineup (designs with 2+ rows); `views_configs_max` (8) |
| `views_motion` | on | Motion-study clips (designs with studies); `views_motion_max` (6) |
| `views_transparent` | off | RGBA stills |
| `views_hero` | off | Path-traced studio still; `views_hero_timeout` (900 s) |
| `views_plate` | off | Plate view on a 10 mm grid |
| `views_bedfit`, `views_bed`, `views_beds` | on, `Bambu Lab X1/P1/A1`, four printers | Bed-fit badge and the bed list |
| `specs_card` | on | Spec card still (`spec.json` is written regardless) |
| `specs_material` | `""` | Material for mass when `.sklent.yaml` names none |
| `specs_bom`, `specs_bom_file` | on, `bom.yaml` | Parts list (CSV, JSON, sheet) and the repo's BOM file |
| `specs_views` | on | Views sheet PNG + PDF |
| `specs_dimensions` | on | Dimension still |
| `specs_assembly`, `specs_assembly_max_steps` | off, `20` | Assembly step images |
| `outputs_presets` | seven presets | Output presets (see [Outputs](#outputs-and-publishing)) |
| `outputs_filepack` | off | Export STEP/3MF/STL during renders |
| `outputs_filepack_formats`, `_body_budget`, `_max_parts`, `_per_body`, `_quality`, `_exclude` | `step, 3mf, stl`, `64`, `2000`, on, `standard`, none | File pack details |
| `outputs_marketplaces` | all five | Marketplaces checked and packed |
| `outputs_licence` | `""` | Licence when neither the design nor the repo sets one |
| `outputs_brand_text`, `_mark`, `_position`, `_opacity`, `_size`, `_photos` | none, off, `bottom-right`, `0.6`, `12` %, on | Watermark on exported copies only |
| `outputs_brand_title_card`, `_end_card`, `_card_text`, `_card_seconds` | off, off, none, `1.5` | Cards on exported clips |
| `outputs_review_share_links` | off | Allow Kist share links (public pages, made only on a click) |
| `outputs_review_proofing`, `_share_days`, `_allow_download` | on, `30`, off | Share link details |
| `render_device` | `SK_RENDERER` (`gpu`) | `gpu`, `software` or `off` (helpers only) |
| `render_gpu_processes` | `1` | Most SolidCraft processes on the GPU at once (software mode: `SK_RENDER_PROCESSES`) |
| `render_quiet_hours`, `render_quiet_mode` | none, `wait` | e.g. `22:00-07:00` (server time, `TZ`); `wait` leaves renders to helpers, `software` renders on the CPU |
| `helpers_fallback_minutes` | `30` | With a helper around, this server takes a render only once it has waited this long; `0` never |
| `helpers_seen_window` | `10` min | A helper counts as around if it asked for work this recently |
| `helpers_require_same_solidcraft` | on | Refuse (409) a helper whose SolidCraft differs from this server's |
| `helpers_max_attempts`, `helpers_lease_seconds` | `2`, `300` | Claims of one job before it fails; a helper's lease, renewed by its progress |

The `render_*` and `helpers_*` settings are server-side only: `.sklent.yaml` can't change them.

## Render helpers

A render helper is another machine with SolidCraft that renders for this server. It asks for
work, downloads the design (and its linked files) from this server, renders the set with this
server's settings and every feature step, and uploads it; this server then files it into Kist,
links the versions and keeps the revision history, exactly as for its own renders. Scans stay
here. A helper needs no database, no data folder and no forge token.

**Its token.** Settings → **Helpers** → *Create helper token* (or `sklent token create NAME
--scope helper`) makes a token that starts with `skh`. It may call only the helper protocol
(`/api/helpers/claim` and `/api/helpers/jobs/...`): every other route and all of MCP answer
403. The panel shows the `.env.helper` lines once; revoke the token in Settings → Tokens.

**Another Linux box** (Intel or AMD GPU through Mesa, or software):

```bash
git clone <this repo> sklent && cd sklent
cp .env.example.helper .env.helper    # paste the lines from Settings -> Helpers
docker compose --env-file .env.helper -f docker-compose.helper.yml up -d
docker compose -f docker-compose.helper.yml logs -f   # "asking ... for work"
```

The helper must run the same SolidCraft version as the server (the image pins it), or its
claims are refused with 409 and the reason (`helpers_require_same_solidcraft`). Stopping it
(`docker compose -f docker-compose.helper.yml stop`, Ctrl-C) reports the job it had as
"helper stopped", and the server queues it again. A helper that vanishes loses its job when
its lease runs out (`helpers_lease_seconds`, 300 s, renewed by every progress report); a
job is claimed at most `helpers_max_attempts` (2) times, then fails.

**Natively** (e.g. a Mac with SolidCraft's app): `pip install` this repo, then

```bash
SK_SOLIDCRAFT_CLI=/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli \
SK_FFMPEG=/opt/homebrew/bin/ffmpeg \
sklent helper --url http://sklent-host:8090 --token-file ~/.config/sklent-helper.token --name mac
```

Options: `--renderer gpu|software`, `--processes N` (frames of one design in parallel),
`--max-bodies N` (leave bigger designs to others), `--once` (one job, then exit). Env
equivalents: `SK_HELPER_URL`, `SK_HELPER_TOKEN`, `SK_HELPER_NAME`, `SK_RENDERER`,
`SK_RENDER_PROCESSES`.

**This server's GPU** (Settings → **Rendering**):

- *Renderer*: `GPU`; `Software (CPU)`, which runs SolidCraft on Mesa lavapipe (slower, the
  same pictures, no GPU load: other GPU work on the machine is left alone); or `Off`, where
  this server never renders and jobs wait for helpers.
- *GPU processes*: the most SolidCraft processes on the GPU at once (default 1). Big designs
  used to fan out to `SK_RENDER_PROCESSES`; that cap still applies in software mode.
- *Quiet hours* (`22:00-07:00`, this server's local time, `TZ`): during them, *Wait* takes no
  render here (the sidebar says "Quiet hours: helpers only"), *Render in software* switches
  to the CPU.
- *Helper fallback*: with no helper seen in the last 10 minutes this server renders at once.
  With one around, it takes a render only once the job is `helpers_fallback_minutes` old
  (30; 0 = never), outside quiet hours (or in software mode) and when the renderer isn't off.
  Scans never wait behind a render held for a helper.

Settings → **Helpers** lists every helper with its last contact, SolidCraft version,
renderer, current job and done count; the job log says "on <helper>", and the title block
says where each set was rendered.

## Inputs and access

### STEP, STL and 3MF

STEP files open as B-rep bodies (an assembly's parts become components); STL and 3MF open as
mesh bodies (no volume; the x-ray style shows the mesh's edges). Everything else (framing,
the grey repaint, the colour guard, every output) is the same. A mesh with the same name as a
SolidCraft design in its folder (`case.sc` and `case.stl`) is taken as its export and skipped;
pointing a source at the file itself renders it anyway. Git LFS files are fetched through the
forge's media endpoint. Tiles carry a `STEP`, `STL` or `3MF` chip; `report.json` gets
`inputs.format`. OpenSCAD (`.scad`) is planned for later.

### Linked designs (multi-file assemblies)

A SolidCraft assembly that links parts saved in other files (`component.insert_design`)
renders whole: before a render, Sklent fetches the design and every file it links (and what
those link; up to 64 files) at the same commit into the repo's own layout, and once
SolidCraft has opened it, updates the links that changed since the design was saved
(`component.update_links`). A linked file that can't be fetched keeps the copy saved in the
assembly, with a note. Editing a linked part re-renders every assembly that uses it: an
assembly's revision is a hash of its own blob and its linked files' blobs. The tile shows
`ASM n`; the sheet's **Inputs** section lists the files.

### `.sklent.yaml`

A repo can carry `.sklent.yaml` (or `.sklent.yml`) at its root or in any folder; every one
above a design applies, the nearest last. It is read with `yaml.safe_load` at the scanned
commit; a wrong key is dropped and reported on the scan job and in the sheet, never fatal.

```yaml
name: Sensor mount family
licence: CERN-OHL-S-2.0
include: ["parts/**", "assemblies/*.sc"]   # globs from this file's folder; /x anchors here
exclude: ["parts/old/**"]
formats: [sc, step]                       # sc, step, stl, 3mf (or mesh)
presets: [printables, youtube-thumbnail]
bom: bom.yaml
material: PETG
highlight: [Lid]
up: y                                     # STEP files exported with Y up
settings: {palette: white, seconds: 6, styles: [shaded], views_exploded: true}
steps:
  - {title: Base, parts: [Base]}
designs:
  parts/case.sc: {title: Pi case, highlight: [Lid]}
  "old/*.stl": {exclude: true}
```

`settings` may override only `palette` (still one of the greys), `seconds`, `styles` and
boolean feature settings. Other features read a design's merged config with
`sklent.repo_config.get(design_id)`; the API shows it as `design.config`.

### Branches, tags and pull requests

A source can name a ref; its designs are kept apart from the default branch's (a design is
keyed by source + ref), and tiles show the ref (`PR #12`, `dev`, `v1.2`). A pull request
source renders only the designs the PR adds or changes, plus assemblies that link a changed
file, at the PR's head. The sheet's **Review comment** section builds Markdown for the PR
thread: each design's still, before (from the base branch, when Sklent has it) and after,
with its envelope and body count and a link to the turntable GIF. The image links point at
this server's file URLs (readers need its token) or, with Kist on, at a Kist share link.

**Nothing is posted** unless `inputs_review_post` is on and someone presses **Post** (or calls
`post_review_comment`); then it is one comment through the forge's API with the server's
token, which needs: GitHub fine-grained `Pull requests: write` (classic: `public_repo` or
`repo`), Forgejo `write:issue`. Without that, scanning needs only read access.

### Class sets and due dates

A class set is an account or organisation plus a repo-name prefix, the way GitHub Classroom
names an assignment's repos (`bracket-hw-<username>`). Add one from the sidebar's **Class
sets** (or `POST /api/classes`, MCP `add_class_source`) with an optional deadline and roster:

- **Deadline** (ISO 8601): each repo renders its newest commit at or before it (committer
  date). A later push shows `after due` on the tile and doesn't re-render.
- **Roster**: usernames, `username, Display name`, or repo-name patterns with `*`. The
  sidebar shows `n/m submitted` and, opened, every student as handed in, `no design`,
  `nothing by due` or `no repo`.

Any source can carry a deadline (`PUT /api/sources/{id}/class`).

### Viewer tokens

Settings → **Tokens** makes a named, read-only viewer token (shown once; stored as a SHA-256
hash), lists them and revokes them; `sklent token create|list|revoke` does the same on the
host. A viewer can browse, view and download, through the UI, every `GET` under `/api`, and
the MCP tools that only read. Rendering, adding or removing sources, changing settings,
managing tokens and every MCP tool that changes something answer 403, and the UI hides
those controls. The token gate takes either kind of token.

## Specs and sheets

Besides the turntables, each render makes drafting sheets from the same open design (render
steps; every one can be switched off in **Settings → Specs and sheets**). Parts stay grey or
white, and dimension lines only ever appear on orthographic views, where they are true.

| file (variant) | default | what it is |
|---|---|---|
| `spec.json` (sidecar) | always | envelope, volume, mass (only when a material is known), bodies, components, user parameters, commit, blob, licence |
| `<design>-spec-card.png` (`spec-card`) | on | 2048×1152 card: the part, the spec list and a title block |
| `<design>-bom.csv` (`bom-csv`), `bom.json`, `<design>-bom-sheet.png` (`bom-sheet`) | on, for assemblies or with a `bom.yaml` | SolidCraft's `assembly.bom` merged with the repo's `bom.yaml` (bought parts: name, qty, supplier, url, price) |
| `<design>-views-sheet.png` / `.pdf` (`views-sheet`, `views-sheet-pdf`) | on | A3 sheet: front, top and right views in third-angle projection at one ISO scale, plus an iso view and a title block. Visible edges only (no hidden lines until SolidCraft's drawings) |
| `<design>-dimensions-2048.png` (`dimensions`) | on | the front view with overall width and height as ISO 129 dimension lines, depth noted |
| `<design>-assembly-NN.png` (`assembly-N`), `<design>-assembly.md` (`assembly-md`) | off | assemblies: one picture per step (new parts in the darker grey, earlier ones lighter) and a GitBuilding BuildUp page |

All of them land in Kist with the rest of the set (`format:<variant>`), and show in the
drawing sheet's schedule; the sheet also gets **Spec** and **Parts** sections and a
Licence cell. A **contact sheet** of every rendered design in a source (3840×2160 PNG
pages and a PDF, hero stills with mono labels) is made on demand from the grid button on
the source's row, or `POST /api/sources/{id}/contact-sheet`; with Kist on it is filed once
per version of the sheet, tagged `format:contact-sheet`.

Settings: `specs_*` in the [Configuration](#configuration) table.

`bom.yaml`:

```yaml
currency: EUR               # optional
parts:                      # or a bare list
  - name: M3x8 socket head cap screw
    qty: 8
    supplier: Example Fasteners
    url: https://example.com/m3x8
    price: 0.12             # each
  - match: Arm              # enrich a model part (by name or part number) instead of adding one
    notes: print in PETG
```

From `.sklent.yaml` (when the repo has one) the sheets also read `title`, `licence`,
`material`, `bom` and `assembly.steps` (`[{name, components: [...]}]`). Mass appears only
for a material set there, in the setting, or in the design itself; SolidCraft's placeholder
"Default" material doesn't count.

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

Settings: `outputs_*` in the [Configuration](#configuration) table; there are no new
environment variables.

## MCP

A streamable-HTTP MCP endpoint at `/mcp`, with the same bearer token:

```bash
claude mcp add --transport http sklent http://<host>:8090/mcp \
  --header "Authorization: Bearer $SK_TOKEN"
```

Tools marked **R** only read; a viewer token may call those and nothing else.

| tool | | |
|---|---|---|
| `render_url` | Scan a URL now and queue renders; returns job ids | |
| `wait_for_job`, `job_status`, `list_jobs` | Follow progress | R |
| `cancel_job` | Drop a queued job, or stop a running render (its SolidCraft processes are killed) | |
| `get_render_set` | Files, sizes, download paths, Kist folder and item ids | R |
| `view_render` | See a still (image content) | R |
| `list_sources`, `list_designs` | What's there | R |
| `add_source`, `scan_source`, `render_design` | Finer control | |
| `get_render_settings` / `set_render_settings` | Palette, length, sizes | R / |
| `list_sets` | Every kept version of a design: commit, message, tags, files | R |
| `compare_sets` | Pixel compare of two versions (changed share, bounding box, mask and composite URLs) plus the commits in between | R |
| `view_compare` | See a compare as one picture: older, newer, changes | R |
| `add_class_source` / `list_class_submissions` | Class sets: add one; who handed in what by the deadline | / R |
| `review_comment` / `post_review_comment` | Review Markdown for a source's renders; posting only when `inputs_review_post` is on | R / |
| `get_design_inputs` | A design's format, linked files, `.sklent.yaml` config and ref | R |
| `quick_check` | Queue a quick-check still (kept beside the current set) | |
| `render_outputs` | Queue a render with chosen outputs and views (`{"views_exploded": true}`, …) for that render only | |
| `get_views` | Quick-check URL, bed fit, configurations, studies, highlight, why views were skipped | R |
| `set_highlight` | A design's "my part" bodies (names or globs) | |
| `view_output` | See any still of a set by variant (`exploded`, `section`, `plate`, …) | R |
| `set_views_settings` | `outputs` and `views_*` settings | |
| `get_design_spec`, `get_bom` | A design's `spec.json` and parts list | R |
| `view_sheet` | See a spec card, parts sheet, views sheet, dimension still or assembly step | R |
| `make_contact_sheet` | Every rendered design of a source on one sheet (PNG pages + PDF) | |
| `get_outputs` | A design's presets, print files, photos, listing details, readiness and Kist board | R |
| `make_output_preset` | Make one preset or all enabled ones | |
| `build_file_pack` | The print pack zip (README, licence, manifest), optionally split (`split_mb`) | |
| `export_project_page` | Offline HTML page for a design or a source (zip) | |
| `build_listing_pack` / `listing_readiness`, `listing_text` | Marketplace packs / the checklist and listing text | / R |
| `set_listing_details` | Title, summary, licence, print notes, tags | |
| `attach_photo` / `list_photos` | Real print photos (base64 in) | / R |
| `make_review_board`, `create_share_link`, `revoke_share_link` | Kist board; public share link only when the setting allows and the user asks | |
| `list_helpers` | Render helpers (last seen, version, renderer, current job, done count) and what this server does with renders now | R (admin token) |

With Kist's own MCP connected as well, an agent can go on to browse, view and tag the
filed sets there.

## API

Core: `/api/sources`, `/api/designs`, `/api/designs/{id}/render`, `/api/designs/{id}/files/{name}`,
`/api/render-url`, `/api/jobs`, `POST /api/jobs/{id}/cancel`, `/api/settings`, `/api/status`
(`sklent/api.py`). Viewer tokens get every `GET` (except `/api/tokens` and `/api/helpers`) and
nothing else; helper tokens only the helper protocol.

- **Inputs** (`sklent/features/inputs/`): `GET /api/whoami`, `GET /api/designs/{id}/inputs`,
  `GET|POST /api/sources/{id}/review-comment`, `GET|POST /api/classes`,
  `GET|PUT /api/sources/{id}/class`, `GET|POST /api/tokens`, `DELETE /api/tokens/{id}`.
- **Revisions**: `GET /api/designs/{id}/sets` (newest first), `/sets/{set}`,
  `/sets/{set}/files/{name}`, `/compare?a=&b=&style=&variant=&frame=` (a older, b newer;
  defaults: the current version against the one before), `/compare/diff.png`,
  `/compare/frame.png?set=&variant=&frame=`, `/compare/composite.png`, `/changelog?base=&head=`.
- **Views**: `GET /api/designs/{id}/views`, `GET /api/designs/{id}/views/preview` (the
  quick-check still, also while rendering), `POST /api/designs/{id}/views/render`
  (`{outputs?, preview_only?, settings?}`), `GET|PUT /api/designs/{id}/views/highlight`
  (`{names}`), `GET /api/views/beds`.
- **Specs**: `/api/designs/{id}/spec`, `/bom`, `/assembly`, `POST /api/sources/{id}/contact-sheet`,
  `/api/sources/{id}/contact-sheet.png?page=N` / `.pdf`.
- **Outputs** (`sklent/features/outputs`): `/api/designs/{id}/outputs` (summary),
  `…/outputs/meta`, `…/outputs/presets[/{name}[/file]]`, `…/outputs/presets.zip`,
  `…/outputs/filepack`, `…/outputs/exports/{file}`, `…/outputs/page[.zip]`,
  `…/outputs/listing[/{market}[/text]]`, `…/outputs/photos[/{photo}[/file]]`,
  `…/outputs/review[/board|/share]`, the same `page` and `review` routes under
  `/api/sources/{id}/outputs/`, and `/api/outputs/{brand,brand/mark,brand/preview,readiness,marketplaces,presets/defaults}`.
- **Helpers** (`sklent/features/helpers`, 0.2.1): `GET /api/helpers` (admin), `GET
  /api/render-state` (device, quiet hours, why renders wait). The helper protocol, for helper
  tokens (and the admin token): `POST /api/helpers/claim` `{name, solidcraft_version, renderer,
  gpu, mem_gb, max_bodies?}` (204 nothing to do, 409 a different SolidCraft, else `{job,
  design, settings_snapshot, design_file, stem, lease_s}`), then under
  `/api/helpers/jobs/{id}/` with `?name=`: `GET inputs.tar`, `GET repo-file?path=`, `POST
  progress` `{fraction, message}` → `{cancel}`, `POST result` (a tar of the set whose first
  member is `.sklent-manifest.json` `{outputs, files: {name: size}}`), `POST fail` `{error,
  retry?}`.

Each design in `/api/designs` carries:

- `blob` (its file's git blob SHA, the sheet's revision) and `report`: `{bodies,
  hidden_bodies, bounds_mm, palette, frame_ms, processes, timings_s, renderer, adapter, host}`
  from its newest set's
  `report.json` (`bounds_mm` is `[[x, y, z] min, [x, y, z] max]`), or `null` before the first
  render;
- `revisions`: `{count, tagged, tags}` (kept versions, how many are tagged, the current
  version's tags);
- `format` (`sc`, `step`, `stl`, `3mf`), `inputs` (`{links, notes}` for an assembly),
  `config` (the merged `.sklent.yaml`), `ref_info` (`{kind: pull|ref, label, …}` off the
  default branch) and `due` (`{deadline, committed_at, after_due}` for a deadline source);
- `views`: `{preview_url, bed_fit}` (`bed_fit`: `{bed, label, fits, largest: {name, size},
  parts, too_big, fits_beds}` or `null`);
- `spec`: the newest set's `spec.json`, or `null`.

## Limits

- OpenSCAD files aren't rendered yet.
- Mesh inputs (STL, 3MF) have no volume, so mass and section caps don't apply to them.
- SolidCraft's headless renderer ignores `view.visual_style`, so the wireframe style is an
  x-ray: see-through bodies with every edge (see `docs/spike.md`).
- The views sheet draws visible edges only: hidden lines wait for SolidCraft 0.45's
  `drawing.*` commands (the sheet switches over when it finds them).
- Transparent output is stills only; there is no transparent video yet.

MIT licensed.
