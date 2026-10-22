"""Merge template requirements without silently dropping user constraints."""

import re

from ..composer import CATEGORY_REQUIREMENTS
from .models import WorkflowTask

_DIALECTS = {
    "postgresql": r"\b(postgresql|postgres)\b",
    "sqlite": r"\bsqlite\b",
    "duckdb": r"\bduckdb\b",
    "mysql": r"\bmysql\b",
    "mariadb": r"\bmariadb\b",
    "sql_server": r"\b(sql server|sqlserver|mssql)\b",
}


class ConstraintMerger:
    @staticmethod
    def dialects_in(request: str, structured_context: dict) -> list[str]:
        names = [name for name, pattern in _DIALECTS.items() if re.search(pattern, request, re.I)]
        context_dialect = structured_context.get("database_dialect")
        if context_dialect:
            canonical = "postgresql" if context_dialect == "postgres" else context_dialect
            if canonical not in names:
                names.append(canonical)
        return names

    def merge(
        self,
        request: str,
        tasks: list[WorkflowTask],
        user_constraints: list[str],
        structured_context: dict,
        workflow_context: dict,
        language: str,
    ) -> dict[str, list[str]]:
        requirements = []
        for task in tasks:
            pair = CATEGORY_REQUIREMENTS.get(task.category)
            if pair:
                requirements.append(pair[1 if language == "ru" else 0])
            requirements.extend(task.constraints)
        requirements.extend(user_constraints)
        requirements.extend(workflow_context.get("technical_constraints", []))
        requirements.extend(workflow_context.get("security_constraints", []))
        requirements.extend(workflow_context.get("reproducibility_requirements", []))
        requirements.extend(workflow_context.get("deployment_constraints", []))
        requirements.extend(workflow_context.get("performance_requirements", []))

        normalized = set()
        unique = []
        for item in requirements:
            key = " ".join(item.casefold().split()).rstrip(".!;:")
            if key and key not in normalized:
                normalized.add(key)
                unique.append(item)

        conflicts = []
        assumptions = []
        warnings = []
        matched_dialects = self.dialects_in(request, structured_context)
        if len(matched_dialects) > 1:
            only_mode = bool(
                re.search(
                    r"\b(only|without choosing|do not choose|must choose one)\b", request, re.I
                )
            )
            if only_mode:
                conflicts.append(
                    "conflicting_database_dialects: multiple engines are named but the request requires only one and does not select it"  # noqa: E501
                )
            else:
                assumptions.append(
                    "Multiple database dialects were requested; interpret this as a deliberate multi-backend requirement and test each separately."  # noqa: E501
                )
        if structured_context.get("read_only") is True and any(
            task.category in {"database_integration", "etl_pipeline"} for task in tasks
        ):
            conflicts.append(
                "read_only_database_conflicts_with_requested_load_or_write: preserve read-only and report the incompatible write goal"  # noqa: E501
            )
        if re.search(r"\boffline\b", request, re.I) and re.search(
            r"\b(fetch|download|live api|online service)\b", request, re.I
        ):
            conflicts.append(
                "offline_requirement_conflicts_with_live_network_access: keep both user requirements visible and ask for resolution"  # noqa: E501
            )
        if not structured_context.get("table_schema") and any(
            task.category in {"database_query", "database_schema_design", "database_integration"}
            for task in tasks
        ):
            assumptions.append(
                "Database schema was not supplied; inspect it using an authorized read-only path before proposing queries or migrations."  # noqa: E501
            )
        if not structured_context.get("csv_columns") and any(
            task.category in {"csv_import", "data_cleaning", "data_validation"} for task in tasks
        ):
            assumptions.append(
                "CSV column names and types are unknown; inspect a bounded, sanitized sample or metadata before selecting transformations."  # noqa: E501
            )
        if any(
            task.category == "bioconductor_analysis" for task in tasks
        ) and not structured_context.get("package_versions"):
            warnings.append(
                "Bioconductor release and package versions are source-grounded only when the caller supplies an R version or explicitly selects a release."  # noqa: E501
            )
        return {
            "requirements": unique,
            "conflicts": list(dict.fromkeys(conflicts)),
            "assumptions": list(dict.fromkeys(assumptions)),
            "warnings": list(dict.fromkeys(warnings)),
        }
