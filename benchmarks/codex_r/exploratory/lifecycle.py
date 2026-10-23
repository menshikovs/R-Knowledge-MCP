"""Single authorized R01-A Managed Agents lifecycle controller.

Live execution is intentionally opt-in through a fresh, scoped authorization.
Unit and Docker integration tests inject synthetic controller responses and
must never produce benchmark records.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path


class LifecycleError(RuntimeError):
    """A trial lifecycle step failed or could not prove a required boundary."""


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LifecycleError("Required benchmark module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _load(Path(__file__).with_name("executor_contract.py"), "r01_lifecycle_contract")


def validate_artifact_workspace(workspace: Path, *, max_bytes: int) -> dict[str, Path]:
    """Require only public inputs and the task's exact output allowlist."""
    workspace = Path(workspace)
    if workspace.is_symlink() or not workspace.is_dir():
        raise LifecycleError("Candidate workspace root is not a regular directory")
    if any(parent.is_symlink() for parent in workspace.parents):
        raise LifecycleError("Candidate workspace has a symlink parent")
    pilot = _load(Path(__file__).with_name("pilot.py"), "r01_lifecycle_pilot")
    task = pilot.bench.task_for("R01")
    allowed = {"TASK.md", "renv.lock", "data/records.csv", *task["artifacts"]}
    files: dict[str, Path] = {}
    total = 0
    for root, dirs, names in os.walk(workspace, followlinks=False):
        root_path = Path(root)
        for name in list(dirs):
            item = root_path / name
            mode = item.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise LifecycleError("Candidate workspace contains a link or special directory")
            if item.relative_to(workspace).as_posix() != "data":
                raise LifecycleError("Candidate workspace contains an unexpected directory")
        for name in names:
            item = root_path / name
            mode = item.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise LifecycleError("Candidate workspace contains a symlink or special file")
            relative = item.relative_to(workspace).as_posix()
            if relative not in allowed:
                raise LifecycleError("Candidate workspace contains an unexpected artifact")
            total += item.stat().st_size
            if total > max_bytes:
                raise LifecycleError("Candidate workspace exceeds the artifact size limit")
            files[relative] = item
    required = {"TASK.md", "renv.lock", "data/records.csv"}
    if not required <= files.keys():
        raise LifecycleError("Public trial inputs are missing")
    outputs = set(task["artifacts"])
    if not outputs <= files.keys():
        raise LifecycleError("Required candidate artifact is missing")
    return files


class R01ALifecycleController:
    """Wire one authorization, Managed Agents session, Docker runtime, scorer and ledger.

    All external components are injected, so tests can exercise orchestration
    without credentials or API calls. `run_one` itself never supports batches.
    """

    STATES = (
        "prepare",
        "consume_authorization",
        "authorize",
        "create_session",
        "start_executor",
        "establish_connection",
        "submit_task",
        "stream_events",
        "finish",
        "terminate_container",
        "export_artifacts",
        "score",
        "checkpoint",
        "cleanup",
    )

    def __init__(
        self,
        *,
        client,
        runtime,
        topology,
        ledger,
        authorize: Callable,
        consume_authorization: Callable,
        lease_factory: Callable,
        score: Callable,
        frozen_r_image_id: str,
        environment_key: str,
        estimated_spend_cents: int,
        checkpoint_review: Callable,
        current_live_gates: Callable[[], dict],
        max_artifact_bytes: int = 8 << 20,
        synthetic_mode: bool = False,
        trial_timeout_seconds: float = 900,
    ):
        self.client = client
        self.runtime = runtime
        self.topology = topology
        self.ledger = ledger
        self.authorize = authorize
        self.consume_authorization = consume_authorization
        self.lease_factory = lease_factory
        self.score = score
        self.frozen_r_image_id = frozen_r_image_id
        self.environment_key = environment_key
        self.estimated_spend_cents = estimated_spend_cents
        self.checkpoint_review = checkpoint_review
        self.current_live_gates = current_live_gates
        self.max_artifact_bytes = max_artifact_bytes
        self.synthetic_mode = synthetic_mode
        if not 0 < trial_timeout_seconds <= 900:
            raise LifecycleError("Trial deadline must be at most 900 seconds")
        self.trial_timeout_seconds = trial_timeout_seconds

    def run_one(self, *, context: dict, authorization: dict, state_directory: Path) -> dict:
        if context.get("trial_id") != "R01-A" or context.get("expected_tools") != []:
            raise LifecycleError("This controller accepts only the fixed R01-A baseline")
        if self.synthetic_mode is not bool(getattr(self.client, "synthetic", False)):
            raise LifecycleError("Synthetic mode must match the injected controller client")
        gates = self.current_live_gates()
        if not self.synthetic_mode and (
            not isinstance(gates, dict)
            or not gates
            or any(value is not True for value in gates.values())
        ):
            raise LifecycleError("Live verification gates are incomplete")
        self.authorize(authorization, context)
        if not self.environment_key:
            raise LifecycleError("Restricted executor environment key is unavailable")
        workspace = Path(context["workspace"]).resolve(strict=True)
        task_path = workspace / "TASK.md"
        task_text = task_path.read_text(encoding="utf-8")
        if len(task_text.encode("utf-8")) > (1 << 20):
            raise LifecycleError("Public task input exceeds the size limit")

        record = {
            "record_type": (
                "synthetic_r01a_lifecycle_audit_not_benchmark_result"
                if self.synthetic_mode
                else "managed_agents_r01a_lifecycle_audit_not_benchmark_result"
            ),
            "synthetic": self.synthetic_mode,
            "trial_id": "R01-A",
            "attempt_id": context.get("attempt_id", "R01-A/attempt-1"),
            "authorization_id": (
                authorization.get("authorization_id")
                if isinstance(authorization, dict)
                and isinstance(authorization.get("authorization_id"), str)
                else None
            ),
            "model": "gpt-6-luna",
            "reasoning_effort": "medium",
            "states": [],
            "events": [],
            "session_created": False,
            "session_creation_attempted": False,
            "sessions_created_count": 0,
            "session_state": "not_started",
            "session_creation_http_status": None,
            "inference_submitted": False,
            "task_submissions_attempted_count": 0,
            "container_termination_verified": False,
            "session_deleted_verified": None,
            "topology_cleanup_verified": False,
            "artifact_hashes": {},
            "scoring": None,
            "checkpoint": None,
            "cleanup_verified": False,
            "launch_permitted": not self.synthetic_mode,
            "deadline_expired": False,
            "deadline_termination_verified": None,
            "pre_session_gates": gates,
            "restricted_egress": None,
            "session_creation_uncertain": False,
            "task_submission_attempted": False,
            "task_submission_uncertain": False,
            "session_creation_outcome": "not_attempted",
            "executor_startup_attempted": False,
            "executor_startup_failed": False,
            "executor_process_started": False,
            "executor_connection_observed": False,
            "task_submission_outcome": "not_attempted",
            "cleanup_failures": [],
        }
        session_id = container_id = None
        lease = self.lease_factory("R01-A")
        session_deleted = False
        container_removed = False
        stream_connected = False
        turn_completed = False
        primary_error = None
        current_operation = "prepare"
        deadline_timer = None
        deadline_expired = threading.Event()
        deadline_termination_verified = []
        executor_cleanup_unverified = False

        def refresh_client_state():
            # Refresh before error reporting, not only after constructing its reason.
            record["session_creation_attempted"] = bool(
                getattr(
                    self.client, "session_creation_attempted", record["session_creation_attempted"]
                )
            )
            if getattr(self.client, "session_creation_response_received", False):
                record["session_created"] = True
                record["sessions_created_count"] = 1
            record["session_creation_http_status"] = getattr(
                self.client, "session_creation_http_status", record["session_creation_http_status"]
            )
            record["session_creation_uncertain"] = bool(
                getattr(
                    self.client, "session_creation_uncertain", record["session_creation_uncertain"]
                )
            )
            record["session_creation_outcome"] = (
                "uncertain"
                if record["session_creation_uncertain"]
                else "confirmed"
                if record["session_created"]
                else "attempted"
                if record["session_creation_attempted"]
                else "not_attempted"
            )
            record["task_submission_attempted"] |= bool(
                getattr(self.client, "task_submission_attempted", False)
            )
            record["task_submission_uncertain"] = bool(
                getattr(
                    self.client, "task_submission_uncertain", record["task_submission_uncertain"]
                )
            )
            record["task_submissions_attempted_count"] = int(record["task_submission_attempted"])
            record["task_submission_outcome"] = (
                "uncertain"
                if record["task_submission_uncertain"]
                else "submitted"
                if record["inference_submitted"]
                else "attempted"
                if record["task_submission_attempted"]
                else "not_attempted"
            )

        def state(name: str):
            nonlocal current_operation
            if name not in self.STATES:
                raise LifecycleError("Unknown lifecycle state")
            current_operation = name
            record["states"].append({"state": name, "at": datetime.now(UTC).isoformat()})

        try:
            lease.__enter__()
            state("prepare")
            current_operation = "consume_authorization"
            state("consume_authorization")
            self.consume_authorization(authorization, context, state_directory, lease=lease)
            current_operation = "authorize"
            self.ledger.authorize_one(
                "R01-A",
                operator_authorized=True,
                estimated_spend_cents=self.estimated_spend_cents,
            )
            state("authorize")
            current_operation = "start_restricted_egress"
            gateway = self.topology.start()
            if not getattr(self.topology, "started", False):
                raise LifecycleError("Restricted egress topology did not verify as active")
            record["restricted_egress"] = {
                "status": gateway.get("status"),
                "allowed_destinations": gateway.get("allowed_destinations"),
                "tls_interception": gateway.get("tls_interception"),
                "remote_url_rewritten": gateway.get("remote_url_rewritten"),
                "network_isolation": gateway.get("network_isolation"),
                "topology_started_and_verified": True,
            }
            current_operation = "create_session"
            record["session_creation_attempted"] = True
            record["session_creation_uncertain"] = True
            record["session_creation_outcome"] = "attempted"
            session = self.client.create_session(context)
            session_id = session["session_id"]
            record["resolved_session"] = session.get("resolved_agent")
            record["session_created"] = True
            record["sessions_created_count"] = 1
            record["session_creation_uncertain"] = False
            refresh_client_state()
            state("create_session")

            def start_executor():
                nonlocal container_id, executor_cleanup_unverified, current_operation
                state("start_executor")
                record["executor_startup_attempted"] = True
                try:
                    started = self.runtime.start_managed_executor(
                        workspace,
                        environment_id=session["environment_id"],
                        remote_url=session["remote_url"],
                        environment_key=self.environment_key,
                        topology=self.topology,
                        proxy_ip=gateway["proxy_internal_ip"],
                    )
                except Exception as exc:
                    record["executor_startup_failed"] = True
                    executor_cleanup_unverified = bool(getattr(exc, "cleanup_unverified", False))
                    container_id = getattr(exc, "container_id", None)
                    raise
                container_id = started["container_id"]
                record["executor_process_started"] = True
                current_operation = "await_executor_connection"

            def connected():
                nonlocal stream_connected, deadline_timer
                stream_connected = True
                record["executor_connection_observed"] = True
                state("establish_connection")
                state("submit_task")
                # The HTTP client marks the attempt immediately before POST.
                # A connected event alone is not a task-submission attempt.

                def terminate_at_deadline():
                    deadline_expired.set()
                    record["deadline_expired"] = True
                    try:
                        deadline_termination_verified.append(
                            bool(container_id and self.runtime.stop_managed_executor(container_id))
                        )
                    except Exception:
                        deadline_termination_verified.append(False)

                deadline_timer = threading.Timer(self.trial_timeout_seconds, terminate_at_deadline)
                deadline_timer.daemon = True
                deadline_timer.start()

            def task_submitted():
                nonlocal current_operation
                if record["inference_submitted"]:
                    raise LifecycleError("Only one task submission is permitted for R01-A")
                record["inference_submitted"] = True
                record["task_submission_attempted"] = True
                record["task_submissions_attempted_count"] = 1
                record["task_submission_uncertain"] = False
                record["task_submission_outcome"] = "submitted"
                current_operation = "stream_events"

            state("stream_events")
            for event in self.client.send_and_stream(
                session_id,
                task_text,
                deadline_seconds=self.trial_timeout_seconds,
                on_stream_ready=start_executor,
                on_environment_connected=connected,
                on_task_submitted=task_submitted,
            ):
                record["events"].append(
                    contract.sanitize_reference_data(event, secrets=(self.environment_key,))
                )
                if event.get("type") == "agent.session.turn.completed":
                    turn_completed = True
                if event.get("type") in {
                    "agent.session.turn.completed",
                    "agent.session.turn.failed",
                    "agent.session.turn.cancelled",
                    "agent.session.failed",
                    "agent.session.environment.failed",
                    "error",
                }:
                    break
            if not stream_connected:
                raise LifecycleError("Executor connection was not observed")
            if deadline_expired.is_set():
                raise LifecycleError("Trial reached its hard execution deadline")
            if not turn_completed:
                raise LifecycleError("Agent turn did not complete successfully")
            state("finish")
        except BaseException as exc:
            primary_error = exc
            refresh_client_state()
            diagnostics = getattr(exc, "diagnostics", None)
            if isinstance(diagnostics, dict) and diagnostics.get("category") == "docker_runtime":
                record["failure"] = contract.project_runtime_diagnostics(diagnostics)
                record["failure"]["operation"] = current_operation
            elif isinstance(diagnostics, dict):
                # Only a small, provider-neutral allowlist is persisted. Never
                # serialize exception text, headers, body bytes, or remote URLs.
                record["failure"] = contract.sanitize_reference_data(
                    {
                        key: diagnostics.get(key)
                        for key in (
                            "operation",
                            "category",
                            "http_status",
                            "reason",
                            "reason_code",
                            "field",
                            "session_state",
                            "session_deleted_verified",
                            "cleanup_reason_code",
                        )
                        if diagnostics.get(key) is None
                        or isinstance(diagnostics.get(key), (str, int))
                    },
                    secrets=(self.environment_key,),
                )
            else:
                record["failure"] = {
                    "operation": current_operation,
                    "category": "local_validation"
                    if isinstance(exc, ValueError)
                    else "local_error",
                    "reason": f"{current_operation} failed before session creation"
                    if not record["session_creation_attempted"]
                    else "Lifecycle operation failed; details omitted",
                }
            if not record["failure"].get("operation"):
                record["failure"]["operation"] = current_operation
            record["failure_category"] = (
                record["failure"].get("category")
                if isinstance(diagnostics, dict)
                else type(exc).__name__
            )
            record["primary_failure_classification"] = record["failure_category"]
        finally:
            refresh_client_state()
            if deadline_timer is not None:
                deadline_timer.cancel()
                if deadline_timer.is_alive():
                    deadline_timer.join(timeout=25)
            if deadline_expired.is_set():
                record["deadline_termination_verified"] = bool(
                    deadline_termination_verified and deadline_termination_verified[-1]
                )
            if session_id and record["session_created"] and primary_error is not None:
                try:
                    self.client.cancel_turn(session_id)
                except Exception:
                    pass
            if container_id:
                try:
                    container_removed = self.runtime.stop_managed_executor(container_id)
                except Exception:
                    container_removed = False
            else:
                container_removed = not executor_cleanup_unverified
            if not container_removed:
                record["cleanup_failures"].append("container_removal_unverified")
            record["container_termination_verified"] = container_removed
            record["session_state"] = getattr(
                self.client,
                "session_state",
                "created"
                if record["session_created"]
                else "unknown"
                if record["session_creation_attempted"]
                else "not_started",
            )
            client_deletion_status = getattr(self.client, "session_deletion_verified", None)
            if client_deletion_status is not None:
                session_deleted = client_deletion_status is True
            elif session_id:
                try:
                    self.client.delete_session(session_id)
                    session_deleted = True
                except Exception:
                    session_deleted = False
            else:
                # A failed/ambiguous create with no usable session ID cannot
                # prove that no server-side session exists or was deleted.
                session_deleted = None if record["session_creation_uncertain"] else True
            client_close = getattr(self.client, "close", None)
            if callable(client_close):
                try:
                    client_close()
                except Exception:
                    session_deleted = False
            try:
                topology_removed = self.topology.cleanup()
            except Exception:
                topology_removed = False
            if session_deleted is False:
                record["cleanup_failures"].append("session_delete_unverified")
            if not topology_removed:
                record["cleanup_failures"].append("topology_cleanup_unverified")
            cleanup_ok = (
                container_removed
                and session_deleted is True
                and topology_removed
                and not record["session_creation_uncertain"]
            )
            record["cleanup_verified"] = cleanup_ok
            record["session_deleted_verified"] = session_deleted
            if session_deleted is True and record["session_created"]:
                record["session_state"] = "deleted"
            elif session_deleted is None or session_deleted is False:
                record["session_state"] = "unknown"
            record["topology_cleanup_verified"] = topology_removed

        if not record["cleanup_verified"] or not container_removed:
            if self.ledger.active_trial_id == "R01-A":
                state("checkpoint")
                try:
                    review = self.checkpoint_review(record)
                except (Exception, KeyboardInterrupt):
                    review = None
                if isinstance(review, dict):
                    record["checkpoint"] = self.ledger.checkpoint("R01-A", **review)
                else:
                    record["checkpoint"] = self.ledger.checkpoint(
                        "R01-A",
                        reported_spend_cents=None,
                        usage=None,
                        correctness_review=None,
                        remaining_balance_cents=None,
                        reconciled=False,
                        balance_source=None,
                        checked_at=None,
                    )
            lease.__exit__(type(primary_error) if primary_error else None, primary_error, None)
            failure = LifecycleError("Cleanup or executor termination could not be verified")
            failure.audit_record = record
            raise failure

        state("terminate_container")
        if primary_error is None:
            try:
                manifest = _load(
                    Path(__file__).parents[1] / "runner" / "bench.py", "r01_lifecycle_bench"
                )
                task = manifest.task_for("R01")
                validate_artifact_workspace(workspace, max_bytes=self.max_artifact_bytes)
                state("export_artifacts")
                with tempfile.TemporaryDirectory(prefix="r01a-sealed-") as directory:
                    sealed = Path(directory) / "sealed"
                    record["artifact_hashes"] = manifest.seal_artifacts("R01", workspace, sealed)
                    if set(record["artifact_hashes"]) != set(task["artifacts"]):
                        raise LifecycleError("Sealed artifact set differs from the task manifest")
                    state("score")
                    record["scoring"] = self.score("R01", sealed, self.frozen_r_image_id)
            except Exception as exc:
                primary_error = exc
                record["failure_category"] = type(exc).__name__
                record["status"] = "post_execution_step_failed_checkpoint_required"
        else:
            diagnostics = getattr(primary_error, "diagnostics", None)
            record["failure_category"] = (
                diagnostics.get("category")
                if isinstance(diagnostics, dict)
                else type(primary_error).__name__
            )
            record["status"] = "attempt_failed_checkpoint_required"

        if self.ledger.active_trial_id == "R01-A":
            state("checkpoint")
            try:
                review = self.checkpoint_review(record)
            except (Exception, KeyboardInterrupt):
                review = None
            if isinstance(review, dict):
                record["checkpoint"] = self.ledger.checkpoint("R01-A", **review)
            else:
                record["checkpoint"] = self.ledger.checkpoint(
                    "R01-A",
                    reported_spend_cents=None,
                    usage=None,
                    correctness_review=None,
                    remaining_balance_cents=None,
                    reconciled=False,
                    balance_source=None,
                    checked_at=None,
                )
        state("cleanup")
        if primary_error is None:
            checkpoint = record.get("checkpoint")
            record["status"] = (
                "completed_one_trial_checkpoint_unreconciled_stopped"
                if checkpoint and not checkpoint.get("reconciled")
                else "completed_one_trial_checkpoint_required_for_next"
            )
        record["automatic_next_trial_authorized"] = False
        lease.mark_cleanup_verified()
        lease.__exit__(type(primary_error) if primary_error else None, primary_error, None)
        return record
