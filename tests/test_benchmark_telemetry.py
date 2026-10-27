"""Normalized benchmark telemetry: JSONL events, error taxonomy and MCP metrics (offline)."""

import json
import logging
import sys

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent

from benchmarks.codex_r import run_simple as simple
from benchmarks.codex_r.telemetry import aggregate, errors, experiment, projection, recorder, schema
from cran_knowledge_mcp.server import create_server
from cran_knowledge_mcp.telemetry import RepeatTracker, result_signals

RUN = "20260101T000000Z-unit"
NL = chr(10)
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Runner uses POSIX signals")


def new_trial(tmp_path, trial_id="D01-B-1", **kwargs):
    run = recorder.RunTelemetry(tmp_path, RUN, strict=True, **kwargs)
    return run, run.trial(trial_id)


def server_call(number, tool="get_function_docs", status="ok", **extra):
    """A normalized server call as parse_mcp_call_telemetry returns it."""
    call = {
        "tool_name": tool,
        "call_number": number,
        "status": status,
        "duration_ms": 10.0 * number,
        "request_bytes": 100,
        "response_bytes": 1000 * number,
        "response_tokens_estimate": 250 * number,
        "error_codes": ["docs_not_found"] if status == "error" else [],
        "timestamp_utc": f"2026-01-01T00:00:{number:02d}.000Z",
        "process_offset_ms": 1000.0 * number,
    }
    call.update(extra)
    return call


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# 1. valid JSONL and required fields ---
def test_jsonl_lines_are_valid_versioned_and_have_required_fields(tmp_path):
    run, trial = new_trial(tmp_path)
    run.emit("benchmark.run.started", trial_count=1)
    trial.emit("benchmark.trial.started", task="D01", mode="with-mcp", model="gpt-6-luna")
    trial.emit("agent.session.created")
    trial.record_server_calls([server_call(1, package="climenu", repository="cran")])
    events = read_events(run.path)
    assert [event["event_type"] for event in events] == [
        "benchmark.run.started",
        "benchmark.trial.started",
        "agent.session.created",
        "mcp.tool.completed",
    ]
    for event in events:
        assert event["schema_version"] == schema.SCHEMA_VERSION == "1.2"
        assert schema.validate_event(event) == []
        assert schema.COMMON_REQUIRED <= set(event)
        assert schema.REQUIRED[event["event_type"]] <= set(event)
    assert set(schema.EVENT_TYPES) >= {event["event_type"] for event in events}
    assert schema.validate_stream(events) == []


def test_provider_session_creation_events_capture_local_request_latency(monkeypatch):
    run = recorder.RunTelemetry(".", RUN, strict=True)
    monkeypatch.setattr(run, "write", lambda event: event)
    trial = run.trial("D01-B-1")
    started = trial.emit(
        "provider.request.started",
        call_id="provider-session-create-0001",
        provider_operation="session_create",
    )
    response = trial.emit(
        "provider.response.received",
        call_id="provider-session-create-0001",
        provider_operation="session_create",
        provider_status="success",
        duration_ms=4.25,
    )
    events = trial.events
    assert started["schema_version"] == response["schema_version"] == "1.2"
    assert all(schema.validate_event(event) == [] for event in events)
    assert schema.validate_stream(events) == []
    assert response["duration_ms"] == 4.25


def test_unknown_client_tool_terminal_does_not_become_success(monkeypatch):
    run = recorder.RunTelemetry(".", RUN, strict=True)
    monkeypatch.setattr(run, "write", lambda event: event)
    trial = run.trial("D01-B-1")
    trial.client_tool_started("item-1", "get_package")
    terminal = trial.client_tool_finished("item-1", "get_package", None)
    assert terminal["event_type"] == "mcp.tool.completed"
    assert terminal["is_error"] is None
    assert schema.validate_event(terminal) == []


def test_schema_rejects_unknown_fields_bad_values_and_missing_fields(tmp_path):
    run = recorder.RunTelemetry(tmp_path, RUN)  # non-strict: invalid events are dropped
    trial = run.trial("D01-B-1")
    assert (
        trial.emit("mcp.tool.started", call_id="c1", tool="get_package", arguments={"x": 1}) is None
    )
    assert trial.emit("mcp.tool.started", call_id="c1") is None
    assert trial.emit("mcp.tool.failed", call_id="c1", tool="t", is_error=False) is None
    assert trial.emit("benchmark.nonexistent") is None
    assert not run.path.exists() and len(run.invalid) == 4
    assert any("unknown field: arguments" in p for p in run.invalid[0]["problems"])
    assert schema.validate_event({"event_type": "x"})
    assert schema.validate_event("not an object") == ["event must be an object"]


def test_agent_evidence_telemetry_is_closed_bounded_and_separates_answer_urls(tmp_path):
    run, trial = new_trial(tmp_path)
    exposure = trial.emit(
        "mcp.exposure.configured",
        toolset="consolidated",
        function_discovery_policy="enabled",
        registered_tools=["get_package", "list_package_functions"],
        policy_allowed_tools=["get_package", "list_package_functions"],
        configured_allowed_tools=["get_package", "list_package_functions"],
        generated_agent_tool_names=["get_package", "list_package_functions"],
        remote_discovery_status="unknown",
        remote_discovered_tools=None,
        session_config_status="generated",
    )
    assert exposure is not None
    assert (
        trial.emit(
            "mcp.exposure.response",
            source="agents_api",
            session_config_status="response_echo_observed",
            returned_agent_tool_names=["get_package", "list_package_functions"],
            session_config_match=True,
        )
        is not None
    )
    state = projection.new_client_state()
    request = {
        "type": "agent.session.turn.item.added",
        "sequence_number": 11,
        "item": {
            "id": "item-1",
            "type": "mcp_tool_call",
            "name": "get_package",
            "status": "in_progress",
            "arguments": {"package": "termr"},
        },
    }
    response = {
        "structuredContent": {
            "package": "termr",
            "version": "1.0.1",
            "repository": "CRAN",
            "verification_status": "verified",
            "sources": ["https://cran.r-project.org/package=termr"],
        },
        "content": [],
    }
    completed = {
        "type": "agent.session.turn.item.done",
        "sequence_number": 14,
        "item": {
            **request["item"],
            "status": "completed",
            "result": response,
            "arguments": {"secret": "sk-test-secret-canary-123456789"},
        },
    }
    simple.observe_stream_event(trial, {}, request, state)
    simple.observe_stream_event(trial, {}, completed, state)
    answer = tmp_path / "answer.json"
    answer.write_text(
        json.dumps(
            {
                "rationale": "private rationale must not enter telemetry",
                "recommendations": [
                    {
                        "package": "termr",
                        "version": "0.1.0",
                        "source_url": "https://cran.r-project.org/package=termr",
                        "documentation_url": "https://cran.r-project.org/web/packages/termr/termr.pdf",
                        "feature_ids": ["reactive_terminal_ui"],
                        "caveat_ids": ["some_apis_experimental"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    simple.emit_answer_projection(trial, answer)
    events = read_events(run.path)
    assert schema.validate_stream(events) == []
    tool = [event for event in events if event["event_type"] == "agent.tool.completed"]
    assert len(tool) == 1
    assert tool[0]["tool_class"] == "mcp" and tool[0]["tool_outcome"] == "success"
    evidence = [event for event in events if event["event_type"] == "agent.evidence.observed"]
    assert len(evidence) == 1
    assert evidence[0]["package"] == "termr" and evidence[0]["package_version"] == "1.0.1"
    urls = [event for event in events if event["event_type"] == "agent.url.mentioned"]
    assert [event["source_access_status"] for event in urls] == [
        "mcp_response_observed",
        "url_mention_only",
        "url_mention_only",
    ]
    serialized = run.path.read_text(encoding="utf-8")
    assert "private rationale" not in serialized
    assert "sk-test-secret-canary-123456789" not in serialized


def test_non_mcp_tool_urls_are_not_mislabeled_as_access(tmp_path):
    run, trial = new_trial(tmp_path)
    state = projection.new_client_state()
    simple.observe_stream_event(
        trial,
        {},
        {
            "type": "agent.session.turn.item.added",
            "sequence_number": 5,
            "item": {
                "id": "exec-1",
                "type": "command_execution",
                "status": "in_progress",
            },
        },
        state,
    )
    simple.observe_stream_event(
        trial,
        {},
        {
            "type": "agent.session.turn.item.done",
            "sequence_number": 6,
            "item": {
                "id": "exec-1",
                "type": "command_execution",
                "status": "completed",
                "output": "https://cran.r-project.org/package=termr",
            },
        },
        state,
    )
    events = read_events(run.path)
    (url_event,) = [event for event in events if event["event_type"] == "agent.url.mentioned"]
    assert url_event["source_access_status"] == "unknown"
    assert url_event["observation_location"] == "tool_output"
    assert schema.validate_stream(events) == []


# 2-3. identifiers ---------------------------------------------------------------------------
def test_identifiers_are_unique_and_run_trial_trace_call_relations_hold(tmp_path):
    run = recorder.RunTelemetry(tmp_path, RUN, strict=True)
    run.emit("benchmark.run.started", trial_count=2)
    first, second = run.trial("D01-A-1"), run.trial("D01-B-1")
    for trial in (first, second):
        trial.emit("benchmark.trial.started", task="D01", mode="with-mcp")
        trial.client_tool_started("exec_a", "get_package")
        trial.client_tool_started("exec_b", "get_package")
        trial.client_tool_finished("exec_a", "get_package", False)
        trial.client_tool_finished("exec_b", "get_package", True)
    events = read_events(run.path)
    assert first.trace_id != second.trace_id
    calls = {(e["trial_id"], e["call_id"]) for e in events if "call_id" in e}
    assert len(calls) == 4  # call-001/002 repeat across trials but never inside one
    assert schema.validate_stream(events) == []
    assert {e["trace_id"] for e in events if e.get("trial_id") == "D01-A-1"} == {first.trace_id}
    run_events = [e for e in events if e["event_type"].startswith("benchmark.run")]
    assert all("trial_id" not in e and "trace_id" not in e for e in run_events)

    broken = [dict(e) for e in events]
    broken[2]["trace_id"] = second.trace_id  # trace shared by two trials
    broken.append({**broken[-1]})  # duplicate terminal call event
    broken.append({**broken[0], "run_id": "another-run"})
    problems = " | ".join(schema.validate_stream(broken))
    assert "shared by several trials" in problems or "more than one trace_id" in problems
    assert "duplicate terminal tool event" in problems and "multiple run_id" in problems


def test_client_and_server_call_ids_stay_separate_and_correlation_is_unconfirmed(tmp_path):
    run, trial = new_trial(tmp_path)
    trial.client_tool_started("exec_1", "get_function_docs")
    trial.client_tool_finished("exec_1", "get_function_docs", True)
    trial.record_server_calls([server_call(7, status="error")])
    events = read_events(run.path)
    client = next(e for e in events if e["source"] == "agent_stream" and "is_error" in e)
    server = next(e for e in events if e["source"] == "mcp_server")
    assert client["call_id"] == "client-call-0001" and server["call_id"] == "server-call-0007"
    assert server["correlation"] == "ordinal_unconfirmed"
    assert server["correlated_call_id"] == client["call_id"]
    assert server["clock"] == "server_process" and client["clock"] == "trial"

    run, trial = new_trial(tmp_path / "other")
    trial.client_tool_started("exec_1", "get_package")  # different tool -> no ordinal link
    trial.record_server_calls([server_call(1)])
    server = next(e for e in read_events(run.path) if e["source"] == "mcp_server")
    assert server["correlation"] == "unmatched" and server["correlated_call_id"] is None


def test_server_calls_without_server_timestamps_get_no_invented_time(tmp_path):
    run, trial = new_trial(tmp_path)
    old = server_call(1)
    del old["timestamp_utc"], old["process_offset_ms"]
    assert trial.record_server_calls([old]) == []
    assert not run.path.exists()


# 4-8. real MCP calls through the in-process server --------------------------------------------
async def mcp_server_events(service, calls, monkeypatch, caplog, trial_id="D01-B-1"):
    monkeypatch.setenv("MCP_TOOLSET", "consolidated")
    monkeypatch.setenv("RKMCP_BENCH_RUN_ID", RUN)
    monkeypatch.setenv("RKMCP_BENCH_TRIAL_ID", trial_id)
    monkeypatch.delenv("RKMCP_DIAGNOSTIC_FUNCTION_ALIASES", raising=False)
    caplog.set_level(logging.INFO, logger="cran_knowledge_mcp.server")
    api, _, _ = service
    results = []
    async with create_connected_server_and_client_session(create_server(service=api)) as session:
        for name, arguments in calls:
            results.append(await session.call_tool(name, arguments))
    parsed = simple.parse_mcp_call_telemetry(NL.join(caplog.messages), RUN, trial_id)
    assert parsed["invalid_records"] == 0
    return results, parsed["calls"]


async def test_real_server_calls_become_success_failure_nested_and_repeat_events(
    service, monkeypatch, caplog, tmp_path
):
    ok = ("get_package", {"package": "ExamplePkg"})
    missing_alias = ("get_function_docs", {"package": "ExamplePkg", "function": "private-guess"})
    missing_pkg = ("get_package", {"package": "MissingPkg"})
    other_alias = ("get_function_docs", {"package": "ExamplePkg", "function": "other-guess"})
    results, calls = await mcp_server_events(
        service,
        [ok, ok, missing_alias, missing_alias, other_alias, missing_pkg],
        monkeypatch,
        caplog,
    )
    assert [r.isError for r in results] == [False, False, True, True, True, True]
    run, trial = new_trial(tmp_path)
    trial.record_server_calls(calls)
    events = read_events(run.path)
    assert schema.validate_stream(events) == []

    first = events[0]  # 4. successful call
    assert first["event_type"] == "mcp.tool.completed" and first["is_error"] is False
    assert first["verification_status"] == "verified" and first["source_count"] >= 1
    assert first["package"] == "ExamplePkg" and first["repository"] == "cran"
    assert first["partial"] is False and first["version_mismatch"] is False
    assert first["result_bytes"] > first["useful_bytes"] > 0  # envelope counts the JSON twice
    assert first["content_duplicates_structured"] is True
    assert first["cache_network_requests"] > 0 and first["cache_hits"] == 0
    assert events[1]["cache_hits"] > 0 and events[1]["cache_network_requests"] == 0  # 14. signal

    failed = events[2]  # 5. failed call, code kept, alias never recorded
    assert failed["event_type"] == "mcp.tool.failed" and failed["is_error"] is True
    assert failed["error_codes"] == ["docs_not_found"] and "function" not in failed
    assert failed["package"] is None  # not confirmed by a verified result

    nested = events[5]  # 7. get_package keeps its code in errors[].error
    assert nested["event_type"] == "mcp.tool.failed"
    assert nested["error_codes"] == ["package_not_found"]
    assert results[5].structuredContent.get("error") is None

    # 8. repeats: identical, identical after an error, similar (same package, other arguments)
    assert [e["repeat_kind"] for e in events[:6]] == [
        "first",
        "identical",
        "first",
        "identical_after_error",
        "similar",
        "first",
    ]
    text = run.path.read_text(encoding="utf-8")
    assert "private-guess" not in text and "other-guess" not in text and "MissingPkg" not in text

    summary = aggregate.summarize_trial({"trial_id": "D01-B-1", "mode": "with-mcp"}, trial.events)
    overall = summary["overall"]
    assert (overall["mcp_calls_attempted"], overall["mcp_calls_succeeded"]) == (6, 2)
    assert (overall["mcp_calls_failed"], overall["mcp_calls_partial"]) == (4, 0)
    assert overall["mcp_repeated_identical_calls"] == 2 and overall["mcp_repeated_after_error"] == 1
    assert overall["mcp_similar_calls"] == 1
    assert overall["mcp_cache_hit_rate"] is not None and overall["mcp_cache_lookups"] > 0
    docs = summary["by_tool"]["get_function_docs"]
    assert docs["mcp_calls_failed"] == 3 and docs["mcp_calls_attempted"] == 3
    classified = errors.classify_mcp_events(
        [
            {"is_error": e["is_error"], "error_codes": e["error_codes"], "partial": e["partial"]}
            for e in events
        ]
    )
    assert {
        (c["reason_code"], c["category"], c["source_code"], c["count"]) for c in classified
    } == {
        ("MCP_PROVIDER_ERROR", "not_found", "docs_not_found", 3),
        ("MCP_PROVIDER_ERROR", "not_found", "package_not_found", 1),
    }


async def test_discovery_observations_persist_query_alias_pages_and_server_call_ids(
    service, monkeypatch, caplog
):
    secret_query = "Authorization: Bearer sk-test-secret-canary-0123456789"
    results, calls = await mcp_server_events(
        service,
        [
            (
                "list_package_functions",
                {
                    "package": "ExamplePkg",
                    "query": "example",
                    "limit": 20,
                    "offset": 0,
                },
            ),
            (
                "list_package_functions",
                {
                    "package": "ExamplePkg",
                    "query": secret_query,
                    "limit": 5,
                    "offset": 0,
                },
            ),
        ],
        monkeypatch,
        caplog,
    )
    assert all(not result.isError for result in results)
    assert all(call.get("server_protocol_call_id") for call in calls)

    rows = projection.correlate([], calls)
    assert len(rows) == 2
    assert all(row["source"] == "mcp_server" for row in rows)
    assert all(projection.validate_record(row) for row in rows)
    first = rows[0]
    assert first["request_projection"]["query_text"] == "example"
    assert first["request_projection"]["offset"] == 0
    assert first["request_projection"]["limit"] == 20
    assert first["response_projection"]["aliases"] == ["example", "example_alias"]
    assert first["server_protocol_call_id"] == calls[0]["server_protocol_call_id"]

    second = rows[1]
    assert second["request_projection"]["query_projection_status"] == "redacted"
    assert "query_text" not in second["request_projection"]
    assert second["request_projection"]["offset"] == 0
    assert secret_query not in caplog.text
    assert secret_query not in json.dumps(rows)


def test_repeat_tracker_is_keyed_and_bounded():
    tracker = RepeatTracker()
    args = {"package": "p", "function": "f"}
    one = tracker.begin("get_function_docs", args)
    tracker.finish(one[0], failed=True)
    again = tracker.begin("get_function_docs", dict(reversed(list(args.items()))))
    assert one[1:] == ("first", 0) and again[1:] == ("identical_after_error", 1)
    assert one[0] == again[0] and len(one[0]) == 12
    assert RepeatTracker().begin("get_function_docs", args)[0] != one[0]  # per-process key
    assert tracker.begin("get_package", {"package": 5})[1] == "first"
    assert tracker.begin("get_function_docs", {"package": "p", "function": "g"})[1] == "similar"


# 6. partial results ---
def call_result(structured, *, is_error=False):
    text = json.dumps(structured, separators=(",", ":"))
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=structured,
        isError=is_error,
    )


def test_partial_result_is_not_counted_as_clean_success(tmp_path):
    structured = {
        "package": "pkgx",
        "verification_status": "partial",
        "sources": [{"source_url": "https://cran.r-project.org/"}],
        "errors": [{"section": "vignettes", "error": {"code": "timeout"}}],
    }
    signals = result_signals({"package": "pkgx"}, call_result(structured))
    assert signals["partial"] is True and signals["verification_status"] == "partial"
    assert signals["package"] == "pkgx"  # partial results still confirm the package

    run, trial = new_trial(tmp_path)
    trial.record_server_calls(
        [
            server_call(
                1,
                "get_package",
                partial=True,
                error_codes=["timeout"],
                verification_status="partial",
                source_count=1,
            ),
            server_call(
                2, "get_package", partial=False, verification_status="verified", source_count=2
            ),
            server_call(3, "get_package", status="error", error_codes=["package_not_found"]),
        ]
    )
    overall = aggregate.summarize_trial({"trial_id": "t"}, trial.events)["overall"]
    assert (overall["mcp_calls_attempted"], overall["mcp_calls_partial"]) == (3, 1)
    assert (overall["mcp_calls_succeeded"], overall["mcp_calls_failed"]) == (1, 1)
    assert (
        overall["mcp_calls_succeeded"]
        + overall["mcp_calls_partial"]
        + overall["mcp_calls_failed"]
        + overall["mcp_calls_unresolved"]
    ) == overall["mcp_calls_attempted"]
    classified = errors.classify_mcp_events(
        [{"is_error": False, "partial": True, "error_codes": ["timeout"]}]
    )
    assert [c["reason_code"] for c in classified] == ["MCP_PARTIAL_RESULT", "MCP_TOOL_TIMEOUT"]


def test_is_error_false_without_completeness_data_is_reported_unknown_not_clean(tmp_path):
    signals = result_signals({}, call_result({"description": "analysis"}))
    assert signals["partial"] is None and signals["verification_status"] is None
    run, trial = new_trial(tmp_path)
    trial.record_server_calls([server_call(1, "analyze_r_source", partial=None)])
    overall = aggregate.summarize_trial({"trial_id": "t"}, trial.events)["overall"]
    assert overall["mcp_calls_partial"] is None and overall["mcp_calls_completeness_unknown"] == 1
    assert overall["mcp_verified_source_rate"] is None


# 9. percentiles ---
def test_percentiles_use_individual_observations_and_report_their_count():
    assert aggregate.percentile([10, 20, 30, 40, 100], 0.5) == 30
    assert aggregate.percentile([10, 20, 30, 40, 100], 0.95) == 88.0
    assert aggregate.percentile([7], 0.95) == 7 and aggregate.percentile([], 0.5) is None
    calls = [{"tool": "t", "is_error": False, "duration_ms": d} for d in (100, 10, 40, 30, 20)]
    values = aggregate.metrics(calls)
    assert (values["mcp_latency_p50_ms"], values["mcp_latency_p95_ms"]) == (30, 88.0)
    assert values["mcp_latency_observations"] == 5
    empty = aggregate.metrics([])
    assert empty["mcp_latency_p50_ms"] is None and empty["mcp_latency_observations"] == 0


# 10. usage and cost ---
def test_missing_usage_and_cost_stay_null(tmp_path):
    usage = aggregate.api_usage({"usage": None, "usage_status": "unavailable", "cost": None})
    assert usage["input_tokens"] is usage["total_tokens"] is usage["cost"] is None
    assert usage["status"] == "unavailable" and usage["cost_status"] == "unavailable"
    observed = aggregate.api_usage(
        {
            "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
            "usage_status": "observed",
        }
    )
    assert observed["total_tokens"] == 7 and observed["cost"] is None

    run, trial = new_trial(tmp_path)
    record = {"status": "scored", "usage_status": "unavailable", "cost_status": "unavailable"}
    simple.finalize_trial_telemetry(record, trial)
    done = next(e for e in read_events(run.path) if e["event_type"] == "benchmark.trial.completed")
    assert done["api_usage_status"] == "unavailable" and done["api_input_tokens"] is None
    assert done["api_total_tokens"] is None and done["cost_status"] == "unavailable"
    assert record["mcp_metrics"]["api_usage"]["input_tokens"] is None


# 11-13. sources, versions, truncation ---
def test_verified_and_unverified_sources_version_mismatch_and_truncation():
    calls = [
        {"tool": "t", "is_error": False, "verification_status": "verified", "source_count": 2},
        {"tool": "t", "is_error": False, "verification_status": "verified", "source_count": 0},
        {"tool": "t", "is_error": False, "verification_status": "partial", "source_count": 1},
        {
            "tool": "t",
            "is_error": True,
            "verification_status": "failed",
            "source_count": 0,
            "error_codes": ["version_mismatch"],
        },
        {"tool": "t", "is_error": False, "verification_status": None},
    ]
    values = aggregate.metrics(calls)
    assert values["mcp_verified_source_rate"] == 0.25
    assert values["mcp_verified_source_denominator"] == 4  # the call without a status is excluded
    assert values["mcp_version_mismatch_count"] == 1
    # source verification, version mismatch and completeness are independent measurements
    assert values["mcp_calls_partial"] is None and values["mcp_calls_completeness_unknown"] == 4

    truncated = [
        {"tool": "t", "is_error": False, "output_truncated": True, "page_truncated": False},
        {"tool": "t", "is_error": False, "output_truncated": False, "page_truncated": True},
        {"tool": "t", "is_error": False, "output_truncated": None},
    ]
    # one call has no truncation information, so the count is unknown rather than 1
    assert aggregate.metrics(truncated)["mcp_output_truncation_count"] is None
    assert aggregate.metrics(truncated[:2])["mcp_output_truncation_count"] == 1
    assert aggregate.metrics(truncated[:2])["mcp_page_truncation_count"] == 1
    assert aggregate.metrics(truncated)["mcp_page_truncation_count"] is None
    assert (
        aggregate.metrics([{"tool": "t", "is_error": False}])["mcp_output_truncation_count"] is None
    )

    structured = {"output_truncation": {"truncated": True}, "truncated": True, "sources": []}
    signals = result_signals({}, call_result(structured))
    assert signals["output_truncated"] is True and signals["page_truncated"] is True
    paging = result_signals({}, call_result({"truncated": True, "next_offset": 8000}))
    assert paging["output_truncated"] is False and paging["page_truncated"] is True

    unknown = [{"tool": "t", "is_error": True, "error_codes": None}]
    assert aggregate.metrics(unknown)["mcp_version_mismatch_count"] is None
    assert errors.classify_mcp_code("version_mismatch")["category"] == "version_mismatch"


def test_output_budget_and_page_truncation_are_aggregated_separately():
    events = [
        {
            "source": "mcp_server",
            "event_type": "mcp.tool.completed",
            "tool": "get_function_docs",
            "is_error": False,
            "output_truncated": False,
            "page_truncated": True,
        },
        {
            "source": "mcp_server",
            "event_type": "mcp.tool.completed",
            "tool": "get_function_docs",
            "is_error": False,
            "output_truncated": True,
            "page_truncated": False,
        },
    ]
    server_calls, _ = aggregate.calls_from_events(events)
    summary = aggregate.metrics(server_calls)
    assert summary["mcp_output_truncation_count"] == 1
    assert summary["mcp_page_truncation_count"] == 1


def test_installed_package_version_is_never_inferred_by_the_server_signals():
    signals = result_signals(
        {"package": "p"}, call_result({"verification_status": "verified", "package_version": "1.0"})
    )
    assert "installed_version" not in signals and signals["version_mismatch"] is False


# 14. cache ---
def test_cache_hit_rate_requires_an_actual_signal():
    assert (
        aggregate.metrics([{"tool": "t", "is_error": False, "duration_ms": 0.1}])[
            "mcp_cache_hit_rate"
        ]
        is None
    )  # a fast answer is never taken as a hit
    no_lookup = [{"tool": "t", "is_error": False, "cache_hits": 0, "cache_network_requests": 0}]
    assert aggregate.metrics(no_lookup)["mcp_cache_hit_rate"] is None
    calls = [
        {"tool": "t", "is_error": False, "cache_hits": 0, "cache_network_requests": 2},
        {"tool": "t", "is_error": False, "cache_hits": 2, "cache_network_requests": 0},
        {"tool": "t", "is_error": False, "cache_hits": 1, "cache_network_requests": 1},
    ]
    values = aggregate.metrics(calls)
    assert values["mcp_cache_hit_rate"] == 0.5 and values["mcp_cache_lookups"] == 6


# error taxonomy ---
def test_taxonomy_keeps_origin_category_and_reason_independent_and_unknown_codes():
    assert set(errors.REASON_CODES) >= {
        "MODEL_TIMEOUT",
        "MODEL_GENERATION_ERROR",
        "MCP_DISCOVERY_FAILED",
        "MCP_TRANSPORT_ERROR",
        "MCP_TOOL_TIMEOUT",
        "MCP_PROVIDER_ERROR",
        "MCP_PARTIAL_RESULT",
        "MCP_INVALID_RESPONSE",
        "R_SYNTAX_ERROR",
        "R_RUNTIME_ERROR",
        "ARTIFACT_INVALID",
        "SCORER_INFRA_ERROR",
        "SCORER_UNSUPPORTED_CLAIMS",
        "CLEANUP_ERROR",
    }
    refusal = errors.classify_mcp_code("rate_limited")
    assert (refusal["origin"], refusal["reason_code"], refusal["category"]) == (
        "mcp_server",
        "MCP_PROVIDER_ERROR",
        "upstream",
    )
    unknown = errors.classify_mcp_code("brand_new_code")
    assert (
        unknown["reason_code"] == "UNCLASSIFIED_ERROR"
        and unknown["source_code"] == "brand_new_code"
    )
    assert errors.classify_mcp_code("source_timeout")["reason_code"] == "MCP_TOOL_TIMEOUT"
    assert schema.FIELDS["error"](errors.make_error("MODEL_TIMEOUT", source_code="x"))
    assert errors.make_error("NOT_A_REASON", source_code="Odd Code")["source_code"] == "odd_code"


def test_scorer_abstention_is_evidence_insufficiency_and_keeps_mcp_diagnostics_secondary():
    partial = {
        "is_error": False,
        "partial": True,
        "error_codes": ["source_unavailable"],
    }
    summary = errors.classify_trial(
        {
            "status": "unsupported_for_automatic_scoring",
            "error_type": None,
            "turn_terminal": True,
            "score": {
                "status": "unsupported_for_automatic_scoring",
                "reason": "unsupported_claims_unknown",
            },
        },
        [partial],
    )
    primary = summary["primary_error"]
    assert primary == {
        "origin": "scorer",
        "category": "evidence_insufficiency",
        "reason_code": "SCORER_UNSUPPORTED_CLAIMS",
        "source_code": "unsupported_claims_unknown",
        "severity": "recoverable",
    }
    assert {item["reason_code"] for item in summary["mcp_errors"]} == {
        "MCP_PARTIAL_RESULT",
        "MCP_PROVIDER_ERROR",
    }
    assert schema.FIELDS["error"](primary)
    assert "SCORER_UNSUPPORTED_CLAIMS" not in errors.AGENT_OUTCOME


def test_provider_refusal_stays_an_mcp_error_when_the_agent_later_fails():
    record = {"status": "error", "error_type": "ValueError", "turn_terminal": True}
    calls = [{"is_error": True, "error_codes": ["rate_limited"], "partial": None}] * 3
    summary = errors.classify_trial(record, calls)
    assert summary["primary_error"]["reason_code"] == "MCP_PROVIDER_ERROR"
    assert summary["primary_error"]["count"] == 3
    assert [e["reason_code"] for e in summary["subsequent_errors"]] == ["ARTIFACT_INVALID"]
    assert summary["order_basis"] == "pipeline_stage_order"
    # "not found" answers are normal tool results and never become the cause of a failure
    quiet = errors.classify_trial(record, [{"is_error": True, "error_codes": ["docs_not_found"]}])
    assert quiet["primary_error"]["reason_code"] == "ARTIFACT_INVALID"
    assert quiet["mcp_errors"][0]["category"] == "not_found"
    # an interrupt or a scorer infrastructure failure has its own cause: MCP errors stay listed
    for record in (
        {"status": "interrupted", "error_type": "KeyboardInterrupt", "interrupted": True},
        {"status": "scoring_error", "score": {"status": "scoring_error", "reason": "exit_125"}},
    ):
        summary = errors.classify_trial(record, calls)
        assert summary["primary_error"]["reason_code"] in {"INTERRUPTED", "SCORER_INFRA_ERROR"}
        assert [e["reason_code"] for e in summary["mcp_errors"]] == ["MCP_PROVIDER_ERROR"]
    ok = errors.classify_trial(
        {"status": "scored"}, [{"is_error": True, "error_codes": ["rate_limited"]}]
    )
    assert ok["primary_error"] is None and ok["mcp_errors"]


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        ({"status": "error", "error_type": "TimeoutError"}, "MODEL_TIMEOUT"),
        (
            {"status": "error", "error_type": "RuntimeError", "turn_failure": "turn_failed"},
            "MODEL_GENERATION_ERROR",
        ),
        (
            {"status": "interrupted", "error_type": "KeyboardInterrupt", "interrupted": True},
            "INTERRUPTED",
        ),
        (
            {
                "status": "candidate_error",
                "score": {"status": "candidate_error", "reason": "invalid_json_answer"},
            },
            "ARTIFACT_INVALID",
        ),
        (
            {"status": "scoring_error", "score": {"status": "scoring_error", "reason": "exit_125"}},
            "SCORER_INFRA_ERROR",
        ),
        (
            {
                "status": "candidate_timeout",
                "score": {"status": "candidate_timeout", "reason": "scorer_deadline"},
            },
            "R_RUNTIME_ERROR",
        ),
    ],
)
def test_trial_primary_error_classification(record, reason):
    assert errors.classify_trial(record)["primary_error"]["reason_code"] == reason


# 15-16. interruption and cleanup ---
@linux_only
def test_ctrl_c_is_recorded_as_the_primary_error_with_cleanup_events(tmp_path, monkeypatch):
    from test_codex_simple_interrupts import trial

    result, _, _ = trial(tmp_path, monkeypatch, phase="during_turn")
    events = read_events(tmp_path / "telemetry.jsonl")
    assert schema.validate_stream(events) == []
    done = next(e for e in events if e["event_type"] == "benchmark.trial.completed")
    assert done["interrupted"] is True and done["status"] == "interrupted"
    assert done["primary_error"]["reason_code"] == "INTERRUPTED"
    assert result["error_summary"]["primary_error"] == done["primary_error"]
    kinds = [e["event_type"] for e in events]
    assert kinds[0] == "benchmark.trial.started" and kinds.index(
        "agent.session.created"
    ) < kinds.index("cleanup.started")
    assert "scorer.started" not in kinds  # an interrupted trial is never scored
    completed = {e["cleanup_operation"] for e in events if e["event_type"] == "cleanup.completed"}
    assert {"delete_session", "remove_executor", "remove_network"} <= completed
    assert result["telemetry"]["trace_id"] == done["trace_id"]


@linux_only
def test_cleanup_errors_are_listed_separately_and_never_replace_the_task_error(
    tmp_path, monkeypatch
):
    from test_codex_simple_interrupts import trial

    result, _, _ = trial(tmp_path, monkeypatch, phase="ordinary_error", deletion="failed")
    events = read_events(tmp_path / "telemetry.jsonl")
    done = next(e for e in events if e["event_type"] == "benchmark.trial.completed")
    assert done["primary_error"]["reason_code"] == "MODEL_GENERATION_ERROR"
    assert [e["reason_code"] for e in done["cleanup_errors"]] == ["CLEANUP_ERROR"]
    assert done["cleanup_errors"][0]["category"] == "delete_session"
    failed = [e for e in events if e["event_type"] == "cleanup.failed"]
    assert failed and failed[0]["cleanup_operation"] == "delete_session"
    assert failed[0]["cleanup_status"] in {"failed", "unknown"}
    assert result["status"] == "error" and result["cleanup_completed"] is False


@linux_only
def test_successful_trial_emits_scorer_and_artifact_events_without_secrets(tmp_path, monkeypatch):
    from test_codex_simple_interrupts import KEYS, trial

    result, _, _ = trial(tmp_path, monkeypatch, phase="completed")
    text = (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in text.splitlines()]
    kinds = [e["event_type"] for e in events]
    for expected in (
        "agent.turn.started",
        "agent.turn.completed",
        "scorer.started",
        "scorer.completed",
    ):
        assert expected in kinds
    scored = next(e for e in events if e["event_type"] == "scorer.completed")
    assert (scored["passed"], scored["total"]) == (4, 4)
    done = next(e for e in events if e["event_type"] == "benchmark.trial.completed")
    assert done["primary_error"] is None and done["api_usage_status"] == "unavailable"
    # 17. no credentials, task text or raw payloads
    for marker in (*KEYS, "private task body marker", "Authorization", "Bearer"):
        assert marker not in text
    assert result["telemetry"]["invalid_events_in_run"] == 0


def test_recorder_masks_configured_secrets_as_a_last_defence(tmp_path):
    secret = "sk-test-0123456789abcdef"
    run, trial = new_trial(tmp_path, secrets=(secret,))
    trial.record_server_calls([server_call(1, package="climenu")])
    # even a value that passes its pattern is masked if it equals a configured secret
    trial.emit(
        "cleanup.completed", cleanup_operation="x", cleanup_status="confirmed", diagnostic=None
    )
    assert secret not in run.path.read_text(encoding="utf-8")
    run.secrets = ("climenu",) + run.secrets
    trial.record_server_calls([server_call(2, package="climenu")])
    assert "[REDACTED]" in run.path.read_text(encoding="utf-8") and run.redactions == 1


def test_event_fields_cannot_carry_free_text():
    assert not {"arguments", "result", "reasoning", "api_key", "authorization", "text"} & set(
        schema.FIELDS
    )
    assert schema.validate_event({"event_type": "agent.turn.started", "api_key": "x"})


# 18. compatibility with older files ---
LEGACY_RECORD = {
    "trial_id": "D01-B-1",
    "mode": "with-mcp",
    "usage": None,
    "usage_status": "unavailable",
    "mcp_usage": {"calls": 4, "calls_by_tool": {"get_function_docs": 3, "get_package": 1}},
    "mcp_telemetry": {
        "calls": [
            {
                "tool_name": "get_package",
                "call_number": 1,
                "status": "ok",
                "duration_ms": 50.0,
                "response_bytes": 2000,
                "response_tokens_estimate": 500,
                "error_code": None,
                "truncated": False,
            },
            {
                "tool_name": "get_package",
                "call_number": 2,
                "status": "error",
                "duration_ms": 1.0,
                "response_bytes": 1800,
                "response_tokens_estimate": 450,
                "error_code": None,
                "truncated": False,
            },
            {
                "tool_name": "get_function_docs",
                "call_number": 3,
                "status": "error",
                "duration_ms": 1.0,
                "response_bytes": 1100,
                "response_tokens_estimate": 275,
                "error_code": "docs_not_found",
                "truncated": False,
            },
            {
                "tool_name": "get_function_docs",
                "call_number": 4,
                "status": "ok",
                "duration_ms": 2.0,
                "response_bytes": 6000,
                "response_tokens_estimate": 1500,
                "error_code": None,
                "truncated": True,
            },
        ]
    },
}


def test_older_results_without_jsonl_are_summarized_without_inventing_fields():
    summary = aggregate.summarize_trial(LEGACY_RECORD)
    overall = summary["overall"]
    assert summary["source"] == "legacy_server_log"
    assert (
        overall["mcp_calls_attempted"],
        overall["mcp_calls_failed"],
        overall["mcp_calls_succeeded"],
    ) == (4, 2, 2)
    assert overall["mcp_result_bytes_total"] == 10900 and overall["mcp_result_bytes_mean"] == 2725.0
    for unknown in (
        "mcp_calls_partial",
        "mcp_verified_source_rate",
        "mcp_version_mismatch_count",
        "mcp_repeated_identical_calls",
        "mcp_cache_hit_rate",
        "mcp_output_truncation_count",
    ):
        assert overall[unknown] is None, unknown
    assert overall["mcp_verified_source_denominator"] == 0 and overall["mcp_calls_unresolved"] == 0
    assert set(summary["by_tool"]) == {"get_function_docs", "get_package"}
    assert summary["api_usage"]["input_tokens"] is None


def test_save_results_keeps_existing_csvs_and_adds_metrics_only_when_present(tmp_path):
    record = {
        **LEGACY_RECORD,
        "run_id": RUN,
        "task": "D01",
        "model": "m",
        "effort": "medium",
        "score": {"passed": 1, "total": 4},
    }
    simple.save_results(tmp_path, [record])
    assert (tmp_path / "results.csv").is_file() and (tmp_path / "mcp_calls.csv").is_file()
    assert not (tmp_path / "mcp_metrics.csv").exists()
    assert "error_codes" in (tmp_path / "mcp_calls.csv").read_text(encoding="utf-8").splitlines()[0]

    record["mcp_metrics"] = aggregate.summarize_trial(record)
    simple.save_results(tmp_path, [record])
    rows = (tmp_path / "mcp_metrics.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0].split(",")[:4] == ["trial_id", "mode", "tool", "metrics_source"]
    assert len(rows) == 1 + 3  # overall plus two tools
    assert set(aggregate.metrics([])) == set(aggregate.METRIC_COLUMNS)


def test_saved_d01_run_can_be_aggregated_without_new_metadata():
    from benchmarks.codex_r.runner import bench

    run = bench.ROOT / "results" / "20261025T083653Z-ca1d5503"
    if not (run / "results.json").is_file():
        pytest.skip("saved D01 run is not available in this checkout")
    records = json.loads((run / "results.json").read_text(encoding="utf-8"))
    before = (run / "results.json").read_bytes()
    report = aggregate.summarize_run(records)
    assert (run / "results.json").read_bytes() == before
    b = next(t for t in report["trials"] if t["trial_id"] == "D01-B-1")
    assert b["source"] == "legacy_server_log"
    overall = b["overall"]
    assert (
        overall["mcp_calls_attempted"],
        overall["mcp_calls_failed"],
        overall["mcp_calls_succeeded"],
    ) == (55, 41, 14)
    assert overall["mcp_result_bytes_total"] == 153198 and overall["mcp_latency_observations"] == 55
    docs = b["by_tool"]["get_function_docs"]
    assert (docs["mcp_calls_attempted"], docs["mcp_calls_failed"]) == (46, 39)
    assert b["by_tool"]["search_packages"]["mcp_calls_failed"] == 0
    assert overall["mcp_cache_hit_rate"] is None and overall["mcp_repeated_identical_calls"] is None
    assert overall["mcp_version_mismatch_count"] is None  # two failures carry no error code
    assert b["api_usage"]["input_tokens"] is None and b["api_usage"]["status"] == "unavailable"
    a = next(t for t in report["trials"] if t["trial_id"] == "D01-A-1")
    assert a["source"] == "none" and a["overall"]["mcp_calls_attempted"] == 0


# experiment configuration and manifest ---
def test_manifest_names_the_historical_and_current_configurations():
    from benchmarks.codex_r import knowledge_pilot

    current = knowledge_pilot.configuration()
    assert current["id"] == "consolidated-v1.1" and current["status"] == "current"
    assert current["docs_not_found_hints"] is True and current["telemetry_schema_version"] == "1.0"
    assert current["d_scorer"] == knowledge_pilot.D_SCORER_VERSION
    historical = knowledge_pilot.configuration("consolidated-v1")
    assert historical["status"] == "historical" and historical["docs_not_found_hints"] is False
    assert (
        historical["runs"] == ["20261025T083653Z-ca1d5503"]
        and historical["toolset"] == "consolidated"
    )


def test_experiment_record_identifies_sources_without_secrets(tmp_path, monkeypatch):
    from benchmarks.codex_r.runner import bench

    monkeypatch.setenv("OPENAI_API_KEY", "must-never-appear-0123456789")
    state = experiment.git_state(bench.REPO)
    assert set(state) >= {"revision", "dirty", "changed_paths"}
    assert state["revision"] is None or len(state["revision"]) == 40
    assert (state["working_tree_sha256"] is None) == (state["dirty"] is False)
    digest = experiment.tree_sha256(bench.REPO / "src")
    assert digest == experiment.tree_sha256(bench.REPO / "src") and len(digest) == 64
    record = experiment.build(
        run_id=RUN,
        repo=bench.REPO,
        configuration="consolidated-v1.1",
        toolset="consolidated",
        allowed_tools=["get_package"],
        registered_tools=["get_package", "get_function_docs"],
        images={"mcp": "sha256:" + "a" * 64},
        scorer_versions={"d_recommendation": "d-recommendation-2"},
        model="gpt-6-luna",
        effort="medium",
        instructions="standard",
        modes=["with-mcp"],
        tasks=["D01"],
        repetitions=1,
        timeout_seconds=900,
        r_version="4.5.2",
        renv_lock=bench.ROOT / "configs" / "renv.lock",
        package_pins={},
    )
    text = json.dumps(record)
    assert "must-never-appear" not in text and "OPENAI" not in text
    assert record["telemetry_schema_version"] == schema.SCHEMA_VERSION
    assert record["mcp_server"]["registered_tool_count"] == 2


def test_unfinished_client_calls_are_unresolved_not_dropped_or_guessed(tmp_path):
    run, trial = new_trial(tmp_path)
    trial.client_tool_started("a", "get_package")
    trial.client_tool_finished("a", "get_package", False)
    trial.client_tool_started("b", "get_package")
    trial.client_tool_finished("b", "get_package", True)
    trial.client_tool_started("c", "get_function_docs")  # Ctrl+C arrived during this call
    summary = aggregate.summarize_trial({"trial_id": "t"}, trial.events)
    overall = summary["overall"]
    assert summary["source"] == "agent_stream_only"
    assert (overall["mcp_calls_attempted"], overall["mcp_calls_succeeded"]) == (3, 1)
    assert (overall["mcp_calls_failed"], overall["mcp_calls_unresolved"]) == (1, 1)
    assert overall["mcp_latency_p50_ms"] is None and overall["mcp_result_bytes_total"] is None
    assert overall["mcp_version_mismatch_count"] is None  # a failed call has no known code


@pytest.mark.parametrize(
    ("version_field", "expected"),
    [("version", "1.0.1"), ("package_version", "1.0.1"), (None, None)],
)
def test_package_version_flows_from_response_projection_to_evidence(version_field, expected):
    structured = {"package": "termr"}
    if version_field is not None:
        structured[version_field] = expected
    response = projection.project_response({"structuredContent": structured})
    emitted = []

    class CapturingTrial:
        def emit(self, event_type, **fields):
            emitted.append({"event_type": event_type, **fields})
            return emitted[-1]

    simple.emit_projected_client_evidence(
        CapturingTrial(),
        "client-call-0001",
        "get_package",
        {"id": "item-1"},
        {
            "completed": [
                {
                    "client_item_id": "item-1",
                    "tool": "get_package",
                    "response_projection": response,
                }
            ]
        },
    )

    evidence = next(event for event in emitted if event["event_type"] == "agent.evidence.observed")
    assert response.get("version") == expected
    assert evidence["package_version"] == expected
