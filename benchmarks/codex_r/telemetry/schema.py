"""Versioned JSONL event schema for benchmark runs (schema_version "1.1").

One JSON object per line. Every event has the common fields below; each event type adds
required fields. Only fields listed in FIELDS are allowed, so free text (arguments, MCP
responses, model reasoning, credentials) cannot enter an event by accident.

Identifiers
    run_id    one complete benchmark invocation (the results directory name)
    trial_id  one execution of one task in one mode (``D01-B-1``); belongs to one run
    trace_id  one execution trace; exactly one per trial and never shared between trials
    call_id   one tool call, unique inside a trial. Client-observed calls are
              ``client-call-NNNN``; server-recorded calls are ``server-call-NNNN``. The
              Agents SDK does not pass a call id to the MCP server, so a server call is
              linked to a client call only by order (``correlation`` is then
              ``ordinal_unconfirmed``) or left ``unmatched``.

Time
    timestamp_utc         wall-clock time the event was observed, in UTC
    monotonic_offset_ms   milliseconds on ``clock`` since that clock's origin
    duration_ms           local duration measured on one clock
    The clocks are independent: ``trial`` (runner), ``run`` (runner) and ``server_process``
    (the MCP server, relative to server start). Offsets from different clocks must not be
    subtracted to estimate cross-container latency.

``validate_event`` and ``validate_stream`` return lists of problems; empty means valid.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

SCHEMA_VERSION = "1.2"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1", SCHEMA_VERSION})

EVENT_TYPES = frozenset(
    {
        "benchmark.run.started",
        "benchmark.run.completed",
        "benchmark.trial.started",
        "benchmark.trial.completed",
        "agent.session.created",
        "agent.turn.started",
        "agent.turn.completed",
        "agent.turn.failed",
        "agent.tool.started",
        "agent.tool.completed",
        "agent.tool.failed",
        "agent.evidence.observed",
        "agent.url.mentioned",
        "agent.answer.claims_observed",
        "provider.request.started",
        "provider.response.received",
        "provider.request.failed",
        "mcp.exposure.configured",
        "mcp.exposure.response",
        "mcp.discovery.started",
        "mcp.discovery.completed",
        "mcp.tool.started",
        "mcp.tool.completed",
        "mcp.tool.failed",
        "artifact.export.completed",
        "scorer.started",
        "scorer.completed",
        "cleanup.started",
        "cleanup.completed",
        "cleanup.failed",
    }
)
RUN_EVENTS = frozenset({"benchmark.run.started", "benchmark.run.completed"})
TOOL_EVENTS = frozenset({"mcp.tool.started", "mcp.tool.completed", "mcp.tool.failed"})
TOOL_TERMINAL = frozenset({"mcp.tool.completed", "mcp.tool.failed"})
AGENT_TOOL_EVENTS = frozenset({"agent.tool.started", "agent.tool.completed", "agent.tool.failed"})

SOURCES = frozenset({"runner", "agent_stream", "agents_api", "mcp_server"})
CLOCKS = frozenset({"run", "trial", "server_process"})

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
SNAKE = re.compile(r"[a-z][a-z0-9_]{0,63}")
UPPER = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
TOOL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}")
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9.]{0,99}")
R_FUNCTION = re.compile(r"[A-Za-z0-9._:<>$@%&*+/=!?|^~-]{1,64}")
FINGERPRINT = re.compile(r"[0-9a-f]{12}")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]{0,39}")


def _int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _number(value: Any) -> bool:
    return type(value) in (int, float) and value >= 0


def _bool(value: Any) -> bool:
    return type(value) is bool


def _match(pattern: re.Pattern) -> Callable[[Any], bool]:
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


def _enum(*values: str) -> Callable[[Any], bool]:
    return lambda value: value in values


def _error(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) <= ERROR_FIELDS
        and {"origin", "category", "reason_code"} <= set(value)
        and all(
            isinstance(value[key], str) and SNAKE.fullmatch(value[key])
            for key in ("origin", "category")
        )
        and isinstance(value["reason_code"], str)
        and UPPER.fullmatch(value["reason_code"]) is not None
        and (value.get("source_code") is None or _match(SNAKE)(value["source_code"]))
        and (value.get("count") is None or _int(value["count"]))
        and (value.get("severity") in (None, "fatal", "recoverable"))
    )


ERROR_FIELDS = frozenset({"origin", "category", "reason_code", "source_code", "count", "severity"})


def _error_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) <= 64 and all(_error(item) for item in value)


def _code_list(value: Any) -> bool:
    return (
        isinstance(value, list) and len(value) <= 8 and all(_match(SNAKE)(item) for item in value)
    )


def _name_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 64
        and all(_match(TOOL_NAME)(item) for item in value)
        and len(value) == len(set(value))
    )


def _claim_id_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 32
        and all(
            isinstance(item, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item) for item in value
        )
        and len(value) == len(set(value))
    )


def _official_url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 512 or "?" in value or "#" in value:
        return False
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(value)
    except ValueError:
        return False
    try:
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname
        in {
            "cran.r-project.org",
            "stat.ethz.ch",
            "bioconductor.org",
            "docs.posit.co",
            "docs.rstudio.com",
        }
        and parts.username is None
        and parts.password is None
        and port is None
        and parts.path.startswith("/")
    )


def _nullable(check: Callable[[Any], bool]) -> Callable[[Any], bool]:
    return lambda value: value is None or check(value)


# Field name -> validator. A field is nullable when the value may be unknown; unknown is
# always null, never zero or false.
FIELDS: dict[str, Callable[[Any], bool]] = {
    # common
    "schema_version": lambda value: value in SUPPORTED_SCHEMA_VERSIONS,
    "event_type": lambda value: value in EVENT_TYPES,
    "run_id": _match(ID),
    "trial_id": _match(ID),
    "trace_id": _match(ID),
    "call_id": _match(ID),
    "timestamp_utc": _match(TIMESTAMP),
    "monotonic_offset_ms": _number,
    "clock": _enum(*CLOCKS),
    "source": _enum(*SOURCES),
    # trial / run description
    "task": _match(ID),
    "mode": _enum("with-mcp", "without-mcp"),
    "model": _match(MODEL),
    "effort": _enum("medium", "high"),
    "repetition": _int,
    "trial_count": _int,
    "status": _match(SNAKE),
    "interrupted": _bool,
    "cleanup_completed": _nullable(_bool),
    "error": _error,
    "primary_error": _nullable(_error),
    "subsequent_errors": _error_list,
    "cleanup_errors": _error_list,
    "mcp_errors": _error_list,
    "api_usage_status": _enum("observed", "unavailable"),
    "api_input_tokens": _nullable(_int),
    "api_output_tokens": _nullable(_int),
    "api_total_tokens": _nullable(_int),
    "cost_status": _enum("observed", "unavailable"),
    # session / discovery / artifacts / scorer / cleanup
    "observation": _match(SNAKE),
    "list_tools_requests": _nullable(_int),
    "artifact_count": _int,
    "scorer_status": _match(SNAKE),
    "scorer_version": _nullable(_match(MODEL)),
    "passed": _nullable(_int),
    "total": _nullable(_int),
    "cleanup_operation": _match(SNAKE),
    "cleanup_status": _enum(
        "confirmed", "failed", "unknown", "skipped", "requested", "not_attempted"
    ),
    "diagnostic": _nullable(_match(SNAKE)),
    "duration_ms": _nullable(_number),
    "provider_operation": _enum("session_create", "turn_submission"),
    "provider_status": _enum("success", "error", "unknown"),
    # MCP tool calls
    "tool": _match(TOOL_NAME),
    "tool_class": _enum("mcp", "tool_search", "web", "browser", "terminal", "file_search", "other"),
    "tool_sequence": lambda value: type(value) is int and value >= 1,
    "tool_outcome": _enum("success", "error", "partial", "unknown"),
    "agent_stream_sequence": _nullable(_int),
    "agent_stream_item_type": _match(SNAKE),
    "exit_code": lambda value: value is None or (type(value) is int and -255 <= value <= 255),
    "registered_tools": _name_list,
    "policy_allowed_tools": _name_list,
    "configured_allowed_tools": _name_list,
    "generated_agent_tool_names": _name_list,
    "remote_discovered_tools": _nullable(_name_list),
    "remote_discovery_status": _enum("observed", "unknown", "not_applicable"),
    "session_config_status": _enum(
        "generated", "response_echo_observed", "response_echo_unavailable"
    ),
    "returned_agent_tool_names": _nullable(_name_list),
    "session_config_match": _nullable(_bool),
    "function_discovery_policy": _enum("enabled", "disabled", "not_applicable"),
    "toolset": _enum("legacy", "consolidated"),
    "server_list_tools_requests": _nullable(_int),
    "source_url": lambda value: _nullable(_official_url)(value),
    "url_role": _enum("source", "documentation", "reference", "unknown"),
    "observation_location": _enum("tool_input", "tool_output", "agent_final_answer"),
    "source_access_status": _enum(
        "mcp_response_observed", "url_mention_only", "unknown", "not_observed"
    ),
    "evidence_source": _enum("mcp_tool_response", "agent_tool_result"),
    "package_version": _nullable(_match(VERSION)),
    "answer_projection_status": _enum("projected", "invalid", "unavailable"),
    "feature_ids": _claim_id_list,
    "caveat_ids": _claim_id_list,
    "client_item_id": _match(ID),
    "server_call_number": _int,
    "correlated_call_id": _nullable(_match(ID)),
    "correlation": _enum("ordinal_unconfirmed", "unmatched"),
    "repository": _nullable(_enum("cran", "bioconductor", "all")),
    "package": _nullable(_match(PACKAGE)),
    "function": _nullable(_match(R_FUNCTION)),
    "is_error": _nullable(_bool),
    "error_codes": _code_list,
    "verification_status": _nullable(_match(SNAKE)),
    "source_count": _nullable(_int),
    "partial": _nullable(_bool),
    "version_mismatch": _nullable(_bool),
    "output_truncated": _nullable(_bool),
    "page_truncated": _nullable(_bool),
    "result_bytes": _nullable(_int),
    "structured_bytes": _nullable(_int),
    "text_content_bytes": _nullable(_int),
    "useful_bytes": _nullable(_int),
    "content_duplicates_structured": _nullable(_bool),
    "result_tokens_estimate": _nullable(_int),
    "request_bytes": _nullable(_int),
    "argument_fingerprint": _nullable(_match(FINGERPRINT)),
    "repeat_kind": _nullable(_enum("first", "identical", "identical_after_error", "similar")),
    "repeat_count": _nullable(_int),
    "cache_hits": _nullable(_int),
    "cache_network_requests": _nullable(_int),
}

COMMON_REQUIRED = frozenset(
    {"schema_version", "event_type", "run_id", "timestamp_utc", "monotonic_offset_ms", "source"}
)
REQUIRED: dict[str, frozenset[str]] = {
    "benchmark.run.started": frozenset({"trial_count"}),
    "benchmark.run.completed": frozenset({"status"}),
    "benchmark.trial.started": frozenset({"trial_id", "trace_id", "task", "mode"}),
    "benchmark.trial.completed": frozenset(
        {"trial_id", "trace_id", "status", "interrupted", "primary_error", "api_usage_status"}
    ),
    "agent.session.created": frozenset({"trial_id", "trace_id"}),
    "agent.turn.started": frozenset({"trial_id", "trace_id"}),
    "agent.turn.completed": frozenset({"trial_id", "trace_id"}),
    "agent.turn.failed": frozenset({"trial_id", "trace_id", "error"}),
    "agent.tool.started": frozenset(
        {"trial_id", "trace_id", "call_id", "tool", "tool_class", "tool_sequence", "tool_outcome"}
    ),
    "agent.tool.completed": frozenset(
        {"trial_id", "trace_id", "call_id", "tool", "tool_class", "tool_sequence", "tool_outcome"}
    ),
    "agent.tool.failed": frozenset(
        {"trial_id", "trace_id", "call_id", "tool", "tool_class", "tool_sequence", "tool_outcome"}
    ),
    "agent.evidence.observed": frozenset(
        {"trial_id", "trace_id", "call_id", "tool", "evidence_source", "source_access_status"}
    ),
    "agent.url.mentioned": frozenset(
        {
            "trial_id",
            "trace_id",
            "call_id",
            "tool",
            "source_url",
            "url_role",
            "observation_location",
            "source_access_status",
        }
    ),
    "agent.answer.claims_observed": frozenset({"trial_id", "trace_id", "answer_projection_status"}),
    "provider.request.started": frozenset(
        {"trial_id", "trace_id", "call_id", "provider_operation"}
    ),
    "provider.response.received": frozenset(
        {
            "trial_id",
            "trace_id",
            "call_id",
            "provider_operation",
            "provider_status",
            "duration_ms",
        }
    ),
    "provider.request.failed": frozenset(
        {
            "trial_id",
            "trace_id",
            "call_id",
            "provider_operation",
            "provider_status",
            "duration_ms",
        }
    ),
    "mcp.exposure.configured": frozenset(
        {
            "trial_id",
            "trace_id",
            "toolset",
            "function_discovery_policy",
            "registered_tools",
            "policy_allowed_tools",
            "configured_allowed_tools",
            "generated_agent_tool_names",
            "remote_discovery_status",
            "session_config_status",
        }
    ),
    "mcp.exposure.response": frozenset(
        {
            "trial_id",
            "trace_id",
            "session_config_status",
            "returned_agent_tool_names",
            "session_config_match",
        }
    ),
    "mcp.discovery.started": frozenset({"trial_id", "trace_id"}),
    "mcp.discovery.completed": frozenset({"trial_id", "trace_id", "observation"}),
    "mcp.tool.started": frozenset({"trial_id", "trace_id", "call_id", "tool"}),
    "mcp.tool.completed": frozenset({"trial_id", "trace_id", "call_id", "tool", "is_error"}),
    "mcp.tool.failed": frozenset({"trial_id", "trace_id", "call_id", "tool", "is_error"}),
    "artifact.export.completed": frozenset({"trial_id", "trace_id", "artifact_count"}),
    "scorer.started": frozenset({"trial_id", "trace_id"}),
    "scorer.completed": frozenset({"trial_id", "trace_id", "scorer_status"}),
    "cleanup.started": frozenset({"trial_id", "trace_id", "cleanup_operation"}),
    "cleanup.completed": frozenset({"trial_id", "trace_id", "cleanup_operation", "cleanup_status"}),
    "cleanup.failed": frozenset({"trial_id", "trace_id", "cleanup_operation", "cleanup_status"}),
}


def validate_event(event: Any) -> list[str]:
    """Return schema problems for one event (an empty list means valid)."""
    if not isinstance(event, dict):
        return ["event must be an object"]
    problems = [f"unknown field: {name}" for name in event if name not in FIELDS]
    event_type = event.get("event_type")
    required = COMMON_REQUIRED | REQUIRED.get(event_type, frozenset())
    problems += [f"missing field: {name}" for name in sorted(required) if name not in event]
    for name, value in event.items():
        check = FIELDS.get(name)
        if check is not None and not check(value):
            problems.append(f"invalid value for {name}")
    if event_type in TOOL_EVENTS and event.get("trace_id") is None:
        problems.append("tool events need a trace_id")
    if event_type in RUN_EVENTS and ("trial_id" in event or "trace_id" in event):
        problems.append("run events must not carry trial_id or trace_id")
    if event.get("event_type") == "mcp.tool.failed" and event.get("is_error") is not True:
        problems.append("mcp.tool.failed requires is_error=true")
    if event.get("event_type") == "mcp.tool.completed" and event.get("is_error") is True:
        problems.append("mcp.tool.completed must not have is_error=true")
    if event.get("event_type") == "agent.tool.failed" and event.get("tool_outcome") != "error":
        problems.append("agent.tool.failed requires tool_outcome=error")
    if event.get("event_type") == "agent.tool.completed" and event.get("tool_outcome") == "error":
        problems.append("agent.tool.completed must not have tool_outcome=error")
    return problems


def validate_stream(events: list[dict]) -> list[str]:
    """Check identifier relations across a whole run: one run, 1:1 trial/trace, unique calls."""
    problems: list[str] = []
    for index, event in enumerate(events):
        problems += [f"event {index}: {problem}" for problem in validate_event(event)]
    runs = {event.get("run_id") for event in events}
    if len(runs) > 1:
        problems.append(f"multiple run_id values: {sorted(map(str, runs))}")
    trace_of: dict[str, str] = {}
    trial_of: dict[str, str] = {}
    for event in events:
        trial, trace = event.get("trial_id"), event.get("trace_id")
        if trial is None and trace is None:
            continue
        if trace_of.setdefault(trial, trace) != trace:
            problems.append(f"trial {trial} has more than one trace_id")
        if trial_of.setdefault(trace, trial) != trial:
            problems.append(f"trace {trace} is shared by several trials")
    terminal: set[tuple[str, str]] = set()
    started: set[tuple[str, str]] = set()
    for event in events:
        if event.get("event_type") not in TOOL_EVENTS | AGENT_TOOL_EVENTS or "call_id" not in event:
            continue
        key = (str(event.get("trial_id")), str(event["call_id"]))
        started_type = (
            "mcp.tool.started" if event["event_type"] in TOOL_EVENTS else "agent.tool.started"
        )
        if event["event_type"] == started_type:
            if key in started:
                problems.append(f"duplicate tool started for {key}")
            started.add(key)
        else:
            if key in terminal:
                problems.append(f"duplicate terminal tool event for {key}")
            terminal.add(key)
    return problems
