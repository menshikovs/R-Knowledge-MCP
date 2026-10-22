import pytest
from conftest import DESCRIPTION, RD, archive

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.http import CATALOG, INDEX
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


async def test_response_bound():
    async def operation():
        return {"text": "x" * 60001}

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
