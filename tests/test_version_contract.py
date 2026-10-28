"""KC-003: one version contract for discovery and documentation.

For every version-sensitive answer: requested version, resolved version (as spelled in the source
DESCRIPTION), the match kind (identical / equivalent under R's `==`), repository scope, and whether
the answer is verified for the requested version. No other version is ever substituted.
"""

import gzip
import hashlib

import httpx
import pytest
from conftest import archive
from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp.http import (
    EQUIVALENCE_RULE,
    INDEX,
    CranHTTP,
    unavailable_version_details,
    version_match,
    version_resolution,
)
from cran_knowledge_mcp.server import create_server
from cran_knowledge_mcp.service import KnowledgeService, bounded


def rd(name, text):
    return f"\\name{{{name}}}\\alias{{{name}}}\\title{{T}}\\description{{{text}}}"


def description(package, version):
    return f"Package: {package}\nVersion: {version}\nEncoding: UTF-8\nTitle: T\n"


# --------------------------------------------------------------- unit level


@pytest.mark.parametrize(
    ("requested", "resolved", "expected"),
    [
        ("2.10-1", "2.10-1", "identical"),
        ("2.10.1", "2.10-1", "equivalent"),
        ("2.10-1.0", "2.10-1", "equivalent"),
        ("2.10-01", "2.10-1", "equivalent"),
        ("2.10-1.00", "2.10-1", "equivalent"),
        ("1.0", "1", "equivalent"),  # R: numeric_version("1.0") == numeric_version("1")
        ("2.1-1", "2.10-1", None),  # 1 vs 10: distinct
        ("2.10-2", "2.10-1", None),
        ("2.10", "2.10-1", None),
        ("20.1", "2.10-1", None),
        ("1.10", "1.1", None),  # R: 1.10 != 1.1
    ],
)
def test_version_match_follows_r_equality_and_reports_the_kind(requested, resolved, expected):
    assert version_match(requested, resolved) == expected


@pytest.mark.parametrize(
    "bad",
    ["", " ", "v2.10", "2.10-", "-2.10", "2..10", "2.10 -1", "1e3", "2.10\n", "2,10"]
    + ["１.２", "2.10\x00", "1" * 101, "2.10-1 ", "latest", "NA"],
)
def test_malformed_versions_are_invalid_input(bad):
    from cran_knowledge_mcp.errors import KnowledgeError

    with pytest.raises(KnowledgeError) as caught:
        version_match(bad, "2.10-1")
    assert caught.value.code == "invalid_input"


def test_resolution_record_never_replaces_the_resolved_spelling():
    exact = version_resolution("2.10-1", "2.10-1", "latest_cran")
    assert exact == {
        "requested": "2.10-1",
        "resolved": "2.10-1",
        "match": "identical",
        "verified_for_requested_version": True,
        "version_scope": "latest_cran",
    }
    equivalent = version_resolution("2.10.1", "2.10-1", "latest_cran")
    assert (equivalent["requested"], equivalent["resolved"]) == ("2.10.1", "2.10-1")
    assert equivalent["match"] == "equivalent"
    assert equivalent["equivalence_rule"] == EQUIVALENCE_RULE
    none = version_resolution(None, "2.10-1", "selected_bioconductor_release")
    assert none["match"] == "not_requested" and none["verified_for_requested_version"] is None


def test_unavailable_details_say_why_and_that_nothing_was_substituted():
    older = unavailable_version_details("2.9", "2.10-1", "latest_cran")
    assert older["requested_relation"] == "older_than_available"
    assert older["reason"] == "historical_versions_not_supported" and older["substituted"] is False
    newer = unavailable_version_details("3.0", "2.10-1", "latest_cran")
    assert newer["requested_relation"] == "newer_than_available"
    assert newer["reason"] == "not_in_repository_index"
    assert newer["available_package_version"] == "2.10-1"


# ------------------------------------------------------- both tools, one rule

SPELLINGS = ["2.10-1", "2.10.1", "2.10-1.0", "2.10-01"]


async def both(api, package_version, package="ExamplePkg"):
    discovery = await bounded(api.list_package_functions(package, package_version=package_version))
    docs = await bounded(
        api.get_versioned_function_docs(package, "example", package_version=package_version)
    )
    return discovery, docs


@pytest.mark.parametrize("spelling", SPELLINGS)
async def test_every_r_spelling_of_the_current_version_works_in_both_tools(service, spelling):
    api, _, _ = service
    discovery, docs = await both(api, spelling)
    assert "error" not in discovery and "error" not in docs
    expected = "identical" if spelling == "2.10-1" else "equivalent"
    for result in (discovery, docs):
        assert result["package_version"] == "2.10-1"  # the source's own spelling is preserved
        assert result["requested_package_version"] == spelling
        resolution = result["version_resolution"]
        assert (resolution["requested"], resolution["resolved"]) == (spelling, "2.10-1")
        assert resolution["match"] == expected and resolution["verified_for_requested_version"]
        assert resolution["version_scope"] == result["version_scope"] == "latest_cran"


async def test_without_a_requested_version_the_record_says_so(service):
    api, _, _ = service
    discovery, docs = await both(api, None)
    for result in (discovery, docs):
        assert result["requested_package_version"] is None
        assert result["version_resolution"]["match"] == "not_requested"
        assert result["version_resolution"]["verified_for_requested_version"] is None
        assert result["package_version"] == "2.10-1"


async def test_discovery_and_documentation_agree_on_identity_version_and_source(service):
    api, _, _ = service
    discovery, docs = await both(api, "2.10.1")
    for key in ("package", "package_version", "version_scope"):
        assert discovery[key] == docs[key]
    assert discovery["repository"] == "cran"
    archive_urls = {s["source_url"] for s in discovery["sources"]} & {
        s["source_url"] for s in docs["sources"]
    }
    assert any(url.endswith("ExamplePkg_2.10-1.tar.gz") for url in archive_urls)
    alias = next(e for e in discovery["aliases"] if e["name"] == "example")
    assert docs["archive_member"] in alias["documentation_topics"]


@pytest.mark.parametrize(
    ("requested", "relation", "reason"),
    [
        ("2.9", "older_than_available", "historical_versions_not_supported"),
        ("2.10-0", "older_than_available", "historical_versions_not_supported"),
        ("2.1-1", "older_than_available", "historical_versions_not_supported"),
        ("2.10-2", "newer_than_available", "not_in_repository_index"),
        ("3.0", "newer_than_available", "not_in_repository_index"),
        ("20.1", "newer_than_available", "not_in_repository_index"),
    ],
)
async def test_unavailable_versions_fail_structurally_and_nothing_is_substituted(
    service, requested, relation, reason
):
    api, _, calls = service
    discovery, docs = await both(api, requested)
    for result in (discovery, docs):
        error = result["error"]
        assert error["code"] == "requested_version_unavailable"
        assert result["verification_status"] == "failed"
        assert "text" not in result and "aliases" not in result and "exports" not in result
        details = {**error, **result}
        assert details["requested_package_version"] == requested
        assert details["available_package_version"] == "2.10-1"
        assert (details["requested_relation"], details["reason"]) == (relation, reason)
        assert details["substituted"] is False and details["version_scope"] == "latest_cran"
    # Refused before any source archive was fetched.
    assert not [c for c in calls if c.url.path.endswith(".tar.gz")]


@pytest.mark.parametrize("bad", ["", "v2.10", "2..10", "2.10-", "１.２", "latest"])
async def test_malformed_requested_versions_are_invalid_input_in_both_tools(service, bad):
    api, _, calls = service
    discovery, docs = await both(api, bad)
    assert discovery["error"]["code"] == docs["error"]["code"] == "invalid_input"
    assert not [c for c in calls if c.url.path.endswith(".tar.gz")]


async def test_docs_not_found_keeps_the_version_contract(service):
    api, _, _ = service
    result = await bounded(
        api.get_versioned_function_docs("ExamplePkg", "missing_fn", package_version="2.10.1")
    )
    error = result["error"]
    assert error["code"] == "docs_not_found"
    assert error["requested_package_version"] == "2.10.1"
    assert error["resolved_package_version"] == "2.10-1"
    assert error["version_resolution"]["match"] == "equivalent"


async def test_upstream_failure_is_not_reported_as_a_version_problem(service):
    api, routes, _ = service
    routes.pop("/src/contrib/ExamplePkg_2.10-1.tar.gz")
    discovery, docs = await both(api, "2.10-1")
    for result in (discovery, docs):
        assert result["error"]["code"] != "requested_version_unavailable"
        assert "version_resolution" not in result and "text" not in result


async def test_race_between_index_and_archive_never_substitutes(service, monkeypatch):
    api, _, _ = service
    provider = await api.provider("cran")
    original = provider.source

    async def changed(package):
        metadata, files, artifact, index = await original(package)
        return {**metadata, "Version": "3.0"}, files, artifact, index

    monkeypatch.setattr(provider, "source", changed)
    discovery, docs = await both(api, "2.10.1")
    for result in (discovery, docs):
        assert result["error"]["code"] == "requested_version_unavailable"
        assert result["error"].get("details", result).get("substituted", False) is False
        assert "text" not in result and "aliases" not in result


# ------------------------------------------------- cache isolation by version


@pytest.fixture
async def moving_package():
    """A package whose CRAN version changes between two calls (HTTP cache disabled)."""
    versions = {
        "1.0": archive(
            {
                "Mv/DESCRIPTION": description("Mv", "1.0"),
                "Mv/NAMESPACE": "export(old_fn)",
                "Mv/man/old_fn.Rd": rd("old_fn", "OLD TEXT"),
            }
        ),
        "2.0": archive(
            {
                "Mv/DESCRIPTION": description("Mv", "2.0"),
                "Mv/NAMESPACE": "export(new_fn)",
                "Mv/man/new_fn.Rd": rd("new_fn", "NEW TEXT"),
            }
        ),
    }
    state = {"current": "1.0"}

    def handler(request):
        path = request.url.path
        if path in (INDEX, INDEX + ".gz"):
            version = state["current"]
            md5 = hashlib.md5(versions[version], usedforsecurity=False).hexdigest()
            text = f"Package: Mv\nVersion: {version}\nMD5sum: {md5}\n".encode()
            return httpx.Response(
                200, content=gzip.compress(text) if path.endswith(".gz") else text
            )
        for version, body in versions.items():
            if path == f"/src/contrib/Mv_{version}.tar.gz":
                return httpx.Response(200, content=body)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield KnowledgeService(CranHTTP(client, ttl=0)), state


async def test_versions_do_not_leak_through_caches(moving_package):
    api, state = moving_package
    first = await bounded(api.list_package_functions("Mv", package_version="1.0"))
    assert [e["name"] for e in first["exports"]] == ["old_fn"]
    old_docs = await bounded(api.get_versioned_function_docs("Mv", "old_fn", package_version="1.0"))
    assert "OLD TEXT" in old_docs["text"]

    state["current"] = "2.0"
    second = await bounded(api.list_package_functions("Mv"))
    assert second["package_version"] == "2.0" and [e["name"] for e in second["exports"]] == [
        "new_fn"
    ]
    assert second["snapshot"] != first["snapshot"]
    # The old version is gone: refused, never answered from the cached 1.0 archive.
    stale = await bounded(api.list_package_functions("Mv", package_version="1.0"))
    assert stale["error"]["code"] == "requested_version_unavailable"
    stale_docs = await bounded(
        api.get_versioned_function_docs("Mv", "old_fn", package_version="1.0")
    )
    assert stale_docs["error"]["code"] == "requested_version_unavailable"
    unversioned = await bounded(api.get_versioned_function_docs("Mv", "old_fn"))
    assert unversioned["error"]["code"] == "docs_not_found"
    assert "OLD TEXT" not in str(unversioned)
    drift = await bounded(api.list_package_functions("Mv", snapshot=first["snapshot"], offset=0))
    assert drift["error"]["code"] == "source_identity_drift"


# ----------------------------------------------------------- MCP surface


async def test_mcp_tools_expose_the_contract_and_reject_bad_versions(service):
    api, _, _ = service
    async with create_connected_server_and_client_session(
        create_server(service=api, toolset="consolidated")
    ) as session:
        listed = await session.call_tool(
            "list_package_functions", {"package": "ExamplePkg", "package_version": "2.10.1"}
        )
        docs = await session.call_tool(
            "get_function_docs",
            {"package": "ExamplePkg", "function": "example", "package_version": "2.10.1"},
        )
        old = await session.call_tool(
            "get_function_docs",
            {"package": "ExamplePkg", "function": "example", "package_version": "2.9"},
        )
        bad = await session.call_tool(
            "list_package_functions", {"package": "ExamplePkg", "package_version": "v2"}
        )
    for result in (listed, docs):
        assert result.isError is False
        resolution = result.structuredContent["version_resolution"]
        assert resolution["match"] == "equivalent" and resolution["resolved"] == "2.10-1"
    assert old.isError is True
    error = old.structuredContent["error"]
    assert error["code"] == "requested_version_unavailable"
    assert error["reason"] == "historical_versions_not_supported"
    assert bad.isError is True and bad.structuredContent["error"]["code"] == "invalid_input"
