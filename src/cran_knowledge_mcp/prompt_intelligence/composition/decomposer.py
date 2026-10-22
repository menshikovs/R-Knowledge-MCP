"""Bounded rule-based decomposition; it does not infer unseen project state."""

import re
from dataclasses import replace

from ...errors import KnowledgeError
from ..templates import CATEGORY_TEMPLATE
from .models import WorkflowTask

MAX_WORKFLOW_TASKS = 10


_RULES = (
    (
        "csv_import",
        r"\b(csv|tsv|delimited file)\b.{0,90}\b(import|read|load|ingest|parse)\b|"
        r"\b(import|read|load|ingest|parse)\b.{0,90}\b(csv|tsv|delimited file)\b",
        "Inspect and parse the supplied delimited input using explicit schema and locale assumptions.",  # noqa: E501
        ("delimited_file",),
        ("parsed_data",),
        (
            "Confirm the header, delimiter, encoding, types, missing-value tokens and date/time zone.",  # noqa: E501
        ),
    ),
    (
        "data_cleaning",
        r"\b(clean|cleaning|transform|reshape|pivot)\w*\b.{0,90}\b(data|csv|table|dataset|column|row)\w*\b|"
        r"\b(data|csv|table|dataset)\w*\b.{0,90}\b(clean|transform|reshape|pivot)\w*\b",
        "Transform and clean data while preserving explicit keys and documenting each change.",
        ("parsed_data",),
        ("cleaned_data",),
        ("Do not invent column names, duplicate rules or missing-value replacements.",),
    ),
    (
        "data_validation",
        r"\b(validat|quality check|integrity check|assert|schema check)\w*\b|"
        r"\b(check|verify)\w*\b.{0,60}\b(data quality|schema|row count|integrity)\b",
        "Validate schema, types, missingness, keys, row counts and stage-to-stage integrity.",
        ("parsed_data", "cleaned_data"),
        ("validated_data", "validation_report"),
        ("Report failures separately; validation must not silently modify data.",),
    ),
    (
        "database_integration",
        r"\b(postgresql|postgres|sqlite|duckdb|mysql|mariadb|sql server|database)\b.{0,100}\b(connect|load|write|insert|store|import|integrat)\w*\b|"  # noqa: E501
        r"\b(connect|load|write|insert|store|import|integrat)\w*\b.{0,100}\b(postgresql|postgres|sqlite|duckdb|mysql|mariadb|sql server|database)\b|"  # noqa: E501
        r"\b(postgresql|postgres|sqlite|duckdb|mysql|mariadb|sql server)\b.{0,50}\bbackend\b",
        "Integrate with the selected database through the named R driver and safe connection lifecycle.",  # noqa: E501
        ("validated_data", "database_connection"),
        ("database_table", "load_report"),
        (
            "Parameterize values, quote identifiers safely, use least privilege and define transaction rollback.",  # noqa: E501
        ),
    ),
    (
        "database_query",
        r"\b(query|queries|sql|select|join|dbplyr)\b.{0,80}\b(postgresql|postgres|sqlite|duckdb|mysql|mariadb|sql server|database|table)\b|"  # noqa: E501
        r"\b(postgresql|postgres|sqlite|duckdb|mysql|mariadb|sql server|database)\b.{0,80}\b(query|queries|sql|select|join)\b|"  # noqa: E501
        r"\b(using|with|on)\s+(postgresql|postgres|sqlite|duckdb|mysql|mariadb|sql server)\b",
        "Build a dialect-specific query against caller-supplied schema and parameters.",
        ("database_connection", "query_parameters"),
        ("query_result",),
        (
            "Parameterize data values and handle identifiers separately; do not claim SQL portability.",  # noqa: E501
        ),
    ),
    (
        "sql_optimization",
        r"\b(sql|query|database)\b.{0,60}\b(optim|performance|explain|query plan|slow)\w*\b|"
        r"\b(optim|performance|explain|query plan|slow)\w*\b.{0,60}\b(sql|query|database)\b",
        "Measure the target engine, workload and query plan before changing SQL or indexes.",
        ("query_result",),
        ("measured_query_plan",),
        ("Compare semantics and performance with reproducible measurements.",),
    ),
    (
        "database_schema_design",
        r"\b(database|sql|table)\b.{0,50}\b(schema|normaliz|primary key|foreign key|migration)\w*\b|"  # noqa: E501
        r"\b(schema|normaliz|primary key|foreign key)\w*\b.{0,50}\b(database|sql|table)\b",
        "Inspect and design a schema from supplied entities, keys, nullability and constraints.",
        ("existing_schema",),
        ("schema_design",),
        ("Require authorization, backup and rollback before destructive migration operations.",),
    ),
    (
        "csv_analysis",
        r"\b(analy[sz]|summari[sz]|exploratory|statistical)\w*\b.{0,70}\b(csv|data|dataset|table)\b|"
        r"\b(csv|data|dataset|table)\b.{0,70}\b(analy[sz]|summari[sz]|exploratory)\w*\b",
        "Analyze validated data with stated assumptions, summary outputs and reproducible checks.",
        ("validated_data",),
        ("analysis_results",),
        ("State statistical assumptions and report uncertainty; do not infer unseen data.",),
    ),
    (
        "statistical_modeling",
        r"\b(fit|build|estimate|compare|validate|diagnose)\b.{0,70}\b(model|regression|survival|hypothesis|mixed.effects?)\b|"
        r"\b(modeling|modelling|regression|survival analysis|hypothesis test|mixed.effects? model)\b",  # noqa: E501
        "Specify the estimand, model assumptions, diagnostics, uncertainty and validation strategy.",  # noqa: E501
        ("analysis_data",),
        ("model_results", "model_diagnostics"),
        ("Report uncertainty and do not infer a causal interpretation without a stated design.",),
    ),
    (
        "csv_export",
        r"\b(export|write|save|serialize)\w*\b.{0,80}\b(csv|tsv|delimited|flat file)\b|"
        r"\b(csv|tsv|delimited|flat file)\b.{0,80}\b(export|write|save)\w*\b",
        "Export a deliberate, reproducible delimited output with explicit formatting and path safeguards.",  # noqa: E501
        ("validated_data", "analysis_results"),
        ("delimited_output",),
        (
            "Specify format and protect spreadsheet consumers from formula injection where relevant.",  # noqa: E501
        ),
    ),
    (
        "data_visualization",
        r"\b(visuali[sz]|plot|chart|graph|interactive dashboard)\w*\b|"
        r"\b(ggplot2|ggraph|plotly)\b.{0,35}\b(charts?|plots?|visuali[sz]ations?|dashboard)\b",
        "Create visual outputs from validated data with explicit mappings and interpretation limits.",  # noqa: E501
        ("analysis_results",),
        ("visualizations",),
        ("Check missing values, scales, labels, accessibility and rendered output.",),
    ),
    (
        "shiny_development",
        r"\b(shiny|bslib)\b.{0,40}\b(app|application|dashboard|ui|server|reactive)\b|"
        r"\b(build|create|develop|implement)\b.{0,40}\b(shiny app|shiny application|dashboard)\b",
        "Design the Shiny application around explicit reactive state and validated inputs.",
        ("analysis_results",),
        ("shiny_application",),
        ("Test reactive behavior, invalid inputs and user-visible errors.",),
    ),
    (
        "quarto_reporting",
        r"\b(quarto|knitr|rmarkdown|\.qmd)\b.{0,50}\b(report|tutorial|document|render|project)\w*\b|"
        r"\b(report|tutorial|document)\w*\b.{0,50}\b(quarto|knitr|rmarkdown|\.qmd)\b",
        "Create a reproducible report or tutorial from verified analysis artifacts.",
        ("analysis_results", "visualizations"),
        ("report_artifact",),
        ("Validate render outputs and record data, package and environment assumptions.",),
    ),
    (
        "bioconductor_analysis",
        r"\b(rna[- ]?seq|differential expression|summarizedexperiment|bioconductor)\b|"
        r"\bdeseq2\b.{0,50}\b(analysis|workflow|pipeline|count|expression)\w*\b|"
        r"\b(analysis|workflow|pipeline|count|expression)\w*\b.{0,50}\bdeseq2\b",
        "Plan an R/Bioconductor analysis against an explicit R and Bioconductor release.",
        ("count_data",),
        ("analysis_results", "bioconductor_results"),
        (
            "Preserve release compatibility and distinguish package repository versions from installed versions.",  # noqa: E501
        ),
    ),
    (
        "package_development",
        r"\b(r package|package development|develop an? package|package documentation)\b",
        "Implement an R package change with documented behavior, tests and build checks.",
        ("package_source",),
        ("r_package", "package_checks"),
        ("Preserve the public API unless an explicit breaking change is requested.",),
    ),
    (
        "testing",
        r"\b(test|testing|unit test|integration test|end.to.end test)\w*\b",
        "Test the integrated workflow at unit, interface and end-to-end boundaries.",
        ("workflow_components",),
        ("test_results",),
        ("Use deterministic fixtures and report only tests actually run.",),
    ),
    (
        "reproducibility",
        r"\b(reproducib|renv|lockfile|offline|environment pin)\w*\b",
        "Record package, R and data provenance so the workflow can be reproduced.",
        ("package_versions", "input_provenance"),
        ("reproducibility_record",),
        ("Do not treat repository metadata as proof of the local installed environment.",),
    ),
    (
        "etl_pipeline",
        r"\b(etl|elt|csv.to.sql pipeline|data ingestion pipeline)\b",
        "Plan an idempotent, validated and restartable data loading pipeline.",
        ("delimited_file", "database_connection"),
        ("database_table", "load_report"),
        ("Bound batches, define duplicate policy and specify rollback and row-count checks.",),
    ),
)


class TaskDecomposer:
    """Detect workflow activities using fixed rules and bounded input."""

    def decompose(self, request: str, workflow_context: dict | None = None) -> list[WorkflowTask]:
        hits = []
        inferred_categories: set[str] = set()
        for category, pattern, description, inputs, outputs, constraints in _RULES:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                hits.append((match.start(), category, description, inputs, outputs, constraints))
        database_work = any(item[1] in {"database_integration", "database_query"} for item in hits)
        if (
            database_work
            and any(item[1] == "csv_import" for item in hits)
            and not any(item[1] == "data_validation" for item in hits)
        ):
            csv_position = next(item[0] for item in hits if item[1] == "csv_import")
            hits.append(
                (
                    csv_position + 1,
                    "data_validation",
                    "Validate parsed rows and schema before database writes.",
                    ("parsed_data",),
                    ("validated_data", "validation_report"),
                    ("Keep validation read-only and report rejected rows.",),
                )
            )
            inferred_categories.add("data_validation")
        # Large CSV analysis through an explicitly named database implies ingestion,
        # even when the user did not use an import verb.
        if (
            re.search(r"\b(csv|tsv)\b", request, re.I)
            and re.search(r"\b(large|big|million|millions|gigabyte|gb)\b", request, re.I)
            and any(item[1] in {"database_query", "database_integration"} for item in hits)
            and not any(item[1] == "csv_import" for item in hits)
        ):
            position = re.search(r"\b(csv|tsv)\b", request, re.I).start()
            hits.append(
                (
                    position,
                    "csv_import",
                    "Inspect and stream or chunk the large delimited input using explicit schema and memory constraints.",  # noqa: E501
                    ("delimited_file",),
                    ("parsed_data",),
                    ("Measure memory and row counts; avoid loading an unbounded file eagerly.",),
                )
            )
            inferred_categories.add("csv_import")
            if not any(item[1] == "data_validation" for item in hits):
                hits.append(
                    (
                        position + 1,
                        "data_validation",
                        "Validate parsed rows and schema before database analysis.",
                        ("parsed_data",),
                        ("validated_data", "validation_report"),
                        ("Keep validation read-only and report rejected rows.",),
                    )
                )
                inferred_categories.add("data_validation")
        hits.sort(key=lambda item: (item[0], item[1]))
        if (
            any(item[1] == "data_visualization" for item in hits)
            and any(
                item[1]
                in {
                    "csv_import",
                    "data_cleaning",
                    "data_validation",
                    "database_query",
                    "database_integration",
                }
                for item in hits
            )
            and not any(item[1] in {"csv_analysis", "bioconductor_analysis"} for item in hits)
        ):
            visual_position = next(item[0] for item in hits if item[1] == "data_visualization")
            hits.append(
                (
                    visual_position,
                    "csv_analysis",
                    "Summarize the validated workflow data and record analytical assumptions before visualization.",  # noqa: E501
                    ("validated_data",),
                    ("analysis_results",),
                    ("State analysis assumptions and avoid claims beyond observed data.",),
                )
            )
            inferred_categories.add("csv_analysis")
            hits.sort(key=lambda item: (item[0], item[1]))
        if len(hits) > MAX_WORKFLOW_TASKS:
            raise KnowledgeError(
                "invalid_input",
                f"Workflow has more than {MAX_WORKFLOW_TASKS} inferred stages; narrow or split the request",  # noqa: E501
            )
        database_positions = [
            position
            for position, category, *_ in hits
            if category in {"database_integration", "database_query"}
        ]
        seen = set()
        tasks = []
        for position, category, description, inputs, outputs, constraints in hits:
            if category in seen:
                continue
            seen.add(category)
            template_id = CATEGORY_TEMPLATE[category]
            if category == "data_cleaning" and any(
                db_position < position for db_position in database_positions
            ):
                inputs = ("database_table",)
            tasks.append(
                WorkflowTask(
                    task_id=f"stage-{category.replace('_', '-')}",
                    description=description,
                    category=category,
                    template_ids=(template_id,),
                    inputs=inputs,
                    outputs=outputs,
                    constraints=constraints,
                    confidence=(
                        "derived_for_dataflow"
                        if category in inferred_categories
                        else "explicit_signal"
                    ),
                    position=position,
                )
            )
        categories = {task.category for task in tasks}
        task_updates = []
        for task in tasks:
            if task.category == "data_cleaning":
                source = (
                    "database_table"
                    if "database_integration" in categories
                    else "parsed_data"
                    if "csv_import" in categories
                    else "caller_supplied_data"
                )
                task = replace(task, inputs=(source,))
            elif task.category == "data_validation" and "csv_import" not in categories:
                task = replace(task, inputs=("caller_supplied_data",))
            elif task.category == "csv_analysis":
                source = (
                    "cleaned_data"
                    if "data_cleaning" in categories
                    else "query_result"
                    if "database_query" in categories
                    else "bioconductor_results"
                    if "bioconductor_analysis" in categories
                    else "validated_data"
                    if "data_validation" in categories
                    else "caller_supplied_analysis_data"
                )
                task = replace(task, inputs=(source,))
            elif task.category == "statistical_modeling":
                source = (
                    "analysis_results"
                    if "csv_analysis" in categories
                    else "bioconductor_results"
                    if "bioconductor_analysis" in categories
                    else "validated_data"
                    if "data_validation" in categories
                    else "caller_supplied_analysis_data"
                )
                task = replace(task, inputs=(source,))
            elif task.category == "data_visualization":
                source = (
                    "model_results"
                    if "statistical_modeling" in categories
                    else "analysis_results"
                    if categories & {"csv_analysis", "bioconductor_analysis"}
                    else "cleaned_data"
                    if "data_cleaning" in categories
                    else "validated_data"
                    if "data_validation" in categories
                    else "caller_supplied_plot_data"
                )
                task = replace(task, inputs=(source,))
            elif task.category == "shiny_development":
                source = (
                    "analysis_results"
                    if categories & {"csv_analysis", "bioconductor_analysis"}
                    else "validated_data"
                    if "data_validation" in categories
                    else "caller_supplied_shiny_data"
                )
                task = replace(task, inputs=(source,))
            elif task.category == "quarto_reporting" and "package_development" in categories:
                source = (
                    ("r_package", "analysis_results")
                    if "csv_analysis" in categories
                    else ("r_package",)
                )
                task = replace(task, inputs=source)
            elif task.category == "quarto_reporting":
                if "statistical_modeling" in categories:
                    inputs = (
                        ("model_results", "visualizations")
                        if "data_visualization" in categories
                        else ("model_results",)
                    )
                elif "csv_analysis" in categories or "bioconductor_analysis" in categories:
                    inputs = (
                        ("analysis_results", "visualizations")
                        if "data_visualization" in categories
                        else ("analysis_results",)
                    )
                elif "data_visualization" in categories:
                    inputs = ("visualizations",)
                else:
                    inputs = ("caller_supplied_report_content",)
                task = replace(task, inputs=inputs)
            elif task.category == "csv_export":
                source = (
                    "analysis_results"
                    if "csv_analysis" in categories
                    else "validated_data"
                    if "data_validation" in categories
                    else "caller_supplied_export_data"
                )
                task = replace(task, inputs=(source,))
            task_updates.append(task)
        tasks = task_updates
        if len(tasks) > 1 and "testing" not in categories:
            if len(tasks) >= MAX_WORKFLOW_TASKS:
                raise KnowledgeError(
                    "invalid_input",
                    f"Workflow exceeds the {MAX_WORKFLOW_TASKS}-stage limit after adding integration validation",  # noqa: E501
                )
            tasks.append(
                WorkflowTask(
                    task_id="stage-integration-validation",
                    description="Validate the complete workflow across data and artifact boundaries.",  # noqa: E501
                    category="testing",
                    template_ids=(CATEGORY_TEMPLATE["testing"],),
                    inputs=("workflow_components",),
                    outputs=("end_to_end_test_results",),
                    dependencies=tuple(task.task_id for task in tasks),
                    constraints=(
                        "Use deterministic fixtures; never use production credentials or data.",
                    ),
                    confidence="default_for_multi_stage_workflow",
                    position=len(request) + 1,
                )
            )
        return tasks
