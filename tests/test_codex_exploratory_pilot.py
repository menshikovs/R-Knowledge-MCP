"""Synthetic-only tests for the nine-row exploratory pilot preparation."""

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/codex_r"


def load():
    spec = importlib.util.spec_from_file_location(
        "exploratory_pilot", ROOT / "exploratory/pilot.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pilot = load()
CLI_HELP = (
    "Usage: codex exec\n  -m, --model <MODEL>\n  -c, --config <key=value>\n"
    "  --json\n  --ephemeral\n"
)
controller_spec = importlib.util.spec_from_file_location(
    "codex_controller", ROOT / "runner/controller.py"
)
controller = importlib.util.module_from_spec(controller_spec)
controller_spec.loader.exec_module(controller)


def test_plan_has_exact_nine_deterministic_randomized_assignments():
    first = pilot.make_plan()
    second = pilot.make_plan()
    assert first == second
    assert len(first["trials"]) == 9
    assert [row["order"] for row in first["trials"]] == list(range(1, 10))
    assert {(row["task"], row["condition"]) for row in first["trials"]} == {
        (task, condition) for task in ("R01", "R06", "R11") for condition in "ABC"
    }
    assert first["model"] == "gpt-6-luna"
    assert first["reasoning_effort"] == "medium"
    assert first["initial_available_balance_estimate_cents"] == 1_000
    assert first["default_spending_reserve_cents"] == 200
    assert first["spending_limit_type"] == "balance_aware_best_effort_not_hard_limit"
    assert first["trial_timeout_seconds"] == 900
    assert first["paid_execution_authorized"] is False
    assert first["sessions_created"] == 0
    assert first["launch_permitted"] is False


def test_tool_inventories_are_exactly_zero_fifteen_and_twenty():
    result = pilot.tool_inventory_status(pilot.make_plan())
    assert {condition: value["count"] for condition, value in result.items()} == {
        "A": 0,
        "B": 15,
        "C": 20,
    }
    assert len(result["B"]["names"]) == len(set(result["B"]["names"]))
    assert len(result["C"]["names"]) == len(set(result["C"]["names"]))
    assert result["A"]["verification_basis"] == (
        "local condition manifest; no MCP server is configured"
    )
    assert result["B"]["verification_basis"] == "local stdio ListTools response"


def _serialized_preflight_cli(monkeypatch, *, executable, run_side_effect=None, which_error=None):
    if which_error:
        monkeypatch.setattr(pilot.shutil, "which", Mock(side_effect=which_error))
    else:
        monkeypatch.setattr(pilot.shutil, "which", Mock(return_value=executable))
    runner = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(pilot.subprocess, "run", runner)
    report = pilot.build_preflight(pilot.make_plan())
    restored = json.loads(json.dumps(report))
    assert report["status"] == "blocked"
    assert report["launch_permitted"] is False
    assert set(restored["codex_cli"]) == pilot.CLI_REPORT_FIELDS
    assert restored["codex_cli"]["checked_without_inference"] is True
    assert restored["codex_cli"]["inference_performed"] is False
    return restored["codex_cli"], runner


def test_preflight_is_machine_readable_and_blocked_without_authorizing_paid_work(monkeypatch):
    cli, runner = _serialized_preflight_cli(monkeypatch, executable=None)
    assert cli["status"] == "not_installed"
    assert cli["metadata_verified"] is False
    assert cli["capabilities_verified"] is False
    assert cli["supports_model_flag"] is None
    assert runner.call_count == 0
    report = json.loads(json.dumps(pilot.build_preflight(pilot.make_plan())))
    assert report["status"] == "blocked"
    assert report["launch_permitted"] is False
    assert report["sessions_created"] == report["paid_calls_made"] == 0
    assert report["model"]["account_access_status"] == "MODEL_ACCESS_UNVERIFIED"
    assert report["budget"]["provider_enforced_aggregate_limit"] == (
        "not_required_for_exploratory_pilot"
    )
    assert report["budget"]["ledger_is_hard_limit"] is False
    assert "HARD_AGGREGATE_BUDGET_UNVERIFIED" not in json.dumps(report)
    assert report["budget"]["sessions_may_run_concurrently"] is False
    assert "MODEL_ACCESS_UNVERIFIED" in report["blocking_conditions"]
    assert "AGENT_ISOLATION_UNVERIFIED" in report["blocking_conditions"]
    assert "HIDDEN_ORACLE_EXPOSURE_UNVERIFIED" in report["blocking_conditions"]
    assert "EFFECTIVE_TOOL_INVENTORY_UNVERIFIED" in report["blocking_conditions"]
    assert "PAID_TRIAL_AUTHORIZATION_MISSING" in report["blocking_conditions"]
    assert report["isolation"]["status"] == "AGENT_ISOLATION_UNVERIFIED"


def test_cli_metadata_success_is_not_inference(monkeypatch):
    cli, runner = _serialized_preflight_cli(
        monkeypatch,
        executable="/usr/bin/codex",
        run_side_effect=[
            subprocess.CompletedProcess([], 0, "codex-cli 0.162.1\n", ""),
            subprocess.CompletedProcess([], 0, CLI_HELP, ""),
        ],
    )
    assert cli["status"] == "verified"
    assert cli["metadata_verified"] is True
    assert cli["capabilities_verified"] is True
    assert cli["supports_model_flag"] is True
    assert cli["supports_config_override"] is True
    assert cli["supports_reasoning_effort_override"] is True
    assert cli["supports_json_events"] is True
    assert cli["supports_ephemeral_mode"] is True
    assert cli["version"] == "codex-cli 0.162.1"
    assert runner.call_count == 2
    assert runner.call_args_list[0].args[0] == ["/usr/bin/codex", "--version"]
    assert runner.call_args_list[1].args[0] == ["/usr/bin/codex", "exec", "--help"]


def test_cli_discovery_error_has_stable_unverified_schema(monkeypatch):
    cli, runner = _serialized_preflight_cli(
        monkeypatch, executable=None, which_error=PermissionError("denied")
    )
    assert cli["status"] == "discovery_error"
    assert cli["available"] is None
    assert cli["metadata_verified"] is False
    assert cli["failure"] == "executable_discovery_failed"
    assert runner.call_count == 0


@pytest.mark.parametrize(
    ("side_effect", "failure"),
    [
        ([subprocess.CalledProcessError(1, "codex --version")], "version_command_failed"),
        (
            [
                subprocess.CompletedProcess([], 0, "codex-cli 0.162.1", ""),
                subprocess.TimeoutExpired("codex exec --help", timeout=5),
            ],
            "help_command_failed",
        ),
    ],
)
def test_cli_metadata_command_errors_have_stable_schema(monkeypatch, side_effect, failure):
    cli, _ = _serialized_preflight_cli(
        monkeypatch, executable="/usr/bin/codex", run_side_effect=side_effect
    )
    assert cli["status"] == "metadata_error"
    assert cli["available"] is True
    assert cli["metadata_verified"] is False
    assert cli["capabilities_verified"] is False
    assert cli["failure"] == failure
    assert cli["supports_model_flag"] is None


def test_unsupported_cli_version_and_missing_capabilities_are_not_verified(monkeypatch):
    cli, runner = _serialized_preflight_cli(
        monkeypatch,
        executable="/usr/bin/codex",
        run_side_effect=[subprocess.CompletedProcess([], 0, "Codex preview build", "")],
    )
    assert cli["status"] == "unsupported_version"
    assert cli["metadata_verified"] is False
    assert cli["failure"] == "unrecognized_version_format"
    assert runner.call_count == 1

    cli, _ = _serialized_preflight_cli(
        monkeypatch,
        executable="/usr/bin/codex",
        run_side_effect=[
            subprocess.CompletedProcess([], 0, "codex-cli 0.1.0", ""),
            subprocess.CompletedProcess([], 0, "Usage: codex exec", ""),
        ],
    )
    assert cli["status"] == "unsupported_version"
    assert cli["metadata_verified"] is True
    assert cli["capabilities_verified"] is True
    assert cli["supports_model_flag"] is False
    assert cli["failure"] == "required_cli_capability_missing"


def test_plan_rejects_model_mismatch_and_condition_inventory_drift():
    changed_model = pilot.make_plan()
    changed_model["model"] = "another-model"
    with pytest.raises(pilot.PilotError, match="deterministic"):
        pilot.validate_plan(changed_model)
    changed_tools = pilot.make_plan()
    changed_tools["trials"][0]["tools"].append("unexpected_tool")
    with pytest.raises(pilot.PilotError, match="deterministic"):
        pilot.validate_plan(changed_tools)


def test_fake_dry_run_redacts_credentials_and_stays_synthetic():
    row = {**pilot.make_plan()["trials"][0], "model": pilot.MODEL}
    result = pilot.dry_run(
        row,
        pilot.FakeProcess(events=[{"type": "log", "message": "Bearer abcdefghijklmnop"}]),
    )
    assert result["synthetic"] is True
    assert result["benchmark_record_created"] is False
    assert result["launch_permitted"] is False
    assert result["usage"] is None
    assert "abcdefghijklmnop" not in json.dumps(result)
    with pytest.raises(pilot.PilotError, match="schema"):
        pilot.validate_dry_run_result({**result, "unexpected": "field"})


def test_dry_run_reports_unexpected_tool_timeout_and_process_failure():
    plan = pilot.make_plan()
    row_b = {**next(row for row in plan["trials"] if row["condition"] == "B"), "model": pilot.MODEL}
    unexpected = pilot.dry_run(
        row_b,
        pilot.FakeProcess(events=[{"type": "tool.call", "tool": "not_allowed"}]),
    )
    assert unexpected["status"] == "simulated_unexpected_tool"
    timeout = pilot.dry_run(row_b, pilot.FakeProcess(elapsed_seconds=901))
    assert timeout["status"] == "simulated_timeout"
    failed = pilot.dry_run(row_b, pilot.FakeProcess(exit_code=17))
    assert failed["status"] == "simulated_process_failure"


def test_balance_aware_ledger_requires_fresh_balance_and_explicit_single_trial_auth():
    unknown = pilot.BalanceAwareLedger(None)
    with pytest.raises(pilot.PilotError, match="current reported available balance"):
        unknown.authorize_one("R01-A", operator_authorized=True, estimated_spend_cents=100)
    assert unknown.stopped_reason == "available_credit_balance_unknown"

    ledger = pilot.BalanceAwareLedger(1_000, reserve_cents=250, checked_at="2026-10-23T10:00:00Z")
    with pytest.raises(pilot.PilotError, match="Explicit operator authorization"):
        ledger.authorize_one("R01-A", operator_authorized=False, estimated_spend_cents=100)
    authorization = ledger.authorize_one(
        "R01-A", operator_authorized=True, estimated_spend_cents=100
    )
    assert authorization["session_started"] is False
    assert authorization["ledger_is_hard_limit"] is False
    with pytest.raises(pilot.PilotError, match="concurrent paid sessions"):
        ledger.authorize_one("R06-B", operator_authorized=True, estimated_spend_cents=100)


def test_balance_aware_authorization_requires_timestamp_and_nonbinding_estimate():
    with pytest.raises(pilot.PilotError, match="UTC timestamp"):
        pilot.BalanceAwareLedger(1_000)
    ledger = pilot.BalanceAwareLedger(300, reserve_cents=200, checked_at="2026-10-23T10:00:00Z")
    with pytest.raises(pilot.PilotError, match="positive operator-estimated"):
        ledger.authorize_one("R01-A", operator_authorized=True, estimated_spend_cents=None)
    assert ledger.stopped_reason == "trial_spend_estimate_unavailable"


def test_balance_checkpoint_reconciles_and_never_authorizes_next_trial():
    ledger = pilot.BalanceAwareLedger(1_000, reserve_cents=200, checked_at="2026-10-23T10:00:00Z")
    ledger.authorize_one("R01-A", operator_authorized=True, estimated_spend_cents=100)
    checkpoint = ledger.checkpoint(
        "R01-A",
        reported_spend_cents=125,
        usage={"input_tokens": 1_000, "output_tokens": 200},
        correctness_review="Reviewed independently; acceptable",
        remaining_balance_cents=875,
        reconciled=True,
        balance_source="operator_dashboard",
        checked_at="2026-10-23T10:00:00Z",
    )
    assert checkpoint["reconciled"] is True
    assert checkpoint["automatic_next_trial_authorized"] is False
    assert checkpoint["ledger_is_hard_limit"] is False
    assert ledger.available_balance_cents == 875
    assert ledger.active_trial_id is None
    audit = json.loads(json.dumps(ledger.audit_record()))
    assert audit["authorizations"][0]["trial_id"] == "R01-A"
    assert audit["checkpoints"][0]["reported_spend_cents"] == 125
    assert audit["ledger_is_hard_limit"] is False
    # A new explicit decision is necessary, even after a clean checkpoint.
    ledger.authorize_one("R06-B", operator_authorized=True, estimated_spend_cents=100)


@pytest.mark.parametrize(
    ("spend", "usage", "remaining", "reconciled", "expected"),
    [
        (None, {"input_tokens": 1}, 900, True, "spending_unavailable"),
        (100, None, 900, True, "usage_unavailable"),
        (100, {"input_tokens": 1}, None, True, "remaining_balance_unavailable"),
        (100, {"input_tokens": 1}, 850, True, "reported_balance_does_not_reconcile_with_spend"),
        (100, {"input_tokens": 1}, 900, False, "spending_or_balance_unreconciled"),
        (100, {"operator_secret": 2}, 900, True, "usage_unavailable"),
    ],
)
def test_balance_checkpoint_stops_on_missing_or_unreconciled_data(
    spend, usage, remaining, reconciled, expected
):
    ledger = pilot.BalanceAwareLedger(1_000, reserve_cents=200, checked_at="2026-10-23T10:00:00Z")
    ledger.authorize_one("R01-A", operator_authorized=True, estimated_spend_cents=100)
    result = ledger.checkpoint(
        "R01-A",
        reported_spend_cents=spend,
        usage=usage,
        correctness_review="Reviewed",
        remaining_balance_cents=remaining,
        reconciled=reconciled,
        balance_source="operator_dashboard",
        checked_at="2026-10-23T10:00:00Z",
    )
    assert result["reconciled"] is False
    assert expected in result["stop_reasons"]
    with pytest.raises(pilot.PilotError, match="Pilot is stopped"):
        ledger.authorize_one("R06-B", operator_authorized=True, estimated_spend_cents=100)


def test_balance_reserve_stops_next_trial_without_aggregate_hard_limit():
    ledger = pilot.BalanceAwareLedger(400, reserve_cents=200, checked_at="2026-10-23T10:00:00Z")
    ledger.authorize_one("R01-A", operator_authorized=True, estimated_spend_cents=100)
    result = ledger.checkpoint(
        "R01-A",
        reported_spend_cents=200,
        usage={"input_tokens": 10},
        correctness_review="Reviewed",
        remaining_balance_cents=200,
        reconciled=True,
        balance_source="operator_dashboard",
        checked_at="2026-10-23T10:00:00Z",
    )
    assert result["reconciled"] is True
    assert ledger.stopped_reason == "available_balance_at_or_below_reserve"
    with pytest.raises(pilot.PilotError, match="Pilot is stopped"):
        ledger.authorize_one("R06-B", operator_authorized=True, estimated_spend_cents=100)


def test_public_workspace_and_artifact_sealing_keep_candidate_boundary(tmp_path):
    candidate = tmp_path / "candidate"
    pilot.bench.prepare("R01", candidate)
    assert not candidate.resolve().is_relative_to(pilot.REPO.resolve())
    assert controller.validate_public_workspace(candidate, "R01")["boundary_verified"] is False
    hidden = candidate / "oracle.R"
    hidden.write_text("hidden", encoding="utf-8")
    with pytest.raises(controller.ControllerError, match="only the assigned public"):
        controller.validate_public_workspace(candidate, "R01")
    hidden.unlink()
    source = tmp_path / "artifacts"
    source.mkdir()
    (source / "solution.R").write_text("result <- 1\n", encoding="utf-8")
    sealed = tmp_path / "sealed"
    hashes = pilot.bench.seal_artifacts("R01", source, sealed)
    assert set(hashes) == {"solution.R"}
    assert (sealed / "solution.R").read_text(encoding="utf-8") == "result <- 1\n"
    assert (sealed / "data/records.csv").is_file()
    assert not (sealed / "oracle").exists()


def test_synthetic_results_are_not_accepted_as_benchmark_records():
    plan = pilot.make_plan()
    row = {**plan["trials"][0], "model": pilot.MODEL}
    result = pilot.dry_run(row)
    with pytest.raises(ValueError, match="Result fields"):
        pilot.bench.validate_record(result, plan)
