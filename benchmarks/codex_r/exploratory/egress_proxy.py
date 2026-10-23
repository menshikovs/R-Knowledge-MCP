"""Restricted CONNECT-only egress gateway for the self-hosted executor.

This is a TCP tunnel, not a TLS-intercepting proxy or a Managed Agents relay.
It accepts only HTTPS CONNECT requests to the two documented OpenAI hosts.
"""

from __future__ import annotations

import ipaddress
import select
import socket
import socketserver
import sys
import threading
import time

ALLOWED_HOSTS = frozenset({"api.openai.com", "codex-cloud-environments.chatgpt.com"})
PORT = 3128
MAX_HEADER_BYTES = 16 * 1024
MAX_TUNNEL_BYTES = 128 * 1024 * 1024
MAX_TUNNEL_SECONDS = 960
CONNECT_TIMEOUT_SECONDS = 8
MAX_CONCURRENT_TUNNELS = 4


class ProxyError(ValueError):
    """A request does not satisfy the fixed egress policy."""


def parse_connect_authority(authority: str) -> tuple[str, int]:
    """Parse a CONNECT authority without accepting userinfo, IPs, or extra syntax."""
    if not isinstance(authority, str) or len(authority) > 300:
        raise ProxyError("invalid_authority")
    if authority.count(":") != 1 or any(char in authority for char in "@/?#\\\\ \t\r\n"):
        raise ProxyError("invalid_authority")
    host, raw_port = authority.rsplit(":", 1)
    if not host or not raw_port.isascii() or not raw_port.isdecimal():
        raise ProxyError("invalid_authority")
    host = host.rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ProxyError("ip_literal_denied")
    if host not in ALLOWED_HOSTS:
        raise ProxyError("host_denied")
    port = int(raw_port)
    if port != 443:
        raise ProxyError("port_denied")
    return host, port


def resolve_public_addresses(host: str, port: int) -> list[tuple[int, tuple]]:
    """Resolve once and reject any non-public answer before opening a tunnel."""
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProxyError("dns_failed") from exc
    addresses: list[tuple[int, tuple]] = []
    seen: set[tuple[int, str]] = set()
    for family, _socktype, _protocol, _canonical, sockaddr in records:
        address = ipaddress.ip_address(sockaddr[0])
        if not address.is_global:
            raise ProxyError("non_public_dns_answer")
        key = (family, str(address))
        if key not in seen:
            seen.add(key)
            addresses.append((family, sockaddr))
    if not addresses:
        raise ProxyError("dns_empty")
    return addresses


def _write_status(client: socket.socket, status: int, phrase: str) -> None:
    try:
        client.sendall(f"HTTP/1.1 {status} {phrase}\r\nConnection: close\r\n\r\n".encode())
    except OSError:
        pass


class ProxyHandler(socketserver.BaseRequestHandler):
    """Handle one bounded CONNECT tunnel and emit metadata-only logs."""

    def handle(self) -> None:
        client: socket.socket = self.request
        upstream: socket.socket | None = None
        try:
            client.settimeout(2)
            header = bytearray()
            while b"\r\n\r\n" not in header:
                chunk = client.recv(min(2048, MAX_HEADER_BYTES + 1 - len(header)))
                if not chunk:
                    raise ProxyError("incomplete_request")
                header.extend(chunk)
                if len(header) > MAX_HEADER_BYTES:
                    raise ProxyError("header_too_large")
            request_line = bytes(header).split(b"\r\n", 1)[0].decode("ascii", "strict")
            parts = request_line.split(" ")
            if (
                len(parts) != 3
                or parts[0] != "CONNECT"
                or parts[2]
                not in {
                    "HTTP/1.0",
                    "HTTP/1.1",
                }
            ):
                raise ProxyError("connect_only")
            host, port = parse_connect_authority(parts[1])
            error: ProxyError | None = None
            for family, sockaddr in resolve_public_addresses(host, port):
                try:
                    upstream = socket.socket(family, socket.SOCK_STREAM)
                    upstream.settimeout(CONNECT_TIMEOUT_SECONDS)
                    upstream.connect(sockaddr)
                    break
                except OSError:
                    if upstream is not None:
                        upstream.close()
                        upstream = None
                    error = ProxyError("upstream_unavailable")
            if upstream is None:
                raise error or ProxyError("upstream_unavailable")
            _write_status(client, 200, "Connection Established")
            client.settimeout(None)
            upstream.settimeout(None)
            self._tunnel(client, upstream)
            self._log("closed", host)
        except (ProxyError, UnicodeError, OSError) as exc:
            status = 403 if isinstance(exc, ProxyError) else 400
            phrase = "Forbidden" if status == 403 else "Bad Request"
            _write_status(client, status, phrase)
            reason = str(exc) if isinstance(exc, ProxyError) else "malformed_request"
            self._log(reason, "")
        finally:
            if upstream is not None:
                upstream.close()

    @staticmethod
    def _tunnel(left: socket.socket, right: socket.socket) -> None:
        deadline = time.monotonic() + MAX_TUNNEL_SECONDS
        transferred = 0
        sockets = (left, right)
        while time.monotonic() < deadline and transferred < MAX_TUNNEL_BYTES:
            readable, _, _ = select.select(sockets, (), (), 0.5)
            if not readable:
                continue
            for source in readable:
                chunk = source.recv(min(64 * 1024, MAX_TUNNEL_BYTES - transferred))
                if not chunk:
                    return
                target = right if source is left else left
                target.sendall(chunk)
                transferred += len(chunk)

    def _log(self, result: str, host: str) -> None:
        # Deliberately omit request headers, URLs, query values and credentials.
        print(f"egress result={result} destination={host or '-'}", file=sys.stderr, flush=True)


class ThreadedProxy(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int]):
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_TUNNELS)
        super().__init__(address, ProxyHandler)

    def process_request(self, request: socket.socket, client_address: tuple) -> None:
        if not self._slots.acquire(blocking=False):
            _write_status(request, 503, "Busy")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: tuple) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def main() -> None:
    with ThreadedProxy(("0.0.0.0", PORT)) as proxy:
        proxy.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
