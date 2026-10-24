"""Deterministic technology-stack planning inputs and bounded validation."""

from __future__ import annotations

import re
from typing import Any

from .errors import KnowledgeError
from .input_safety import contains_credential_like_text
from .prompt_intelligence.templates import TEMPLATE_BY_ID

PROJECT_TYPES = ("analytics", "api", "dashboard", "package", "etl", "ml", "other")
DEPLOYMENT_TARGETS = ("local", "docker", "cloud", "on_premises")

# Candidate packages come from the existing versioned workflow templates. Each candidate is
# filtered against current repository metadata before it can be returned as a recommendation.
_PROJECTS: dict[str, dict[str, Any]] = {
    "analytics": {
        "templates": ("csv-analysis",),
        "pattern": "A reproducible R analysis pipeline with separate input, transformation, analysis, and output stages.",  # noqa: E501  # Intentional user-facing recommendation copy.
        "components": [
            {
                "role": "data input",
                "choice": "Keep input parsing explicit and validate the expected columns before analysis.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "analysis",
                "choice": "Separate transformation and analysis steps from reporting so each can be tested independently.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "outputs",
                "choice": "Record input, package, and output provenance for repeatable results.",
            },
        ],
        "alternatives": [
            {
                "choice": "File-based inputs and outputs",
                "tradeoff": "Simple to review and exchange; large or concurrent workloads may need a database.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "choice": "Database-backed analysis",
                "tradeoff": "Supports shared and larger datasets; adds connection, access-control, and lifecycle requirements.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "sequence": [
            "Define input schema and validation rules.",
            "Implement and test transformations.",
            "Add analysis and outputs.",
            "Record environment and source provenance.",
        ],
    },
    "api": {
        "templates": (),
        "pattern": "An R service with a narrow request boundary, validated inputs, isolated business logic, and explicit response/error handling.",  # noqa: E501  # Intentional user-facing recommendation copy.
        "components": [
            {
                "role": "request boundary",
                "choice": "Validate request shape, sizes, and allowed operations before application logic.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "service logic",
                "choice": "Keep computation independent from HTTP handling so it can be tested without a running server.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "operations",
                "choice": "Plan authentication, rate limits, health checks, and structured error responses before deployment.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "alternatives": [
            {
                "choice": "Synchronous request/response",
                "tradeoff": "Simpler operational model for bounded work; long-running requests need explicit timeout handling.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "choice": "Queued background work",
                "tradeoff": "Handles long jobs more safely; requires durable queue, worker, and result-retention decisions.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "sequence": [
            "Choose and verify an R HTTP framework.",
            "Define request/response contracts and auth requirements.",
            "Implement service logic and boundary tests.",
            "Add deployment, monitoring, and load limits.",
        ],
    },
    "dashboard": {
        "templates": ("shiny-app",),
        "pattern": "A Shiny application with a thin interface, modular reactive logic, and isolated data/service functions.",  # noqa: E501  # Intentional user-facing recommendation copy.
        "components": [
            {
                "role": "interface",
                "choice": "Keep presentation and input validation separate from data access.",
            },
            {
                "role": "reactive logic",
                "choice": "Use small modules with explicit inputs and outputs to limit reactive coupling.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "data access",
                "choice": "Keep credentials and data-source configuration outside app source and container images.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "alternatives": [
            {
                "choice": "Single Shiny application",
                "tradeoff": "Fewer components to operate; scaling and isolation are tied to the app process.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "choice": "Shiny front end with a separate service",
                "tradeoff": "Can isolate shared or expensive computation; adds API security and deployment work.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "sequence": [
            "Define user tasks, data boundaries, and access rules.",
            "Build a static interface and validate inputs.",
            "Add modular reactive behavior and test it.",
            "Review authentication, session isolation, and deployment limits.",
        ],
    },
    "package": {
        "templates": ("r-package-development",),
        "pattern": "A focused R package with a small exported API, documented behavior, and deterministic tests.",  # noqa: E501  # Intentional user-facing recommendation copy.
        "components": [
            {
                "role": "public API",
                "choice": "Keep exported functions small and document arguments, return values, and failure behavior.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "implementation",
                "choice": "Separate internal helpers from exported functions and declare dependencies explicitly.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {"role": "quality", "choice": "Use isolated tests and package checks before release."},
        ],
        "alternatives": [
            {
                "choice": "One package",
                "tradeoff": "Simple to develop and release; may become difficult to maintain if domains are unrelated.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "choice": "Several coordinated packages",
                "tradeoff": "Clearer ownership boundaries; adds versioning and release coordination.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "sequence": [
            "Define the public API and supported R range.",
            "Implement one vertical slice with tests and documentation.",
            "Declare runtime and optional dependencies separately.",
            "Run package checks and review release metadata.",
        ],
    },
    "etl": {
        "templates": ("csv-import", "csv-sql-pipeline"),
        "pattern": "A restartable ETL flow with bounded ingestion, validation, explicit transformations, and controlled writes.",  # noqa: E501  # Intentional user-facing recommendation copy.
        "components": [
            {
                "role": "ingestion",
                "choice": "Bound input size and make encoding, delimiter, and type assumptions explicit.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "validation",
                "choice": "Reject or quarantine invalid records with measurable checks and a reviewable report.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "load",
                "choice": "Use explicit transactions or atomic file replacement where supported; make retries idempotent.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "alternatives": [
            {
                "choice": "File-to-file pipeline",
                "tradeoff": "Easy to inspect and replay; coordination is needed for concurrent writers.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "choice": "Database-backed pipeline",
                "tradeoff": "Supports transactions and shared access; requires dialect, permission, and migration decisions.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "sequence": [
            "Specify input and output schemas.",
            "Implement bounded ingestion and validation.",
            "Add idempotent transformations and load behavior.",
            "Test retries, partial failure, and reconciliation.",
        ],
    },
    "ml": {
        "templates": ("statistical-modeling",),
        "pattern": "A reproducible modeling workflow that separates data preparation, training, evaluation, and artifact handling.",  # noqa: E501  # Intentional user-facing recommendation copy.
        "components": [
            {
                "role": "data preparation",
                "choice": "Define leakage-safe splits and preprocessing using the project’s stated data unit.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "training",
                "choice": "Record model inputs, parameters, random seeds, and environment for each run.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "role": "evaluation",
                "choice": "Choose metrics and decision thresholds before comparing models.",
            },
        ],
        "alternatives": [
            {
                "choice": "Batch scoring",
                "tradeoff": "Simpler to reproduce and operate; results are not immediately updated.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
            {
                "choice": "Online scoring service",
                "tradeoff": "Lower serving delay; adds availability, monitoring, and model-versioning requirements.",  # noqa: E501  # Intentional user-facing recommendation copy.
            },
        ],
        "sequence": [
            "Define target, unit of prediction, and evaluation criteria.",
            "Create leakage-safe preprocessing and splits.",
            "Train and compare baselines.",
            "Document artifact, monitoring, and retraining decisions.",
        ],
    },
    "other": {
        "templates": (),
        "pattern": "No project-specific architecture is selected because the supplied project type does not match a supported workflow profile.",  # noqa: E501  # Intentional user-facing recommendation copy.
        "components": [],
        "alternatives": [],
        "sequence": [
            "Clarify project type, users, data boundaries, and deployment constraints.",
            "Select a workflow profile before choosing packages.",
        ],
    },
}

_ROLE_FIT: dict[str, tuple[str, ...]] = {
    "readr": ("read", "import", "delimited", "rectangular text", "data"),
    "dplyr": ("data manipulation", "transform", "manipulation"),
    "ggplot2": ("visual", "graphics", "plot"),
    "shiny": ("web application", "web framework", "interactive application"),
    "bslib": ("bootstrap", "theme", "shiny"),
    "testthat": ("test", "testing"),
    "roxygen2": ("documentation", "document"),
    "data.table": ("data manipulation", "fast aggregation", "file reading", "fread"),
    "vroom": ("read", "write", "rectangular text", "delimited"),
    "DBI": ("database interface", "database"),
    "duckdb": ("database", "analytical", "sql"),
}
_ROLE_FIT_BY_ROLE = {
    "API framework": ("api", "http", "web application", "web framework"),
    "modeling framework": ("machine learning", "predictive model", "modeling", "modelling"),
}

_PACKAGE_ROLES = {
    "readr": (
        "data ingestion",
        "Delimited-file handling is a direct part of the selected analysis/ETL workflow.",
    ),
    "dplyr": (
        "data transformation",
        "The selected workflow includes explicit data transformation before analysis.",
    ),
    "ggplot2": ("visualization", "The selected analysis workflow includes data visualization."),
    "shiny": (
        "interactive application",
        "The dashboard profile uses the existing Shiny workflow template.",
    ),
    "bslib": (
        "interface styling",
        "The dashboard profile includes the existing Shiny UI styling candidate.",
    ),
    "testthat": (
        "package testing",
        "The package workflow template identifies package-level tests as a core role.",
    ),
    "roxygen2": (
        "API documentation",
        "The package workflow template includes generated API documentation.",
    ),
    "data.table": (
        "data ingestion",
        "The ETL workflow template includes this as an alternative delimited-data tool.",
    ),
    "vroom": (
        "data ingestion",
        "The ETL workflow template includes this as an alternative delimited-data tool.",
    ),
    "DBI": ("database interface", "The selected ETL workflow includes a database loading path."),
    "duckdb": (
        "embedded database option",
        "The selected ETL workflow includes an embedded database option.",
    ),
}

_TYPE_HINTS = {
    "analytics": ("analysis", "analytics", "analytical", "statistic", "report"),
    "api": ("api", "http service", "web service", "endpoint"),
    "dashboard": ("dashboard", "shiny", "interactive web app"),
    "package": ("r package", "package development", "cran package"),
    "etl": ("etl", "data pipeline", "data integration", "import and load"),
    "ml": ("machine learning", "model training", "predictive model", "prediction"),
}


def _validate_text(value: Any, label: str, *, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > 4000:
        raise KnowledgeError(
            "invalid_input", f"{label} must be non-empty text up to 4000 characters"
        )
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise KnowledgeError("invalid_input", f"{label} contains unsupported control characters")
    if contains_credential_like_text(value):
        raise KnowledgeError(
            "sensitive_input",
            f"Remove credential-like text from {label} before requesting recommendations",
        )
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise KnowledgeError("invalid_input", f"{label} must contain valid Unicode") from exc
    return value


def validate_recommendation_inputs(
    objective: Any,
    project_type: Any,
    requirements: Any,
    existing_stack: Any,
    deployment_target: Any,
    preferences: Any,
) -> dict[str, Any]:
    objective = _validate_text(objective, "objective", required=True)
    if project_type is not None and project_type not in PROJECT_TYPES:
        raise KnowledgeError(
            "invalid_input", f"project_type must be one of: {', '.join(PROJECT_TYPES)}"
        )
    if deployment_target is not None and deployment_target not in DEPLOYMENT_TARGETS:
        raise KnowledgeError(
            "invalid_input", f"deployment_target must be one of: {', '.join(DEPLOYMENT_TARGETS)}"
        )
    normalized_lists: dict[str, list[str]] = {}
    for label, values, max_items in (
        ("requirements", requirements, 20),
        ("existing_stack", existing_stack, 30),
    ):
        values = [] if values is None else values
        if not isinstance(values, list) or len(values) > max_items:
            raise KnowledgeError(
                "invalid_input", f"{label} must be a list with at most {max_items} items"
            )
        normalized_lists[label] = [_validate_text(item, f"{label} item") for item in values]
    preferences = {} if preferences is None else preferences
    if not isinstance(preferences, dict) or set(preferences) - {"prefer", "exclude"}:
        raise KnowledgeError(
            "invalid_input", "preferences may contain only prefer and exclude lists"
        )
    normalized_preferences = {}
    for key in ("prefer", "exclude"):
        values = preferences.get(key, [])
        if not isinstance(values, list) or len(values) > 20:
            raise KnowledgeError(
                "invalid_input", f"preferences.{key} must be a list with at most 20 items"
            )
        normalized_preferences[key] = [
            _validate_text(item, f"preferences.{key} item") for item in values
        ]
    all_text = [
        objective,
        *normalized_lists["requirements"],
        *normalized_lists["existing_stack"],
        *normalized_preferences["prefer"],
        *normalized_preferences["exclude"],
    ]
    if sum(len(item.encode("utf-8")) for item in all_text) > 64 * 1024:
        raise KnowledgeError("input_too_large", "Combined recommendation text exceeds 64 KiB")
    return {
        "objective": objective,
        "project_type": project_type,
        **normalized_lists,
        "deployment_target": deployment_target,
        "preferences": normalized_preferences,
    }


def resolve_project_type(
    project_type: str | None, objective: str, requirements: list[str]
) -> tuple[str, str]:
    if project_type is not None:
        return project_type, "caller_supplied"
    text = " ".join((objective, *requirements)).casefold()
    scores = {
        kind: sum(1 for hint in hints if re.search(rf"\b{re.escape(hint)}\b", text))
        for kind, hints in _TYPE_HINTS.items()
    }
    best = max(scores.values(), default=0)
    winners = [kind for kind, score in scores.items() if score == best and score > 0]
    if len(winners) == 1:
        return winners[0], "objective_keyword_heuristic"
    return "other", "unresolved"


def package_candidates(project_type: str) -> list[dict[str, str]]:
    plan = _PROJECTS[project_type]
    candidates: list[dict[str, str]] = []
    for template_id in plan["templates"]:
        template = TEMPLATE_BY_ID[template_id]
        for package in template.packages:
            role, rationale = _PACKAGE_ROLES.get(
                package,
                (template.task_category.replace("_", " "), template.description),
            )
            candidates.append(
                {
                    "package": package,
                    "role": role,
                    "rationale": rationale,
                    "template_id": template_id,
                }
            )
    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate["package"].casefold(), candidate)
    return list(unique.values())


def metadata_supports_role(
    package: str, title: Any, description: Any, role: str | None = None
) -> bool:
    signals = _ROLE_FIT_BY_ROLE.get(role or "", _ROLE_FIT.get(package, ()))
    if not signals:
        return False
    text = " ".join(value for value in (title, description) if isinstance(value, str)).casefold()
    tokens = _role_tokens(text)
    return any(_contains_role_phrase(tokens, _role_tokens(signal)) for signal in signals)


def _role_tokens(value: str) -> list[str]:
    return [_singular_role_token(token) for token in re.findall(r"[a-z0-9]+", value.casefold())]


def _singular_role_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ches", "shes", "xes", "zes", "sses")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _contains_role_phrase(tokens: list[str], phrase: list[str]) -> bool:
    if not phrase or len(phrase) > len(tokens):
        return False
    width = len(phrase)
    return any(
        tokens[offset : offset + width] == phrase for offset in range(len(tokens) - width + 1)
    )


def project_plan(project_type: str) -> dict[str, Any]:
    return _PROJECTS[project_type]
