# Changelog

## [Unreleased]

### Design system and UI (0.2 builder D)

- Kist 2.0's design system: its tokens are vendored verbatim in `sklent/web/css/kist-tokens.css`
  (Kist v2.0.0, pinned by hash; `scripts/sync_kist_tokens.py <kist checkout>` refreshes it),
  with Sklent's drafting overlay as `--sk-*` tokens built only from Kist's. Three themes,
  gallery grey by default, under a new **Appearance** menu; Inter, Instrument Serif and
  JetBrains Mono are self-hosted with their OFL licences.
- One grey surface with a pinstripe, monochrome ink (Render is the one primary), 28 px
  controls, a one-line top bar with a Kist status dot, and a grid header with a serif title.
- A faint 24 px grid on the canvas with the tiles snapped to it; each tile is a clean render
  with a label strip under it: the name, then `95 × 66 × 32 mm · 1 body · 1258878`, or the
  job's frame counter while it renders, or the failure reason.
- Progress is a 1 px scale rule with ticks and the percentage.
- The sidebar reads as a schedule: Lucide icons, sources as their file or folder name over
  the path, a mono job log with a Cancel button on queued and running jobs.
- The detail view is a drawing sheet: the media with dimension lines giving its true pixel
  size, a numbered schedule of the files (with the Discord file's `0.6/10 MB` budget) and a
  title block (title, source @ commit, revision, date, palette, styles, envelope, bodies,
  status, sheet n/N, Kist folder).
- Render settings as a spec sheet with live frame totals; Kist-style dialogs, toasts (with
  Cancel on "Render queued") and a confirm dialog in place of the browser's.
- The token gate is a blank sheet with a title-block card; the first run shows example URLs;
  every empty view says what would appear there.
- Phone: two-row top bar, view pills, the sidebar as a drawer (filters, sources and jobs were
  unreachable on a phone), two columns, the detail as one scrolling sheet, a PWA manifest,
  and `theme-color` following the theme.
- App icon: the S-in-a-ring mark, now white on Kist's #3A3A3A tile (`scripts/build_icons.py`).
- `app.js` is now native ES modules in `sklent/web/js/` and `styles.css` per-area files in
  `sklent/web/css/`; no build step. Code and styles are served with `Cache-Control: no-cache`
  so an upgrade never runs stale modules.
- Seams for feature work: `registerDetailSection`, `registerTitleBlockField`,
  `registerSidebarSection`, `registerTileBadge`, `registerSettingsGroup` (see `docs/design.md`).
- API: designs carry `blob` and `report` (bodies, hidden bodies, bounds in mm, palette, frame
  time, processes, timings) from the newest set's `report.json`.
- `POST /api/jobs/{id}/cancel` and the MCP `cancel_job` tool: a queued job is dropped, a
  running render's SolidCraft processes are killed; the design goes back to its old status.
- Job messages say "1 body", not "1 bodies".
- A render set is found under the data dir even when the stored absolute path moved (a
  restored or relocated data dir).

### Specs and sheets (0.2 builder S)

- **Spec card (F2):** every render writes `spec.json` (envelope, volume, mass when a material
  is known, bodies, components, user parameters, commit, blob, licence) and a 2048×1152
  title-block still. Assemblies are measured as placed (each placement of a part counts).
  Designs in the API carry `spec`, so the drawing sheet's title block shows mass and material.
- **BOM card (F8):** `assembly.bom` merged with an optional `bom.yaml` of bought parts, as
  `bom.csv` (filed in Kist), `bom.json` and a parts sheet; a **Parts** section in the sheet.
- **Engineering view sheet (F11):** front, top and right orthographic views in third-angle
  projection at an ISO scale on A3, an iso view and a title block, as PNG and PDF. Ready
  for SolidCraft's `drawing.*` (0.45+) through a feature-detected sheet backend.
- **Dimension callout (F21):** the front view with overall width and height as ISO 129
  dimension lines from the measured box at the camera's exact orthographic scale, depth noted.
- **Contact sheet (F27):** a button on each source row (and `POST /api/sources/{id}/contact-sheet`,
  MCP `make_contact_sheet`) puts every rendered design's hero still on one page with mono
  labels: 3840×2160 PNG pages and a PDF; filed in Kist once per version when Kist is on.
- **Assembly steps (F30, off by default):** one picture per step, new parts darker and earlier
  ones lighter, plus `assembly.md` in GitBuilding BuildUp Markdown; steps from `.sklent.yaml`
  or the order parts were placed.
- MCP: `get_design_spec`, `get_bom`, `view_sheet`, `make_contact_sheet`. `sklent render`
  takes `--settings JSON`.
- The drawing sheet shows PDF, CSV and Markdown files as open/download cards; a new
  `registerSourceAction` seam adds buttons to source rows.

## 0.1.1 (2026-11-01)

- New app icon: an S inside a ring, light grey on deep grey (a matched set with Kist's K),
  in the top bar and as the browser tab, bookmark and home-screen icon.
- `favicon.ico`, `favicon.svg` and `apple-touch-icon.png` are also served at the site root,
  where browsers and bookmark services look for them (they used to get the page's HTML).
- Icon URLs carry a version query so browsers pick up a changed icon.

## 0.1.0 (2026-10-31)

First release.

- Point it at a GitHub or Forgejo account, repo, folder or file; every SolidCraft design
  found (`.sc`, `.solidcraft`) is rendered, and a re-scan renders only what changed.
- Per design, in a shaded and a wireframe (x-ray) style: a 1080p turntable movie, a
  1080×1920 reel, a Discord-sized 640p movie under 10 MB, a GIF, a 2048² social still and a
  3840×2160 still.
- Parts are always cool grey or white: every body is repainted and a colour guard greys
  out any pixel that still carries colour.
- Camera distance is fitted to the visible bodies' bounding box, separately per aspect ratio.
- Render sets are filed into Kist under `SolidCraft/<owner>/<repo>/<design>` with tags and
  a source link at the rendered commit; re-rendering trashes the previous set.
- Web UI (hover-to-play tiles), REST API and a streamable-HTTP MCP endpoint, all behind one
  bearer token.
- Docker image with SolidCraft 0.28.0; uses a `/dev/dri` GPU through Mesa Vulkan when
  present, software Vulkan otherwise.
- Renamed from look-askew before release; an existing `look-askew.db` is adopted on first
  start.
