# Privacy

Sklent runs on your server and talks only to the places you point it at. It has no telemetry,
no update check and no analytics, and the web UI loads nothing from anywhere else: the fonts
(Inter, Instrument Serif, JetBrains Mono) and icons ship inside the app.

## What it sends where

| to | when | what |
|---|---|---|
| **GitHub** (`api.github.com`, file downloads, Git LFS media) | You add a GitHub source; then on each scan and render | Tree and commit API reads, the design files and their linked files at the scanned commit. `SK_GITHUB_TOKEN`, if set, goes only to GitHub |
| **Your Forgejo** (`SK_FORGEJO_URL`) | You add a Forgejo source; then on each scan and render | The same reads. `SK_FORGEJO_TOKEN` is only ever sent to that host |
| **Your Kist** (`SK_KIST_URL`) | You set the URL; then after each render | The render set's files, tags and version links, filed into its folder |
| **This server**, from a render helper | You run a helper with a helper token | The helper asks for work, downloads the design and uploads the set. The server never calls out to helpers |

Re-scans repeat the forge reads every `SK_SCAN_INTERVAL_MINUTES` (360 by default; `0` turns the
schedule off, so sources are scanned only when you ask). GitHub allows 60 anonymous API calls
an hour, so a token also keeps a big scan from hitting the limit.

## Off by default

Everything that publishes or makes something public is off until you turn it on, and then
happens only on a click:

- **Posting review comments** to a pull request (`inputs_review_post`). Even when on, a comment
  is posted only when someone presses **Post** or an agent calls `post_review_comment`.
- **Kist share links** (`outputs_review_share_links`). A share link is a public page on your
  Kist; it is made only when you click and confirm, expires (30 days by default) and can be
  revoked.
- **Pruning Kist** (`revisions_prune_kist`): left off, Sklent never trashes anything in Kist.
- **Print file packs** (`outputs_filepack`) and **brand** watermarks: local only, but off.

Sklent packages and never posts to a marketplace: listing packs, presets and project pages are
zips you download and upload yourself.

## What stays local

- Render sets, presets, packs and photos stay under `SK_DATA` (`./data`), and in Kist if you
  connected one.
- **Real photos** you upload lose their EXIF, GPS included, when they're stored.
- **Project pages** have no scripts and fetch nothing: fonts and pictures are inside the zip.
- Tokens: viewer and helper tokens are stored as SHA-256 hashes and shown once.

## Building the image

`docker compose up --build` downloads Ubuntu's packages, Python packages and SolidCraft's
release (from GitHub, checked against a pinned SHA-256). That happens at build time only.

## This site

sklent.app is static pages on GitHub Pages with self-hosted fonts: it sets no cookies and
makes no request to any other site.
