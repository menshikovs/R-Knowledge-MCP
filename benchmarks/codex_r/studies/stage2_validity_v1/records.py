"""Trial record schema and the preregistered missing-data rules for study stage2_validity_v1.

A trial record is the single row analysed by `analysis.py`. It is validated here, so a malformed or
inconsistent record is rejected loudly instead of being silently coerced. Every planned trial must
have exactly one record: a trial that did not produce an outcome still has a record with a
non-scored `outcome_kind` (never a deleted row).

Outcome kinds (fixed before any confirmatory run):
  scored                  the preregistered scorer ran; `score` is passed/total checks in [0, 1].
  candidate_failure       the agent produced no scorable result (timeout, missing artifact, crash of
                          the candidate's own code). Counts as score 0 (intention-to-treat).
  infrastructure_failure  runner, container, network or model-API failure unrelated to the
                          candidate. Missing outcome; retried under the preregistered allowance.
  scoring_error           the scorer itself failed. Missing outcome; never a success.
  not_executed            interrupted or never started. Missing outcome.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("trial_record.schema.json")
OUTCOME_KINDS = (
    "scored",
    "candidate_failure",
    "infrastructure_failure",
    "scoring_error",
    "not_executed",
)
MISSING_KINDS = frozenset({"infrastructure_failure", "scoring_error", "not_executed"})
CORRELATION_STATUSES = (
    "confirmed_protocol_id",
    "ordinal_unconfirmed",
    "unmatched",
    "not_applicable",
)
USAGE_STATUSES = ("observed", "unavailable")


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_record(record: dict) -> list[str]:
    """Problems of one trial record; an empty list means valid. Does not need jsonschema."""
    problems: list[str] = []

    def need(key: str, kinds: tuple[type, ...]) -> object:
        value = record.get(key)
        if (
            key not in record
            or not isinstance(value, kinds)
            or isinstance(value, bool)
            and bool not in kinds
        ):
            problems.append(f"{key}: missing or wrong type")
            return None
        return value

    for key in ("trial_id", "block_id", "task", "arm", "model", "effort", "scorer_version"):
        need(key, (str,))
    need("repetition", (int,))
    need("execution_index", (int,))
    kind = need("outcome_kind", (str,))
    if kind is not None and kind not in OUTCOME_KINDS:
        problems.append(f"outcome_kind: {kind!r} is not one of {OUTCOME_KINDS}")
    if record.get("arm") not in ("A", "B", "C"):
        problems.append("arm: must be A, B or C")

    score = record.get("score")
    if kind == "scored":
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
            problems.append("score: a scored trial needs a number in [0, 1]")
        total, passed = record.get("checks_total"), record.get("checks_passed")
        if not (isinstance(total, int) and isinstance(passed, int) and 0 <= passed <= total > 0):
            problems.append(
                "checks_passed/checks_total: required integers with 0 <= passed <= total"
            )
        elif isinstance(score, (int, float)) and abs(score - passed / total) > 1e-9:
            problems.append("score: differs from checks_passed / checks_total")
    elif kind == "candidate_failure":
        if score != 0:
            problems.append("score: a candidate failure is recorded as 0 (intention-to-treat)")
    elif kind in MISSING_KINDS and score is not None:
        problems.append(f"score: must be null for {kind}")

    mcp = record.get("mcp")
    if not isinstance(mcp, dict):
        problems.append("mcp: missing summary object")
    else:
        for key in ("available", "listed", "attempted", "completed", "errored", "correlation"):
            if key not in mcp:
                problems.append(f"mcp.{key}: missing")
        if mcp.get("correlation") not in CORRELATION_STATUSES:
            problems.append("mcp.correlation: unknown status")
        a, c, e = mcp.get("attempted"), mcp.get("completed"), mcp.get("errored")
        if all(isinstance(x, int) for x in (a, c, e)) and not (0 <= c + e <= a):
            problems.append("mcp: completed + errored must not exceed attempted")
    usage = record.get("usage")
    if not isinstance(usage, dict) or usage.get("status") not in USAGE_STATUSES:
        problems.append("usage.status: must be observed or unavailable")
    elif usage["status"] == "observed" and not all(
        isinstance(usage.get(k), int) for k in ("input_tokens", "output_tokens")
    ):
        problems.append("usage: observed usage needs integer input_tokens and output_tokens")
    if not isinstance(record.get("violations"), list):
        problems.append("violations: required list (empty when none)")
    return problems


def validate_dataset(records: list[dict], planned_trial_ids: list[str]) -> list[str]:
    """Dataset-level checks: one valid record per planned trial, no extras, no duplicates."""
    problems = []
    ids = [r.get("trial_id") for r in records]
    for trial_id in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"duplicate record for {trial_id}")
    missing = sorted(set(planned_trial_ids) - set(ids))
    if missing:
        problems.append(f"{len(missing)} planned trials have no record, e.g. {missing[0]}")
    extra = sorted(set(ids) - set(planned_trial_ids))
    if extra:
        problems.append(f"{len(extra)} records are not in the plan, e.g. {extra[0]}")
    for record in records:
        problems.extend(f"{record.get('trial_id')}: {p}" for p in validate_record(record))
    return problems


def analysis_value(record: dict, exclude_invalidating: bool = True) -> tuple[float | None, str]:
    """(score used by the primary analysis, reason) for one record.

    Preregistered rules: `scored` uses its score; `candidate_failure` is 0; missing kinds and
    trials carrying an invalidating protocol violation are excluded (None) and reported.
    """
    if exclude_invalidating and any(v.get("invalidating") for v in record["violations"]):
        return None, "invalidating_protocol_violation"
    kind = record["outcome_kind"]
    if kind == "scored":
        return float(record["score"]), "scored"
    if kind == "candidate_failure":
        return 0.0, "candidate_failure_as_zero"
    return None, kind


def from_runner_result(
    planned_trial: dict,
    runner_record: dict,
    telemetry_events: list[dict],
    expected: dict,
) -> dict:
    """Convert a `run_simple.py` trial result + telemetry stream into a Stage 2 trial record.

    Any capability or isolation gap in the runner output (for example `run_simple.py`'s default
    plain Docker bridge network without an observing egress proxy, or a two-mode runner lacking
    arm-C instructions) is recorded explicitly as a protocol violation rather than concealed.
    """
    from . import amendment, protocol, telemetry

    arm_id = planned_trial["arm"]
    status = runner_record.get("status")
    raw_score = runner_record.get("score") if isinstance(runner_record.get("score"), dict) else None
    primary_err = (runner_record.get("error_summary") or {}).get("primary_error") or {}

    passed: int | None = None
    total: int | None = None
    score_val: float | None = None

    scorer_result = _canonical_scorer_result(raw_score)
    if status == "scored" and raw_score is not None:
        p_val = raw_score.get("passed")
        t_val = raw_score.get("total")
        # The preregistered outcome is passed/total of the scorer. Multidimensional scorers
        # (knowledge-pilot v2/v2.1) deliberately report no passed/total and no overall score; no
        # aggregate is invented here. Such a result is a missing primary outcome, and the
        # scorer's own fully_correct and dimensions are preserved in `scorer_result`.
        if isinstance(p_val, int) and isinstance(t_val, int) and 0 <= p_val <= t_val > 0:
            kind = "scored"
            passed = p_val
            total = t_val
            score_val = passed / total
        else:
            kind = "scoring_error"
    elif status in ("unsupported_for_automatic_scoring", "scoring_error") or (
        primary_err.get("origin") == "scorer"
        or primary_err.get("source_code") == "unsupported_for_automatic_scoring"
    ):
        kind = "scoring_error"
    elif status == "interrupted" or runner_record.get("interrupted") is True:
        kind = "not_executed"
    elif status == "error" and primary_err.get("origin") == "candidate":
        kind = "candidate_failure"
        score_val = 0.0
    else:
        kind = "infrastructure_failure"

    allowed_tools = runner_record.get("allowed_tools")
    mcp_started = bool(
        runner_record.get("mcp_container_started")
        if "mcp_container_started" in runner_record
        else (
            runner_record.get("mode") == "with-mcp"
            or runner_record.get("mcp_server_audit") is not None
        )
    )
    summary = telemetry.summarize_trace(
        telemetry_events,
        available=bool(mcp_started or allowed_tools),
        proxy_entries=runner_record.get("proxy_entries"),
    )
    audit = runner_record.get("mcp_server_audit") or {}
    mcp_calls_observed = (
        audit.get("call_tool_requests")
        if isinstance(audit.get("call_tool_requests"), int)
        else summary["server_calls"]
    )
    instructions_sha = runner_record.get("agent_instructions_sha256")
    if instructions_sha is None and runner_record.get("instructions") == "standard":
        instructions_sha = protocol.sha256_text(expected["base_instructions"])

    scorer_ver = (
        runner_record.get("scorer_identity")
        or runner_record.get("knowledge_pilot_scorer")
        or runner_record.get("scorer_version")
        or ("hard-v1" if runner_record.get("suite") == "hard-v1" else "legacy")
    )
    evidence = {
        "allowed_tools": allowed_tools,
        "mcp_container_started": mcp_started,
        "mcp_calls_observed": mcp_calls_observed,
        "instructions_sha256": instructions_sha,
        "model": runner_record.get("model", ""),
        "effort": runner_record.get("effort", ""),
        "scorer_version": scorer_ver,
        "network_internal": bool(runner_record.get("network_internal", False)),
        "egress_destinations": runner_record.get("egress_destinations"),
    }
    violation_list = [
        v.as_dict() for v in protocol.capability_violations(arm_id, evidence, expected)
    ]
    protocol_version = protocol.STUDY_VERSION
    if expected.get("protocol_amendment") == amendment.AMENDMENT_ID:
        # Applies only to runs that declare A1; recorded 1.0.0 violations are kept, not removed.
        violation_list = amendment.evaluate(
            violation_list, runner_record.get("capability"), expected.get("capability_policy") or {}
        )
        protocol_version = f"{amendment.PROTOCOL_VERSION}+{amendment.AMENDMENT_ID}"
    elif expected.get("protocol_amendment") is not None:
        raise ValueError(f"unknown protocol amendment {expected['protocol_amendment']!r}")

    raw_usage = runner_record.get("usage") if isinstance(runner_record.get("usage"), dict) else {}
    if (
        runner_record.get("usage_status") == "observed"
        and isinstance(raw_usage.get("input_tokens"), int)
        and isinstance(raw_usage.get("output_tokens"), int)
    ):
        usage = {
            "status": "observed",
            "input_tokens": raw_usage["input_tokens"],
            "output_tokens": raw_usage["output_tokens"],
        }
    else:
        usage = {"status": "unavailable"}

    record = {
        "trial_id": planned_trial["trial_id"],
        "block_id": planned_trial["block_id"],
        "task": planned_trial["task"],
        "arm": arm_id,
        "repetition": planned_trial["repetition"],
        "execution_index": planned_trial["execution_index"],
        "model": str(runner_record.get("model") or ""),
        "effort": str(runner_record.get("effort") or ""),
        "scorer_version": str(scorer_ver),
        "outcome_kind": kind,
        "score": score_val,
        "checks_passed": passed,
        "checks_total": total,
        "mcp": {k: v for k, v in summary.items() if k != "links"},
        "usage": usage,
        "violations": violation_list,
        "synthetic": False,
        "protocol_version": protocol_version,
    }
    if scorer_result is not None:
        record["scorer_result"] = scorer_result
    # Tool availability (configuration) and observed tool use, kept apart; optional evidence.
    if isinstance(runner_record.get("agent_tools"), dict):
        record["agent_tools"] = runner_record["agent_tools"]
    if isinstance(runner_record.get("capability"), dict):
        record["capability"] = runner_record["capability"]
    return record


def _canonical_scorer_result(raw_score: dict | None) -> dict | None:
    """The scorer's own verdict, unaggregated: status, checks, fully_correct, dimension states."""
    if raw_score is None:
        return None
    dims = raw_score.get("dimensions")
    p_val, t_val = raw_score.get("passed"), raw_score.get("total")
    defined = isinstance(p_val, int) and isinstance(t_val, int) and t_val > 0
    return {
        "status": raw_score.get("status"),
        "scorer_version": raw_score.get("scorer_version"),
        "passed": p_val,
        "total": t_val,
        "fully_correct": raw_score.get("fully_correct"),
        "primary_metric": ("passed_over_total" if defined else "undefined_by_canonical_scorer"),
        "dimensions": (
            {
                name: {k: v.get(k) for k in ("status", "passed", "total") if k in v}
                for name, v in dims.items()
                if isinstance(v, dict)
            }
            if isinstance(dims, dict)
            else None
        ),
    }
