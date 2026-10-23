import importlib.util
import socket
import socketserver
import threading

import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "codex_egress_proxy", ROOT / "benchmarks/codex_r/exploratory/egress_proxy.py"
)
assert SPEC is not None and SPEC.loader is not None
proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proxy)


@pytest.mark.parametrize(
    "authority, expected",
    [
        ("api.openai.com:443", ("api.openai.com", 443)),
        (
            "CODEx-cloud-environments.chatgpt.com.:443",
            ("codex-cloud-environments.chatgpt.com", 443),
        ),
    ],
)
def test_connect_authority_accepts_only_documented_hosts(authority, expected):
    assert proxy.parse_connect_authority(authority) == expected


@pytest.mark.parametrize(
    "authority, reason",
    [
        ("example.com:443", "host_denied"),
        ("93.184.216.34:443", "ip_literal_denied"),
        ("api.openai.com:80", "port_denied"),
        ("user@api.openai.com:443", "invalid_authority"),
        ("api.openai.com:443/path", "invalid_authority"),
        ("api.openai.com:443:444", "invalid_authority"),
    ],
)
def test_connect_authority_rejects_general_proxy_targets(authority, reason):
    with pytest.raises(proxy.ProxyError, match=reason):
        proxy.parse_connect_authority(authority)


def test_dns_resolution_rejects_private_or_mixed_answers(monkeypatch):
    monkeypatch.setattr(
        proxy.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.9", 443))
        ],
    )
    # TEST-NET is deliberately non-global and cannot be an upstream target.
    with pytest.raises(proxy.ProxyError, match="non_public_dns_answer"):
        proxy.resolve_public_addresses("api.openai.com", 443)


def test_dns_resolution_uses_literal_public_addresses_without_re_resolve(monkeypatch):
    expected = [(socket.AF_INET, ("8.8.8.8", 443))]
    calls = []
    monkeypatch.setattr(
        proxy.socket,
        "getaddrinfo",
        lambda *args, **kwargs: (
            calls.append((args, kwargs))
            or [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        ),
    )
    assert proxy.resolve_public_addresses("api.openai.com", 443) == expected
    assert len(calls) == 1


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(128)
        self.request.sendall(data)


def test_connect_proxy_tunnels_bytes_without_interpreting_tls(monkeypatch):
    upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), EchoHandler)
    proxy_server = proxy.ThreadedProxy(("127.0.0.1", 0))
    monkeypatch.setattr(
        proxy,
        "resolve_public_addresses",
        lambda _host, _port: [(socket.AF_INET, upstream.server_address)],
    )
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    upstream_thread.start()
    proxy_thread.start()
    try:
        client = socket.create_connection(proxy_server.server_address, timeout=2)
        client.sendall(b"CONNECT api.openai.com:443 HTTP/1.1\r\nHost: api.openai.com:443\r\n\r\n")
        assert client.recv(1024).startswith(b"HTTP/1.1 200")
        client.sendall(b"synthetic-tls-record")
        assert client.recv(128) == b"synthetic-tls-record"
        client.close()
    finally:
        proxy_server.shutdown()
        upstream.shutdown()
        proxy_server.server_close()
        upstream.server_close()


def test_proxy_does_not_log_request_headers_or_signed_query(monkeypatch, capsys):
    proxy_server = proxy.ThreadedProxy(("127.0.0.1", 0))
    monkeypatch.setattr(
        proxy,
        "resolve_public_addresses",
        lambda *_args: (_ for _ in ()).throw(proxy.ProxyError("host_denied")),
    )
    thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    thread.start()
    try:
        client = socket.create_connection(proxy_server.server_address, timeout=2)
        client.sendall(
            b"CONNECT example.com:443 HTTP/1.1\r\n"
            b"Proxy-Authorization: Bearer synthetic-secret\r\n"
            b"X-Request: https://example.com/?signed=private-value\r\n\r\n"
        )
        assert client.recv(1024).startswith(b"HTTP/1.1 403")
        client.close()
    finally:
        proxy_server.shutdown()
        proxy_server.server_close()
    logs = capsys.readouterr().err
    assert "host_denied" in logs
    assert "synthetic-secret" not in logs
    assert "private-value" not in logs
