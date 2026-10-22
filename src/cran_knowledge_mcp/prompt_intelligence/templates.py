"""Version-controlled prompt template registry; templates are data, never code."""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TemplateComposition:
    required_context: tuple[str, ...] = ()
    optional_context: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    compatible_workflows: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    priority: int = 100
    version: str = "1"


@dataclass(frozen=True)
class PromptTemplate:
    template_id: str
    task_category: str
    title: str
    description: str
    packages: tuple[str, ...] = ()
    function_refs: tuple[tuple[str, str], ...] = ()
    composition: TemplateComposition = field(default_factory=TemplateComposition)


TEMPLATES = (
    PromptTemplate(
        "r-package-development",
        "package_development",
        "R package development",
        "Create or extend a maintainable R package.",
        ("testthat", "roxygen2"),
        composition=TemplateComposition(
            inputs=("package_source",),
            outputs=("r_package", "package_checks"),
            capabilities=("implement_package_api", "document_functions", "test_package"),
            priority=60,
        ),
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
        composition=TemplateComposition(
            inputs=("analysis_data",),
            outputs=("model_results", "model_diagnostics"),
            capabilities=("fit_statistical_model", "validate_assumptions", "report_uncertainty"),
            priority=55,
        ),
    ),
    PromptTemplate(
        "data-visualization",
        "data_visualization",
        "R data visualization",
        "Build an honest, accessible visualization and test its data mappings.",
        ("ggplot2",),
        composition=TemplateComposition(
            inputs=("analysis_results",),
            outputs=("visualizations",),
            capabilities=("map_data_to_visuals", "validate_plot"),
            priority=65,
        ),
    ),
    PromptTemplate(
        "shiny-app",
        "shiny_development",
        "Shiny application",
        "Design a Shiny application with clear reactive boundaries.",
        ("shiny", "bslib"),
        composition=TemplateComposition(
            inputs=("analysis_results",),
            outputs=("shiny_application",),
            capabilities=("build_reactive_ui", "validate_user_inputs"),
            priority=75,
        ),
    ),
    PromptTemplate(
        "quarto-report",
        "quarto_reporting",
        "Quarto report",
        "Create a reproducible Quarto document or project.",
        ("knitr",),
        composition=TemplateComposition(
            inputs=("analysis_results", "visualizations"),
            outputs=("report_artifact",),
            capabilities=("render_reproducible_report", "record_provenance"),
            priority=80,
        ),
    ),
    PromptTemplate(
        "bioconductor-analysis",
        "bioconductor_analysis",
        "Bioconductor analysis",
        "Plan an R and Bioconductor release-aware analysis.",
        ("DESeq2", "SummarizedExperiment"),
        composition=TemplateComposition(
            required_context=("r_version_or_release",),
            optional_context=("r_version", "bioconductor_release", "package_category"),
            inputs=("count_data",),
            outputs=("analysis_results", "bioconductor_results"),
            capabilities=("check_release_compatibility", "analyze_bioconductor_data"),
            priority=50,
        ),
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
    PromptTemplate(
        "csv-import",
        "csv_import",
        "CSV and delimited-file import",
        "Inspect and import delimited data with explicit parsing and memory requirements.",
        ("readr", "data.table", "vroom"),
        (("readr", "read_delim"), ("data.table", "fread"), ("vroom", "vroom")),
        TemplateComposition(
            required_context=("input_format",),
            optional_context=("schema", "encoding", "delimiter", "row_estimate"),
            inputs=("delimited_file",),
            outputs=("parsed_data",),
            capabilities=("parse_delimited_data", "inspect_schema", "plan_memory"),
            compatible_workflows=(
                "csv-analysis",
                "csv-cleaning",
                "csv-validation",
                "csv-sql-pipeline",
            ),
            priority=10,
        ),
    ),
    PromptTemplate(
        "csv-cleaning",
        "data_cleaning",
        "CSV data cleaning",
        "Clean delimited data without assuming column names, types, missingness or duplicate rules.",  # noqa: E501  # Intentional user-facing template description.
        ("dplyr", "tidyr", "janitor"),
        (("janitor", "clean_names"), ("dplyr", "mutate"), ("dplyr", "distinct")),
        TemplateComposition(
            inputs=("parsed_data",),
            outputs=("cleaned_data",),
            capabilities=("transform_data", "normalize_names"),
            priority=30,
        ),
    ),
    PromptTemplate(
        "csv-validation",
        "data_validation",
        "CSV data validation",
        "Define measurable data-quality checks and report failures without silently changing data.",
        ("pointblank", "validate"),
        (("pointblank", "create_agent"), ("validate", "validator")),
        TemplateComposition(
            inputs=("parsed_data", "cleaned_data"),
            outputs=("validated_data", "validation_report"),
            capabilities=("validate_schema", "report_quality_failures"),
            priority=20,
        ),
    ),
    PromptTemplate(
        "csv-analysis",
        "csv_analysis",
        "CSV analysis",
        "Inspect a delimited dataset before analysis and make transformations and outputs reproducible.",  # noqa: E501  # Intentional user-facing template description.
        ("readr", "dplyr", "ggplot2"),
        (("readr", "read_csv"), ("dplyr", "summarise"), ("ggplot2", "ggplot")),
        TemplateComposition(
            inputs=("validated_data",),
            outputs=("analysis_results", "visualizations"),
            capabilities=("summarize_data", "analyze_data"),
            priority=50,
        ),
    ),
    PromptTemplate(
        "csv-export",
        "csv_export",
        "CSV export",
        "Write a deliberate, reproducible delimited output and protect spreadsheet consumers.",
        ("readr", "data.table"),
        (("readr", "write_delim"), ("data.table", "fwrite")),
        TemplateComposition(
            required_context=("output_format",),
            optional_context=("output_path", "encoding", "delimiter"),
            inputs=("validated_data", "analysis_results"),
            outputs=("delimited_output",),
            capabilities=("write_delimited_data",),
            priority=90,
        ),
    ),
    PromptTemplate(
        "sql-query",
        "database_query",
        "SQL query from R",
        "Build a dialect-aware, parameterized query against an explicitly described schema.",
        ("DBI", "dbplyr"),
        (("DBI", "dbGetQuery"), ("DBI", "dbBind"), ("dbplyr", "show_query")),
        TemplateComposition(
            required_context=("database_dialect", "schema"),
            optional_context=("read_only", "pagination", "transaction_policy"),
            inputs=("database_connection", "query_parameters"),
            outputs=("query_result",),
            capabilities=("query_database", "bind_query_values"),
            priority=40,
            conflicts=("write_requires_authorization",),
        ),
    ),
    PromptTemplate(
        "sql-database",
        "database_integration",
        "R database integration",
        "Connect to a named database through DBI with explicit lifecycle and transaction safeguards.",  # noqa: E501  # Intentional user-facing template description.
        ("DBI", "odbc"),
        (("DBI", "dbConnect"), ("DBI", "dbWithTransaction"), ("odbc", "odbc")),
        TemplateComposition(
            required_context=("database_dialect",),
            optional_context=("credential_source", "transaction_policy", "read_only"),
            inputs=("credentials_from_environment",),
            outputs=("database_connection",),
            capabilities=("connect_database", "manage_connection_lifecycle"),
            priority=35,
        ),
    ),
    PromptTemplate(
        "sql-performance",
        "sql_optimization",
        "SQL query performance",
        "Use the target database's query plan and measured workload before changing a query or indexes.",  # noqa: E501  # Intentional user-facing template description.
        ("DBI", "dbplyr", "duckdb"),
        (("dbplyr", "explain"), ("DBI", "dbGetQuery")),
        TemplateComposition(
            required_context=("database_dialect", "workload_or_query"),
            optional_context=("query_plan", "performance_requirements"),
            inputs=("query_result",),
            outputs=("measured_query_plan",),
            capabilities=("inspect_query_plan", "measure_workload"),
            priority=70,
        ),
    ),
    PromptTemplate(
        "sql-schema",
        "database_schema_design",
        "SQL schema design",
        "Design or review a schema using stated entities, keys, constraints and migration safeguards.",  # noqa: E501  # Intentional user-facing template description.
        ("DBI",),
        (("DBI", "dbListTables"), ("DBI", "dbListFields")),
        TemplateComposition(
            required_context=("database_dialect", "entities_or_schema"),
            optional_context=("keys", "indexes", "migration_policy"),
            inputs=("existing_schema",),
            outputs=("schema_design",),
            capabilities=("inspect_schema", "design_schema"),
            priority=25,
            conflicts=("destructive_migration_requires_authorization",),
        ),
    ),
    PromptTemplate(
        "csv-sql-pipeline",
        "etl_pipeline",
        "CSV to SQL pipeline",
        "Plan a validated, restartable delimited-file load with type mapping and transaction-aware checks.",  # noqa: E501  # Intentional user-facing template description.
        ("readr", "DBI", "duckdb"),
        (("readr", "read_delim"), ("DBI", "dbWriteTable"), ("DBI", "dbWithTransaction")),
        TemplateComposition(
            required_context=("input_format", "database_dialect"),
            optional_context=("schema", "duplicate_policy", "batch_size"),
            inputs=("delimited_file",),
            outputs=("database_table", "load_report"),
            dependencies=("csv-import", "csv-validation", "sql-database"),
            capabilities=("validate", "type_map", "transactional_load"),
            priority=15,
            conflicts=("write_requires_authorization",),
        ),
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
    "csv_import": "csv-import",
    "data_cleaning": "csv-cleaning",
    "data_validation": "csv-validation",
    "csv_analysis": "csv-analysis",
    "csv_export": "csv-export",
    "database_query": "sql-query",
    "database_integration": "sql-database",
    "sql_optimization": "sql-performance",
    "database_schema_design": "sql-schema",
    "etl_pipeline": "csv-sql-pipeline",
}


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": template.template_id,
            "task_category": template.task_category,
            "title": template.title,
            "description": template.description,
            "candidate_packages": list(template.packages),
            "function_references": [
                {"package": package, "function": function}
                for package, function in template.function_refs
            ],
            "composition": {
                "required_context": list(template.composition.required_context),
                "optional_context": list(template.composition.optional_context),
                "inputs": list(template.composition.inputs),
                "outputs": list(template.composition.outputs),
                "dependencies": list(template.composition.dependencies),
                "capabilities": list(template.composition.capabilities),
                "compatible_workflows": list(template.composition.compatible_workflows),
                "conflicts": list(template.composition.conflicts),
                "priority": template.composition.priority,
                "version": template.composition.version,
            },
        }
        for template in TEMPLATES
    ]


def validate_template_registry() -> None:
    """Validate the data-only template registry and its composition references."""
    template_ids = set(TEMPLATE_BY_ID)
    if len(template_ids) != len(TEMPLATES):
        raise ValueError("template ids must be unique")
    for template in TEMPLATES:
        metadata = template.composition
        if template.task_category not in CATEGORY_TEMPLATE:
            raise ValueError(f"unknown task category for {template.template_id}")
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", metadata.version):
            raise ValueError(f"invalid composition metadata version for {template.template_id}")
        if not 0 <= metadata.priority <= 1000:
            raise ValueError(f"invalid priority for {template.template_id}")
        if any(
            ref not in template_ids
            for ref in (*metadata.dependencies, *metadata.compatible_workflows)
        ):
            raise ValueError(f"unknown template reference in {template.template_id}")
        for field_name in (
            "required_context",
            "optional_context",
            "inputs",
            "outputs",
            "dependencies",
            "capabilities",
            "compatible_workflows",
            "conflicts",
        ):
            values = getattr(metadata, field_name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"invalid {field_name} metadata in {template.template_id}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(template_id: str) -> None:
        if template_id in visiting:
            raise ValueError(f"template dependency cycle detected at {template_id}")
        if template_id in visited:
            return
        visiting.add(template_id)
        for dependency in TEMPLATE_BY_ID[template_id].composition.dependencies:
            visit(dependency)
        visiting.remove(template_id)
        visited.add(template_id)

    for template_id in sorted(template_ids):
        visit(template_id)
