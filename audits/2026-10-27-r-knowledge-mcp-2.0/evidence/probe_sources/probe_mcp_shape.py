"""In-memory MCP session against mocked upstreams: result shape, duplication, schema strength."""
import asyncio
import json
import sys

from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp.http import CranHTTP
from cran_knowledge_mcp.server import create_server
from cran_knowledge_mcp.service import KnowledgeService

sys.path.insert(0, sys.argv[1])
from fx import make_client  # noqa: E402


async def main():
    client, routes = make_client()
    async with client:
        svc = KnowledgeService(CranHTTP(client))
        server = create_server(service=svc)
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            tools = (await session.list_tools()).tools
            by = {t.name: t for t in tools}
            print("outputSchema (get_package):", json.dumps(by["get_package"].outputSchema))
            print("inputSchema additionalProperties:", by["get_package"].inputSchema.get("additionalProperties"))
            print("inputSchema (list_package_functions) keys:", sorted(by["list_package_functions"].inputSchema["properties"]))
            for name, args in (
                ("get_package", {"package": "Ex"}),
                ("get_function_docs", {"package": "Ex", "function": "ex"}),
                ("list_package_functions", {"package": "Ex", "limit": 20}),
                ("get_package", {"package": "Ex", "verbosity": "full"}),
            ):
                r = await session.call_tool(name, args)
                text = "".join(c.text for c in r.content if c.type == "text")
                structured = json.dumps(r.structuredContent, separators=(",", ":"), ensure_ascii=False)
                total = len(r.model_dump_json(exclude_none=True, by_alias=True).encode())
                print(f"{name:24} isError={r.isError} text_bytes={len(text.encode())} structured_bytes={len(structured.encode())} identical={text == structured} wire_bytes={total}")
            # invalid arguments through the real MCP stack
            r = await session.call_tool("get_package", {"package": "Ex", "include": ["nope"]})
            print("bad enum -> isError:", r.isError, "| code:", (r.structuredContent or {}).get("error", {}).get("code"))
            r = await session.call_tool("get_function_docs", {"package": "Ex"})
            print("missing required arg -> isError:", r.isError, "| code:", (r.structuredContent or {}).get("error", {}).get("code"))
            r = await session.call_tool("get_package", {"package": "Nope"})
            sc = r.structuredContent; print("package not found -> isError:", r.isError, "| status:", sc.get("verification_status"), "| top-level keys:", sorted(sc)[:12], "| errors:", [(e["section"], e["error"]["code"]) for e in sc.get("errors", [])])
            r = await session.read_resource("cran://Ex/man/ex")
            print("resource cran://Ex/man/ex ->", r.contents[0].text[:80].replace("\n", " "))
            r = await session.read_resource("cran://Ex/man/nope")
            print("resource missing alias (no isError channel) ->", json.loads(r.contents[0].text)["error"]["code"])
            p = await session.get_prompt("csv-import", {"request": "Read a CSV and parse dates"})
            print("prompt csv-import: messages", len(p.messages), "chars", sum(len(m.content.text) for m in p.messages))


asyncio.run(main())
