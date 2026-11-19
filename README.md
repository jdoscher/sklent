# sklent

Point it at a GitHub or Forgejo account, repo, folder, file, branch, tag or pull request, and
it renders every [SolidCraft](https://github.com/tangency-labs/solidcraft) design (and every
STEP, STL and 3MF file) it finds into a media set, then files the set into a
[Kist](https://github.com/jdoscher/kist) folder.

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
  --settings '{"styles": ["shaded"]}'          # any render or feature setting, as JSON
```

`sklent render` applies the `.sklent.yaml` files in the folders above the design (up to the
git root; `--config PATH` names one, `--config none` skips them), then `--palette` /
`--seconds`, then `--settings`.
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
| `inputs_step` | `true` | Scans find `.step`/`.stp` files |
| `inputs_mesh` | `true` | Scans find `.stl`/`.3mf` files (exports next to a `.sc` design are skipped) |
| `inputs_review_post` | `false` | Allow **Post** of a review comment to the pull request (only ever on a click) |
| `inputs_public_url` | `""` | This server's URL for links in review comments (empty: the address the page uses) |

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
those controls.
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
| `list_sets` | Every kept version of a design: commit, message, tags, files |
| `compare_sets` | Pixel compare of two versions (changed share, bounding box, mask and composite URLs) plus the commits in between |
| `view_compare` | See a compare as one picture: older, newer, changes (image content) |
| `add_class_source`, `list_class_submissions` | Class sets: add one; who handed in what by the deadline |
| `review_comment`, `post_review_comment` | Review Markdown for a source's renders; posting only when `inputs_review_post` is on |
| `get_design_inputs` | A design's format, linked files, `.sklent.yaml` config and ref |

A viewer token may call only the tools that read (`list_*`, `get_*`, `job_status`,
`wait_for_job`, `view_render`, `review_comment`, …).
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
see `sklent/api.py`. Inputs and access add `GET /api/whoami`, `GET /api/designs/{id}/inputs`,
`GET|POST /api/sources/{id}/review-comment`, `GET|POST /api/classes`,
`GET|PUT /api/sources/{id}/class`, and `GET|POST /api/tokens`, `DELETE /api/tokens/{id}`
(see `sklent/features/inputs/`).
see `sklent/api.py`. Views: `GET /api/designs/{id}/views`, `GET /api/designs/{id}/views/preview`
(the quick-check still, also while rendering), `POST /api/designs/{id}/views/render`
(`{outputs?, preview_only?, settings?}`: this render's choice), `GET|PUT
/api/designs/{id}/views/highlight` (`{names}`), `GET /api/views/beds`.

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
one that set was rendered with), or `null` before the first render. They also carry `format`
(`sc`, `step`, `stl`, `3mf`), `inputs` (`{links, notes}` for an assembly, else `null`),
`config` (the merged `.sklent.yaml`, or `null`), `ref_info` (`{kind: pull|ref, label, …}` off
the default branch) and `due` (`{deadline, committed_at, after_due}` for a deadline source).
one that set was rendered with), or `null` before the first render. `views` holds
`{preview_url, bed_fit}` (`bed_fit`: `{bed, label, fits, largest: {name, size}, parts,
too_big, fits_beds}` or `null`).

`sklent render` takes `--outputs 1080p,gif` (`--outputs ''` for a quick check),
`--settings '{"views_exploded": true}'` and `--highlight 'Arm*,Gripper'`.

## Limits

- OpenSCAD files aren't rendered yet.
- Mesh inputs (STL, 3MF) have no volume, so mass and section caps don't apply to them.
- SolidCraft's headless renderer ignores `view.visual_style`, so the wireframe style is an
  x-ray: see-through bodies with every edge (see `docs/spike.md`).

MIT licensed.
