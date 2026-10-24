"""Benchmark-only MCP allowlist and recorder; never imported by production."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent

import cran_knowledge_mcp

MANIFEST = Path(__file__).resolve().parents[1] / "manifest.json"
MAX_ARGUMENT_BYTES = 65536
MAX_RESULT_BYTES = 4 << 20
MAX_AUDIT_BYTES = 32 << 20
MAX_CALLS = 100


class Gateway:
    def __init__(self, condition, backend, audit):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if condition not in {"B", "C"}:
            raise ValueError("A must not start an MCP server")
        self.condition = condition
        self.allowed = set(data["conditions"][condition]["tools"])
        self.backend, self.audit = backend, audit
        self.calls = 0
        self.bytes = 0
        self.lock = asyncio.Lock()

    def write(self, value):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        self.bytes += len(text.encode())
        if self.bytes > MAX_AUDIT_BYTES:
            raise ValueError("Audit limit reached; terminate this trial")
        self.audit.write(text)
        self.audit.flush()

    async def tools(self):
        tools = (await self.backend.list_tools()).tools
        found = {t.name for t in tools}
        if not self.allowed <= found:
            raise ValueError("Production tool set differs from the registered protocol")
        exposed = [t for t in tools if t.name in self.allowed]
        self.write(
            {
                "event": "exposure",
                "condition": self.condition,
                "tools": [t.model_dump(mode="json") for t in exposed],
            }
        )
        return exposed

    async def call(self, name, arguments):
        async with self.lock:
            self.calls += 1
            start = time.perf_counter()
            timestamp = datetime.now(UTC).isoformat()
            if name not in self.allowed or self.calls > MAX_CALLS:
                result = CallToolResult(
                    isError=True,
                    content=[
                        TextContent(
                            type="text", text="Tool denied by benchmark condition or call budget"
                        )
                    ],
                )
            elif len(json.dumps(arguments).encode()) > MAX_ARGUMENT_BYTES:
                result = CallToolResult(
                    isError=True,
                    content=[TextContent(type="text", text="Argument byte limit exceeded")],
                )
            else:
                try:
                    async with asyncio.timeout(45):
                        result = await self.backend.call_tool(name, arguments)
                except Exception:
                    # Never copy exception text (which may contain credentials).
                    result = CallToolResult(
                        isError=True,
                        content=[
                            TextContent(type="text", text="Recorded upstream MCP transport failure")
                        ],
                    )
            serialized = result.model_dump(mode="json")
            if len(json.dumps(serialized).encode()) > MAX_RESULT_BYTES:
                raise ValueError("Result limit exceeded; terminate this trial")
            # Inputs are restricted to public synthetic benchmark task material.
            # Store the complete actual sources, timestamps, errors and PI response.
            self.write(
                {
                    "event": "call",
                    "condition": self.condition,
                    "tool": name,
                    "arguments": arguments,
                    "result": serialized,
                    "started_at": timestamp,
                    "elapsed_seconds": time.perf_counter() - start,
                }
            )
            return result


async def serve(condition, audit_path):
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    package_root = Path(cran_knowledge_mcp.__file__).parent
    hashes = {
        p.relative_to(package_root).as_posix(): hashlib.sha256(
            p.read_text(encoding="utf-8").encode()
        ).hexdigest()
        for p in package_root.rglob("*.py")
    }
    if hashes != data["production_sources"]:
        raise ValueError("Installed production source differs from the evaluated commit")
    for package in ("mcp", "httpx"):
        key = "mcp_sdk" if package == "mcp" else package
        if importlib.metadata.version(package) != data["environment"][key]:
            raise ValueError("Gateway dependency differs from the frozen environment")
    # Fresh upstream process/cache per independent trial. No account credentials.
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ}
    env["PROMPT_INTELLIGENCE_ENABLED"] = "true"
    # Benchmark conditions name the original tools; pin that surface explicitly.
    env["MCP_TOOLSET"] = "legacy"
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "cran_knowledge_mcp.server"], env=env
    )
    # Exclusive creation prevents mixing conditions/trials or overwriting raw evidence.
    with Path(audit_path).open("x", encoding="utf-8") as audit:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                gateway = Gateway(condition, session, audit)
                definitions = await gateway.tools()
                app = Server("codex-r-benchmark-allowlist")

                @app.list_tools()
                async def list_tools():
                    return definitions

                @app.call_tool()
                async def call_tool(name, arguments):
                    return await gateway.call(name, arguments)

                # No MCP Prompts/Resources handlers: they cannot bypass the allowlist.
                async with stdio_server() as (incoming, outgoing):
                    await app.run(incoming, outgoing, app.create_initialization_options())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", required=True, choices=["B", "C"])
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(serve(args.condition, args.audit))
