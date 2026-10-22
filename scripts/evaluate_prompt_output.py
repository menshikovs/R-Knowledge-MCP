"""Reproduce the offline Prompt Intelligence output-size evaluation.

This benchmark uses deterministic synthetic package metadata and never accesses a
network service. Token counts are estimates (UTF-8 bytes divided by four).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cran_knowledge_mcp.prompt_intelligence import PromptIntelligence
from cran_knowledge_mcp.prompt_intelligence.templates import TEMPLATE_BY_ID

CRAN_URL = "https://cran.r-project.org/src/contrib/PACKAGES"
BIOC_URL = "https://bioconductor.org/config.yaml"
CHECKED_AT = "2026-10-22T00:00:00+00:00"
TEMPLATE_FUNCTIONS = {
    (package.casefold(), function.casefold())
    for template in TEMPLATE_BY_ID.values()
    for package, function in template.function_refs
}


class OfflineKnowledge:
    """Stable fixture for output measurement; versions are synthetic test data."""

    async def get_package_info(self, package, repository="cran", bioc_version=None):
        if package.casefold() == "unknownpkg":
            return {"results": [], "errors": [], "verification_status": "verified"}
        bioc = package.casefold() in {"deseq2", "summarizedexperiment"}
        record = {
            "package": package,
            "repository": "bioconductor" if bioc else "cran",
            "package_version": "0.0.0-fixture",
            "bioc_version": (bioc_version or "0.0") if bioc else None,
            "category": "software" if bioc else None,
            "sources": [
                {
                    "source_url": BIOC_URL if bioc else CRAN_URL,
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
            "verification_status": "verified",
            "sources": [
                {
                    "source_url": BIOC_URL if repository == "bioconductor" else CRAN_URL,
                    "checked_at": CHECKED_AT,
                }
            ],
        }

    async def get_function_docs(
        self, package, function, offset=0, repository="cran", bioc_version=None
    ):
        if (package.casefold(), function.casefold()) not in TEMPLATE_FUNCTIONS:
            return {
                "error": {"code": "docs_not_found", "source_url": CRAN_URL},
                "verification_status": "failed",
                "source_url": CRAN_URL,
                "checked_at": CHECKED_AT,
            }
        return {
            "package_version": "0.0.0-fixture",
            "verification_status": "verified",
            "source_url": BIOC_URL if package.casefold() == "deseq2" else CRAN_URL,
            "checked_at": CHECKED_AT,
            "repository": "bioconductor" if package.casefold() == "deseq2" else "cran",
            "sources": [
                {
                    "source_url": BIOC_URL if package.casefold() == "deseq2" else CRAN_URL,
                    "checked_at": CHECKED_AT,
                }
            ],
        }

    async def get_bioconductor_version(self, _r_version):
        return {
            "recommended_bioc_version": "0.0",
            "releases": [{"bioc_version": "0.0", "r_version": "0.0"}],
            "sources": [{"source_url": BIOC_URL, "checked_at": CHECKED_AT}],
        }

    async def check_package_compatibility(self, *_args, **_kwargs):
        return {
            "compatibility_status": "metadata_compatible",
            "source_url": BIOC_URL,
            "checked_at": CHECKED_AT,
            "warnings": [],
        }


SCENARIOS = [
    {"id": "simple-ggplot-scatter", "request": "Create a ggplot2 scatter plot."},
    {"id": "simple-dplyr-filter", "request": "Filter rows using dplyr."},
    {"id": "simple-readr-csv", "request": "Import a CSV file with readr."},
    {"id": "simple-group-summary", "request": "Summarize grouped data with dplyr."},
    {
        "id": "simple-sqlite-query",
        "request": "Create a simple SQLite query through DBI.",
        "structured_context": {"database_dialect": "sqlite", "read_only": True},
    },
    {"id": "medium-clean-validate-csv", "request": "Clean and validate a CSV dataset."},
    {"id": "medium-shiny-module", "request": "Create a reusable Shiny module."},
    {"id": "medium-debug-legend", "request": "Debug an incorrect ggplot2 legend."},
    {
        "id": "medium-postgres-parameters",
        "request": "Build a PostgreSQL query with parameterized inputs.",
        "structured_context": {"database_dialect": "postgresql", "read_only": True},
    },
    {"id": "medium-quarto-report", "request": "Create a Quarto report with tables and plots."},
    {
        "id": "workflow-csv-dplyr-ggplot-quarto",
        "request": (
            "Read a CSV, transform it with dplyr, plot with ggplot2, and render a Quarto report."
        ),
    },
    {
        "id": "workflow-csv-postgres-sql-r",
        "request": "Import CSV to PostgreSQL, validate SQL data, then analyze it in R.",
        "structured_context": {"database_dialect": "postgresql", "read_only": False},
    },
    {
        "id": "workflow-deseq2-visualization-quarto",
        "request": (
            "Analyze RNA-seq differential expression with DESeq2, visualize results, "
            "and create a Quarto report."
        ),
        "r_version": "4.5.1",
        "bioconductor_release": "3.22",
    },
    {
        "id": "workflow-sql-clean-shiny",
        "request": "Query PostgreSQL, clean the data, and build a Shiny dashboard.",
        "structured_context": {"database_dialect": "postgresql", "read_only": True},
    },
    {
        "id": "workflow-explicit-templates",
        "request": "Import, validate, analyze, visualize, and report the dataset.",
        "templates": ["csv-import", "csv-validation", "csv-analysis", "quarto-report"],
    },
    {
        "id": "safety-explicit-constraints",
        "request": "Create a plot from the supplied data.",
        "constraints": ["Do not install packages.", "Save the result as plot.png."],
    },
    {
        "id": "safety-missing-docs",
        "request": "Use ggplot2::unknown_plot() to transform the data.",
    },
    {
        "id": "safety-conflicting-workflow",
        "request": "Validate the CSV before loading it, but load it before validation.",
    },
    {
        "id": "safety-destructive-sql",
        "request": "Use DBI to run DROP TABLE old_data in PostgreSQL.",
        "structured_context": {"database_dialect": "postgresql", "read_only": False},
    },
    {
        "id": "safety-version-mismatch",
        "request": "Use ggplot2 version 1.0.0 to create a plot.",
        "structured_context": {"package_versions": {"ggplot2": "1.0.0"}},
    },
]


def _measure(result: dict, scenario: dict, detail_level: str) -> dict:
    prompt = result["prompt_text"]
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    duplicates = sum(count - 1 for count in Counter(lines).values() if count > 1)
    return {
        "scenario": scenario["id"],
        "detail_level": detail_level,
        "characters": len(prompt),
        "utf8_bytes": len(prompt.encode("utf-8")),
        "estimated_tokens_utf8_bytes_div_4": math.ceil(len(prompt.encode("utf-8")) / 4),
        "repeated_nonempty_lines": duplicates,
        "sections": [line[3:] for line in lines if line.startswith("## ")],
        "selected_templates": [item["id"] for item in result["selected_templates"]],
        "preserved_constraints": [
            value for value in scenario.get("constraints", []) if value in prompt
        ],
        "verified_package_references": [
            f"{item['package']}:{item.get('package_version')}:{item.get('verification_status')}"
            for item in result["packages"]
        ],
        "function_references": [
            f"{item.get('package')}::{item.get('function')}:{item.get('status')}"
            for item in result["function_documentation"]
        ],
        "assumptions": result["assumptions"],
        "warnings": result["warnings"],
    }


async def evaluate() -> dict:
    service = PromptIntelligence(OfflineKnowledge())
    records = []
    for scenario in SCENARIOS:
        for level in ("concise", "standard", "comprehensive"):
            options = {
                key: value for key, value in scenario.items() if key not in {"id", "request"}
            }
            result = await service.build_r_prompt(
                scenario["request"],
                detail_level=level,
                target="codex",
                enhancement_mode="deterministic",
                **options,
            )
            records.append(_measure(result, scenario, level))
    return {
        "methodology": {
            "network": "disabled; deterministic synthetic metadata fixture",
            "token_estimate": "ceil(UTF-8 byte count / 4), rough estimate only",
            "scenario_count": len(SCENARIOS),
            "detail_levels": ["concise", "standard", "comprehensive"],
        },
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(evaluate())
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
