import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.technology_recommendation import (
    metadata_supports_role,
    package_candidates,
)


def _sources(package):
    return [
        {
            "source_url": f"https://example.invalid/packages/{package}",
            "checked_at": "2026-10-24T00:00:00+00:00",
        }
    ]


def _dashboard_info(package):
    records = {
        "shiny": {
            "title": "Web Application Framework for R",
            "description": "A framework for building interactive web applications.",
        },
        "bslib": {
            "title": "Custom Bootstrap Themes for Shiny",
            "description": "Theme support for Shiny applications.",
        },
    }
    return {
        "package": package,
        "package_version": "1.2.3",
        "repository": "cran",
        "metadata_verification_level": "description_version_matched",
        "verification_status": "verified",
        "sources": _sources(package),
        **records[package],
    }


async def _install_dashboard_metadata(monkeypatch, api, *, title_override=None):
    calls = []

    async def get_info(package, repository="cran", bioc_version=None, verify_archive=True):
        calls.append(("info", package, verify_archive))
        info = _dashboard_info(package)
        if package == "shiny" and title_override is not None:
            info["title"] = title_override
            info["description"] = "An unrelated package description."
        return info

    async def get_dependencies(package, repository="cran", bioc_version=None):
        calls.append(("dependencies", package, None))
        return {
            "package": package,
            "repository": "cran",
            "package_version": "1.2.3",
            "dependencies": {
                "Depends": "R (>= 4.0)",
                "Imports": "methods",
                "LinkingTo": "",
                "Suggests": "testthat",
                "Enhances": "SyntheticEnhancer",
            },
            "sources": _sources(package),
        }

    monkeypatch.setattr(api, "get_package_info", get_info)
    monkeypatch.setattr(api, "get_dependencies", get_dependencies)
    return calls


async def test_dashboard_recommendations_are_role_and_metadata_grounded(service, monkeypatch):
    api, _, _ = service
    calls = await _install_dashboard_metadata(monkeypatch, api)

    result = await api.recommend_technology_stack(
        "Build a small public dashboard",
        "dashboard",
        ["Требование оставить исходные русские формулировки."],
        ["shiny"],
        "docker",
        {"prefer": ["bslib"], "exclude": []},
    )

    assert result["recommendation_status"] == "provisional"
    assert result["project_type"] == {"value": "dashboard", "basis": "caller_supplied"}
    roles = {entry["role"]: entry["packages"] for entry in result["stack"]["r_packages_by_role"]}
    assert roles["interactive application"][0]["package"] == "shiny"
    assert (
        roles["interactive application"][0]["recommendation_status"] == "already_selected_by_user"
    )
    assert roles["interface styling"][0]["package"] == "bslib"
    assert roles["interface styling"][0]["preference_match"] == "user_preferred"
    assert result["dependencies"]["by_package"][0]["required"] == {
        "Depends": "R (>= 4.0)",
        "Imports": "methods",
        "LinkingTo": "",
    }
    dependency = result["dependencies"]["by_package"][0]
    assert dependency["runtime_required"] == {
        "Depends": "R (>= 4.0)",
        "Imports": "methods",
    }
    assert dependency["build_time"] == {"LinkingTo": ""}
    assert dependency["optional"] == {
        "Suggests": "testthat",
        "Enhances": "SyntheticEnhancer",
    }
    assert dependency["dependency_field_scope"]["build_time_fields"] == ["LinkingTo"]
    assert result["dependencies"]["runtime_required_fields"] == ["Depends", "Imports"]
    assert result["dependencies"]["optional_fields"] == ["Suggests", "Enhances"]
    assert result["user_inputs_preserved"]["requirements"] == [
        "Требование оставить исходные русские формулировки."
    ]
    assert result["security_maintenance_deployment"]["deployment_considerations"]
    assert result["not_executed"] is True
    assert len(result["sources"]) == 2
    assert calls == [
        ("info", "shiny", False),
        ("dependencies", "shiny", None),
        ("info", "bslib", False),
        ("dependencies", "bslib", None),
    ]


async def test_excluded_package_is_not_looked_up_or_recommended(service, monkeypatch):
    api, _, _ = service
    calls = await _install_dashboard_metadata(monkeypatch, api)
    result = await api.recommend_technology_stack(
        "Build a dashboard",
        project_type="dashboard",
        preferences={"prefer": [], "exclude": ["shiny"]},
    )

    assert calls[0] == ("info", "bslib", False)
    assert all(call[1] != "shiny" for call in calls)
    assert result["package_checks"][0] == {
        "package": "shiny",
        "role": "interactive application",
        "status": "excluded_by_user_preference",
    }
    assert all(
        item["package"] != "shiny"
        for group in result["stack"]["r_packages_by_role"]
        for item in group["packages"]
    )


async def test_package_is_not_recommended_when_repository_metadata_does_not_support_role(
    service, monkeypatch
):
    api, _, _ = service
    await _install_dashboard_metadata(monkeypatch, api, title_override="Unrelated metadata")
    result = await api.recommend_technology_stack("Build a dashboard", project_type="dashboard")

    shiny = next(
        item
        for group in result["stack"]["r_packages_by_role"]
        for item in group["packages"]
        if item["package"] == "shiny"
    )
    assert shiny["recommendation_status"] == "requires_user_review"
    assert shiny["metadata_fit_status"] == "metadata_does_not_confirm_role_fit"


async def test_etl_recommends_at_most_one_package_per_role_and_honors_preference(
    service, monkeypatch
):
    api, _, _ = service
    titles = {
        "readr": "Read Rectangular Text Data",
        "data.table": "Fast File Reading and Data Manipulation",
        "vroom": "Read and Write Rectangular Text Data Quickly",
        "DBI": "R Database Interface",
        "duckdb": "Database Interface for DuckDB",
    }

    async def get_info(package, repository="cran", bioc_version=None, verify_archive=True):
        return {
            "package": package,
            "package_version": "1.0.0",
            "repository": "cran",
            "title": titles[package],
            "description": titles[package],
            "metadata_verification_level": "description_version_matched",
            "verification_status": "verified",
            "sources": _sources(package),
        }

    async def get_dependencies(package, repository="cran", bioc_version=None):
        return {
            "package": package,
            "repository": "cran",
            "package_version": "1.0.0",
            "dependencies": {"Depends": "", "Imports": "", "LinkingTo": "", "Suggests": ""},
            "sources": _sources(package),
        }

    monkeypatch.setattr(api, "get_package_info", get_info)
    monkeypatch.setattr(api, "get_dependencies", get_dependencies)
    result = await api.recommend_technology_stack(
        "Load, validate, and store tabular data",
        project_type="etl",
        preferences={"prefer": ["vroom"], "exclude": []},
    )

    roles = {entry["role"]: entry["packages"] for entry in result["stack"]["r_packages_by_role"]}
    ingestion = roles["data ingestion"]
    assert sum(item["recommendation_status"] == "recommended" for item in ingestion) == 1
    assert (
        next(item for item in ingestion if item["package"] == "vroom")["recommendation_status"]
        == "recommended"
    )
    assert {item["recommendation_status"] for item in ingestion if item["package"] != "vroom"} == {
        "alternative"
    }


async def test_api_profile_does_not_invent_package_or_framework_recommendations(
    service, monkeypatch
):
    api, _, calls = service

    async def search_packages(query, limit=10, offset=0, repository="cran", bioc_version=None):
        calls.append(("search", query))
        return {"query": query, "results": [], "sources": _sources("catalog")}

    monkeypatch.setattr(api, "search_packages", search_packages)
    result = await api.recommend_technology_stack(
        "Build an API", "api", ["Не переводить это требование."], deployment_target="local"
    )

    assert result["stack"]["r_packages_by_role"] == []
    assert (
        result["stack"]["complementary_technologies"]["additional_named_technology_recommendations"]
        == []
    )
    assert result["user_inputs_preserved"]["requirements"] == ["Не переводить это требование."]
    assert "API framework" in result["unknowns_requiring_user_decisions"][0]
    assert calls == [("search", "api")]


@pytest.mark.parametrize(
    ("project_type", "query", "role", "title"),
    [
        ("api", "api", "API framework", "Lightweight HTTP API Framework"),
        ("ml", "machine learning", "modeling framework", "Machine Learning Framework for R"),
    ],
)
async def test_api_and_ml_candidates_come_from_provider_search_and_metadata(
    service, monkeypatch, project_type, query, role, title
):
    api, _, _ = service
    search_calls = []
    package = "SyntheticFramework"

    async def search_packages(
        search_query, limit=10, offset=0, repository="cran", bioc_version=None
    ):
        search_calls.append(search_query)
        return {
            "query": search_query,
            "results": [{"package": package, "title": title}],
            "sources": _sources("catalog"),
        }

    async def get_info(package_name, repository="cran", bioc_version=None, verify_archive=True):
        return {
            "package": package_name,
            "repository": "cran",
            "package_version": "1.4.0",
            "title": title,
            "description": title,
            "metadata_verification_level": "description_version_matched",
            "verification_status": "verified",
            "sources": _sources(package_name),
        }

    async def get_dependencies(package_name, repository="cran", bioc_version=None):
        return {
            "package": package_name,
            "repository": "cran",
            "package_version": "1.4.0",
            "dependencies": {"Depends": "R", "Imports": "", "LinkingTo": "", "Suggests": ""},
            "sources": _sources(package_name),
        }

    monkeypatch.setattr(api, "search_packages", search_packages)
    monkeypatch.setattr(api, "get_package_info", get_info)
    monkeypatch.setattr(api, "get_dependencies", get_dependencies)
    result = await api.recommend_technology_stack(
        f"Plan a {project_type} project", project_type=project_type
    )

    assert search_calls == [query]
    assert result["package_discovery"]["status"] == "repository_search_completed"
    candidate = result["stack"]["r_packages_by_role"][0]["packages"][0]
    assert candidate["role"] == role
    assert candidate["package"] == package
    assert candidate["recommendation_status"] == "recommended"


async def test_objective_type_heuristic_and_unknown_case(service, monkeypatch):
    api, _, _ = service
    await _install_dashboard_metadata(monkeypatch, api)
    inferred = await api.recommend_technology_stack("Create an interactive web dashboard")
    unknown = await api.recommend_technology_stack("Create a tool")

    assert inferred["project_type"] == {
        "value": "dashboard",
        "basis": "objective_keyword_heuristic",
    }
    assert unknown["project_type"] == {"value": "other", "basis": "unresolved"}
    assert unknown["stack"]["r_packages_by_role"] == []
    assert "Project type is unresolved" in unknown["unknowns_requiring_user_decisions"][0]


async def test_invalid_inputs_fail_before_package_metadata_access(service, monkeypatch):
    api, _, calls = service
    await _install_dashboard_metadata(monkeypatch, api)

    with pytest.raises(KnowledgeError, match="preferences"):
        await api.recommend_technology_stack(
            "Build a dashboard", "dashboard", preferences={"blocked": ["shiny"]}
        )
    with pytest.raises(KnowledgeError, match="objective"):
        await api.recommend_technology_stack("   ", "dashboard")
    with pytest.raises(KnowledgeError, match="deployment_target"):
        await api.recommend_technology_stack("Build a dashboard", deployment_target="unknown")
    with pytest.raises(KnowledgeError, match="credential-like"):
        await api.recommend_technology_stack(
            "Build a dashboard", "dashboard", ["api_key=synthetic-secret-value"]
        )
    assert calls == []


def test_candidates_reuse_existing_versioned_workflow_templates():
    candidates = package_candidates("etl")
    assert {candidate["package"] for candidate in candidates} == {
        "readr",
        "data.table",
        "vroom",
        "DBI",
        "duckdb",
    }
    assert {candidate["template_id"] for candidate in candidates} == {
        "csv-import",
        "csv-sql-pipeline",
    }


@pytest.mark.parametrize(
    ("package", "role", "title", "description", "expected"),
    [
        ("readr", None, "Database tools", "Database connections", False),
        ("readr", None, "Data-import tools", None, True),
        ("DBI", None, "DATABASE interface", "Connect to relational stores.", True),
        ("shiny", None, "Interactive web applications", "Server framework", True),
        ("ggplot2", None, "Statistical plots", "Visual summaries", True),
        ("readr", None, None, None, False),
        ("readr", None, "Database and data files", None, True),
        ("Synthetic", "API framework", "HTTP Web Frameworks", None, True),
        ("Synthetic", "API framework", "Database framework", None, False),
    ],
)
def test_metadata_role_matching_uses_tokens_phrases_and_safe_plurals(
    package, role, title, description, expected
):
    assert metadata_supports_role(package, title, description, role) is expected


async def test_stack_recommendation_reuses_local_official_r_documentation(service, monkeypatch):
    api, _, _ = service
    calls = []

    async def search_r_documentation(query, manuals=None, limit=5, r_version=None):
        calls.append((query, manuals, limit, r_version))
        return {
            "status": "ok",
            "results": [
                {
                    "document_id": "introduction-to-r",
                    "document_title": "An Introduction to R",
                    "heading": "Vectors",
                    "excerpt": "R provides vector and list data structures.",
                    "source_url": "https://cran.r-project.org/doc/manuals/r-release/R-intro.html",
                    "anchor_url": None,
                    "r_version": "4.5.1",
                    "checked_at": "2026-10-24T00:00:00Z",
                    "content_hash": "b" * 64,
                    "verification_status": "indexed_official_documentation",
                }
            ],
        }

    monkeypatch.setattr(api, "search_r_documentation", search_r_documentation)
    result = await api.recommend_technology_stack(
        "Recommend an R project stack", project_type="other"
    )

    assert calls == [
        (
            "R objects functions data structures programming",
            ["introduction-to-r"],
            2,
            None,
        )
    ]
    assert result["official_r_documentation"]["status"] == "ok"
    assert result["official_r_documentation"]["references"][0]["heading"] == "Vectors"
    assert "unrelated third-party products" in " ".join(
        result["official_r_documentation"]["limitations"]
    )
