import json
import os
import sys
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp.server import create_http_app, create_server

TOOLS = {
    "search_packages",
    "get_package_info",
    "get_dependencies",
    "get_function_docs",
    "check_package_version",
    "get_bioconductor_version",
    "check_package_compatibility",
    "get_package_vignettes",
    "get_package_agent_guidance",
    "get_context7_docs",
    "get_package_knowledge",
    "get_shiny_docs",
    "explain_shiny_reactivity",
    "analyze_shiny_app",
    "get_positron_guidance",
    "analyze_r_workspace",
    "get_quarto_docs",
    "analyze_quarto_document",
    "analyze_quarto_project",
    "get_r_workflow_guidance",
    "get_visualization_docs",
    "get_visualization_workflow",
    "analyze_ggplot_code",
    "analyze_ggraph_code",
    "analyze_tidyr_pipeline",
    "analyze_ggplotly_compatibility",
    "analyze_knitr_chunks",
}


async def test_sdk_tool_registration_and_mocked_call(service, monkeypatch):
    api, _, _ = service
    monkeypatch.setattr(
        "cran_knowledge_mcp.server.make_client",
        lambda: httpx.AsyncClient(transport=api.http.client._transport),
    )
    async with create_connected_server_and_client_session(create_server()) as session:
        tools = (await session.list_tools()).tools
        assert {tool.name for tool in tools} == TOOLS
        assert all(tool.annotations.readOnlyHint for tool in tools)
        result = await session.call_tool("get_dependencies", {"package": "ExamplePkg"})
        assert not result.isError
        assert result.structuredContent["latest_cran_version"] == "2.10-1"
        result = await session.call_tool("get_package_info", {"package": "../bad"})
        assert result.structuredContent["error"]["code"] == "invalid_input"
        knowledge = await session.call_tool("get_package_knowledge", {"package": "ExamplePkg"})
        assert knowledge.structuredContent["verification_status"] == "partial"
        assert (
            knowledge.structuredContent["sections"]["agent_guidance"]["status"] == "not_requested"
        )
        assert knowledge.structuredContent["sections"]["package_info"]["source_url"]
        analysis = await session.call_tool(
            "analyze_quarto_document",
            {"source": "---\ntitle: Test\n---\n```{r}\n1 + 1\n```"},
        )
        assert analysis.structuredContent["not_executed"] is True
        shiny = await session.call_tool("analyze_shiny_app", {"source": "shinyApp(ui, server)"})
        assert shiny.structuredContent["analysis"] == "static_heuristics"
        docs = await session.call_tool(
            "get_shiny_docs", {"package": "shiny", "function": "page_sidebar"}
        )
        assert docs.structuredContent["error"]["code"] == "function_owner_mismatch"
        visual = await session.call_tool(
            "analyze_ggplot_code", {"source": "ggplot(df) + geom_point(aes(x = missing))"}
        )
        assert visual.structuredContent["not_executed"] is True
        assert visual.structuredContent["analysis"] == "analyze_ggplot_code"


async def test_streamable_http_initialization_and_tool_call(service, monkeypatch):
    api, _, calls = service
    monkeypatch.setattr(
        "cran_knowledge_mcp.server.make_client",
        lambda: httpx.AsyncClient(transport=api.http.client._transport),
    )
    app = create_http_app()
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers=headers
        ) as client:
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            assert response.status_code == 200
            assert response.json()["result"]["serverInfo"]["name"] == "CRAN Knowledge MCP"
            assert "mcp-session-id" not in response.headers
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "get_dependencies", "arguments": {"package": "ExamplePkg"}},
                },
            )
            assert response.status_code == 200
            assert response.json()["result"]["structuredContent"]["package"] == "ExamplePkg"
            # Stateless requests share the ASGI-owned cache, not a fresh one per request.
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "get_dependencies", "arguments": {"package": "ExamplePkg"}},
                },
            )
            assert response.status_code == 200
            assert len(calls) == 1
            blocked = await client.post("/mcp", headers={"Host": "evil.test"}, json={})
            assert blocked.status_code == 421


async def test_stdio_subprocess_initialize_and_error():
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cran_knowledge_mcp.server"],
        cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(root / "src")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert {tool.name for tool in (await session.list_tools()).tools} == TOOLS
            result = await session.call_tool("get_dependencies", {"package": "../bad"})
            assert json.loads(result.content[0].text)["error"]["code"] == "invalid_input"
