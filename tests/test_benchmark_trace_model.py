"""Synthetic, offline tests for deterministic observable trace spans."""

from benchmarks.codex_r.telemetry import trace_model


def event(event_type, offset, **fields):
    return {
        "schema_version": "1.2",
        "event_type": event_type,
        "run_id": "synthetic-run",
        "trial_id": "R02-A-1",
        "trace_id": "trace-synthetic0001",
        "timestamp_utc": f"2026-10-27T10:00:{int(offset // 1000):02d}Z",
        "monotonic_offset_ms": offset,
        "clock": "trial",
        "source": "runner",
        **fields,
    }


def nested_events():
    return [
        event("benchmark.trial.started", 0, task="R02", mode="with-mcp"),
        event("agent.session.created", 2),
        event(
            "provider.request.started",
            3,
            call_id="provider-session-create-1",
            provider_operation="session_create",
        ),
        event(
            "provider.response.received",
            8,
            call_id="provider-session-create-1",
            provider_operation="session_create",
            provider_status="success",
            duration_ms=5,
        ),
        event("agent.turn.started", 10, source="agent_stream"),
        event(
            "mcp.tool.started",
            20,
            source="agent_stream",
            call_id="client-call-0001",
            tool="get_function_docs",
        ),
        event(
            "mcp.tool.completed",
            25,
            source="agent_stream",
            call_id="client-call-0001",
            tool="get_function_docs",
            is_error=False,
        ),
        event(
            "mcp.tool.started",
            30,
            source="agent_stream",
            call_id="client-call-0002",
            tool="get_package",
        ),
        event(
            "mcp.tool.completed",
            37,
            source="agent_stream",
            call_id="client-call-0002",
            tool="get_package",
            is_error=False,
        ),
        event("agent.turn.completed", 70, source="agent_stream"),
        event("scorer.started", 80),
        event("scorer.completed", 91, scorer_status="completed"),
        event("benchmark.trial.completed", 100, status="scored", interrupted=False),
    ]


def test_nested_trace_has_stable_parented_spans_and_same_clock_durations():
    spans = trace_model.derive_spans(
        nested_events(),
        run_id="synthetic-run",
        trial_id="R02-A-1",
        trace_id="trace-synthetic0001",
    )
    again = trace_model.derive_spans(
        nested_events(),
        run_id="synthetic-run",
        trial_id="R02-A-1",
        trace_id="trace-synthetic0001",
    )
    assert [span["span_id"] for span in spans] == [span["span_id"] for span in again]
    assert trace_model.validate_trace_spans(spans) == []
    root = next(span for span in spans if span["span_kind"] == "trial")
    assert root["duration_ms"] == 100
    turn = next(span for span in spans if span["span_kind"] == "agent_turn")
    calls = [span for span in spans if span["span_kind"] == "mcp_tool"]
    assert len(calls) == 2
    assert all(span["parent_span_id"] == turn["span_id"] for span in calls)
    assert sorted(span["duration_ms"] for span in calls) == [5, 7]
    provider = next(span for span in spans if span["span_kind"] == "provider_request")
    assert provider["duration_ms"] == 5
    assert provider["status"] == "completed"


def test_partial_provider_telemetry_is_explicit_without_inventing_response():
    events = [
        event("benchmark.trial.started", 0, task="R02", mode="with-mcp"),
        event(
            "provider.request.started",
            3,
            call_id="provider-session-create-1",
            provider_operation="session_create",
        ),
        event("benchmark.trial.completed", 100, status="error", interrupted=False),
    ]
    spans = trace_model.derive_spans(
        events,
        run_id="synthetic-run",
        trial_id="R02-A-1",
        trace_id="trace-synthetic0001",
    )
    provider = next(span for span in spans if span["span_kind"] == "provider_request")
    assert provider["status"] == "partial"
    assert provider["timestamp_end_utc"] is None
    assert trace_model.validate_trace_spans(spans) == []


def test_trial_timeout_has_its_own_trace_status():
    spans = trace_model.derive_spans(
        [
            event("benchmark.trial.started", 0, task="R02", mode="with-mcp"),
            event("benchmark.trial.completed", 100, status="timed_out", interrupted=False),
        ],
        run_id="synthetic-run",
        trial_id="R02-A-1",
        trace_id="trace-synthetic0001",
    )
    root = next(span for span in spans if span["span_kind"] == "trial")
    assert root["status"] == "timed_out"
    assert trace_model.validate_trace_spans(spans) == []


def test_integrity_rejects_duplicate_ids_missing_parents_cycles_and_bad_time():
    root = {
        "span_id": "span-000000000000000000000001",
        "parent_span_id": None,
        "status": "completed",
        "clock": "trial",
        "start_offset_ms": 0,
        "end_offset_ms": 10,
        "duration_ms": 10,
        "timestamp_start_utc": "invalid",
        "timestamp_end_utc": "2026-10-27T10:00:00Z",
    }
    child = {
        "span_id": "span-000000000000000000000001",
        "parent_span_id": "span-ffffffffffffffffffffffff",
        "status": "unknown",
        "clock": "trial",
        "start_offset_ms": 11,
        "end_offset_ms": 10,
        "duration_ms": -1,
        "timestamp_start_utc": None,
        "timestamp_end_utc": None,
    }
    problems = trace_model.validate_trace_spans([root, child])
    assert "duplicate_span_id:span-000000000000000000000001" in problems
    assert "span_0_invalid_timestamp_start_utc" in problems
    assert "span_1_missing_parent" in problems
    assert "span_1_invalid_duration" in problems
    assert "span_1_invalid_event_order" in problems

    first = {
        **child,
        "span_id": "span-000000000000000000000002",
        "parent_span_id": "span-000000000000000000000003",
        "duration_ms": 1,
        "start_offset_ms": 1,
        "end_offset_ms": 2,
    }
    second = {
        **first,
        "span_id": "span-000000000000000000000003",
        "parent_span_id": "span-000000000000000000000002",
    }
    assert any(
        code.startswith("parent_cycle:")
        for code in trace_model.validate_trace_spans([first, second])
    )


def test_trace_completeness_keeps_missing_telemetry_distinct():
    assert (
        trace_model.trace_completeness([], jsonl_present=False, jsonl_complete=False)
        == "unavailable"
    )
    assert trace_model.trace_completeness([], jsonl_present=True, jsonl_complete=False) == "partial"
    assert (
        trace_model.trace_completeness(nested_events(), jsonl_present=True, jsonl_complete=True)
        == "complete"
    )
