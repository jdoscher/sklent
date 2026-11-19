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
