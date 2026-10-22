"""Version-controlled prompt template registry; templates are data, never code."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    template_id: str
    task_category: str
    title: str
    description: str
    packages: tuple[str, ...] = ()


TEMPLATES = (
    PromptTemplate(
        "r-package-development",
        "package_development",
        "R package development",
        "Create or extend a maintainable R package.",
        ("testthat", "roxygen2"),
    ),
    PromptTemplate(
        "data-analysis",
        "data_analysis",
        "R data analysis",
        "Plan a reproducible analysis with explicit inputs and outputs.",
    ),
    PromptTemplate(
        "data-transformation",
        "data_transformation",
        "R data transformation",
        "Refactor or build a readable, tested data transformation pipeline.",
        ("dplyr", "tidyr"),
    ),
    PromptTemplate(
        "statistical-modeling",
        "statistical_modeling",
        "R statistical modeling",
        "Make model assumptions, diagnostics and uncertainty explicit.",
    ),
    PromptTemplate(
        "data-visualization",
        "data_visualization",
        "R data visualization",
        "Build an honest, accessible visualization and test its data mappings.",
        ("ggplot2",),
    ),
    PromptTemplate(
        "shiny-app",
        "shiny_development",
        "Shiny application",
        "Design a Shiny application with clear reactive boundaries.",
        ("shiny", "bslib"),
    ),
    PromptTemplate(
        "quarto-report",
        "quarto_reporting",
        "Quarto report",
        "Create a reproducible Quarto document or project.",
        ("knitr",),
    ),
    PromptTemplate(
        "bioconductor-analysis",
        "bioconductor_analysis",
        "Bioconductor analysis",
        "Plan an R and Bioconductor release-aware analysis.",
        ("DESeq2", "SummarizedExperiment"),
    ),
    PromptTemplate(
        "r-debugging",
        "debugging",
        "R debugging",
        "Reproduce and diagnose an R failure before changing code.",
    ),
    PromptTemplate(
        "r-refactoring",
        "refactoring",
        "R refactoring",
        "Improve structure while preserving observable behavior.",
    ),
    PromptTemplate(
        "r-architecture-audit",
        "architecture_review",
        "R architecture review",
        "Review an R project from inspected evidence and report risks.",
    ),
    PromptTemplate(
        "r-test-generation",
        "testing",
        "R test generation",
        "Design deterministic tests around behavior and edge cases.",
        ("testthat",),
    ),
    PromptTemplate(
        "r-reproducibility",
        "reproducibility",
        "R reproducibility",
        "Make package, data and environment assumptions explicit.",
        ("renv",),
    ),
    PromptTemplate(
        "r-performance",
        "performance_optimization",
        "R performance optimization",
        "Measure before optimizing and preserve output semantics.",
        ("bench", "profvis"),
    ),
    PromptTemplate(
        "ggplot2-visualization",
        "data_visualization",
        "ggplot2 visualization",
        "Develop a ggplot2 visualization from explicit data and aesthetic requirements.",
        ("ggplot2",),
    ),
    PromptTemplate(
        "ggraph-workflow",
        "data_visualization",
        "ggraph workflow",
        "Visualize graph data with separate node and edge mappings.",
        ("ggraph",),
    ),
    PromptTemplate(
        "tidyr-pipeline",
        "data_transformation",
        "tidyr pipeline",
        "Reshape tabular data with explicit keys and expected output schema.",
        ("tidyr",),
    ),
    PromptTemplate(
        "plotly-interactivity",
        "data_visualization",
        "Plotly interactivity",
        "Add interaction to a plot with accessibility and rendering checks.",
        ("plotly",),
    ),
    PromptTemplate(
        "knitr-reporting",
        "quarto_reporting",
        "knitr reporting",
        "Create a reproducible R Markdown or Quarto report.",
        ("knitr",),
    ),
    PromptTemplate(
        "r-security-audit",
        "architecture_review",
        "R project security audit",
        "Review data flow, secrets, package execution and deployment boundaries.",
    ),
)

TEMPLATE_BY_ID = {template.template_id: template for template in TEMPLATES}
CATEGORY_TEMPLATE = {
    "package_development": "r-package-development",
    "data_analysis": "data-analysis",
    "data_transformation": "data-transformation",
    "statistical_modeling": "statistical-modeling",
    "data_visualization": "data-visualization",
    "shiny_development": "shiny-app",
    "quarto_reporting": "quarto-report",
    "bioconductor_analysis": "bioconductor-analysis",
    "debugging": "r-debugging",
    "refactoring": "r-refactoring",
    "architecture_review": "r-architecture-audit",
    "testing": "r-test-generation",
    "reproducibility": "r-reproducibility",
    "performance_optimization": "r-performance",
}


def list_templates() -> list[dict[str, str | list[str]]]:
    return [
        {
            "id": template.template_id,
            "task_category": template.task_category,
            "title": template.title,
            "description": template.description,
            "candidate_packages": list(template.packages),
        }
        for template in TEMPLATES
    ]
