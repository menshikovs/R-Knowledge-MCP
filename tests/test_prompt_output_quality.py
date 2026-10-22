"""Public-service regression coverage for concise and grounded prompts."""

from cran_knowledge_mcp.prompt_intelligence import PromptIntelligence

CHECKED_AT = "2026-10-22T00:00:00+00:00"
CRAN_URL = "https://cran.r-project.org/src/contrib/PACKAGES"
BIOC_URL = "https://bioconductor.org/config.yaml"


class OfflineKnowledge:
    async def get_package_info(self, package, repository="cran", bioc_version=None):
        is_bioc = package.casefold() == "deseq2"
        record = {
            "package": package,
            "repository": "bioconductor" if is_bioc else "cran",
            "package_version": "2.4.1-fixture",
            "bioc_version": (bioc_version or "3.22") if is_bioc else None,
            "category": "software" if is_bioc else None,
            "sources": [
                {
                    "source_url": BIOC_URL if is_bioc else CRAN_URL,
                    "checked_at": CHECKED_AT,
                }
            ],
            "verification_status": "verified",
        }
        if repository == "all":
            return {"results": [record], "errors": [], "verification_status": "verified"}
        return record

    async def get_dependencies(
        self, package, repository="cran", bioc_version=None, resolve_repositories=False
    ):
        return {
            "dependencies": {"Imports": "stats"},
            "resolved_dependencies": [],
            "sources": [
                {
                    "source_url": BIOC_URL if repository == "bioconductor" else CRAN_URL,
                    "checked_at": CHECKED_AT,
                }
            ],
            "verification_status": "verified",
        }

    async def get_function_docs(
        self, package, function, offset=0, repository="cran", bioc_version=None
    ):
        if function in {"ggplot", "filter", "read_csv", "dbGetQuery", "DESeq"}:
            is_bioc = repository == "bioconductor"
            return {
                "package_version": "2.4.1-fixture",
                "format": "raw Rd fixture",
                "sources": [
                    {
                        "source_url": BIOC_URL if is_bioc else CRAN_URL,
                        "checked_at": CHECKED_AT,
                    }
                ],
                "source_url": BIOC_URL if is_bioc else CRAN_URL,
                "checked_at": CHECKED_AT,
                "verification_status": "verified",
            }
        return {
            "error": {"code": "docs_not_found", "source_url": CRAN_URL},
            "verification_status": "failed",
            "source_url": CRAN_URL,
            "checked_at": CHECKED_AT,
        }

    async def get_bioconductor_version(self, r_version):
        return {
            "recommended_bioc_version": "3.22",
            "releases": [{"bioc_version": "3.22", "r_version": "4.5"}],
            "sources": [{"source_url": BIOC_URL, "checked_at": CHECKED_AT}],
        }

    async def check_package_compatibility(self, package, r_version, bioc_version=None):
        return {
            "compatibility_status": "metadata_compatible",
            "source_url": BIOC_URL,
            "checked_at": CHECKED_AT,
            "warnings": [],
        }


def service():
    return PromptIntelligence(OfflineKnowledge())


async def test_simple_concise_is_materially_shorter_and_keeps_task_and_package_fact():
    prompt_service = service()
    request = "Create a ggplot2 scatter plot with x = age and y = score."
    concise = await prompt_service.build_r_prompt(request, detail_level="concise")
    standard = await prompt_service.build_r_prompt(request, detail_level="standard")
    comprehensive = await prompt_service.build_r_prompt(request, detail_level="comprehensive")

    assert concise["prompt_text"].startswith("#")
    assert request in concise["prompt_text"]
    assert "ggplot2" in concise["prompt_text"]
    assert concise["packages"][0]["package_version"] == "2.4.1-fixture"
    assert concise["prompt_text"].count("Specify data mappings") == 1
    assert standard["prompt_text"].count("Specify data mappings") == 1
    assert len(concise["prompt_text"]) < len(standard["prompt_text"]) * 0.65
    assert (
        len(concise["prompt_text"])
        < len(standard["prompt_text"])
        < len(comprehensive["prompt_text"])
    )


async def test_concise_retains_explicit_constraints_and_structured_fields():
    request = "Create a ggplot2 scatter plot."
    constraint = "Do not install packages."
    result = await service().build_r_prompt(
        request,
        detail_level="concise",
        constraints=[constraint],
        structured_context={
            "output_path": "plots/figure.svg",
            "csv_columns": ["x", "y"],
            "sample_records": [{"x": 1, "y": 2}],
        },
    )

    assert constraint in result["prompt_text"]
    assert '"output_path":"plots/figure.svg"' in result["prompt_text"]
    assert '"csv_columns":["x","y"]' in result["prompt_text"]
    assert '"sample_records":[{"x":1,"y":2}]' in result["prompt_text"]
    assert "potentially sensitive" in result["prompt_text"]


async def test_concise_composed_workflow_preserves_dependencies_and_stage_order():
    request = (
        "Import a CSV, validate it, write the valid rows to PostgreSQL, "
        "then analyze with dplyr and create a Quarto report."
    )
    result = await service().build_r_prompt(
        request,
        detail_level="concise",
        structured_context={"database_dialect": "postgresql", "read_only": False},
    )
    prompt = result["prompt_text"]
    assert result["composition_mode"] == "composed"
    assert result["dependencies"]
    stages = result["workflow_stages"]
    stage_positions = {stage["task_id"]: index for index, stage in enumerate(stages)}
    for dependency in result["dependencies"]:
        assert dependency["before"] in prompt
        assert dependency["after"] in prompt
        assert stage_positions[dependency["before"]] < stage_positions[dependency["after"]]
    assert "Parameterize SQL values" in prompt
    assert "authorization" in prompt
    assert result["validation_summary"]["composition"]["dimensions"]["security"]["passed"]
    assert result["validation_summary"]["composition"]["dimensions"]["testability"]["passed"]


async def test_composed_detail_levels_render_distinct_amounts_of_guidance():
    request = (
        "Import a CSV, validate it, load it into PostgreSQL, analyze it with dplyr, "
        "and produce a Quarto report."
    )
    results = {
        level: await service().build_r_prompt(request, detail_level=level)
        for level in ("concise", "standard", "comprehensive")
    }

    assert (
        len(results["concise"]["prompt_text"])
        < len(results["standard"]["prompt_text"])
        < len(results["comprehensive"]["prompt_text"])
    )
    assert "Extended verification" in results["comprehensive"]["prompt_text"]


async def test_concise_keeps_explicit_stage_order_and_unresolved_conflicts():
    request = "Import a CSV, validate rows, then write valid rows to PostgreSQL."
    first = await service().build_r_prompt(request, detail_level="concise")
    order = [stage["task_id"] for stage in first["workflow_stages"]]
    ordered = await service().build_r_prompt(
        request,
        detail_level="concise",
        workflow_context={"stage_order": order},
    )
    conflict = await service().build_r_prompt(
        "Use PostgreSQL and SQLite as the only database, without choosing between them.",
        detail_level="concise",
    )

    assert [stage["task_id"] for stage in ordered["workflow_stages"]] == order
    assert not ordered["conflicts"]
    assert any("conflicting_database_dialects" in item for item in conflict["conflicts"])
    assert "conflicting_database_dialects" in conflict["prompt_text"]


async def test_concise_sql_keeps_destructive_action_approval_safeguards():
    result = await service().build_r_prompt(
        "Use DBI to run DROP TABLE old_data in PostgreSQL.",
        detail_level="concise",
        structured_context={"database_dialect": "postgresql", "read_only": False},
    )

    assert "DROP TABLE" in result["prompt_text"]
    assert "explicit authorization" in result["prompt_text"]
    assert "backup" in result["prompt_text"]
    assert "rollback" in result["prompt_text"]


async def test_explicit_multi_template_prompt_deduplicates_requirements_and_keeps_ids():
    result = await service().build_r_prompt(
        "Import, validate, analyze, and report this CSV dataset.",
        detail_level="concise",
        templates=["csv-import", "csv-validation", "csv-analysis", "quarto-report"],
    )

    selected = [item["id"] for item in result["selected_templates"]]
    assert set(selected) == {"csv-import", "csv-validation", "csv-analysis", "quarto-report"}
    assert result["validation_summary"]["composition"]["duplicate_requirement_count"] == 0


async def test_concise_preserves_verified_and_unverified_function_doc_status():
    verified = await service().build_r_prompt(
        "Create a ggplot2 chart with ggplot2::ggplot().", detail_level="concise"
    )
    missing = await service().build_r_prompt(
        "Use ggplot2::unknown_plot() to draw the chart.", detail_level="concise"
    )

    assert "ggplot2::ggplot(): verified" in verified["prompt_text"]
    assert "ggplot2::unknown_plot(): docs_not_found" in missing["prompt_text"]
    assert CRAN_URL in verified["packages"][0]["sources"][0]["source_url"]


async def test_concise_bioconductor_fact_keeps_release_version_and_compatibility():
    result = await service().build_r_prompt(
        "Analyze differential expression with DESeq2::DESeq().",
        detail_level="concise",
        r_version="4.5.1",
        bioconductor_release="3.22",
    )

    assert "DESeq2" in result["prompt_text"]
    assert "Bioconductor 3.22" in result["prompt_text"]
    assert "R compatibility metadata_compatible" in result["prompt_text"]
    assert BIOC_URL in result["prompt_text"]


async def test_russian_concise_prompt_is_deterministic_and_preserves_request():
    request = "Создай точечный график ggplot2, сохрани оси x и y без изменений."
    constraint = "Не устанавливай пакеты."
    first = await service().build_r_prompt(
        request, detail_level="concise", constraints=[constraint]
    )
    second = await service().build_r_prompt(
        request, detail_level="concise", constraints=[constraint]
    )
    assert request in first["prompt_text"]
    assert constraint in first["prompt_text"]
    assert first["prompt_text"] == second["prompt_text"]
    assert first["detail_level"] == "concise"
