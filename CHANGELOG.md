# Changelog

## [Unreleased]

### Revisions (0.2 builder R)

- **Revision history (F1).** Every rendered version of a design keeps its own render set
  (`set.json`: the commit that made it, its message, author and date, git tags, files, Kist
  items) instead of the newest replacing the rest. Re-rendering the same version replaces
  only its set. Keep policy `revisions_keep` (tagged versions plus the newest 10 untagged on
  disk; `0` keeps all); Kist is never pruned unless `revisions_prune_kist`.
- **Kist versions.** A re-render no longer trashes the previous set's items. Every item
  carries `rev:<commit10>` (items filed before this get theirs from their notes), and each
  new item is linked `version_of` the item it follows and stacked with it as the cover, so
  Kist's versions and compare work on the chain and existing Kist links keep working.
- **Compare, filmstrip, changelog.** Two new sheets under Revisions: a slider, side by side
  or changed-pixel view (numpy mask in the sheet's ink) of any still or the same turntable
  frame, with the commits in between from the forge; and a filmstrip of one still per
  version on a hairline timeline. Tile badge `N rev`; title-block Tags and Versions.
  `GET /api/designs/{id}/sets`, `/compare`, `/changelog` and friends; MCP `list_sets`,
  `compare_sets`, `view_compare`.
- **Cancel keeps the old set.** A render writes into a staging folder and swaps it in once
  finished, so cancelling (or a failure in) a forced re-render leaves the design's set as
  it was.
- **Build-history timelapse (F29).** Render step `timelapse` (`revisions_timelapse`, off):
  `timeline.rollback` through the feature history, one still per step, as MP4 and GIF;
  skipped above `revisions_timelapse_max_bodies` (100) or `_max_features` (200), with the
  reason in the report.
- `sklent render --settings JSON` passes feature settings to a one-off render.
### Views and render modes (0.2 builder V)

- Quick check (F17): every render first makes one shaded iso still, guarded for colour, shown
  on the tile and the sheet while the rest renders. `RenderOptions.outputs` (Settings →
  Outputs, and per render on the sheet, `POST /api/designs/{id}/views/render`, MCP
  `quick_check` / `render_outputs`) picks which of the six files to make; none is a quick
  check alone. Frames that no chosen output needs aren't rendered.
- Shot presets and masters (F24): half orbit onto the iso angle, push-in, top-down to iso and
  a low angle, eased and fitted to the part; 4K H.264, ProRes 422 HQ and zipped PNG-sequence
  masters that loop exactly, up to 60 s. Off by default.
- Exploded still and explode animation (F4), section cut through the centre with filled
  caps (F9), configuration stills and a same-scale lineup (F10, on when a design has
  configurations), "my part" highlight still and turntable (F20, per design or
  `.sklent.yaml`), motion-study clips (F22, on when a design has studies), transparent
  stills and a path-traced studio hero (F15), and a plate view on a 10 mm grid (F16), as
  render steps 10–48. Each records what it made or why it skipped in `report.json`
  (`views`), shown in the sheet's **Views** section.
- Bed-fit badge on tiles and in the title block, against a named printer bed from an
  editable list (F16).
- `sklent render` gained `--outputs`, `--settings` and `--highlight`.
- Seams: `registerTileFigure` (tiles.js) and a `checklist` field type (settings.js).
### Outputs and publishing (0.2 builder O)

- Output presets (F6): named sizes cut from a set on demand and framed on the part, stepped
  down to each site's cap (Printables/MakerWorld 4:3 cover, Cults 800×800 ≤ 10 MB video,
  YouTube 1280×720 ≤ 2 MB, LinkedIn and Instagram 4:5, GitHub 1280×640 ≤ 1 MB, Handshake
  PDF ≤ 1 MB), cached under the set's `presets/`; an editable list; "Download all" zips.
- Print and release file pack (F7, off by default): a render step exports STEP, 3MF and STL
  from the rendered commit (per body, and no 3MF, above a body budget; hidden and excluded
  bodies left out); packs add README, licence and a sha256 manifest and split for Etsy's
  5 × 20 MB. Checked against SolidCraft 0.44.1.
- Project page export (F5): a static, offline HTML folder per design or source.
- Listing packs and text (F13): a zip per marketplace checked against its rules, with
  `listing.md` and `pack.json`. Nothing is posted.
- Real photo slots (F19): upload print photos (EXIF removed); they lead packs and pages; a
  "ready to list" checklist per marketplace and a `photos n/N` tile badge.
- Brand presets (F23, off by default): watermark (text or PNG mark), title and end cards on
  exported copies only.
- Kist review board (F26): a set or source as a Kist board; a share link with guest
  proofing only when allowed in Settings and clicked. `sklent.features.outputs.share_link()`
  hands it to other features.
- The drawing sheet shows "no preview" for files without a picture (STEP, STL, zips), and
  its Styles cell lists only shaded/wireframe.

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

### Inputs and access (0.2 area P)

- STEP (`.step`/`.stp`), STL and 3MF files are designs: discovery finds them (settings
  `inputs_step`, `inputs_mesh`, both on; `.sklent.yaml` `formats`), skips a mesh that is the
  export of a `.sc` design next to it, checks each file is what its name says, and follows
  Git LFS pointers on GitHub. Tiles show a `STEP`/`STL`/`3MF` chip.
- Multi-file assemblies: a SolidCraft design's linked files are fetched with it at the same
  commit, in the repo's layout, and links that changed are updated when SolidCraft opens it.
  An assembly re-renders when a linked part changes.
- `.sklent.yaml` per repo or folder: include/exclude globs, formats, title, licence,
  presets, `bom.yaml` path, material, highlight bodies, assembly steps, STEP `up`, and render
  overrides (palette, seconds, styles, feature toggles). `sklent.repo_config.get(design_id)`
  for other features; `design.config` in the API.
- Branch, tag, commit and pull request URLs (`/pull/<n>` on GitHub, `/pulls/<n>` on Forgejo).
  Designs are keyed by source and ref; a PR renders the designs it changes (and the
  assemblies that link them) and shows `PR #n`. **Copy review comment** builds before/after
  Markdown; posting it to the PR is a setting (`inputs_review_post`), off by default.
- Class sets: an org plus a repo prefix, a deadline (each repo renders its last commit at or
  before it; later pushes show `after due`), and a roster showing who has no submission. A
  **Class sets** section in the sidebar.
- Read-only viewer tokens: Settings → Tokens (and `sklent token create|list|revoke`); stored
  hashed; viewers can browse, view and download, but every write, the token list and MCP
  tools that change things are refused, and the UI hides those controls.
- `sklent render` takes STEP/STL/3MF, `--settings JSON` and `--config`.
- MCP: `add_class_source`, `list_class_submissions`, `review_comment`,
  `post_review_comment`, `get_design_inputs`.
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
