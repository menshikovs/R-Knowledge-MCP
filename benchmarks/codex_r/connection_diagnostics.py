"""Payload-free connection evidence for the pinned Codex 0.163.0 runtime.

This is observation, not a readiness protocol. Only environment.connected from
the session stream establishes harness readiness. No URLs, IDs, bodies, free
text errors, prompts or model output are persisted here.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import UTC, datetime

import httpx

# Reviewed against rust-v0.163.0 exec-server/src/remote.rs and its submodules.
# Do not enable global info/debug: other targets may contain private payloads.
RUNTIME_LOG_FILTER = (
    "error,opentelemetry_sdk=off,opentelemetry_otlp=off,codex_exec_server::remote=info"
)
PHASES = frozenset(
    {
        "session_create_requested",
        "session_validated",
        "executor_start_requested",
        "executor_started",
        "sse_open_requested",
        "sse_headers_received",
        "sse_first_line",
        "session_snapshot",
        "environment_pending",
        "environment_connected",
        "environment_failed",
        "task_submit_requested",
        "task_submit_acknowledged",
        "connection_observation",
        "wait_finished",
        "cleanup_started",
        "cleanup_finished",
    }
)
OUTCOMES = frozenset(
    {
        "connected",
        "not_connected",
        "connection_rejected",
        "timeout",
        "cancelled",
        "unknown",
        "process_exited",
        "binding_mismatch",
    }
)
ERROR_CODES = frozenset(
    {
        "environment_connection_timeout",
        "authentication_error",
        "invalid_api_key",
        "permission_denied",
        "registration_conflict",
        "authentication_service_unavailable",
    }
)
RUNTIME_KINDS = frozenset({"http", "io", "tls", "protocol", "connection_closed", "other"})
REJECTIONS = frozenset(
    {
        "expired",
        "missing_role",
        "missing_expiry",
        "missing_signature",
        "missing_version",
        "missing_executor_registration_id",
        "unexpected_executor_registration_id",
        "malformed_query",
        "invalid_role",
        "invalid_expiry",
        "invalid_signature",
        "invalid_secret",
        "extra_query_param",
        "pod_draining",
        "unknown_route",
        "wrong_rendezvous_cluster",
        "route_unavailable",
    }
)


def failure_outcome(exc):
    if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
        return "cancelled"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    return "unknown"


def error_code(value):
    """Only documented/reviewed categorical values; never upstream messages."""
    if not isinstance(value, dict):
        return None
    code = value.get("code")
    return code if isinstance(code, str) and code in ERROR_CODES else None


def runtime_evidence(text):
    """Project bounded stderr, discarding raw lines. False means marker not observed."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text[-32768:])
    result = {
        "registration_completed": "Noise executor registration completed" in text,
        "rendezvous_connected": "Noise executor connected to rendezvous" in text,
        "registration_retry_observed": "Noise executor retrying uncommitted registry registration"
        in text,
        "path_alias_warning": "Refusing to create helper binaries under temporary dir" in text,
    }
    if "environment registry returned a different environment id" in text:
        result.update(outcome="binding_mismatch", error_kind="protocol")
    elif "environment registry returned unsupported security profile" in text:
        result.update(outcome="connection_rejected", error_kind="protocol")
    for line in text.splitlines():
        if "environment registry authentication failed (" in line:
            match = re.search(r"authentication failed \((401|403)\b", line)
            if match:
                result.update(outcome="connection_rejected", http_status=int(match[1]))
        if "Noise executor failed to connect to rendezvous" not in line:
            continue
        result["outcome"] = "not_connected"
        for field, allowed in (("error_kind", RUNTIME_KINDS), ("rejection_reason", REJECTIONS)):
            match = re.search(rf'\b{field}=(?:Some\()?"?([a-z_]+)', line)
            if match and match[1] in allowed:
                result[field] = match[1]
        match = re.search(r"\bhttp_status=(?:Some\()?(\d{3})\b", line)
        if match and 100 <= int(match[1]) <= 599:
            result["http_status"] = int(match[1])
            result["outcome"] = "connection_rejected"
        if 'io_error_kind=Some("timed_out")' in line or 'io_error_kind="timed_out"' in line:
            result["outcome"] = "timeout"
    return result


class ConnectionJournal:
    """Bounded, immediately flushed metadata, surviving cancellation before result.json."""

    def __init__(self, path, *, clock=time.monotonic):
        self.path, self.clock = path, clock
        self.started = self.previous = clock()
        self.rows = []
        self.lock = threading.Lock()
        self.write_failed = False

    def emit(self, phase, *, outcome=None, http_status=None, code=None, exception=None, **facts):
        if phase not in PHASES:
            raise ValueError("Unreviewed connection phase")
        with self.lock:
            if len(self.rows) >= 512:
                return
            current = self.clock()
            row = {
                "phase": phase,
                "checked_at": datetime.now(UTC).isoformat(),
                "elapsed_seconds": round(current - self.started, 3),
                "since_previous_seconds": round(current - self.previous, 3),
            }
            self.previous = current
            if outcome in OUTCOMES:
                row["outcome"] = outcome
            if type(http_status) is int and 100 <= http_status <= 599:
                row["http_status"] = http_status
            if isinstance(code, str) and code in ERROR_CODES:
                row["error_code"] = code
            if exception is not None:
                # A dynamic exception class name can itself contain private data.
                row["exception_type"] = next(
                    (
                        cls.__name__
                        for cls in (
                            KeyboardInterrupt,
                            GeneratorExit,
                            httpx.TimeoutException,
                            TimeoutError,
                            httpx.TransportError,
                            ValueError,
                            RuntimeError,
                        )
                        if isinstance(exception, cls)
                    ),
                    "Exception",
                )
            for name in (
                "session_matches",
                "environment_matches",
                "environment_status_present",
                "running",
                "registration_completed",
                "rendezvous_connected",
                "registration_retry_observed",
                "path_alias_warning",
            ):
                if type(facts.get(name)) is bool:
                    row[name] = facts[name]
            if type(facts.get("exit_code")) is int:
                row["exit_code"] = facts["exit_code"]
            for name, allowed in (("error_kind", RUNTIME_KINDS), ("rejection_reason", REJECTIONS)):
                if isinstance(facts.get(name), str) and facts[name] in allowed:
                    row[name] = facts[name]
            operation = facts.get("operation")
            if operation in {
                "startup_wait",
                "capture_executor",
                "delete_session",
                "remove_executor",
                "remove_network",
                "close_client",
                "remove_workspace",
            }:
                row["operation"] = operation
            if type(facts.get("confirmed")) is bool:
                row["confirmed"] = facts["confirmed"]
            self.rows.append(row)
            try:
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError:
                self.write_failed = True
