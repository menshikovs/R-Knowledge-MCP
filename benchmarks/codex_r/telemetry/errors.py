"""Normalized error taxonomy: origin, category and reason_code are independent fields.

``reason_code`` is the stable, coarse cause (``MCP_PROVIDER_ERROR``). ``origin`` says which
component reported it and ``category`` refines it (``not_found``, ``upstream``,
``resource_limit``...). The machine-readable code that produced a classification is kept in
``source_code`` so nothing is lost when a code is not yet mapped: unknown codes become
``UNCLASSIFIED_ERROR`` with ``source_code`` intact.
"""

from __future__ import annotations

import re

REASON_CODES = {
    "MODEL_TIMEOUT": ("model", "timeout"),
    "MODEL_GENERATION_ERROR": ("model", "generation"),
    "MCP_DISCOVERY_FAILED": ("mcp_server", "discovery"),
    "MCP_TRANSPORT_ERROR": ("mcp_transport", "transport"),
    "MCP_TOOL_TIMEOUT": ("mcp_server", "timeout"),
    "MCP_PROVIDER_ERROR": ("mcp_server", "provider"),
    "MCP_PARTIAL_RESULT": ("mcp_server", "partial_result"),
    "MCP_INVALID_RESPONSE": ("mcp_transport", "invalid_response"),
    "R_SYNTAX_ERROR": ("candidate", "r_syntax"),
    "R_RUNTIME_ERROR": ("candidate", "r_runtime"),
    "ARTIFACT_INVALID": ("candidate", "artifact"),
    "SCORER_INFRA_ERROR": ("scorer", "infrastructure"),
    "SCORER_UNSUPPORTED_CLAIMS": ("scorer", "evidence_insufficiency"),
    "CLEANUP_ERROR": ("cleanup", "cleanup"),
    "INTERRUPTED": ("runner", "interrupt"),
    "UNCLASSIFIED_ERROR": ("unknown", "unclassified"),
}

# Server-reported application error codes -> (reason_code, category).
# A refusal by CRAN/Bioconductor or an unusable upstream file stays MCP_PROVIDER_ERROR even
# when the agent later fails to finish its task.
MCP_CODES = {
    "timeout": ("MCP_TOOL_TIMEOUT", "timeout"),
    "package_not_found": ("MCP_PROVIDER_ERROR", "not_found"),
    "docs_not_found": ("MCP_PROVIDER_ERROR", "not_found"),
    "not_found": ("MCP_PROVIDER_ERROR", "not_found"),
    "ambiguous_docs": ("MCP_PROVIDER_ERROR", "ambiguous"),
    "invalid_input": ("MCP_PROVIDER_ERROR", "invalid_request"),
    "invalid_r_syntax": ("MCP_PROVIDER_ERROR", "invalid_request"),
    "input_too_large": ("MCP_PROVIDER_ERROR", "invalid_request"),
    "input_too_complex": ("MCP_PROVIDER_ERROR", "invalid_request"),
    "tool_not_found": ("MCP_PROVIDER_ERROR", "invalid_request"),
    "version_mismatch": ("MCP_PROVIDER_ERROR", "version_mismatch"),
    "requested_version_unavailable": ("MCP_PROVIDER_ERROR", "version_mismatch"),
    "checksum_mismatch": ("MCP_PROVIDER_ERROR", "integrity"),
    "invalid_source": ("MCP_PROVIDER_ERROR", "source_invalid"),
    "unsupported_encoding": ("MCP_PROVIDER_ERROR", "source_invalid"),
    "source_too_large": ("MCP_PROVIDER_ERROR", "resource_limit"),
    "response_too_large": ("MCP_PROVIDER_ERROR", "resource_limit"),
    "rate_limited": ("MCP_PROVIDER_ERROR", "upstream"),
    "blocked_url": ("MCP_PROVIDER_ERROR", "policy"),
    "invalid_configuration": ("MCP_PROVIDER_ERROR", "configuration"),
    "internal_error": ("MCP_PROVIDER_ERROR", "internal"),
    "index_write_failed": ("MCP_PROVIDER_ERROR", "internal"),
    "integration_disabled": ("MCP_PROVIDER_ERROR", "integration"),
    "repository_not_verified": ("MCP_PROVIDER_ERROR", "integration"),
}
# Categories that describe a normal answer ("no such thing") rather than a malfunction.
AGENT_OUTCOME = frozenset(
    {
        "MODEL_TIMEOUT",
        "MODEL_GENERATION_ERROR",
        "ARTIFACT_INVALID",
        "R_SYNTAX_ERROR",
        "R_RUNTIME_ERROR",
        "UNCLASSIFIED_ERROR",
    }
)
INFORMATIONAL_CATEGORIES = frozenset({"not_found", "ambiguous", "invalid_request"})

SCORER_REASONS = {
    "invalid_json_answer": ("ARTIFACT_INVALID", "artifact"),
    "answer_too_large": ("ARTIFACT_INVALID", "artifact"),
    "output_limit": ("R_RUNTIME_ERROR", "output_limit"),
    "scorer_deadline": ("R_RUNTIME_ERROR", "timeout"),
    "unparseable_result": ("SCORER_INFRA_ERROR", "protocol"),
    "ambiguous_result": ("SCORER_INFRA_ERROR", "protocol"),
    "invalid_result_shape": ("SCORER_INFRA_ERROR", "protocol"),
    "unsupported_claims_unknown": (
        "SCORER_UNSUPPORTED_CLAIMS",
        "evidence_insufficiency",
    ),
    "unsupported_for_automatic_scoring": (
        "SCORER_UNSUPPORTED_CLAIMS",
        "evidence_insufficiency",
    ),
}
_SNAKE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def snake(value) -> str | None:
    """Lower-case a machine code if it is safe to keep; otherwise drop it."""
    if not isinstance(value, str):
        return None
    candidate = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return candidate if _SNAKE.fullmatch(candidate) else None


def make_error(reason_code, *, category=None, source_code=None, severity=None, count=None):
    """Build a normalized error object; unknown reason codes are kept as unclassified."""
    if reason_code not in REASON_CODES:
        source_code, reason_code = source_code or snake(reason_code), "UNCLASSIFIED_ERROR"
    origin, default_category = REASON_CODES[reason_code]
    error = {
        "origin": origin,
        "category": category or default_category,
        "reason_code": reason_code,
        "source_code": snake(source_code),
    }
    if severity is not None:
        error["severity"] = severity
    if count is not None:
        error["count"] = count
    return error


def classify_mcp_code(code) -> dict:
    """Map a server error code (error.code or errors[].error.code) without losing it."""
    reason, category = MCP_CODES.get(code, (None, None))
    if reason is None and isinstance(code, str):
        if code.endswith("_timeout"):
            reason, category = "MCP_TOOL_TIMEOUT", "timeout"
        elif code.endswith(("_unavailable", "_unreachable", "_failed")):
            reason, category = "MCP_PROVIDER_ERROR", "upstream"
    if reason is None:
        return make_error("UNCLASSIFIED_ERROR", source_code=code, severity="recoverable")
    return make_error(reason, category=category, source_code=code, severity="recoverable")


def classify_mcp_events(calls) -> list[dict]:
    """Aggregate server-side tool errors and partial results by (reason, category, code)."""
    groups: dict[tuple, dict] = {}
    for call in calls:
        problems = []
        if call.get("is_error") is True:
            codes = call.get("error_codes") or [None]
            problems = [classify_mcp_code(code) for code in codes]
            if call.get("error_codes") is None:
                problems = [
                    make_error("UNCLASSIFIED_ERROR", source_code=None, severity="recoverable")
                ]
        elif call.get("partial") is True:
            problems = [make_error("MCP_PARTIAL_RESULT", severity="recoverable")]
            problems[0]["source_code"] = "verification_partial"
            codes = call.get("error_codes") or []
            problems += [classify_mcp_code(code) for code in codes]
        for problem in problems:
            key = (problem["reason_code"], problem["category"], problem["source_code"])
            group = groups.setdefault(key, {**problem, "count": 0})
            group["count"] += 1
    return list(groups.values())


def is_actionable(error) -> bool:
    """True for MCP errors that suggest a malfunction rather than a normal "not found"."""
    return error["category"] not in INFORMATIONAL_CATEGORIES


def classify_cleanup(record) -> list[dict]:
    """One CLEANUP_ERROR per failed or unconfirmed cleanup operation, never the task error."""
    errors = []
    for name, operation in (record.get("cleanup_operations") or {}).items():
        if operation.get("status") in {"failed", "unknown"}:
            error = make_error(
                "CLEANUP_ERROR", category=snake(name), source_code=operation.get("diagnostic")
            )
            error["severity"] = "recoverable"
            errors.append(error)
    return errors


def classify_trial(record, mcp_calls=()) -> dict:
    """Primary error, later errors and cleanup errors of one trial.

    Ordering follows pipeline stages (session/executor, MCP calls, turn, interrupt, artifact,
    scorer) because the runner has no shared clock with the MCP server. ``order_basis`` says
    so explicitly. Cleanup errors are listed separately and never replace the task error.
    Informational MCP answers (not found, invalid request) are summarized in ``mcp_errors``
    only; malfunction-type MCP errors join the chain, ahead of the agent's own failure, when the
    trial failed in its outcome (not by interrupt or scorer infrastructure).
    """
    mcp_errors = classify_mcp_events(mcp_calls)
    chain: list[dict] = []
    status = record.get("status")
    failed = status not in {"scored", "completed", "smoke_transport_observed"}
    if record.get("environment_error"):
        chain.append(
            make_error(
                "UNCLASSIFIED_ERROR",
                category="executor_environment",
                source_code="environment_failed",
                severity="fatal",
            )
        )
    error_type = record.get("error_type")
    turn_failure = snake(record.get("turn_failure"))
    if turn_failure and "environment" not in turn_failure:
        chain.append(
            make_error("MODEL_GENERATION_ERROR", source_code=turn_failure, severity="fatal")
        )
    elif error_type == "TimeoutError":
        chain.append(
            make_error("MODEL_TIMEOUT", source_code="elapsed_time_limit", severity="fatal")
        )
    elif error_type == "KeyboardInterrupt" or record.get("interrupted"):
        chain.append(make_error("INTERRUPTED", source_code="keyboard_interrupt", severity="fatal"))
    elif (
        error_type
        and error_type != "CleanupUnconfirmed"
        and not (turn_failure or record.get("environment_error"))
    ):
        # Other failures: a late failure after the turn ended concerns the deliverable.
        reason = "ARTIFACT_INVALID" if record.get("turn_terminal") else "UNCLASSIFIED_ERROR"
        chain.append(make_error(reason, source_code=snake(error_type), severity="fatal"))
    score = record.get("score") or {}
    if score.get("status") and score["status"] != "scored":
        reason, category = SCORER_REASONS.get(
            score.get("reason") or score.get("status"), (None, None)
        )
        if reason is None:
            infrastructure = score["status"] == "scoring_error"
            reason = "SCORER_INFRA_ERROR" if infrastructure else "R_RUNTIME_ERROR"
            category = "infrastructure" if infrastructure else "r_runtime"
        chain.append(
            make_error(
                reason,
                category=category,
                source_code=score.get("reason") or score["status"],
                severity=("recoverable" if reason == "SCORER_UNSUPPORTED_CLAIMS" else "fatal"),
            )
        )
    # A malfunctioning MCP call precedes a failure of the agent's own outcome (it may have
    # starved the agent), but not an interrupt or scorer-infrastructure failure, which have
    # their own cause. Its classification as an MCP/provider error never changes.
    if failed and any(error["reason_code"] in AGENT_OUTCOME for error in chain):
        position = 1 if chain and chain[0]["category"] == "executor_environment" else 0
        chain[position:position] = [
            {**error, "severity": "fatal"}
            for error in mcp_errors
            if error["reason_code"] != "MCP_PARTIAL_RESULT" and is_actionable(error)
        ]
    primary = chain[0] if chain else None
    return {
        "primary_error": primary,
        "subsequent_errors": chain[1:],
        "cleanup_errors": classify_cleanup(record),
        "mcp_errors": mcp_errors,
        "order_basis": "pipeline_stage_order",
    }
