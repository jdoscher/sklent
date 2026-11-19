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
`palette:<name>` and `rev:<commit10>` (the commit that made that version of the file), with
the file's URL at the rendered commit as its source. A new version never trashes the
previous one's items: each new item is linked `version_of` the item it follows and stacked
with it as the cover, so Kist's versions list and compare work on the chain and links to
older items keep working (see **Revisions**).

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

`--settings '{"revisions_timelapse": true}'` passes feature settings to that render.

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
are in the UI's **Settings** and the MCP `set_render_settings` tool. Feature settings are in
the same Settings sheet and `GET/PUT /api/settings`:

| setting | default | |
|---|---|---|
| `revisions_keep` | `10` | Untagged versions kept on disk besides every tagged one; `0` keeps all |
| `revisions_prune_kist` | off | Also trash pruned versions' Kist items (off keeps every Kist link working) |
| `revisions_timelapse` | off | Build-history timelapse MP4 and GIF |
| `revisions_timelapse_max_features` | `200` | Skip the timelapse above this many features |
| `revisions_timelapse_max_bodies` | `100` | Skip the timelapse above this many bodies |

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
| `list_sets` | Every kept version of a design: commit, message, tags, files |
| `compare_sets` | Pixel compare of two versions (changed share, bounding box, mask and composite URLs) plus the commits in between |
| `view_compare` | See a compare as one picture: older, newer, changes (image content) |

With Kist's own MCP connected as well, an agent can go on to browse, view and tag the
filed sets there.

## API

`/api/sources`, `/api/designs`, `/api/designs/{id}/render`, `/api/designs/{id}/files/{name}`,
`/api/render-url`, `/api/jobs`, `POST /api/jobs/{id}/cancel`, `/api/settings`, `/api/status`;
see `sklent/api.py`.

Each design carries `blob` (its file's git blob SHA, the sheet's revision) and `report`:
`{bodies, hidden_bodies, bounds_mm, palette, frame_ms, processes, timings_s}` from its newest
render set's `report.json` (`bounds_mm` is `[[x, y, z] min, [x, y, z] max]`; `palette` is the
one that set was rendered with), or `null` before the first render, and `revisions`:
`{count, tagged, tags}` (kept versions, how many are tagged, the current version's tags).

Revisions: `GET /api/designs/{id}/sets` (newest first), `/sets/{set}`,
`/sets/{set}/files/{name}`, `/compare?a=&b=&style=&variant=&frame=` (a older, b newer;
defaults: the current version against the one before), `/compare/diff.png` (alpha mask of the
changed pixels), `/compare/frame.png?set=&variant=&frame=`, `/compare/composite.png`, and
`/changelog?base=&head=`.

## Limits

- Designs are fetched as single files. A design that links parts from other files in its
  repo isn't supported yet.
- SolidCraft's headless renderer ignores `view.visual_style`, so the wireframe style is an
  x-ray: see-through bodies with every edge (see `docs/spike.md`).

MIT licensed.
