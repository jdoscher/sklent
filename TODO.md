# To do

Open work as of 2026-10-31, with the context needed to pick it up cold. Newest
decisions first within each item.

## 1. Parallel render processes (speed up large designs)

**Status:** agreed in principle, not started.

**Why.** GPU passthrough works (the container has `/dev/dri` and the render group;
`solidcraft-cli gpu` picks the Intel Iris Xe, hardware tier), but the GPU is mostly idle.
Measured on SELENE-functional (2,116 bodies), warm, inside the container:

| step | time | bound by |
|---|---|---|
| Load design (`mcp --headless --in`, SolidCraft rebuilds the model) | ~125 s, once per process | one CPU core |
| First screenshot (geometry upload) | ~16 s, once per process | GPU |
| Each later screenshot | ~0.55 s at 1920×1080, 1080×1920 **and** 320×180 | one CPU core (SolidCraft at ~87%) |
| Painting all bodies (`appearance.assign` in one `batch`) | <0.1 s | |

Frame time doesn't change with resolution, so the per-frame cost is SolidCraft redoing
CPU-side scene work on every `screenshot`, not drawing. A full set is 960 frames
(2 styles × 2 aspects × 240), about 9 of SELENE-functional's 12 minutes. Small parts
(pi-case) take ~15 ms a frame and don't need any of this.

**Plan.**
- Split the frame work in `sklent/render.py` `render_set` across N `SolidCraft`
  processes. Simplest split: each worker gets a contiguous slice of the 960
  (style, aspect, frame) tasks, so each paints once or twice instead of per frame.
  Every worker loads the design itself (load is the fixed cost, paid in parallel).
- Keep stills in worker 0. Keep the colour guard and ffmpeg encode after all workers
  finish (unchanged).
- Setting: `SK_RENDER_PROCESSES` (default 4) in `config.py`, documented in README and
  `.env.example`. Use 1 when the design is small: e.g. render the first 8 frames in one
  process, and only fan out if the measured frame time is over ~50 ms.
- Progress: aggregate the workers' frame counts into the job's progress.
- Errors: if any worker fails, kill the others and fail the job with that worker's stderr
  tail (`SolidCraftError` already carries it).

**Memory.** Peak RSS per SolidCraft process: pi-case 275 MB, SELENE-functional
**6.7 GB**. The render host had 47 GB free, so 4 workers (~27 GB) fit; 6+ wouldn't leave headroom.
Consider capping workers by `MemAvailable / (measured RSS of worker 0 after load)`.

**Expected.** SELENE-functional ~12 min → ~5–6 min (2 min load + ~2.2 min frames +
guard and encode). Measure after building it; record before/after here.

## 2. File an upstream SolidCraft issue

Headless `screenshot` (`crates/gpu/src/capture.rs`) costs ~0.55 s of CPU per frame on
a 2,000-body design regardless of resolution. If it reused the scene between frames when
only the camera changes, big designs would render nearly as fast as small ones, which
makes item 1 mostly unnecessary. Include the numbers above and a repro (SELENE-functional
from `assets/render/selene/models/`, a loop of `screenshot` calls with only `yaw` changing).

Also worth filing: headless capture ignores `view.visual_style` (it hardcodes the default
style), which is why our wireframe is an x-ray (all bodies at opacity 0). See
`docs/spike.md`.

## 3. Kist changes that were planned but not built

The second Kist runs **unmodified Kist 1.0.0**. GIF and video previews were already in
1.0.0, so nothing was required. The hover-to-play GIFs are in sklent's own UI only.
If these go into Kist, release them as Kist 1.1.0 (its `docs/releasing.md`):

1. Hover-to-play videos and animated GIFs in Kist's grid.
2. An idempotent "ensure folder path" call in Kist's API and MCP
   (`ensure_folder("SolidCraft/owner/repo/design")`). sklent does it client-side today
   in `sklent/kist.py`.
3. Public share links (unguessable, revocable, per item or folder) so doscher.com can
   embed files without the token. The biggest of the four.
4. A check that ~50 MB video uploads work. The largest render so far was ~6 MB, fine.

## 4. GitHub release of sklent

**Public.** The repo is public on Forgejo, and personal infrastructure is scrubbed from the
code and the whole history (2026-10-31): no Forgejo URL default, SSH URLs on non-GitHub
hosts map to `https://<host>` when none is configured, documentation addresses and paths
are placeholders. Left to do:

- Tag `v0.1.0` and use `CHANGELOG.md` for the release notes.
- No GitHub remote is configured; push by URL with gh's credential helper (as for Kist).

## 5. Promote sklent to production

- Today: dev only, `/srv/docker-dev/sklent` (compose project `sklent-dev`), port 8090, filing into
  the **dev** renders Kist on port 8083.
- Prod renders Kist already exists: `/srv/docker/kist-renders`,
  port 8082, running the main Kist's images through `docker-compose.override.yml`. It has
  a copy of the 3 test render sets.
- To promote: new compose dir under `/srv/docker/sklent`, its own
  token, `SK_KIST_URL=http://192.0.2.10:8082` with the prod renders Kist's token.
  Optionally copy the dev `data/` so existing designs keep their Kist item ids (the prod
  renders Kist was rebuilt from the same library, so the ids match).
- LAN only; no reverse proxy wanted.

## 6. Smaller items

- **Tokens:** set `SK_FORGEJO_TOKEN` (private Forgejo repos aren't visible without it)
  and `SK_GITHUB_TOKEN` (anonymous GitHub is 60 API calls/hour; scanning a whole account
  needs more).
- **Linked designs:** designs are fetched as single files. A design that pulls parts from
  other files in its repo won't render. Would need a shallow or sparse clone.
- **Path-traced stills** (`solidcraft-cli render`, CPU) are untested. They could give
  photoreal hero stills alongside the viewport look.
- **Saved views:** prefer a design's named views (`view.list`) for stills when present.
- **Framing:** square stills of long, low designs still have generous margins; framing
  uses the bounding box of visible bodies, which counts a stray small body (SELENE's
  sphere) as much as the main model.
- **Discord sizing:** "640p" is read as 1138×640. Change in `render.py` if 640×360 was
  meant.
