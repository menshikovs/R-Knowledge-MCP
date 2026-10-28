"""Local mock model endpoint for Stage 2.6 infrastructure tests (no real model, no network).

Speaks plain HTTP on port 8443 behind the egress gateway, which tunnels
``api.openai.com:443`` to this server. It requires the per-trial synthetic bearer token and logs
only metadata (never the token, headers or request body).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8443
EXPECTED = os.environ.get("MOCK_MODEL_TOKEN", "")


def _log(**fields) -> None:
    fields["ts"] = time.time()
    print(json.dumps(fields, sort_keys=True), file=sys.stderr, flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args) -> None:  # silence default access log (it may echo paths)
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(length, 1 << 20))
        supplied = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        auth_ok = bool(EXPECTED) and hmac.compare_digest(supplied, EXPECTED)
        _log(
            event="model_request",
            path=self.path[:64],
            host=(self.headers.get("Host") or "")[:64],
            auth_ok=auth_ok,
            body_bytes=len(body),
            body_sha256=hashlib.sha256(body).hexdigest(),
        )
        if not auth_ok or self.path != "/v1/responses":
            payload, status = {"error": "unauthorized_or_unknown"}, 401 if not auth_ok else 404
        else:
            payload, status = (
                {
                    "id": "mock-response",
                    "output_text": "mock model reply",
                    "usage": {"input_tokens": 1000 + len(body), "output_tokens": 42},
                },
                200,
            )
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    _log(event="startup", result="ready")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
