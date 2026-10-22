"""Probe the real public stdio gateway without agent sessions or network tool calls."""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from bench import ROOT, manifest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def probe():
    observations = []
    with tempfile.TemporaryDirectory(prefix="r-mcp-interface-") as temp:
        for condition in ("B", "C"):
            audit = Path(temp) / f"{condition}.jsonl"
            params = StdioServerParameters(
                command=sys.executable,
                args=[
                    str(ROOT / "runner/gateway.py"),
                    "--condition",
                    condition,
                    "--audit",
                    str(audit),
                ],
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    expected = set(manifest()["conditions"][condition]["tools"])
                    if names != expected:
                        raise RuntimeError("Actual tool exposure differs from protocol")
                    result = await session.call_tool("list_r_prompt_templates", {})
                    if bool(result.isError) != (condition == "B"):
                        raise RuntimeError("Actual tool-level condition enforcement failed")
                    observations.append(
                        {
                            "condition": condition,
                            "exposed_tools": sorted(names),
                            "template_call_is_error": bool(result.isError),
                            "audit_records": len(audit.read_text(encoding="utf-8").splitlines()),
                        }
                    )
    return {
        "kind": "public_MCP_interface_selftest_not_agent_trials",
        "agent_trials": 0,
        "upstream_network_tool_calls": 0,
        "observations": observations,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(asyncio.run(probe()), indent=2) + "\n", encoding="utf-8")
