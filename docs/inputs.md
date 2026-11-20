# Inputs and access

## What a URL can point at

Paste any of these into the top bar and press **Render** (or **Add source** to watch it without
rendering yet):

- `https://github.com/<owner>`: every non-fork, non-archived repo
- `https://github.com/<owner>/<repo>` or `…/tree/<branch>/<folder>`
- `https://github.com/<owner>/<repo>/blob/<branch>/<path>.sc`: one design (or `.step`, `.stl`, `.3mf`)
- `…/pull/<n>` (GitHub) or `…/pulls/<n>` (Forgejo): the designs a pull request changes
- `…/tree/<tag>`, `…/releases/tag/<tag>`, `…/commit/<sha>`: a tag or commit
- `https://github.com/<org>?prefix=<repo prefix>`: a [class set](#class-sets-and-due-dates)
- the same shapes on Forgejo (`…/src/branch/<branch>/<path>`), and SSH clone URLs

**Discovery** uses the forges' git-tree APIs; nothing is cloned. Files are found with their
blob SHAs, so a re-scan renders only what changed. Folders named `tests`, `test`, `fixtures`
and `corpus` are skipped by default (per-source `exclude`). A scheduler re-scans every source
every `SK_SCAN_INTERVAL_MINUTES` (360; `0` turns it off).

## Formats

| format | opens as | setting |
|---|---|---|
| `.sc`, `.solidcraft` | SolidCraft designs | always |
| `.step`, `.stp` | B-rep bodies; an assembly's parts become components | `inputs_step` (on) |
| `.stl`, `.3mf` | mesh bodies (no volume; the x-ray style shows the mesh's edges) | `inputs_mesh` (on) |

Everything else (framing, the grey repaint, the colour guard, every output) is the same. A mesh
with the same name as a SolidCraft design in its folder (`case.sc` and `case.stl`) is taken as
its export and skipped; pointing a source at the file itself renders it anyway. Git LFS files
are fetched through the forge's media endpoint. Tiles carry a `STEP`, `STL` or `3MF` chip.
OpenSCAD (`.scad`) isn't rendered yet.

### Linked designs (multi-file assemblies)

A SolidCraft assembly that links parts saved in other files renders whole: before a render,
Sklent fetches the design and every file it links (and what those link; up to 64 files) at the
same commit, and once SolidCraft has opened it, updates the links that changed since the design
was saved. A linked file that can't be fetched keeps the copy saved in the assembly, with a
note. Editing a linked part re-renders every assembly that uses it. The tile shows `ASM n`; the
sheet's **Inputs** section lists the files.

## `.sklent.yaml`

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
boolean feature settings; the `render_*` and `helpers_*` settings are the server's alone.
Listing packs also read `title`, `licence`/`license`, `description`, `print_notes`, `tags` and
`print_exclude` from it.

## Branches, tags and pull requests

A source can name a ref; its designs are kept apart from the default branch's, and tiles show
the ref (`PR #12`, `dev`, `v1.2`). A pull-request source renders only the designs the PR adds or
changes, plus assemblies that link a changed file, at the PR's head.

The sheet's **Review comment** section builds Markdown for the PR thread: each design's still
before (from the base branch, when Sklent has it) and after, with its envelope and body count
and a link to the turntable GIF. **Nothing is posted** unless `inputs_review_post` is on and
someone presses **Post** (or calls `post_review_comment`); then it is one comment through the
forge's API with the server's token, which needs GitHub fine-grained `Pull requests: write`
(classic: `public_repo` or `repo`) or Forgejo `write:issue`. Without that, scanning needs only
read access. `inputs_public_url` sets this server's URL for the comment's links.

## Class sets and due dates

A class set is an account or organisation plus a repo-name prefix, the way GitHub Classroom
names an assignment's repos (`bracket-hw-<username>`). Add one from the sidebar's **Class
sets** (or `POST /api/classes`, MCP `add_class_source`), with an optional deadline and roster:

- **Deadline** (ISO 8601): each repo renders its newest commit at or before it (committer
  date). A later push shows `after due` on the tile and doesn't re-render.
- **Roster**: usernames, `username, Display name`, or repo-name patterns with `*`. The sidebar
  shows `n/m submitted` and, opened, every student as handed in, `no design`, `nothing by due`
  or `no repo`.

Any source can carry a deadline (`PUT /api/sources/{id}/class`).

## Tokens

| token | made by | may |
|---|---|---|
| Admin (`SK_TOKEN`) | `.env` | everything: UI, API, MCP |
| Viewer | **Settings → Tokens**, or `sklent token create NAME` | browse, view and download: every `GET` under `/api` (except `/api/tokens` and `/api/helpers`) and the read-only MCP tools |
| Helper (`skh…`) | **Settings → Helpers**, or `sklent token create NAME --scope helper` | only the [helper protocol](helpers.md#the-protocol) |

Viewer and helper tokens are shown once and stored as SHA-256 hashes; `sklent token
list|revoke` and **Settings → Tokens** list and revoke them. For a viewer, rendering, adding or
removing sources, changing settings, managing tokens and every MCP tool that changes something
answer 403, and the UI hides those controls.
