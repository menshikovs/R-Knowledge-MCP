"""Append-only JSONL writer for normalized benchmark events.

The recorder never raises into the benchmark: an event that fails schema validation is not
written and its problems are kept in ``invalid`` (bounded) so tests and reports can show it.
Only fields declared in ``schema.FIELDS`` can be written, and configured secrets are masked
in the serialized line as a last defence.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import schema

MAX_INVALID_RECORDS = 50


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _given(value, default):
    """An explicit value (even 0) wins; only a missing one is filled in."""
    return default() if value is None else value


class RunTelemetry:
    """Events of one benchmark run, written to ``<results>/telemetry.jsonl``."""

    FILENAME = "telemetry.jsonl"

    def __init__(self, directory, run_id, *, secrets=(), strict=False):
        self.path = Path(directory) / self.FILENAME
        self.run_id = run_id
        self.secrets = tuple(secret for secret in secrets if secret and len(secret) >= 8)
        self.strict = strict
        self.invalid: list[dict] = []
        self.redactions = 0
        self._origin = time.monotonic()
        self._lock = threading.Lock()

    def offset_ms(self) -> float:
        return round((time.monotonic() - self._origin) * 1000, 3)

    def emit(self, event_type, *, source="runner", **fields):
        """Write one run-level event (no trial or trace id)."""
        event = {
            "schema_version": schema.SCHEMA_VERSION,
            "event_type": event_type,
            "run_id": self.run_id,
            "timestamp_utc": _given(fields.pop("timestamp_utc", None), utc_timestamp),
            "monotonic_offset_ms": _given(fields.pop("monotonic_offset_ms", None), self.offset_ms),
            "clock": fields.pop("clock", "run"),
            "source": source,
            **fields,
        }
        return self.write(event)

    def write(self, event):
        problems = schema.validate_event(event)
        if problems:
            if len(self.invalid) < MAX_INVALID_RECORDS:
                self.invalid.append({"event_type": event.get("event_type"), "problems": problems})
            if self.strict:
                raise ValueError(f"invalid telemetry event: {problems}")
            return None
        line = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
        for secret in self.secrets:
            if secret in line:
                line = line.replace(secret, "[REDACTED]")
                self.redactions += 1
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")
        return event

    def trial(self, trial_id):
        return TrialRecorder(self, trial_id)


class TrialRecorder:
    """Events of one trial; owns the trial's trace_id and its call-id sequences."""

    def __init__(self, run: RunTelemetry, trial_id):
        self.run = run
        self.trial_id = trial_id
        self.trace_id = "trace-" + uuid.uuid4().hex[:16]
        self.events: list[dict] = []
        self.client_calls: list[dict] = []
        self.agent_calls: dict[str, dict] = {}
        self._agent_call_sequence = 0
        self._origin = time.monotonic()

    def offset_ms(self) -> float:
        return round((time.monotonic() - self._origin) * 1000, 3)

    def emit(self, event_type, *, source="runner", **fields):
        event = {
            "schema_version": schema.SCHEMA_VERSION,
            "event_type": event_type,
            "run_id": self.run.run_id,
            "trial_id": self.trial_id,
            "trace_id": self.trace_id,
            "timestamp_utc": _given(fields.pop("timestamp_utc", None), utc_timestamp),
            "monotonic_offset_ms": _given(fields.pop("monotonic_offset_ms", None), self.offset_ms),
            "clock": fields.pop("clock", "trial"),
            "source": source,
            **fields,
        }
        written = self.run.write(event)
        if written is not None:
            self.events.append(written)
        return written

    # -- calls observed by the runner while it consumes the agent event stream ------------
    def agent_tool_started(self, item_id, tool, tool_class, item_type, sequence=None):
        """Record a payload-free start for any tool item exposed by the agent stream."""
        if item_id is None:
            self._agent_call_sequence += 1
            key = f"anonymous-{self._agent_call_sequence}"
        else:
            key = item_id
        call = self.agent_calls.get(key)
        if call is None:
            if item_id is not None:
                self._agent_call_sequence += 1
            call = {
                "call_id": f"agent-call-{self._agent_call_sequence:04d}",
                "tool": tool,
                "tool_class": tool_class,
                "item_type": item_type,
                "sequence": self._agent_call_sequence,
            }
            self.agent_calls[key] = call
        self.emit(
            "agent.tool.started",
            source="agent_stream",
            call_id=call["call_id"],
            tool=call["tool"],
            tool_class=call["tool_class"],
            tool_sequence=call["sequence"],
            tool_outcome="unknown",
            agent_stream_sequence=sequence,
            agent_stream_item_type=call["item_type"],
        )
        return call["call_id"]

    def agent_tool_finished(self, item_id, tool, tool_class, item_type, outcome, sequence=None):
        """Record a terminal observation without retaining tool input or output."""
        if item_id is None:
            key = next((item for item in self.agent_calls if item.startswith("anonymous-")), None)
        else:
            key = item_id
        call = self.agent_calls.pop(key, None)
        if call is None:
            self._agent_call_sequence += 1
            call = {
                "call_id": f"agent-call-{self._agent_call_sequence:04d}",
                "tool": tool,
                "tool_class": tool_class,
                "item_type": item_type,
                "sequence": self._agent_call_sequence,
            }
        outcome = outcome if outcome in {"success", "error", "partial", "unknown"} else "unknown"
        event_type = "agent.tool.failed" if outcome == "error" else "agent.tool.completed"
        self.emit(
            event_type,
            source="agent_stream",
            call_id=call["call_id"],
            tool=call["tool"],
            tool_class=call["tool_class"],
            tool_sequence=call["sequence"],
            tool_outcome=outcome,
            agent_stream_sequence=sequence,
            agent_stream_item_type=call["item_type"],
        )
        return call["call_id"]

    def client_tool_started(self, item_id, tool):
        call_id = f"client-call-{len(self.client_calls) + 1:04d}"
        self.client_calls.append({"call_id": call_id, "tool": tool, "item_id": item_id})
        self.emit(
            "mcp.tool.started",
            source="agent_stream",
            call_id=call_id,
            tool=tool,
            client_item_id=item_id,
        )
        return call_id

    def client_tool_finished(self, item_id, tool, failed: bool | None):
        """``failed`` is the stream's own item status; unknown stays None."""
        call = next((c for c in self.client_calls if c["item_id"] == item_id), None)
        if call is None:
            # Only the terminal item was streamed: no start event is invented for it.
            call = {
                "call_id": f"client-call-{len(self.client_calls) + 1:04d}",
                "tool": tool,
                "item_id": item_id,
            }
            self.client_calls.append(call)
        call["is_error"] = failed
        return self.emit(
            "mcp.tool.failed" if failed is True else "mcp.tool.completed",
            source="agent_stream",
            call_id=call["call_id"],
            tool=tool,
            client_item_id=item_id,
            is_error=failed,
        )

    # -- calls recorded by the MCP server (parsed from its log after the trial) ------------
    def record_server_calls(self, calls):
        """Emit one terminal event per server-recorded call that has a server timestamp.

        A server call is linked to a client call only by position and only when both sides
        saw the same number of calls with the same tool names; the link is never confirmed
        because the SDK passes no call id to the server.
        """
        comparable = len(calls) == len(self.client_calls) and all(
            call.get("tool_name") == client["tool"]
            for call, client in zip(calls, self.client_calls, strict=False)
        )
        emitted = []
        for index, call in enumerate(calls):
            if call.get("timestamp_utc") is None or call.get("process_offset_ms") is None:
                continue  # A server without timestamps cannot be placed in time; no fake time.
            fields = {
                "tool": call["tool_name"],
                "server_call_number": call["call_number"],
                "is_error": call["status"] == "error",
                "duration_ms": call.get("duration_ms"),
                "request_bytes": call.get("request_bytes"),
                "result_bytes": call.get("response_bytes"),
                "result_tokens_estimate": call.get("response_tokens_estimate"),
                "error_codes": list(call.get("error_codes") or []),
                "correlation": "ordinal_unconfirmed" if comparable else "unmatched",
                "correlated_call_id": self.client_calls[index]["call_id"] if comparable else None,
            }
            for name in (
                "repository",
                "package",
                "function",
                "verification_status",
                "source_count",
                "partial",
                "version_mismatch",
                "output_truncated",
                "page_truncated",
                "structured_bytes",
                "text_content_bytes",
                "useful_bytes",
                "content_duplicates_structured",
                "argument_fingerprint",
                "repeat_kind",
                "repeat_count",
                "cache_hits",
                "cache_network_requests",
            ):
                if name in call:
                    fields[name] = call[name]
            event = self.emit(
                "mcp.tool.failed" if fields["is_error"] else "mcp.tool.completed",
                source="mcp_server",
                clock="server_process",
                call_id=f"server-call-{call['call_number']:04d}",
                timestamp_utc=call["timestamp_utc"],
                monotonic_offset_ms=call["process_offset_ms"],
                **fields,
            )
            if event is not None:
                emitted.append(event)
        return emitted


_active: TrialRecorder | None = None


def set_active(recorder: TrialRecorder | None) -> None:
    """The runner executes one trial at a time; cleanup helpers report to the active one."""
    global _active
    _active = recorder


def get_active() -> TrialRecorder | None:
    return _active
