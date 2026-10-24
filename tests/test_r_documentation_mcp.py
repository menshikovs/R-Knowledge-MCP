from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp.http import CranHTTP
from cran_knowledge_mcp.providers.r_documentation import RDocumentationProvider
from cran_knowledge_mcp.server import create_server
from cran_knowledge_mcp.service import KnowledgeService


def find_enums(value):
    if isinstance(value, dict):
        if isinstance(value.get("enum"), list):
            yield value["enum"]
        for child in value.values():
            yield from find_enums(child)
    elif isinstance(value, list):
        for child in value:
            yield from find_enums(child)


@pytest.mark.asyncio
async def test_r_manual_tools_are_discoverable_and_invoke_against_local_index():
    path = Path(__file__).with_name(f".r-doc-mcp-{uuid4().hex}.json")
    calls = []
    fixture = (
        "<html><head><title>R version 4.5.1</title></head><body>"
        '<h1 id="manual">Manual</h1><h2 id="reading-data">Reading data</h2>'
        "<p>read.table imports delimited text data.</p></body></html>"
    )

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            text=fixture,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False
        ) as client:
            provider = RDocumentationProvider(client, path)
            await provider.refresh()
            service = KnowledgeService(CranHTTP(client), r_documentation_provider=provider)
            request_count_after_refresh = len(calls)
            async with create_connected_server_and_client_session(
                create_server(service=service)
            ) as session:
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert "search_r_documentation" in tools
                assert "get_r_documentation_section" in tools
                manual_schema = tools["search_r_documentation"].inputSchema["properties"]["manuals"]
                expected_ids = {
                    "r-data-import-export",
                    "r-installation-administration",
                    "writing-r-extensions",
                    "r-internals",
                    "r-faq",
                    "introduction-to-r",
                }
                assert any(set(values) == expected_ids for values in find_enums(manual_schema))
                search = await session.call_tool(
                    "search_r_documentation",
                    {"query": "read.table import", "manuals": ["r-data-import-export"]},
                )
                assert search.isError is False
                assert search.structuredContent["status"] == "ok"
                section = search.structuredContent["results"][0]
                retrieved = await session.call_tool(
                    "get_r_documentation_section",
                    {
                        "document_id": section["document_id"],
                        "section_id": section["section_id"],
                    },
                )
                assert retrieved.isError is False
                assert retrieved.structuredContent["section"]["heading"] == "Reading data"
                assert len(calls) == request_count_after_refresh == 6
    finally:
        path.unlink(missing_ok=True)
