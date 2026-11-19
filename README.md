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

Every render starts with a **quick check**: one shaded iso still (`<design>-preview.png`,
1024×1024) made seconds after the design loads and shown on its tile while the rest
renders. Which of the six files above a render makes is a setting (**Outputs**) and can be
chosen per render on the design's sheet; none at all is a quick check on its own.

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

Render settings (palette, length, frame rate, camera pitch, still and GIF sizes, styles,
outputs, and the `views_*` settings above) are in the UI's **Settings** and the MCP
`set_render_settings` / `set_views_settings` tools.

| render setting | default | |
|---|---|---|
| `outputs` | all six | which of `1080p`, `reel`, `discord`, `gif`, `social`, `hires` to make; `[]` = quick check only |
| `views_*` | see **Views and render modes** | shot presets, masters, extra views, beds |

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
| `quick_check` | Queue a render of just the quick-check still |
| `render_outputs` | Queue a render with chosen outputs and views (`{"views_exploded": true}`, …) for that render only |
| `get_views` | Quick-check URL, bed fit, configurations, studies, highlight, why views were skipped |
| `set_highlight` | A design's "my part" bodies (names or globs) |
| `view_output` | See any still of a set by variant (`exploded`, `section`, `plate`, …), or the quick check while rendering |
| `set_views_settings` | `outputs` and `views_*` settings |

With Kist's own MCP connected as well, an agent can go on to browse, view and tag the
filed sets there.

## API

`/api/sources`, `/api/designs`, `/api/designs/{id}/render`, `/api/designs/{id}/files/{name}`,
`/api/render-url`, `/api/jobs`, `POST /api/jobs/{id}/cancel`, `/api/settings`, `/api/status`;
see `sklent/api.py`. Views: `GET /api/designs/{id}/views`, `GET /api/designs/{id}/views/preview`
(the quick-check still, also while rendering), `POST /api/designs/{id}/views/render`
(`{outputs?, preview_only?, settings?}`: this render's choice), `GET|PUT
/api/designs/{id}/views/highlight` (`{names}`), `GET /api/views/beds`.

Each design carries `blob` (its file's git blob SHA, the sheet's revision) and `report`:
`{bodies, hidden_bodies, bounds_mm, palette, frame_ms, processes, timings_s}` from its newest
render set's `report.json` (`bounds_mm` is `[[x, y, z] min, [x, y, z] max]`; `palette` is the
one that set was rendered with), or `null` before the first render. `views` holds
`{preview_url, bed_fit}` (`bed_fit`: `{bed, label, fits, largest: {name, size}, parts,
too_big, fits_beds}` or `null`).

`sklent render` takes `--outputs 1080p,gif` (`--outputs ''` for a quick check),
`--settings '{"views_exploded": true}'` and `--highlight 'Arm*,Gripper'`.

## Limits

- Designs are fetched as single files. A design that links parts from other files in its
  repo isn't supported yet.
- SolidCraft's headless renderer ignores `view.visual_style`, so the wireframe style is an
  x-ray: see-through bodies with every edge (see `docs/spike.md`).

MIT licensed.
