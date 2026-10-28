"""Stage 2.6 opt-in live A/B/C trial executor over real Docker topologies and a mock model.

`make_docker_trial_executor` returns a ``TrialAttemptExecutor`` for
``runner.execute_study_plan``: the ledger, retry policy, ``not_executed`` materialisation and
Stage 2 record schema are reused unchanged. Per attempt it creates a fresh workspace, topology,
mock model token and containers (nothing is shared across trials or arms), proves isolation
(structural inspection + behavioural canary) *before* running the workload, scores the produced
artifact on the host with the frozen scorer, projects telemetry, and verifies that every Docker
resource is gone again.

Scope, stated plainly:

* The "model" is a local mock reached through the allow-listing gateway; usage numbers are
  synthetic and every record produced here is labelled synthetic by the study config.
* The workload is a deterministic mock agent, not the Codex Managed Agents executor. Wiring the
  real executor into this topology is the remaining pilot blocker (see the readiness report).
* Only tasks the frozen host JSON scorers accept (``HOST_SCORABLE``) are scored here; R verifier
  tasks need the scorer container and are recorded as an infrastructure failure before any
  container is created. None of the Stage 2.7 calibration candidates is host-scorable.
* ``benchmarks/codex_r/run_simple.py`` is untouched; this module never changes legacy behaviour.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.codex_r import knowledge_pilot, knowledge_pilot_v2, knowledge_pilot_v21

from . import live_network, manifest, protocol, runner

CLIENT, SERVER = "agent_stream", "mcp_server"
# Local, network-free MCP tool used by the mock agent so a successful call needs no upstream.
MOCK_TOOL_CALL = {
    "name": "validate_r_prompt",
    "arguments": {"prompt_text": "Write R code that reads a CSV file and prints a summary."},
}


# Mirrors the task guards inside the frozen scorers (knowledge_pilot_v2.contract_path and
# knowledge_pilot_v21.score); a test keeps the two in step.
HOST_SCORABLE: dict[str, frozenset[str]] = {
    "knowledge-pilot-v2": frozenset({"D01", "D02", "D03", "E01", "E04", "E05"}),
    "knowledge-pilot-v2.1": frozenset({"D01", "D03"}),
}


def host_scorable(task: str, scorer_version: str) -> bool:
    return task in HOST_SCORABLE.get(scorer_version, frozenset())


class TrialScoringUnavailable(RuntimeError):
    """The task has no host-side JSON scorer / mock answer in this live adapter."""


class FrozenEvidenceError(RuntimeError):
    """Frozen benchmark evidence differs from its recorded digests; refuse to run."""


@dataclass(frozen=True)
class LiveExecutorSettings:
    run_label: str = "stage26"
    python_image: str = live_network.PYTHON_IMAGE
    mcp_image: str = live_network.MCP_IMAGE
    workload_timeout_seconds: float = 120.0
    # Deterministic "voluntary" behaviour of the mock agent in Arm B (Arm C always calls).
    arm_b_call_modulus: int = 3


def mock_gold_answer(task: str) -> dict[str, Any]:
    """Deterministic gold answers for the JSON tasks (identical for every arm: no effect)."""
    r_ver = knowledge_pilot.manifest()["environment"]["r"]
    if task == "D01":
        return {
            "r_version": r_ver,
            "rationale": (
                "termr 1.0.1 provides reactive terminal UI components, headless app test "
                "support, and stable return values while requiring a real terminal."
            ),
            "recommendations": [
                {
                    "package": "termr",
                    "version": "1.0.1",
                    "source_url": "https://cran.r-project.org/package=termr",
                    "documentation_url": (
                        "https://stat.ethz.ch/CRAN/web/packages/termr/refman/termr.html"
                    ),
                    "feature_ids": [
                        "reactive_terminal_ui",
                        "headless_app_tests",
                        "stable_return_values",
                    ],
                    "caveat_ids": ["real_terminal_required", "some_apis_experimental"],
                }
            ],
        }
    if task == "D02":
        return {
            "r_version": r_ver,
            "rationale": (
                "httptest2 1.2.2 provides recorded HTTP fixtures and first-class httr2 "
                "integration while being specific to httr2."
            ),
            "recommendations": [
                {
                    "package": "httptest2",
                    "version": "1.2.2",
                    "source_url": "https://cran.r-project.org/package=httptest2",
                    "documentation_url": (
                        "https://cran.r-project.org/web/packages/httptest2/httptest2.pdf"
                    ),
                    "feature_ids": ["recorded_fixtures", "httr2_support"],
                    "caveat_ids": ["httr2_specific"],
                }
            ],
        }
    if task == "D03":
        return {
            "r_version": r_ver,
            "rationale": (
                "validate 1.1.7 supports declarative rules, cross-record validation rules, "
                "and row-level failure reports in a lightweight rule engine."
            ),
            "recommendations": [
                {
                    "package": "validate",
                    "version": "1.1.7",
                    "source_url": "https://cran.r-project.org/package=validate",
                    "documentation_url": (
                        "https://cran.r-project.org/web/packages/validate/validate.pdf"
                    ),
                    "feature_ids": [
                        "declarative_rules",
                        "cross_record_rules",
                        "row_level_failure_reports",
                    ],
                    "caveat_ids": ["lightweight_rule_engine"],
                }
            ],
        }
    raise TrialScoringUnavailable(f"no mock answer / JSON scorer for task {task}")


def score_workspace(task: str, scorer_version: str, workspace: Path) -> dict[str, Any]:
    """Run the frozen JSON scorer on the host over the produced artifact directory."""
    if not host_scorable(task, scorer_version):
        raise TrialScoringUnavailable(f"{task} / {scorer_version} needs the scorer container")
    if scorer_version == "knowledge-pilot-v2.1":
        return knowledge_pilot_v21.score(task, workspace)
    if scorer_version == "knowledge-pilot-v2":
        return knowledge_pilot_v2.score(task, workspace)
    raise TrialScoringUnavailable(f"scorer {scorer_version} needs the scorer container")


def _error_record(
    spec: dict[str, Any],
    *,
    origin: str,
    category: str,
    code: str,
    live: dict[str, Any],
    network_internal: bool = False,
    egress: list[str] | None = None,
    scored: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = "error"
    if scored is not None and scored.get("status") == "unsupported_for_automatic_scoring":
        status = "unsupported_for_automatic_scoring"
    return {
        "trial_id": spec["trial_id"],
        "task": spec["task"],
        "mode": spec["mode"],
        "repetition": spec["repetition"],
        "model": spec["model"],
        "effort": spec["effort"],
        "scorer_identity": spec["scorer_version"],
        "task_sha256": live.get("task_sha256", spec["task_sha256"]),
        "scorer_sha256": live.get("scorer_sha256", spec["scorer_sha256"]),
        "status": status,
        "score": None,
        "error_summary": {
            "primary_error": {"origin": origin, "category": category, "source_code": code}
        },
        "allowed_tools": live.get("observed_tools"),
        "mcp_container_started": bool(live.get("mcp_container_started", False)),
        "agent_instructions_sha256": live.get("agent_instructions_sha256"),
        "network_internal": network_internal,
        "egress_destinations": egress,
        "proxy_entries": None,
        "usage_status": "unavailable",
        "live_evidence": live,
    }


def _events(
    report: dict[str, Any] | None, mcp_telemetry: list[dict[str, Any]], listed: bool
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if listed:
        events.append(
            {
                "event_type": "mcp.discovery.completed",
                "source": CLIENT,
                "list_tools_requests": 1,
            }
        )
    for call in ((report or {}).get("mcp") or {}).get("calls", []):
        base = {"source": CLIENT, "call_id": call["call_id"], "tool": call["tool"]}
        events.append({"event_type": "mcp.tool.started", **base})
        events.append({"event_type": "mcp.tool.completed", "is_error": call["is_error"], **base})
    for item in mcp_telemetry:
        events.append(
            {
                "event_type": "mcp.tool.completed",
                "source": SERVER,
                "call_id": f"srv-{item.get('protocol_call_id')}",
                "tool": item.get("tool_name"),
                "is_error": item.get("status") == "error",
                "response_bytes": item.get("response_bytes"),
                "useful_bytes": item.get("useful_bytes"),
                "duration_ms": item.get("duration_ms"),
                "protocol_call_id": item.get("protocol_call_id"),
            }
        )
    return events


def _egress(
    gateway_events: list[dict[str, Any]], canary: dict[str, Any], report: dict[str, Any] | None
) -> list[str] | None:
    """Logical destinations actually reached; ``None`` when no gateway log could be read."""
    if not gateway_events:
        return None
    reached: set[str] = set()
    for event in gateway_events:
        if event.get("event") == "connect" and event.get("result") == "allowed":
            authority = event.get("authority")
            reached.add(
                protocol.MODEL_ENDPOINT if authority == live_network.MODEL_AUTHORITY else authority
            )
    by_id = {p["id"]: p for p in canary.get("probes", [])}
    if by_id.get("mcp_direct", {}).get("outcome") == "allowed" or ((report or {}).get("mcp") or {}):
        reached.add(protocol.MCP_ENDPOINT)
    reached.update(f"breach:{pid}" for pid in canary.get("breaches", []))
    return sorted(reached)


def make_docker_trial_executor(
    settings: LiveExecutorSettings | None = None,
    *,
    interrupt_before_workload: set[tuple[str, int]] | None = None,
    topology_faults: dict[tuple[str, int], str] | None = None,
    on_topology: Callable[[live_network.TrialTopology], None] | None = None,
    answer_provider: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
) -> runner.TrialAttemptExecutor:
    """Build the live executor. The keyword hooks exist for fault-injection tests only.

    ``answer_provider`` returns the mock agent's answer for a spec (``None``: the agent writes no
    artifact). By default only the deterministic D01-D03 gold answers exist; any other task is an
    infrastructure failure rather than an invented candidate outcome.
    """
    cfg = settings or LiveExecutorSettings()
    interrupts = interrupt_before_workload or set()
    faults = topology_faults or {}

    def _execute(spec: dict[str, Any], attempt_index: int, workspace_dir: Path) -> dict[str, Any]:
        tid = spec["trial_id"]
        live: dict[str, Any] = {
            "attempt_index": attempt_index,
            "arm": spec["arm"],
            "session_isolation_id": spec["session_isolation_id"],
            "mock_model": True,
        }
        # Hashes are re-measured at execution time, not trusted from the plan.
        measured = runner._task_and_scorer_meta(spec["task"])
        live.update(task_sha256=measured["task_sha256"], scorer_sha256=measured["scorer_sha256"])
        if measured["task_sha256"] != spec["task_sha256"] or (
            measured["scorer_sha256"] != spec["scorer_sha256"]
        ):
            return {
                "runner_record": _error_record(
                    spec,
                    origin="runner",
                    category="integrity",
                    code="task_or_scorer_hash_mismatch",
                    live=live,
                ),
                "telemetry_events": [],
            }
        if any(workspace_dir.iterdir()):
            return {
                "runner_record": _error_record(
                    spec,
                    origin="runner",
                    category="workspace",
                    code="workspace_not_fresh",
                    live=live,
                ),
                "telemetry_events": [],
            }
        # Decided before any container exists: an unscorable trial must not consume resources.
        if not host_scorable(spec["task"], spec["scorer_version"]):
            return {
                "runner_record": _error_record(
                    spec,
                    origin="runner",
                    category="scorer",
                    code="scorer_container_required",
                    live=live,
                ),
                "telemetry_events": [],
            }
        try:
            answer = (answer_provider or (lambda s: mock_gold_answer(s["task"])))(spec)
        except TrialScoringUnavailable:
            return {
                "runner_record": _error_record(
                    spec,
                    origin="runner",
                    category="workload",
                    code="mock_answer_unavailable",
                    live=live,
                ),
                "telemetry_events": [],
            }

        topo = live_network.TrialTopology(
            spec["arm"],
            trial_id=tid,
            run_label=cfg.run_label,
            python_image=cfg.python_image,
            mcp_image=cfg.mcp_image,
            fault=faults.get((tid, attempt_index)),
        )
        leftovers: dict[str, list[str]] = {"containers": [], "networks": []}
        runner_record: dict[str, Any] | None = None
        events: list[dict[str, Any]] = []
        began = time.monotonic()
        try:
            try:
                topo.start()
                if on_topology is not None:
                    on_topology(topo)
                live.update(
                    topology_id=topo.topology_id,
                    mcp_container_started=topo.has_mcp,
                    setup_seconds=round(time.monotonic() - began, 3),
                )
                enforcement = topo.verify_enforcement()
                canary = topo.run_canary()
                logs = topo.collect_logs()
                live.update(
                    enforcement=enforcement,
                    canary={k: v for k, v in canary.items() if k != "report"},
                )
                egress = _egress(logs["gateway_events"], canary, None)
                if not enforcement["ok"] or not canary["ok"]:
                    # Fail closed: the workload never starts without proven isolation.
                    runner_record = _error_record(
                        spec,
                        origin="runner",
                        category="isolation",
                        code="isolation_enforcement_failed",
                        live=live,
                        network_internal=bool(enforcement["internal_flag"])
                        and not canary["breaches"],
                        egress=egress,
                    )
                else:
                    if (tid, attempt_index) in interrupts:
                        raise runner.InterruptionSimulated(f"interrupted {tid} before workload")
                    call = bool(
                        spec["arm"] == "C"
                        or (spec["arm"] == "B" and spec["trial_seed"] % cfg.arm_b_call_modulus != 0)
                    )
                    started = time.monotonic()
                    result = topo.run_workload(
                        {
                            "instructions": spec["instructions"],
                            "mcp_expected": spec["mcp_container_started"],
                            "call_tool": call,
                            "tool_call": MOCK_TOOL_CALL,
                            "answer": answer,
                        },
                        workspace_dir,
                        cfg.workload_timeout_seconds,
                    )
                    live["workload_seconds"] = round(time.monotonic() - started, 3)
                    report = result["report"]
                    logs = topo.collect_logs()
                    live["workload_inspect"] = result["inspect"]
                    live["workload_report_env_names"] = (report or {}).get("env_names")
                    egress = _egress(logs["gateway_events"], canary, report)
                    tools = ((report or {}).get("mcp") or {}).get("tools")
                    live.update(
                        observed_tools=tools if spec["mcp_container_started"] else [],
                        agent_instructions_sha256=(report or {}).get("instructions_sha256"),
                    )
                    events = _events(
                        report,
                        logs["mcp_telemetry"],
                        listed=bool(((report or {}).get("mcp") or {}).get("ok")),
                    )
                    internal = bool(enforcement["internal_flag"]) and not canary["breaches"]
                    if result["timed_out"]:
                        runner_record = _error_record(
                            spec,
                            origin="candidate",
                            category="timeout",
                            code="candidate_timeout",
                            live=live,
                            network_internal=internal,
                            egress=egress,
                        )
                    elif report is None or "agent_error" in report or result["exit_code"] != 0:
                        runner_record = _error_record(
                            spec,
                            origin="runner",
                            category="workload",
                            code="mock_agent_failed",
                            live=live,
                            network_internal=internal,
                            egress=egress,
                        )
                    else:
                        try:
                            scored = score_workspace(
                                spec["task"], spec["scorer_version"], workspace_dir
                            )
                        except TrialScoringUnavailable:
                            scored = None
                        usage = (report.get("model") or {}).get("usage") or {}
                        base = {
                            "network_internal": internal,
                            "egress_destinations": egress,
                            "usage_status": "observed"
                            if "input_tokens" in usage
                            else "unavailable",
                            "usage": usage,
                        }
                        if scored is None:
                            runner_record = _error_record(
                                spec,
                                origin="runner",
                                category="scorer",
                                code="scorer_container_required",
                                live=live,
                                network_internal=internal,
                                egress=egress,
                            )
                        elif scored.get("status") == "scored":
                            passed_cnt = scored.get("passed")
                            total_cnt = scored.get("total")
                            if (passed_cnt is None or total_cnt is None) and isinstance(
                                scored.get("dimensions"), dict
                            ):
                                dims = scored["dimensions"]
                                passed_cnt = sum(
                                    v["passed"]
                                    for v in dims.values()
                                    if isinstance(v.get("passed"), int)
                                )
                                total_cnt = sum(
                                    v["total"]
                                    for v in dims.values()
                                    if isinstance(v.get("total"), int)
                                )
                            runner_record = {
                                **_error_record(spec, origin="", category="", code="", live=live),
                                **base,
                                "status": "scored",
                                "score": {
                                    "passed": passed_cnt,
                                    "total": total_cnt,
                                    "fully_correct": scored.get("fully_correct"),
                                    "dimensions": scored.get("dimensions"),
                                },
                                "error_summary": {"primary_error": None},
                            }
                        else:
                            candidate = scored.get("status") == "candidate_error"
                            runner_record = _error_record(
                                spec,
                                origin="candidate" if candidate else "scorer",
                                category="artifact" if candidate else "scorer",
                                code=str(scored.get("reason") or scored.get("status")),
                                live=live,
                                network_internal=internal,
                                egress=egress,
                                scored=scored,
                            )
                            runner_record.update(
                                usage_status=base["usage_status"], usage=base["usage"]
                            )
                    runner_record["mcp_server_audit"] = {
                        "call_tool_requests": len(logs["mcp_telemetry"])
                    }
                    secrets_seen = [
                        name
                        for name in live_network.HOST_SECRET_NAMES
                        if name in (report or {}).get("env_names", []) and name != "CODEX_API_KEY"
                    ]
                    live["host_secret_names_in_candidate"] = secrets_seen
            except live_network.IsolationEnforcementError as exc:
                runner_record = _error_record(
                    spec,
                    origin="runner",
                    category="isolation",
                    code="isolation_enforcement_failed",
                    live={**live, "detail": str(exc)[:600]},
                )
            except (live_network.DockerError, OSError) as exc:
                runner_record = _error_record(
                    spec,
                    origin="runner",
                    category="docker",
                    code="docker_failure",
                    live={**live, "detail": str(exc)[:600]},
                )
        finally:
            leftovers = topo.teardown()
        live["cleanup_leftovers"] = leftovers
        if runner_record is None:  # pragma: no cover - defensive
            raise RuntimeError("live executor produced no record")
        if leftovers["containers"] or leftovers["networks"]:
            # Unverified cleanup could contaminate later arms: not a usable outcome.
            runner_record = _error_record(
                spec,
                origin="runner",
                category="docker",
                code="cleanup_incomplete",
                live=live,
                network_internal=runner_record.get("network_internal", False),
                egress=runner_record.get("egress_destinations"),
            )
        runner_record["live_evidence"] = live
        return {"runner_record": runner_record, "telemetry_events": events}

    return _execute


def execute_live_study(
    plan: dict[str, Any],
    config: runner.StudyExecutionConfig,
    run_dir: Path,
    settings: LiveExecutorSettings | None = None,
    *,
    before_commit_hook: Callable[[str, int], None] | None = None,
    executor: runner.TrialAttemptExecutor | None = None,
    attempt_controller: runner.AttemptController | None = None,
) -> dict[str, Any]:
    """Run a plan against real Docker topologies with a mock model (opt-in entry point)."""
    cfg = settings or LiveExecutorSettings(
        run_label="stage26-" + hashlib.sha256(str(Path(run_dir).resolve()).encode()).hexdigest()[:8]
    )
    status = live_network.docker_status((cfg.python_image, cfg.mcp_image))
    if not status["ready"]:
        raise live_network.DockerUnavailable(status["reason"] or "Docker is not ready")
    recorded = json.loads(
        (Path(__file__).with_name("frozen_evidence_digests.json")).read_text(encoding="utf-8")
    )
    problems = manifest.verify_frozen(recorded)
    if problems:
        raise FrozenEvidenceError(f"{len(problems)} frozen evidence differences: {problems[:3]}")
    swept = live_network.sweep_run(cfg.run_label)
    result = runner.execute_study_plan(
        plan,
        config,
        run_dir,
        executor or make_docker_trial_executor(cfg),
        before_commit_hook=before_commit_hook,
        attempt_controller=attempt_controller,
    )
    result["resource_cleanup"] = {
        "run_label": cfg.run_label,
        "swept_before_start": swept,
        "remaining_after": live_network.list_resources(run=cfg.run_label),
        "docker_server_version": status["server_version"],
    }
    return result


def fresh_workspace_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="rkmcp-s26-run-"))
