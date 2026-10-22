"""Resolve decomposed workflow tasks to the existing versioned template registry."""

from ...errors import KnowledgeError
from ..templates import TEMPLATE_BY_ID, TemplateComposition, validate_template_registry
from .models import WorkflowTask

MAX_SELECTED_TEMPLATES = 8


class TemplateResolver:
    def __init__(self) -> None:
        validate_template_registry()

    def resolve(
        self,
        tasks: list[WorkflowTask],
        request: str,
        explicit_templates: list[str] | None = None,
    ) -> tuple[list[WorkflowTask], list[str]]:
        if explicit_templates is not None:
            if (
                not isinstance(explicit_templates, list)
                or not 1 <= len(explicit_templates) <= MAX_SELECTED_TEMPLATES
                or any(not isinstance(value, str) for value in explicit_templates)
            ):
                raise KnowledgeError(
                    "invalid_input",
                    f"templates must contain 1..{MAX_SELECTED_TEMPLATES} template ids",
                )
            requested = list(dict.fromkeys(explicit_templates))
            unknown = [value for value in requested if value not in TEMPLATE_BY_ID]
            if unknown:
                raise KnowledgeError("invalid_input", f"Unknown template ids: {', '.join(unknown)}")
            tasks = self._tasks_for_explicit(requested)
        else:
            tasks = [self._specialize(task, request) for task in tasks]
        selected = list(dict.fromkeys(template for task in tasks for template in task.template_ids))
        if len(selected) > MAX_SELECTED_TEMPLATES:
            raise KnowledgeError(
                "invalid_input", f"At most {MAX_SELECTED_TEMPLATES} templates may be composed"
            )
        selected = list(dict.fromkeys(selected))
        if len(selected) > MAX_SELECTED_TEMPLATES:
            raise KnowledgeError("invalid_input", "Resolved workflow exceeds the template limit")
        return tasks, selected

    @staticmethod
    def _tasks_for_explicit(template_ids: list[str]) -> list[WorkflowTask]:
        result = []
        for index, template_id in enumerate(template_ids):
            template = TEMPLATE_BY_ID[template_id]
            metadata: TemplateComposition = template.composition
            result.append(
                WorkflowTask(
                    task_id=f"stage-{index + 1:02d}-{template.task_category.replace('_', '-')}",
                    description=template.description,
                    category=template.task_category,
                    template_ids=(template_id,),
                    inputs=metadata.inputs,
                    outputs=metadata.outputs,
                    constraints=(),
                    confidence="explicit_template_selection",
                    position=index,
                )
            )
        return result

    @staticmethod
    def _specialize(task: WorkflowTask, request: str) -> WorkflowTask:
        lowered = request.casefold()
        template_id = task.template_ids[0]
        if task.category == "data_visualization":
            if "plotly" in lowered:
                template_id = "plotly-interactivity"
            elif "ggraph" in lowered:
                template_id = "ggraph-workflow"
            elif "ggplot2" in lowered:
                template_id = "ggplot2-visualization"
        elif task.category == "data_transformation":
            if "tidyr" in lowered:
                template_id = "tidyr-pipeline"
        elif task.category == "data_cleaning":
            if "tidyr" in lowered:
                template_id = "tidyr-pipeline"
            elif not any(token in lowered for token in ("csv", "tsv", "delimited")):
                template_id = "data-transformation"
        elif task.category == "quarto_reporting" and "knitr" in lowered:
            template_id = "knitr-reporting"
        elif task.category == "csv_analysis":
            template_id = "csv-analysis"
        return WorkflowTask(**{**task.to_dict(), "template_ids": (template_id,)})
