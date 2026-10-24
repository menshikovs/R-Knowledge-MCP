import json

import pytest
from conftest import DESCRIPTION, RD, archive

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.http import CATALOG, INDEX
from cran_knowledge_mcp.providers import base, cran
from cran_knowledge_mcp.providers.base import PackageSearchIndex
from cran_knowledge_mcp.service import bounded


async def test_all_tools_and_provenance(service):
    api, _, calls = service
    search = await api.search_packages("synthetic data")
    assert len(search["results"]) == 1
    assert {k: search["results"][0][k] for k in ("package", "title", "latest_cran_version")} == {
        "package": "ExamplePkg",
        "title": "Synthetic Data Tools",
        "latest_cran_version": "2.10-1",
    }
    info = await api.get_package_info("ExamplePkg")
    assert info["authors"] == "Test Author"
    assert info["license"] == "MIT"
    assert info["installed_version"] is None
    assert info["latest_cran_version"] == "2.10-1"
    assert info["metadata_verification_level"] == "description_version_matched"
    deps = await api.get_dependencies("ExamplePkg")
    assert deps["dependencies"] == {
        "Depends": "R (>= 4.1)",
        "Imports": "stats, other (>= 1.0)",
        "Suggests": "testthat, knitr",
        "LinkingTo": "",
        "Enhances": "",
    }
    docs = await api.get_function_docs("ExamplePkg", "example_alias")
    assert docs["text"] == RD
    assert docs["package_version"] == info["latest_cran_version"]
    assert docs["archive_member"] == "ExamplePkg/man/example.Rd"
    assert docs["sources"][1]["source_url"].endswith("ExamplePkg_2.10-1.tar.gz")
    for result in (info, deps, search, docs):
        assert all(
            s["checked_at"] and s["source_url"].startswith("https://cran.r-project.org/")
            for s in result["sources"]
        )
    assert len(calls) == 3  # index, catalog, archive; subsequent reads use cache


@pytest.mark.parametrize(
    ("installed", "relation"),
    [
        ("2.9", "older"),
        ("2.10.1.0", "equal"),
        ("2.10-1", "equal"),
        ("3.0", "newer"),
    ],
)
async def test_r_version_comparison(service, installed, relation):
    api, _, _ = service
    result = await api.check_package_version("ExamplePkg", installed)
    assert result["comparison"] == relation
    assert result["installed_version"] == installed


async def test_search_pagination(service):
    api, _, _ = service
    first = await api.search_packages("tools", limit=1)
    second = await api.search_packages("tools", limit=1, offset=first["next_offset"])
    assert first["total"] == 2
    assert first["results"][0] != second["results"][0]
    assert second["next_offset"] is None


@pytest.mark.parametrize(
    "name", ["../etc/passwd", "https://localhost/a", "x/y", "x?y", "", "a%2fb"]
)
async def test_invalid_package_never_requests(service, name):
    api, _, calls = service
    result = await bounded(api.get_package_info(name))
    assert result["error"]["code"] == "invalid_input"
    assert calls == []


async def test_missing_package_and_docs_are_errors(service):
    api, _, _ = service
    assert (await bounded(api.get_dependencies("Missing")))["error"]["code"] == "package_not_found"
    assert (await bounded(api.get_function_docs("ExamplePkg", "missing")))["error"][
        "code"
    ] == "docs_not_found"


async def test_mismatched_source_version(service):
    api, routes, _ = service
    routes["/src/contrib/ExamplePkg_2.10-1.tar.gz"] = archive(
        {
            "ExamplePkg/DESCRIPTION": DESCRIPTION.replace("2.10-1", "9.0"),
        }
    )
    result = await bounded(api.get_package_info("ExamplePkg"))
    assert result["error"]["code"] == "version_mismatch"


async def test_no_silent_catalog_fallback(service):
    api, routes, _ = service
    routes[CATALOG] = b"<html>upstream maintenance</html>"
    assert (await bounded(api.search_packages("test")))["error"]["code"] == "invalid_source"


async def test_invalid_index(service):
    api, routes, _ = service
    routes[INDEX] = b"<html>maintenance</html>"
    assert (await bounded(api.get_dependencies("ExamplePkg")))["error"]["code"] == "invalid_source"


async def test_document_pagination(service):
    api, routes, _ = service
    text = RD + ("x" * 9000)
    routes["/src/contrib/ExamplePkg_2.10-1.tar.gz"] = archive(
        {
            "ExamplePkg/DESCRIPTION": DESCRIPTION,
            "ExamplePkg/man/example.Rd": text,
        }
    )
    first = await api.get_function_docs("ExamplePkg", "example")
    second = await api.get_function_docs("ExamplePkg", "example", first["next_offset"])
    assert first["truncated"] is True
    assert second["next_offset"] is None
    assert first["text"] + second["text"] == text


@pytest.mark.parametrize("version", ["v1.0", "1.2rc1", "", "-1", "1/2"])
async def test_invalid_installed_version(service, version):
    api, _, calls = service
    result = await bounded(api.check_package_version("ExamplePkg", version))
    assert result["error"]["code"] == "invalid_input"
    assert not calls


async def test_response_bound_truncates_long_text_and_records_the_cut():
    async def operation():
        return {
            "package": "ExamplePkg",
            "sections": {"guidance": {"files": [{"path": "AGENTS.md", "text": "x" * 90000}]}},
            "sources": [{"source_url": "https://example.test", "checked_at": "now"}],
        }

    result = await bounded(operation())
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 60_000
    assert result["package"] == "ExamplePkg"
    assert result["sources"] == [{"source_url": "https://example.test", "checked_at": "now"}]
    text = result["sections"]["guidance"]["files"][0]["text"]
    assert text.startswith("xxx") and text.endswith("[truncated by server output limit]")
    truncation = result["output_truncation"]
    assert truncation["truncated"] is True
    assert truncation["fields"][0]["field"] == "sections.guidance.files[0].text"
    assert truncation["fields"][0]["original_characters"] == 90000


async def test_response_bound_still_fails_when_text_cannot_be_shortened_enough():
    async def operation():
        return {"items": [f"value-{index}" for index in range(10000)]}

    assert (await bounded(operation()))["error"]["code"] == "response_too_large"


async def test_bounded_turns_invalid_unicode_results_into_tool_errors():
    async def operation():
        return {"text": "\ud800"}

    result = await bounded(operation())
    assert result["verification_status"] == "failed"
    assert result["error"]["code"] == "invalid_input"


async def test_bounded_hides_unexpected_exception_details(caplog):
    async def operation():
        raise RuntimeError("private implementation detail")

    result = await bounded(operation())
    assert result["error"]["code"] == "internal_error"
    assert "private implementation detail" not in str(result)
    assert "RuntimeError" in caplog.text
    assert "operation=operation" in caplog.text
    assert "private implementation detail" not in caplog.text
    assert "Traceback" not in caplog.text


async def test_expected_input_errors_do_not_log_internal_tracebacks(caplog):
    async def invalid_operation():
        raise KnowledgeError("invalid_input", "Expected validation failure")

    result = await bounded(invalid_operation())
    assert result["error"]["code"] == "invalid_input"
    assert not caplog.records


async def test_prompt_and_credential_like_exception_text_is_not_logged_by_default(
    caplog, monkeypatch
):
    monkeypatch.delenv("LOG_INTERNAL_TRACEBACKS", raising=False)
    sensitive_prompt = "user asks to reveal a private dataset"
    credential = "token=super-secret-value"

    async def failing_operation():
        raise RuntimeError(f"{sensitive_prompt}; {credential}")

    caplog.set_level("DEBUG")
    result = await bounded(failing_operation())
    assert result["error"]["code"] == "internal_error"
    assert "operation=failing_operation" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert sensitive_prompt not in caplog.text
    assert credential not in caplog.text
    assert "Traceback" not in caplog.text


async def test_repeated_function_docs_reuse_one_verified_archive_parse(service, monkeypatch):
    api, _, calls = service
    parses = []
    original = base.source_files

    def counting(body, package):
        parses.append(package)
        return original(body, package)

    monkeypatch.setattr(base, "source_files", counting)
    first = await api.get_function_docs("ExamplePkg", "example")
    second = await api.get_function_docs("ExamplePkg", "example_alias")
    assert first["archive_member"] == second["archive_member"] == "ExamplePkg/man/example.Rd"
    assert parses == ["ExamplePkg"]
    assert sum(call.url.path.endswith(".tar.gz") for call in calls) == 1


async def test_title_catalog_is_parsed_once_per_fetched_artifact(service, monkeypatch):
    api, _, _ = service
    parses = []
    original = cran._parse_catalog

    def counting(artifact):
        parses.append(artifact.source_url)
        return original(artifact)

    monkeypatch.setattr(cran, "_parse_catalog", counting)
    assert (await api.search_packages("synthetic"))["total"] == 1
    assert (await api.search_packages("data tools"))["total"] == 1
    assert len(parses) == 1


async def test_package_knowledge_reads_description_without_downloading_archive(service):
    api, _, calls = service
    result = await api.get_package_knowledge("ExamplePkg")
    info = result["sections"]["package_info"]
    assert info["metadata_verification_level"] == "description_version_matched"
    assert info["urls"] == "https://example.invalid"
    assert not any(call.url.path.endswith(".tar.gz") for call in calls)


async def test_package_knowledge_falls_back_to_archive_without_description_page(service):
    api, routes, calls = service
    del routes["/web/packages/ExamplePkg/DESCRIPTION"]
    result = await api.get_package_knowledge("ExamplePkg")
    info = result["sections"]["package_info"]
    assert info["verification_status"] == "verified"
    assert info["metadata_verification_level"] != "index_verified"
    assert info["urls"] == "https://example.invalid"
    assert any(call.url.path.endswith(".tar.gz") for call in calls)


def test_package_search_ranks_names_before_titles_and_requires_word_matches():
    index = PackageSearchIndex(
        [
            ("rapidapi", "Rapid helpers"),
            ("plumber", "An API Generator for R"),
            ("therapy", "Tools for therapist schedules"),
            ("api2lm", "Functions for linear models"),
            ("httr2", "Perform HTTP requests and process the responses; web APIs"),
            ("ggplot2", "Create Elegant Data Visualisations"),
            ("data.table", "Extension of data.frame"),
        ]
    )
    # 'api' never matches inside 'therapy'/'therapist'; name matches outrank title words.
    assert index.search("api") == ["api2lm", "rapidapi", "plumber", "httr2"]
    assert index.search("plot")[0] == "ggplot2"
    assert index.search("data.table") == ["data.table"]
    assert index.search("visual table") == []
    assert index.search("api generator") == ["plumber"]
