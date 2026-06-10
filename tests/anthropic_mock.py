"""Minimal Anthropic-Messages-API mock (SSE) used to verify the engine's
non-first-party endpoint path end-to-end: per-session env injection, Bearer
auth, model routing, prompted-JSON parsing, and usd=0 ledger attribution.
This is a TEST FIXTURE standing in for a local Ollama server's wire format —
it proves routing/plumbing, not model quality."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Recorded:
    requests: list[dict] = field(default_factory=list)


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class MockAnthropicServer:
    """Serves POST /v1/messages with a canned streamed text response."""

    def __init__(self, reply_text: str) -> None:
        self.recorded = Recorded()
        reply = reply_text
        recorded = self.recorded

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # silence test output
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                recorded.requests.append(
                    {
                        "path": self.path,
                        "model": body.get("model"),
                        "stream": body.get("stream"),
                        "authorization": self.headers.get("authorization"),
                        "x_api_key": self.headers.get("x-api-key"),
                    }
                )
                if not self.path.startswith("/v1/messages"):
                    self.send_response(404)
                    self.end_headers()
                    return
                model = body.get("model", "mock-model")
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                usage = {
                    "input_tokens": 42,
                    "output_tokens": 7,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                }
                self.wfile.write(
                    _sse(
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {
                                "id": "msg_mock",
                                "type": "message",
                                "role": "assistant",
                                "model": model,
                                "content": [],
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": usage,
                            },
                        },
                    )
                )
                self.wfile.write(
                    _sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                )
                self.wfile.write(
                    _sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": reply},
                        },
                    )
                )
                self.wfile.write(
                    _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
                )
                self.wfile.write(
                    _sse(
                        "message_delta",
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                            "usage": {"output_tokens": 120},
                        },
                    )
                )
                self.wfile.write(_sse("message_stop", {"type": "message_stop"}))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "MockAnthropicServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
