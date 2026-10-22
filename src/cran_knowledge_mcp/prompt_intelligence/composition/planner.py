"""Deterministic bounded DAG planning for downstream workflow instructions."""

from collections import defaultdict

from ...errors import KnowledgeError
from ..templates import TEMPLATE_BY_ID
from .decomposer import MAX_WORKFLOW_TASKS
from .models import WorkflowPlan, WorkflowTask

_CATEGORY_EDGES = {
    ("csv_import", "data_validation"),
    ("csv_import", "database_integration"),
    ("csv_import", "database_query"),
    ("data_cleaning", "csv_analysis"),
    ("data_cleaning", "data_visualization"),
    ("data_cleaning", "shiny_development"),
    ("data_validation", "database_integration"),
    ("data_validation", "database_query"),
    ("data_validation", "csv_analysis"),
    ("database_integration", "database_query"),
    ("database_integration", "csv_analysis"),
    ("database_query", "csv_analysis"),
    ("csv_analysis", "statistical_modeling"),
    ("data_validation", "statistical_modeling"),
    ("bioconductor_analysis", "statistical_modeling"),
    ("statistical_modeling", "data_visualization"),
    ("statistical_modeling", "quarto_reporting"),
    ("csv_analysis", "csv_export"),
    ("data_validation", "csv_export"),
    ("database_query", "sql_optimization"),
    ("bioconductor_analysis", "data_visualization"),
    ("bioconductor_analysis", "shiny_development"),
    ("csv_analysis", "data_visualization"),
    ("data_visualization", "quarto_reporting"),
    ("csv_analysis", "quarto_reporting"),
    ("data_cleaning", "quarto_reporting"),
    ("package_development", "quarto_reporting"),
    ("package_development", "testing"),
}


class DependencyPlanner:
    """Build a stable topological order and parallelizable layers."""

    def plan(
        self,
        tasks: list[WorkflowTask],
        selected_templates: list[str] | None = None,
        stage_order: list[str] | None = None,
        warnings: list[str] | None = None,
        conflicts: list[str] | None = None,
        assumptions: list[str] | None = None,
    ) -> WorkflowPlan:
        if not 1 <= len(tasks) <= MAX_WORKFLOW_TASKS:
            raise KnowledgeError(
                "invalid_input", f"Workflow must have 1..{MAX_WORKFLOW_TASKS} stages"
            )
        task_by_id = {task.task_id: task for task in tasks}
        if len(task_by_id) != len(tasks):
            raise KnowledgeError("invalid_input", "Workflow stage ids must be unique")
        task_ids = set(task_by_id)
        edges: set[tuple[str, str]] = set()

        for task in tasks:
            for dependency in task.dependencies:
                if dependency not in task_ids:
                    raise KnowledgeError(
                        "invalid_input", f"Unknown workflow dependency: {dependency}"
                    )
                if dependency == task.task_id:
                    raise KnowledgeError(
                        "invalid_input", "A workflow stage cannot depend on itself"
                    )
                edges.add((dependency, task.task_id))

        # Add edges from explicit input/output contracts, respecting request order.
        for consumer in tasks:
            for producer in tasks:
                if producer.position < consumer.position and set(producer.outputs) & set(
                    consumer.inputs
                ):
                    edges.add((producer.task_id, consumer.task_id))

        # Add workflow semantics where task names alone do not express the handoff.
        by_category: dict[str, list[WorkflowTask]] = defaultdict(list)
        by_template: dict[str, list[WorkflowTask]] = defaultdict(list)
        for task in tasks:
            by_category[task.category].append(task)
            for template_id in task.template_ids:
                by_template[template_id].append(task)
        for before_category, after_category in _CATEGORY_EDGES:
            for before in by_category[before_category]:
                for after in by_category[after_category]:
                    if before.task_id != after.task_id:
                        edges.add((before.task_id, after.task_id))

        selected = set(selected_templates or [t for task in tasks for t in task.template_ids])
        for template_id in selected:
            template = TEMPLATE_BY_ID.get(template_id)
            if template is None:
                raise KnowledgeError("invalid_input", f"Unknown template id: {template_id}")
            for dependency_template in template.composition.dependencies:
                if dependency_template not in selected:
                    continue
                for producer in by_template[dependency_template]:
                    for consumer in by_template[template_id]:
                        if producer.task_id != consumer.task_id:
                            edges.add((producer.task_id, consumer.task_id))

        # A caller can request an explicit sequence of stage IDs; only those adjacent
        # pairs are ordered, leaving unrelated stages eligible to run in parallel.
        if stage_order is not None:
            if (
                not isinstance(stage_order, list)
                or len(stage_order) > MAX_WORKFLOW_TASKS
                or any(stage_id not in task_ids for stage_id in stage_order)
                or len(stage_order) != len(set(stage_order))
            ):
                raise KnowledgeError(
                    "invalid_input", "stage_order must list unique known stage ids"
                )
            edges.update(zip(stage_order, stage_order[1:], strict=False))

        indegree = {task_id: 0 for task_id in task_ids}
        children: dict[str, set[str]] = defaultdict(set)
        for before, after in edges:
            if before not in task_ids or after not in task_ids:
                raise KnowledgeError("invalid_input", "Workflow edge references an unknown stage")
            if after not in children[before]:
                children[before].add(after)
                indegree[after] += 1

        def stable_key(task_id: str) -> tuple[int, str]:
            return task_by_id[task_id].position, task_id

        ready = sorted(
            (task_id for task_id, count in indegree.items() if count == 0), key=stable_key
        )
        ordered: list[WorkflowTask] = []
        groups: list[tuple[str, ...]] = []
        while ready:
            layer = tuple(ready)
            groups.append(layer)
            next_ready = []
            for task_id in layer:
                ordered.append(task_by_id[task_id])
                for child in sorted(children[task_id], key=stable_key):
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        next_ready.append(child)
            ready = sorted(set(next_ready), key=stable_key)
        if len(ordered) != len(tasks):
            cyclic = sorted(task_id for task_id, count in indegree.items() if count)
            raise KnowledgeError(
                "invalid_workflow", f"Workflow dependency cycle detected: {', '.join(cyclic)}"
            )
        dependency_list = tuple(
            {"before": before, "after": after}
            for before, after in sorted(
                edges, key=lambda pair: (stable_key(pair[1]), stable_key(pair[0]))
            )
        )
        ordered_selected_templates = tuple(
            dict.fromkeys(template for task in ordered for template in task.template_ids)
        )
        return WorkflowPlan(
            tasks=tuple(ordered),
            dependencies=dependency_list,
            parallel_groups=tuple(groups),
            selected_templates=ordered_selected_templates,
            warnings=tuple(warnings or []),
            conflicts=tuple(conflicts or []),
            assumptions=tuple(assumptions or []),
        )
