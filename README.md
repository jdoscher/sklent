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
# feature settings as JSON, e.g. assembly steps on:
docker compose run --rm app sklent render /data/some.sc /data/out --settings '{"specs_assembly": true}'
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

| setting | default | |
|---|---|---|
| `specs_card` | `true` | spec card still (`spec.json` is written regardless) |
| `specs_material` | `""` | material assigned for mass when `.sklent.yaml` names none (`material.list`: PLA, ABS Plastic, Aluminum, …) |
| `specs_bom` | `true` | parts list (CSV, JSON, sheet) |
| `specs_bom_file` | `bom.yaml` | the BOM file next to the design in the repo; `.sklent.yaml` `bom:` overrides it or holds the list inline |
| `specs_views` | `true` | views sheet PNG + PDF |
| `specs_dimensions` | `true` | dimension still |
| `specs_assembly` | `false` | assembly step images |
| `specs_assembly_max_steps` | `20` | skip (with a note in the report) above this many steps |

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
| `get_design_spec`, `get_bom` | A design's `spec.json` and parts list |
| `view_sheet` | See a spec card, parts sheet, views sheet, dimension still or assembly step |
| `make_contact_sheet` | Every rendered design of a source on one sheet (PNG pages + PDF) |

With Kist's own MCP connected as well, an agent can go on to browse, view and tag the
filed sets there.

## API

`/api/sources`, `/api/designs`, `/api/designs/{id}/render`, `/api/designs/{id}/files/{name}`,
`/api/render-url`, `/api/jobs`, `POST /api/jobs/{id}/cancel`, `/api/settings`, `/api/status`;
see `sklent/api.py`. Specs and sheets add `/api/designs/{id}/spec`, `/api/designs/{id}/bom`,
`/api/designs/{id}/assembly`, `POST /api/sources/{id}/contact-sheet` and
`/api/sources/{id}/contact-sheet.png?page=N` / `.pdf`.

Each design carries `blob` (its file's git blob SHA, the sheet's revision) and `report`:
`{bodies, hidden_bodies, bounds_mm, palette, frame_ms, processes, timings_s}` from its newest
render set's `report.json` (`bounds_mm` is `[[x, y, z] min, [x, y, z] max]`; `palette` is the
one that set was rendered with), or `null` before the first render. With specs on it also
carries `spec`, the newest set's `spec.json`.

## Limits

- Designs are fetched as single files. A design that links parts from other files in its
  repo isn't supported yet.
- SolidCraft's headless renderer ignores `view.visual_style`, so the wireframe style is an
  x-ray: see-through bodies with every edge (see `docs/spike.md`).

MIT licensed.
