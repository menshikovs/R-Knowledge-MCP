"""Fail-closed CONNECT-only egress gateway for one Stage 2.6 trial topology.

Runs inside a container (standard library only). The policy is an exact allow-list that maps a
client-requested ``host:port`` authority to a fixed upstream ``host:port``. The client never
chooses the upstream address: anything not listed is refused with HTTP 403, including IP
literals, non-CONNECT methods, malformed authorities and the MCP/model upstream names.

Logs are one JSON object per line on stderr. They contain the requested authority and the
decision only: never headers, bodies, credentials or tunnel payload.
"""

from __future__ import annotations

import ipaddress
import json
import os
import select
import socket
import socketserver
import sys
import threading
import time

LISTEN_PORT = 3128
MAX_HEADER_BYTES = 16 * 1024
MAX_TUNNEL_BYTES = 64 * 1024 * 1024
MAX_TUNNEL_SECONDS = 300
CONNECT_TIMEOUT_SECONDS = 5
MAX_CONCURRENT_TUNNELS = 8


class PolicyError(ValueError):
    """The gateway policy is missing or malformed; the process must not start."""


class Denied(ValueError):
    """A request does not satisfy the policy."""


def _split_authority(authority: str) -> tuple[str, int]:
    if not isinstance(authority, str) or not authority or len(authority) > 300:
        raise Denied("invalid_authority")
    if authority.count(":") != 1 or any(c in authority for c in "@/?#\\ \t\r\n[]"):
        raise Denied("invalid_authority")
    host, raw_port = authority.rsplit(":", 1)
    if not host or not raw_port.isascii() or not raw_port.isdecimal():
        raise Denied("invalid_authority")
    port = int(raw_port)
    if not 0 < port < 65536:
        raise Denied("invalid_authority")
    return host.rstrip(".").lower(), port


def load_policy(raw: str | None) -> dict[str, tuple[str, int]]:
    """Parse ``{"allow": {"host:port": "upstream:port"}}``; raise PolicyError otherwise."""
    if not raw:
        raise PolicyError("policy_missing")
    try:
        data = json.loads(raw)
        allow = data["allow"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PolicyError("policy_unparseable") from exc
    if not isinstance(allow, dict) or not allow:
        raise PolicyError("policy_empty")
    table: dict[str, tuple[str, int]] = {}
    for key, value in allow.items():
        try:
            host, port = _split_authority(key)
            upstream = _split_authority(value)
        except Denied as exc:
            raise PolicyError("policy_entry_invalid") from exc
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise PolicyError("policy_ip_literal_key")
        table[f"{host}:{port}"] = upstream
    return table


def decide(request_line: str, policy: dict[str, tuple[str, int]]) -> tuple[str, tuple[str, int]]:
    """Return (authority, upstream) for an allowed request or raise Denied(reason)."""
    parts = request_line.split(" ")
    if len(parts) != 3 or parts[2] not in {"HTTP/1.0", "HTTP/1.1"}:
        raise Denied("malformed_request")
    if parts[0] != "CONNECT":
        raise Denied("connect_only")
    host, port = _split_authority(parts[1])
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise Denied("ip_literal_denied")
    authority = f"{host}:{port}"
    upstream = policy.get(authority)
    if upstream is None:
        raise Denied("authority_not_allowed")
    return authority, upstream


def _log(**fields) -> None:
    fields["ts"] = time.time()
    print(json.dumps(fields, sort_keys=True), file=sys.stderr, flush=True)


def _status(client: socket.socket, code: int, phrase: str) -> None:
    try:
        client.sendall(f"HTTP/1.1 {code} {phrase}\r\nConnection: close\r\n\r\n".encode())
    except OSError:
        pass


class Handler(socketserver.BaseRequestHandler):
    policy: dict[str, tuple[str, int]] = {}

    def handle(self) -> None:
        client: socket.socket = self.request
        upstream: socket.socket | None = None
        requested = "-"
        try:
            client.settimeout(3)
            header = bytearray()
            while b"\r\n\r\n" not in header:
                chunk = client.recv(2048)
                if not chunk:
                    raise Denied("incomplete_request")
                header.extend(chunk)
                if len(header) > MAX_HEADER_BYTES:
                    raise Denied("header_too_large")
            line = bytes(header).split(b"\r\n", 1)[0].decode("ascii", "replace")
            requested = line.split(" ")[1][:120] if line.count(" ") >= 1 else "-"
            authority, target = decide(line, self.policy)
            try:
                upstream = socket.create_connection(target, timeout=CONNECT_TIMEOUT_SECONDS)
            except OSError:
                _status(client, 502, "Bad Gateway")
                _log(event="connect", authority=authority, result="error", reason="upstream_failed")
                return
            _status(client, 200, "Connection Established")
            _log(event="connect", authority=authority, result="allowed", reason="allow_listed")
            client.settimeout(None)
            upstream.settimeout(None)
            sent = self._tunnel(client, upstream)
            _log(event="closed", authority=authority, bytes=sent)
        except Denied as exc:
            _status(client, 403, "Forbidden")
            _log(event="connect", authority=requested, result="denied", reason=str(exc))
        except OSError:
            _log(event="connect", authority=requested, result="error", reason="io_error")
        finally:
            if upstream is not None:
                upstream.close()

    @staticmethod
    def _tunnel(left: socket.socket, right: socket.socket) -> int:
        deadline = time.monotonic() + MAX_TUNNEL_SECONDS
        moved = 0
        while time.monotonic() < deadline and moved < MAX_TUNNEL_BYTES:
            readable, _, _ = select.select((left, right), (), (), 0.5)
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return moved
                (right if source is left else left).sendall(data)
                moved += len(data)
        return moved


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler):
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_TUNNELS)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            _status(request, 503, "Busy")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def main() -> int:
    try:
        policy = load_policy(os.environ.get("RKMCP_GATEWAY_POLICY"))
    except PolicyError as exc:
        # Fail closed: without a valid policy there is no gateway at all.
        _log(event="startup", result="refused", reason=str(exc))
        return 2
    Handler.policy = policy
    _log(event="startup", result="ready", allowed=sorted(policy))
    with Server(("0.0.0.0", LISTEN_PORT), Handler) as server:
        server.serve_forever(poll_interval=0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
