"""Offline, fail-closed preparation for the nine-trial exploratory Codex pilot.

There is deliberately no model/session launch path in this module. All dry-run
events and usage values are synthetic and cannot be imported as benchmark data.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
PLAN_PATH = ROOT / "reports" / "exploratory-pilot-plan.json"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "medium"
TASKS = ("R01", "R06", "R11")
CONDITIONS = ("A", "B", "C")
SEED = 1729
TRIAL_COUNT = len(TASKS) * len(CONDITIONS)
BUDGET_CENTS = 1_000
TRIAL_TIMEOUT_SECONDS = 900
MODEL_DOC_URL = "https://developers.openai.com/api/docs/models"
GPT6_GUIDE_URL = "https://developers.openai.com/api/docs/guides/latest-model"


class PilotError(ValueError):
    """Invalid exploratory pilot plan, preflight, or synthetic event."""


def _load_bench():
    spec = importlib.util.spec_from_file_location("codex_r_bench", ROOT / "runner" / "bench.py")
    if spec is None or spec.loader is None:
        raise PilotError("Benchmark planning module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load_bench()


def make_plan(seed: int = SEED) -> dict:
    """Create a nine-row schedule independent of the preregistered 72-trial plan."""
    manifest = bench.manifest()
    by_id = {task["id"]: task for task in manifest["tasks"]}
    if set(TASKS) - by_id.keys():
        raise PilotError("Exploratory task set is absent from the benchmark manifest")
    rng = random.Random(seed)
    trials = [{"task": task, "condition": condition} for task in TASKS for condition in CONDITIONS]
    rng.shuffle(trials)
    for index, trial in enumerate(trials, start=1):
        trial["trial_id"] = f"{trial['task']}-{trial['condition']}"
        trial["order"] = index
        trial["timeout_seconds"] = TRIAL_TIMEOUT_SECONDS
        trial["tools"] = list(manifest["conditions"][trial["condition"]]["tools"])
    return {
        "schema_version": 1,
        "plan_type": "exploratory_offline_preflight_only",
        "benchmark": manifest["benchmark"],
        "seed": seed,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "trial_count": TRIAL_COUNT,
        "aggregate_budget_usd": 10.00,
        "aggregate_budget_cents": BUDGET_CENTS,
        "trial_timeout_seconds": TRIAL_TIMEOUT_SECONDS,
        "paid_execution_authorized": False,
        "sessions_created": 0,
        "launch_permitted": False,
        "trials": trials,
    }


def validate_plan(plan: dict) -> dict:
    """Fail closed if controls, row count, condition inventory, or schedule drift."""
    expected = make_plan(plan.get("seed", SEED)) if isinstance(plan, dict) else None
    if plan != expected:
        raise PilotError("Plan does not match its deterministic nine-trial schedule and controls")
    if len(plan["trials"]) != 9:
        raise PilotError("Exploratory pilot must contain exactly nine assignments")
    return plan


def tool_inventory_status(plan: dict) -> dict:
    """Cross-check required inventories against the local MCP interface evidence."""
    validate_plan(plan)
    report_path = ROOT / "reports" / "exploratory-mcp-interface.json"
    report = bench.read_json(report_path)
    observations = {
        item["condition"]: set(item["exposed_tools"]) for item in report["observations"]
    }
    manifest = bench.manifest()
    inventory = {}
    for condition, expected_count in (("A", 0), ("B", 15), ("C", 20)):
        expected = set(manifest["conditions"][condition]["tools"])
        observed = expected if condition == "A" else observations.get(condition)
        if observed is None or observed != expected or len(expected) != expected_count:
            raise PilotError(f"Local MCP tool inventory mismatch for condition {condition}")
        inventory[condition] = {
            "count": expected_count,
            "names": sorted(expected),
            "verified": True,
            "verification_basis": (
                "local condition manifest; no MCP server is configured"
                if condition == "A"
                else "local stdio ListTools response"
            ),
        }
    if report.get("agent_trials") != 0 or report.get("upstream_network_tool_calls") != 0:
        raise PilotError("MCP interface evidence is not a no-trial local check")
    return inventory


def local_cli_metadata() -> dict:
    """Read only CLI version/help; never invoke a prompt, login or model request."""
    try:
        version = subprocess.run(
            ["codex", "--version"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
        help_text = subprocess.run(
            ["codex", "exec", "--help"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "detail": type(exc).__name__}
    return {
        "status": "verified_local_cli_metadata",
        "version": version,
        "supports_model_flag": bool(re.search(r"(?m)^\s+-m, --model", help_text)),
        "supports_json_events": "--json" in help_text,
        "supports_ephemeral_mode": "--ephemeral" in help_text,
        "checked_without_inference": True,
    }


def build_preflight(plan: dict, *, checked_at: datetime | None = None) -> dict:
    """Produce a machine-readable gate report that cannot authorize execution."""
    validate_plan(plan)
    checked_at = checked_at or datetime.now(UTC)
    return {
        "schema_version": 1,
        "checked_at": checked_at.astimezone(UTC).isoformat(),
        "plan_type": plan["plan_type"],
        "model": {
            "id": MODEL,
            "documentation_status": "verified_public_documentation",
            "reasoning_effort": REASONING_EFFORT,
            "responses_api_function_calling": "documented",
            "source_urls": [MODEL_DOC_URL, GPT6_GUIDE_URL],
            "account_access_status": "MODEL_ACCESS_UNVERIFIED",
        },
        "codex_cli": local_cli_metadata(),
        "tool_inventory": tool_inventory_status(plan),
        "budget": {
            "aggregate_ceiling_cents": BUDGET_CENTS,
            "provider_enforced_aggregate_limit": "HARD_AGGREGATE_BUDGET_UNVERIFIED",
            "managed_agent_session_usage": "best_effort_and_may_be_delayed",
            "synthetic_client_ledger_is_provider_enforcement": False,
            "source_urls": [
                "https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create",
                "https://developers.openai.com/api/docs/guides/agents-api/observability",
            ],
        },
        "isolation": {"status": "AGENT_ISOLATION_UNVERIFIED"},
        "launch_permitted": False,
        "sessions_created": 0,
        "paid_calls_made": 0,
        "status": "blocked",
    }


class BudgetLedger:
    """Synthetic client-side ledger; unknown or delayed settlement blocks progress."""

    def __init__(self, limit_cents: int = BUDGET_CENTS):
        if type(limit_cents) is not int or limit_cents <= 0:
            raise PilotError("Budget limit must be positive integer cents")
        self.limit_cents = limit_cents
        self.settled_cents = 0
        self.reservations: dict[str, int | None] = {}
        self.pending: set[str] = set()

    @property
    def reserved_cents(self) -> int:
        return sum(amount for amount in self.reservations.values() if amount is not None)

    def reserve(self, trial_id: str, amount_cents: int | None) -> None:
        if not trial_id or trial_id in self.reservations:
            raise PilotError("Trial reservation must be unique")
        if self.pending or amount_cents is None:
            raise PilotError("Unknown or delayed spend prevents another trial reservation")
        if type(amount_cents) is not int or amount_cents <= 0:
            raise PilotError("Reservation must be positive integer cents")
        if self.settled_cents + self.reserved_cents + amount_cents > self.limit_cents:
            raise PilotError("Synthetic aggregate budget ceiling would be exceeded")
        self.reservations[trial_id] = amount_cents
        self.pending.add(trial_id)

    def settle(self, trial_id: str, actual_cents: int | None, *, final: bool) -> None:
        if trial_id not in self.pending:
            raise PilotError("No pending reservation exists for this trial")
        if actual_cents is None or not final:
            return
        if type(actual_cents) is not int or actual_cents < 0:
            raise PilotError("Settled spend must be non-negative integer cents")
        if actual_cents > self.reservations[trial_id]:
            raise PilotError("Reported spend exceeds its synthetic reservation")
        self.settled_cents += actual_cents
        del self.reservations[trial_id]
        self.pending.remove(trial_id)


class FakeProcess:
    """Synthetic Codex-like process result; it has no process or network handle."""

    def __init__(self, *, exit_code=0, elapsed_seconds=1, events=()):
        self.exit_code = exit_code
        self.elapsed_seconds = elapsed_seconds
        self.events = list(events)


def redact(value):
    """Scrub common credential strings from synthetic event output."""
    if isinstance(value, str):
        for pattern in (
            re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
            re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
            re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[^\s,;]+"),
        ):
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if re.search(r"(?i)(api[_-]?key|access[_-]?token|authorization)", key)
            else redact(item)
            for key, item in value.items()
        }
    return value


def validate_dry_run_result(result: dict) -> dict:
    required = {
        "record_type",
        "synthetic",
        "trial_id",
        "model",
        "condition",
        "status",
        "events",
        "usage",
        "benchmark_record_created",
        "launch_permitted",
    }
    if set(result) != required or result["record_type"] != "exploratory_dry_run_not_trial":
        raise PilotError("Dry-run result does not match the synthetic result schema")
    if result["synthetic"] is not True or result["benchmark_record_created"] is not False:
        raise PilotError("Synthetic dry-run output cannot be represented as a real trial")
    if result["launch_permitted"] is not False or result["usage"] is not None:
        raise PilotError("Synthetic output cannot claim launch permission or actual usage")
    if (
        result["model"] != MODEL
        or result["condition"] not in CONDITIONS
        or result["status"]
        not in {
            "simulated_ready",
            "simulated_timeout",
            "simulated_process_failure",
            "simulated_unexpected_tool",
        }
        or not isinstance(result["trial_id"], str)
        or not isinstance(result["events"], list)
    ):
        raise PilotError("Dry-run result values do not match the synthetic result schema")
    return result


def dry_run(trial: dict, process: FakeProcess | None = None) -> dict:
    """Simulate a single row from fake event data; never starts an OS process."""
    if not isinstance(trial, dict) or trial.get("model", MODEL) != MODEL:
        raise PilotError("Trial model differs from the fixed exploratory model")
    if (
        trial.get("condition") not in CONDITIONS
        or trial.get("timeout_seconds", TRIAL_TIMEOUT_SECONDS) != TRIAL_TIMEOUT_SECONDS
    ):
        raise PilotError("Trial condition or timeout differs from the fixed plan")
    expected = set(bench.manifest()["conditions"][trial["condition"]]["tools"])
    process = process or FakeProcess(events=({"type": "turn.completed", "usage": None},))
    calls = [event.get("tool") for event in process.events if event.get("type") == "tool.call"]
    if any(tool not in expected for tool in calls):
        status = "simulated_unexpected_tool"
    elif process.elapsed_seconds > TRIAL_TIMEOUT_SECONDS:
        status = "simulated_timeout"
    elif process.exit_code != 0:
        status = "simulated_process_failure"
    else:
        status = "simulated_ready"
    result = {
        "record_type": "exploratory_dry_run_not_trial",
        "synthetic": True,
        "trial_id": trial["trial_id"],
        "model": MODEL,
        "condition": trial["condition"],
        "status": status,
        "events": redact(process.events),
        "usage": None,
        "benchmark_record_created": False,
        "launch_permitted": False,
    }
    return validate_dry_run_result(result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-plan", "preflight", "dry-run"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write-plan":
        result = make_plan()
        output = args.output or PLAN_PATH
    else:
        plan = validate_plan(bench.read_json(PLAN_PATH))
        result = (
            build_preflight(plan)
            if args.command == "preflight"
            else {
                "status": "synthetic_only",
                "plan_type": plan["plan_type"],
                "results": [dry_run({**trial, "model": MODEL}) for trial in plan["trials"]],
                "sessions_created": 0,
                "paid_calls_made": 0,
                "launch_permitted": False,
            }
        )
        output = args.output
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if output:
        output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")
    return 2 if args.command == "preflight" else 0


if __name__ == "__main__":
    raise SystemExit(main())
