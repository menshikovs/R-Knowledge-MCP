"""Researcher-authored MCP opportunity annotations and conservative trial assessments."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

OPPORTUNITY_SCHEMA_VERSION = "1.0"
OBSERVATION_STATES = frozenset(
    {"observed", "not_observed", "unknown", "unavailable", "not_applicable"}
)
ASSESSMENT_STATES = frozenset(
    {"utilized", "no_relevant_call_observed", "unknown", "not_applicable"}
)
CAPABILITIES = frozenset(
    {
        "package_discovery",
        "package_metadata",
        "function_documentation",
        "dependency_analysis",
        "version_compatibility",
        "bioconductor_release_mapping",
        "vignette_discovery",
        "shiny_documentation",
        "quarto_documentation",
        "visualization_documentation",
        "r_documentation",
        "prompt_assistance",
        "workflow_guidance",
    }
)
SUPPORTED_TOOLS = frozenset(
    {
        "search_packages",
        "get_package_info",
        "get_dependencies",
        "get_function_docs",
        "check_package_version",
        "get_bioconductor_version",
        "check_package_compatibility",
        "get_package_vignettes",
        "get_shiny_docs",
        "explain_shiny_reactivity",
        "get_positron_guidance",
        "get_quarto_docs",
        "get_r_workflow_guidance",
        "get_visualization_docs",
        "get_visualization_workflow",
        "build_r_prompt",
        "improve_r_prompt",
        "validate_r_prompt",
        "list_r_prompt_templates",
        "get_r_prompt_context",
        "get_package",
        "list_package_functions",
        "check_r_compatibility",
        "search_r_documentation",
        "get_r_documentation_section",
        "get_framework_docs",
        "analyze_r_source",
        "analyze_r_project",
        "recommend_technology_stack",
    }
)
_CAPABILITY_RE = re.compile(r"[a-z][a-z0-9_]{1,63}\Z")
_TOOL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}\Z")
_TASK_SOURCE_RE = re.compile(
    r"benchmarks/codex_r/(?:tasks/R[0-9]{2}/task\.md|"
    r"knowledge_pilot/tasks/[BCDE][0-9]{2}\.md|hard/tasks/H(?:01|04|10)/prompt\.md)\Z"
)
DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "opportunities.json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class OpportunityManifestError(ValueError):
    """Raised for invalid or unsupported researcher opportunity metadata."""


def validate_opportunity_manifest(document: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(document, dict):
        return ["manifest_not_object"]
    if document.get("schema_version") != OPPORTUNITY_SCHEMA_VERSION:
        problems.append("unsupported_schema_version")
    version = document.get("opportunity_version")
    if not isinstance(version, str) or not re.fullmatch(
        r"p2-opportunities-[0-9]+\.[0-9]+", version
    ):
        problems.append("invalid_opportunity_version")
    tasks = document.get("tasks")
    if not isinstance(tasks, list):
        return problems + ["tasks_not_list"]
    seen_tasks: set[str] = set()
    seen_opportunities: set[tuple[str, str]] = set()
    for task_index, task in enumerate(tasks):
        if not isinstance(task, dict):
            problems.append(f"task_{task_index}_not_object")
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Z][A-Z0-9]{1,7}", task_id):
            problems.append(f"task_{task_index}_invalid_id")
        elif task_id in seen_tasks:
            problems.append(f"duplicate_task:{task_id}")
        else:
            seen_tasks.add(task_id)
        if not isinstance(task.get("task_family"), str) or not task["task_family"].strip():
            problems.append(f"task_{task_index}_invalid_family")
        source = task.get("source")
        if not isinstance(source, str) or not _TASK_SOURCE_RE.fullmatch(source):
            problems.append(f"task_{task_index}_invalid_source")
        opportunities = task.get("opportunities")
        if not isinstance(opportunities, list):
            problems.append(f"task_{task_index}_opportunities_not_list")
            continue
        for opportunity_index, opportunity in enumerate(opportunities):
            if not isinstance(opportunity, dict):
                problems.append(f"task_{task_index}_opportunity_{opportunity_index}_not_object")
                continue
            opportunity_id = opportunity.get("opportunity_id")
            if not isinstance(opportunity_id, str) or not re.fullmatch(
                r"[A-Z][A-Z0-9]{1,7}-[A-Z0-9][A-Z0-9_-]{0,47}", opportunity_id
            ):
                problems.append(f"task_{task_index}_opportunity_{opportunity_index}_invalid_id")
            elif (task_id, opportunity_id) in seen_opportunities:
                problems.append(f"duplicate_opportunity:{opportunity_id}")
            else:
                seen_opportunities.add((task_id, opportunity_id))
            capability = opportunity.get("capability")
            if (
                not isinstance(capability, str)
                or not _CAPABILITY_RE.fullmatch(capability)
                or capability not in CAPABILITIES
            ):
                problems.append(f"{task_id}:{opportunity_id}:invalid_capability")
            candidates = opportunity.get("candidate_tools")
            if (
                not isinstance(candidates, list)
                or not candidates
                or any(
                    not isinstance(tool, str)
                    or not _TOOL_RE.fullmatch(tool)
                    or tool not in SUPPORTED_TOOLS
                    for tool in candidates
                )
                or len(set(candidates)) != len(candidates)
            ):
                problems.append(f"{task_id}:{opportunity_id}:invalid_candidate_tools")
            if opportunity.get("relevance") not in {"low", "medium", "high"}:
                problems.append(f"{task_id}:{opportunity_id}:invalid_relevance")
            if opportunity.get("source") != "task_manifest":
                problems.append(f"{task_id}:{opportunity_id}:invalid_source")
            if opportunity.get("evidence_class") != "researcher_annotation":
                problems.append(f"{task_id}:{opportunity_id}:invalid_evidence_class")
            rationale = opportunity.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 500:
                problems.append(f"{task_id}:{opportunity_id}:invalid_rationale")
    return problems


def load_opportunity_manifest(path: str | Path = DEFAULT_MANIFEST) -> tuple[dict, str]:
    content = Path(path).read_bytes()
    if len(content) > 1 << 20:
        raise OpportunityManifestError("opportunity_manifest_too_large")
    try:
        document = json.loads(content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise OpportunityManifestError("invalid_opportunity_manifest_json") from exc
    problems = validate_opportunity_manifest(document)
    if problems:
        raise OpportunityManifestError("invalid_opportunity_manifest:" + ",".join(problems))
    for task in document["tasks"]:
        source_path = REPOSITORY_ROOT / task["source"]
        resolved = source_path.resolve()
        if not resolved.is_relative_to(REPOSITORY_ROOT) or not resolved.is_file():
            raise OpportunityManifestError("opportunity_source_unavailable")
        source_content = resolved.read_bytes()
        if len(source_content) > 1 << 20:
            raise OpportunityManifestError("opportunity_source_too_large")
        task["source_sha256"] = hashlib.sha256(source_content).hexdigest()
    return document, hashlib.sha256(content).hexdigest()


def _items(events):
    result = []
    for item in events:
        if isinstance(item, tuple) and len(item) == 2:
            event_id, event = item
        else:
            event = item
            event_id = hashlib.sha256(
                json.dumps(
                    event, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
        if isinstance(event, dict):
            result.append((event_id, event))
    return result


def _first(items, event_type):
    return next(
        ((event_id, event) for event_id, event in items if event.get("event_type") == event_type),
        None,
    )


def _list_field(event, field):
    value = event.get(field) if isinstance(event, dict) else None
    return (
        set(value)
        if isinstance(value, list) and all(isinstance(item, str) for item in value)
        else None
    )


def _observed_tool_events(items, tool):
    mcp_events = [
        (event_id, event)
        for event_id, event in items
        if event.get("event_type") in {"mcp.tool.started", "mcp.tool.completed", "mcp.tool.failed"}
        and event.get("tool") == tool
    ]
    if mcp_events:
        return mcp_events
    return [
        (event_id, event)
        for event_id, event in items
        if event.get("event_type")
        in {"agent.tool.started", "agent.tool.completed", "agent.tool.failed"}
        and event.get("tool_class") == "mcp"
        and event.get("tool") == tool
    ]


def _checkpoint(
    run_id,
    trial_id,
    checkpoint_type,
    subject,
    status,
    *,
    expected,
    capture_source=None,
    verification_status="unknown",
    evidence_reference=None,
    reason_code=None,
):
    return {
        "run_id": run_id,
        "trial_id": trial_id,
        "checkpoint_type": checkpoint_type,
        "subject": subject,
        "observation_status": status,
        "expected": expected,
        "capture_source": capture_source,
        "verification_status": verification_status,
        "evidence_reference": evidence_reference,
        "reason_code": reason_code,
    }


def _tool_checkpoint_set(
    *,
    run_id,
    trial_id,
    tool,
    mcp_enabled,
    config_event,
    echo_event,
    remote_tools,
    items,
    stream_complete,
):
    observed_items = []
    if not mcp_enabled:
        base = "not_applicable"
        expected = False
    elif config_event is None:
        base = "unknown"
        expected = True
    else:
        configured = _list_field(config_event[1], "generated_agent_tool_names")
        if configured is None:
            configured = _list_field(config_event[1], "configured_allowed_tools")
        if configured is None:
            base = "unknown"
        else:
            base = "observed" if tool in configured else "not_observed"
        expected = True
    rows = [
        _checkpoint(
            run_id,
            trial_id,
            "configured",
            tool,
            base,
            expected=expected,
            capture_source=config_event[1].get("source") if config_event else None,
            verification_status="direct_observation" if config_event else "unknown",
            evidence_reference=config_event[0] if config_event else None,
            reason_code="tool_not_enabled" if base == "not_observed" else None,
        )
    ]
    if not mcp_enabled:
        advertised_status = discovery_status = invoked_status = success_status = "not_applicable"
        advertised_expected = discovery_expected = invocation_expected = success_expected = False
        invocation_advertised = False
        echoed = None
        advert_evidence = discovery_evidence = invocation_evidence = success_evidence = None
        advert_source = discovery_source = invocation_source = success_source = None
    else:
        echoed = _list_field(echo_event[1], "returned_agent_tool_names") if echo_event else None
        if echo_event is None or echoed is None:
            advertised_status = "unknown"
            advert_evidence = echo_event[0] if echo_event else None
            advert_source = echo_event[1].get("source") if echo_event else None
        else:
            advertised_status = "observed" if tool in echoed else "not_observed"
            advert_evidence = echo_event[0]
            advert_source = echo_event[1].get("source")
        advertised_expected = True
        if remote_tools is None:
            discovery_status = "unknown"
            discovery_evidence = None
            discovery_source = None
        else:
            discovery_status = "observed" if tool in remote_tools else "not_observed"
            discovery_evidence = config_event[0] if config_event else None
            discovery_source = config_event[1].get("source") if config_event else None
        discovery_expected = remote_tools is not None
        observed_items = _observed_tool_events(items, tool)
        invocation_advertised = bool(observed_items)
        if invocation_advertised:
            advertised_status = "observed"
            advert_evidence = observed_items[0][0]
            advert_source = observed_items[0][1].get("source")
        invocation_expected = True
        if observed_items:
            invoked_status = "observed"
            invocation_evidence = observed_items[0][0]
            invocation_source = observed_items[0][1].get("source")
        elif stream_complete:
            invoked_status = "not_observed"
            invocation_evidence = None
            invocation_source = "agent_stream"
        else:
            invoked_status = "unknown"
            invocation_evidence = None
            invocation_source = None
        terminals = [
            (event_id, event)
            for event_id, event in observed_items
            if event.get("event_type")
            in {
                "mcp.tool.completed",
                "mcp.tool.failed",
                "agent.tool.completed",
                "agent.tool.failed",
            }
        ]
        successful = [
            (event_id, event)
            for event_id, event in terminals
            if (event.get("event_type") == "mcp.tool.completed" and event.get("is_error") is False)
            or (
                event.get("event_type") == "agent.tool.completed"
                and event.get("tool_outcome") == "success"
            )
        ]
        if successful:
            success_status = "observed"
            success_evidence = successful[0][0]
            success_source = successful[0][1].get("source")
        elif terminals:
            unknown_terminal = any(
                (event.get("event_type") == "mcp.tool.completed" and event.get("is_error") is None)
                or (
                    event.get("event_type") == "agent.tool.completed"
                    and event.get("tool_outcome") == "unknown"
                )
                for _, event in terminals
            )
            success_status = "unknown" if unknown_terminal else "not_observed"
            success_evidence = terminals[0][0]
            success_source = terminals[0][1].get("source")
        elif observed_items:
            success_status = "unknown"
            success_evidence = None
            success_source = None
        elif stream_complete:
            success_status = "not_observed"
            success_evidence = None
            success_source = "agent_stream"
        else:
            success_status = "unknown"
            success_evidence = None
            success_source = None
        success_expected = True
        if base == "not_observed" and not observed_items:
            advertised_expected = echo_event is not None
            discovery_expected = False
            invoked_status = success_status = "not_applicable"
            invocation_expected = success_expected = False
    rows.extend(
        [
            _checkpoint(
                run_id,
                trial_id,
                "advertised",
                tool,
                advertised_status,
                expected=advertised_expected,
                capture_source=advert_source,
                verification_status=(
                    "direct_observation"
                    if invocation_advertised
                    else "echo_only"
                    if echo_event
                    else "unknown"
                ),
                evidence_reference=advert_evidence,
                reason_code=("api_echo_is_not_remote_discovery" if echo_event else None),
            ),
            _checkpoint(
                run_id,
                trial_id,
                "discovery_confirmed",
                tool,
                discovery_status,
                expected=discovery_expected,
                capture_source=discovery_source,
                verification_status=(
                    "direct_observation" if remote_tools is not None else "unknown"
                ),
                evidence_reference=discovery_evidence,
                reason_code="remote_tool_names_unavailable" if remote_tools is None else None,
            ),
            _checkpoint(
                run_id,
                trial_id,
                "invocation_observed",
                tool,
                invoked_status,
                expected=invocation_expected,
                capture_source=invocation_source,
                verification_status=(
                    "direct_observation" if observed_items else "derived_from_observations"
                ),
                evidence_reference=invocation_evidence,
                reason_code=(
                    "complete_trace_no_call" if invoked_status == "not_observed" else None
                ),
            ),
            _checkpoint(
                run_id,
                trial_id,
                "invocation_succeeded",
                tool,
                success_status,
                expected=success_expected,
                capture_source=success_source,
                verification_status=(
                    "direct_observation" if success_evidence else "derived_from_observations"
                ),
                evidence_reference=success_evidence,
                reason_code=("success_not_observed" if success_status == "not_observed" else None),
            ),
        ]
    )
    return rows, {
        "configured_status": base,
        "advertised_status": advertised_status,
        "discovery_status": discovery_status,
        "invocation_status": invoked_status,
        "success_status": success_status,
    }


def derive_trial_evidence(
    *,
    run_id,
    trial_id,
    task_id,
    record,
    events,
    manifest,
    trace_status,
    telemetry_available,
    manifest_sha256=None,
):
    """Return privacy-safe checkpoint and opportunity rows for one trial."""
    items = _items(events)
    task_annotation = next((task for task in manifest["tasks"] if task["task_id"] == task_id), None)
    if not telemetry_available:
        disabled = record.get("mode") == "without-mcp"
        return [], [
            {
                "run_id": run_id,
                "trial_id": trial_id,
                "opportunity_version": manifest["opportunity_version"],
                "task_id": task_id,
                "opportunity_id": item["opportunity_id"],
                "opportunity_manifest_sha256": manifest_sha256,
                "applicability_status": "not_applicable" if disabled else "unknown",
                "configured_status": "not_applicable" if disabled else "unavailable",
                "visibility_status": "not_applicable" if disabled else "unavailable",
                "discovery_status": "not_applicable" if disabled else "unavailable",
                "invocation_status": "not_applicable" if disabled else "unavailable",
                "success_status": "not_applicable" if disabled else "unavailable",
                "assessment_state": "not_applicable" if disabled else "unknown",
                "adequate_observation": False if disabled else None,
                "utilized": None,
                "missed": None,
                "candidate_calls": None,
                "repeated_calls": None,
                "evidence_class": "unknown",
            }
            for item in (task_annotation or {}).get("opportunities", [])
        ]
    config_event = _first(items, "mcp.exposure.configured")
    echo_event = _first(items, "mcp.exposure.response")
    discovery_event = _first(items, "mcp.discovery.completed")
    mcp_enabled = record.get("mode") == "with-mcp"
    completion = _first(items, "benchmark.trial.completed")
    provider_started = _first(items, "provider.request.started")
    provider_terminal = next(
        (
            (event_id, event)
            for event_id, event in items
            if event.get("event_type") in {"provider.response.received", "provider.request.failed"}
        ),
        None,
    )
    provider_attempted = bool(record.get("session_creation_attempted"))
    turn_completed = any(event.get("event_type") == "agent.turn.completed" for _, event in items)
    stream_complete = trace_status == "complete" and turn_completed
    configured = (
        _list_field(config_event[1], "generated_agent_tool_names") if config_event else None
    )
    if configured is None and config_event:
        configured = _list_field(config_event[1], "configured_allowed_tools")
    observed_tools = {
        event.get("tool")
        for _, event in items
        if event.get("event_type") in {"mcp.tool.started", "mcp.tool.completed", "mcp.tool.failed"}
        and isinstance(event.get("tool"), str)
    }
    task_tools = {
        tool
        for opportunity in (task_annotation or {}).get("opportunities", [])
        for tool in opportunity["candidate_tools"]
    }
    all_tools = sorted((configured or set()) | observed_tools | task_tools)
    remote_tools = None
    if config_event:
        remote_status = config_event[1].get("remote_discovery_status")
        remote_tools = _list_field(config_event[1], "remote_discovered_tools")
        if remote_status == "not_applicable":
            remote_tools = set()
    checkpoint_rows = []
    states_by_tool = {}
    for tool in all_tools:
        rows, states = _tool_checkpoint_set(
            run_id=run_id,
            trial_id=trial_id,
            tool=tool,
            mcp_enabled=mcp_enabled,
            config_event=config_event,
            echo_event=echo_event,
            remote_tools=remote_tools,
            items=items,
            stream_complete=stream_complete,
        )
        checkpoint_rows.extend(rows)
        states_by_tool[tool] = states
    if mcp_enabled:
        list_tools = discovery_event[1].get("list_tools_requests") if discovery_event else None
        if type(list_tools) is int and list_tools >= 0:
            discovery_status = "observed" if list_tools > 0 else "not_observed"
            discovery_source = discovery_event[1].get("source")
            discovery_evidence = discovery_event[0]
            discovery_reason = "server_audit_request_count"
        else:
            discovery_status = "unknown"
            discovery_source = discovery_evidence = None
            discovery_reason = "server_discovery_audit_unavailable"
        checkpoint_rows.append(
            _checkpoint(
                run_id,
                trial_id,
                "discovery_confirmed",
                "server_list_tools_request",
                discovery_status,
                expected=True,
                capture_source=discovery_source,
                verification_status="direct_observation" if discovery_event else "unknown",
                evidence_reference=discovery_evidence,
                reason_code=discovery_reason,
            )
        )
    else:
        checkpoint_rows.append(
            _checkpoint(
                run_id,
                trial_id,
                "discovery_confirmed",
                "server_list_tools_request",
                "not_applicable",
                expected=False,
                reason_code="mcp_disabled",
            )
        )
    if config_event:
        configured_status = "observed"
        configured_source = config_event[1].get("source")
        configured_ref = config_event[0]
    elif mcp_enabled:
        configured_status, configured_source, configured_ref = "unknown", None, None
    else:
        configured_status, configured_source, configured_ref = "not_applicable", None, None
    checkpoint_rows.extend(
        [
            _checkpoint(
                run_id,
                trial_id,
                "trial_started",
                "trial",
                "observed"
                if _first(items, "benchmark.trial.started")
                else ("unknown" if trace_status == "partial" else "unavailable"),
                expected=True,
                capture_source="runner" if _first(items, "benchmark.trial.started") else None,
                verification_status="direct_observation",
                evidence_reference=(
                    _first(items, "benchmark.trial.started")[0]
                    if _first(items, "benchmark.trial.started")
                    else None
                ),
            ),
            _checkpoint(
                run_id,
                trial_id,
                "trial_completed",
                "trial",
                "observed"
                if completion
                else ("unknown" if trace_status == "partial" else "unavailable"),
                expected=True,
                capture_source="runner" if completion else None,
                verification_status="direct_observation" if completion else "unknown",
                evidence_reference=completion[0] if completion else None,
            ),
            _checkpoint(
                run_id,
                trial_id,
                "configured",
                "mcp_session",
                configured_status,
                expected=mcp_enabled,
                capture_source=configured_source,
                verification_status="direct_observation" if config_event else "unknown",
                evidence_reference=configured_ref,
                reason_code="mcp_disabled" if not mcp_enabled else None,
            ),
            _checkpoint(
                run_id,
                trial_id,
                "agent_turn_completed",
                "agent_stream",
                "observed"
                if turn_completed
                else ("unknown" if trace_status == "partial" else "unavailable"),
                expected=True,
                capture_source="agent_stream" if turn_completed else None,
                verification_status="direct_observation" if turn_completed else "unknown",
                evidence_reference=next(
                    (
                        event_id
                        for event_id, event in items
                        if event.get("event_type") == "agent.turn.completed"
                    ),
                    None,
                ),
            ),
            _checkpoint(
                run_id,
                trial_id,
                "provider_session_creation",
                "session_create",
                "not_applicable"
                if not provider_attempted
                else "observed"
                if provider_started and provider_terminal
                else "unknown",
                expected=provider_attempted,
                capture_source="runner" if provider_started or provider_terminal else None,
                verification_status=(
                    "direct_observation" if provider_started and provider_terminal else "unknown"
                ),
                evidence_reference=provider_terminal[0] if provider_terminal else None,
                reason_code=(
                    "provider_terminal_event_missing"
                    if provider_attempted and provider_started and not provider_terminal
                    else None
                ),
            ),
        ]
    )
    opportunity_rows = []
    for opportunity in (task_annotation or {}).get("opportunities", []):
        candidates = opportunity["candidate_tools"]
        if not mcp_enabled:
            applicability = "not_applicable"
            configured_state = visibility_state = discovery_state = invocation_state = (
                success_state
            ) = "not_applicable"
            assessment = "not_applicable"
            adequate = False
            candidate_calls = repeated_calls = None
            utilized = missed = None
        elif config_event is None or configured is None:
            applicability = "unknown"
            configured_state = visibility_state = discovery_state = "unknown"
            invocation_state = success_state = "unknown"
            assessment = "unknown"
            adequate = False
            candidate_calls = repeated_calls = None
            utilized = missed = None
        else:
            configured_candidates = sorted(set(candidates) & configured)
            if not configured_candidates:
                applicability = "not_applicable"
                configured_state = "not_observed"
                visibility_state = "unknown"
                discovery_state = "unknown"
                invocation_state = success_state = "not_applicable"
                assessment = "not_applicable"
                adequate = False
                candidate_calls = repeated_calls = None
                utilized = missed = None
            else:
                applicability = "observed"
                configured_state = "observed"
                candidate_calls_by_tool = Counter()
                candidate_terminal = Counter()
                for tool in configured_candidates:
                    chosen = _observed_tool_events(items, tool)
                    starts = [
                        item
                        for item in chosen
                        if item[1].get("event_type") in {"mcp.tool.started", "agent.tool.started"}
                    ]
                    if starts:
                        candidate_calls_by_tool[tool] = len(starts)
                    else:
                        terminal_only = [
                            item
                            for item in chosen
                            if item[1].get("event_type")
                            in {
                                "mcp.tool.completed",
                                "mcp.tool.failed",
                                "agent.tool.completed",
                                "agent.tool.failed",
                            }
                        ]
                        candidate_calls_by_tool[tool] = len(terminal_only)
                    candidate_terminal[tool] = len(
                        [
                            item
                            for item in chosen
                            if item[1].get("event_type")
                            in {
                                "mcp.tool.completed",
                                "mcp.tool.failed",
                                "agent.tool.completed",
                                "agent.tool.failed",
                            }
                        ]
                    )
                candidate_calls = sum(candidate_calls_by_tool.values())
                repeated_calls = sum(
                    max(0, count - 1) for count in candidate_calls_by_tool.values()
                )
                call_tools = {tool for tool, count in candidate_calls_by_tool.items() if count}
                success_tools = set()
                success_unknown_tools = set()
                for tool in call_tools:
                    states = states_by_tool.get(tool, {})
                    if states.get("success_status") == "observed":
                        success_tools.add(tool)
                    elif states.get("success_status") == "unknown":
                        success_unknown_tools.add(tool)
                invocation_state = (
                    "observed" if call_tools else ("not_observed" if stream_complete else "unknown")
                )
                if success_tools:
                    success_state = "observed"
                elif success_unknown_tools:
                    success_state = "unknown"
                elif sum(candidate_terminal.values()):
                    success_state = "not_observed"
                elif call_tools:
                    success_state = "unknown"
                else:
                    success_state = "not_observed" if stream_complete else "unknown"
                echoed = (
                    _list_field(echo_event[1], "returned_agent_tool_names") if echo_event else None
                )
                if call_tools:
                    visibility_state = "observed"
                elif echoed is None:
                    visibility_state = "unknown"
                else:
                    visibility_state = "observed" if set(candidates) & echoed else "not_observed"
                discovery_state = (
                    "observed"
                    if remote_tools is not None and set(candidates) & remote_tools
                    else "not_observed"
                    if remote_tools is not None
                    else "unknown"
                )
                adequate = stream_complete
                if call_tools:
                    assessment = "utilized"
                    utilized = True
                    missed = False
                elif adequate:
                    assessment = "no_relevant_call_observed"
                    utilized = False
                    missed = visibility_state == "observed"
                else:
                    assessment = "unknown"
                    utilized = missed = None
        opportunity_rows.append(
            {
                "run_id": run_id,
                "trial_id": trial_id,
                "opportunity_version": manifest["opportunity_version"],
                "task_id": task_id,
                "opportunity_id": opportunity["opportunity_id"],
                "opportunity_manifest_sha256": manifest_sha256,
                "applicability_status": applicability,
                "configured_status": configured_state,
                "visibility_status": visibility_state,
                "discovery_status": discovery_state,
                "invocation_status": invocation_state,
                "success_status": success_state,
                "assessment_state": assessment,
                "adequate_observation": adequate,
                "utilized": utilized,
                "missed": missed,
                "candidate_calls": candidate_calls,
                "repeated_calls": repeated_calls,
                "evidence_class": "derived_from_observations",
            }
        )
    return checkpoint_rows, opportunity_rows
