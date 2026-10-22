"""Bounded heuristic task classification and conservative package detection."""

import re

from ..errors import KnowledgeError

MAX_REQUEST_CHARS = 8000
MAX_PACKAGES = 8

CATEGORIES = {
    "package_development",
    "data_analysis",
    "data_transformation",
    "statistical_modeling",
    "data_visualization",
    "shiny_development",
    "quarto_reporting",
    "bioconductor_analysis",
    "debugging",
    "refactoring",
    "architecture_review",
    "testing",
    "reproducibility",
    "performance_optimization",
}

CATEGORY_PATTERNS = [
    (
        "architecture_review",
        r"\b(architecture|architect|system design|review.*project)\b|архитектур|обзор проект",
    ),
    ("testing", r"\b(test|tests|testing|testthat|unit test)\b|тест(ы|ирование|ов)?"),
    (
        "package_development",
        r"\b(r package|package development|r package|roxygen2|rcpp)\b|пакет r|разработ.*пакет",
    ),
    ("shiny_development", r"\b(shiny|dashboard|reactive|bslib)\b|дашборд|приложени.*shiny"),
    (
        "bioconductor_analysis",
        r"\b(bioconductor|deseq2|rna[- ]?seq|differential expression|summarizedexperiment)\b|биокондуктор|дифференциальн.*экспресс",  # noqa: E501  # Long user-facing copy or regex.
    ),
    ("quarto_reporting", r"\b(quarto|\.qmd|quarto report)\b|отч[её]т.*quarto"),
    (
        "data_visualization",
        r"\b(ggplot2|ggraph|plotly|visuali[sz]|plot|chart|graph visualization)\b|визуализац|график",
    ),
    (
        "data_transformation",
        r"\b(tidyr|dplyr|pivot_longer|pivot_wider|data transform|pipeline)\b|преобразован.*данн|tidyverse конвейер",  # noqa: E501  # Long user-facing copy or regex.
    ),
    (
        "statistical_modeling",
        r"\b(model|modeling|regression|inference|hypothesis test|survival analysis)\b|моделирован|регресси|статистическ.*анализ",  # noqa: E501  # Long user-facing copy or regex.
    ),
    (
        "performance_optimization",
        r"\b(performance|profil(e|ing)|optimi[sz]e|benchmark|memory usage)\b|производительност|оптимизир",  # noqa: E501  # Long user-facing copy or regex.
    ),
    ("reproducibility", r"\b(reproducib|renv|lockfile|reproducible report)\b|воспроизводим|renv"),
    ("debugging", r"\b(debug|debugging|bug|error|failure|fix)\b|отлад|ошибк|исправ"),
    ("refactoring", r"\b(refactor|refactoring|restructure)\b|рефактор|перестроить код"),
    (
        "data_analysis",
        r"\b(data analysis|analy[sz]e data|exploratory)\b|анализ данн|исследовательск.*анализ",
    ),
]

PACKAGE_ALIASES = {
    name.casefold(): name
    for name in (
        "DESeq2",
        "SummarizedExperiment",
        "GenomicRanges",
        "BiocManager",
        "shiny",
        "bslib",
        "ggplot2",
        "ggraph",
        "tidyr",
        "dplyr",
        "plotly",
        "knitr",
        "rmarkdown",
        "Rcpp",
        "testthat",
        "roxygen2",
        "usethis",
        "devtools",
        "renv",
        "bench",
        "profvis",
        "data.table",
        "readr",
        "purrr",
        "targets",
        "BiocParallel",
        "edgeR",
    )
}

PACKAGE_SUGGESTIONS = {
    "package_development": ["testthat", "roxygen2"],
    "testing": ["testthat"],
    "shiny_development": ["shiny", "bslib"],
    "bioconductor_analysis": ["DESeq2", "SummarizedExperiment"],
    "quarto_reporting": ["knitr"],
    "data_visualization": ["ggplot2"],
    "data_transformation": ["dplyr", "tidyr"],
    "performance_optimization": ["bench", "profvis"],
    "reproducibility": ["renv"],
}

NAMESPACE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._])([A-Za-z][A-Za-z0-9.]*)\s*::\s*([A-Za-z.][A-Za-z0-9._]*)"
)


def validate_text(value: str, label: str, maximum: int = MAX_REQUEST_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeError("invalid_input", f"{label} must be non-empty text")
    if len(value) > maximum:
        raise KnowledgeError("input_too_large", f"{label} exceeds {maximum} characters")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise KnowledgeError("invalid_input", f"{label} must be valid Unicode") from exc
    return value.strip()


def classify_request(request: str, explicit_category: str | None = None) -> str:
    if explicit_category is not None:
        normalized = explicit_category.strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized not in CATEGORIES:
            raise KnowledgeError(
                "invalid_input", f"task_category must be one of: {', '.join(sorted(CATEGORIES))}"
            )
        return normalized
    folded = request.casefold()
    for category, pattern in CATEGORY_PATTERNS:
        if re.search(pattern, folded, re.IGNORECASE):
            return category
    return "data_analysis"


def detect_packages(
    request: str, explicit: list[str] | None, category: str
) -> tuple[list[str], list[str]]:
    if explicit is not None and (not isinstance(explicit, list) or len(explicit) > MAX_PACKAGES):
        raise KnowledgeError("invalid_input", f"packages must contain at most {MAX_PACKAGES} names")
    supplied: list[str] = []
    for package in explicit or []:
        if not isinstance(package, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9.]{0,99}", package):
            raise KnowledgeError("invalid_input", "Each package must be a valid R package name")
        supplied.append(PACKAGE_ALIASES.get(package.casefold(), package))

    namespace_packages = [
        PACKAGE_ALIASES.get(pkg.casefold(), pkg) for pkg, _ in NAMESPACE_PATTERN.findall(request)
    ]
    plain_mentions = [
        canonical
        for key, canonical in PACKAGE_ALIASES.items()
        if re.search(rf"(?<![A-Za-z0-9.]){re.escape(key)}(?![A-Za-z0-9.])", request, re.IGNORECASE)
    ]
    detected = list(dict.fromkeys([*supplied, *namespace_packages, *plain_mentions]))
    suggestions = [name for name in PACKAGE_SUGGESTIONS.get(category, []) if name not in detected]
    return detected[:MAX_PACKAGES], suggestions


def detect_functions(request: str) -> list[tuple[str, str]]:
    return list(dict.fromkeys(NAMESPACE_PATTERN.findall(request)))[:3]


def infer_language(request: str, language: str | None) -> str:
    if language is not None:
        value = language.strip().casefold()
        if value in {"ru", "russian", "русский"}:
            return "ru"
        if value in {"en", "english"}:
            return "en"
        if value != "auto":
            raise KnowledgeError("invalid_input", "language must be auto, en or ru")
    return "ru" if re.search(r"[А-Яа-яЁё]", request) else "en"
