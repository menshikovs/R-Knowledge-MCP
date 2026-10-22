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
    "build_r_prompt",
    "improve_r_prompt",
    "validate_r_prompt",
    "list_r_prompt_templates",
    "get_r_prompt_context",
}

PROMPTS = {
    "r-package-development",
    "shiny-app-development",
    "quarto-report",
    "bioconductor-analysis",
    "ggplot2-visualization",
    "r-debugging",
    "r-architecture-audit",
    "csv-import",
    "csv-cleaning",
    "csv-validation",
    "sql-query",
    "sql-database",
    "csv-sql-pipeline",
    "r-multi-stage-workflow",
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
        package_info_tool = next(tool for tool in tools if tool.name == "get_package_info")
        assert package_info_tool.inputSchema["properties"]["verify_archive"]["type"] == "boolean"
        assert "verify_archive" not in package_info_tool.inputSchema.get("required", [])
        prompts = (await session.list_prompts()).prompts
        assert {prompt.name for prompt in prompts} == PROMPTS
        prompt = await session.get_prompt(
            "shiny-app-development", {"request": "Build a Shiny dashboard"}
        )
        assert "Shiny" in prompt.messages[0].content.text
        assert "not authorize" in prompt.messages[0].content.text
        csv_prompt = await session.get_prompt(
            "csv-import", {"request": "Import a large CSV with an explicit schema"}
        )
        assert "delimiter" in csv_prompt.messages[0].content.text.lower()
        assert "CSV" in csv_prompt.messages[0].content.text
        workflow_prompt = await session.get_prompt(
            "r-multi-stage-workflow",
            {
                "objective": "Import a CSV into PostgreSQL and create a Quarto report",
                "technologies": "readr, DBI, Quarto",
                "inputs": "measurements.csv",
                "outputs": "report.html",
                "constraints": "Use parameterized SQL",
            },
        )
        assert "Implementation plan" in workflow_prompt.messages[0].content.text
        assert "PostgreSQL" in workflow_prompt.messages[0].content.text
        result = await session.call_tool("get_dependencies", {"package": "ExamplePkg"})
        assert not result.isError
        assert result.structuredContent["latest_cran_version"] == "2.10-1"
        result = await session.call_tool("get_package_info", {"package": "../bad"})
        assert result.structuredContent["error"]["code"] == "invalid_input"
        result = await session.call_tool(
            "get_package_info", {"package": "ExamplePkg", "verify_archive": False}
        )
        assert result.structuredContent["metadata_verification_level"] == (
            "description_version_matched"
        )
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
        generated = await session.call_tool(
            "build_r_prompt",
            {
                "request": "Import a CSV file",
                "task_category": "csv_import",
                "structured_context": {"delimiter": ";", "encoding": "UTF-8"},
                "enhancement_mode": "deterministic",
            },
        )
        assert generated.structuredContent["not_executed"] is True
        assert generated.structuredContent["structured_context"]["delimiter"] == ";"
        assert "UTF-8" in generated.structuredContent["prompt_text"]
        composed = await session.call_tool(
            "build_r_prompt",
            {
                "request": "Import and validate a CSV file",
                "composition_mode": "composed",
                "templates": ["csv-import", "csv-validation"],
                "workflow_context": {"outputs": ["validated table"]},
                "include_plan": True,
                "include_provenance": False,
            },
        )
        assert composed.structuredContent["composition_mode"] == "composed"
        assert len(composed.structuredContent["workflow_stages"]) == 2
        assert composed.structuredContent["sources"] == []
        templates = await session.call_tool("list_r_prompt_templates", {})
        assert templates.structuredContent["template_count"] >= 18
        checked = await session.call_tool(
            "validate_r_prompt",
            {"prompt_text": "Build an R package; include tests and acceptance criteria."},
        )
        assert checked.structuredContent["rubric"].startswith("Heuristic")


async def test_prompt_intelligence_can_be_disabled_without_disabling_knowledge_tools(monkeypatch):
    monkeypatch.setenv("PROMPT_INTELLIGENCE_ENABLED", "false")
    async with create_connected_server_and_client_session(create_server()) as session:
        assert {tool.name for tool in (await session.list_tools()).tools} == (
            TOOLS
            - {
                "build_r_prompt",
                "improve_r_prompt",
                "validate_r_prompt",
                "list_r_prompt_templates",
                "get_r_prompt_context",
            }
        )
        assert (await session.list_prompts()).prompts == []


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
            assert response.json()["result"]["serverInfo"]["name"] == "R Knowledge MCP"
            assert "mcp-session-id" not in response.headers
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 11, "method": "prompts/list", "params": {}},
            )
            assert response.status_code == 200
            prompt_names = {item["name"] for item in response.json()["result"]["prompts"]}
            assert prompt_names == PROMPTS
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "prompts/get",
                    "params": {
                        "name": "bioconductor-analysis",
                        "arguments": {"request": "Analyze DESeq2 data"},
                    },
                },
            )
            assert response.status_code == 200
            assert "Bioconductor" in response.json()["result"]["messages"][0]["content"]["text"]
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "tools/call",
                    "params": {
                        "name": "build_r_prompt",
                        "arguments": {
                            "request": "Investigate the R error",
                            "templates": ["r-debugging", "r-architecture-audit"],
                            "composition_mode": "composed",
                            "include_plan": True,
                        },
                    },
                },
            )
            assert response.status_code == 200
            assert response.json()["result"]["structuredContent"]["composition_mode"] == "composed"
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
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "get_package_info",
                        "arguments": {"package": "ExamplePkg", "verify_archive": False},
                    },
                },
            )
            assert response.status_code == 200
            assert (
                response.json()["result"]["structuredContent"]["metadata_verification_level"]
                == "description_version_matched"
            )
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
            assert len(calls) == 2
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
            assert {prompt.name for prompt in (await session.list_prompts()).prompts} == PROMPTS
            result = await session.call_tool("get_dependencies", {"package": "../bad"})
            assert json.loads(result.content[0].text)["error"]["code"] == "invalid_input"
