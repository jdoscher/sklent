# sklent

*Sklent* is Scots for a slant, or to look at something sideways. (It was called look-askew until
2026-10-31; an existing `look-askew.db` is picked up and renamed on first start.)

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

Hovering a tile plays its turntable; clicking it shows every file with downloads.

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
| `SK_RENDER_GID` | `992` | Group owning `/dev/dri/renderD128` on the host |

Render settings (palette, length, frame rate, camera pitch, still and GIF sizes, styles)
are in the UI's **Settings** and the MCP `set_render_settings` tool.

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
| `get_render_set` | Files, sizes, download paths, Kist folder and item ids |
| `view_render` | See a still (image content) |
| `add_source`, `list_sources`, `scan_source`, `list_designs`, `render_design` | Finer control |
| `get_render_settings`, `set_render_settings` | Palette, length, sizes |

With Kist's own MCP connected as well, an agent can go on to browse, view and tag the
filed sets there.

## API

`/api/sources`, `/api/designs`, `/api/designs/{id}/render`, `/api/designs/{id}/files/{name}`,
`/api/render-url`, `/api/jobs`, `/api/settings`, `/api/status`; see `sklent/api.py`.

## Limits

- Designs are fetched as single files. A design that links parts from other files in its
  repo isn't supported yet.
- SolidCraft's headless renderer ignores `view.visual_style`, so the wireframe style is an
  x-ray: see-through bodies with every edge (see `docs/spike.md`).

MIT licensed.
