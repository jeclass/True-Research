"""Verify a local Anthropic-compatible endpoint (e.g. Ollama >= 0.14) against
the engine's EXACT session plumbing. Run this on the machine that hosts the
local model — the remote build container cannot reach model-weight hosts.

    .venv/bin/python scripts/check_local_backend.py --model qwen3:4b-instruct-2507-q4_K_M

Checks, in order:
1. endpoint liveness (GET base_url)
2. a reader-shaped session via prompted-JSON (the engine's production path
   for non-first-party endpoints) — validates JSON compliance of the model.
   The session is routed THROUGH a recording proxy so the Authorization
   header is observable: if anything other than the configured bearer
   placeholder arrives (e.g. an sk-ant-* token from an ambient Claude Code
   login), the check FAILS — that would mean real Anthropic credentials are
   leaking to the local endpoint. Verified necessary: host-broker
   environments can override injected auth (docs/SDK_NOTES.md).
3. ledger attribution: endpoint name + usd == 0

Exit code 0 only if all hold.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from src.ledger import Ledger  # noqa: E402
from src.runspace import Runspace  # noqa: E402
from src.sessions.base import SessionError, run_role_session  # noqa: E402
from src.sessions.reader import ReaderOutput  # noqa: E402
from src.settings import load_settings  # noqa: E402


class _RecordingProxy:
    """Forwards requests to the real local endpoint, recording auth headers."""

    def __init__(self, upstream: str) -> None:
        self.auth_seen: list[str] = []
        auth_seen = self.auth_seen

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                auth_seen.append(self.headers.get("authorization") or "(none)")
                length = int(self.headers.get("content-length", "0"))
                body = self.rfile.read(length)
                try:
                    upstream_resp = httpx.post(
                        upstream + self.path,
                        content=body,
                        headers={
                            k: v
                            for k, v in self.headers.items()
                            if k.lower() in ("content-type", "authorization", "anthropic-version", "x-api-key", "accept")
                        },
                        timeout=600,
                    )
                except httpx.HTTPError as exc:
                    self.send_response(502)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(exc)}).encode())
                    return
                self.send_response(upstream_resp.status_code)
                for k, v in upstream_resp.headers.items():
                    if k.lower() in ("content-type",):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(upstream_resp.content)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

_PAGE = """\
Intermittent fasting trial results, Example Journal 2024.
A 12-month randomized controlled trial (n=244) found alternate-day fasting
produced 6.0 kg mean weight loss versus 5.3 kg for daily calorie restriction
(difference 0.7 kg, 95% CI -0.7 to 2.1, p=0.31). Dropout was 38% vs 29%.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="local model id, e.g. qwen3:4b-instruct-2507-q4_K_M")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    print(f"[1/4] endpoint liveness: {args.base_url}")
    try:
        httpx.get(args.base_url, timeout=10)
    except httpx.HTTPError as exc:
        print(f"  FAIL: {exc}")
        return 1
    print("  OK")

    proxy = _RecordingProxy(upstream=args.base_url)
    settings = load_settings(config_path=args.config)
    raw = settings.model_dump()
    raw["secrets"] = {"OLLAMA_AUTH": "ollama", **{
        k: v.get_secret_value() for k, v in settings.secrets.items()
    }}
    raw["endpoints"]["local"]["base_url"] = proxy.base_url  # observe the wire
    raw["roles"]["reader_subagent"] = {
        "endpoint": "local", "model": args.model, "max_turns": 4,
    }
    from src.settings import Settings

    settings = Settings.model_validate(raw)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            run = Runspace.create(Path(tmp) / "runs", "local backend check", "general")
            ledger = Ledger(run)
            prompt = (
                "Research question: does intermittent fasting beat daily calorie "
                "restriction for weight loss?\n\nPage text:\n" + _PAGE
            )

            print(f"[2/4] reader session via prompted JSON ({args.model})")
            try:
                spawn = run_role_session(
                    run=run, settings=settings, ledger=ledger, cycle=0,
                    session_type="reader", role="reader_subagent",
                    system_prompt="You summarize one page for a research engine. No tools.",
                    user_prompt=prompt, tools=[], output_model=ReaderOutput,
                )
                out: ReaderOutput = spawn.structured
                print(f"  OK: useful={out.useful} credibility={out.credibility} "
                      f"title={out.title!r}")
                print(f"  tokens in/out: {spawn.input_tokens}/{spawn.output_tokens}, "
                      f"wall {spawn.wall_seconds:.1f}s")
            except SessionError as exc:
                print(f"  FAIL: {exc}")
                print("  -> this model is unsuitable for the reader role (§1).")
                run.release_lock()
                return 1

            print("[3/4] auth isolation on the wire")
            bad = [
                a for a in proxy.auth_seen
                if a != "Bearer ollama"
            ]
            for a in set(proxy.auth_seen):
                shown = a if not a.startswith("Bearer sk-") else "Bearer sk-…REDACTED"
                print(f"  saw Authorization: {shown}")
            if bad:
                print(
                    "  FAIL: a credential other than the configured placeholder "
                    "reached the local endpoint. If you are logged into Claude "
                    "Code on this machine, real Anthropic credentials are "
                    "LEAKING to the local server — do not run hybrid here "
                    "until resolved."
                )
                run.release_lock()
                return 1
            print("  OK: only the configured placeholder bearer reached the endpoint")

            print("[4/4] ledger attribution")
            entries = ledger.entries
            local_entries = [e for e in entries if e.endpoint == "local"]
            ok = bool(local_entries) and all(e.usd == 0.0 for e in local_entries)
            for e in local_entries:
                print(f"  {e.session_type} model={e.model} endpoint={e.endpoint} "
                      f"usd={e.usd} tokens={e.input_tokens}/{e.output_tokens}")
            run.release_lock()
            if not ok:
                print("  FAIL: expected local entries with usd=0")
                return 1
            print("  OK")
    finally:
        proxy.shutdown()
    print("\nLOCAL BACKEND CHECK PASSED — reader role can run on this endpoint.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
