"""`sklent serve` runs the app; `sklent render FILE OUT_DIR` renders one local design."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sklent")
    sub = p.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the web app, API, MCP endpoint and worker")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    one = sub.add_parser("render", help="render one local design file (no database, no Kist)")
    one.add_argument("design", type=Path)
    one.add_argument("out_dir", type=Path)
    one.add_argument("--palette", default="cool-grey")
    one.add_argument("--seconds", type=float, default=8.0)
    one.add_argument("--processes", type=int, default=None,
                     help="most SolidCraft processes for frames (default: SK_RENDER_PROCESSES)")
    one.add_argument("--settings", type=json.loads, default=None,
                     help='feature settings as JSON, e.g. \'{"specs_assembly": true}\'')
    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("sklent.app:app", host=args.host, port=args.port, proxy_headers=True)
        return 0

    from . import features
    from .render import RenderOptions, render_set
    features.load()
    opts = RenderOptions(palette=args.palette, seconds=args.seconds)
    stem = args.design.stem
    outputs, report = render_set(args.design.resolve(), args.out_dir.resolve(), stem, opts,
                                 lambda f, m: print(f"{f:4.0%} {m}", file=sys.stderr),
                                 processes=args.processes,
                                 settings={**asdict(opts), **args.settings} if args.settings else None)
    print(json.dumps({"outputs": [asdict(o) for o in outputs], "report": report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
