from __future__ import annotations

import json

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.http import CranHTTP
from cran_knowledge_mcp.server import create_server
from cran_knowledge_mcp.service import KnowledgeService


@pytest.fixture(autouse=True)
def legacy_toolset(monkeypatch):
    """These contract tests cover the original 35-tool surface kept for MCP_TOOLSET=legacy."""
    monkeypatch.setenv("MCP_TOOLSET", "legacy")


async def _session(service):
    return create_connected_server_and_client_session(create_server(service=service))


def _assert_error_response(result, code):
    assert result.isError is True
    assert result.structuredContent["verification_status"] == "failed"
    assert result.structuredContent["error"]["code"] == code
    assert result.content and result.content[0].type == "text"
    assert json.loads(result.content[0].text) == result.structuredContent


async def test_mcp_result_classifies_success_failure_and_partial(service):
    api, _, _ = service
    async with await _session(api) as session:
        success = await session.call_tool("get_package_info", {"package": "ExamplePkg"})
        assert success.isError is False
        assert success.structuredContent["package_version"] == "2.10-1"
        assert json.loads(success.content[0].text) == success.structuredContent

        missing = await session.call_tool("get_package_info", {"package": "MissingPkg"})
        _assert_error_response(missing, "package_not_found")

        invalid = await session.call_tool("get_package_info", {"package": "../bad"})
        _assert_error_response(invalid, "invalid_input")

        partial = await session.call_tool(
            "search_packages", {"query": "Example", "repository": "all"}
        )
        assert partial.isError is False
        assert partial.structuredContent["verification_status"] == "partial"
        assert partial.structuredContent["results"]
        assert partial.structuredContent["errors"]


async def test_unavailable_upstream_and_timeout_keep_structured_codes():
    async def unavailable(_request):
        return httpx.Response(503, text="upstream internal detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        api = KnowledgeService(CranHTTP(client))
        async with await _session(api) as session:
            unavailable_result = await session.call_tool(
                "get_package_info", {"package": "ExamplePkg"}
            )
            _assert_error_response(unavailable_result, "source_unavailable")
            assert "upstream internal detail" not in unavailable_result.content[0].text
            error_envelope = unavailable_result.structuredContent
            assert error_envelope["package"] == "ExamplePkg"
            assert error_envelope["repository"] == "cran"
            assert error_envelope["package_version"] is None
            assert error_envelope["checked_at"] is None
            assert error_envelope["error"]["source_url"] == error_envelope["source_url"]
            assert error_envelope["error"]["attempted_at"]

            async def timeout(*_args, **_kwargs):
                raise TimeoutError("private timeout detail")

            api.get_package_info = timeout
            timed_out = await session.call_tool("get_package_info", {"package": "ExamplePkg"})
            _assert_error_response(timed_out, "timeout")
            assert "private timeout detail" not in timed_out.content[0].text


async def test_sdk_argument_validation_and_internal_exception_are_sanitized(monkeypatch, service):
    api, _, _ = service
    async with await _session(api) as session:
        invalid_schema = await session.call_tool(
            "search_packages", {"query": "Example", "limit": "not-an-integer"}
        )
        _assert_error_response(invalid_schema, "invalid_input")
        assert "not-an-integer" not in invalid_schema.content[0].text
        assert "Traceback" not in invalid_schema.content[0].text

        def explode(_self):
            raise RuntimeError("credential-like-private-detail")

        monkeypatch.setattr(
            "cran_knowledge_mcp.server.PromptIntelligence.list_r_prompt_templates", explode
        )
        internal = await session.call_tool("list_r_prompt_templates", {})
        _assert_error_response(internal, "internal_error")
        assert "credential-like-private-detail" not in internal.content[0].text
        assert "Traceback" not in internal.content[0].text

        async def invalid_output(*_args, **_kwargs):
            return ["not", "an", "object"]

        api.get_package_info = invalid_output
        invalid_result = await session.call_tool("get_package_info", {"package": "ExamplePkg"})
        _assert_error_response(invalid_result, "internal_error")
        assert "ValidationError" not in invalid_result.content[0].text


async def test_function_docs_context7_and_prompt_tools_have_consistent_results(service):
    api, _, _ = service
    async with await _session(api) as session:
        missing_docs = await session.call_tool(
            "get_function_docs", {"package": "ExamplePkg", "function": "not_an_alias"}
        )
        _assert_error_response(missing_docs, "docs_not_found")

        context7 = await session.call_tool(
            "get_context7_docs", {"package": "ExamplePkg", "question": "How to use it?"}
        )
        assert context7.isError is True
        assert context7.structuredContent["error"]["code"] in {
            "integration_disabled",
            "context7_not_configured",
            "not_configured",
            "repository_not_verified",
        }

        guidance = await session.call_tool(
            "get_package_agent_guidance",
            {"package": "ExamplePkg", "revision": "v1.0.0"},
        )
        _assert_error_response(guidance, "repository_not_verified")

        bioconductor = await session.call_tool(
            "get_package_info",
            {"package": "DESeq2", "repository": "bioconductor"},
        )
        assert bioconductor.isError is True
        assert bioconductor.structuredContent["verification_status"] == "failed"
        assert bioconductor.structuredContent["error"]["code"]

        knowledge = await session.call_tool(
            "get_package_knowledge",
            {"package": "ExamplePkg", "question": "How to use it?"},
        )
        assert knowledge.isError is False
        assert knowledge.structuredContent["verification_status"] == "partial"
        assert knowledge.structuredContent["sections"]["package_info"]["package_version"]
        assert any(
            error["section"] == "context7_docs" for error in knowledge.structuredContent["errors"]
        )

        invalid_prompt = await session.call_tool("build_r_prompt", {"request": ""})
        _assert_error_response(invalid_prompt, "invalid_input")
        invalid_template = await session.call_tool(
            "build_r_prompt",
            {
                "request": "Build a CSV import workflow",
                "composition_mode": "composed",
                "templates": ["not-a-template"],
            },
        )
        _assert_error_response(invalid_template, "invalid_input")

        successful_prompt = await session.call_tool(
            "build_r_prompt",
            {"request": "Import a CSV file", "enhancement_mode": "deterministic"},
        )
        assert successful_prompt.isError is False
        assert successful_prompt.structuredContent["prompt_text"]

        quality_check = await session.call_tool(
            "validate_r_prompt", {"prompt_text": "Use dplyr to summarize the supplied data."}
        )
        assert quality_check.isError is False
        assert quality_check.structuredContent["rubric"].startswith("Heuristic")

        templates = await session.call_tool("list_r_prompt_templates", {})
        assert templates.isError is False
        assert templates.structuredContent["template_count"] >= 18

        with pytest.raises(McpError):
            await session.get_prompt("not-a-registered-prompt", {})


async def test_repository_all_failure_is_error_without_partial_data(service):
    api, routes, _ = service
    routes.clear()
    async with await _session(api) as session:
        result = await session.call_tool(
            "search_packages", {"query": "nothing", "repository": "all"}
        )
    assert result.isError is True
    assert result.structuredContent["verification_status"] == "failed"
    assert not result.structuredContent["results"]
    assert len(result.structuredContent["errors"]) == 2
    assert json.loads(result.content[0].text) == result.structuredContent


async def test_partial_context7_failure_does_not_fail_overall_tool(service, monkeypatch):
    api, _, _ = service

    async def unavailable(*_args, **_kwargs):
        raise KnowledgeError("context7_unavailable", "Context7 is temporarily unavailable")

    monkeypatch.setattr(api.context7, "get_context7_docs", unavailable)
    async with await _session(api) as session:
        result = await session.call_tool(
            "get_package_knowledge",
            {"package": "ExamplePkg", "question": "Show an example"},
        )
    assert result.isError is False
    assert result.structuredContent["verification_status"] == "partial"
    assert result.structuredContent["sections"]["package_info"]["package_version"] == "2.10-1"
    assert result.structuredContent["sections"]["context7_docs"]["error"]["code"] == (
        "context7_unavailable"
    )


async def test_optional_cran_description_404_remains_a_partial_success(service):
    api, routes, _ = service
    routes.pop("/web/packages/ExamplePkg/DESCRIPTION")
    async with await _session(api) as session:
        result = await session.call_tool(
            "get_package_info", {"package": "ExamplePkg", "verify_archive": False}
        )
    assert result.isError is False
    assert result.structuredContent["verification_status"] == "partial"
    assert result.structuredContent["metadata_verification_level"] == "index_verified"
    assert result.structuredContent["metadata_error"]["code"] == "not_found"


async def test_sdk_tool_validation_errors_do_not_kill_session(service):
    api, _, _ = service
    async with await _session(api) as session:
        failed = await session.call_tool(
            "get_package_info", {"package": "ExamplePkg", "verify_archive": "invalid-bool"}
        )
        _assert_error_response(failed, "invalid_input")
        succeeded = await session.call_tool("analyze_shiny_app", {"source": "shinyApp(ui, server)"})
        assert succeeded.isError is False
