"""Offline safeguards for the single-trial Codex adapter."""

import importlib.util
import json
from datetime import UTC, datetime
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
    second = authorize()
    with pytest.raises(adapter.AdapterError, match="trial already has a consumed authorization"):
        adapter.consume_authorization(second, context, state)
    assert (state / "consumed-trials" / "R01-A.json").exists()


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
