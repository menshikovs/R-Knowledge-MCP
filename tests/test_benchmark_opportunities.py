"""Synthetic, deterministic tests for MCP opportunity and visibility semantics."""

import copy

from benchmarks.codex_r.telemetry import opportunities


def synthetic_event(event_type, **fields):
    return {
        "schema_version": "1.2",
        "event_type": event_type,
        "run_id": "synthetic-run",
        "trial_id": "D01-B-1",
        "trace_id": "trace-synthetic0001",
        "timestamp_utc": "2026-10-27T10:00:00Z",
        "monotonic_offset_ms": 1,
        "clock": "trial",
        "source": "runner",
        **fields,
    }


def base_events(*, tools=None, echo=None, audit=True):
    tools = ["get_package"] if tools is None else tools
    events = [
        synthetic_event("benchmark.trial.started", task="D01", mode="with-mcp"),
        synthetic_event(
            "mcp.exposure.configured",
            generated_agent_tool_names=tools,
            configured_allowed_tools=tools,
            remote_discovery_status="unknown",
            remote_discovered_tools=None,
        ),
        synthetic_event("agent.turn.completed", source="agent_stream"),
        synthetic_event("benchmark.trial.completed", status="scored", interrupted=False),
    ]
    if echo is not None:
        events.insert(
            2,
            synthetic_event(
                "mcp.exposure.response",
                source="agents_api",
                returned_agent_tool_names=echo,
            ),
        )
    if audit:
        events.insert(
            -2,
            synthetic_event(
                "mcp.discovery.completed",
                source="mcp_server",
                observation="server_audit_after_trial",
                list_tools_requests=0,
                clock="server_process",
            ),
        )
    return events


def evaluate(events, *, mode="with-mcp", trace_status="complete", task_id="D01"):
    manifest, _ = opportunities.load_opportunity_manifest()
    return opportunities.derive_trial_evidence(
        run_id="synthetic-run",
        trial_id="D01-B-1",
        task_id=task_id,
        record={"task": task_id, "mode": mode},
        events=events,
        manifest=manifest,
        trace_status=trace_status,
        telemetry_available=True,
    )


def test_manifest_uses_real_task_ids_and_controlled_tools():
    manifest, sha = opportunities.load_opportunity_manifest()
    assert manifest["opportunity_version"] == "p2-opportunities-1.0"
    assert len(sha) == 64
    assert {task["task_id"] for task in manifest["tasks"]} == {
        *(f"R{i:02}" for i in range(1, 13)),
        "H01",
        "H04",
        "H10",
        *(
            f"{block}{i:02}"
            for block, count in (("B", 3), ("C", 5), ("D", 3), ("E", 5))
            for i in range(1, count + 1)
        ),
    }
    assert {task["task_id"] for task in manifest["tasks"]} >= {
        "R01",
        "R12",
        "H01",
        "H04",
        "H10",
        "B01",
        "E05",
    }
    invalid = copy.deepcopy(manifest)
    invalid["tasks"][0]["opportunities"] = [
        {
            "opportunity_id": "R01-INVALID",
            "capability": "secretly_inferred_reasoning",
            "candidate_tools": ["search_packages"],
            "relevance": "high",
            "source": "task_manifest",
            "evidence_class": "researcher_annotation",
            "rationale": "synthetic invalid fixture",
        }
    ]
    assert any(
        "invalid_capability" in item
        for item in opportunities.validate_opportunity_manifest(invalid)
    )


def test_api_echo_does_not_prove_remote_discovery_and_no_call_is_not_a_miss_without_visibility():
    checkpoints, assessments = evaluate(base_events(tools=["get_package"], echo=None))
    row = next(item for item in assessments if item["opportunity_id"] == "D01-PACKAGE-DISCOVERY")
    assert row["assessment_state"] == "no_relevant_call_observed"
    assert row["visibility_status"] == "unknown"
    assert row["discovery_status"] == "unknown"
    assert row["missed"] is False
    tool_discovery = next(
        item
        for item in checkpoints
        if item["checkpoint_type"] == "discovery_confirmed" and item["subject"] == "get_package"
    )
    assert tool_discovery["observation_status"] == "unknown"
    echo_checkpoint = next(
        item
        for item in checkpoints
        if item["checkpoint_type"] == "advertised" and item["subject"] == "get_package"
    )
    assert echo_checkpoint["observation_status"] == "unknown"


def test_visible_candidate_with_complete_no_call_trace_is_named_and_missed_rate_eligible():
    checkpoints, assessments = evaluate(base_events(tools=["get_package"], echo=["get_package"]))
    row = next(item for item in assessments if item["opportunity_id"] == "D01-PACKAGE-DISCOVERY")
    assert row["assessment_state"] == "no_relevant_call_observed"
    assert row["adequate_observation"] is True
    assert row["visibility_status"] == "observed"
    assert row["missed"] is True
    assert row["candidate_calls"] == 0
    assert row["discovery_status"] == "unknown"
    advertised = next(
        item
        for item in checkpoints
        if item["checkpoint_type"] == "advertised" and item["subject"] == "get_package"
    )
    assert advertised["observation_status"] == "observed"
    assert advertised["verification_status"] == "echo_only"


def test_actual_mcp_invocation_is_utilization_and_failed_call_is_not_success():
    events = base_events(tools=["get_package"], echo=None)
    events.extend(
        [
            synthetic_event(
                "mcp.tool.started",
                source="agent_stream",
                call_id="client-call-0001",
                tool="get_package",
            ),
            synthetic_event(
                "mcp.tool.failed",
                source="agent_stream",
                call_id="client-call-0001",
                tool="get_package",
                is_error=True,
            ),
        ]
    )
    _, assessments = evaluate(events)
    row = next(item for item in assessments if item["opportunity_id"] == "D01-PACKAGE-DISCOVERY")
    assert row["assessment_state"] == "utilized"
    assert row["invocation_status"] == "observed"
    assert row["success_status"] == "not_observed"
    assert row["candidate_calls"] == 1
    assert row["missed"] is False


def test_unknown_terminal_outcome_keeps_success_unknown():
    events = base_events(tools=["get_package"], echo=["get_package"])
    events.extend(
        [
            synthetic_event(
                "mcp.tool.started",
                source="agent_stream",
                call_id="client-call-0001",
                tool="get_package",
            ),
            synthetic_event(
                "mcp.tool.completed",
                source="agent_stream",
                call_id="client-call-0001",
                tool="get_package",
                is_error=None,
            ),
        ]
    )
    _, assessments = evaluate(events)
    row = next(item for item in assessments if item["opportunity_id"] == "D01-PACKAGE-DISCOVERY")
    assert row["assessment_state"] == "utilized"
    assert row["success_status"] == "unknown"


def test_multiple_candidates_and_repeats_count_calls_without_calling_them_redundant():
    events = base_events(
        tools=["search_packages", "get_package"],
        echo=["search_packages", "get_package"],
    )
    for number, tool in enumerate(["search_packages", "search_packages", "get_package"], start=1):
        events.extend(
            [
                synthetic_event(
                    "mcp.tool.started",
                    source="agent_stream",
                    call_id=f"client-call-{number:04d}",
                    tool=tool,
                ),
                synthetic_event(
                    "mcp.tool.completed",
                    source="agent_stream",
                    call_id=f"client-call-{number:04d}",
                    tool=tool,
                    is_error=False,
                ),
            ]
        )
    _, assessments = evaluate(events)
    row = next(item for item in assessments if item["opportunity_id"] == "D01-PACKAGE-DISCOVERY")
    assert row["candidate_calls"] == 3
    assert row["repeated_calls"] == 1
    assert row["assessment_state"] == "utilized"


def test_incomplete_trace_historical_unavailability_and_no_mcp_are_distinct():
    _, partial = evaluate(base_events(tools=["get_package"], echo=None), trace_status="partial")
    row = next(item for item in partial if item["opportunity_id"] == "D01-PACKAGE-DISCOVERY")
    assert row["assessment_state"] == "unknown"
    assert row["adequate_observation"] is False

    manifest, _ = opportunities.load_opportunity_manifest()
    _, historical = opportunities.derive_trial_evidence(
        run_id="synthetic-run",
        trial_id="D01-B-1",
        task_id="D01",
        record={"task": "D01", "mode": "with-mcp"},
        events=[],
        manifest=manifest,
        trace_status="unavailable",
        telemetry_available=False,
    )
    assert historical[0]["assessment_state"] == "unknown"
    assert historical[0]["configured_status"] == "unavailable"
    _, disabled = evaluate(base_events(tools=[], echo=[]), mode="without-mcp")
    assert all(item["assessment_state"] == "not_applicable" for item in disabled)


def test_task_without_opportunity_has_no_assessment_rows():
    _, rows = evaluate(base_events(tools=["get_package"]), task_id="R01")
    assert rows == []
    _, unannotated_rows = evaluate(base_events(tools=["get_package"]), task_id="Z99")
    assert unannotated_rows == []
