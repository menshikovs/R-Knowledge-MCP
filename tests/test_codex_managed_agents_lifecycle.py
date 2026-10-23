"""Synthetic lifecycle-controller tests; none of these events are trial evidence."""

import importlib.util
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/codex_r"
SPEC = importlib.util.spec_from_file_location(
    "codex_r_lifecycle", ROOT / "exploratory/lifecycle.py"
)
lifecycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lifecycle)


class FakeLease:
    def __init__(self, trial_id):
        self.trial_id = trial_id
        self.released = False
        self.verified = False

    def __enter__(self):
        return self

    def mark_cleanup_verified(self):
        self.verified = True

    def __exit__(self, *_):
        self.released = self.verified


class FakeLedger:
    def __init__(self):
        self.active_trial_id = None
        self.checkpoint_record = None

    def authorize_one(self, trial_id, **kwargs):
        assert kwargs["operator_authorized"] is True
        assert kwargs["estimated_spend_cents"] == 100
        self.active_trial_id = trial_id

    def checkpoint(self, trial_id, **kwargs):
        self.checkpoint_record = {"trial_id": trial_id, **kwargs}
        self.active_trial_id = None
        return self.checkpoint_record


class FakeTopology:
    def __init__(self):
        self.started = False
        self.cleaned = False

    def start(self):
        self.started = True
        return {"proxy_internal_ip": "172.20.0.2"}

    def cleanup(self):
        self.cleaned = True
        return True


class FakeRuntime:
    def __init__(self, workspace):
        self.workspace = workspace
        self.stopped = False

    def start_managed_executor(self, *_args, **_kwargs):
        return {"container_id": "a" * 64}

    def stop_managed_executor(self, _container_id):
        self.stopped = True
        return True


class FakeClient:
    synthetic = True

    def __init__(self, workspace, *, fail=False, delay=0):
        self.workspace = workspace
        self.fail = fail
        self.delay = delay
        self.submitted = False
        self.cancelled = False
        self.deleted = False

    def create_session(self, _context):
        return {
            "session_id": "synthetic_session",
            "environment_id": "synthetic_env",
            "remote_url": "https://api.openai.com/v1/agents/api",
        }

    def send_and_stream(
        self,
        _session_id,
        _task,
        *,
        on_stream_ready,
        on_environment_connected,
        on_task_submitted,
        deadline_seconds,
    ):
        assert 0 < deadline_seconds <= 900
        on_stream_ready()
        on_environment_connected()
        on_task_submitted()
        self.submitted = True
        if self.delay:
            time.sleep(self.delay)
        if not self.fail:
            (self.workspace / "solution.R").write_text("# synthetic output\n")
            yield {"type": "agent.session.turn.completed", "synthetic": True}
        else:
            raise TimeoutError("synthetic stream timeout")

    def cancel_turn(self, _session_id):
        self.cancelled = True

    def delete_session(self, _session_id):
        self.deleted = True


def make_controller(workspace, *, fail=False, delay=0):
    client = FakeClient(workspace, fail=fail, delay=delay)
    runtime = FakeRuntime(workspace)
    topology = FakeTopology()
    ledger = FakeLedger()
    leases = []

    def lease_factory(trial_id):
        lease = FakeLease(trial_id)
        leases.append(lease)
        return lease

    controller = lifecycle.R01ALifecycleController(
        client=client,
        runtime=runtime,
        topology=topology,
        ledger=ledger,
        authorize=lambda *_: None,
        consume_authorization=lambda *_args, **_kwargs: None,
        lease_factory=lease_factory,
        score=lambda task, artifacts, image: {
            "status": "candidate_error",
            "passed": 0,
            "total": 4,
            "synthetic": True,
        },
        frozen_r_image_id="sha256:" + "1" * 64,
        environment_key="synthetic-environment-key",
        estimated_spend_cents=100,
        checkpoint_review=lambda _record: {
            "reported_spend_cents": 50,
            "usage": {"input_tokens": 4, "output_tokens": 2},
            "correctness_review": "synthetic review only",
            "remaining_balance_cents": 950,
            "reconciled": True,
            "balance_source": "synthetic fixture",
            "checked_at": datetime.now(UTC).isoformat(),
        },
        current_live_gates=lambda: {},
        synthetic_mode=True,
    )
    return controller, client, runtime, topology, ledger, leases


def prepare_workspace(path):
    (path / "data").mkdir(parents=True)
    (path / "TASK.md").write_text("Synthetic task only\n")
    (path / "renv.lock").write_text("{}\n")
    (path / "data" / "records.csv").write_text("x\n1\n")


def test_synthetic_controller_runs_one_ordered_lifecycle_and_checkpoints(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    controller, client, runtime, topology, ledger, leases = make_controller(workspace)
    context = {"trial_id": "R01-A", "expected_tools": [], "workspace": str(workspace)}

    report = controller.run_one(
        context=context,
        authorization={"synthetic": True},
        state_directory=tmp_path / "state",
    )

    names = [item["state"] for item in report["states"]]
    assert names == [
        "prepare",
        "consume_authorization",
        "authorize",
        "create_session",
        "stream_events",
        "start_executor",
        "establish_connection",
        "submit_task",
        "finish",
        "terminate_container",
        "export_artifacts",
        "score",
        "checkpoint",
        "cleanup",
    ]
    assert report["synthetic"] is True
    assert "not_benchmark_result" in report["record_type"]
    assert report["launch_permitted"] is False
    assert report["artifact_hashes"]["solution.R"]
    assert report["checkpoint"]["trial_id"] == "R01-A"
    assert report["automatic_next_trial_authorized"] is False
    assert client.submitted and client.deleted
    assert runtime.stopped and topology.cleaned and ledger.active_trial_id is None
    assert leases[0].released


def test_stream_failure_cancels_and_requires_spend_checkpoint(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    controller, client, runtime, topology, ledger, leases = make_controller(workspace, fail=True)
    context = {"trial_id": "R01-A", "expected_tools": [], "workspace": str(workspace)}

    report = controller.run_one(
        context=context,
        authorization={"synthetic": True},
        state_directory=tmp_path / "state",
    )

    assert report["status"] == "attempt_failed_checkpoint_required"
    assert report["scoring"] is None
    assert report["checkpoint"] is not None
    assert client.cancelled and client.deleted and runtime.stopped and topology.cleaned
    assert leases[0].released


def test_create_session_diagnostic_is_preserved_in_safe_lifecycle_audit(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    controller, _client, runtime, topology, ledger, leases = make_controller(workspace)

    class SessionRejectedClient(FakeClient):
        def create_session(self, _context):
            # Match the production client's conservative create-failure flags.
            self.session_creation_attempted = True
            self.session_creation_uncertain = True
            self.session_state = "unknown"
            error = RuntimeError("safe synthetic rejection")
            error.diagnostics = {
                "operation": "create_session",
                "category": "http_rejection",
                "http_status": 403,
                "reason": "Managed Agents API rejected the request with HTTP 403",
                "authorization": "Bearer never-store-this",
                "response_body": "must-not-appear",
            }
            raise error

    controller.client = SessionRejectedClient(workspace)
    context = {"trial_id": "R01-A", "expected_tools": [], "workspace": str(workspace)}
    with pytest.raises(lifecycle.LifecycleError, match="Cleanup") as caught:
        controller.run_one(
            context=context,
            authorization={"synthetic": True},
            state_directory=tmp_path / "state",
        )
    report = caught.value.audit_record

    assert report["failure"] == {
        "operation": "create_session",
        "category": "http_rejection",
        "http_status": 403,
        "reason": "Managed Agents API rejected the request with HTTP 403",
        "reason_code": None,
        "field": None,
        "session_state": None,
        "session_deleted_verified": None,
        "cleanup_reason_code": None,
    }
    assert report["failure_category"] == "http_rejection"
    assert report["inference_submitted"] is False
    assert report["sessions_created_count"] == 0
    assert "never-store-this" not in str(report)
    assert "must-not-appear" not in str(report)
    assert runtime.stopped is False
    assert report["session_creation_outcome"] == "uncertain"
    assert report["session_deleted_verified"] is None and not report["cleanup_verified"]
    assert topology.cleaned and ledger.active_trial_id is None and not leases[0].released


@pytest.mark.parametrize(
    ("deletion_status", "session_state", "cleanup_verified"),
    [
        (True, "deleted", True),
        (None, "unknown", False),
    ],
)
def test_http_201_validation_failure_audit_reports_session_deletion_state(
    tmp_path, deletion_status, session_state, cleanup_verified
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    controller, _client, runtime, topology, _ledger, leases = make_controller(workspace)

    class CreatedButInvalidClient(FakeClient):
        def __init__(self, candidate_workspace):
            super().__init__(candidate_workspace)
            self.session_creation_attempted = True
            self.session_creation_response_received = True
            self.session_creation_http_status = 201
            self.session_creation_uncertain = deletion_status is None
            self.session_id_for_cleanup = "synthetic_session"
            self.session_deletion_verified = deletion_status
            self.session_state = session_state

        def create_session(self, _context):
            error = RuntimeError("Managed Agents session response failed validation")
            error.diagnostics = {
                "operation": "create_session",
                "category": "response_schema_validation",
                "http_status": 201,
                "reason": "Managed Agents session response failed validation",
                "reason_code": "remote_url_path_not_permitted",
                "field": "environment.remote_url",
                "session_state": session_state,
                "session_deleted_verified": deletion_status,
                "cleanup_reason_code": (
                    None if deletion_status is True else "session_delete_not_confirmed"
                ),
            }
            raise error

    controller.client = CreatedButInvalidClient(workspace)
    context = {"trial_id": "R01-A", "expected_tools": [], "workspace": str(workspace)}
    try:
        report = controller.run_one(
            context=context,
            authorization={"synthetic": True},
            state_directory=tmp_path / "state",
        )
    except lifecycle.LifecycleError as exc:
        report = exc.audit_record

    assert report["session_created"] is True
    assert report["sessions_created_count"] == 1
    assert report["session_creation_http_status"] == 201
    assert report["session_state"] == session_state
    assert report["session_deleted_verified"] is deletion_status
    assert report["cleanup_verified"] is cleanup_verified
    assert report["task_submissions_attempted_count"] == 0
    assert report["failure"]["reason_code"] == "remote_url_path_not_permitted"
    assert runtime.stopped is False and topology.cleaned
    assert leases[0].released is cleanup_verified


def test_pre_session_local_failure_records_safe_operation(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    controller, client, runtime, topology, _ledger, leases = make_controller(workspace)

    def reject_consumption(*_args, **_kwargs):
        raise ValueError("Bearer sk-sensitive-secret")

    controller.consume_authorization = reject_consumption
    context = {"trial_id": "R01-A", "expected_tools": [], "workspace": str(workspace)}
    report = controller.run_one(
        context=context,
        authorization={"synthetic": True},
        state_directory=tmp_path / "state",
    )

    assert report["failure"]["operation"] == "consume_authorization"
    assert report["failure"]["category"] == "local_validation"
    assert report["failure"]["reason"] == "consume_authorization failed before session creation"
    assert "sensitive" not in repr(report["failure"])
    assert report["session_creation_attempted"] is False
    assert report["sessions_created_count"] == 0
    assert report["task_submissions_attempted_count"] == 0
    assert client.submitted is False
    assert runtime.stopped is False and topology.cleaned and leases[0].released


def test_deadline_watchdog_terminates_executor_and_requires_checkpoint(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    controller, client, runtime, topology, _ledger, _leases = make_controller(workspace, delay=0.05)
    controller.trial_timeout_seconds = 0.01
    context = {"trial_id": "R01-A", "expected_tools": [], "workspace": str(workspace)}
    with pytest.raises(lifecycle.LifecycleError) as caught:
        controller.run_one(
            context=context,
            authorization={"synthetic": True},
            state_directory=tmp_path / "state",
        )
    report = caught.value.audit_record
    # The deliberately uncooperative fake stream can still be running after
    # candidate termination; that uncertainty must retain the lease.
    assert report["unfinished_operations_uncertain"] is True
    assert report["cleanup_verified"] is False
    assert report["deadline_expired"] is True
    assert report["deadline_termination_verified"] is True
    assert report["checkpoint"] is not None
    assert report["scoring"] is None
    assert client.cancelled and runtime.stopped and topology.cleaned


def test_live_mode_rejects_synthetic_client_before_authorization(tmp_path):
    controller, *_ = make_controller(tmp_path)
    controller.synthetic_mode = False
    with pytest.raises(lifecycle.LifecycleError, match="Synthetic mode"):
        controller.run_one(
            context={"trial_id": "R01-A", "expected_tools": [], "workspace": str(tmp_path)},
            authorization={},
            state_directory=tmp_path / "state",
        )


def test_live_mode_stays_blocked_without_verified_gates(tmp_path):
    controller, client, runtime, topology, ledger, leases = make_controller(tmp_path)
    client.synthetic = False
    controller.synthetic_mode = False

    gate_reads = []
    attempted_side_effects = []
    controller.current_live_gates = lambda: gate_reads.append(True) or {}

    def forbidden(name):
        def attempt(*_args, **_kwargs):
            attempted_side_effects.append(name)
            raise RuntimeError(f"unexpected pre-gate side effect: {name}")

        return attempt

    controller.authorize = forbidden("authorize")
    controller.consume_authorization = forbidden("consume_authorization")
    controller.lease_factory = forbidden("lease_acquisition")
    ledger.authorize_one = forbidden("ledger_authorize")
    topology.start = forbidden("topology_start")
    topology.cleanup = forbidden("topology_cleanup")
    client.create_session = forbidden("session_creation")
    client.send_and_stream = forbidden("task_stream_and_submission")
    client.cancel_turn = forbidden("session_cancellation")
    client.delete_session = forbidden("session_deletion")
    runtime.start_managed_executor = forbidden("executor_start")
    runtime.stop_managed_executor = forbidden("executor_termination")

    with pytest.raises(lifecycle.LifecycleError) as caught:
        controller.run_one(
            context={"trial_id": "R01-A", "expected_tools": [], "workspace": str(tmp_path)},
            authorization={},
            state_directory=tmp_path / "state",
        )

    assert str(caught.value) == "Cleanup or executor termination/evidence requires review"
    assert isinstance(caught.value.__cause__, lifecycle.LifecycleError)
    assert str(caught.value.__cause__) == "Live verification gates are incomplete"
    assert gate_reads == [True]
    assert attempted_side_effects == []
    assert leases == []
    assert client.submitted is False and client.deleted is False and client.cancelled is False
    assert runtime.stopped is False
    assert topology.started is False and topology.cleaned is False
    assert ledger.active_trial_id is None
    report = caught.value.audit_record
    assert report["cleanup_verified"] is False
    assert report["failure"]["operation"] == "preparation"
    assert report["failure"]["category"] == "preparation_failed"
    audit_path = controller.safety.journal.path.with_suffix(".audit.json")
    assert audit_path.is_file()


def test_unverified_container_termination_blocks_export_and_retains_lease(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    controller, client, runtime, topology, ledger, leases = make_controller(workspace)
    runtime.stop_managed_executor = lambda _container_id: False
    context = {"trial_id": "R01-A", "expected_tools": [], "workspace": str(workspace)}
    with pytest.raises(lifecycle.LifecycleError, match="termination"):
        controller.run_one(
            context=context,
            authorization={"synthetic": True},
            state_directory=tmp_path / "state",
        )
    assert client.deleted and topology.cleaned
    assert ledger.checkpoint_record is not None
    assert leases[0].verified is False
    assert leases[0].released is False


def test_artifact_workspace_rejects_unexpected_files(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    (workspace / "unexpected.bin").write_bytes(b"unexpected")
    with pytest.raises(lifecycle.LifecycleError, match="unexpected artifact"):
        lifecycle.validate_artifact_workspace(workspace, max_bytes=1024)


def test_artifact_workspace_rejects_symlinks(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    try:
        (workspace / "escape").symlink_to(workspace / "TASK.md")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows sandbox does not grant symlink creation privilege")
        raise
    with pytest.raises(lifecycle.LifecycleError, match="symlink or special"):
        lifecycle.validate_artifact_workspace(workspace, max_bytes=1024)


def test_artifact_workspace_enforces_total_size_limit(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepare_workspace(workspace)
    (workspace / "solution.R").write_text("# output\n")
    with pytest.raises(lifecycle.LifecycleError, match="size limit"):
        lifecycle.validate_artifact_workspace(workspace, max_bytes=1)


@pytest.mark.docker
def test_real_docker_synthetic_lifecycle_never_creates_a_trial_record(tmp_path):
    codex_image = os.environ.get("R_KNOWLEDGE_CODEX_IMAGE_ID")
    r_image = os.environ.get("R_KNOWLEDGE_BENCH_IMAGE_ID")
    if not codex_image or not r_image or shutil.which("docker") is None:
        pytest.skip("Pinned Codex/R image IDs and Docker are required")
    available = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if available.returncode:
        pytest.skip("Docker daemon is unavailable")

    def load_module(name, relative):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    adapter = load_module("r01_lifecycle_adapter", "exploratory/adapter.py")
    pilot = load_module("r01_lifecycle_pilot_for_docker", "exploratory/pilot.py")
    docker_runtime = load_module("r01_lifecycle_docker", "exploratory/docker_runtime.py")
    bench = load_module("r01_lifecycle_score_bench", "runner/bench.py")

    workspace = tmp_path / "synthetic-r01-workspace"
    pilot.bench.prepare("R01", workspace)
    state_directory = tmp_path / "controller-state"
    context = adapter.build_trial_context(
        pilot.make_plan(),
        "R01-A",
        workspace,
        candidate_image_digest=codex_image,
        state_directory=state_directory,
    )
    authorization = adapter.create_authorization(
        context,
        typed_confirmation="AUTHORIZE ONE PAID TRIAL R01-A",
        available_balance_cents=1000,
        reserve_cents=200,
        estimated_spend_cents=100,
        balance_source="synthetic fixture",
        balance_checked_at=datetime.now(UTC).isoformat(),
        restricted_key_scope_confirmation="CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A",
    )
    fake_client = FakeClient(workspace)
    topology = docker_runtime.RestrictedEgressNetwork()

    class OfflineDockerRuntime:
        def __init__(self):
            self.probe = None

        def start_managed_executor(self, candidate_workspace, **_kwargs):
            # Runs the actual Codex binary through the offline, isolated fake
            # CONNECT sink. No OpenAI host is contacted or registered.
            self.probe = docker_runtime.run_codex_proxy_transport_probe(
                codex_image, candidate_workspace
            )
            return {"container_id": "b" * 64}

        def stop_managed_executor(self, _container_id):
            return bool(self.probe and self.probe["candidate_container_removed"])

    runtime = OfflineDockerRuntime()
    ledger = pilot.BalanceAwareLedger(
        1000,
        checked_at=datetime.now(UTC).isoformat(),
        balance_source="synthetic fixture",
        reserve_cents=200,
    )
    controller = lifecycle.R01ALifecycleController(
        client=fake_client,
        runtime=runtime,
        topology=topology,
        ledger=ledger,
        authorize=adapter.validate_authorization,
        consume_authorization=adapter.consume_authorization,
        lease_factory=lambda trial_id: adapter.SingleTrialLease(state_directory, trial_id),
        score=lambda task_id, artifacts, image: bench.score(task_id, artifacts, image),
        frozen_r_image_id=r_image,
        environment_key="synthetic-environment-key-never-sent-upstream",
        estimated_spend_cents=100,
        checkpoint_review=lambda _report: {
            "reported_spend_cents": 50,
            "usage": {"input_tokens": 4, "output_tokens": 2},
            "correctness_review": "synthetic only; not an operator review",
            "remaining_balance_cents": 950,
            "reconciled": True,
            "balance_source": "synthetic fixture",
            "checked_at": datetime.now(UTC).isoformat(),
        },
        current_live_gates=lambda: {},
        synthetic_mode=True,
    )
    report = controller.run_one(
        context=context,
        authorization=authorization,
        state_directory=state_directory,
    )

    assert report["synthetic"] is True
    assert report["record_type"] == "synthetic_r01a_lifecycle_audit_not_benchmark_result"
    assert report["launch_permitted"] is False
    assert report["artifact_hashes"]["solution.R"]
    assert report["scoring"]["status"] in {"scored", "candidate_error", "scoring_error"}
    assert runtime.probe["codex_https_proxy_connect_observed"] is True
    assert runtime.probe["upstream_hosts_contacted"] == []
    assert runtime.probe["candidate_container_removed"] is True
    assert report["cleanup_verified"] is True
    assert report["automatic_next_trial_authorized"] is False
    assert not (state_directory / "active-trial.lock").exists()
