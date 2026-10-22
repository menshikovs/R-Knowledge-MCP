"""Typed workflow contracts used by the composable prompt engine."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowTask:
    task_id: str
    description: str
    category: str
    template_ids: tuple[str, ...]
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    confidence: str = "inferred"
    position: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowPlan:
    tasks: tuple[WorkflowTask, ...]
    dependencies: tuple[dict[str, str], ...]
    parallel_groups: tuple[tuple[str, ...], ...]
    selected_templates: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [task.to_dict() for task in self.tasks],
            "dependencies": list(self.dependencies),
            "parallel_groups": [list(group) for group in self.parallel_groups],
            "selected_templates": list(self.selected_templates),
            "warnings": list(self.warnings),
            "conflicts": list(self.conflicts),
            "assumptions": list(self.assumptions),
        }
