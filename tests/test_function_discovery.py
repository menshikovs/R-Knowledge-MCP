"""Offline source fixtures shared by Python, actual PyO3 and provider tests."""

import dataclasses
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from conftest import archive
from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp import function_discovery as fd
from cran_knowledge_mcp import native as native_module
from cran_knowledge_mcp import visualization_analysis as va
from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.http import INDEX, CranHTTP
from cran_knowledge_mcp.parsers import source_files
from cran_knowledge_mcp.server import create_server
from cran_knowledge_mcp.service import KnowledgeService, bounded

FIXTURE = json.loads(
    (Path(__file__).parent / "data" / "function_discovery_cases.json").read_text(encoding="utf-8")
)
CASES = FIXTURE["cases"]
DESCRIPTION = "Package: DiscoveryPkg\nVersion: 1.0.0\nEncoding: UTF-8\nTitle: Synthetic\n"


def files_for(case):
    files = {"DiscoveryPkg/DESCRIPTION": DESCRIPTION.encode()}
    if case["namespace"] is not None:
        files["DiscoveryPkg/NAMESPACE"] = case["namespace"].encode()
    files.update({f"DiscoveryPkg/man/{k}": v.encode() for k, v in case["rd"].items()})
    return files


def build(case):
    return fd.build_discovery_index("DiscoveryPkg", {"Encoding": "UTF-8"}, files_for(case))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
@pytest.mark.parametrize("backend", ["python", "native"])
def test_shared_semantic_fixtures(case, backend, monkeypatch):
    if backend == "native" and native_module.native is None:
        pytest.skip("cran_knowledge_native is not installed")
    monkeypatch.setattr(va, "native", None if backend == "python" else native_module.native)
    result = build(case)
    assert sorted(e["name"] for e in result.entries if e["kind"] == "export") == case["exports"]
    assert sorted(e["name"] for e in result.entries if e["kind"] == "alias") == case["aliases"]
    assert result.namespace_status == case["namespace_status"]
    assert result.rd_status == case["rd_status"]
    assert all(e["callability"] == "not_checked" for e in result.entries)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_actual_native_python_parity_including_matching_and_pages(case, monkeypatch):
    if native_module.native is None:
        pytest.skip("actual PyO3 module is unavailable; parity not verified")
    monkeypatch.setattr(va, "native", None)
    reference = build(case)
    monkeypatch.setattr(va, "native", native_module.native)
    actual = build(case)
    assert dataclasses.asdict(actual) == dataclasses.asdict(reference)
    for query in (None, "select", "choos", "DiscoveryPkg::select()", "unknown_xyz", "données"):
        for offset in (0, 1):
            for index in (reference, actual):
                if offset > len(index.ranked(query, "DiscoveryPkg")[0]):
                    continue
                assert actual.page("DiscoveryPkg", query, 2, offset) == reference.page(
                    "DiscoveryPkg", query, 2, offset
                )


@pytest.mark.parametrize(
    "namespace",
    [
        "export(a)+export(b)",
        "export(a) export(b)",
        "{export(a)}",
        "x <- export(a)",
        "if (TRUE) export(a)",
        "export(get('a'))",
        "export(a = b)",
        "eval(parse(text='export(a)'))",
    ],
)
def test_dynamic_or_embedded_calls_never_become_verified_exports(namespace):
    result = fd.parse_namespace(namespace)
    assert result["exports"] == []
    assert result["status"] == "partial"


def test_namespace_imports_are_not_exports_and_methods_are_separate():
    result = build(CASES[1])
    exports = {e["name"]: e for e in result.entries if e["kind"] == "export"}
    assert "import_only" not in exports and "print.Widget" not in exports
    assert exports["delegated"]["possible_reexport_from"] == ["OtherPkg"]
    assert exports["delegated"]["reexport_status"] == "possible"
    methods = [e for e in result.entries if e["kind"] == "method"]
    assert {e["method_kind"] for e in methods} == {"S3", "S4_export"}


def test_export_pattern_is_unresolved_not_an_empty_proven_export_set():
    result = build(CASES[2])
    assert result.patterns == ("^auto",)
    page = result.page("DiscoveryPkg", None, 50, 0)
    assert page["coverage"]["namespace"] == "partial"
    assert page["export_patterns"] == ["^auto"]


def test_literal_comments_escaping_and_unsupported_macros():
    assert fd.parse_namespace("# comment\nexport('a', \"b\") # x\n")["status"] == "verified"
    assert [x["name"] for x in fd.parse_namespace('export("caf\\u00e9")')["exports"]] == ["café"]
    assert fd.parse_namespace('export("\\q")')["status"] == "partial"
    files = files_for(CASES[0])
    files["DiscoveryPkg/man/macro.Rd"] = b"\\name{macro}\n\\Sexpr{stop('never')}\n"
    result = fd.build_discovery_index("DiscoveryPkg", {}, files)
    assert result.rd_status == "partial"


def test_bad_encoding_retains_safe_partial_topics():
    files = files_for(CASES[0])
    files["DiscoveryPkg/man/bad.Rd"] = b"\xff\xfe"
    result = fd.build_discovery_index("DiscoveryPkg", {}, files)
    assert result.rd_status == "partial"
    assert any(e["name"] == "select" for e in result.entries)


def test_exact_alias_topic_normalized_fuzzy_and_no_suggestion():
    result = build(CASES[0])
    for query, expected in (
        ("select", {"exact", "alias"}),
        ("choose", {"alias"}),
        ("selection", {"topic"}),
        ("DiscoveryPkg::select()", {"normalized"}),
        ("choos", {"fuzzy"}),
    ):
        matches = result.page("DiscoveryPkg", query, 50, 0)["matches"]
        assert expected <= {m["match_type"] for m in matches}
    assert result.suggestions("completely_unrelated_xyz", "DiscoveryPkg") == []
    suggestion = result.suggestions("choos", "DiscoveryPkg")[0]
    assert suggestion["name"] == "choose" and suggestion["alias_verified"] is True
    assert suggestion["export_status"] == "unknown"
    assert suggestion["match_type"] == "fuzzy"


def test_page_arrays_share_one_stream_and_have_explicit_counts():
    index = build(CASES[0])
    ids, offset = [], 0
    while True:
        page = index.page("DiscoveryPkg", None, 2, offset)
        ids.extend(m["id"] for m in page["matches"])
        assert page["returned"] == sum(len(page[c]) for c in fd.COLLECTIONS)
        for collection in fd.COLLECTIONS:
            assert page["collections"][collection]["returned"] == len(page[collection])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert len(ids) == len(set(ids)) == len(index.entries)
    assert ids == [e["id"] for e in index.entries]


def test_bounds_and_fuzzy_coverage(monkeypatch):
    with pytest.raises(KnowledgeError, match="256 KiB"):
        fd.parse_namespace("#" + "a" * (256 << 10))
    monkeypatch.setattr(fd, "MAX_ENTRIES", 1)
    with pytest.raises(KnowledgeError, match="entries"):
        build(CASES[0])
    monkeypatch.setattr(fd, "MAX_ENTRIES", 10000)
    monkeypatch.setattr(fd, "MAX_FUZZY_CANDIDATES", 1)
    assert (
        build(CASES[0]).page("DiscoveryPkg", "choos", 50, 0)["coverage"]["fuzzy_search_complete"]
        is False
    )


@pytest.fixture
async def discovery_service():
    tarball = archive(files_for(CASES[0]))
    md5 = hashlib.md5(tarball, usedforsecurity=False).hexdigest()
    routes = {
        INDEX: f"Package: DiscoveryPkg\nVersion: 1.0.0\nMD5sum: {md5}\n".encode(),
        "/src/contrib/DiscoveryPkg_1.0.0.tar.gz": tarball,
        "/web/packages/DiscoveryPkg/DESCRIPTION": DESCRIPTION.encode(),
    }
    calls = []

    def handler(request):
        calls.append(request.url.path)
        body = routes.get(request.url.path)
        return httpx.Response(200 if body is not None else 404, content=body or b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield KnowledgeService(CranHTTP(client)), routes, calls


async def call_discovery(api, **kwargs):
    return await bounded(api.list_package_functions("DiscoveryPkg", **kwargs))


async def test_verified_version_snapshot_payload_and_cached_index(discovery_service):
    api, _, calls = discovery_service
    first = await call_discovery(api, package_version="1.0.0", limit=2)
    assert first["verification_status"] == "verified"
    assert first["source_verification_level"] == "archive_checksum_verified"
    assert first["package_version"] == "1.0.0" and len(first["snapshot"]) == 64
    assert first["sources"] and len(json.dumps(first).encode()) <= 20 << 10
    provider = await api.provider("cran")
    cached = next(iter(provider._parsed.values()))["discovery"]
    second = await call_discovery(api, offset=first["next_offset"], snapshot=first["snapshot"])
    assert next(iter(provider._parsed.values()))["discovery"] is cached
    assert not ({m["id"] for m in first["matches"]} & {m["id"] for m in second["matches"]})
    assert calls.count("/src/contrib/DiscoveryPkg_1.0.0.tar.gz") == 1


async def test_errors_missing_version_archive_checksum_and_package(discovery_service):
    api, routes, _ = discovery_service
    wrong = await call_discovery(api, package_version="0.9")
    assert wrong["error"]["code"] == "requested_version_unavailable"
    missing = await bounded(api.list_package_functions("AbsentPkg"))
    assert missing["error"]["code"] == "package_not_found"
    routes.pop("/src/contrib/DiscoveryPkg_1.0.0.tar.gz")
    unavailable = await call_discovery(api)
    assert unavailable["error"]["code"] == "not_found"
    routes["/src/contrib/DiscoveryPkg_1.0.0.tar.gz"] = archive(
        {"DiscoveryPkg/DESCRIPTION": DESCRIPTION, "DiscoveryPkg/NAMESPACE": "export(changed)"}
    )
    checksum = await call_discovery(api)
    assert checksum["error"]["code"] == "checksum_mismatch"


async def test_docs_success_unchanged_and_missing_has_provenance(discovery_service):
    api, _, _ = discovery_service
    found = await api.get_versioned_function_docs("DiscoveryPkg", "select", package_version="1.0.0")
    assert "error" not in found and "\\alias{select}" in found["text"]
    assert not {"suggestions", "exports"} & found.keys()
    missing = await api.get_versioned_function_docs(
        "DiscoveryPkg", "choos", package_version="1.0.0"
    )
    assert missing["error"]["code"] == "docs_not_found"
    assert missing["error"]["message"] == "No literal Rd alias found in this package version"
    assert missing["package_version"] is None and len(missing["sources"]) == 2
    assert missing["checked_at"] is None
    assert missing["error"]["resolved_package_version"] == "1.0.0"
    assert missing["error"]["source_checked_at"]
    assert missing["error"]["requested_package_version"] == "1.0.0"
    assert missing["error"]["available_aliases"] == ["choose", "select"]
    assert missing["error"]["suggestions"][0]["alias_verified"] is True


async def test_source_drift_and_query_change_reject_continuation(discovery_service):
    api, routes, _ = discovery_service
    first = await call_discovery(api, limit=1)
    query_change = await call_discovery(api, query="select", offset=1, snapshot=first["snapshot"])
    assert query_change["error"]["code"] == "source_identity_drift"
    api.http.ttl = 0
    # Clear the TTL cache to simulate revalidation returning a new body at the same URL/version.
    api.http._cache.clear()
    api.http._bytes = 0
    tarball = archive({**files_for(CASES[0]), "DiscoveryPkg/NAMESPACE": "export(changed)\n"})
    routes["/src/contrib/DiscoveryPkg_1.0.0.tar.gz"] = tarball
    routes[INDEX] = b"Package: DiscoveryPkg\nVersion: 1.0.0\n"
    changed = await call_discovery(api, offset=1, snapshot=first["snapshot"])
    assert changed["error"]["code"] == "source_identity_drift"
    assert changed["sources"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 51},
        {"limit": True},
        {"offset": -1},
        {"offset": True},
        {"offset": 1},
        {"snapshot": "bad"},
        {"query": ""},
        {"query": "\n"},
        {"query": "a" * 201},
        {"repository": "all"},
        {"package_version": "../bad"},
    ],
)
async def test_invalid_inputs_never_fetch_archive(discovery_service, kwargs):
    api, _, calls = discovery_service
    result = await call_discovery(api, **kwargs)
    assert result["error"]["code"] == "invalid_input"
    assert not any(path.endswith(".tar.gz") for path in calls)


async def test_mcp_registration_schema_workflow_and_legacy_unchanged(discovery_service):
    api, _, _ = discovery_service
    async with create_connected_server_and_client_session(
        create_server(service=api, toolset="consolidated")
    ) as session:
        tools = (await session.list_tools()).tools
        tool = next(t for t in tools if t.name == "list_package_functions")
        assert tool.annotations.readOnlyHint
        assert tool.inputSchema["properties"]["repository"]["enum"] == ["cran", "bioconductor"]
        discovery = await session.call_tool(
            "list_package_functions",
            {"package": "DiscoveryPkg", "query": "choose", "package_version": "1.0.0"},
        )
        assert not discovery.isError
        alias = discovery.structuredContent["aliases"][0]["name"]
        docs = await session.call_tool(
            "get_function_docs",
            {"package": "DiscoveryPkg", "function": alias, "package_version": "1.0.0"},
        )
        assert not docs.isError
    async with create_connected_server_and_client_session(
        create_server(service=api, toolset="legacy")
    ) as session:
        assert "list_package_functions" not in {t.name for t in (await session.list_tools()).tools}


def test_archive_is_data_only_and_namespace_member_bounded(tmp_path):
    files = source_files(
        archive(
            {
                **files_for(CASES[0]),
                "DiscoveryPkg/R/zzz.R": "stop('never execute')",
                "../NAMESPACE": "export(injected)",
                "DiscoveryPkg/../NAMESPACE": "export(injected)",
            }
        ),
        "DiscoveryPkg",
    )
    assert files["DiscoveryPkg/NAMESPACE"] == CASES[0]["namespace"].encode()
    assert not any("/R/" in name or ".." in name for name in files)
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(KnowledgeError, match="2 MiB"):
        source_files(
            archive(
                {
                    "DiscoveryPkg/DESCRIPTION": DESCRIPTION,
                    "DiscoveryPkg/NAMESPACE": "a" * ((2 << 20) + 1),
                }
            ),
            "DiscoveryPkg",
        )


@pytest.mark.parametrize("namespace", ["export(,a)", "export(a,)", "export(a,,b)"])
def test_empty_namespace_arguments_are_partial(namespace):
    result = fd.parse_namespace(namespace)
    assert result["exports"] == [] and result["status"] == "partial"


def test_large_payload_is_paged_not_identity_truncated():
    long_names = ["x" * 150 + str(i) for i in range(70)]
    files = {
        "DiscoveryPkg/DESCRIPTION": DESCRIPTION.encode(),
        "DiscoveryPkg/NAMESPACE": ("export(" + ",".join(long_names) + ")\n").encode(),
    }
    for i, name in enumerate(long_names):
        files[f"DiscoveryPkg/man/topic{i}.Rd"] = (
            f"\\name{{topic{i}}}\n\\alias{{{name}}}\n"
        ).encode()
    index = fd.build_discovery_index("DiscoveryPkg", {}, files)
    page = index.page("DiscoveryPkg", None, 50, 0)
    assert page["returned"] < 50 and page["next_offset"] == page["returned"]
    assert len(json.dumps(page, ensure_ascii=False).encode()) < fd.PAGE_BYTES + 200
    assert all(m["name"] in long_names or m["name"].startswith("topic") for m in page["matches"])


async def test_checksum_revalidation_checks_cached_archive(discovery_service):
    api, routes, _ = discovery_service
    assert "error" not in await call_discovery(api)
    # Revalidate the index while the archive remains in the HTTP/parsed cache.
    routes[INDEX] = (
        b"Package: DiscoveryPkg\nVersion: 1.0.0\nMD5sum: 00000000000000000000000000000000\n"
    )
    api.http._cache.pop(INDEX)
    result = await call_discovery(api)
    assert result["error"]["code"] == "checksum_mismatch"


async def test_version_race_never_substitutes_archive(discovery_service, monkeypatch):
    api, _, _ = discovery_service
    provider = await api.provider("cran")
    original = provider.source

    async def changed(package):
        metadata, files, artifact, index = await original(package)
        return {**metadata, "Version": "2.0.0"}, files, artifact, index

    monkeypatch.setattr(provider, "source", changed)
    result = await call_discovery(api, package_version="1.0.0")
    assert result["error"]["code"] == "requested_version_unavailable"
    docs = await api.get_versioned_function_docs("DiscoveryPkg", "select", package_version="1.0.0")
    assert docs["error"]["code"] == "requested_version_unavailable"


def test_no_native_selection_remains_explicit(monkeypatch):
    monkeypatch.setenv("R_KNOWLEDGE_NATIVE", "0")
    assert native_module._load() is None
    monkeypatch.setattr(va, "native", None)
    assert build(CASES[0]).namespace_status == "verified"


def test_actual_native_binding_rejects_oversized_and_nontext_inputs():
    if native_module.native is None:
        pytest.skip("PyO3 unavailable; binding checks not verified")
    with pytest.raises(ValueError) as error:
        native_module.native.scan_calls("a" * ((256 << 10) + 1))
    assert error.value.args[0] == "input_too_large"
    with pytest.raises(TypeError):
        native_module.native.scan_calls(b"\xff")


async def test_feature_flag_changes_only_tool_availability(discovery_service, monkeypatch):
    api, _, _ = discovery_service
    monkeypatch.setenv("FUNCTION_DISCOVERY_ENABLED", "true")
    enabled = create_server(service=api, toolset="consolidated")
    async with create_connected_server_and_client_session(enabled) as session:
        treatment = {tool.name: tool.model_dump() for tool in (await session.list_tools()).tools}
    monkeypatch.setenv("FUNCTION_DISCOVERY_ENABLED", "false")
    disabled = create_server(service=api, toolset="consolidated")
    async with create_connected_server_and_client_session(disabled) as session:
        control = {tool.name: tool.model_dump() for tool in (await session.list_tools()).tools}
    assert enabled.instructions == disabled.instructions
    treatment.pop("list_package_functions")
    assert treatment == control
    monkeypatch.setenv("FUNCTION_DISCOVERY_ENABLED", "invalid")
    with pytest.raises(KnowledgeError, match="boolean"):
        create_server(service=api, toolset="consolidated")


def test_rd_comments_cannot_create_topics_and_empty_index_is_explicit():
    from cran_knowledge_mcp.parsers import rd_index_record

    topic, names, complete, source = rd_index_record(
        "DiscoveryPkg/man/file.Rd", "% \\name{fake}\n\\alias{real}\n"
    )
    assert topic == "file" and names == ["real"] and not complete
    assert source == "archive_filename"
    index = fd.build_discovery_index(
        "DiscoveryPkg",
        {},
        {
            "DiscoveryPkg/NAMESPACE": b"",
            "DiscoveryPkg/DESCRIPTION": DESCRIPTION.encode(),
        },
    )
    page = index.page("DiscoveryPkg", None, 20, 0)
    assert page["total_matches"] == 0 and page["next_offset"] is None
    assert all(c["source_status"] == "verified" for c in page["collections"].values())


@pytest.mark.parametrize("name", ["_invalid", "if", "function", "NULL", "NA_real_"])
def test_non_symbol_bare_namespace_arguments_cannot_be_verified(name):
    parsed = fd.parse_namespace(f"export({name})")
    assert parsed["exports"] == [] and parsed["status"] == "partial"
    quoted = fd.parse_namespace(f'export("{name}")')
    assert [e["name"] for e in quoted["exports"]] == [name]


def test_distinct_generics_using_one_method_symbol_keep_separate_identity(monkeypatch):
    files = {
        "DiscoveryPkg/DESCRIPTION": DESCRIPTION.encode(),
        "DiscoveryPkg/NAMESPACE": (
            b"S3method(print, Widget, shared_method)\nS3method(format, Widget, shared_method)\n"
        ),
    }
    monkeypatch.setattr(va, "native", None)
    reference = fd.build_discovery_index("DiscoveryPkg", {}, files)
    methods = [e for e in reference.entries if e["kind"] == "method"]
    assert len(methods) == 2 and len({e["id"] for e in methods}) == 2
    assert {e["generic"] for e in methods} == {"print", "format"}
    if native_module.native is not None:
        monkeypatch.setattr(va, "native", native_module.native)
        actual = fd.build_discovery_index("DiscoveryPkg", {}, files)
        assert dataclasses.asdict(actual) == dataclasses.asdict(reference)
