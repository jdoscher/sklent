# Sklent's design system

Sklent wears Kist 2.0's design system, so the two apps read as one suite, plus a small
drafting layer of its own (the "truth rule": every line either carries a real value or
separates two real things). The web UI is plain files: native ES modules and per-area CSS
under `sklent/web/`, with no bundler and no build step.

The decisions behind it are in the 0.2 review (U1 "Suite system", U2 "Drafting overlay");
the options built are UI 1–17 with 9a (label strip), 11a (schedule sidebar), 12a (drawing
sheet), 15a (sheet-style gate plus the first-run screen), 16a (the S-in-a-ring mark on
Kist's #3A3A3A tile, Instrument Serif wordmark) and 17a (no Sklent-side background keying).

## Layers

| layer | file | what it may contain |
|---|---|---|
| Kist tokens | `css/kist-tokens.css` | **Generated.** Kist's `web/src/styles.css` `:root` scale (type, motion, floats, corners, controls) and `web/src/themes.css` (dark, light, gallery), verbatim, with the Kist tag and commit in its header. Never edit by hand. |
| Pin | `css/kist-tokens.lock.json` | The Kist tag, commit and the copy's sha256. |
| Sklent tokens | `css/sk-tokens.css` | Only `--sk-*` names, each a Kist token or a `color-mix` of one: the canvas grid, the spec (mono) voice, hairline tones, the drawing sheet, dimension-line offsets, the title block. No colour values. |
| Areas | `css/base.css` … `css/phone.css` | Rules only. Colours come from tokens; no hex, `rgb()` or named colours (tested). |

Theme: `html[data-theme]` is `gallery` (default), `dark` or `light`; the Appearance menu also
offers System. `theme-init.js` sets it from `localStorage['sk.theme']` before the stylesheets
load, so the first frame is already the right colour, and `js/theme.js` keeps
`<meta name="theme-color">` equal to the theme's `--chrome`.

### Refreshing Kist's tokens

```bash
python scripts/sync_kist_tokens.py ~/src/kist          # a checkout at the tag you want
python scripts/sync_kist_tokens.py ~/src/kist --check  # exit 1 if the copy differs
```

The script rewrites `kist-tokens.css` and its lock and prints the token names added and
removed. Then run the tests: a removed or renamed token fails `test_tokens.py`, and a theme
change that breaks a text/surface pair fails `test_contrast.py`.

## Ownership

| file | owner | notes |
|---|---|---|
| `sklent/web/index.html` | design system | markup for the shell, gate, sheet, dialogs |
| `sklent/web/theme-init.js` | design system | first-paint theme (classic script) |
| `sklent/web/manifest.webmanifest`, icons (`favicon.*`, `icon-*`, `apple-touch-icon.png`) | design system | built by `scripts/build_icons.py` |
| `sklent/web/fonts/` | design system | Inter, Instrument Serif, JetBrains Mono (latin woff2) + OFL licences |
| `sklent/web/css/kist-tokens.css`, `.lock.json` | **Kist** (generated) | `scripts/sync_kist_tokens.py` only |
| `sklent/web/css/sk-tokens.css` | design system | the drafting overlay tokens |
| `sklent/web/css/base.css` | design system | fonts, reset, type roles, controls, focus, reduced motion |
| `sklent/web/css/shell.css` | design system | top bar, sidebar, job log, progress rule |
| `sklent/web/css/grid.css` | design system | canvas grid, grid header, tiles, empty states |
| `sklent/web/css/detail.css` | design system | drawing sheet, schedule, title block, dimension lines |
| `sklent/web/css/floats.css` | design system | dialogs, settings spec sheet, confirm, Appearance menu, toast |
| `sklent/web/css/gate.css` | design system | token gate |
| `sklent/web/css/phone.css` | design system | everything under 760 px |
| `sklent/web/js/api.js` | design system (seam) | `api(path, opts)` |
| `sklent/web/js/store.js` | design system | state, poll loop, `onChange` / `emit` |
| `sklent/web/js/ctx.js` | design system | the object handed to every seam callback |
| `sklent/web/js/detail.js` | design system (seam) | `registerDetailSection`, `registerTitleBlockField` |
| `sklent/web/js/sidebar.js` | design system (seam) | `registerSidebarSection`, `registerSourceAction` (added by specs) |
| `sklent/web/js/tiles.js` | design system (seam) | `registerTileBadge`, `registerTileFigure` |
| `sklent/web/js/settings.js` | design system (seam) | `registerSettingsGroup` (field types incl. `checklist`; optional `render`) |
| `sklent/web/js/grid.js`, `theme.js`, `toast.js`, `confirm.js`, `format.js`, `icons.js`, `dom.js`, `main.js` | design system | |
| `sklent/web/js/features.js` | **feature builders** | one `import './features/<name>.js';` line per feature |
| `sklent/web/js/features/*.js` | **feature builders** | feature UI, using only the seams below: `revisions.js`, `inputs-access.js`, `inputs-sources.js`, `inputs-classes.js`, `views.js`, `specs.js`, `outputs.js` |
| `sklent/web/css/features/<area>.css` | **feature builders** | one sheet per area, classes prefixed `sk-<area>-` (tested), tokens only |
| `docs/design.md`, `scripts/sync_kist_tokens.py`, `scripts/build_icons.py` | design system | |

Feature code doesn't edit design-system files; it calls the seams. If a seam is missing
something, extend the seam.

## Seams for feature work

A feature module lives in `sklent/web/js/features/` and is imported from `js/features.js`
(main.js imports that before the first render). Every callback gets `ctx`
(`js/ctx.js`): `{ state, api, refresh, schedule, emit, toast, confirm, activeJobFor, icon,
esc, $, $$, format }`. Treat `ctx.state` as read-only; escape anything from the server with
`ctx.esc`.

### `api(path, opts)` — `js/api.js`

```js
import { api } from '../api.js';
const job = await api(`/designs/${id}/render`, { method: 'POST', body: { force: true } });
```

`path` is under `/api`; `opts.body` is sent as JSON with the bearer token. Returns the parsed
JSON; throws `Error(detail)` on a non-2xx; a 401 sends the user to the token gate.

### `registerDetailSection({ id, title, order, render(container, design, ctx), sheet, when, group })` — `js/detail.js`

Extra content in the drawing sheet.

- `sheet: false` (the default): a section in the side column between the schedule and the
  title block, under a ruled caps label `title` (a spec card, a BOM, a files pack).
- `sheet: true`: a numbered row in the schedule after the files, under the label `group`
  (default `More`); choosing it renders the section into the viewer, in place of a media
  file (compare, filmstrip, an engineering sheet).
- `when(design) -> bool` hides it for designs it doesn't apply to.
- `order` sorts sections (default 100). Re-registering an `id` replaces it.
- `render` runs when the sheet opens and whenever that design's data changes (each poll
  that changes it), into a fresh container. Keep it idempotent.

```js
import { registerDetailSection } from '../detail.js';
registerDetailSection({
  id: 'spec-card', title: 'Spec card', order: 10,
  when: (d) => d.status === 'rendered',
  render(el, d, ctx) { el.innerHTML = `<p class="sk-data">${ctx.esc(d.name)}</p>`; },
});
```

### `registerTitleBlockField({ id, label, order, wide, value(design, ctx) })` — `js/detail.js`

An extra cell in the title block. `value` returns a string (escaped for you) or `null`; a
cell with no data is not shown (ISO 7200: the block holds the minimum). `wide` spans both
columns.

The built-in cells read `design.report` (from the API: `bodies`, `hidden_bodies`,
`bounds_mm`, `palette`, `frame_ms`, `processes`, `timings_s`) and, when the API adds it,
`design.spec`, whose values win: `spec.title`, `spec.bounds_mm`, `spec.bodies`,
`spec.palette`, and two cells shown only when present, `spec.mass_g` (or `spec.mass_kg`) as
**Mass** and `spec.material` as **Material**.

### `registerSidebarSection({ id, title, order, render(container, ctx), grow })` — `js/sidebar.js`

A section in the sidebar (the drawer on a phone). Built-ins: `views` (0), `sources` (10),
`jobs` (20, `grow: true`). `title: ''` draws no heading. `render` runs after every poll and
view change.

### `registerSourceAction({ id, icon, label, order, when, run })` — `js/sidebar.js`

An icon button (`icon` is a Lucide name from `js/icons.js`) on every source row, before Scan
and Remove, shown on hover (always on the phone). `when(source) -> bool` hides it;
`run(source, ctx)` may be async and its errors become a toast. Used by the contact sheet.

Files that aren't pictures or movies (PDF, CSV, Markdown) open in the viewer as a card with
Open and Download, without dimension lines.

### `registerTileBadge(fn)` — `js/tiles.js`

`fn(design) -> { text, title } | null`. Badges are small neutral mono chips at the right of a
tile's name line (`--chip-bg` / `--chip-text`); nothing is ever drawn over the render.

### `registerTileFigure(fn)` — `js/tiles.js`

`fn(design) -> url | null`: a picture for a tile whose design has no social still yet (the
views area's quick-check still while a first render runs, or a quick-check-only set). The
first non-null wins; a design with a `thumb_url` never asks.

### `registerSettingsGroup({ id, title, order, fields })` — `js/settings.js`

A group in the render-settings spec sheet. Built-ins: palette (0), turntable (10), stills
(20), GIF (30), output (40). Each field is
`{ name, label, type, unit, min, max, step, options, hint }`; `type` is `number` (default),
`select` (`options`: values or `{ value, label }`, the value's type is kept), `checkbox`,
`text` or `checklist` (a list value, one checkbox per option, e.g. the `outputs` list). Values load from `GET /api/settings` by `name` and are sent in the same
`PUT /api/settings` as the built-in fields, so the server must accept the new keys (add them
to its settings first; it rejects unknown ones). A group may also pass `render(container, ctx)` to draw rows it
manages itself under its heading (Settings → Tokens does); those aren't sent with Save.

## Backend seams

The web seams above have server-side partners. Every feature area is a package in
`sklent/features/` and plugs in through these; shared files only call them.

| seam | where | signature / contract |
|---|---|---|
| Feature registry | `sklent/features/__init__.py` | `MODULES` (one line per area: `revisions`, `inputs`, `views`, `specs`, `outputs`); each module exposes `SCHEMA` (additive SQL), `router` (mounted at `/api`) and `register_mcp(mcp)` |
| Render steps | `sklent/steps.py` | `register_step(name, run, *, order, when)`; `run(ctx: StepContext)` with `ctx.sc`, `ctx.add(...)`, `ctx.guard`, `ctx.restore()`, `ctx.settings`, `ctx.enabled(key)`, `ctx.info` (world-placed bodies), `ctx.box`. A failing step never fails the render. Orders: views 10–48, specs 50–79, revisions 80, outputs 90. Skipped on a quick check (`settings["quick_check"]`) |
| Settings registry | `sklent/jobs.py` | `register_setting(key, default, validate)`; `get_all_settings(design_id=None)` and `get_options(design_id=None)` apply a repo's `.sklent.yaml` overrides |
| Render path | `sklent/jobs.py` `_render` | download (`inputs.links.fetch_design`) → options (`get_options(id)`, `get_all_settings(id)`, then `views.render_overrides(id, opts, settings)`) → `settings["design"]` = the design row → `render_set` into a staging dir → Kist filing (`rev:`, `ref:` tags, version links) → `sets.promote` → keep policy |
| Render sets | `sklent/sets.py` (revisions owns it) | `latest_set(design_id)`, `get_set(design_id, set_id)`, `list_sets(design_id)`, `read_json(folder, name)`, `write_json(folder, name, data)`; one set per blob; `commit_sha` is always a commit |
| Framing | `sklent/render.py` | `world_bodies(sc, info)` (measure's world boxes; extra placements in `placed`), `placed_bounds(info)`; `ortho_fit`, `shot_path`, `paint_style`, `plan(opts, settings)` |
| Views | `sklent/features/views` | `render_overrides(design_id, opts, settings)`; `steps.render_job(sc, path, w, h, cam, ...)` |
| Specs | `sklent/features/specs` | `meta.design_row(ctx)` (reads `ctx.settings["design"]`), `ortho.register_sheet_backend(name, fn)`, `ortho.drawing_support(sc)` (SolidCraft ≥ 0.45 `drawing.*`) |
| Repo config | `sklent/repo_config.py` | `get(design_id) -> dict`, `render_overrides(design_id)`, `for_local(path)`, `parse(bytes)`, `resolve(path, files)`; read by views (highlight), specs (material, licence, bom, steps), outputs (title, licence) |
| Share links | `sklent/features/outputs` | `share_link(design_id) -> str \| None` (never creates one); used by the inputs review comment |
| Viewer gate | `sklent/auth.py`, `sklent/mcp_server.py` | viewers get `GET` under `/api` (not `/api/tokens`) and MCP tools in `mcp_server.READ_ONLY_TOOLS` (annotated `readOnlyHint`); every tool must be in `READ_ONLY_TOOLS` or `WRITE_TOOLS` (tested) |

## Vocabulary

| | |
|---|---|
| Faces | Inter (`--font-ui`) for every word; Instrument Serif (`--font-display`) for names and titles; JetBrains Mono (`--sk-font-data`, class `.sk-data` / `.mono`) for spec values: sizes, envelopes, hashes, paths, dates, frame counts. Counts a person reads stay Inter. |
| Sizes | `--fs-1`…`--fs-6` (11/13/15/18/24/34). A raw size needs `/* type-scale: allow */` (only the 16 px phone fields, so iOS doesn't zoom). |
| Controls | 28 px (`--ctl-h`), quiet by default; one primary per view (Render, Save, Continue; Re-render on the sheet uses Kist's preview pair). |
| Selection | `--accent-soft` fill + 1 px `--selected-line` outline; in the sheet `--preview-soft` + `--preview-dim`. |
| Lines | always 1 px (`--sk-line`). The frame is the one 3:1 line (`--sk-sheet-frame`); rules are decorative tones (`--sk-rule`, `--sk-rule-float`, `--sk-sheet-rule`). |
| Grid | 24 px cells on the canvas only, never behind a render or text, off on the phone and under `prefers-contrast: more`. Tiles are 280 px (`--sk-tile`) so gutters sit on grid lines. |
| Dimension lines | only on the media's edge, giving the file's true pixel size; never on a part. |
| Icons | Lucide (ISC), inlined in `js/icons.js`, 14/16/20 px, 1.5 stroke. Add a glyph there from lucide-static. |
| Motion | Kist's `--dur-*` / `--ease-*`; everything off under `prefers-reduced-motion`. |
| Floats | `--bg-float`, `--float-line`, `--float-shadow`, `--dialog-radius` / `--float-radius`, over `--scrim`. |

## Tests

| test | guards |
|---|---|
| `tests/test_tokens.py` | the vendored copy matches its pinned hash; the sync script reproduces it; `sk-tokens.css` defines only `--sk-*` from known tokens; every `var()` in the CSS exists; no colours outside the token files; font sizes on the scale; font and icon licences ship |
| `tests/test_contrast.py` | a Python port of Kist's `contrast.ts` (maths, parser, its 80 pairs) plus Sklent's own text/surface pairs, in all three themes |
| `tests/test_web.py` | every asset `index.html` names is served; ES-module imports resolve; the seams are exported; code is served `no-cache`; the manifest and its icons |
| `tests/test_design_api.py` | `blob` and `report` on designs; job cancel; "1 body" |

When a feature adds text on a new surface pair, add the pair to `SKLENT_PAIRS` in
`tests/test_contrast.py`.
