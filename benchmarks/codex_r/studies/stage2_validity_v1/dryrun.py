"""Deterministic synthetic validation of the study machinery. NO model, container or API is used.

A synthetic agent and a mock environment generate complete trial records (including failed, partial,
interrupted and mis-configured trials) from a seed. The records then go through exactly the code a
real study would use: plan verification, per-trial capability checks, dataset validation, telemetry
summaries and the preregistered analysis. The output is evidence about the *machinery* (arm
isolation checks, accounting, schemas, regeneration); it contains no information about the real
effect of R-Knowledge-MCP and must never be reported as model evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import analysis, design, protocol, records, telemetry

DRYRUN_BASE = "Synthetic base instructions shared by every arm."
EXPECTED = {
    "model": "synthetic-model",
    "effort": "medium",
    "scorer_version": "synthetic-scorer-1",
    "base_instructions": DRYRUN_BASE,
    "mcp_tools": ["search_packages", "get_package", "get_function_docs", "list_package_functions"],
    "require_egress_log": True,
}
TOOLS = EXPECTED["mcp_tools"]


class ToolUnavailable(Exception):
    """The mock environment refused a tool call because the arm does not provide it."""


class MockEnvironment:
    """What an arm's sandbox exposes. Misconfiguration flags model real failure modes."""

    def __init__(self, arm_id: str, **faults: bool):
        self.arm = protocol.ARMS[arm_id]
        self.faults = faults
        self.egress: list[str] = [protocol.MODEL_ENDPOINT]
        self.calls = 0

    @property
    def mcp_visible(self) -> bool:
        return self.arm.mcp_available != bool(self.faults.get("flip_mcp"))

    def visible_tools(self) -> list[str]:
        return list(TOOLS) if self.mcp_visible else []

    def call(self, tool: str) -> None:
        if tool not in self.visible_tools():
            raise ToolUnavailable(tool)
        self.calls += 1
        if protocol.MCP_ENDPOINT not in self.egress:
            self.egress.append(protocol.MCP_ENDPOINT)

    def evidence(self, instructions: str | None = None) -> dict:
        destinations = list(self.egress)
        if self.faults.get("leak_web"):
            destinations.append("cran.r-project.org")
        text = self.arm.instructions(DRYRUN_BASE) if instructions is None else instructions
        return {
            "allowed_tools": self.visible_tools(),
            "mcp_container_started": self.mcp_visible,
            "mcp_calls_observed": self.calls,
            "instructions_sha256": protocol.sha256_text(text),
            "model": EXPECTED["model"],
            "effort": EXPECTED["effort"],
            "scorer_version": EXPECTED["scorer_version"],
            "network_internal": not self.faults.get("open_network"),
            "egress_destinations": None if self.faults.get("no_egress_log") else destinations,
        }


def _event(kind: str, run_id: str, trial_id: str, clock_ms: float, source: str, **fields) -> dict:
    return {
        "schema_version": "1.2",
        "event_type": kind,
        "run_id": run_id,
        "trial_id": trial_id,
        "trace_id": "trace-" + hashlib.sha256(trial_id.encode()).hexdigest()[:16],
        "timestamp_utc": "2026-01-01T00:00:00.000Z",
        "monotonic_offset_ms": clock_ms,
        "clock": "trial" if source != telemetry.SERVER else "server_process",
        "source": source,
        **fields,
    }


def synthetic_tool_events(run_id: str, trial_id: str, behaviour: str, rng) -> list[dict]:
    """Schema-1.2 events for one trial's MCP use. `behaviour` selects the scenario."""
    events: list[dict] = []
    if behaviour == "none":
        return events
    calls = {"uses_ok": 2, "uses_errors": 2, "interrupted": 2, "partial_trace": 2, "mismatch": 2}[
        behaviour
    ]
    if behaviour != "partial_trace":
        events.append(
            _event(
                "mcp.discovery.completed",
                run_id,
                trial_id,
                5.0,
                telemetry.SERVER,
                observation="server_audit_after_trial",
                list_tools_requests=1,
            )
        )
    for n in range(1, calls + 1):
        tool = TOOLS[(n + rng.randrange(2)) % len(TOOLS)] if behaviour != "uses_ok" else TOOLS[n]
        cid = f"client-call-{n:04d}"
        events.append(
            _event(
                "mcp.tool.started",
                run_id,
                trial_id,
                1000.0 * n,
                telemetry.CLIENT,
                call_id=cid,
                tool=tool,
            )
        )
        if behaviour == "interrupted" and n == calls:
            continue  # started, never completed: must not be counted as a success
        failed = behaviour == "uses_errors" and n == 1
        events.append(
            _event(
                "mcp.tool.failed" if failed else "mcp.tool.completed",
                run_id,
                trial_id,
                1000.0 * n + 50,
                telemetry.CLIENT,
                call_id=cid,
                tool=tool,
                is_error=failed,
            )
        )
        if behaviour != "partial_trace":
            sid = f"server-call-{n:04d}"
            server_tool = tool if behaviour != "mismatch" else TOOLS[0]
            events.append(
                _event(
                    "mcp.tool.failed" if failed else "mcp.tool.completed",
                    run_id,
                    trial_id,
                    100.0 * n,
                    telemetry.SERVER,
                    call_id=sid,
                    tool=server_tool,
                    is_error=failed,
                    server_call_number=n,
                    duration_ms=12.5,
                    **({"error_codes": ["docs_not_found"]} if failed else {}),
                )
            )
    return events


@dataclass(frozen=True)
class Scenario:
    name: str
    effect_b: float  # change in success probability when the tool is used
    use_b: float  # probability the agent calls a tool in arm B
    use_c: float
    infra_failure: float = 0.04
    leak_a: float = 0.0  # share of arm-A trials whose sandbox wrongly exposes the MCP
    tool_tax: float = 0.0  # reduction in success probability caused by merely having tools


SCENARIOS = {
    "null": Scenario("null", 0.0, 0.5, 0.8),
    "positive": Scenario("positive", 0.30, 0.6, 0.85),
    "negative_tool_tax": Scenario("negative_tool_tax", 0.0, 0.6, 0.85, tool_tax=0.2),
    "heavy_missingness": Scenario("heavy_missingness", 0.15, 0.5, 0.8, infra_failure=0.25),
    "leaky_control": Scenario("leaky_control", 0.0, 0.5, 0.8, leak_a=0.3),
}


def _trial_record(trial: dict, scenario: Scenario, seed: int, run_id: str, base_p: dict) -> dict:
    rng = design.seeded(seed, "synthetic-trial", trial["trial_id"])
    arm_id = trial["arm"]
    faults = {"flip_mcp": True} if arm_id == "A" and rng.random() < scenario.leak_a else {}
    env = MockEnvironment(arm_id, **faults)
    use_p = {"A": 0.0, "B": scenario.use_b, "C": scenario.use_c}[arm_id]
    behaviour = "none"
    if env.mcp_visible and rng.random() < max(use_p, 0.95 if faults else 0.0):
        behaviour = rng.choice(["uses_ok", "uses_ok", "uses_errors", "interrupted", "mismatch"])
        if rng.random() < 0.1:
            behaviour = "partial_trace"
    if behaviour != "none":
        for tool in TOOLS[:2]:
            env.call(tool)
    events = synthetic_tool_events(run_id, trial["trial_id"], behaviour, rng)
    summary = telemetry.summarize_trace(events, available=env.mcp_visible)
    p = base_p[trial["task"]]
    if arm_id != "A":
        p -= scenario.tool_tax
    if behaviour in ("uses_ok", "uses_errors", "mismatch"):
        p += scenario.effect_b
    p = min(max(p, 0.02), 0.98)
    draw = rng.random()
    kind = "scored"
    if draw < scenario.infra_failure:
        kind = "infrastructure_failure"
    elif draw < scenario.infra_failure + 0.01:
        kind = "scoring_error"
    elif draw < scenario.infra_failure + 0.03:
        kind = "candidate_failure"
    elif draw < scenario.infra_failure + 0.04:
        kind = "not_executed"
    total = 5
    passed = sum(rng.random() < p for _ in range(total)) if kind == "scored" else None
    violations = protocol.capability_violations(arm_id, env.evidence(), EXPECTED)
    observed = rng.random() < 0.7
    return {
        "trial_id": trial["trial_id"],
        "block_id": trial["block_id"],
        "task": trial["task"],
        "arm": arm_id,
        "repetition": trial["repetition"],
        "execution_index": trial["execution_index"],
        "model": EXPECTED["model"],
        "effort": EXPECTED["effort"],
        "scorer_version": EXPECTED["scorer_version"],
        "outcome_kind": kind,
        "score": passed / total
        if kind == "scored"
        else 0.0
        if kind == "candidate_failure"
        else None,
        "checks_passed": passed if kind == "scored" else None,
        "checks_total": total if kind == "scored" else None,
        "mcp": {k: v for k, v in summary.items() if k != "links"},
        "usage": (
            {"status": "observed", "input_tokens": 1000 + rng.randrange(500), "output_tokens": 300}
            if observed
            else {"status": "unavailable"}
        ),
        "violations": [v.as_dict() for v in violations],
        "synthetic": True,
    }


def generate(scenario_name: str, tasks: int, reps: int, seed: int) -> tuple[dict, list[dict]]:
    scenario = SCENARIOS[scenario_name]
    task_ids = [f"S{i:02d}" for i in range(1, tasks + 1)]
    plan = design.build_plan(
        task_ids, ("A", "B", "C"), reps, seed, protocol.STUDY_ID + "-synthetic"
    )
    rng = design.seeded(seed, "synthetic-difficulty")
    base_p = {t: 0.2 + 0.6 * rng.random() for t in task_ids}
    run_id = f"synthetic-{scenario_name}-{seed}"
    recs = [_trial_record(t, scenario, seed, run_id, base_p) for t in plan["trials"]]
    return plan, recs


def write_inputs(out: Path, plan: dict, recs: list[dict]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(
        json.dumps(plan, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    with (out / "trial_records.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for rec in recs:
            handle.write(json.dumps(rec, sort_keys=True) + "\n")


def read_inputs(out: Path) -> tuple[dict, list[dict]]:
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    lines = (out / "trial_records.jsonl").read_text(encoding="utf-8").splitlines()
    return plan, [json.loads(line) for line in lines]


def analyse(
    plan: dict, recs: list[dict], seed: int, n_perm: int = 2999, n_boot: int = 1000
) -> dict:
    """Full pipeline from preserved inputs; raises on any validation problem."""
    problems = design.verify_plan(plan) + records.validate_dataset(
        recs, [t["trial_id"] for t in plan["trials"]]
    )
    if problems:
        raise ValueError("; ".join(problems[:5]))
    kinds: dict[str, int] = {}
    for rec in recs:
        kinds[rec["outcome_kind"]] = kinds.get(rec["outcome_kind"], 0) + 1
    violation_codes: dict[str, int] = {}
    for rec in recs:
        for v in rec["violations"]:
            violation_codes[v["code"]] = violation_codes.get(v["code"], 0) + 1
    return {
        "plan_sha256": plan["plan_sha256"],
        "n_trials_planned": len(plan["trials"]),
        "n_records": len(recs),
        "outcome_kinds": dict(sorted(kinds.items())),
        "violation_codes": dict(sorted(violation_codes.items())),
        "arm_position_balance": design.position_balance(plan),
        "analysis": analysis.run_preregistered_analysis(recs, seed, n_perm, n_boot),
        "synthetic": True,
    }


def result_digest(result: dict) -> str:
    return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()


def run_scenario(out: Path, scenario_name: str, tasks: int, reps: int, seed: int) -> dict:
    plan, recs = generate(scenario_name, tasks, reps, seed)
    write_inputs(out, plan, recs)
    result = analyse(plan, recs, seed)
    (out / "analysis.json").write_text(
        json.dumps(result, indent=1, sort_keys=True), encoding="utf-8"
    )
    return {"scenario": scenario_name, "digest": result_digest(result), "result": result}
