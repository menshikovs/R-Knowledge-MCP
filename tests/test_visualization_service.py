import pytest

from cran_knowledge_mcp.errors import KnowledgeError


async def test_explicit_renv_lock_version_is_reported_as_client_supplied(service):
    api, _, _ = service
    result = await api.analyze_ggplot_code(
        "ggplot(data) + geom_point()",
        renv_lock='{"Packages":{"ggplot2":{"Version":"3.5.0"}}}',
    )
    assert result["package_versions"]["ggplot2"] == {
        "renv_lock_version": "3.5.0",
        "verification_status": "client_supplied_lock_unverified",
        "version_scope": "renv_lock_not_installed_version",
    }
    assert result["renv_lock_checked"] is False


async def test_requested_version_check_surfaces_unavailable_cran_source(service):
    api, _, _ = service
    result = await api.analyze_ggplot_code("ggplot(data)", package_versions={"ggplot2": "3.5.0"})
    assert result["verification_status"] == "partial"
    assert result["package_versions"]["ggplot2"]["verification_status"] == "failed"
    assert result["package_versions"]["ggplot2"]["error"]["code"] == "package_not_found"


async def test_visualization_docs_only_accept_curated_packages(service):
    api, _, _ = service
    with pytest.raises(KnowledgeError, match="Choose ggplot2"):
        await api.get_visualization_docs("../server", "geom_point")


async def test_visualization_docs_preserve_verified_package_version(service, monkeypatch):
    api, _, _ = service

    async def package_info(package, repository, verify_archive=True):
        return {
            "package": package,
            "package_version": "4.1.0",
            "source_url": "https://cran.example/metadata",
            "checked_at": "2026-10-22T00:00:00+00:00",
            "sources": [
                {
                    "source_url": "https://cran.example/metadata",
                    "checked_at": "2026-10-22T00:00:00+00:00",
                }
            ],
        }

    async def function_docs(package, function, repository):
        return {
            "package": package,
            "package_version": "4.1.0",
            "function": function,
            "source_url": "https://cran.example/source",
            "checked_at": "2026-10-22T00:00:01+00:00",
            "sources": [
                {
                    "source_url": "https://cran.example/source",
                    "checked_at": "2026-10-22T00:00:01+00:00",
                }
            ],
        }

    monkeypatch.setattr(api, "get_package_info", package_info)
    monkeypatch.setattr(api, "get_function_docs", function_docs)
    current = await api.get_visualization_docs("ggplot2", "geom_point", "4.1.0")
    assert current["verification_status"] == "verified"
    assert current["package_version"] == "4.1.0"
    assert current["source_url"] == "https://cran.example/source"
    historical = await api.get_visualization_docs("ggplot2", "geom_point", "3.5.0")
    assert historical["verification_status"] == "failed"
    assert historical["error"]["code"] == "requested_version_unavailable"
    assert historical["latest_package_version"] == "4.1.0"


async def test_invalid_lock_data_fails_explicitly(service):
    api, _, _ = service
    with pytest.raises(KnowledgeError, match="valid JSON"):
        await api.analyze_knitr_chunks("```{r}\n1\n```", renv_lock="not-json")


async def test_visualization_workflow_preserves_missing_source_failures(service):
    api, _, _ = service
    result = await api.get_visualization_workflow("tidy_to_plot")
    assert result["verification_status"] == "partial"
    assert len(result["steps"]) == 4
    assert all(step["verification_status"] == "failed" for step in result["steps"])
    assert result["no_code_executed"] is True
