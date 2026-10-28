"""Deterministic mock agent used inside the candidate container for Stage 2.6 infrastructure tests.

Standard library only. It reads ``/agent/spec.json`` (mounted read-only), performs the requested
network probes and/or a scripted workload (model call through the egress gateway, MCP discovery and
call, answer file) and prints exactly one ``STAGE26_REPORT <json>`` line. It never contacts a real
model: the "model" is a local mock reached only through the allow-listing gateway.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import sys
import traceback

GATEWAY = ("egress-gateway", 3128)
MCP_HOST, MCP_PORT = "r-knowledge-mcp", 8000
TIMEOUT = 4


def _tcp(target: str) -> dict:
    host, port = target.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=TIMEOUT).close()
        return {"outcome": "allowed", "detail": "connected"}
    except OSError as exc:
        return {"outcome": "denied", "detail": type(exc).__name__}


def _dns(host: str) -> dict:
    try:
        socket.setdefaulttimeout(TIMEOUT)
        socket.getaddrinfo(host, 443)
        return {"outcome": "allowed", "detail": "resolved"}
    except OSError as exc:
        return {"outcome": "denied", "detail": type(exc).__name__}


def _proxy_exchange(request: bytes) -> tuple[int | None, socket.socket | None]:
    sock = socket.create_connection(GATEWAY, timeout=TIMEOUT)
    sock.sendall(request)
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(1024)
        if not chunk:
            break
        buffer += chunk
    first = buffer.split(b"\r\n", 1)[0].split(b" ")
    status = int(first[1]) if len(first) > 1 and first[1].isdigit() else None
    return status, sock


def _proxy_connect(authority: str) -> dict:
    try:
        status, sock = _proxy_exchange(
            f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode()
        )
        if sock is not None:
            sock.close()
    except OSError as exc:
        return {"outcome": "error", "detail": type(exc).__name__}
    outcome = "allowed" if status == 200 else "denied" if status == 403 else "error"
    return {"outcome": outcome, "detail": f"http_{status}"}


def _proxy_get(url: str) -> dict:
    try:
        status, sock = _proxy_exchange(f"GET {url} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        if sock is not None:
            sock.close()
    except OSError as exc:
        return {"outcome": "error", "detail": type(exc).__name__}
    return {"outcome": "denied" if status in (403, 405) else "error", "detail": f"http_{status}"}


def run_probe(probe: dict) -> dict:
    kind, target = probe["kind"], probe["target"]
    handler = {"tcp": _tcp, "dns": _dns, "proxy_connect": _proxy_connect, "proxy_get": _proxy_get}[
        kind
    ]
    result = handler(target)
    result.update(id=probe["id"], kind=kind, target=target, expect=probe["expect"])
    result["as_expected"] = result["outcome"] == probe["expect"]
    return result


def model_call(token: str) -> dict:
    status, sock = _proxy_exchange(b"CONNECT api.openai.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
    if status != 200 or sock is None:
        return {"ok": False, "gateway_status": status}
    body = json.dumps({"model": "mock", "input": "hello"}).encode()
    sock.sendall(
        b"POST /v1/responses HTTP/1.0\r\nHost: api.openai.com\r\n"
        + f"Authorization: Bearer {token}\r\n".encode()
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    data = b""
    while chunk := sock.recv(4096):
        data += chunk
    sock.close()
    head, _, payload = data.partition(b"\r\n\r\n")
    code = int(head.split(b" ")[1]) if head.startswith(b"HTTP/") else None
    parsed = json.loads(payload) if payload else {}
    usage = parsed.get("usage") or {}
    return {"ok": code == 200, "http_status": code, "usage": usage}


def _mcp_post(payload: dict, session: str | None):
    conn = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=20)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["mcp-session-id"] = session
    conn.request("POST", "/mcp", json.dumps(payload), headers)
    response = conn.getresponse()
    raw = response.read().decode()
    parsed = None
    if "text/event-stream" in (response.getheader("content-type") or ""):
        for line in raw.splitlines():
            if line.startswith("data:"):
                parsed = json.loads(line[5:].strip())
    elif raw.strip():
        parsed = json.loads(raw)
    return response.status, response.getheader("mcp-session-id") or session, parsed, len(raw)


def mcp_workflow(call: dict | None) -> dict:
    status, session, init, _ = _mcp_post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "stage26-mock-agent", "version": "1"},
            },
        },
        None,
    )
    if status != 200 or not init or "result" not in init:
        return {"ok": False, "stage": "initialize", "http_status": status}
    _mcp_post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    status, session, listing, _ = _mcp_post(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session
    )
    tools = sorted(t["name"] for t in (listing or {}).get("result", {}).get("tools", []))
    out = {"ok": bool(tools), "tools": tools, "calls": []}
    if call and tools:
        status, _, reply, size = _mcp_post(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": call["name"], "arguments": call["arguments"]},
            },
            session,
        )
        result = (reply or {}).get("result") or {}
        out["calls"].append(
            {
                "call_id": "client-call-1",
                "tool": call["name"],
                "http_status": status,
                "is_error": bool(result.get("isError")) or "error" in (reply or {}),
                "response_bytes": size,
            }
        )
    return out


def main() -> int:
    spec = json.load(open("/agent/spec.json", encoding="utf-8"))
    report: dict = {
        "mode": spec["mode"],
        "env_names": sorted(os.environ),
        "uid": os.getuid(),
    }
    try:
        if spec["mode"] == "canary":
            report["probes"] = [run_probe(p) for p in spec["probes"]]
        else:
            report["workspace_entries_at_start"] = sorted(os.listdir("/candidate"))
            report["instructions_sha256"] = hashlib.sha256(
                spec["instructions"].encode()
            ).hexdigest()
            report["model"] = model_call(os.environ.get("CODEX_API_KEY", ""))
            if spec["mcp_expected"]:
                report["mcp"] = mcp_workflow(spec["tool_call"] if spec["call_tool"] else None)
            with open("/candidate/answer.json", "w", encoding="utf-8") as handle:
                json.dump(spec["answer"], handle)
    except Exception as exc:  # report the failure rather than crash silently
        report["agent_error"] = f"{type(exc).__name__}: {exc}"
        report["traceback_tail"] = traceback.format_exc()[-600:]
    print("STAGE26_REPORT " + json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
