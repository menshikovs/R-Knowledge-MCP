"""Validation for caller-supplied, bounded workflow context."""

import json
import re

from ...errors import KnowledgeError

_TEXT_FIELDS = {
    "project_environment": 1000,
    "reproducibility_requirements": 500,
    "deployment_constraints": 500,
    "performance_requirements": 500,
    "security_constraints": 500,
}
_LIST_FIELDS = {"inputs", "outputs", "data_contracts", "technical_constraints"}
_ALLOWED = {*_TEXT_FIELDS, *_LIST_FIELDS, "stage_order"}


def validate_workflow_context(value: dict | None) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > len(_ALLOWED):
        raise KnowledgeError("invalid_input", "workflow_context must be a bounded object")
    unknown = set(value) - _ALLOWED
    if unknown:
        raise KnowledgeError(
            "invalid_input", f"Unsupported workflow_context fields: {', '.join(sorted(unknown))}"
        )
    result = {}
    for key, maximum in _TEXT_FIELDS.items():
        if key not in value:
            continue
        text = value[key]
        if not isinstance(text, str) or len(text) > maximum:
            raise KnowledgeError(
                "invalid_input", f"workflow_context.{key} must be text up to {maximum} characters"
            )
        result[key] = text.strip()
    for key in _LIST_FIELDS:
        if key not in value:
            continue
        items = value[key]
        if not isinstance(items, list) or len(items) > 10:
            raise KnowledgeError(
                "invalid_input", f"workflow_context.{key} must be a list of at most 10 strings"
            )
        clean = []
        for item in items:
            if not isinstance(item, str) or not item.strip() or len(item) > 300:
                raise KnowledgeError(
                    "invalid_input",
                    f"workflow_context.{key} items must be text up to 300 characters",
                )
            clean.append(item.strip())
        result[key] = clean
    if "stage_order" in value:
        order = value["stage_order"]
        if (
            not isinstance(order, list)
            or len(order) > 10
            or any(
                not isinstance(item, str) or not re.fullmatch(r"stage-[a-z0-9-]+", item)
                for item in order
            )
            or len(order) != len(set(order))
        ):
            raise KnowledgeError(
                "invalid_input", "workflow_context.stage_order must contain unique stage ids"
            )
        result["stage_order"] = order
    try:
        size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise KnowledgeError(
            "invalid_input", "workflow_context must contain valid JSON data"
        ) from exc
    if size > 8000:
        raise KnowledgeError("input_too_large", "workflow_context exceeds 8 KiB")
    return result
