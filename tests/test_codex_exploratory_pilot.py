"""Synthetic-only tests for the nine-row exploratory pilot preparation."""

import importlib.util
import json
from pathlib import Path

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
    assert first["aggregate_budget_cents"] == 1_000
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


def test_preflight_is_machine_readable_and_blocked_without_authorizing_paid_work():
    report = pilot.build_preflight(pilot.make_plan())
    restored = json.loads(json.dumps(report))
    assert restored["status"] == "blocked"
    assert restored["launch_permitted"] is False
    assert restored["sessions_created"] == restored["paid_calls_made"] == 0
    assert restored["model"]["account_access_status"] == "MODEL_ACCESS_UNVERIFIED"
    assert restored["budget"]["provider_enforced_aggregate_limit"] == (
        "HARD_AGGREGATE_BUDGET_UNVERIFIED"
    )
    assert restored["isolation"]["status"] == "AGENT_ISOLATION_UNVERIFIED"
    assert restored["codex_cli"]["checked_without_inference"] is True


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


def test_budget_ledger_refuses_over_budget_missing_and_delayed_spend():
    ledger = pilot.BudgetLedger()
    ledger.reserve("one", 600)
    with pytest.raises(pilot.PilotError, match="Unknown or delayed"):
        pilot.BudgetLedger().reserve("unknown", None)
    ledger.settle("one", None, final=False)
    with pytest.raises(pilot.PilotError, match="Unknown or delayed"):
        ledger.reserve("two", 100)
    ledger.settle("one", 590, final=True)
    with pytest.raises(pilot.PilotError, match="exceeded"):
        ledger.reserve("overspend", 411)
    ledger.reserve("two", 410)
    with pytest.raises(pilot.PilotError, match="exceeds"):
        ledger.settle("two", 411, final=True)


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
