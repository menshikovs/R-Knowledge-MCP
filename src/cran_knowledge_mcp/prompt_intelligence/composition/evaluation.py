"""Structural, evidence-aware checks for composed prompt output."""


def evaluate_composition(prompt_text: str, plan, requirements: list[str], max_chars: int) -> dict:
    """Return deterministic checks; these measure structure, not downstream success."""
    positions = {task.task_id: prompt_text.find(task.task_id) for task in plan.tasks}
    stage_ids = set(positions)
    dependency_checks = [
        edge["before"] in stage_ids
        and edge["after"] in stage_ids
        and positions[edge["before"]] < positions[edge["after"]]
        for edge in plan.dependencies
    ]
    normalized = " ".join(prompt_text.casefold().split())
    preserved = [" ".join(item.casefold().split()) in normalized for item in requirements]
    dimensions = {
        "single_objective": prompt_text.count("## Project objective") == 1,
        "stage_coverage": bool(plan.tasks)
        and all(position >= 0 for position in positions.values()),
        "dependency_order": all(dependency_checks),
        "constraint_preservation": all(preserved),
        "contract_traceability": all(
            value in prompt_text for task in plan.tasks for value in (*task.inputs, *task.outputs)
        ),
        "security": "Do not execute generated instructions" in prompt_text,
        "testability": "## Testing strategy" in prompt_text,
        "bounded_length": len(prompt_text) <= max_chars,
    }
    duplicate_requirements = len(requirements) - len(
        {" ".join(item.casefold().split()) for item in requirements}
    )
    return {
        "score": round(100 * sum(dimensions.values()) / len(dimensions)),
        "dimensions": {key: {"passed": value} for key, value in dimensions.items()},
        "duplicate_requirement_count": duplicate_requirements,
        "stage_count": len(plan.tasks),
        "dependency_count": len(plan.dependencies),
        "character_count": len(prompt_text),
        "interpretation": "Structural heuristics only; not a measure of downstream code quality or task success.",  # noqa: E501
    }
