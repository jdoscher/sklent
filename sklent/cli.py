"""`sklent serve` runs the app; `sklent render FILE OUT_DIR` renders one local design;
`sklent token create|list|revoke` manages viewer and helper tokens; `sklent helper` renders
for a Sklent server from this machine."""

import argparse
import json
import os
import sys
from dataclasses import asdict, fields
from pathlib import Path


def _render(args) -> int:
    from . import features
    from .render import RenderOptions, render_set
    from .sources import design_format

    features.load()
    if design_format(args.design.name) is None:
        print(f"sklent: {args.design.name} is not a design file (.sc, .solidcraft, .step, .stp, .stl, .3mf)",
              file=sys.stderr)
        return 2
    # precedence: defaults < .sklent.yaml < --palette/--seconds < --settings
    settings: dict = {}
    config: dict = {}
    if args.config != "none":
        from .repo_config import for_local, parse, resolve

        if args.config == "auto":
            config = for_local(args.design)
        else:
            data, errors = parse(Path(args.config).read_bytes())
            config = resolve(args.design.name, {".sklent.yaml": {"data": data, "errors": errors, "blob": None}})
        for e in config.get("errors") or []:
            print(f"sklent: .sklent.yaml: {e}", file=sys.stderr)
        settings.update(config.get("settings") or {})
    if args.palette is not None:
        settings["palette"] = args.palette
    if args.seconds is not None:
        settings["seconds"] = args.seconds
    if args.settings:
        try:
            extra = json.loads(args.settings)
        except ValueError as exc:
            print(f"sklent: --settings is not JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(extra, dict):
            print("sklent: --settings must be a JSON object", file=sys.stderr)
            return 2
        from .jobs import _EXTRA

        for k, v in extra.items():  # feature settings go through their validators
            settings[k] = _EXTRA[k][1](v) if k in _EXTRA and _EXTRA[k][1] else v
    if args.outputs is not None:  # views (F17): which core outputs; '' = quick check
        settings["outputs"] = [o.strip() for o in args.outputs.split(",") if o.strip()]
    if args.highlight:  # views (F20)
        settings["views_highlight_names"] = [n.strip() for n in args.highlight.split(",") if n.strip()]
    known = {f.name for f in fields(RenderOptions)}
    opts = RenderOptions(**{k: v for k, v in settings.items() if k in known})
    design = args.design.resolve()
    if config.get("up") and design_format(design.name) == "step":
        design.with_name(design.name + ".sklent.json").write_text(json.dumps({"up": config["up"]}))
    outputs, report = render_set(design, args.out_dir.resolve(), args.design.stem, opts,
                                 lambda f, m: print(f"{f:4.0%} {m}", file=sys.stderr),
                                 processes=args.processes, settings={**asdict(opts), **settings},
                                 **({"renderer": args.renderer} if args.renderer != "gpu" else {}))
    from .features.inputs.links import report_for

    report["inputs"] = report_for(design)
    if config:
        report["config"] = {k: v for k, v in config.items() if k != "included"}
    print(json.dumps({"outputs": [asdict(o) for o in outputs], "report": report}, indent=2))
    return 0


def _token(args) -> int:
    from . import db
    from .features.inputs import tokens

    db.init()
    if args.action == "create":
        t = tokens.create(args.name, args.scope)
        if args.scope == "helper":
            print(f"Helper token \u201c{t['name']}\u201d (shown once; it can only claim and report render jobs):",
                  file=sys.stderr)
        else:
            print(f"Viewer token \u201c{t['name']}\u201d (shown once; it can browse, view and download, nothing else):",
                  file=sys.stderr)
        print(t["token"])
    elif args.action == "list":
        for t in tokens.list_tokens():
            state = f"revoked {t['revoked_at']}" if t["revoked_at"] else f"last used {t['last_used_at'] or 'never'}"
            print(f"{t['id']}  {t['hint']}  {t.get('scope') or 'viewer':6}  {t['name']}  ({state})")
    else:
        try:
            t = tokens.revoke(args.id)
        except KeyError as exc:
            print(f"sklent: {exc.args[0]}", file=sys.stderr)
            return 1
        print(f"revoked {t['name']}" if t["changed"] else f"{t['name']} was already revoked")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sklent")
    sub = p.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the web app, API, MCP endpoint and worker")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    one = sub.add_parser("render", help="render one local design file (no database, no Kist): .sc, .solidcraft, "
                                        ".step/.stp, .stl or .3mf")
    one.add_argument("design", type=Path)
    one.add_argument("out_dir", type=Path)
    one.add_argument("--palette", default=None, help="cool-grey (default) or white")
    one.add_argument("--seconds", type=float, default=None, help="turntable length (default 8)")
    one.add_argument("--processes", type=int, default=None,
                     help="most SolidCraft processes for frames (default: SK_RENDER_PROCESSES)")
    one.add_argument("--outputs", default=None,
                     help="comma-separated core outputs (1080p,reel,discord,gif,social,hires); '' = quick check")
    one.add_argument("--highlight", default=None,
                     help="comma-separated body names or globs to render solid, the rest x-ray")
    one.add_argument("--settings", default=None,
                     help="render and feature settings as JSON, e.g. "
                          '\'{"styles": ["shaded"], "views_exploded": true}\'')
    one.add_argument("--renderer", choices=["gpu", "software"],
                     default="software" if (os.environ.get("SK_RENDERER") or "").lower() == "software" else "gpu",
                     help="gpu (default) or software: Mesa lavapipe on the CPU, no GPU (SK_RENDERER)")
    one.add_argument("--config", default="auto",
                     help="a .sklent.yaml to apply; auto (default) reads those in the folders above the design "
                          "(up to the git root), none skips them")
    tok = sub.add_parser("token", help="viewer and helper tokens (in SK_DATA_DIR's database)")
    tsub = tok.add_subparsers(dest="action", required=True)
    mk = tsub.add_parser("create", help="make a viewer token, or a helper token with --scope helper (printed once)")
    mk.add_argument("name")
    mk.add_argument("--scope", choices=["viewer", "helper"], default="viewer")
    tsub.add_parser("list", help="list viewer tokens")
    tsub.add_parser("revoke", help="revoke a token by id").add_argument("id")
    env = os.environ.get
    hp = sub.add_parser("helper", help="render for a Sklent server from this machine (no database needed)")
    hp.add_argument("--url", default=env("SK_HELPER_URL"),
                    help="the server, e.g. http://sklent-host:8090 (SK_HELPER_URL)")
    hp.add_argument("--token-file", default=env("SK_HELPER_TOKEN_FILE"),
                    help="file holding a helper token (else SK_HELPER_TOKEN)")
    hp.add_argument("--name", default=env("SK_HELPER_NAME"),
                    help="this helper's name in the server's list (SK_HELPER_NAME)")
    hp.add_argument("--renderer", choices=["gpu", "software"], default=(env("SK_RENDERER") or "gpu").lower()
                    if (env("SK_RENDERER") or "gpu").lower() in ("gpu", "software") else "gpu",
                    help="gpu (default) or software (Mesa lavapipe on the CPU) (SK_RENDERER)")
    hp.add_argument("--processes", type=int, default=None,
                    help="most SolidCraft processes for one design's frames (default SK_RENDER_PROCESSES)")
    hp.add_argument("--max-bodies", type=int, default=None,
                    help="skip designs whose last render had more bodies than this")
    hp.add_argument("--once", action="store_true", help="render at most one job, then exit")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("sklent.app:app", host=args.host, port=args.port, proxy_headers=True)
        return 0
    if args.cmd == "token":
        return _token(args)
    if args.cmd == "helper":
        return _helper(args)
    return _render(args)


def _helper(args) -> int:
    from .features.helpers import client

    token = client.read_token(args.token_file)
    missing = [n for n, v in (("--url (SK_HELPER_URL)", args.url), ("--name (SK_HELPER_NAME)", args.name),
                              ("a token (--token-file or SK_HELPER_TOKEN)", token)) if not v]
    if missing:
        print(f"sklent helper: needs {', '.join(missing)}", file=sys.stderr)
        return 2
    return client.main(args.url, token, args.name, args.renderer, args.processes, args.once, args.max_bodies)


if __name__ == "__main__":
    raise SystemExit(main())
