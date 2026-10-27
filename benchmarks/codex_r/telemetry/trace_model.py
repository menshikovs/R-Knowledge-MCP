"""Bounded, deterministic spans derived from observable benchmark events."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime

TRACE_MODEL_VERSION = "1.0"
TRACE_STATUSES = frozenset(
    {
        "observed",
        "completed",
        "failed",
        "interrupted",
        "partial",
        "running",
        "timed_out",
        "unknown",
    }
)
_ID = re.compile(r"span-[0-9a-f]{24}\Z")
_START_TO_TERMINAL = {
    "agent.turn.started": {"agent.turn.completed", "agent.turn.failed"},
    "agent.tool.started": {"agent.tool.completed", "agent.tool.failed"},
    "mcp.tool.started": {"mcp.tool.completed", "mcp.tool.failed"},
    "scorer.started": {"scorer.completed"},
    "cleanup.started": {"cleanup.completed", "cleanup.failed"},
    "provider.request.started": {"provider.response.received", "provider.request.failed"},
}


def _event_and_id(item: dict | tuple) -> tuple[str, dict]:
    if isinstance(item, tuple) and len(item) == 2:
        event_id, event = item
        if isinstance(event_id, str) and isinstance(event, dict):
            return event_id, event
    event = item
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), event


def _span_id(run_id: str, trial_id: str, trace_id: str, kind: str, key: str) -> str:
    source = "\0".join((run_id, trial_id, trace_id, kind, key))
    return "span-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def _finite_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _utc(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None


def _sort_key(item):
    event_id, event = item
    offset = event.get("monotonic_offset_ms")
    return (
        event.get("clock", ""),
        offset if _finite_number(offset) else float("inf"),
        event_id,
    )


def _span_row(
    *,
    run_id,
    trial_id,
    trace_id,
    kind,
    key,
    events,
    parent_span_id,
    status,
    verification_status="derived_from_observations",
):
    first_id, first = events[0]
    last_id, last = events[-1]
    start_item = next(
        (item for item in events if item[1].get("event_type") in _START_TO_TERMINAL), None
    )
    if kind == "trial":
        start_item = next(
            (item for item in events if item[1].get("event_type") == "benchmark.trial.started"),
            None,
        )
    terminal_types = set().union(*_START_TO_TERMINAL.values()) | {"benchmark.trial.completed"}
    end_item = next(
        (item for item in reversed(events) if item[1].get("event_type") in terminal_types), None
    )
    if kind == "trial":
        end_item = next(
            (
                item
                for item in reversed(events)
                if item[1].get("event_type") == "benchmark.trial.completed"
            ),
            None,
        )
    start_event = start_item[1] if start_item else None
    end_event = end_item[1] if end_item else None
    point_types = {
        "agent_session",
        "tool_exposure",
        "mcp_discovery",
        "evidence_observation",
        "answer_projection",
        "artifact_export",
        "telemetry_event",
    }
    if kind in point_types and len(events) == 1:
        start_event = end_event = first
    clock = (start_event or end_event or first).get("clock")
    start_offset = (start_event or {}).get("monotonic_offset_ms")
    end_offset = (end_event or {}).get("monotonic_offset_ms")
    duration = None
    if start_offset is not None and end_offset is not None:
        if (start_event or {}).get("clock") == (end_event or {}).get("clock"):
            duration = round(end_offset - start_offset, 3)
    if duration is None and end_event and _finite_number(end_event.get("duration_ms")):
        duration = round(end_event["duration_ms"], 3)
    event_types = [event.get("event_type") for _, event in events]
    event_type = "benchmark.trial" if kind == "trial" else event_types[-1]
    source = (start_event or end_event or first).get("source", "runner")
    span_id = _span_id(run_id, trial_id, trace_id, kind, key)
    tool_name = next((event.get("tool") for _, event in events if event.get("tool")), None)
    call_id = next((event.get("call_id") for _, event in events if event.get("call_id")), None)
    return {
        "run_id": run_id,
        "trial_id": trial_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "span_kind": kind,
        "event_type": event_type,
        "status": status,
        "capture_source": source,
        "verification_status": verification_status,
        "timestamp_start_utc": (start_event or {}).get("timestamp_utc"),
        "timestamp_end_utc": (end_event or {}).get("timestamp_utc"),
        "clock": clock,
        "start_offset_ms": start_offset,
        "end_offset_ms": end_offset,
        "duration_ms": duration,
        "call_id": call_id,
        "tool_name": tool_name,
        "event_ids_json": json.dumps([event_id for event_id, _ in events], separators=(",", ":")),
        "_events": events,
        "_key": key,
    }


def derive_spans(events, *, run_id: str, trial_id: str, trace_id: str) -> list[dict]:
    """Build stable lifecycle spans without correlating across independent clocks."""
    items = [(_event_and_id(item)) for item in events]
    items = [item for item in items if item[1].get("trial_id") == trial_id]
    items.sort(key=_sort_key)
    starts = [item for item in items if item[1].get("event_type") == "benchmark.trial.started"]
    ends = [item for item in items if item[1].get("event_type") == "benchmark.trial.completed"]
    root_events = starts[:1] + ends[-1:]
    if not root_events:
        root_events = items[:1]
    root_status = "partial"
    if ends:
        terminal = ends[-1][1]
        if terminal.get("interrupted"):
            root_status = "interrupted"
        elif terminal.get("status") in {"timeout", "timed_out"}:
            root_status = "timed_out"
        elif terminal.get("status") in {"error", "failed"}:
            root_status = "failed"
        else:
            root_status = "completed"
    root = _span_row(
        run_id=run_id,
        trial_id=trial_id,
        trace_id=trace_id,
        kind="trial",
        key="trial-lifecycle",
        events=root_events,
        parent_span_id=None,
        status=root_status,
    )
    root_id = root["span_id"]
    rows = [root]
    consumed = {event_id for event_id, _ in root_events}

    grouped: dict[tuple, list[tuple[str, dict]]] = {}
    point_events: list[tuple[str, dict]] = []
    turn_number = 0
    turn_active = None
    for item in items:
        event_id, event = item
        event_type = event.get("event_type")
        if event_id in consumed:
            continue
        if event_type in {"benchmark.trial.started", "benchmark.trial.completed"}:
            continue
        if event_type in {"agent.turn.started", "agent.turn.completed", "agent.turn.failed"}:
            if event_type == "agent.turn.started":
                turn_number += 1
                turn_active = turn_number
            elif turn_active is None:
                turn_number += 1
                turn_active = turn_number
            grouped.setdefault(("agent_turn", "runner-turn", str(turn_active)), []).append(item)
            if event_type in {"agent.turn.completed", "agent.turn.failed"}:
                turn_active = None
            continue
        if event_type in {
            "provider.request.started",
            "provider.response.received",
            "provider.request.failed",
        }:
            identity = event.get("call_id") or event.get("provider_operation") or "provider"
            grouped.setdefault(
                ("provider_request", event.get("source", "runner"), str(identity)), []
            ).append(item)
            continue
        if event_type in _START_TO_TERMINAL or any(
            event_type in terminals for terminals in _START_TO_TERMINAL.values()
        ):
            if event_type.startswith("agent.tool."):
                kind = "agent_tool"
            elif event_type.startswith("mcp.tool."):
                kind = "mcp_tool"
            elif event_type.startswith("scorer."):
                kind = "evaluation"
            else:
                kind = "cleanup"
            identity = event.get("call_id") or event.get("cleanup_operation") or "singleton"
            grouped.setdefault((kind, event.get("source", "runner"), str(identity)), []).append(
                item
            )
            continue
        if event_type == "agent.session.created":
            grouped.setdefault(
                ("agent_session", event.get("source", "runner"), "session"), []
            ).append(item)
            continue
        point_events.append(item)

    for (kind, source, identity), grouped_events in grouped.items():
        group_events = sorted(grouped_events, key=_sort_key)
        if kind == "agent_turn":
            start_names, terminal_names = (
                {"agent.turn.started"},
                {
                    "agent.turn.completed",
                    "agent.turn.failed",
                },
            )
        elif kind == "agent_tool":
            start_names, terminal_names = (
                {"agent.tool.started"},
                {
                    "agent.tool.completed",
                    "agent.tool.failed",
                },
            )
        elif kind == "mcp_tool":
            start_names, terminal_names = (
                {"mcp.tool.started"},
                {
                    "mcp.tool.completed",
                    "mcp.tool.failed",
                },
            )
        elif kind == "evaluation":
            start_names, terminal_names = {"scorer.started"}, {"scorer.completed"}
        elif kind == "provider_request":
            start_names, terminal_names = (
                {"provider.request.started"},
                {
                    "provider.response.received",
                    "provider.request.failed",
                },
            )
        else:
            start_names, terminal_names = (
                {"cleanup.started"},
                {
                    "cleanup.completed",
                    "cleanup.failed",
                },
            )
        first_start = next((e for _, e in group_events if e.get("event_type") in start_names), None)
        terminal = next(
            (
                (event_id, e)
                for event_id, e in reversed(group_events)
                if e.get("event_type") in terminal_names
            ),
            None,
        )
        if kind == "agent_session":
            span_status = "observed"
        elif terminal and first_start is None:
            span_status = "partial"
        elif not terminal:
            span_status = "partial"
        elif terminal[1].get("event_type", "").endswith("failed") or terminal[1].get("is_error"):
            span_status = "failed"
        elif terminal[1].get("cleanup_status") == "failed":
            span_status = "failed"
        elif terminal[1].get("interrupted"):
            span_status = "interrupted"
        else:
            span_status = "completed"
        key = f"{source}:{identity}:{group_events[0][0]}"
        row = _span_row(
            run_id=run_id,
            trial_id=trial_id,
            trace_id=trace_id,
            kind=kind,
            key=key,
            events=group_events,
            parent_span_id=root_id,
            status=span_status,
        )
        if kind in {"agent_tool", "mcp_tool"}:
            call_events = [e for _, e in group_events]
            call_start = next((e for e in call_events if e.get("event_type") in start_names), None)
            row["parent_span_id"] = next(
                (
                    candidate["span_id"]
                    for candidate in rows
                    if candidate["span_kind"] == "agent_turn"
                    and candidate.get("clock") == row.get("clock")
                    and call_start
                    and _finite_number(call_start.get("monotonic_offset_ms"))
                    and _finite_number(candidate.get("start_offset_ms"))
                    and call_start["monotonic_offset_ms"] >= candidate["start_offset_ms"]
                    and (
                        candidate.get("end_offset_ms") is None
                        or call_start["monotonic_offset_ms"] <= candidate["end_offset_ms"]
                    )
                ),
                root_id,
            )
        rows.append(row)

    for event_id, event in point_events:
        event_type = event.get("event_type", "")
        if event_type.startswith("mcp.exposure"):
            kind = "tool_exposure"
        elif event_type.startswith("mcp.discovery"):
            kind = "mcp_discovery"
        elif event_type.startswith("agent.evidence") or event_type.startswith("agent.url"):
            kind = "evidence_observation"
        elif event_type.startswith("agent.answer"):
            kind = "answer_projection"
        elif event_type.startswith("artifact.export"):
            kind = "artifact_export"
        else:
            kind = "telemetry_event"
        row = _span_row(
            run_id=run_id,
            trial_id=trial_id,
            trace_id=trace_id,
            kind=kind,
            key=f"{event_id}:{event_type}",
            events=[(event_id, event)],
            parent_span_id=root_id,
            status="observed",
            verification_status="direct_observation",
        )
        row["event_type"] = event_type
        rows.append(row)

    for row in rows:
        row.pop("_events", None)
        row.pop("_key", None)
    return rows


def validate_trace_spans(spans: list[dict]) -> list[str]:
    """Return stable integrity error codes; partial lifecycles remain representable."""
    problems: list[str] = []
    by_id: dict[str, dict] = {}
    duplicates: set[str] = set()
    for index, span in enumerate(spans):
        if not isinstance(span, dict):
            problems.append(f"span_{index}_not_object")
            continue
        span_id = span.get("span_id")
        if not isinstance(span_id, str) or not _ID.fullmatch(span_id):
            problems.append(f"span_{index}_invalid_id")
        elif span_id in by_id:
            duplicates.add(span_id)
        else:
            by_id[span_id] = span
        if span.get("status") not in TRACE_STATUSES:
            problems.append(f"span_{index}_invalid_status")
        duration = span.get("duration_ms")
        if duration is not None and (not _finite_number(duration) or duration < 0):
            problems.append(f"span_{index}_invalid_duration")
        for field in ("timestamp_start_utc", "timestamp_end_utc"):
            value = span.get(field)
            if value is not None and _utc(value) is None:
                problems.append(f"span_{index}_invalid_{field}")
        clock = span.get("clock")
        start, end = span.get("start_offset_ms"), span.get("end_offset_ms")
        if start is not None and (not _finite_number(start) or start < 0):
            problems.append(f"span_{index}_invalid_start_offset")
        if end is not None and (not _finite_number(end) or end < 0):
            problems.append(f"span_{index}_invalid_end_offset")
        if clock is not None and start is not None and end is not None and start > end:
            problems.append(f"span_{index}_invalid_event_order")
    problems.extend(f"duplicate_span_id:{span_id}" for span_id in sorted(duplicates))
    for index, span in enumerate(spans):
        if not isinstance(span, dict):
            continue
        parent_id = span.get("parent_span_id")
        if parent_id is not None and parent_id not in by_id:
            problems.append(f"span_{index}_missing_parent")
            continue
        parent = by_id.get(parent_id)
        if parent is None or span.get("clock") != parent.get("clock"):
            continue
        child_start, child_end = span.get("start_offset_ms"), span.get("end_offset_ms")
        parent_start, parent_end = parent.get("start_offset_ms"), parent.get("end_offset_ms")
        if (
            _finite_number(child_start)
            and _finite_number(parent_start)
            and child_start < parent_start
        ):
            problems.append(f"span_{index}_starts_before_parent")
        if _finite_number(child_end) and _finite_number(parent_end) and child_end > parent_end:
            problems.append(f"span_{index}_ends_after_parent")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(span_id):
        if span_id in visiting:
            problems.append(f"parent_cycle:{span_id}")
            return
        if span_id in visited:
            return
        visiting.add(span_id)
        parent_id = by_id[span_id].get("parent_span_id")
        if parent_id in by_id:
            visit(parent_id)
        visiting.remove(span_id)
        visited.add(span_id)

    for span_id in by_id:
        visit(span_id)
    return sorted(set(problems))


def trace_completeness(events, *, jsonl_present: bool, jsonl_complete: bool) -> str:
    if not jsonl_present:
        return "unavailable"
    event_values = [event for _, event in map(_event_and_id, events)]
    started = any(event.get("event_type") == "benchmark.trial.started" for event in event_values)
    completed = [
        event for event in event_values if event.get("event_type") == "benchmark.trial.completed"
    ]
    if not jsonl_complete or not started or not completed:
        return "partial"
    if completed[-1].get("interrupted"):
        return "partial"
    return "complete"
