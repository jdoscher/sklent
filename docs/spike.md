# Rendering spike (2026-10-31)

Goal: prove SolidCraft designs can be turned into turntable videos, GIFs, and stills
headlessly on the render host, in both a shaded and a wireframe style.

## Setup

- SolidCraft 0.28.0 `linux-x86_64.tar.gz`, `solidcraft-cli mcp --headless --in <design>`
  driven over stdio by `mcpc.py` (a ~40-line MCP client).
- Container: `ubuntu:24.04` + `mesa-vulkan-drivers`, `ffmpeg`, `python3`; run with
  `--device /dev/dri --group-add 992` (render group). `solidcraft-cli gpu` picks the
  **Intel Iris Xe (Vulkan, hardware tier)**; renderer reports `gpu`.
- Working dir on the render host: `/srv/docker-dev/look-askew-spike/`.

## Findings

| question | answer |
|---|---|
| Headless render on the render host GPU? | Yes. Iris Xe via Mesa ANV inside Docker. |
| Turntable camera | `screenshot` with `camera: {target, yaw, pitch, distance, fov}`; step `yaw`. Pass `fov > 0` for perspective. Don't pass the `up`/`roll` keys that `view.isometric` returns. |
| `view.visual_style wireframe` | **Ignored by headless capture.** `crates/gpu/src/capture.rs` hardcodes the default style; the output is byte-identical to shaded. |
| Wireframe workaround | `appearance.assign {bodies, color, opacity: 0}` on every body: glass at 5% plus all B-rep edges, hidden ones included. Reads as an x-ray wireframe and looks good. |
| Speed, simple part (pi-case, 1 body) | 240 frames at 1080p in ~3–5 s. Whole set incl. encode ~35 s. |
| Speed, assembly (SELENE showcase, ~100 bodies) | 240 frames at 1080p in 40–60 s per aspect. Whole set ~5 min. |
| 4096² stills | 0.2–0.6 s. The CLI allows up to 8192. |
| Sizes (8 s, 30 fps) | 1080p mp4 1–4 MB; reel 1–3 MB; Discord 640p 0.3–0.9 MB (far under 10 MB); GIF 640 px 1.2–2.3 MB. |

## Gaps for the real renderer

- **Framing.** `measure` returns per-body `bbox`, with no overall box; the spike fits the
  bounding sphere, which leaves the model small (worse for flat or long designs like
  SELENE's display plate). Fit from the bbox corners projected per yaw instead, per aspect.
- **Saved views and render setups.** Designs may carry named views (`view.list`) or render
  setups. Prefer those for stills when present.
- **Upstream fix worth filing.** Headless `screenshot` should honor `view.visual_style`
  (and `shaded_with_hidden_edges`). Until then, keep the opacity workaround.
- **Body colour.** Designs carry their own colours (SELENE is orange and blue). Renders
  must be cool grey or white, so every body is repainted (`appearance.assign` in one
  `batch`, fast even for 1,400 bodies), which also overrides component and material looks.
  Per-face paint still wins over a body's look.
- Path-traced stills (`solidcraft-cli render`, CPU) were not tested.

## Outcome

All of the gaps above except path tracing are handled in the app: `sklent/render.py`
fits the camera from the projected bounding box per aspect ratio, and `sklent/palette.py`
repaints every body grey or white and greys out any pixel that still carries colour. The
spike scripts are not kept in the repo.
