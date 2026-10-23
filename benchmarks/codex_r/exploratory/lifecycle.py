"""Single authorized R01-A Managed Agents lifecycle controller.

Live execution is intentionally opt-in through a fresh, scoped authorization.
Unit and Docker integration tests inject synthetic controller responses and
must never produce benchmark records.
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import tempfile
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
safety_lib = _load(Path(__file__).with_name("lifecycle_safety.py"), "r01_lifecycle_safety")


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
        safety_factory=None,
        audit_writer=None,
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
        self.safety_factory = safety_factory
        self.audit_writer = audit_writer or safety_lib.private_write
        self._lease = None
        self._record = None

    def run_one(self, *, context: dict, authorization: dict, state_directory: Path) -> dict:
        if context.get("trial_id") != "R01-A" or context.get("expected_tools") != []:
            raise LifecycleError("Only the fixed R01-A baseline is supported")
        if self.synthetic_mode is not bool(getattr(self.client, "synthetic", False)):
            raise LifecycleError("Synthetic mode must match the controller client")
        if self.safety_factory:
            self.safety = self.safety_factory(state_directory, context, self.synthetic_mode)
        else:
            try:
                journal = safety_lib.Journal(
                    state_directory,
                    context.get("attempt_id", "R01-A/attempt-1"),
                    synthetic=self.synthetic_mode,
                )
            except safety_lib.EvidenceError as exc:
                raise LifecycleError(
                    "Lifecycle verification gates require durable private evidence"
                ) from exc
            self.safety = safety_lib.LifecycleSafety(
                journal, task_seconds=self.trial_timeout_seconds
            )
        for component in (self.client, self.runtime, self.topology):
            component.safety = self.safety
        failure = None
        record = None
        try:
            record = self._run_one(
                context=context, authorization=authorization, state_directory=state_directory
            )
        except BaseException as exc:
            failure = exc
            record = (
                getattr(exc, "audit_record", None)
                or self._record
                or {
                    "record_type": "synthetic_r01a_lifecycle_audit_not_benchmark_result"
                    if self.synthetic_mode
                    else "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
                    "synthetic": self.synthetic_mode,
                    "trial_id": "R01-A",
                    "attempt_id": context.get("attempt_id", "R01-A/attempt-1"),
                    "cleanup_verified": False,
                    "failure_category": "preparation_failed",
                    "failure": {
                        "operation": "preparation",
                        "category": "preparation_failed",
                        "reason_code": "deadline_expired"
                        if getattr(exc, "phase", None)
                        else "operation_failed",
                    },
                }
            )
            if not getattr(exc, "audit_record", None):
                record["cleanup_verified"] = False
                record["controller_secondary_failure"] = "local_controller_failure"
            record.setdefault("primary_failure_classification", record.get("failure_category"))
        record["deadline_transitions"] = list(self.safety.transitions)
        record["expired_phases"] = list(self.safety.timeouts)
        record["unfinished_operations_uncertain"] = self.safety.abandoned
        record["journal_directory_fsync_supported"] = self.safety.journal.directory_sync
        record["journal_reference"] = self.safety.journal.path.name
        record["automatic_next_trial_authorized"] = False
        record["evidence_commit_requires_journal"] = True
        try:
            inspection = safety_lib.inspect_journal(self.safety.journal.path)
            incomplete_evidence = bool(
                inspection["pending_operations"]
                or inspection["invalid_record"]
                or inspection["incomplete_tail"]
            )
        except (OSError, safety_lib.EvidenceError):
            incomplete_evidence = True
            self.safety.evidence_failed = True
        if incomplete_evidence:
            record["cleanup_verified"] = False
        if self.safety.abandoned or self.safety.evidence_failed:
            record["cleanup_verified"] = False
        try:
            sealed_record = contract.sanitize_reference_data(
                record, secrets=(self.environment_key, getattr(self.client, "_key", ""))
            )
            final_path = self.safety.journal.path.with_suffix(".audit.json")
            evidence_flow = safety_lib.Flow("postprocess", 60, self.safety.clock)
            self.safety.call(
                lambda: self.safety.effect(
                    "audit_persist", lambda: self.audit_writer(final_path, sealed_record)
                ),
                flow=evidence_flow,
            )
        except BaseException:
            record["cleanup_verified"] = False
            record["evidence_failure"] = "final_audit_not_durable"
            failure = failure or LifecycleError("Final audit could not be made durable")
        if self._lease is not None and record.get("cleanup_verified"):

            def release_lease():
                self._lease.mark_cleanup_verified()
                self._lease.__exit__(None, None, None)

            try:
                self.safety.call(
                    lambda: self.safety.effect("lease_release", release_lease),
                    flow=evidence_flow,
                )
            except BaseException:
                record["cleanup_verified"] = False
                record.setdefault("cleanup_failures", []).append("lease_release_unverified")
                failure = failure or LifecycleError("Lease release could not be made durable")
        record["unfinished_operations_uncertain"] = self.safety.abandoned
        record["expired_phases"] = list(self.safety.timeouts)
        if not self.safety.abandoned:
            self.safety.journal.close()
        if failure is not None or not record.get("cleanup_verified"):
            error = LifecycleError("Cleanup or executor termination/evidence requires review")
            error.audit_record = record
            raise error from failure
        return record

    def _run_one(self, *, context: dict, authorization: dict, state_directory: Path) -> dict:
        if context.get("trial_id") != "R01-A" or context.get("expected_tools") != []:
            raise LifecycleError("This controller accepts only the fixed R01-A baseline")
        if self.synthetic_mode is not bool(getattr(self.client, "synthetic", False)):
            raise LifecycleError("Synthetic mode must match the injected controller client")

        def prepare():
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
            return gates, workspace, task_text

        gates, workspace, task_text = self.safety.call(prepare)

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
        self._record = record
        session_id = container_id = None
        lease = self.lease_factory("R01-A")
        self._lease = lease
        lease.safety = self.safety
        lease_acquired = False
        session_deleted = False
        container_removed = False
        stream_connected = False
        turn_completed = False
        primary_error = None
        current_operation = "prepare"
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
            self.safety.call(lease.__enter__)
            lease_acquired = True
            state("prepare")
            current_operation = "consume_authorization"
            state("consume_authorization")
            self.safety.call(
                lambda: self.safety.effect(
                    "authorization_consumption",
                    lambda: self.consume_authorization(
                        authorization, context, state_directory, lease=lease
                    ),
                )
            )
            current_operation = "authorize"
            self.ledger.authorize_one(
                "R01-A",
                operator_authorized=True,
                estimated_spend_cents=self.estimated_spend_cents,
            )
            state("authorize")
            current_operation = "start_restricted_egress"
            gateway = self.safety.call(
                lambda: self.safety.effect("topology_start", self.topology.start)
            )
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
            self.safety.transition("session_creation")
            session = self.safety.call(
                lambda: self.safety.effect(
                    "session_create", lambda: self.client.create_session(context)
                )
            )
            session_id = session["session_id"]
            record["resolved_session"] = session.get("resolved_agent")
            record["session_created"] = True
            record["sessions_created_count"] = 1
            record["session_creation_uncertain"] = False
            refresh_client_state()
            state("create_session")

            def start_executor():
                nonlocal container_id, executor_cleanup_unverified, current_operation
                self.safety.check()
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
                self.safety.transition("connection")

            def connected():
                nonlocal stream_connected
                self.safety.check()
                self.safety.transition("task")
                stream_connected = True
                record["executor_connection_observed"] = True
                state("establish_connection")
                state("submit_task")

            def task_submitted():
                nonlocal current_operation
                self.safety.check()
                if record["inference_submitted"]:
                    raise LifecycleError("Only one task submission is permitted for R01-A")
                record["inference_submitted"] = True
                record["task_submission_attempted"] = True
                record["task_submissions_attempted_count"] = 1
                record["task_submission_uncertain"] = False
                record["task_submission_outcome"] = "submitted"
                current_operation = "stream_events"

            state("stream_events")
            self.safety.transition("startup")
            # Pass the executor credential to the production event sanitizer
            # without changing the public client streaming call contract.
            self.client._additional_sanitization_secrets = (self.environment_key,)
            events = self.client.send_and_stream(
                session_id,
                task_text,
                deadline_seconds=self.trial_timeout_seconds,
                on_stream_ready=start_executor,
                on_environment_connected=connected,
                on_task_submitted=task_submitted,
            )
            while True:
                try:
                    event = self.safety.call(lambda: next(events))
                except StopIteration:
                    break
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
            self.safety.check()
            if not turn_completed:
                raise LifecycleError("Agent turn did not complete successfully")
            state("finish")
        except BaseException as exc:
            primary_error = exc
            refresh_client_state()
            if getattr(exc, "diagnostics", {}).get("category") == "deadline_expired":
                record["expired_phase"] = exc.phase
                record["deadline_expired"] = exc.phase == "task"
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
            if (
                session_id is None
                and getattr(primary_error, "diagnostics", {}).get("category") == "deadline_expired"
            ):
                reported_id = getattr(self.client, "session_id_for_cleanup", None)
                if isinstance(reported_id, str) and re.fullmatch(
                    r"[A-Za-z0-9_-]{1,128}", reported_id
                ):
                    session_id = reported_id
            if (
                session_id
                and record["session_created"]
                and primary_error is not None
                and getattr(self.client, "session_deletion_verified", None) is not True
            ):
                try:
                    self.safety.cleanup(
                        "cancellation", lambda: self.client.cancel_turn(session_id), cap=10
                    )
                except Exception:
                    record["cleanup_failures"].append("cancellation_unverified")
            if container_id:
                try:
                    container_removed = self.safety.cleanup(
                        "executor_terminate",
                        lambda: self.runtime.stop_managed_executor(container_id),
                        cap=20,
                    )
                except Exception:
                    container_removed = False
            else:
                container_removed = not executor_cleanup_unverified
            if not container_removed:
                record["cleanup_failures"].append("container_removal_unverified")
            record["container_termination_verified"] = container_removed
            if record["deadline_expired"]:
                record["deadline_termination_verified"] = container_removed
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
                    self.safety.cleanup(
                        "session_delete", lambda: self.client.delete_session(session_id), cap=15
                    )
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
                    self.safety.cleanup("session_delete", client_close, cap=5)
                except Exception:
                    session_deleted = False
            try:
                topology_removed = self.safety.cleanup(
                    "topology_cleanup", self.topology.cleanup, cap=15
                )
            except Exception:
                topology_removed = False
            if session_deleted is False:
                record["cleanup_failures"].append("session_delete_unverified")
            if not topology_removed:
                record["cleanup_failures"].append("topology_cleanup_unverified")
            cleanup_ok = (
                lease_acquired
                and container_removed
                and session_deleted is True
                and topology_removed
                and not record["session_creation_uncertain"]
                and not self.safety.abandoned
                and not self.safety.evidence_failed
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
                    review = self.safety.review(lambda: self.checkpoint_review(record))
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
                self.safety.primary = safety_lib.Flow(
                    "postprocess", self.safety.budgets["postprocess"], self.safety.clock
                )

                def postprocess():
                    manifest = _load(
                        Path(__file__).parents[1] / "runner" / "bench.py", "r01_lifecycle_bench"
                    )
                    task = manifest.task_for("R01")
                    validate_artifact_workspace(workspace, max_bytes=self.max_artifact_bytes)
                    state("export_artifacts")
                    with tempfile.TemporaryDirectory(prefix="r01a-sealed-") as directory:
                        sealed = Path(directory) / "sealed"
                        record["artifact_hashes"] = manifest.seal_artifacts(
                            "R01", workspace, sealed
                        )
                        if set(record["artifact_hashes"]) != set(task["artifacts"]):
                            raise LifecycleError(
                                "Sealed artifact set differs from the task manifest"
                            )
                        self.safety.check()
                        state("score")
                        record["scoring"] = self.score("R01", sealed, self.frozen_r_image_id)

                self.safety.call(postprocess)
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
                review = self.safety.review(lambda: self.checkpoint_review(record))
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
        return record
