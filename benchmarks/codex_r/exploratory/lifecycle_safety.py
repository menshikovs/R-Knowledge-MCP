"""Offline-testable timing, private durable evidence and read-only inspection.

This module never authorizes, retries, contacts a service or starts Docker.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from pathlib import Path

BUDGETS = {
    "preparation": 60,
    "session_creation": 30,
    "startup": 45,
    "connection": 60,
    "task": 900,
    "task_submission": 15,
    "teardown": 60,
    "postprocess": 120,
    "review": 300,
}
OPERATIONS = frozenset(
    {
        "authorization_consumption",
        "trial_marker_create",
        "authorization_marker_create",
        "topology_start",
        "session_create",
        "executor_create",
        "executor_start",
        "task_submit",
        "cancellation",
        "executor_terminate",
        "session_delete",
        "topology_cleanup",
        "audit_persist",
        "lease_release",
        "image_version_probe",
    }
)
ATTEMPTS = {
    "R01-A/attempt-1",
    "R01-A/attempt-2",
    "R01-A/recovery-after-attempt-2",
    "R01-A/final-continuation",
}
CODES = frozenset(
    {
        "ok",
        "operation_failed",
        "deadline_expired",
        "write_failed",
        "cleanup_unverified",
        "cli_nonzero",
        "executable_unavailable",
        "command_os_error",
        "command_timeout",
        "output_limit",
        "invalid_inspection",
        "invalid_container_id",
        "executor_exited",
        "executor_not_running",
        "runtime_policy_rejected",
        "remote_url_rejected",
        "network_error",
        "tls_error",
        "http_rejection",
        "invalid_json",
        "response_schema_validation",
    }
)


class EvidenceError(RuntimeError):
    """Evidence is unavailable; existing state must be preserved and launch blocked."""


class PhaseTimeout(RuntimeError):
    def __init__(self, phase):
        super().__init__("Lifecycle phase deadline expired")
        self.phase = phase
        self.diagnostics = {
            "operation": phase,
            "category": "deadline_expired",
            "reason_code": "deadline_expired",
            "reason": "Lifecycle phase deadline expired",
            "deadline_phase": phase,
        }


def sync_directory(path: Path) -> bool:
    """No power-loss claim where directory fsync is unsupported (notably Windows)."""
    if os.name == "nt":
        return False
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def ensure_directory(path: Path, *, mode=0o700):
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    path.mkdir(mode=mode, parents=True, exist_ok=True)
    for created in reversed(missing):
        sync_directory(created.parent)


def private_write(path: Path, value: dict, *, exclusive=True):
    """Flush a private JSON file and parent metadata; never overwrite by default."""
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise EvidenceError("Linked evidence paths are forbidden")
    ensure_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
    # A partial write is evidence, not a reason to delete or silently replace the file.
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, indent=2, ensure_ascii=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    return sync_directory(path.parent)


class Journal:
    """One exclusive journal per EXISTING attempt; no reopen/resume writer API."""

    def __init__(
        self,
        state_directory,
        attempt_id,
        *,
        synthetic=False,
        write=os.write,
        fsync=os.fsync,
        transition_hook=None,
    ):
        if (
            not isinstance(attempt_id, str)
            or attempt_id not in ATTEMPTS
            or type(synthetic) is not bool
        ):
            raise EvidenceError("Unknown attempt identity")
        root = Path(state_directory).absolute() / "lifecycle-journals"
        if any(p.is_symlink() for p in (root, *root.parents)):
            raise EvidenceError("Linked journal paths are forbidden")
        ensure_directory(root)
        if os.name != "nt" and (root.stat().st_mode & 0o077):
            raise EvidenceError("Journal directory is not owner-only")
        self.directory_sync = sync_directory(root.parent)
        if not synthetic and (os.name == "nt" or not self.directory_sync):
            raise EvidenceError("Live evidence requires POSIX owner-only and directory fsync")
        self.path = root / (attempt_id.replace("/", "-") + ".jsonl")
        self.fd = os.open(
            self.path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_APPEND
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            self.directory_sync = sync_directory(root)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise EvidenceError("Journal directory entry could not be made durable") from None
        self.attempt_id, self.synthetic = attempt_id, synthetic
        self.sequence, self.previous = 0, "0" * 64
        self._lock = threading.Lock()
        self._write, self._fsync = write, fsync
        self._hook = transition_hook
        self.failed = False

    def append(self, operation, event, *, intent_seq=None, code="ok", cleanup_code=None):
        if operation not in OPERATIONS or event not in {"intent", "outcome"}:
            raise EvidenceError("Unknown journal transition")
        if (event == "intent" and intent_seq is not None) or (
            event == "outcome" and (type(intent_seq) is not int or intent_seq <= 0)
        ):
            raise EvidenceError("Invalid journal intent reference")
        if not isinstance(code, str) or code not in CODES:
            code = "operation_failed"
        cleanup_code = "cleanup_unverified" if cleanup_code == "cleanup_unverified" else None
        with self._lock:
            if self.failed:
                raise EvidenceError("Journal has an incomplete write")
            value = {
                "schema_version": 1,
                "record_type": "r01a_lifecycle_journal_not_benchmark_result",
                "synthetic": self.synthetic,
                "attempt_id": self.attempt_id,
                "seq": self.sequence + 1,
                "operation": operation,
                "event": event,
                "intent_seq": intent_seq,
                "code": code,
                "cleanup_code": cleanup_code,
                "previous_sha256": self.previous,
            }
            raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            try:
                if self._hook:
                    self._hook("before", value)
                written = self._write(self.fd, raw)
                if written != len(raw):
                    raise OSError("Incomplete journal write")
                self._fsync(self.fd)
                self.sequence += 1
                self.previous = hashlib.sha256(raw).hexdigest()
                if self._hook:
                    self._hook("after", value)
            except BaseException as exc:
                self.failed = True
                raise EvidenceError("Journal transition could not be made durable") from exc
            return self.sequence

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def inspect_journal(path):
    """Read-only, bounded validation; never repairs tails, markers, locks or sessions."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > (8 << 20):
        raise EvidenceError("Journal is unavailable, linked or oversized")
    if not stat.S_ISREG(path.stat().st_mode):
        raise EvidenceError("Journal is not a regular file")
    raw = path.read_bytes()
    pending, outcomes = {}, []
    previous, last = "0" * 64, 0
    invalid, incomplete, synthetic = False, bool(raw and not raw.endswith(b"\n")), None
    attempt = None
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        try:
            item = json.loads(line)
            expected = {
                "schema_version",
                "record_type",
                "synthetic",
                "attempt_id",
                "seq",
                "operation",
                "event",
                "intent_seq",
                "code",
                "cleanup_code",
                "previous_sha256",
            }
            if (
                set(item) != expected
                or item["schema_version"] != 1
                or item["record_type"] != "r01a_lifecycle_journal_not_benchmark_result"
                or type(item["synthetic"]) is not bool
                or item["attempt_id"] not in ATTEMPTS
                or type(item["seq"]) is not int
                or item["seq"] != last + 1
                or item["previous_sha256"] != previous
                or item["operation"] not in OPERATIONS
                or item["code"] not in CODES
                or item["cleanup_code"] not in (None, "cleanup_unverified")
                or (synthetic is not None and item["synthetic"] != synthetic)
                or (attempt is not None and item["attempt_id"] != attempt)
            ):
                raise ValueError
            synthetic = item["synthetic"]
            attempt = item["attempt_id"]
            if item["event"] == "intent" and item["intent_seq"] is None:
                pending[item["seq"]] = item["operation"]
            elif (
                item["event"] == "outcome"
                and type(item["intent_seq"]) is int
                and pending.get(item["intent_seq"]) == item["operation"]
            ):
                del pending[item["intent_seq"]]
                outcomes.append((item["operation"], item["code"]))
            else:
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            invalid = True
            break
        previous, last = hashlib.sha256(line).hexdigest(), item["seq"]
    return {
        "record_type": "r01a_read_only_recovery_inspection_not_benchmark_result",
        "synthetic": synthetic,
        "valid_records": last,
        "invalid_record": invalid,
        "incomplete_tail": incomplete,
        "pending_operations": sorted(set(pending.values())),
        "remote_session_state": "unknown",
        "provider_spending": "unknown",
        "final_audit_outcome_recorded": ("audit_persist", "ok") in outcomes,
        "lease_release_outcome_recorded": ("lease_release", "ok") in outcomes,
        "cleanup_proven_by_inspection": False,
        "automatic_recovery_permitted": False,
        "replay_permitted": False,
    }


class Flow:
    def __init__(self, phase, seconds, clock, *, parent=None):
        self.clock, self.phase = clock, phase
        self.deadline = clock() + seconds
        self.cancelled = False
        self.parent = parent
        self._lock = threading.RLock()

    def remaining(self):
        with self._lock:
            if self.parent is not None:
                self.parent.remaining()
            remaining = self.deadline - self.clock()
            if self.cancelled or remaining <= 0:
                self.cancelled = True
                raise PhaseTimeout(self.phase)
            return remaining

    def transition(self, phase, seconds):
        with self._lock:
            self.remaining()
            self.phase, self.deadline = phase, self.clock() + seconds


class LifecycleSafety:
    """A bounded caller plus sticky per-flow cancellation for late worker calls.

    Python cannot forcibly kill a blocked thread. Abandoned work always retains
    the lease and unknown outcome; side-effect gates prevent subsequent work.
    """

    def __init__(self, journal, *, task_seconds=900, clock=time.monotonic, wait=None, budgets=None):
        self.journal, self.clock = journal, clock
        self.budgets = dict(BUDGETS)
        for name, seconds in (budgets or {}).items():
            if name not in BUDGETS or not 0 < seconds <= BUDGETS[name]:
                raise ValueError("Timing budgets may only reduce reviewed caps")
            self.budgets[name] = seconds
        if not 0 < task_seconds <= 900:
            raise ValueError("Task cap is at most 900 seconds")
        self.budgets["task"] = min(task_seconds, self.budgets["task"])
        self.primary = Flow("preparation", self.budgets["preparation"], clock)
        self.teardown = None
        self._local = threading.local()
        self._teardown_lock = threading.Lock()
        self.wait = wait or (lambda done, seconds: done.wait(seconds))
        self.abandoned = False
        self.evidence_failed = False
        self.timeouts = []
        self.transitions = ["preparation"]

    def flow(self):
        return getattr(self._local, "flow", self.primary)

    def check(self):
        return self.flow().remaining()

    def transition(self, phase):
        self.flow().transition(phase, self.budgets[phase])
        self.transitions.append(phase)

    def timeout(self, cap):
        return min(cap, self.check())

    def io(self, fn, *, cap, phase=None):
        parent = self.flow()
        child = Flow(phase or parent.phase, min(cap, parent.remaining()), self.clock, parent=parent)
        return self.call(fn, flow=child)

    def call(self, fn, *, flow=None):
        selected = flow or self.flow()
        selected.remaining()
        done, result = threading.Event(), []

        def worker():
            self._local.flow = selected
            try:
                selected.remaining()
                result.append((True, fn()))
            except BaseException as exc:
                result.append((False, exc))
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        try:
            while not done.is_set():
                self.wait(done, min(selected.remaining(), 0.05))
            selected.remaining()
        except PhaseTimeout as exc:
            selected.cancelled = True
            if not done.is_set():
                self.abandoned = True
            self.timeouts.append(exc.phase)
            raise
        except BaseException:
            selected.cancelled = True
            if not done.is_set():
                self.abandoned = True
            raise
        success, value = result[0]
        if not success:
            raise value
        return value

    def effect(self, operation, fn):
        self.check()
        active = getattr(self._local, "effects", ())
        if operation in active:
            return fn()
        try:
            sequence = self.journal.append(operation, "intent")
        except EvidenceError:
            self.evidence_failed = True
            # Evidence loss must not prevent narrowly reviewed destructive cleanup.
            # It still blocks launch/replay and prevents cleanup certification.
            if operation in {
                "cancellation",
                "executor_terminate",
                "session_delete",
                "topology_cleanup",
            }:
                self.check()
                return fn()
            raise
        self._local.effects = (*active, operation)
        try:
            self.check()  # fsync itself may have consumed the remaining budget.
            value = fn()
        except BaseException as exc:
            diagnostics = getattr(exc, "diagnostics", {})
            code = (
                diagnostics.get("reason_code") or diagnostics.get("category") or "operation_failed"
            )
            try:
                self.journal.append(
                    operation,
                    "outcome",
                    intent_seq=sequence,
                    code=code,
                    cleanup_code=diagnostics.get("secondary_cleanup_failure"),
                )
            except EvidenceError:
                self.evidence_failed = True
            raise
        finally:
            self._local.effects = active
        try:
            cleanup_unverified = (
                operation
                in {"cancellation", "executor_terminate", "session_delete", "topology_cleanup"}
                and value is False
            )
            self.journal.append(
                operation,
                "outcome",
                intent_seq=sequence,
                code="cleanup_unverified" if cleanup_unverified else "ok",
                cleanup_code="cleanup_unverified" if cleanup_unverified else None,
            )
        except EvidenceError:
            self.evidence_failed = True
            raise
        return value

    def cleanup(self, operation, fn, *, cap):
        with self._teardown_lock:
            if self.teardown is None:
                self.teardown = Flow("teardown", self.budgets["teardown"], self.clock)
                self.transitions.append("teardown")
            seconds = min(cap, self.teardown.remaining())
            child = Flow("teardown", seconds, self.clock, parent=self.teardown)
        return self.call(lambda: self.effect(operation, fn), flow=child)

    def review(self, fn):
        self.transitions.append("review")
        return self.call(fn, flow=Flow("review", self.budgets["review"], self.clock))
