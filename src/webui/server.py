"""`true-research ui` — serve the local web UI (localhost single-operator tool).

No auth by design: the app is a read-only window over runs/ plus a launch
endpoint, a key-write endpoint, and a distill endpoint (all three
origin-checked against localhost), intended strictly for 127.0.0.1. Binding
to a non-loopback host prints a loud warning (the UI would be open to the
network with no auth).
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="true-research ui", description="Serve the local True Research web UI."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--no-browser", action="store_true",
                        help="don't auto-open the browser")
    args = parser.parse_args(argv)

    import uvicorn

    from src.webui.app import create_app

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"WARNING: binding to {args.host} exposes the UI (which has NO auth) "
            "beyond this machine. Intended use is localhost only.",
            file=sys.stderr,
        )
    app = create_app(runs_dir=Path(args.runs_dir))
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        webbrowser.open(url)
    print(f"True Research UI: {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
