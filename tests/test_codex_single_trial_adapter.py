"""Offline safeguards for the single-trial Codex adapter."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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


def test_prepare_workspace_exports_only_public_r01_inputs(tmp_path):
    workspace = tmp_path / "public-R01"
    report = adapter.prepare_workspace("R01", workspace)
    assert report["record_type"] == "public_candidate_workspace_prepared_not_isolation_proof"
    assert report["boundary_verified"] is False
    assert report["files"] == ["TASK.md", "data/records.csv", "renv.lock"]
    assert (
        sorted(
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
            if path.is_file()
        )
        == report["files"]
    )


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


def test_authorization_is_single_row_scoped_expiring_and_one_use(tmp_path):
    plan = pilot.make_plan()
    row = next(item for item in plan["trials"] if item["trial_id"] == "R01-A")
    image_digest = "sha256:" + "b" * 64
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state_directory = tmp_path / "state"
    context = adapter.build_trial_context(
        plan,
        row["trial_id"],
        workspace,
        candidate_image_digest=image_digest,
        state_directory=state_directory,
    )
    now = datetime.now(UTC)
    authorization = adapter.create_authorization(
        context,
        typed_confirmation=f"AUTHORIZE ONE PAID TRIAL {row['trial_id']}",
        now=now,
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic test snapshot",
        balance_checked_at=now.isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
    )
    assert adapter.validate_authorization(authorization, context, now=now) is authorization
    with pytest.raises(adapter.AdapterError, match="does not match"):
        adapter.validate_authorization(
            authorization,
            {**context, "trial_id": "R06-B"},
            now=now,
        )
    with pytest.raises(adapter.AdapterError, match="scope differs"):
        adapter.validate_authorization(
            authorization,
            {**context, "candidate_image_digest": "sha256:" + "c" * 64},
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


def test_active_trial_lease_rejects_a_competing_process(tmp_path):
    state = tmp_path / "state"
    with adapter.SingleTrialLease(state, "R01-A"):
        code = (
            "import importlib.util, pathlib, sys; "
            "s=importlib.util.spec_from_file_location('adapter', sys.argv[1]); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "m.SingleTrialLease(pathlib.Path(sys.argv[2]), 'R01-A').__enter__()"
        )
        competing = subprocess.run(
            [sys.executable, "-c", code, str(adapter.__file__), str(state)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert competing.returncode != 0
        assert "Another trial is active" in competing.stderr


def test_attempt_two_consumption_accepts_only_its_own_verified_lease(tmp_path, monkeypatch):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    markers = state / "consumed-trials"
    markers.mkdir(parents=True)
    first_marker = markers / "R01-A.json"
    first_marker.write_text('{"trial_id":"R01-A","authorization_id":"first"}\n')
    first_marker_bytes = first_marker.read_bytes()
    first_result = tmp_path / "r01a-result.json"
    first_audit = {
        "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
        "trial_id": "R01-A",
        "failure_category": "ManagedAgentsError",
        "session_creation_attempted": True,
        "session_created": False,
        "sessions_created_count": 0,
        "inference_submitted": False,
        "task_submissions_attempted_count": 0,
        "cleanup_verified": True,
        "container_termination_verified": True,
        "session_deleted_verified": True,
        "topology_cleanup_verified": True,
    }
    first_result.write_text(json.dumps(first_audit))
    monkeypatch.setattr(adapter.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    state_directory = state
    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest="sha256:" + "b" * 64,
        state_directory=state_directory,
        attempt_id="R01-A/attempt-2",
        previous_attempt_result=first_result,
    )
    now = datetime.now(UTC)
    authorization = adapter.create_authorization(
        context,
        typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A/attempt-2",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic fixture",
        balance_checked_at=now.isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
        attempt_id="R01-A/attempt-2",
        previous_attempt_result=first_result,
    )

    lease = adapter.SingleTrialLease(state, "R01-A")
    with lease:
        report = adapter.verify_cleanup(state, first_result, lease=lease)
        assert report["active_trial_lock_present"] is True
        assert report["active_trial_lock_owned_by_caller"] is True
        assert report["local_cleanup_verified"] is True
        original_audit_bytes = first_result.read_bytes()
        first_result.write_bytes(original_audit_bytes + b" ")
        with pytest.raises(adapter.AdapterError, match="audit or cleanup verification changed"):
            adapter.consume_authorization(authorization, context, state, lease=lease)
        assert not (markers / "R01-A-attempt-2.json").exists()
        first_result.write_bytes(original_audit_bytes)
        adapter.consume_authorization(authorization, context, state, lease=lease)
        lease.mark_cleanup_verified()
    assert (markers / "R01-A-attempt-2.json").is_file()
    assert first_marker.read_bytes() == first_marker_bytes
    assert not (state / "active-trial.lock").exists()


def test_cleanup_verification_rejects_foreign_or_stale_lock(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
                "synthetic": False,
                "cleanup_verified": True,
                "session_deleted_verified": True,
                "container_termination_verified": True,
                "topology_cleanup_verified": True,
            }
        )
    )
    monkeypatch.setattr(adapter.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    lock_path = state / "active-trial.lock"
    lock_path.write_text('{"trial_id":"R01-A","pid":1,"lease_id":"foreign"}\n')
    foreign = adapter.SingleTrialLease(state, "R01-A")
    report = adapter.verify_cleanup(state, audit_path, lease=foreign)
    assert report["active_trial_lock_present"] is True
    assert report["active_trial_lock_owned_by_caller"] is False
    assert report["local_cleanup_verified"] is False
    with pytest.raises(adapter.AdapterError, match="cleanup is not verified"):
        adapter._verify_first_attempt_for_retry(state, audit_path, lease=foreign)

    lock_path.unlink()
    own_lease = adapter.SingleTrialLease(state, "R01-A")
    with own_lease:
        lock_path.unlink()
        lock_path.write_text('{"trial_id":"R06-A","pid":2,"lease_id":"replacement"}\n')
        own_lease.mark_cleanup_verified()
    assert lock_path.is_file(), "lease exit must not remove a replaced foreign lock"


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


def test_run_one_stays_blocked_before_any_session_can_start(tmp_path):
    plan = pilot.make_plan()
    trial_id = "R01-A"
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    with pytest.raises(adapter.AdapterError, match="image digest"):
        adapter.create_authorization(
            adapter.build_trial_context(plan, trial_id, workspace),
            typed_confirmation=f"AUTHORIZE ONE PAID TRIAL {trial_id}",
            available_balance_cents=1000,
            reserve_cents=200,
            estimated_spend_cents=100,
            balance_source="synthetic test snapshot",
            balance_checked_at=datetime.now(UTC).isoformat(),
            restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
        )
    authorization = adapter.create_authorization(
        adapter.build_trial_context(
            plan,
            trial_id,
            workspace,
            candidate_image_digest="sha256:" + "b" * 64,
            state_directory=tmp_path / "state",
        ),
        typed_confirmation=f"AUTHORIZE ONE PAID TRIAL {trial_id}",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic test snapshot",
        balance_checked_at=datetime.now(UTC).isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
    )
    assert authorization["scope"]["state_directory"] == str((tmp_path / "state").resolve())
    with pytest.raises(adapter.AdapterError, match="scope differs"):
        adapter.validate_authorization(
            authorization,
            adapter.build_trial_context(
                plan,
                trial_id,
                workspace,
                candidate_image_digest="sha256:" + "b" * 64,
                state_directory=tmp_path / "other-state",
            ),
        )


def test_authorization_file_is_private_and_one_use_without_network(tmp_path):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    output = state / "authorization.json"
    now = datetime.now(UTC)
    report = adapter.create_authorization_file(
        plan=pilot.make_plan(),
        trial_id="R01-A",
        workspace=workspace,
        candidate_image_digest="sha256:" + "b" * 64,
        state_directory=state,
        typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic test snapshot",
        balance_checked_at=now.isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
        output=output,
    )
    assert report["status"] == "authorized_one_trial"
    assert output.exists()
    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest="sha256:" + "b" * 64,
        state_directory=state,
    )
    authorization = json.loads(output.read_text())
    assert adapter.validate_authorization(authorization, context)
    with pytest.raises(FileExistsError):
        adapter.create_authorization_file(
            plan=pilot.make_plan(),
            trial_id="R01-A",
            workspace=workspace,
            candidate_image_digest="sha256:" + "b" * 64,
            state_directory=state,
            typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A",
            available_balance_cents=1000,
            reserve_cents=200,
            estimated_spend_cents=100,
            balance_source="synthetic test snapshot",
            balance_checked_at=now.isoformat(),
            restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
            output=output,
        )


def test_usage_extraction_uses_actual_managed_agents_turn_usage():
    usage = adapter._usage_from_lifecycle_events(
        [
            {
                "type": "agent.session.turn.completed",
                "turn": {
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 5,
                        "reasoning_tokens": 3,
                    }
                },
            }
        ]
    )
    assert usage == {
        "input_tokens": 12,
        "output_tokens": 5,
        "reasoning_tokens": 3,
        "total_tokens": 17,
    }
    assert adapter._usage_from_lifecycle_events([]) is None


def test_run_one_delegates_only_the_scoped_r01a_context_to_lifecycle(tmp_path, monkeypatch):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    image = "sha256:" + "b" * 64
    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest=image,
        state_directory=state,
    )
    now = datetime.now(UTC)
    authorization = adapter.create_authorization(
        context,
        typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic test snapshot",
        balance_checked_at=now.isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
    )

    class FakeLifecycleController:
        def run_one(self, **kwargs):
            assert kwargs["context"]["trial_id"] == "R01-A"
            assert kwargs["context"]["expected_tools"] == []
            assert kwargs["authorization"] is authorization
            return {"record_type": "synthetic_r01a_lifecycle_audit_not_benchmark_result"}

    monkeypatch.setattr(
        adapter,
        "_make_live_controller",
        lambda *_args: FakeLifecycleController(),
    )
    result = adapter.run_one(
        plan=pilot.make_plan(),
        trial_id="R01-A",
        authorization=authorization,
        state_directory=state,
        workspace=workspace,
        candidate_image_digest=image,
    )
    assert result["record_type"].startswith("synthetic_")


def test_run_one_rejects_authorization_replay_under_different_state_directory(tmp_path):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    image = "sha256:" + "b" * 64
    context = adapter.build_trial_context(
        pilot.make_plan(), "R01-A", workspace, candidate_image_digest=image, state_directory=state
    )
    now = datetime.now(UTC)
    authorization = adapter.create_authorization(
        context,
        typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic test snapshot",
        balance_checked_at=now.isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
    )
    with pytest.raises(adapter.AdapterError, match="scope differs"):
        adapter.run_one(
            plan=pilot.make_plan(),
            trial_id="R01-A",
            authorization=authorization,
            state_directory=tmp_path / "alternate-state",
            workspace=workspace,
            candidate_image_digest=image,
        )


def test_consumed_trial_marker_prevents_a_second_authorization_in_fixed_state(tmp_path):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    image = "sha256:" + "b" * 64
    context = adapter.build_trial_context(
        pilot.make_plan(), "R01-A", workspace, candidate_image_digest=image, state_directory=state
    )
    now = datetime.now(UTC)

    def authorize():
        return adapter.create_authorization(
            context,
            typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A",
            available_balance_cents=1000,
            reserve_cents=200,
            estimated_spend_cents=100,
            balance_source="synthetic test snapshot",
            balance_checked_at=now.isoformat(),
            restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
        )

    first = authorize()
    adapter.consume_authorization(first, context, state)
    with pytest.raises(adapter.AdapterError, match="already been consumed"):
        authorize()
    assert (state / "consumed-trials" / "R01-A.json").exists()


def test_attempt_two_requires_immutable_clean_attempt_one_and_has_separate_marker(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    marker_dir = state / "consumed-trials"
    marker_dir.mkdir(parents=True)
    first_marker = marker_dir / "R01-A.json"
    first_marker.write_text('{"trial_id":"R01-A","authorization_id":"first"}\n')
    first_marker_before = first_marker.read_bytes()
    first_result = tmp_path / "r01a-result-attempt-1.json"
    first_audit = {
        "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
        "trial_id": "R01-A",
        "failure_category": "ManagedAgentsError",
        "session_creation_attempted": True,
        "session_created": False,
        "sessions_created_count": 0,
        "inference_submitted": False,
        "task_submissions_attempted_count": 0,
        "session_creation_uncertain": True,
        "cleanup_verified": True,
        "container_termination_verified": True,
        "session_deleted_verified": True,
        "topology_cleanup_verified": True,
    }
    first_result.write_text(json.dumps(first_audit))
    monkeypatch.setattr(
        adapter,
        "verify_cleanup",
        lambda *_args, **_kwargs: {"cleanup_verified": False, "local_cleanup_verified": True},
    )

    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest="sha256:" + "b" * 64,
        state_directory=state,
        attempt_id="R01-A/attempt-2",
        previous_attempt_result=first_result,
    )
    now = datetime.now(UTC)
    auth = adapter.create_authorization(
        context,
        typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A/attempt-2",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic fixture",
        balance_checked_at=now.isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
        attempt_id="R01-A/attempt-2",
        previous_attempt_result=first_result,
    )
    assert auth["attempt_id"] == "R01-A/attempt-2"
    assert auth["scope"]["trial_id"] == "R01-A"
    assert (
        auth["scope"]["previous_attempt_audit_sha256"]
        == hashlib.sha256(first_result.read_bytes()).hexdigest()
    )
    assert (
        auth["scope"]["previous_attempt_failure_classification"]
        == "legacy_create_session_failure_unclassified"
    )
    assert auth["scope"]["previous_attempt_provider_status"] == "unknown"
    assert adapter.validate_authorization(auth, context) is auth
    first_result.write_bytes(first_result.read_bytes() + b" ")
    with pytest.raises(adapter.AdapterError, match="audit or cleanup verification changed"):
        adapter.validate_authorization(auth, context)
    first_result.write_text(json.dumps(first_audit))
    adapter.consume_authorization(auth, context, state)
    assert (marker_dir / "R01-A-attempt-2.json").exists()
    assert first_marker.read_bytes() == first_marker_before

    with pytest.raises(adapter.AdapterError, match="trial already has a consumed authorization"):
        adapter.consume_authorization(auth, context, state)
    with pytest.raises(adapter.AdapterError, match="one separately authorized recovery"):
        adapter.build_trial_context(pilot.make_plan(), "R01-A", attempt_id="R01-A/attempt-3")


@pytest.mark.parametrize(
    "audit_change",
    [
        {"task_submission_attempted": True},
        {"task_submissions_attempted_count": 1},
        {"inference_submitted": True},
        {"sessions_created_count": 1},
        {"cleanup_verified": False},
        {"container_termination_verified": False},
        {"session_deleted_verified": False},
        {"topology_cleanup_verified": False},
    ],
)
def test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup(
    tmp_path, monkeypatch, audit_change
):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    markers = state / "consumed-trials"
    markers.mkdir(parents=True)
    (markers / "R01-A.json").write_text('{"trial_id":"R01-A"}\n')
    audit = {
        "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
        "trial_id": "R01-A",
        "failure_category": "ManagedAgentsError",
        "session_creation_attempted": True,
        "session_created": False,
        "sessions_created_count": 0,
        "task_submission_attempted": False,
        "task_submissions_attempted_count": 0,
        "inference_submitted": False,
        "cleanup_verified": True,
        "container_termination_verified": True,
        "session_deleted_verified": True,
        "topology_cleanup_verified": True,
    }
    audit.update(audit_change)
    previous = tmp_path / "attempt-1.json"
    previous.write_text(json.dumps(audit))
    monkeypatch.setattr(
        adapter,
        "verify_cleanup",
        lambda *_args, **_kwargs: {"cleanup_verified": False, "local_cleanup_verified": True},
    )

    with pytest.raises(adapter.AdapterError, match="work or cleanup that is not verified"):
        adapter.build_trial_context(
            pilot.make_plan(),
            "R01-A",
            workspace,
            state_directory=state,
            attempt_id="R01-A/attempt-2",
            previous_attempt_result=previous,
        )


def test_attempt_two_rejects_missing_first_attempt_consumed_marker(tmp_path, monkeypatch):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    previous = tmp_path / "attempt-1.json"
    previous.write_text(
        json.dumps(
            {
                "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
                "trial_id": "R01-A",
                "failure_category": "ManagedAgentsError",
                "session_creation_attempted": True,
                "session_created": False,
                "sessions_created_count": 0,
                "task_submissions_attempted_count": 0,
                "inference_submitted": False,
                "cleanup_verified": True,
                "container_termination_verified": True,
                "session_deleted_verified": True,
                "topology_cleanup_verified": True,
            }
        )
    )
    monkeypatch.setattr(
        adapter,
        "verify_cleanup",
        lambda *_args, **_kwargs: {"cleanup_verified": False, "local_cleanup_verified": True},
    )
    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest="sha256:" + "b" * 64,
        state_directory=state,
        attempt_id="R01-A/attempt-2",
        previous_attempt_result=previous,
    )
    with pytest.raises(adapter.AdapterError, match="Attempt 1 authorization marker is missing"):
        adapter.create_authorization(
            context,
            typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A/attempt-2",
            available_balance_cents=1000,
            reserve_cents=200,
            estimated_spend_cents=100,
            balance_source="synthetic fixture",
            balance_checked_at=datetime.now(UTC).isoformat(),
            restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
            attempt_id="R01-A/attempt-2",
            previous_attempt_result=previous,
        )


def test_recovery_is_append_only_bound_to_expired_attempt_two_provenance(tmp_path, monkeypatch):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    markers = state / "consumed-trials"
    markers.mkdir(parents=True)
    first_marker = markers / "R01-A.json"
    first_marker.write_text('{"trial_id":"R01-A","authorization_id":"first"}\n')
    first_marker_before = first_marker.read_bytes()
    first_result = state / "r01a-result.json"
    first_audit = {
        "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
        "trial_id": "R01-A",
        "failure_category": "ManagedAgentsError",
        "session_creation_attempted": True,
        "session_created": False,
        "sessions_created_count": 0,
        "inference_submitted": False,
        "task_submissions_attempted_count": 0,
        "cleanup_verified": True,
        "container_termination_verified": True,
        "session_deleted_verified": True,
        "topology_cleanup_verified": True,
    }
    first_result.write_text(json.dumps(first_audit))
    prior_two_result = state / "r01a-result-attempt-2.json"
    prior_two_audit = {
        "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
        "synthetic": False,
        "trial_id": "R01-A",
        "attempt_id": "R01-A/attempt-2",
        "failure_category": "AdapterError",
        "states": [
            {"state": name, "at": "2026-10-23T00:00:00+00:00"}
            for name in ("prepare", "terminate_container", "cleanup")
        ],
        "session_creation_attempted": False,
        "session_created": False,
        "sessions_created_count": 0,
        "session_creation_uncertain": False,
        "task_submission_attempted": False,
        "task_submission_uncertain": False,
        "task_submissions_attempted_count": 0,
        "inference_submitted": False,
        "restricted_egress": None,
        "checkpoint": None,
        "cleanup_verified": True,
        "container_termination_verified": True,
        "session_deleted_verified": True,
        "topology_cleanup_verified": True,
    }
    prior_two_result.write_text(json.dumps(prior_two_audit))
    auth_id = "a" * 32
    prior_issued = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=20)
    prior_authorization = {
        "schema_version": 1,
        "authorization_id": auth_id,
        "authorized": True,
        "issued_at": prior_issued.isoformat(),
        "expires_at": (prior_issued + timedelta(seconds=60)).isoformat(),
        "scope": {
            "trial_id": "R01-A",
            "attempt_id": "R01-A/attempt-2",
            "previous_attempt_result": str(first_result.resolve()),
            "previous_attempt_audit_sha256": hashlib.sha256(first_result.read_bytes()).hexdigest(),
            "state_directory": str(state.resolve()),
        },
        "typed_confirmation": "AUTHORIZE ONE PAID TRIAL R01-A/attempt-2",
        "attempt_id": "R01-A/attempt-2",
        "restricted_key_scope_operator_attested": True,
        "consumed": False,
        "balance_snapshot": {},
    }
    prior_auth_path = state / "authorization-attempt-2.json"
    prior_auth_path.write_text(json.dumps(prior_authorization))
    prior_auth_bytes = prior_auth_path.read_bytes()
    monkeypatch.setattr(adapter.shutil, "which", lambda _name: "docker")
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    recovery_id = adapter.RECOVERY_ATTEMPT_ID
    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest="sha256:" + "b" * 64,
        state_directory=state,
        attempt_id=recovery_id,
        previous_attempt_result=prior_two_result,
        first_attempt_result=first_result,
        previous_attempt_authorization=prior_auth_path,
    )
    recovery_auth = adapter.create_authorization(
        context,
        typed_confirmation=f"AUTHORIZE ONE PAID TRIAL {recovery_id}",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic test fixture; no live authorization",
        balance_checked_at=datetime.now(UTC).isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
        attempt_id=recovery_id,
        previous_attempt_result=prior_two_result,
        first_attempt_result=first_result,
        previous_attempt_authorization=prior_auth_path,
    )
    assert recovery_auth["attempt_id"] == recovery_id
    assert (
        recovery_auth["scope"]["previous_attempt_audit_sha256"]
        == hashlib.sha256(prior_two_result.read_bytes()).hexdigest()
    )
    assert (
        recovery_auth["scope"]["recovery_first_attempt_audit_sha256"]
        == hashlib.sha256(first_result.read_bytes()).hexdigest()
    )
    assert (
        recovery_auth["scope"]["previous_attempt_authorization_sha256"]
        == hashlib.sha256(prior_auth_bytes).hexdigest()
    )
    assert recovery_auth["authorization_id"] != auth_id
    assert adapter.validate_authorization(recovery_auth, context) is recovery_auth
    assert first_marker.read_bytes() == first_marker_before
    assert prior_auth_path.read_bytes() == prior_auth_bytes
    assert not (markers / "R01-A-attempt-2.json").exists()
    assert not (markers / "R01-A-recovery-after-attempt-2.json").exists()

    prior_two_result.write_bytes(prior_two_result.read_bytes() + b" ")
    with pytest.raises(adapter.AdapterError, match="provenance changed"):
        adapter.validate_authorization(recovery_auth, context)


def test_attempt_two_is_blocked_without_verified_cleanup_or_prior_consumption(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    result = tmp_path / "first.json"
    result.write_text("{}")
    monkeypatch.setattr(
        adapter,
        "verify_cleanup",
        lambda *_args, **_kwargs: {"cleanup_verified": False, "local_cleanup_verified": False},
    )
    with pytest.raises(adapter.AdapterError, match="cleanup is not verified"):
        adapter.build_trial_context(
            pilot.make_plan(),
            "R01-A",
            workspace,
            state_directory=tmp_path / "state",
            attempt_id="R01-A/attempt-2",
            previous_attempt_result=result,
        )


def _final_continuation_fixture(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "consumed-trials").mkdir(parents=True)
    (state / "consumed-authorizations").mkdir()
    first_result = state / "r01a-result.json"
    first_result.write_text(
        json.dumps(
            {
                "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
                "synthetic": False,
                "trial_id": "R01-A",
                "attempt_id": "R01-A/attempt-1",
                "failure_category": "ManagedAgentsError",
                "session_creation_attempted": True,
                "session_created": False,
                "sessions_created_count": 0,
                "inference_submitted": False,
                "task_submission_attempted": False,
                "task_submissions_attempted_count": 0,
                "cleanup_verified": True,
                "container_termination_verified": True,
                "session_deleted_verified": True,
                "topology_cleanup_verified": True,
            }
        )
    )
    first_id, second_id, third_id = "1" * 32, "2" * 32, "3" * 32
    first_auth = {
        "schema_version": 1,
        "authorization_id": first_id,
        "authorized": True,
        "issued_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:05:00+00:00",
        "typed_confirmation": "AUTHORIZE ONE PAID TRIAL R01-A",
        "restricted_key_scope_operator_attested": True,
        "consumed": False,
        "balance_snapshot": {
            "available_balance_cents": 1000,
            "reserve_cents": 200,
            "estimated_spend_cents": 100,
            "balance_source": "historical operator snapshot",
            "checked_at": "2026-01-01T00:00:00+00:00",
            "estimate_is_binding": False,
            "ledger_is_hard_limit": False,
        },
        "scope": {
            "trial_id": "R01-A",
            "task": "R01",
            "condition": "A",
            "model": "gpt-6-luna",
            "reasoning_effort": "medium",
            "environment_fingerprint": "a" * 64,
            "candidate_image_digest": "sha256:" + "b" * 64,
            "execution_config_digest": "c" * 64,
            "workspace": str((tmp_path / "public-R01").resolve()),
            "state_directory": str(state.resolve()),
            "controller_version": "1.0.0",
        },
    }
    first_auth_path = state / "authorization.json"
    first_auth_path.write_text(json.dumps(first_auth))
    first_marker = state / "consumed-trials" / "R01-A.json"
    first_marker.write_text(json.dumps({"trial_id": "R01-A", "authorization_id": first_id}))
    (state / "consumed-authorizations" / f"{first_id}.json").write_text(
        json.dumps({"authorization_id": first_id, "trial_id": "R01-A"})
    )

    second_result = state / "r01a-result-attempt-2.json"
    second_result.write_text(
        json.dumps(
            {
                "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
                "synthetic": False,
                "trial_id": "R01-A",
                "attempt_id": "R01-A/attempt-2",
                "failure_category": "AdapterError",
                "states": ["prepare", "terminate_container", "cleanup"],
                "session_creation_attempted": False,
                "session_created": False,
                "sessions_created_count": 0,
                "session_creation_uncertain": False,
                "task_submission_attempted": False,
                "task_submission_uncertain": False,
                "task_submissions_attempted_count": 0,
                "inference_submitted": False,
                "cleanup_verified": True,
                "container_termination_verified": True,
                "topology_cleanup_verified": True,
            }
        )
    )
    second_auth = {
        "authorization_id": second_id,
        "authorized": True,
        "consumed": False,
        "attempt_id": "R01-A/attempt-2",
        "typed_confirmation": "AUTHORIZE ONE PAID TRIAL R01-A/attempt-2",
        "issued_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-01T00:01:00+00:00",
        "scope": {
            "trial_id": "R01-A",
            "attempt_id": "R01-A/attempt-2",
            "previous_attempt_result": str(first_result.resolve()),
            "previous_attempt_audit_sha256": hashlib.sha256(first_result.read_bytes()).hexdigest(),
            "state_directory": str(state.resolve()),
        },
    }
    second_auth_path = state / "authorization-attempt-2.json"
    second_auth_path.write_text(json.dumps(second_auth))

    third_result = state / "r01a-result-recovery-after-attempt-2.json"
    third_audit = {
        "record_type": "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
        "synthetic": False,
        "trial_id": "R01-A",
        "attempt_id": "R01-A/recovery-after-attempt-2",
        "authorization_id": third_id,
        "failure_category": "response_schema_validation",
        "failure": {
            "operation": "create_session",
            "category": "response_schema_validation",
            "http_status": 201,
        },
        "session_creation_attempted": True,
        "session_created": False,
        "sessions_created_count": 0,
        "session_state": "unknown",
        "session_deleted_verified": None,
        "task_submissions_attempted_count": 0,
        "inference_submitted": False,
        "container_termination_verified": True,
        "topology_cleanup_verified": True,
        "cleanup_verified": False,
    }
    adapter._private_json_write(third_result, third_audit)
    third_auth = {
        "authorization_id": third_id,
        "authorized": True,
        "consumed": False,
        "attempt_id": adapter.RECOVERY_ATTEMPT_ID,
        "scope": {
            "trial_id": "R01-A",
            "attempt_id": adapter.RECOVERY_ATTEMPT_ID,
            "previous_attempt_audit_sha256": hashlib.sha256(second_result.read_bytes()).hexdigest(),
            "recovery_first_attempt_audit_sha256": hashlib.sha256(
                first_result.read_bytes()
            ).hexdigest(),
            "previous_attempt_authorization_sha256": hashlib.sha256(
                second_auth_path.read_bytes()
            ).hexdigest(),
        },
    }
    third_auth_path = state / "authorization-recovery-after-attempt-2.json"
    third_auth_path.write_text(json.dumps(third_auth))
    third_marker = state / "consumed-trials" / "R01-A-recovery-after-attempt-2.json"
    third_marker.write_text(json.dumps({"trial_id": "R01-A", "authorization_id": third_id}))
    (state / "consumed-authorizations" / f"{third_id}.json").write_text(
        json.dumps({"authorization_id": third_id, "trial_id": "R01-A"})
    )

    evidence = {
        "record_type": "managed_agents_session_quiescence_evidence",
        "source_url": adapter.SESSION_QUIESCENCE_SOURCE,
        "checked_at": datetime.now(UTC).isoformat(),
        "operator_confirmation": adapter.SESSION_QUIESCENCE_CONFIRMATION,
        "not_based_on_agents_logs": True,
        "all_pages_checked": True,
        "pages": [{"data": [{"id": "sess-old", "status": "failed"}], "has_more": False}],
    }
    evidence_path = state / "session-quiescence.json"
    evidence_path.write_text(json.dumps(evidence))
    monkeypatch.setattr(
        adapter,
        "verify_cleanup",
        lambda *_args, **_kwargs: {"local_cleanup_verified": True, "cleanup_verified": False},
    )
    return {
        "state": state,
        "first_result": first_result,
        "first_auth": first_auth_path,
        "second_result": second_result,
        "second_auth": second_auth_path,
        "third_result": third_result,
        "third_auth": third_auth_path,
        "evidence": evidence_path,
        "third_audit": third_audit,
    }


def test_final_continuation_accepts_actual_third_attempt_shape_and_binds_all_history(
    tmp_path, monkeypatch
):
    files = _final_continuation_fixture(tmp_path, monkeypatch)
    persisted_third_audit = json.loads(files["third_result"].read_text())
    assert persisted_third_audit["authorization_id"] == "[REDACTED]"
    hashes = adapter._verify_final_continuation_provenance(
        files["state"],
        files["first_result"],
        files["first_auth"],
        files["second_result"],
        files["second_auth"],
        files["third_result"],
        files["third_auth"],
        files["evidence"],
    )
    assert hashes["third_server_session_state"] == "unknown_until_independent_inventory"
    assert hashes["independent_inventory_active_sessions"] == 0
    assert (
        hashes["first_authorization_sha256"]
        == hashlib.sha256(files["first_auth"].read_bytes()).hexdigest()
    )
    assert (
        hashes["attempt_two_authorization_sha256"]
        == hashlib.sha256(files["second_auth"].read_bytes()).hexdigest()
    )
    assert (
        hashes["third_authorization_sha256"]
        == hashlib.sha256(files["third_auth"].read_bytes()).hexdigest()
    )

    workspace = tmp_path / "public-R01"
    monkeypatch.setattr(adapter, "REPO", tmp_path / "repository-root")
    workspace.mkdir()
    monkeypatch.setattr(
        adapter,
        "_load_controller",
        lambda: SimpleNamespace(
            validate_public_workspace=lambda *_args: {
                "boundary_verified": False,
                "files": ["TASK.md", "data/records.csv", "renv.lock"],
            }
        ),
    )
    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest="sha256:" + "b" * 64,
        state_directory=files["state"],
        attempt_id=adapter.FINAL_CONTINUATION_ATTEMPT_ID,
        first_attempt_result=files["first_result"],
        first_attempt_authorization=files["first_auth"],
        attempt_two_result=files["second_result"],
        attempt_two_authorization=files["second_auth"],
        previous_attempt_result=files["third_result"],
        previous_attempt_authorization=files["third_auth"],
        session_quiescence_evidence=files["evidence"],
    )
    auth = adapter.create_authorization(
        context,
        typed_confirmation=f"AUTHORIZE ONE PAID TRIAL {adapter.FINAL_CONTINUATION_ATTEMPT_ID}",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="offline test fixture",
        balance_checked_at=datetime.now(UTC).isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
        attempt_id=adapter.FINAL_CONTINUATION_ATTEMPT_ID,
        first_attempt_result=files["first_result"],
        first_attempt_authorization=files["first_auth"],
        attempt_two_result=files["second_result"],
        attempt_two_authorization=files["second_auth"],
        previous_attempt_result=files["third_result"],
        previous_attempt_authorization=files["third_auth"],
        session_quiescence_evidence=files["evidence"],
    )
    assert auth["scope"]["final_continuation_provenance"] == hashes
    assert adapter.validate_authorization(auth, context) is auth
    assert not (files["state"] / "consumed-trials" / "R01-A-final-continuation.json").exists()
    historical_auth_bytes = files["first_auth"].read_bytes()
    files["first_auth"].write_bytes(historical_auth_bytes + b" ")
    with pytest.raises(adapter.AdapterError, match="provenance or session evidence changed"):
        adapter.validate_authorization(auth, context)
    files["first_auth"].write_bytes(historical_auth_bytes)
    original_third_bytes = files["third_result"].read_bytes()
    files["third_audit"]["session_deleted_verified"] = True
    files["third_result"].write_text(json.dumps(files["third_audit"]))
    accepted_legacy_claim = adapter._verify_final_continuation_provenance(
        files["state"],
        files["first_result"],
        files["first_auth"],
        files["second_result"],
        files["second_auth"],
        files["third_result"],
        files["third_auth"],
        files["evidence"],
    )
    assert (
        accepted_legacy_claim["third_server_session_state"] == "unknown_until_independent_inventory"
    )
    assert accepted_legacy_claim["legacy_session_deletion_claim_ignored"] is True
    files["third_result"].write_bytes(original_third_bytes)
    files["first_result"].write_bytes(files["first_result"].read_bytes() + b" ")
    with pytest.raises(adapter.AdapterError):
        adapter._verify_final_continuation_provenance(
            files["state"],
            files["first_result"],
            files["first_auth"],
            files["second_result"],
            files["second_auth"],
            files["third_result"],
            files["third_auth"],
            files["evidence"],
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"session_creation_http_status": 400},
        {"failure": {"operation": "create_session", "category": "response_schema_validation"}},
        {"session_created": True},
        {"sessions_created_count": 1},
        {
            "failure": {
                "operation": "other",
                "category": "response_schema_validation",
                "http_status": 201,
            }
        },
        {"authorization_id": "not-the-third-authorization"},
        {"failure_category": "http_rejection"},
        {"task_submission_attempted": True},
        {"task_submission_uncertain": True},
        {"task_submissions_attempted_count": 1},
        {"inference_submitted": True},
        {"container_termination_verified": False},
        {"topology_cleanup_verified": False},
    ],
)
def test_final_continuation_rejects_unsafe_third_attempt_audit(tmp_path, monkeypatch, mutation):
    files = _final_continuation_fixture(tmp_path, monkeypatch)
    files["third_audit"].update(mutation)
    files["third_result"].write_text(json.dumps(files["third_audit"]))
    with pytest.raises(adapter.AdapterError):
        adapter._verify_final_continuation_provenance(
            files["state"],
            files["first_result"],
            files["first_auth"],
            files["second_result"],
            files["second_auth"],
            files["third_result"],
            files["third_auth"],
            files["evidence"],
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"all_pages_checked": False},
        {"not_based_on_agents_logs": False},
        {"source_url": "https://example.com/sessions"},
        {"operator_confirmation": ""},
        {"pages": [{"data": [{"id": "active", "status": "in_progress"}], "has_more": False}]},
        {"pages": [{"data": [{"id": "idle", "status": "idle"}], "has_more": False}]},
        {"pages": [{"data": [{"id": "pending", "status": "requires_action"}], "has_more": False}]},
        {"pages": [{"data": [{"id": "unknown", "status": "mystery"}], "has_more": False}]},
        {"pages": [{"data": [], "has_more": True}]},
        {"checked_at": "2020-01-01T00:00:00+00:00"},
        {
            "pages": [
                {
                    "data": [{"id": "one", "status": "failed"}],
                    "has_more": True,
                    "last_id": "one",
                },
                {"data": [], "has_more": False, "after": "wrong-cursor"},
            ]
        },
    ],
)
def test_final_continuation_requires_complete_fresh_independent_session_inventory(
    tmp_path, monkeypatch, mutation
):
    files = _final_continuation_fixture(tmp_path, monkeypatch)
    evidence = json.loads(files["evidence"].read_text())
    evidence.update(mutation)
    files["evidence"].write_text(json.dumps(evidence))
    with pytest.raises(adapter.AdapterError):
        adapter._verify_final_continuation_provenance(
            files["state"],
            files["first_result"],
            files["first_auth"],
            files["second_result"],
            files["second_auth"],
            files["third_result"],
            files["third_auth"],
            files["evidence"],
        )


@pytest.mark.parametrize("mutation", ["top_level_attempt_id", "scope_attempt_id", "scope_field"])
def test_final_continuation_rejects_nonlegacy_first_authorization_schema(
    tmp_path, monkeypatch, mutation
):
    files = _final_continuation_fixture(tmp_path, monkeypatch)
    first_auth = json.loads(files["first_auth"].read_text())
    if mutation == "top_level_attempt_id":
        first_auth["attempt_id"] = "R01-A/attempt-1"
    elif mutation == "scope_attempt_id":
        first_auth["scope"]["attempt_id"] = "R01-A/attempt-1"
    else:
        first_auth["scope"]["unrecognized"] = True
    files["first_auth"].write_text(json.dumps(first_auth))
    with pytest.raises(adapter.AdapterError, match="legacy contract"):
        adapter._verify_final_continuation_provenance(
            files["state"],
            files["first_result"],
            files["first_auth"],
            files["second_result"],
            files["second_auth"],
            files["third_result"],
            files["third_auth"],
            files["evidence"],
        )


def test_final_continuation_requires_consumed_first_authorization_marker(tmp_path, monkeypatch):
    files = _final_continuation_fixture(tmp_path, monkeypatch)
    marker = files["state"] / "consumed-trials" / "R01-A.json"
    marker.write_text(json.dumps({"trial_id": "R01-A", "authorization_id": "f" * 32}))
    with pytest.raises(adapter.AdapterError, match="does not match its authorization"):
        adapter._verify_final_continuation_provenance(
            files["state"],
            files["first_result"],
            files["first_auth"],
            files["second_result"],
            files["second_auth"],
            files["third_result"],
            files["third_auth"],
            files["evidence"],
        )


@pytest.mark.parametrize("missing_marker", ["trial", "authorization"])
def test_redacted_third_audit_id_requires_valid_third_consumption_markers(
    tmp_path, monkeypatch, missing_marker
):
    files = _final_continuation_fixture(tmp_path, monkeypatch)
    marker = (
        files["state"]
        / ("consumed-trials" if missing_marker == "trial" else "consumed-authorizations")
        / (
            "R01-A-recovery-after-attempt-2.json"
            if missing_marker == "trial"
            else f"{'3' * 32}.json"
        )
    )
    marker.unlink()
    with pytest.raises(adapter.AdapterError):
        adapter._verify_final_continuation_provenance(
            files["state"],
            files["first_result"],
            files["first_auth"],
            files["second_result"],
            files["second_auth"],
            files["third_result"],
            files["third_auth"],
            files["evidence"],
        )


def test_final_continuation_rejects_a_fifth_attempt_identity():
    with pytest.raises(
        adapter.AdapterError, match="first two attempts or one separately authorized recovery"
    ):
        adapter.build_trial_context(pilot.make_plan(), "R01-A", attempt_id="R01-A/attempt-5")


def test_lifecycle_audit_is_not_valid_strict_benchmark_result():
    bench = adapter._load_module(ROOT / "runner" / "bench.py", "test_lifecycle_not_benchmark")
    strict = {}
    with pytest.raises(ValueError, match="Result fields differ"):
        bench.validate_record(
            {
                "record_type": "synthetic_r01a_lifecycle_audit_not_benchmark_result",
                "synthetic": True,
                "trial_id": "R01-A",
                "model": "gpt-6-luna",
                "reasoning_effort": "medium",
                "scoring": {"status": "scored", "passed": 4},
            },
            strict,
        )


def test_live_controller_factory_uses_existing_components_and_keeps_keys_controller_side(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "public-R01"
    adapter.prepare_workspace("R01", workspace)
    state = tmp_path / "state"
    image = "sha256:" + "b" * 64
    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest=image,
        state_directory=state,
    )
    now = datetime.now(UTC)
    authorization = adapter.create_authorization(
        context,
        typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic test snapshot",
        balance_checked_at=now.isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-controller-key")
    monkeypatch.setenv("OPENAI_EXECUTOR_API_KEY", "synthetic-restricted-key")
    instances = {}

    class FakeRuntime:
        docker = "docker"

        def __init__(self, image_id):
            assert image_id == image

        def verify_candidate_image(self):
            return {"image_id": image}

        def _validate_workspace(self, path):
            assert path == workspace
            return {"files": ["TASK.md", "data/records.csv", "renv.lock"]}

    class FakeRRuntime:
        def __init__(self, image_id):
            assert image_id == "sha256:" + "c" * 64

        def verify_engine_and_image(self):
            return {"image_id": "sha256:" + "c" * 64}

    class FakeTopology:
        NAME = SimpleNamespace(pattern="rkmcp-fixed-name-check")

        def __init__(self, docker):
            assert docker == "docker"

    class FakeClient:
        synthetic = False

        def __init__(self, key):
            assert key == "synthetic-controller-key"

    class FakeLifecycle:
        def __init__(self, **kwargs):
            instances.update(kwargs)

    docker_module = SimpleNamespace(
        CodexCandidateRuntime=FakeRuntime,
        DockerCandidateRuntime=FakeRRuntime,
        RestrictedEgressNetwork=FakeTopology,
        FROZEN_R_IMAGE_ID="sha256:" + "c" * 64,
    )
    managed_module = SimpleNamespace(ManagedAgentsClient=FakeClient)
    lifecycle_module = SimpleNamespace(R01ALifecycleController=FakeLifecycle)
    bench_module = SimpleNamespace(score=lambda *_args: {"status": "scored"})

    def load_module(path, _name):
        return {
            "docker_runtime.py": docker_module,
            "lifecycle.py": lifecycle_module,
            "managed_agents.py": managed_module,
            "bench.py": bench_module,
        }[path.name]

    monkeypatch.setattr(adapter, "_load_module", load_module)
    controller = adapter._make_live_controller(context, authorization, state)
    assert isinstance(controller, FakeLifecycle)
    assert instances["current_live_gates"]() == {
        "docker_candidate_image": True,
        "frozen_r_scorer_image": True,
        "public_workspace": True,
        "controller_application_credential": True,
        "restricted_environment_key_present_and_separate": True,
        "restricted_environment_key_scope_operator_attested": True,
        "condition_a_zero_tools": True,
    }
    assert instances["environment_key"] == "synthetic-restricted-key"
    assert instances["client"].synthetic is False
    assert instances["trial_timeout_seconds"] == 900
    monkeypatch.setenv("OPENAI_EXECUTOR_API_KEY", "synthetic-controller-key")
    with pytest.raises(adapter.AdapterError, match="must be distinct"):
        adapter._make_live_controller(context, authorization, state)
