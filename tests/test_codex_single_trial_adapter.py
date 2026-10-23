"""Offline safeguards for the single-trial Codex adapter."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/codex_r"


def load_adapter():
    spec = importlib.util.spec_from_file_location(
        "codex_single_trial_adapter", ROOT / "exploratory/adapter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_adapter()
pilot = adapter.pilot


def test_jsonl_events_are_bounded_and_credentials_are_redacted():
    raw = b'{"type":"turn.completed","api_key":"secret-value"}\n'
    events = adapter.parse_jsonl_events(raw)
    assert events == [{"type": "turn.completed", "api_key": "[REDACTED]"}]
    with pytest.raises(adapter.AdapterError, match="partial JSONL"):
        adapter.parse_jsonl_events(b'{"type":"partial"}')
    with pytest.raises(adapter.AdapterError, match="byte limit"):
        adapter.parse_jsonl_events(b"x" * (adapter.MAX_EVENT_STREAM_BYTES + 1))


def test_trial_context_binds_fixed_model_condition_tools_and_inputs():
    plan = pilot.make_plan()
    row = plan["trials"][0]
    context = adapter.build_trial_context(plan, row["trial_id"])
    assert context["model"] == "gpt-6-luna"
    assert context["reasoning_effort"] == "medium"
    assert context["timeout_seconds"] == 900
    assert len(context["expected_tools"]) == {"A": 0, "B": 15, "C": 20}[row["condition"]]
    assert len(context["environment_fingerprint"]) == 64
    with pytest.raises(adapter.AdapterError, match="not assigned"):
        adapter.build_trial_context(plan, "R99-A")


def test_preflight_is_honest_and_never_ready_without_isolation_and_access():
    row = pilot.make_plan()["trials"][0]
    context = adapter.build_trial_context(pilot.make_plan(), row["trial_id"])
    report = json.loads(
        json.dumps(
            adapter.build_preflight(
                context,
                cli_report={"status": "verified", "inference_performed": False},
                docker_report={"status": "daemon_available_boundary_unverified"},
            )
        )
    )
    assert report["status"] == "blocked"
    assert report["launch_permitted"] is False
    assert report["sessions_created"] == report["paid_calls_made"] == 0
    assert report["gates"]["account_model_access"]["status"] == "unverified"
    assert report["gates"]["candidate_isolation"]["status"] == "unverified"
    assert report["gates"]["hidden_oracle_exclusion"]["status"] == "unverified"
    assert "SECURE_CODEX_EXECUTION_BACKEND_NOT_IMPLEMENTED" in report["blocking_conditions"]


def test_authorization_is_single_row_scoped_expiring_and_one_use():
    plan = pilot.make_plan()
    row = plan["trials"][0]
    context = adapter.build_trial_context(plan, row["trial_id"])
    now = datetime(2026, 10, 23, tzinfo=UTC)
    authorization = adapter.create_authorization(
        context,
        typed_confirmation=f"AUTHORIZE ONE PAID TRIAL {row['trial_id']}",
        now=now,
    )
    assert adapter.validate_authorization(authorization, context, now=now) is authorization
    with pytest.raises(adapter.AdapterError, match="does not match"):
        adapter.validate_authorization(
            authorization,
            adapter.build_trial_context(plan, plan["trials"][1]["trial_id"]),
            now=now,
        )
    authorization["consumed"] = True
    with pytest.raises(adapter.AdapterError, match="already been consumed"):
        adapter.validate_authorization(authorization, context, now=now)


def test_active_trial_lease_is_exclusive_and_retained_without_cleanup_proof(tmp_path):
    outside_repo = tmp_path / "state"
    with adapter.SingleTrialLease(outside_repo, "R01-A"):
        with pytest.raises(adapter.AdapterError, match="Another trial"):
            with adapter.SingleTrialLease(outside_repo, "R06-B"):
                pass
    assert (outside_repo / "active-trial.lock").exists()

    (outside_repo / "active-trial.lock").unlink()
    with adapter.SingleTrialLease(outside_repo, "R01-A") as lease:
        lease.mark_cleanup_verified()
    assert not (outside_repo / "active-trial.lock").exists()


def test_offline_timeout_probe_terminates_its_synthetic_process_tree():
    result = adapter.run_local_timeout_probe(0.25)
    assert result["record_type"] == "local_process_cleanup_probe_not_trial"
    assert result["synthetic"] is True
    assert result["codex_started"] is False
    assert result["model_requests"] == 0
    assert result["timed_out"] is True
    assert result["process_exited"] is True
    if not result["child_pid_observed"]:
        pytest.skip(
            "Windows sandbox denied child-process creation; process-tree cleanup unverified"
        )
    assert result["descendant_cleanup_verified"] is True


def test_run_one_stays_blocked_before_any_session_can_start():
    plan = pilot.make_plan()
    trial_id = plan["trials"][0]["trial_id"]
    context = adapter.build_trial_context(plan, trial_id)
    authorization = adapter.create_authorization(
        context, typed_confirmation=f"AUTHORIZE ONE PAID TRIAL {trial_id}"
    )
    with pytest.raises(adapter.AdapterError, match="execution is blocked"):
        adapter.run_one(
            plan=plan,
            trial_id=trial_id,
            authorization=authorization,
            state_directory=Path("unused"),
        )
