#!/usr/bin/env python3
"""Refresh Sklent's pinned copy of Kist's design tokens.

    python scripts/sync_kist_tokens.py <kist checkout>          # rewrite the copy
    python scripts/sync_kist_tokens.py <kist checkout> --check  # exit 1 if it differs

Kist is the source of truth for the suite's colours, type scale, motion and control
sizes. Sklent has no build step and must run without Kist, so it ships a verbatim copy:
`sklent/web/css/kist-tokens.css` holds Kist's `web/src/styles.css` :root scale (from
its first `:root {` up to the first rule that isn't a token block) followed by
`web/src/themes.css`, byte for byte, under a header naming the Kist tag and commit.
`kist-tokens.lock.json` next to it pins that file's sha256; tests/test_tokens.py
fails when the two disagree, so the copy is never edited by hand.

Point it at a local Kist checkout at the tag you want (no network needed). It prints
the token names added and removed, so a bump is a deliberate, reviewable diff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sklent" / "web" / "css" / "kist-tokens.css"
LOCK = OUT.with_name("kist-tokens.lock.json")


def _git(kist: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(kist), *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def kist_version(kist: Path) -> tuple[str, str]:
    """(tag or version, short commit) of the checkout."""
    tag = _git(kist, "describe", "--tags", "--exact-match") or _git(kist, "describe", "--tags")
    if not tag:
        m = re.search(r'^version\s*=\s*"([^"]+)"', (kist / "pyproject.toml").read_text(), re.M) \
            if (kist / "pyproject.toml").is_file() else None
        tag = f"v{m.group(1)}" if m else "unknown"
    return tag, _git(kist, "rev-parse", "--short=12", "HEAD") or "unknown"


def scale_block(styles_css: str) -> str:
    """Kist's styles.css token blocks: the first `:root {` through the last token-only
    block before the first ordinary rule (`* {`)."""
    start = styles_css.index(":root {")
    end = styles_css.index("\n* {", start)
    return styles_css[start:end].rstrip() + "\n"


def build(kist: Path) -> tuple[str, dict]:
    src = kist / "web" / "src"
    styles, themes = (src / "styles.css").read_text(), (src / "themes.css").read_text()
    tag, commit = kist_version(kist)
    header = (
        "/* kist-tokens.css: GENERATED, do not edit. Run scripts/sync_kist_tokens.py <kist checkout>.\n"
        f" * From Kist {tag} ({commit}), verbatim: web/src/styles.css's :root scale, then\n"
        " * web/src/themes.css (contrast-checked in Kist and again in tests/test_contrast.py).\n"
        " * Sklent's own tokens are --sk-* in sk-tokens.css, built only from these. */\n\n"
    )
    body = (header + "/* ---- web/src/styles.css :root scale ---- */\n" + scale_block(styles)
            + "\n/* ---- web/src/themes.css ---- */\n" + themes)
    lock = {"kist_tag": tag, "kist_commit": commit,
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "files": ["web/src/styles.css (:root scale)", "web/src/themes.css"]}
    return body, lock


def names(css: str) -> set[str]:
    return set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.M))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("kist", type=Path, help="a Kist checkout (the tag you want checked out)")
    p.add_argument("--check", action="store_true", help="only report whether the copy differs")
    args = p.parse_args(argv)
    if not (args.kist / "web" / "src" / "themes.css").is_file():
        p.error(f"{args.kist} is not a Kist checkout (no web/src/themes.css)")
    body, lock = build(args.kist)
    old = OUT.read_text() if OUT.is_file() else ""
    added, removed = sorted(names(body) - names(old)), sorted(names(old) - names(body))
    same = old == body
    print(f"Kist {lock['kist_tag']} ({lock['kist_commit']}): "
          + ("unchanged" if same else f"{len(added)} token(s) added, {len(removed)} removed"))
    for n in added:
        print(f"  + {n}")
    for n in removed:
        print(f"  - {n}")
    if args.check:
        return 0 if same else 1
    OUT.write_text(body)
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} and {LOCK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
