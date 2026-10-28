"""search_packages -> list_package_functions -> get_function_docs over real archives, offline.

The repositories are built from the authentic CRAN/Bioconductor tarballs in tests/fixtures/archives
and served through httpx.MockTransport; no test here touches the network.
"""

import json
import os
import sys
from pathlib import Path

import httpx
import jsonschema
import pytest
from archive_corpus import BIOC_VERSION, corpus_service, entries
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp.server import create_http_app, create_server
from cran_knowledge_mcp.service import bounded

CRAN = entries("cran")
BIOC = entries("bioconductor")[0]
IDS = [e["package"] for e in CRAN]


async def all_pages(api, package, **kwargs):
    """Every page of an unfiltered discovery listing (bounded), as one merged dict per kind."""
    merged = {"exports": [], "aliases": [], "documentation_topics": [], "methods": []}
    snapshot, offset, first = None, 0, None
    for _ in range(200):
        page = await bounded(
            api.list_package_functions(
                package, limit=50, offset=offset, snapshot=snapshot, **kwargs
            )
        )
        assert "error" not in page, page
        first = first or page
        snapshot = page["snapshot"]
        assert page["snapshot"] == first["snapshot"]
        for key in merged:
            merged[key].extend(page[key])
        if page["next_offset"] is None:
            return first, merged
        offset = page["next_offset"]
    raise AssertionError("pagination did not terminate")


@pytest.mark.parametrize("entry", CRAN, ids=IDS)
async def test_search_discovery_docs_chain_agrees_on_identity_and_version(entry):
    package, version = entry["package"], entry["version"]
    async with corpus_service() as (api, _, _):
        found = await bounded(api.search_packages(package))
        top = found["results"][0]
        assert (top["package"], top["latest_cran_version"]) == (package, version)

        first, merged = await all_pages(api, package)
        assert first["repository"] == "cran" and first["package_version"] == version
        assert first["verification_status"] == entry["expected"]["verification_status"]
        assert first["completeness"] == entry["expected"]["completeness"]
        assert first["version_resolution"]["resolved"] == version
        assert {k: len(merged[k]) for k in ("exports", "aliases", "methods")} == {
            k: entry["expected"]["counts"][v]
            for k, v in (("exports", "export"), ("aliases", "alias"), ("methods", "method"))
        }

        # Documentation for aliases spread over the listing resolves to the advertised topic.
        aliases = merged["aliases"]
        for alias in (aliases[0], aliases[len(aliases) // 2], aliases[-1]):
            docs = await bounded(
                api.get_versioned_function_docs(package, alias["name"], package_version=version)
            )
            assert "error" not in docs, (alias["name"], docs)
            assert docs["package"] == package and docs["package_version"] == version
            assert docs["version_resolution"]["match"] == "identical"
            if alias["documentation_topics_complete"]:
                assert docs["archive_member"] in alias["documentation_topics"]
            assert docs["version_scope"] == first["version_scope"] == "latest_cran"
            urls = {s["source_url"] for s in docs["sources"]}
            assert {s["source_url"] for s in first["sources"]} & urls
            assert all(s["checked_at"] for s in docs["sources"])


async def test_mixed_encoding_alias_resolves_with_its_own_declared_encoding():
    async with corpus_service() as (api, _, _):
        listing = await bounded(api.list_package_functions("cluster", query="plantTraits"))
        assert listing["matches"][0]["name"] == "plantTraits"
        docs = await bounded(api.get_versioned_function_docs("cluster", "plantTraits"))
    assert docs["rd_encoding"] == {"encoding": "iso8859-1", "source": "rd_declaration"}
    assert "unreadable_rd_members_in_package" not in docs


async def test_bioconductor_chain_keeps_repository_release_and_version_identity():
    package, version = BIOC["package"], BIOC["version"]
    async with corpus_service() as (api, _, _):
        found = await bounded(api.search_packages(package, repository="bioconductor"))
        assert found["results"][0]["bioc_version"] == BIOC_VERSION
        first, merged = await all_pages(api, package, repository="bioconductor")
        assert (first["repository"], first["bioc_version"]) == ("bioconductor", BIOC_VERSION)
        assert first["version_scope"] == "selected_bioconductor_release"
        name = merged["aliases"][0]["name"]
        docs = await bounded(
            api.get_versioned_function_docs(
                package, name, repository="bioconductor", package_version=f"{version}.0"
            )
        )
        assert "error" not in docs and docs["package_version"] == version
        assert docs["version_resolution"]["match"] == "equivalent"
        assert docs["version_scope"] == "selected_bioconductor_release"
        wrong = await bounded(
            api.get_versioned_function_docs(
                package, name, repository="bioconductor", package_version="0.1"
            )
        )
        assert wrong["error"]["code"] == "requested_version_unavailable"
        assert wrong["error"]["version_scope"] == "selected_bioconductor_release"
        # A package never answers for the other repository.
        other = await bounded(api.list_package_functions(package, repository="cran"))
        assert other["error"]["code"] == "package_not_found"
        reverse = await bounded(api.list_package_functions("cluster", repository="bioconductor"))
        assert reverse["error"]["code"] == "package_not_found"


async def test_unknown_function_is_actionable_and_names_the_resolved_version():
    async with corpus_service() as (api, _, _):
        result = await bounded(
            api.get_versioned_function_docs("R6", "R6Clas", package_version="2.6.1")
        )
    error = result["error"]
    assert error["code"] == "docs_not_found" and error["lookup_stage"] == "literal_rd_alias"
    assert error["resolved_package_version"] == "2.6.1"
    assert error["suggestions"] and error["suggestions"][0]["name"] == "R6Class"
    assert error["discovery_status"] == {"namespace": "verified", "rd": "verified"}
    assert error["version_resolution"]["match"] == "identical"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": "x" * 201},
        {"query": "bad\x00query"},
        {"query": "   "},
        {"limit": 0},
        {"limit": 51},
        {"offset": -1},
        {"offset": 5},  # continuation without a snapshot
        {"snapshot": "not-a-token"},
        {"package_version": "1;rm -rf /"},
    ],
)
async def test_malformed_discovery_requests_are_rejected_before_any_fetch(kwargs):
    async with corpus_service() as (api, _, calls):
        result = await bounded(api.list_package_functions("cluster", **kwargs))
        assert result["error"]["code"] == "invalid_input"
        assert not calls


@pytest.mark.parametrize("package", ["../etc/passwd", "a b", "", "x" * 300, "pkg;ls"])
async def test_malformed_package_names_never_reach_the_network(package):
    async with corpus_service() as (api, _, calls):
        discovery = await bounded(api.list_package_functions(package))
        docs = await bounded(api.get_versioned_function_docs(package, "f"))
        assert discovery["error"]["code"] == docs["error"]["code"] == "invalid_input"
        assert not calls


async def test_ambiguous_or_oversized_function_names_are_structured_errors():
    async with corpus_service() as (api, _, _):
        for name in ("", "a" * 161, "bad\nname"):
            result = await bounded(api.get_versioned_function_docs("cluster", name))
            assert result["error"]["code"] == "invalid_input"


# --------------------------------------------------------------- MCP surface


async def test_tools_over_mcp_validate_against_their_declared_schemas():
    async with corpus_service() as (api, _, _):
        async with create_connected_server_and_client_session(
            create_server(service=api, toolset="consolidated")
        ) as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}
            assert {"search_packages", "list_package_functions", "get_function_docs"} <= set(tools)
            for name in ("list_package_functions", "get_function_docs"):
                assert "package_version" in tools[name].inputSchema["properties"]
            calls = [
                ("search_packages", {"query": "cluster"}),
                ("list_package_functions", {"package": "cluster", "query": "pam"}),
                (
                    "get_function_docs",
                    {"package": "cluster", "function": "pam", "package_version": "2.1.8.3"},
                ),
                (
                    "get_function_docs",
                    {"package": "cluster", "function": "pam", "package_version": "1"},
                ),
                ("list_package_functions", {"package": "cluster", "package_version": "x"}),
            ]
            outcomes = []
            for name, arguments in calls:
                result = await session.call_tool(name, arguments)
                if tools[name].outputSchema:
                    jsonschema.validate(result.structuredContent, tools[name].outputSchema)
                assert result.structuredContent is not None
                outcomes.append((result.isError, result.structuredContent))
    assert [o[0] for o in outcomes] == [False, False, False, True, True]
    assert outcomes[2][1]["version_resolution"]["match"] == "identical"
    assert outcomes[3][1]["error"]["code"] == "requested_version_unavailable"
    assert outcomes[4][1]["error"]["code"] == "invalid_input"


async def test_streamable_http_serves_the_discovery_chain(monkeypatch):
    async with corpus_service() as (api, _, _):
        transport = api.http.client._transport
        monkeypatch.setattr(
            "cran_knowledge_mcp.server.make_client", lambda: httpx.AsyncClient(transport=transport)
        )
        monkeypatch.setenv("MCP_TOOLSET", "consolidated")
        app = create_http_app()
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers=headers
            ) as client:

                async def rpc(number, method, params):
                    response = await client.post(
                        "/mcp",
                        json={"jsonrpc": "2.0", "id": number, "method": method, "params": params},
                    )
                    assert response.status_code == 200
                    return response.json()["result"]

                await rpc(
                    1,
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "1"},
                    },
                )
                names = {t["name"] for t in (await rpc(2, "tools/list", {}))["tools"]}
                assert {"list_package_functions", "get_function_docs"} <= names
                listing = (
                    await rpc(
                        3,
                        "tools/call",
                        {"name": "list_package_functions", "arguments": {"package": "R6"}},
                    )
                )["structuredContent"]
                assert listing["package_version"] == "2.6.1"
                assert listing["version_resolution"]["match"] == "not_requested"
                docs = (
                    await rpc(
                        4,
                        "tools/call",
                        {
                            "name": "get_function_docs",
                            "arguments": {
                                "package": "R6",
                                "function": "R6Class",
                                "package_version": "2.6.1.0",
                            },
                        },
                    )
                )["structuredContent"]
                assert docs["version_resolution"]["match"] == "equivalent"
                assert "R6Class" in docs["text"]


async def test_stdio_subprocess_advertises_the_contract_and_rejects_bad_versions_offline():
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cran_knowledge_mcp.server"],
        cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(root / "src"), "MCP_TOOLSET": "consolidated"},
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name: t for t in (await session.list_tools()).tools}
                assert len(tools) == 16
                assert (
                    "package_version" in tools["list_package_functions"].inputSchema["properties"]
                )
                result = await session.call_tool(
                    "list_package_functions", {"package": "cluster", "package_version": "v2"}
                )
                assert result.isError is True
                assert json.loads(result.content[0].text)["error"]["code"] == "invalid_input"
    except PermissionError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 5:
            pytest.skip("The Windows sandbox denies the named pipe required by stdio subprocesses")
        raise
