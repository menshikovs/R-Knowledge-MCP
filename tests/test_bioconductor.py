"""Real package names with deliberately synthetic versions; no live network."""

import gzip

import httpx
import pytest
from conftest import archive

from cran_knowledge_mcp.http import CATALOG, INDEX, CranHTTP
from cran_knowledge_mcp.providers import BioconductorProvider, CranProvider, PackageRepository
from cran_knowledge_mcp.service import KnowledgeService, bounded

CONFIG = b"""release_version: "9.40"
devel_version: "9.41"
r_ver_for_bioc_ver:
  "9.38": "4.3"
  "9.39": "4.4"
  "9.40": "4.4"
  "9.41": "4.5"
"""
SOFTWARE = b"""Package: DESeq2
Version: 999.1
Depends: R (>= 4.4.1), BiocGenerics (>= 999.0)
Imports: ggplot2 (>= 3.4.0), methods
Suggests: ExampleData, org.Example.db

Package: BiocGenerics
Version: 999.0
Depends: R (>= 4.0)
"""
CRAN = b"""Package: ggplot2
Version: 900.0
Depends: R (>= 4.0)
License: MIT
"""
DESC = """Package: DESeq2
Version: 999.1
Title: Synthetic Bioconductor fixture
Description: Test only, not real package metadata.
Author: Test
License: MIT
"""


@pytest.fixture
async def bioc_service():
    routes = {
        ("bioconductor.org", "/config.yaml"): CONFIG,
        ("cran.r-project.org", INDEX): CRAN,
        ("cran.r-project.org", CATALOG): b"<tr><td>ggplot2</td><td>Synthetic Plotting</td></tr>",
    }
    for version in ("9.38", "9.39", "9.40", "9.41"):
        for category, content in (
            ("bioc", SOFTWARE),
            (
                "data/annotation",
                b"Package: org.Example.db\nVersion: 999.0\n"
                b"\nPackage: org.Hs.eg.db\nVersion: 999.2\nLicense: Artistic-2.0\n",
            ),
            (
                "data/experiment",
                b"Package: ExampleData\nVersion: 999.0\n"
                b"\nPackage: scRNAseq\nVersion: 999.3\nLicense: Artistic-2.0\n",
            ),
        ):
            routes[("bioconductor.org", f"/packages/{version}/{category}/src/contrib/PACKAGES")] = (
                content
            )
        routes[
            ("bioconductor.org", f"/packages/{version}/bioc/src/contrib/DESeq2_999.1.tar.gz")
        ] = archive(
            {
                "DESeq2/DESCRIPTION": DESC,
                "DESeq2/man/DESeq.Rd": r"\alias{DESeq}\title{Test only}",
            }
        )
        routes[("bioconductor.org", f"/packages/{version}/bioc/html/DESeq2.html")] = (
            "<table><tr><td>Version</td><td>999.1</td></tr></table>"
            f'<a href="/packages/{version}/bioc/vignettes/DESeq2/inst/doc/test.html">HTML</a>'
            '<a href="http://127.0.0.1/private">evil</a>'
            '<a href="https://evil.test/test.pdf">evil</a>'
            '<a href="/packages/release/bioc/vignettes/DESeq2/inst/doc/test.html">unpinned</a>'
        ).encode()
    calls = []

    def handler(request):
        calls.append(request)
        content = routes.get((request.url.host, request.url.path))
        plain = (request.url.host, request.url.path.removesuffix(".gz"))
        if content is None and request.url.path.endswith("/PACKAGES.gz") and plain in routes:
            # Like the official mirrors, serve the compressed index next to the plain one.
            content = routes[plain]
            content = content if isinstance(content, int) else gzip.compress(content)
        if isinstance(content, int):
            return httpx.Response(content)
        return httpx.Response(404 if content is None else 200, content=content or b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield KnowledgeService(CranHTTP(client)), routes, calls


async def test_independent_provider_contract(bioc_service):
    api, _, _ = bioc_service
    assert isinstance(await api.provider("cran"), CranProvider)
    assert isinstance(await api.provider("cran"), PackageRepository)
    assert isinstance(await api.provider("bioconductor"), BioconductorProvider)
    assert isinstance(await api.provider("bioconductor"), PackageRepository)


async def test_search_deseq2_and_ggplot2(bioc_service):
    api, _, _ = bioc_service
    bioc = await api.search_packages("DESeq2", repository="bioconductor")
    result = bioc["results"][0]
    assert result["package"] == "DESeq2"
    assert result["repository"] == "bioconductor"
    assert result["package_version"] == "999.1"
    assert result["bioc_version"] == "9.40"
    assert result["verification_status"] == "verified"
    assert result["source_url"] and result["checked_at"]
    cran = await api.search_packages("ggplot2", repository="cran")
    assert cran["results"][0]["package"] == "ggplot2"
    assert cran["results"][0]["repository"] == "cran"
    assert cran["results"][0]["bioc_version"] is None


async def test_cross_repository_dependencies(bioc_service):
    api, _, _ = bioc_service
    result = await api.get_dependencies("DESeq2", "bioconductor", "release")
    resolved = {r["package"]: r for r in result["resolved_dependencies"]}
    assert resolved["ggplot2"]["candidates"][0]["repository"] == "cran"
    assert resolved["BiocGenerics"]["candidates"][0]["repository"] == "bioconductor"
    assert resolved["ExampleData"]["candidates"][0]["bioc_version"] == "9.40"
    assert resolved["org.Example.db"]["resolution"] == "found"
    assert resolved["methods"]["resolution"] == "r_runtime"
    assert resolved["ggplot2"]["candidates"][0]["constraint_satisfied"] is True
    assert result["dependencies"]["Imports"] == "ggplot2 (>= 3.4.0), methods"


async def test_dynamic_r_mapping_and_no_implicit_devel(bioc_service):
    api, _, _ = bioc_service
    result = await api.get_bioconductor_version("4.4.2")
    assert result["recommended_bioc_version"] == "9.40"
    assert [r["bioc_version"] for r in result["releases"]] == ["9.39", "9.40"]
    future = await api.get_bioconductor_version("4.5.0")
    assert future["recommended_bioc_version"] is None
    assert future["releases"][0]["channel"] == "devel"
    unknown = await api.get_bioconductor_version("99.0.0")
    assert unknown["releases"] == []
    assert unknown["warnings"]


@pytest.mark.parametrize(
    ("selection", "version", "channel"),
    [
        ("release", "9.40", "release"),
        ("stable", "9.40", "release"),
        ("devel", "9.41", "devel"),
        ("9.38", "9.38", "historical"),
    ],
)
async def test_pinned_metadata_docs_and_channels(bioc_service, selection, version, channel):
    api, _, calls = bioc_service
    info = await api.get_package_info("DESeq2", "bioconductor", selection)
    assert info["bioc_version"] == version and info["channel"] == channel
    assert info["package_version"] == "999.1"
    assert "latest_cran_version" not in info
    assert info["warnings"] and info["compatibility_status"] == "not_checked"
    docs = await api.get_function_docs(
        "DESeq2", "DESeq", repository="bioconductor", bioc_version=selection
    )
    assert docs["text"] == r"\alias{DESeq}\title{Test only}"
    assert docs["bioc_version"] == version
    assert f"/packages/{version}/" in docs["source_url"]
    assert all("/packages/release/" not in r.url.path for r in calls)


@pytest.mark.parametrize(
    ("package", "selection", "version", "category"),
    [
        ("DESeq2", "release", "999.1", "software"),
        ("org.Hs.eg.db", "release", "999.2", "annotation"),
        ("scRNAseq", "release", "999.3", "experiment"),
        ("DESeq2", "9.38", "999.1", "software"),
    ],
)
async def test_lightweight_bioconductor_metadata_uses_selected_category_index(
    bioc_service, package, selection, version, category
):
    api, _, calls = bioc_service
    result = await api.get_package_info(
        package, repository="bioconductor", bioc_version=selection, verify_archive=False
    )
    assert result["package_version"] == version
    assert result["metadata_verification_level"] == "index_verified"
    assert result["category"] == category
    assert result["verification_status"] == "verified"
    assert result["bioc_version"] == ("9.38" if selection == "9.38" else "9.40")
    assert result["metadata_fields_missing"]
    assert not any(request.url.path.endswith(".tar.gz") for request in calls)
    assert any(f"/packages/{result['bioc_version']}/" in s["source_url"] for s in result["sources"])


async def test_large_bioconductor_index_metadata_avoids_archive_transfer(bioc_service):
    api, routes, calls = bioc_service
    result = await api.get_package_info("scRNAseq", "bioconductor", "release", verify_archive=False)
    assert result["category"] == "experiment"
    assert result["metadata_verification_level"] == "index_verified"
    assert len(calls) == 4  # config plus the three release-scoped compressed category indexes
    assert {(request.url.host, request.url.path) for request in calls} == {
        ("bioconductor.org", "/config.yaml"),
        ("bioconductor.org", "/packages/9.40/bioc/src/contrib/PACKAGES.gz"),
        ("bioconductor.org", "/packages/9.40/data/annotation/src/contrib/PACKAGES.gz"),
        ("bioconductor.org", "/packages/9.40/data/experiment/src/contrib/PACKAGES.gz"),
    }
    assert not any(request.url.path.endswith(".tar.gz") for request in calls)


async def test_compatibility_r_mapping_and_patch_constraints(bioc_service):
    api, _, _ = bioc_service
    good = await api.check_package_compatibility("DESeq2", "4.4.2", "release")
    assert good["compatible"] is True and good["compatibility_status"] == "metadata_compatible"
    bad_patch = await api.check_package_compatibility("DESeq2", "4.4.0", "release")
    assert bad_patch["compatible"] is False
    bad_release = await api.check_package_compatibility("DESeq2", "4.3.3", "release")
    assert bad_release["compatible"] is False and bad_release["warnings"]
    assert not any("R version not supplied" in w for w in good["warnings"])


async def test_missing_package_in_selected_release_does_not_fall_back(bioc_service):
    api, routes, _ = bioc_service
    routes[("bioconductor.org", "/packages/9.38/bioc/src/contrib/PACKAGES")] = (
        b"Package: Other\nVersion: 1.0\n"
    )
    result = await api.get_package_info("DESeq2", "bioconductor", "9.38")
    assert result["error"]["code"] == "package_not_found"
    assert result["bioc_version"] == "9.38"
    assert result["verification_status"] == "failed"


@pytest.mark.parametrize(
    "path",
    [
        "/config.yaml",
        "/packages/9.40/bioc/src/contrib/PACKAGES",
        "/packages/9.40/data/annotation/src/contrib/PACKAGES",
        "/packages/9.40/data/experiment/src/contrib/PACKAGES",
    ],
)
async def test_unavailable_official_sources_explicit(bioc_service, path):
    api, routes, _ = bioc_service
    routes[("bioconductor.org", path)] = 503
    result = await api.get_dependencies("DESeq2", "bioconductor")
    assert result["error"]["code"] == "source_unavailable"
    assert result["verification_status"] == "failed"
    # Category indexes are fetched as PACKAGES.gz; the failure names that route.
    suffix = ".gz" if path.endswith("/PACKAGES") else ""
    assert result["source_url"] == "https://bioconductor.org" + path + suffix


async def test_vignettes_only_official_pinned_links(bioc_service):
    api, _, _ = bioc_service
    result = await api.get_package_vignettes("DESeq2", "bioconductor")
    assert result["package_version"] == "999.1"
    assert result["content_fetched"] is False
    assert len(result["vignettes"]) == 1
    assert (
        result["vignettes"][0]["url"]
        == "https://bioconductor.org/packages/9.40/bioc/vignettes/DESeq2/inst/doc/test.html"
    )


async def test_all_explicit_partial_results_and_pagination(bioc_service):
    api, routes, _ = bioc_service
    result = await api.get_dependencies("DESeq2", "all")
    assert result["results"][0]["repository"] == "bioconductor"
    assert result["errors"][0]["error"]["code"] == "package_not_found"
    assert result["verification_status"] == "verified"
    # Empty query is rejected by each provider, rather than silently searching everything.
    result = await api.search_packages(" ", repository="all")
    assert result["verification_status"] == "failed"
    api.bioc_http._cache.clear()
    api.bioc_http._bytes = 0
    routes[("bioconductor.org", "/config.yaml")] = 503
    result = await api.search_packages("ggplot2", repository="all")
    assert result["results"][0]["package"] == "ggplot2"
    assert result["verification_status"] == "partial"
    assert result["errors"][0]["error"]["code"] == "source_unavailable"


@pytest.mark.parametrize("value", ["../../etc", "https://evil.test", "3.23/bioc", "1.2?x", "99.99"])
async def test_bioc_selection_validation(bioc_service, value):
    api, _, calls = bioc_service
    result = await api.get_package_info("DESeq2", "bioconductor", value)
    assert result["error"]["code"] in {"invalid_input", "release_not_found"}
    assert all(r.url.path == "/config.yaml" for r in calls)


async def test_unknown_r_compatibility_not_invented(bioc_service):
    api, _, _ = bioc_service
    result = await bounded(api.check_package_compatibility("DESeq2", "99.0.0"))
    assert result["error"]["code"] == "no_compatible_release"


async def test_cran_dependencies_can_resolve_bioconductor_explicitly(bioc_service):
    api, routes, _ = bioc_service
    routes[("cran.r-project.org", INDEX)] = CRAN.replace(
        b"License: MIT", b"Suggests: BiocGenerics\nLicense: MIT"
    )
    result = await api.get_dependencies("ggplot2", "cran", "9.38", resolve_repositories=True)
    assert result["repository"] == "cran" and result["bioc_version"] is None
    assert result["dependency_bioc_version"] == "9.38"
    generics = next(d for d in result["resolved_dependencies"] if d["package"] == "BiocGenerics")
    assert generics["candidates"][0]["repository"] == "bioconductor"
    assert generics["candidates"][0]["bioc_version"] == "9.38"


async def test_bioconductor_mcp_protocol_and_selector_schema(bioc_service):
    from mcp.shared.memory import create_connected_server_and_client_session

    from cran_knowledge_mcp.server import create_server

    api, _, _ = bioc_service
    server = create_server(service=api, toolset="legacy")
    async with create_connected_server_and_client_session(server) as session:
        tools = (await session.list_tools()).tools
        search = next(t for t in tools if t.name == "search_packages")
        assert search.inputSchema["properties"]["repository"]["enum"] == [
            "cran",
            "bioconductor",
            "all",
        ]
        result = await session.call_tool(
            "get_package_info",
            {
                "package": "DESeq2",
                "repository": "bioconductor",
                "bioc_version": "devel",
            },
        )
        assert result.structuredContent["bioc_version"] == "9.41"
        result = await session.call_tool(
            "check_package_compatibility",
            {
                "package": "DESeq2",
                "r_version": "4.4.2",
                "bioc_version": "release",
            },
        )
        assert result.structuredContent["compatibility_status"] == "metadata_compatible"


@pytest.mark.parametrize(
    ("package", "category"), [("org.Example.db", "annotation"), ("ExampleData", "experiment")]
)
async def test_data_package_categories(bioc_service, package, category):
    api, _, _ = bioc_service
    result = await api.search_packages(package, repository="bioconductor")
    assert result["results"][0]["category"] == category
    result = await api.get_dependencies(package, "bioconductor")
    assert result["category"] == category
    assert result["package_version"] == "999.0"


@pytest.mark.parametrize(
    "config",
    [
        b"<html>maintenance</html>",
        b"null",
        b"!!python/object:fake {}",
        b'release_version: "9.40"\ndevel_version: "9.41"\nr_ver_for_bioc_ver: {}',
    ],
)
async def test_malformed_or_unsafe_release_config(bioc_service, config):
    api, routes, _ = bioc_service
    routes[("bioconductor.org", "/config.yaml")] = config
    result = await api.get_package_info("DESeq2", "bioconductor")
    assert result["error"]["code"] == "invalid_source"
    assert result["source_url"] == "https://bioconductor.org/config.yaml"


async def test_incompatible_dependency_r_requirement(bioc_service):
    api, routes, _ = bioc_service
    routes[("cran.r-project.org", INDEX)] = CRAN.replace(b"R (>= 4.0)", b"R (>= 4.5)")
    result = await api.check_package_compatibility("DESeq2", "4.4.2")
    assert result["compatible"] is False
    assert any("ggplot2" in warning for warning in result["warnings"])


async def test_unknown_dependency_prevents_compatibility_claim(bioc_service):
    api, routes, _ = bioc_service
    path = ("bioconductor.org", "/packages/9.40/bioc/src/contrib/PACKAGES")
    routes[path] = SOFTWARE.replace(b"ggplot2 (>= 3.4.0)", b"MissingPackage (>= 1.0)")
    result = await api.check_package_compatibility("DESeq2", "4.4.2")
    assert result["compatible"] is None
    assert result["compatibility_status"] == "unknown"


async def test_version_mismatch_on_vignette_page(bioc_service):
    api, routes, _ = bioc_service
    path = ("bioconductor.org", "/packages/9.40/bioc/html/DESeq2.html")
    routes[path] = routes[path].replace(b"999.1", b"999.2")
    result = await api.get_package_vignettes("DESeq2", "bioconductor")
    assert result["error"]["code"] == "version_mismatch"


async def test_cran_vignette_page_version_and_links(bioc_service):
    api, routes, _ = bioc_service
    routes[("cran.r-project.org", "/web/packages/ggplot2/index.html")] = (
        b"<table><tr><td>Version:</td><td>900.0</td></tr></table>"
        b'<a href="vignettes/example.html">Synthetic vignette</a>'
    )
    result = await api.get_package_vignettes("ggplot2")
    assert (
        result["vignettes"][0]["url"]
        == "https://cran.r-project.org/web/packages/ggplot2/vignettes/example.html"
    )


async def test_all_search_keeps_duplicate_package_identities_and_pages(bioc_service):
    api, routes, _ = bioc_service
    path = ("bioconductor.org", "/packages/9.40/bioc/src/contrib/PACKAGES")
    routes[path] = SOFTWARE + b"\nPackage: ggplot2\nVersion: 777.0\n"
    first = await api.search_packages("ggplot2", limit=1, repository="all")
    second = await api.search_packages(
        "ggplot2", limit=1, offset=first["next_offset"], repository="all"
    )
    assert first["total"] == 2
    assert first["results"][0]["repository"] == "cran"
    assert second["results"][0]["repository"] == "bioconductor"
    assert second["next_offset"] is None


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.test/",
        "//127.0.0.1/private",
        "/packages/release/bioc/src/contrib/PACKAGES",
        "/packages/9.40/bioc/src/contrib/../secret",
        "/packages/9.40/bioc/src/contrib/PACKAGES?x=1",
    ],
)
async def test_bioconductor_ssrf_routes_rejected(bioc_service, path):
    from cran_knowledge_mcp.errors import KnowledgeError

    api, _, calls = bioc_service
    with pytest.raises(KnowledgeError, match="fixed"):
        await api.bioc_http.fetch(path)
    assert not calls


async def test_function_discovery_release_category_and_cache_separation(bioc_service):
    api, _, _ = bioc_service
    a = await api.list_package_functions("DESeq2", repository="bioconductor", bioc_version="9.40")
    b = await api.list_package_functions("DESeq2", repository="bioconductor", bioc_version="9.41")
    assert a["bioc_version"] == "9.40" and b["bioc_version"] == "9.41"
    assert a["category"] == "software" and a["required_r_version"] == "4.4"
    assert a["snapshot"] != b["snapshot"]
    assert a["coverage"]["namespace"] == "unavailable"
    assert a["verification_status"] == "partial"
