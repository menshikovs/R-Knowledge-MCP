"""Stage 3A: run stage2_validity_v1 trials through the existing benchmark runner.

``make_legacy_trial_executor`` returns a ``runner.TrialAttemptExecutor``. Each attempt is exactly
one ``run_simple.run_trial`` call, so the model API path (``SimpleClient`` over the Agents API),
credential handling, Docker executor, MCP container, artifact sealing, R scorers, telemetry and
cleanup are the legacy runner's own. This module only

* maps an arm to the runner's inputs (A: ``without-mcp``; B: ``with-mcp``; C: ``with-mcp`` plus
  the preregistered encouragement sentence), fixing one MCP surface for every task;
* points ``run_trial`` at a fresh per-attempt output directory owned by the Stage 2 ledger;
* translates the legacy ``result.json`` and the trial's schema-1.2 telemetry into a Stage 2 runner
  record (``records.from_runner_result`` does the rest), keeping the canonical scorer result.

Isolation is the legacy runner's: a plain Docker bridge network and instruction-level rules. Every
trial records the 1.0.0 ``egress_not_restricted`` and ``egress_unverified`` violations. Runs are
evaluated under preregistration amendment A1 (``amendment.py``): those codes stay recorded but are
superseded, and per-trial capability equivalence is checked against ``capability_policy``.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import amendment, manifest, protocol, runner, spend_control

# Present on every trial run through the legacy bridge network (no observing egress proxy).
STRUCTURAL_VIOLATIONS = ("egress_not_restricted", "egress_unverified")
WEB_ACCESS_ITEM_TYPES = frozenset({"web_search_call", "web_fetch_call", "browser_call"})
DEFAULT_MCP_IMAGE = "cran-knowledge-mcp:shiny-quarto"
# What run_trial actually uses in every arm: a fresh per-trial Docker bridge network and the
# Agents API with a self-hosted executor (the same model transport for A, B and C).
LEGACY_NETWORK = "docker_bridge_per_trial"
MODEL_TRANSPORT = "agents_api_self_hosted_executor"
# Heuristic markers of the benchmark's scorer/reference material in agent tool items.
REFERENCE_MARKERS = (
    "menshikovs/r-knowledge-mcp",
    "benchmarks/codex_r/oracle",
    "benchmarks/codex_r/hard/verifier",
    "stage3b_expansion/verifier",
    "knowledge_pilot/verifier",
    "scorer_evidence",
)
NON_MCP_ITEM_TYPES = frozenset(
    {"command_execution", "web_search_call", "web_fetch_call", "browser_call", "browser_action"}
)
ARM_INVOCATION = {  # arm -> (run_simple mode, instruction variant)
    "A": ("without-mcp", "standard"),
    "B": ("with-mcp", "standard"),
    "C": ("with-mcp", "mcp-encouraged"),
}


@dataclass(frozen=True)
class StudyConfiguration:
    id: str
    question: str
    agent_tools: tuple[str, ...]  # configured non-MCP capabilities, identical in every arm
    web_access: bool
    supported: bool
    unsupported_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "agent_tools": list(self.agent_tools),
            "web_access": self.web_access,
            "supported": self.supported,
            "unsupported_reason": self.unsupported_reason,
        }


STUDIES = {
    "study1": StudyConfiguration(
        id="study1_mcp_vs_model_knowledge",
        question="Does R-Knowledge-MCP add package/API knowledge beyond the model and local R?",
        agent_tools=("command_execution",),
        web_access=False,
        supported=True,
    ),
    "study2": StudyConfiguration(
        id="study2_mcp_with_standard_tools",
        question="What does R-Knowledge-MCP add next to standard agent tools including web search?",
        agent_tools=("command_execution", "web_search"),
        web_access=True,
        supported=False,
        unsupported_reason=(
            "The legacy runner's Agents API session declares no web-search tool, its shared "
            "instructions forbid browsing, and no verified API contract for an equal web-search "
            "tool exists in this repository. Equal web access in every arm cannot be ensured."
        ),
    ),
}


class StudyUnsupported(RuntimeError):
    """The study configuration cannot be run with comparable conditions."""


class LegacyRunnerUnavailable(RuntimeError):
    """The legacy runner's preconditions (Linux, Docker, credentials, images) are not met."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("legacy runner unavailable: " + "; ".join(reasons))


@dataclass(frozen=True)
class LegacyExecutionContext:
    study: StudyConfiguration
    effort: str
    timeout_seconds: int
    images: dict[str, str]  # immutable image ids: executor, scorer, mcp
    runtime_versions: dict[str, Any] | None = None
    keys: tuple[str, str] = field(default=("", ""), repr=False)
    # Fail-safe default: only preflight() for a real run sets False.
    synthetic: bool = True


def study_configuration(name: str) -> StudyConfiguration:
    study = STUDIES[name]
    if not study.supported:
        raise StudyUnsupported(f"{study.id}: {study.unsupported_reason}")
    return study


def preflight(
    tasks: list[str],
    *,
    study: StudyConfiguration,
    effort: str,
    timeout_seconds: int,
    need_mcp: bool,
    executor_image: str | None = None,
    scorer_image: str | None = None,
    mcp_image: str = DEFAULT_MCP_IMAGE,
) -> LegacyExecutionContext:
    """The legacy runner's own startup checks, before any session can be created.

    Credential values are read here (only presence is reported) and never logged.
    """
    import os

    from benchmarks.codex_r import knowledge_pilot, run_simple

    if not study.supported:
        raise StudyUnsupported(f"{study.id}: {study.unsupported_reason}")
    reasons = []
    if sys.platform != "linux":
        reasons.append("run_simple runs only on Linux / Ubuntu WSL2 (it uses SIGALRM)")
    if not shutil.which("docker"):
        reasons.append("Docker CLI not found in PATH")
    keys = tuple(os.environ.get(name, "") for name in run_simple.KEY_NAMES)
    missing = [n for n, v in zip(run_simple.KEY_NAMES, keys, strict=True) if not v.strip()]
    if missing:
        reasons.append("missing environment variables: " + ", ".join(missing))
    if reasons:
        raise LegacyRunnerUnavailable(reasons)
    refs = run_simple.default_image_refs(tasks)
    try:
        images = {
            "executor": run_simple.image_id(executor_image or refs["executor"]),
            "scorer": run_simple.image_id(scorer_image or refs["scorer"]),
        }
        if need_mcp:
            images["mcp"] = run_simple.image_id(mcp_image)
        runtime_versions = {
            "scorer": knowledge_pilot.verify_scorer_image(images["scorer"], tasks),
            "executor": knowledge_pilot.verify_runtime_image(
                images["executor"], tasks, role="executor"
            ),
        }
    except (RuntimeError, ValueError, OSError) as exc:
        raise LegacyRunnerUnavailable([str(exc)[:500]]) from exc
    return LegacyExecutionContext(
        study=study,
        effort=effort,
        timeout_seconds=timeout_seconds,
        images=images,
        runtime_versions=runtime_versions,
        keys=keys,  # type: ignore[arg-type]
        synthetic=False,
    )


def capability_policy(ctx: LegacyExecutionContext) -> dict[str, Any]:
    """The capabilities every arm of the run must have (amendment A1), MCP excepted."""
    return {
        "study_configuration": ctx.study.id,
        # Non-MCP tool entries in the session request (the executor runtime supplies its shell).
        "non_mcp_tools": [],
        "executor_image": ctx.images["executor"],
        "network": LEGACY_NETWORK,
        "model_transport": MODEL_TRANSPORT,
        "web_access_policy": "equal_web_search" if ctx.study.web_access else "none",
    }


def study_execution_config(
    ctx: LegacyExecutionContext, *, study_id: str = protocol.STUDY_ID, stage: str | None = None
) -> runner.StudyExecutionConfig:
    from benchmarks.codex_r import run_simple

    return runner.StudyExecutionConfig(
        study_id=study_id,
        stage=stage or f"{ctx.study.id}_legacy_runner",
        model=run_simple.MODEL,
        effort=ctx.effort,
        timeout_seconds=ctx.timeout_seconds,
        max_infra_retries=1,
        stop_on_invalidating_violation=True,
        synthetic=ctx.synthetic,
        protocol_amendment=amendment.AMENDMENT_ID,
        capability_policy=capability_policy(ctx),
    )


def scorer_isolation(task: str) -> dict[str, Any]:
    """Whether the task's scorer/reference files are reachable from the candidate's mounts.

    run_simple mounts only the fresh trial workspace into the executor and only ``src`` (read
    only) into the MCP server, so a file is exposed if it lies under ``src``.
    """
    from benchmarks.codex_r.runner import bench

    meta = runner._task_and_scorer_meta(task)
    from . import scorer_bindings

    binding = scorer_bindings.bind(task, meta["catalogue_scorer_label"])
    candidates = list(binding.files) + manifest.task_files(task)
    src = (bench.REPO / "src").resolve()
    exposed = sorted(
        str(path.relative_to(manifest.ROOT)).replace("\\", "/")
        for path in candidates
        if path.resolve().is_relative_to(src)
    )
    return {
        "candidate_mounts": ["fresh trial workspace -> /candidate"],
        "mcp_mounts": ["src -> /evaluated (read-only)"],
        "checked_files": len(candidates),
        "exposed_files": exposed,
    }


def reference_access_hits(output: Path, trial_id: str) -> list[str]:
    """Heuristic: markers of scorer/reference locations inside non-MCP agent tool items."""
    path = Path(output) / trial_id / "events.json"
    try:
        events = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    hits = set()
    for event in events if isinstance(events, list) else []:
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict) or item.get("type") not in NON_MCP_ITEM_TYPES:
            continue
        text = json.dumps(item).casefold()
        hits.update(marker for marker in REFERENCE_MARKERS if marker in text)
    return sorted(hits)


def read_trial_telemetry(output: Path, trial_id: str) -> list[dict[str, Any]]:
    """The trial's canonical schema-1.2 events from the legacy run's telemetry.jsonl."""
    path = Path(output) / "telemetry.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("trial_id") == trial_id:
            events.append(event)
    return events


def _primary_error(legacy: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    """Legacy outcome -> (Stage 2 runner status, primary error). Never guesses a score."""
    status = legacy.get("status")
    score = legacy.get("score") if isinstance(legacy.get("score"), dict) else {}

    def err(origin: str, category: str, code: str) -> dict[str, str]:
        return {"origin": origin, "category": category, "source_code": code}

    if status == "scored":
        return "scored", None
    if status == "unsupported_for_automatic_scoring":
        return status, err("scorer", "scorer", "unsupported_for_automatic_scoring")
    if status == "scoring_error":
        return "error", err("scorer", "scorer", str(score.get("reason") or "scoring_error"))
    if status == "candidate_timeout":
        return "error", err("candidate", "timeout", "scorer_deadline")
    if status == "candidate_error":
        return "error", err("candidate", "artifact", str(score.get("reason") or status))
    if status == "error" and legacy.get("error_type") == "TimeoutError":
        # The arm's elapsed-time budget ran out: an outcome of the evaluated condition.
        return "error", err("candidate", "timeout", "agent_elapsed_time_limit")
    if status == "cleanup_error":
        return "error", err("runner", "docker", "cleanup_incomplete")
    code = legacy.get("turn_failure") or legacy.get("error_type") or str(status)
    return "error", err("runner", "infrastructure", str(code))


def _agent_tools(
    study: StudyConfiguration, arm: str, events: list[dict[str, Any]]
) -> dict[str, Any]:
    started = [e for e in events if e.get("event_type") == "agent.tool.started"]
    used = Counter(str(e.get("tool")) for e in started)
    web = sum(1 for e in started if e.get("tool") in WEB_ACCESS_ITEM_TYPES)
    findings = []
    if web and not study.web_access:
        findings.append(f"{web} web-access tool call(s) observed although none was configured")
    return {
        "study_configuration": study.id,
        "available": {
            "agent_tools": list(study.agent_tools),
            "web_access": study.web_access,
            "r_knowledge_mcp": protocol.ARMS[arm].mcp_available,
        },
        "used": dict(sorted(used.items())),
        "web_access_calls": web,
        "findings": findings,
    }


def capability_record(
    spec: dict[str, Any],
    legacy: dict[str, Any],
    study: StudyConfiguration,
    tools: dict[str, Any],
    hits: list[str],
) -> dict[str, Any]:
    """The capability configuration actually delivered in this trial, and observed deviations."""
    session_types = legacy.get("session_tool_types")
    return {
        "protocol_amendment": amendment.AMENDMENT_ID,
        "study_configuration": study.id,
        "started_at_utc": legacy.get("started_at"),
        "non_mcp_tools": (
            None if session_types is None else [t for t in session_types if t != "mcp"]
        ),
        "executor_image": (legacy.get("images") or {}).get("executor"),
        "network": LEGACY_NETWORK,
        "model_transport": MODEL_TRANSPORT,
        "web_access_policy": "equal_web_search" if study.web_access else "none",
        "mcp_tools": legacy.get("allowed_tools"),
        "instructions_sha256": legacy.get("session_instructions_sha256"),
        "scorer_isolation": scorer_isolation(spec["task"]),
        "observed": {
            "agent_tools": tools["used"],
            "web_access_calls": tools["web_access_calls"],
            "reference_access_hits": hits,
        },
    }


def translate(
    spec: dict[str, Any],
    legacy: dict[str, Any],
    measured: dict[str, str],
    study: StudyConfiguration,
    events: list[dict[str, Any]],
    reference_hits: list[str] | None = None,
) -> dict[str, Any]:
    """Legacy run_simple record -> Stage 2 runner record (what records.from_runner_result reads)."""
    status, primary = _primary_error(legacy)
    with_mcp = spec["mcp_container_started"]
    tools = _agent_tools(study, spec["arm"], events)
    return {
        "trial_id": spec["trial_id"],
        "task": spec["task"],
        "mode": legacy.get("mode"),
        "repetition": spec["repetition"],
        "model": legacy.get("model"),
        "effort": legacy.get("effort"),
        "scorer_identity": measured["scorer_version"],
        "task_sha256": measured["task_sha256"],
        "scorer_sha256": measured["scorer_sha256"],
        "status": status,
        "score": legacy.get("score") if isinstance(legacy.get("score"), dict) else None,
        "error_summary": {"primary_error": primary},
        "allowed_tools": legacy.get("allowed_tools"),
        # run_trial starts the MCP container before it creates the session.
        "mcp_container_started": bool(with_mcp and legacy.get("session_creation_attempted")),
        "mcp_server_audit": legacy.get("mcp_server_audit"),
        "agent_instructions_sha256": legacy.get("session_instructions_sha256"),
        # The legacy runner uses a plain bridge network without an observing proxy.
        "network_internal": False,
        "egress_destinations": None,
        "proxy_entries": None,
        "usage_status": legacy.get("usage_status", "unavailable"),
        "usage": legacy.get("usage"),
        "agent_tools": tools,
        "capability": capability_record(spec, legacy, study, tools, reference_hits or []),
        "legacy_result": {
            key: legacy.get(key)
            for key in (
                "run_id",
                "status",
                "error",
                "error_type",
                "turn_failure",
                "cost",
                "cost_status",
                "session_deleted",
                "cleanup_completed",
                "agent_seconds",
                "duration_seconds",
                "mcp_toolset",
                "mcp_usage",
            )
        },
    }


def make_legacy_trial_executor(
    ctx: LegacyExecutionContext, *, run_trial: Any = None
) -> runner.TrialAttemptExecutor:
    """One Stage 2 attempt = one ``run_simple.run_trial`` in the attempt's own directory."""
    from benchmarks.codex_r import run_simple

    if not ctx.study.supported:
        raise StudyUnsupported(f"{ctx.study.id}: {ctx.study.unsupported_reason}")
    run = run_trial or run_simple.run_trial

    def _execute(spec: dict[str, Any], attempt_index: int, workspace_dir: Path) -> dict[str, Any]:
        mode, variant = ARM_INVOCATION[spec["arm"]]
        measured = runner._task_and_scorer_meta(spec["task"])
        if (measured["task_sha256"], measured["scorer_sha256"]) != (
            spec["task_sha256"],
            spec["scorer_sha256"],
        ):
            # Refuse before any session: the files changed since the plan was pinned.
            record = {
                "trial_id": spec["trial_id"],
                "task": spec["task"],
                "model": spec["model"],
                "effort": spec["effort"],
                "scorer_identity": measured["scorer_version"],
                "task_sha256": measured["task_sha256"],
                "scorer_sha256": measured["scorer_sha256"],
                "status": "error",
                "error_summary": {
                    "primary_error": {
                        "origin": "runner",
                        "category": "integrity",
                        "source_code": "task_or_scorer_hash_mismatch",
                    }
                },
                "allowed_tools": spec["allowed_tools"],
                "mcp_container_started": False,
                "agent_instructions_sha256": None,
                "network_internal": False,
                "egress_destinations": None,
                "usage_status": "unavailable",
            }
            return {"runner_record": record, "telemetry_events": []}
        if spec["model"] != run_simple.MODEL:
            raise ValueError(f"plan model {spec['model']!r} is not the runner's {run_simple.MODEL}")
        args = SimpleNamespace(
            effort=spec["effort"],
            timeout=ctx.timeout_seconds,
            instructions=variant,
            experiment=None,
            mcp_discovery=None,
            function_discovery="enabled",
            # Only knowledge-pilot tasks read this; others keep run_simple's default.
            knowledge_pilot_scorer=(
                measured["scorer_version"]
                if measured["scorer_version"] in run_simple.VERSIONED_KNOWLEDGE_PILOT_SCORERS
                else "legacy"
            ),
            run_id=f"{spec['trial_id']}__att{attempt_index:02d}",
            runtime_versions=ctx.runtime_versions,
            mcp_tool_override=(
                ("consolidated", tuple(spec["allowed_tools"]))
                if spec["mcp_container_started"]
                else None
            ),
        )
        legacy = run(
            args,
            spec["task"],
            mode,
            spec["repetition"],
            Path(workspace_dir),
            ctx.keys,
            ctx.images,
            planned_trial_id=spec["trial_id"],
        )
        if legacy.get("interrupted"):
            # The ledger records the interruption; resume starts a fresh attempt.
            raise runner.InterruptionSimulated(f"run_trial interrupted: {spec['trial_id']}")
        events = read_trial_telemetry(Path(workspace_dir), spec["trial_id"])
        hits = reference_access_hits(Path(workspace_dir), spec["trial_id"])
        record = translate(spec, legacy, measured, ctx.study, events, hits)
        mcp_events = [e for e in events if str(e.get("event_type", "")).startswith("mcp.")]
        return {"runner_record": record, "telemetry_events": mcp_events}

    return _execute


def pin_plan_identities(plan: dict[str, Any]) -> dict[str, Any]:
    """Copy of a design plan with each trial's task/scorer digests pinned (plan digest renewed).

    The executor re-measures both before every attempt and refuses to start on a difference.
    """
    from . import design

    pinned = json.loads(json.dumps(plan))
    meta: dict[str, dict[str, str]] = {}
    for trial in pinned["trials"]:
        task = trial["task"]
        meta.setdefault(task, runner._task_and_scorer_meta(task))
        trial["task_sha256"] = meta[task]["task_sha256"]
        trial["scorer_sha256"] = meta[task]["scorer_sha256"]
    pinned["plan_sha256"] = design.plan_digest(pinned)
    return pinned


def plan_identity_problems(plan: dict[str, Any]) -> list[str]:
    """Trials whose pinned digests are missing or differ from the files as they are now."""
    problems = []
    meta: dict[str, dict[str, str]] = {}
    for trial in plan["trials"]:
        task = trial["task"]
        if not trial.get("task_sha256") or not trial.get("scorer_sha256"):
            problems.append(f"{trial['trial_id']}: task/scorer digests are not pinned")
            continue
        meta.setdefault(task, runner._task_and_scorer_meta(task))
        for key in ("task_sha256", "scorer_sha256"):
            if trial[key] != meta[task][key]:
                problems.append(f"{trial['trial_id']}: {key} differs from the current files")
    return problems


def bind_run_directory(run_dir: Path, binding: dict[str, Any]) -> None:
    """Pin study configuration and spend ceiling to the run directory; resume must match."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "study_execution.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != binding:
            raise ValueError("Resume rejected: study configuration or spend ceiling differs")
    else:
        path.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def execute_study(
    plan: dict[str, Any],
    run_dir: Path,
    ctx: LegacyExecutionContext,
    *,
    spend_ceiling: spend_control.SpendCeiling | None,
    executor: runner.TrialAttemptExecutor | None = None,
) -> dict[str, Any]:
    """Run (or resume) an A/B/C plan through the legacy runner under a spend ceiling.

    A real run (``ctx.synthetic`` false) requires a valid ceiling; mocked-model runs may omit it.
    """
    if not ctx.study.supported:
        raise StudyUnsupported(f"{ctx.study.id}: {ctx.study.unsupported_reason}")
    if spend_ceiling is None and not ctx.synthetic:
        raise RuntimeError("a real-model study run requires an explicit spend ceiling")
    problems = plan_identity_problems(plan)
    if problems:
        raise ValueError(f"plan identities are not pinned or have drifted: {problems[:5]}")
    guard = spend_control.SpendGuard(spend_ceiling) if spend_ceiling else None
    bind_run_directory(
        Path(run_dir),
        {
            "study_configuration": ctx.study.to_dict(),
            "executor": "run_simple.run_trial",
            "spend_ceiling": spend_ceiling.to_dict() if spend_ceiling else None,
            "synthetic": ctx.synthetic,
            "protocol_amendment": amendment.AMENDMENT_ID,
            "capability_policy": capability_policy(ctx),
        },
    )
    cfg = study_execution_config(ctx)
    result = runner.execute_study_plan(
        plan,
        cfg,
        Path(run_dir),
        executor or make_legacy_trial_executor(ctx),
        attempt_controller=guard,
    )
    result["spend"] = guard.summary() if guard else None
    result["study_configuration"] = ctx.study.id
    return result
