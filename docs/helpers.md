# Render helpers and GPU

Sklent renders every design with [SolidCraft](https://github.com/tangency-labs/solidcraft), an open-source parametric CAD app, which it
runs headless (with no window). It can keep a shared GPU usable, render in software, hold
renders for quiet hours, and hand the rendering to other machines.

## This server's GPU

**Settings → Rendering**:

- **Renderer**: `GPU`; `Software (CPU)`, which runs SolidCraft on Mesa lavapipe (slower, the
  same pictures, no GPU load, so other GPU work on the machine is left alone); or
  `Off: helpers only`, where this server never renders and jobs wait for helpers. Scans,
  filing into [Kist](https://kist.pictures) and the UI carry on either way.
- **GPU processes**: the most SolidCraft processes on the GPU at once (default 1). In software
  mode, big designs fan out to `SK_RENDER_PROCESSES` instead.
- **Quiet hours** (e.g. `22:00-07:00`, this server's local time, `TZ`): during them, *Wait:
  helpers only* takes no render here (the sidebar says "Quiet hours: helpers only"), and
  *Render in software* switches to the CPU.
- **Helper fallback**: with no helper seen in the last 10 minutes this server renders at
  once. With one around, it takes a render only once the job is `helpers_fallback_minutes` old
  (30; 0 = never), outside quiet hours (or in software mode) and when the renderer isn't off.
  Scans never wait behind a render held for a helper.

Each set's `report.json` and the drawing sheet's title block say where it was rendered
(`renderer: gpu|software`, the adapter, and the host).

## Render helpers

A render helper is another machine with SolidCraft that renders for this server. It asks for
work, downloads the design (and its linked files) from this server, renders the set with this
server's settings and every feature step, and uploads it. This server then files it into
[Kist](https://kist.pictures), links the versions and keeps the revision history, exactly as for its own renders.
Scans stay on the server. A helper needs no database, no data folder and no forge token.

### Its token

**Settings → Helpers → Create helper token** (or `sklent token create NAME --scope helper` on
the server) makes a token that starts with `skh`. It may call only the helper protocol
(`/api/helpers/claim` and `/api/helpers/jobs/…`); every other route and every MCP tool (MCP is
the protocol AI agents like Claude use to call tools) answer 403.
The panel shows the `.env.helper` lines once. Revoke the token in **Settings → Tokens**.

### A Linux box (container)

An Intel or AMD GPU through Mesa, or software rendering:

```bash
git clone https://github.com/jdoscher/sklent.git && cd sklent
cp .env.example.helper .env.helper    # paste the lines from Settings -> Helpers
docker compose --env-file .env.helper -f docker-compose.helper.yml up -d
docker compose -f docker-compose.helper.yml logs -f   # "asking ... for work"
```

`.env.helper` holds `SK_HELPER_URL` (the server as this machine reaches it), `SK_HELPER_NAME`
(its name in the server's Helpers list), `SK_HELPER_TOKEN`, `SK_RENDERER`,
`SK_RENDER_PROCESSES` and `SK_RENDER_GID`. On a box without `/dev/dri`, drop the `devices:` and
`group_add:` keys and set `SK_RENDERER=software`.

### A Mac with Apple silicon (native)

Install SolidCraft's app and ffmpeg, `pip install` this repo, then run the helper with full
paths to the programs:

```bash
SK_SOLIDCRAFT_CLI=/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli \
SK_FFMPEG=/opt/homebrew/bin/ffmpeg \
sklent helper --url http://sklent-host:8090 --token-file ~/.config/sklent-helper.token --name mac
```

Options: `--renderer gpu|software`, `--processes N` (frames of one design in parallel),
`--max-bodies N` (leave bigger designs to others) and `--once` (one job, then exit). The
environment equivalents are `SK_HELPER_URL`, `SK_HELPER_TOKEN`, `SK_HELPER_NAME`,
`SK_RENDERER` and `SK_RENDER_PROCESSES`. The parallel-frame memory guard works on macOS too,
and when free memory can't be measured the helper renders with one process.

### Rules of the road

- A helper must run the **same SolidCraft version** as the server, or its claims are refused
  with 409 and the reason (`helpers_require_same_solidcraft`). The container image pins it; on
  a Mac, install the matching release.
- Stopping a helper (`docker compose -f docker-compose.helper.yml stop`, or Ctrl-C) reports
  its job as "helper stopped", and the server queues it again at once.
- A helper that vanishes loses its job when its lease runs out (`helpers_lease_seconds`,
  300 s, renewed by every progress report). A job is claimed at most `helpers_max_attempts`
  (2) times, then fails.

**Settings → Helpers** lists every helper with its last contact, SolidCraft version,
renderer, current job and done count; the job log says which helper rendered a job.

## Settings

The `render_*` and `helpers_*` settings are server-side only: `.sklent.yaml` can't change them.

| setting | default | |
|---|---|---|
| `render_device` | `SK_RENDERER` (`gpu`) | `gpu`, `software` or `off` (helpers only) |
| `render_gpu_processes` | `1` | Most SolidCraft processes on the GPU at once |
| `render_quiet_hours`, `render_quiet_mode` | none, `wait` | e.g. `22:00-07:00` (server time, `TZ`); `wait` leaves renders to helpers, `software` renders on the CPU |
| `helpers_fallback_minutes` | `30` | With a helper around, this server takes a render only once it has waited this long; `0` never |
| `helpers_seen_window` | `10` min | A helper counts as around if it asked for work this recently |
| `helpers_require_same_solidcraft` | on | Refuse (409) a helper whose SolidCraft differs from this server's |
| `helpers_max_attempts`, `helpers_lease_seconds` | `2`, `300` | Claims of one job before it fails; a helper's lease, renewed by its progress |

## The protocol

For helper tokens (and the admin token): `POST /api/helpers/claim` with `{name,
solidcraft_version, renderer, gpu, mem_gb, max_bodies?}` answers 204 (nothing to do), 409 (a
different SolidCraft) or `{job, design, settings_snapshot, design_file, stem, lease_s}`. Then,
under `/api/helpers/jobs/{id}/` with `?name=`: `GET inputs.tar`, `GET repo-file?path=`, `POST
progress` (`{fraction, message}` → `{cancel}`), `POST result` (a tar of the set whose first
member is `.sklent-manifest.json`) and `POST fail` (`{error, retry?}`).
`GET /api/render-state` says what the server does with renders now and why they wait.
