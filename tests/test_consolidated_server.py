"""Contract tests for the consolidated MCP surface (default MCP_TOOLSET)."""

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp.providers.r_documentation import RDocumentationProvider
from cran_knowledge_mcp.server import create_server
from cran_knowledge_mcp.service import r_constraint_status

TOOLS = {
    "search_packages",
    "get_package",
    "get_function_docs",
    "list_package_functions",
    "check_package_version",
    "check_r_compatibility",
    "search_r_documentation",
    "get_r_documentation_section",
    "get_framework_docs",
    "get_r_workflow_guidance",
    "analyze_r_source",
    "analyze_r_project",
    "recommend_technology_stack",
    "build_r_prompt",
    "validate_r_prompt",
    "get_r_prompt_context",
}
OFFLINE_TOOLS = {
    "search_r_documentation",
    "get_r_documentation_section",
    "analyze_r_project",
    "validate_r_prompt",
}


def session_for(api):
    return create_connected_server_and_client_session(
        create_server(service=api, toolset="consolidated")
    )


def nested_sources(value, depth=0):
    if isinstance(value, dict):
        return any(
            (key == "sources" and depth > 0) or nested_sources(item, depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(nested_sources(item, depth + 1) for item in value)
    return False


async def test_tool_surface_annotations_and_parameter_descriptions(service):
    api, _, _ = service
    async with session_for(api) as session:
        tools = (await session.list_tools()).tools
    assert {tool.name for tool in tools} == TOOLS
    for tool in tools:
        assert tool.description
        assert tool.annotations.title
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.openWorldHint is (tool.name not in OFFLINE_TOOLS)
        for name, schema in tool.inputSchema["properties"].items():
            assert schema.get("description"), f"{tool.name}.{name} lacks a description"


async def test_get_package_sections_compact_and_full(service):
    api, _, calls = service
    async with session_for(api) as session:
        compact = await session.call_tool(
            "get_package", {"package": "ExamplePkg", "include": ["metadata", "dependencies"]}
        )
        full = await session.call_tool(
            "get_package",
            {"package": "ExamplePkg", "include": ["metadata", "dependencies"], "verbosity": "full"},
        )
    assert compact.isError is False
    content = compact.structuredContent
    assert content["verification_status"] == "verified"
    assert content["sections"]["metadata"]["urls"] == "https://example.invalid"
    assert content["sections"]["dependencies"]["dependencies"]["Depends"] == "R (>= 4.1)"
    assert content["response_mode"] == "compact"
    assert not nested_sources(content)
    urls = [(s["source_url"], s["checked_at"]) for s in content["sources"]]
    assert len(urls) == len(set(urls)) >= 2
    assert nested_sources(full.structuredContent)
    assert "response_mode" not in full.structuredContent
    assert not any(call.url.path.endswith(".tar.gz") for call in calls)


async def test_get_package_rejects_section_arguments_that_would_be_ignored(service):
    api, _, _ = service
    async with session_for(api) as session:
        missing_revision = await session.call_tool(
            "get_package", {"package": "ExamplePkg", "include": ["agent_guidance"]}
        )
        stray_revision = await session.call_tool(
            "get_package", {"package": "ExamplePkg", "revision": "main"}
        )
        removed_section = await session.call_tool(
            "get_package", {"package": "ExamplePkg", "include": ["context7"]}
        )
    for result in (missing_revision, stray_revision, removed_section):
        assert result.isError is True
        assert result.structuredContent["error"]["code"] == "invalid_input"


@pytest.mark.parametrize(
    ("toolset", "tool"), [("consolidated", "get_package"), ("legacy", "get_package_knowledge")]
)
async def test_removed_question_parameter_is_rejected_not_ignored(service, toolset, tool):
    api, _, _ = service
    async with create_connected_server_and_client_session(
        create_server(service=api, toolset=toolset)
    ) as session:
        listed = {item.name: item for item in (await session.list_tools()).tools}
        result = await session.call_tool(tool, {"package": "ExamplePkg", "question": "How?"})
    assert listed[tool].inputSchema["additionalProperties"] is False
    assert "question" not in listed[tool].inputSchema["properties"]
    assert result.isError is True
    assert result.structuredContent["error"]["code"] == "invalid_input"


async def test_function_docs_never_substitute_another_version(service):
    api, _, _ = service
    async with session_for(api) as session:
        current = await session.call_tool(
            "get_function_docs",
            {"package": "ExamplePkg", "function": "example", "package_version": "2.10-1"},
        )
        older = await session.call_tool(
            "get_function_docs",
            {"package": "ExamplePkg", "function": "example", "package_version": "2.9"},
        )
    assert current.isError is False
    assert "\\name{example}" in current.structuredContent["text"]
    assert older.isError is True
    assert older.structuredContent["error"]["code"] == "requested_version_unavailable"
    assert older.structuredContent["available_package_version"] == "2.10-1"


@pytest.mark.parametrize(
    ("r_version", "operator", "required", "expected"),
    [
        ("4.1", ">=", "4.1.0", True),
        ("4.1", "<", "4.1.0", False),
        ("4.1", ">=", "4.1.2", None),
        ("4.4.1", ">=", "4.1", True),
        ("4.0.5", ">=", "4.1", False),
    ],
)
def test_r_constraint_status_marks_undecidable_patch_bounds(
    r_version, operator, required, expected
):
    assert r_constraint_status(r_version, operator, required) is expected


async def test_cran_compatibility_checks_r_and_direct_dependencies(service):
    api, _, _ = service
    async with session_for(api) as session:
        newer = await session.call_tool(
            "check_r_compatibility", {"package": "ExamplePkg", "r_version": "4.4"}
        )
        older = await session.call_tool(
            "check_r_compatibility", {"package": "ExamplePkg", "r_version": "4.0.5"}
        )
        no_package = await session.call_tool("check_r_compatibility", {"r_version": "4.4"})
    content = newer.structuredContent
    assert content["repository"] == "cran"
    assert content["r_constraints"] == [{"constraint": "R (>= 4.1)", "satisfied": True}]
    # `other` is absent from the CRAN index, so the result cannot be claimed compatible.
    assert content["compatibility_status"] == "unknown"
    assert any("other" in warning for warning in content["warnings"])
    assert older.structuredContent["compatibility_status"] == "incompatible"
    assert older.structuredContent["compatible"] is False
    assert no_package.isError is True


async def test_analyze_r_source_dispatches_and_rejects_misplaced_options(service):
    api, _, _ = service
    async with session_for(api) as session:
        ggplot = await session.call_tool(
            "analyze_r_source",
            {
                "kind": "ggplot",
                "source": "ggplot(df, aes(x = a)) + geom_point()",
                "schemas": {"data": {"b": "numeric"}},
            },
        )
        misplaced = await session.call_tool(
            "analyze_r_source",
            {"kind": "ggplot", "source": "ggplot(df)", "document_type": "qmd"},
        )
        wrong_schema = await session.call_tool(
            "analyze_r_source",
            {"kind": "tidyr", "source": "pivot_longer(df, x)", "schemas": {"data": {}}},
        )
        shiny = await session.call_tool(
            "analyze_r_source", {"kind": "shiny", "source": "shinyApp(ui, server)"}
        )
    assert ggplot.isError is False
    assert any(
        f["code"] == "mapping_not_in_supplied_schema" for f in ggplot.structuredContent["findings"]
    )
    assert "limitations" not in ggplot.structuredContent
    for result in (misplaced, wrong_schema):
        assert result.isError is True
        assert result.structuredContent["error"]["code"] == "invalid_input"
    assert shiny.structuredContent["analysis"] == "static_heuristics"


async def test_project_framework_workflow_and_prompt_routing(service):
    api, _, _ = service
    async with session_for(api) as session:
        project = await session.call_tool(
            "analyze_r_project",
            {
                "files": {
                    "_quarto.yml": "project:\n  type: book\nbibliography: refs.bib\n",
                    "index.qmd": "# Title",
                }
            },
        )
        wrong_topic = await session.call_tool(
            "get_framework_docs", {"framework": "quarto", "topic": "modules"}
        )
        stray_question = await session.call_tool(
            "get_framework_docs", {"framework": "quarto", "topic": "r", "question": "Why?"}
        )
        workflow = await session.call_tool(
            "get_r_workflow_guidance",
            {"scenario": "tidy_to_plot", "packages": [{"package": "shiny"}]},
        )
        improve = await session.call_tool(
            "build_r_prompt",
            {"request": "Write an R function", "mode": "improve", "task_category": "testing"},
        )
        improved = await session.call_tool(
            "build_r_prompt", {"request": "Write an R function that reads a CSV", "mode": "improve"}
        )
    assert project.structuredContent["quarto_project"]["project_type"] == "book"
    assert any(
        f["kind"] == "bibliography_file_not_in_manifest"
        for f in project.structuredContent["quarto_project"]["findings"]
    )
    assert wrong_topic.structuredContent["error"]["code"] == "unsupported_topic"
    for result in (stray_question, workflow, improve):
        assert result.isError is True
        assert result.structuredContent["error"]["code"] == "invalid_input"
    assert improved.isError is False
    assert improved.structuredContent["original_prompt_preserved_verbatim"] is True


async def test_resources_list_and_read(service, tmp_path):
    api, _, _ = service
    api.r_documentation = RDocumentationProvider(index_path=tmp_path / "missing.json")
    async with session_for(api) as session:
        resources = {str(r.uri) for r in (await session.list_resources()).resources}
        templates = {
            t.uriTemplate for t in (await session.list_resource_templates()).resourceTemplates
        }
        catalog = await session.read_resource("r-knowledge://framework-docs")
        rd = await session.read_resource("cran://ExamplePkg/man/example")
        outline = await session.read_resource("r-manual://writing-r-extensions")
        unknown = await session.read_resource("r-manual://not-a-manual")
    assert {"r-knowledge://framework-docs", "r-knowledge://prompt-templates"} <= resources
    assert templates == {
        "r-manual://{document_id}",
        "r-manual://{document_id}/{section_id}",
        "cran://{package}/man/{alias}",
    }
    assert "quarto" in json.loads(catalog.contents[0].text)["catalog"]
    rd_content = json.loads(rd.contents[0].text)
    assert rd_content["package_version"] == "2.10-1"
    assert "\\name{example}" in rd_content["text"]
    assert json.loads(outline.contents[0].text)["status"] == "index_unavailable"
    assert json.loads(unknown.contents[0].text)["error"]["code"] == "invalid_input"


async def test_legacy_toolset_keeps_original_names_except_the_removed_context7_tool(service):
    api, _, _ = service
    server = create_server(service=api, toolset="legacy")
    async with create_connected_server_and_client_session(server) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
    assert len(names) == 34
    assert "get_context7_docs" not in names
    assert {"get_shiny_docs", "get_quarto_docs", "analyze_ggplot_code"} <= names
