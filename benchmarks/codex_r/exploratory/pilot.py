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
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
_SANITIZER_SPEC = importlib.util.spec_from_file_location(
    "r01_pilot_executor_contract", ROOT / "exploratory" / "executor_contract.py"
)
if _SANITIZER_SPEC is None or _SANITIZER_SPEC.loader is None:
    raise RuntimeError("Reference-data sanitizer is unavailable")
_SANITIZER = importlib.util.module_from_spec(_SANITIZER_SPEC)
_SANITIZER_SPEC.loader.exec_module(_SANITIZER)
PLAN_PATH = ROOT / "reports" / "exploratory-pilot-plan.json"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "medium"
TASKS = ("R01", "R06", "R11")
CONDITIONS = ("A", "B", "C")
SEED = 1729
TRIAL_COUNT = len(TASKS) * len(CONDITIONS)
INITIAL_BALANCE_ESTIMATE_CENTS = 1_000
DEFAULT_RESERVE_CENTS = 200
TRIAL_TIMEOUT_SECONDS = 900
MODEL_DOC_URL = "https://developers.openai.com/api/docs/models/gpt-6-luna"
GPT6_GUIDE_URL = "https://developers.openai.com/api/docs/guides/reasoning"
CLI_REPORT_FIELDS = frozenset(
    {
        "status",
        "available",
        "executable",
        "version",
        "metadata_verified",
        "capabilities_verified",
        "supports_model_flag",
        "supports_config_override",
        "supports_reasoning_effort_override",
        "supports_json_events",
        "supports_ephemeral_mode",
        "checked_without_inference",
        "inference_performed",
        "failure",
    }
)


class PilotError(ValueError):
    """Invalid exploratory pilot plan, preflight, or synthetic event."""


def _is_utc_timestamp(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == datetime.now(UTC).utcoffset()


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
        "initial_available_balance_estimate_usd": 10.00,
        "initial_available_balance_estimate_cents": INITIAL_BALANCE_ESTIMATE_CENTS,
        "default_spending_reserve_cents": DEFAULT_RESERVE_CENTS,
        "spending_limit_type": "balance_aware_best_effort_not_hard_limit",
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
        executable = shutil.which("codex")
    except OSError:
        return _cli_report("discovery_error", failure="executable_discovery_failed")
    if executable is None:
        return _cli_report("not_installed", available=False, failure="executable_not_found")

    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return _cli_report(
            "metadata_error",
            available=True,
            executable=executable,
            failure="version_command_failed",
        )

    version = result.stdout.strip().splitlines()[0][:200] if result.stdout.strip() else ""
    if not re.fullmatch(r"codex-cli \d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        return _cli_report(
            "unsupported_version",
            available=True,
            executable=executable,
            version=version or None,
            failure="unrecognized_version_format",
        )

    try:
        help_result = subprocess.run(
            [executable, "exec", "--help"], capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return _cli_report(
            "metadata_error",
            available=True,
            executable=executable,
            version=version,
            failure="help_command_failed",
        )

    help_text = help_result.stdout
    capabilities = {
        "supports_model_flag": bool(re.search(r"(?m)^\s+-m, --model", help_text)),
        "supports_config_override": bool(re.search(r"(?m)^\s+-c, --config", help_text)),
        "supports_json_events": "--json" in help_text,
        "supports_ephemeral_mode": "--ephemeral" in help_text,
    }
    capabilities["supports_reasoning_effort_override"] = capabilities["supports_config_override"]
    supported = all(capabilities.values())
    return _cli_report(
        "verified" if supported else "unsupported_version",
        available=True,
        executable=executable,
        version=version,
        metadata_verified=True,
        capabilities_verified=True,
        failure=None if supported else "required_cli_capability_missing",
        **capabilities,
    )


def _cli_report(
    status: str,
    *,
    available: bool | None = None,
    executable: str | None = None,
    version: str | None = None,
    metadata_verified: bool = False,
    capabilities_verified: bool = False,
    supports_model_flag: bool | None = None,
    supports_config_override: bool | None = None,
    supports_reasoning_effort_override: bool | None = None,
    supports_json_events: bool | None = None,
    supports_ephemeral_mode: bool | None = None,
    failure: str | None = None,
) -> dict:
    """Return a stable CLI schema and explicitly state that no inference ran."""
    report = {
        "status": status,
        "available": available,
        "executable": executable,
        "version": version,
        "metadata_verified": metadata_verified,
        "capabilities_verified": capabilities_verified,
        "supports_model_flag": supports_model_flag,
        "supports_config_override": supports_config_override,
        "supports_reasoning_effort_override": supports_reasoning_effort_override,
        "supports_json_events": supports_json_events,
        "supports_ephemeral_mode": supports_ephemeral_mode,
        "checked_without_inference": True,
        "inference_performed": False,
        "failure": failure,
    }
    assert set(report) == CLI_REPORT_FIELDS
    return report


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
            "codex_reasoning_override": "documented_model_reasoning_effort_config_key",
            "codex_model_flag": "checked_from_local_cli_help_only",
            "responses_api_function_calling": "documented",
            "source_urls": [
                MODEL_DOC_URL,
                GPT6_GUIDE_URL,
                "https://learn.chatgpt.com/docs/config-file/config-basic",
            ],
            "account_access_status": "MODEL_ACCESS_UNVERIFIED",
            "effective_tool_inventory_status": "unverified_without_execution_session",
        },
        "codex_cli": local_cli_metadata(),
        "tool_inventory": tool_inventory_status(plan),
        "budget": {
            "initial_available_balance_estimate_cents": INITIAL_BALANCE_ESTIMATE_CENTS,
            "balance_status": "operator_must_record_current_dashboard_balance_before_each_trial",
            "balance_source": "operator_dashboard_snapshot",
            "spend_source": (
                "completed_session_report; optional_org_cost_buckets_are_only_a_cross_check"
            ),
            "operator_reserve_cents": DEFAULT_RESERVE_CENTS,
            "reserve_is_configurable": True,
            "policy": "balance_aware_best_effort_sequential_checkpoints",
            "provider_enforced_aggregate_limit": "not_required_for_exploratory_pilot",
            "ledger_is_hard_limit": False,
            "usage_and_cost_reporting": "best_effort_and_may_be_delayed",
            "delayed_accounting_warning": (
                "Delayed usage/cost accounting may allow charges to exceed the "
                "currently reported prepaid balance. The client ledger cannot prevent this."
            ),
            "stop_conditions": [
                "reported_balance_at_or_below_reserve",
                "insufficient_reported_balance",
                "missing_usage_or_spend_data",
                "unreconciled_balance_or_spending",
            ],
            "sessions_may_run_concurrently": False,
            "source_urls": [
                "https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create",
                "https://developers.openai.com/api/docs/guides/agents-api/observability",
                "https://developers.openai.com/api/docs/guides/rate-limits",
                "https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs",
            ],
        },
        "isolation": {"status": "AGENT_ISOLATION_UNVERIFIED"},
        "blocking_conditions": [
            "MODEL_ACCESS_UNVERIFIED",
            "AGENT_ISOLATION_UNVERIFIED",
            "HIDDEN_ORACLE_EXPOSURE_UNVERIFIED",
            "EFFECTIVE_TOOL_INVENTORY_UNVERIFIED",
            "PAID_TRIAL_AUTHORIZATION_MISSING",
        ],
        "trial_execution": {
            "mode": "one_trial_per_explicit_authorization",
            "automatic_batch_launch": False,
            "checkpoint_required_after_each_trial": True,
            "real_execution_adapter_status": "not_implemented_and_not_verified",
        },
        "launch_permitted": False,
        "sessions_created": 0,
        "paid_calls_made": 0,
        "status": "blocked",
    }


class BalanceAwareLedger:
    """Client-side balance checkpoint workflow; this is not a provider hard limit."""

    def __init__(
        self,
        available_balance_cents: int | None = None,
        *,
        reserve_cents: int = DEFAULT_RESERVE_CENTS,
        balance_source: str = "operator_dashboard",
        checked_at: str | None = None,
    ):
        if available_balance_cents is not None and (
            type(available_balance_cents) is not int or available_balance_cents < 0
        ):
            raise PilotError("Available balance must be non-negative integer cents or unknown")
        if type(reserve_cents) is not int or reserve_cents < 0:
            raise PilotError("Operator reserve must be non-negative integer cents")
        if not balance_source or not isinstance(balance_source, str):
            raise PilotError("Balance source must be named")
        if available_balance_cents is not None and not _is_utc_timestamp(checked_at):
            raise PilotError("A current UTC timestamp is required with a balance snapshot")
        self.available_balance_cents = available_balance_cents
        self.reserve_cents = reserve_cents
        self.balance_source = balance_source
        self.balance_checked_at = checked_at
        self.opening_balance_cents = available_balance_cents
        self.opening_balance_checked_at = checked_at
        self.authorizations: list[dict] = []
        self.completed_trials: list[dict] = []
        self.active_trial_id: str | None = None
        self.stopped_reason: str | None = None

    def authorize_one(
        self,
        trial_id: str,
        *,
        operator_authorized: bool,
        estimated_spend_cents: int | None,
    ) -> dict:
        """Record explicit authorization for one trial; does not launch it."""
        if self.stopped_reason:
            raise PilotError(f"Pilot is stopped: {self.stopped_reason}")
        if not operator_authorized:
            raise PilotError("Explicit operator authorization is required for each paid trial")
        if self.active_trial_id is not None:
            raise PilotError("A trial is active; concurrent paid sessions are prohibited")
        if self.available_balance_cents is None:
            self.stopped_reason = "available_credit_balance_unknown"
            raise PilotError("Cannot proceed without a current reported available balance")
        if self.available_balance_cents <= self.reserve_cents:
            self.stopped_reason = "available_balance_at_or_below_reserve"
            raise PilotError("Available balance does not exceed the operator reserve")
        if type(estimated_spend_cents) is not int or estimated_spend_cents <= 0:
            self.stopped_reason = "trial_spend_estimate_unavailable"
            raise PilotError("A positive operator-estimated trial spend is required")
        if self.available_balance_cents - self.reserve_cents < estimated_spend_cents:
            self.stopped_reason = "estimated_trial_spend_exceeds_available_balance"
            raise PilotError("Reported balance is insufficient for estimate plus reserve")
        allowed_ids = {f"{task}-{condition}" for task in TASKS for condition in CONDITIONS}
        if trial_id not in allowed_ids or trial_id in {
            x["trial_id"] for x in self.completed_trials
        }:
            raise PilotError("Trial ID must be assigned in the pilot and not previously completed")
        self.active_trial_id = trial_id
        record = {
            "trial_id": trial_id,
            "authorized_by_operator": True,
            "authorized_at": datetime.now(UTC).isoformat(),
            "session_started": False,
            "automatic_next_trial_authorized": False,
            "available_balance_cents": self.available_balance_cents,
            "reserve_cents": self.reserve_cents,
            "operator_estimated_spend_cents": estimated_spend_cents,
            "estimate_is_binding": False,
            "ledger_is_hard_limit": False,
        }
        self.authorizations.append(record)
        return record

    def checkpoint(
        self,
        trial_id: str,
        *,
        reported_spend_cents: int | None,
        usage: dict | None,
        correctness_review: str | None,
        remaining_balance_cents: int | None,
        reconciled: bool,
        balance_source: str | None,
        checked_at: str | None,
    ) -> dict:
        """Record required post-trial review; any unknown/mismatch stops the pilot."""
        if self.active_trial_id != trial_id:
            raise PilotError("No matching authorized trial is awaiting a checkpoint")
        issues = []
        if type(reported_spend_cents) is not int or reported_spend_cents < 0:
            issues.append("spending_unavailable")
        usage_fields = {
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "tool_calls",
        }
        if not isinstance(usage, dict) or not usage or not set(usage).issubset(usage_fields):
            issues.append("usage_unavailable")
        elif any(type(value) is not int or value < 0 for value in usage.values()):
            issues.append("usage_unreconciled")
        if not correctness_review or not isinstance(correctness_review, str):
            issues.append("correctness_review_missing")
        if not _is_utc_timestamp(checked_at):
            issues.append("checkpoint_timestamp_missing_or_invalid")
        if not balance_source or not isinstance(balance_source, str):
            issues.append("balance_source_missing")
        if type(remaining_balance_cents) is not int or remaining_balance_cents < 0:
            issues.append("remaining_balance_unavailable")
        if not reconciled:
            issues.append("spending_or_balance_unreconciled")
        if type(self.available_balance_cents) is not int or type(reported_spend_cents) is not int:
            issues.append("opening_balance_or_spend_missing")
        elif (
            type(reported_spend_cents) is int
            and type(remaining_balance_cents) is int
            and (self.available_balance_cents - reported_spend_cents != remaining_balance_cents)
        ):
            issues.append("reported_balance_does_not_reconcile_with_spend")

        checkpoint = {
            "trial_id": trial_id,
            "checked_at": checked_at,
            "balance_source": balance_source,
            "opening_balance_cents": self.available_balance_cents,
            "reported_spend_cents": reported_spend_cents,
            "usage": usage,
            "correctness_review": correctness_review,
            "remaining_balance_cents": remaining_balance_cents,
            "reconciled": not issues,
            "stop_reasons": issues,
            "automatic_next_trial_authorized": False,
            "ledger_is_hard_limit": False,
        }
        self.completed_trials.append(checkpoint)
        self.active_trial_id = None
        if issues:
            self.stopped_reason = ",".join(issues)
        else:
            self.available_balance_cents = remaining_balance_cents
            self.balance_source = balance_source or self.balance_source
            self.balance_checked_at = checked_at
            if remaining_balance_cents <= self.reserve_cents:
                self.stopped_reason = "available_balance_at_or_below_reserve"
        return checkpoint

    def audit_record(self) -> dict:
        """Return a JSON-safe appendable audit snapshot containing no credentials."""
        return {
            "schema_version": 1,
            "record_type": "exploratory_pilot_balance_ledger_not_provider_limit",
            "plan_type": "exploratory_offline_preflight_only",
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "opening_balance_cents": self.opening_balance_cents,
            "opening_balance_checked_at": self.opening_balance_checked_at,
            "balance_cents": self.available_balance_cents,
            "balance_checked_at": self.balance_checked_at,
            "balance_source": self.balance_source,
            "reserve_cents": self.reserve_cents,
            "ledger_is_hard_limit": False,
            "delayed_accounting_may_exceed_reported_balance": True,
            "active_trial_id": self.active_trial_id,
            "stopped_reason": self.stopped_reason,
            "authorizations": list(self.authorizations),
            "checkpoints": list(self.completed_trials),
        }


# Compatibility import name; semantics are balance-aware and best-effort.
BudgetLedger = BalanceAwareLedger


class FakeProcess:
    """Synthetic Codex-like process result; it has no process or network handle."""

    def __init__(self, *, exit_code=0, elapsed_seconds=1, events=()):
        self.exit_code = exit_code
        self.elapsed_seconds = elapsed_seconds
        self.events = list(events)


def redact(value):
    """Scrub synthetic event keys and values through the shared bounded policy."""
    return _SANITIZER.sanitize_reference_data(value, redact_urls=False)


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
