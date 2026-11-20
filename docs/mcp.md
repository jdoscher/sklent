# Agents (MCP)

Sklent has a streamable-HTTP MCP endpoint at `/mcp`, behind the same bearer token as the UI and
API. Agents can render a URL, follow the job, look at the stills, compare versions and build
every publishing output.

## Connect

=== "Claude Code"
    ```bash
    claude mcp add --transport http sklent http://<host>:8090/mcp \
      --header "Authorization: Bearer <token>"
    ```

=== "Any MCP client"
    URL `http://<host>:8090/mcp`, transport **streamable HTTP**, header
    `Authorization: Bearer <token>`.

Use the admin token (`SK_TOKEN`) for an agent that may render and change settings, or a
**viewer token** (Settings → Tokens) for one that should only look. A viewer may call the
tools marked **R** below and nothing else; every other tool answers 403. Helper tokens
(`skh…`) can't use MCP at all.

## Tools

46 tools; the 24 marked **R** only read.

| tool | | |
|---|---|---|
| `render_url` | Scan a URL now and queue renders; returns job ids | |
| `wait_for_job`, `job_status`, `list_jobs` | Follow progress | R |
| `cancel_job` | Drop a queued job, or stop a running render | |
| `get_render_set` | Files, sizes, download paths, Kist folder and item ids | R |
| `view_render` | See a still (image content) | R |
| `list_sources`, `list_designs` | What's there | R |
| `add_source`, `scan_source`, `render_design` | Finer control | |
| `get_render_settings` / `set_render_settings` | Palette, length, sizes | R / |
| `list_sets` | Every kept version of a design: commit, message, tags, files | R |
| `compare_sets` | Pixel compare of two versions plus the commits in between | R |
| `view_compare` | See a compare as one picture: older, newer, changes | R |
| `add_class_source` / `list_class_submissions` | Class sets: add one; who handed in what by the deadline | / R |
| `review_comment` / `post_review_comment` | Review Markdown for a source's renders; posting only when `inputs_review_post` is on | R / |
| `get_design_inputs` | A design's format, linked files, `.sklent.yaml` config and ref | R |
| `quick_check` | Queue a quick-check still (kept beside the current set) | |
| `render_outputs` | Queue a render with chosen outputs and views for that render only | |
| `get_views` | Quick-check URL, bed fit, configurations, studies, highlight, why views were skipped | R |
| `set_highlight` | A design's "my part" bodies (names or globs) | |
| `view_output` | See any still of a set by variant (`exploded`, `section`, `plate`, …) | R |
| `set_views_settings` | `outputs` and `views_*` settings | |
| `get_design_spec`, `get_bom` | A design's `spec.json` and parts list | R |
| `view_sheet` | See a spec card, parts sheet, views sheet, dimension still or assembly step | R |
| `make_contact_sheet` | Every rendered design of a source on one sheet | |
| `get_outputs` | A design's presets, print files, photos, listing details, readiness and Kist board | R |
| `make_output_preset` | Make one preset or all enabled ones | |
| `build_file_pack` | The print pack zip, optionally split (`split_mb`) | |
| `export_project_page` | Offline HTML page for a design or a source (zip) | |
| `build_listing_pack` / `listing_readiness`, `listing_text` | Marketplace packs / the checklist and listing text | / R |
| `set_listing_details` | Title, summary, licence, print notes, tags | |
| `attach_photo` / `list_photos` | Real print photos (base64 in) | / R |
| `make_review_board`, `create_share_link`, `revoke_share_link` | Kist board; a public share link only when the setting allows and the user asks | |
| `list_helpers` | Render helpers and what this server does with renders now | R (admin token only) |

## Things to ask

- "Render `https://github.com/<owner>/<repo>` and show me the spec card of the biggest design."
- "Compare the last two versions of `case.sc` and tell me what changed."
- "Build the Printables and Etsy listing packs for the bracket, with the licence from the repo."

Nothing an agent does posts anywhere on its own: review comments need
`inputs_review_post` on, and share links need `outputs_review_share_links` on and a request
from the user. See [Privacy](privacy.md).
