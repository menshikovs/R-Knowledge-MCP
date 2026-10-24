"""Offline controller dry-run tests; no Codex session or network request is started."""

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("r01a_offline_guard")

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/codex_r"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"runner/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench, controller = load("bench"), load("controller")
IMAGE = "sha256:" + "a" * 64


def experiment():
    return bench.plan("explicit-model-id", "high", IMAGE, repetitions=1)


def config(condition="A"):
    plan = experiment()
    assignment = next(row for row in plan["trials"] if row["condition"] == condition)
    return controller.build_trial_config(plan, assignment["trial_id"])


@pytest.mark.parametrize(("condition", "count"), [("A", 0), ("B", 15), ("C", 20)])
def test_condition_configuration_has_exact_tools_and_only_expected_gateway(condition, count):
    result = config(condition)
    assert len(result["tools"]) == count
    assert len(set(result["tools"])) == count
    assert result["mcp_integrations"] == (
        [] if condition == "A" else ["r-knowledge-benchmark-gateway"]
    )
    assert result["fresh_ephemeral_session"] is True
    assert result["resume_allowed"] is False
    assert result["actual_codex_argv"] is None
    assert result["real_execution_enabled"] is False


def test_config_keeps_preregistered_model_image_and_limits():
    result = config("B")
    assert result["model"] == "explicit-model-id"
    assert result["reasoning_effort"] == "high"
    assert result["image"] == IMAGE
    assert result["wall_time_limit_seconds"] == 900
    assert result["model_token_limit"] == 30_000
    assert result["candidate_mounts"] == ["public task workspace only", "frozen R image"]
    assert "oracle" in result["denied_mounts"]
    assert result["ordinary_network"] == "disabled"


def test_rejects_unassigned_trial_and_changed_fingerprint():
    plan = experiment()
    with pytest.raises(controller.ControllerError, match="not assigned"):
        controller.build_trial_config(plan, "R01-A-2")
    plan["fingerprint"] = "0" * 64
    with pytest.raises(controller.ControllerError, match="fingerprint"):
        controller.build_trial_config(plan, plan["trials"][0]["trial_id"])


def test_rejects_changed_baseline_and_nonimmutable_image():
    plan = experiment()
    plan["production_commit"] = "0" * 40
    with pytest.raises(controller.ControllerError, match="production commit"):
        controller.build_trial_config(plan, plan["trials"][0]["trial_id"])
    plan = experiment()
    plan["image"] = "latest"
    with pytest.raises(controller.ControllerError, match="image digest"):
        controller.build_trial_config(plan, plan["trials"][0]["trial_id"])


def test_rejects_edited_schedule_and_unknown_plan_fields():
    plan = experiment()
    plan["trials"][0]["condition"] = "B" if plan["trials"][0]["condition"] != "B" else "A"
    with pytest.raises(controller.ControllerError, match="deterministic schedule"):
        controller.build_trial_config(plan, plan["trials"][0]["trial_id"])
    plan = experiment()
    plan["unexpected"] = True
    with pytest.raises(controller.ControllerError, match="Plan fields"):
        controller.build_trial_config(plan, plan["trials"][0]["trial_id"])


def test_preflight_stops_even_when_mcp_inventory_matches():
    result = controller.preflight(config("C"), observed_tools=config("C")["tools"])
    assert result["status"] == "blocked"
    assert result["launch_permitted"] is False
    assert result["token_enforcement"] == "unavailable"
    assert any("preemptive cumulative" in reason for reason in result["blockers"])
    assert any("isolated Codex" in reason for reason in result["blockers"])


def test_preflight_rejects_missing_tool_inventory():
    result = controller.preflight(config("B"))
    assert any("inventory has not been probed" in reason for reason in result["blockers"])


def test_preflight_rejects_tool_mismatch():
    expected = config("B")["tools"]
    result = controller.preflight(config("B"), observed_tools=expected[:-1])
    assert any("does not exactly match" in reason for reason in result["blockers"])


@pytest.mark.parametrize("observed", [["unexpected"], ["tool", "tool"]])
def test_tool_inventory_verification_fails_closed(observed):
    with pytest.raises(controller.ControllerError, match="exact condition allowlist"):
        controller.validate_tool_inventory(config("B"), observed)


def test_tool_inventory_verification_accepts_exact_condition():
    assert controller.validate_tool_inventory(config("C"), config("C")["tools"])


def test_initial_workspace_contains_only_public_inputs(tmp_path):
    workspace = tmp_path / "candidate-R03-A-1"
    bench.prepare("R03", workspace)
    result = controller.validate_public_workspace(workspace, "R03")
    assert result["files"] == ["TASK.md", "data/measurements.csv", "renv.lock"]
    assert result["boundary_verified"] is False


def test_workspace_rejects_evaluator_tree_and_added_hidden_material(tmp_path):
    with pytest.raises(controller.ControllerError, match="inside the evaluator"):
        controller.validate_public_workspace(bench.REPO, "R01")
    workspace = tmp_path / "candidate"
    bench.prepare("R01", workspace)
    (workspace / "oracle.R").write_text("hidden", encoding="utf-8")
    with pytest.raises(controller.ControllerError, match="only the assigned public"):
        controller.validate_public_workspace(workspace, "R01")


def test_workspace_rejects_symlinked_root(tmp_path, monkeypatch):
    link = tmp_path / "link"
    bench.prepare("R01", link)
    is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == link or is_symlink(path),
    )
    with pytest.raises(controller.ControllerError, match="regular directory"):
        controller.validate_public_workspace(link, "R01")


def test_redacts_credentials_from_events_and_nested_output():
    value = {
        "message": "Authorization: Bearer abcdefghijklmnop",
        "nested": ["sk-0123456789abcdefghijkl", {"api_key": "very-secret"}],
    }
    redacted = controller.redact_secrets(value)
    assert "abcdefghijklmnop" not in json.dumps(redacted)
    assert "0123456789abcdefghijkl" not in json.dumps(redacted)
    assert "very-secret" not in json.dumps(redacted)


def test_offline_dry_run_is_synthetic_and_does_not_create_benchmark_record():
    plan = experiment()
    result = controller.dry_run(config("A"))
    assert result["record_type"] == "controller_dry_run_not_trial"
    assert result["synthetic"] is True
    assert result["usage"] is None
    assert result["benchmark_record_created"] is False
    assert result["launch_permitted"] is False
    with pytest.raises(ValueError, match="Result fields"):
        bench.validate_record(result, plan)


def test_missing_token_usage_remains_null():
    result = controller.dry_run(
        config("B"), controller.FakeCodexProcess(events=({"type": "turn.completed"},))
    )
    assert result["usage"] is None
    assert result["events"] == [{"type": "turn.completed"}]


def test_timeout_forces_simulated_termination_and_cleanup():
    result = controller.dry_run(
        config("A"),
        controller.FakeCodexProcess(elapsed_seconds=901, events=({"type": "turn.started"},)),
    )
    assert result["status"] == "simulated_timeout"
    assert result["terminated"] is True
    assert result["cleanup_complete"] is True


def test_unexpected_process_exit_is_recorded_as_simulated_failure():
    result = controller.dry_run(config("C"), controller.FakeCodexProcess(exit_code=73))
    assert result["status"] == "simulated_error"
    assert result["cleanup_complete"] is True


def test_dry_run_refuses_real_execution_configuration():
    bad = config("A")
    bad["real_execution_enabled"] = True
    with pytest.raises(controller.ControllerError, match="refuses executable"):
        controller.dry_run(bad)


def test_preflight_stays_blocked_without_verified_isolation_boundary():
    result = controller.preflight(config("A"), observed_tools=[])
    assert result["status"] == "blocked"
    assert result["launch_permitted"] is False
    assert config("A")["denied_mounts"]
