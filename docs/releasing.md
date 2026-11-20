# Releasing

1. Move the **Unreleased** notes in `CHANGELOG.md` under a new
   `## [X.Y.Z] - YYYY-MM-DD` heading.
2. Set the version in `pyproject.toml` and `sklent/__init__.py`, and
   `extra.version_label` in `site/mkdocs.yml` (the docs footer's title block shows it).
3. Commit, run the tests (`pytest`), tag and push the tag:

   ```bash
   git tag -a vX.Y.Z -m "Sklent X.Y.Z"
   git push origin vX.Y.Z
   ```

## Docs site (sklent.app)

The docs site is built from `docs/` by `site/mkdocs.yml` (MkDocs with Material for MkDocs,
pinned in `site/requirements.txt`) and published to GitHub Pages at **https://sklent.app**.
Publishing is manual.

Check the build locally first; `--strict` turns any broken link or missing file into an error:

```bash
uvx --with-requirements site/requirements.txt mkdocs build --strict -f site/mkdocs.yml
uvx --with-requirements site/requirements.txt mkdocs serve -f site/mkdocs.yml   # http://127.0.0.1:8000
```

The output goes to `site/_build/`, which git ignores.

To publish: **Actions → Docs site → Run workflow** on `main`, with **deploy** ticked
(`.github/workflows/docs.yml`). Without the tick it only builds, which is a safe check of a
branch. The workflow runs the same strict build and deploys with GitHub's Pages actions.

One-time setup (first publish):

1. **Settings → Pages → Source: GitHub Actions**.
2. Custom domain `sklent.app`. At the DNS host, point the apex at GitHub Pages (the four `A`
   records and four `AAAA` records in GitHub's Pages docs) and keep the records **DNS-only**
   (not proxied), so GitHub can issue the certificate.
3. Tick **Enforce HTTPS** once the certificate is issued.

## Screenshots and example outputs

Shoot them only on an instance that holds public designs (the current ones are from
[tangency-labs/solidcraft](credits.md), Apache-2.0), never on one with private work. Before each
shot, hide anything that names a machine, an address, a path or a token (the tooltip of
the chip that shows the connected [Kist](https://kist.pictures) library, the job log's helper names, the title block's **Rendered on** cell, URL fields).

- Screenshots: WebP (quality about 85) in `docs/assets/screenshots/`, desktop 1440×900 in
  gallery grey, dark and light, and the phone at 390×844 with touch emulation.
- Example outputs: real render outputs, converted to WebP in `docs/assets/outputs/`; the
  turntable GIF stays under about 4 MB. If an output can't be shown with the example designs
  (an exploded view needs a design with two or more components), say so rather than mock one.
- Keep all docs media together under about 15 MB, and update `credits.md` if the designs
  change.

The social preview (`docs/brand/social-preview.png`, 1280×640, also the repo's GitHub social
preview) is rebuilt with `python docs/brand/build_social.py` (needs Pillow and fontTools).
