"""MCP metrics per trial and per tool, from JSONL events or from older result files.

Definitions are in ``README.md`` next to this module. Unknown is ``None``, never zero: a
metric is ``None`` when no call carried the information it needs.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from .schema import TOOL_TERMINAL

VERSION_CODES = frozenset({"version_mismatch", "requested_version_unavailable"})
TOKEN_METHOD = "ceil(UTF-8 bytes of the serialized MCP result / 4); an estimate, not API usage"
METRIC_COLUMNS = (
    "mcp_calls_attempted",
    "mcp_calls_succeeded",
    "mcp_calls_failed",
    "mcp_calls_partial",
    "mcp_calls_unresolved",
    "mcp_calls_completeness_unknown",
    "mcp_latency_p50_ms",
    "mcp_latency_p95_ms",
    "mcp_latency_observations",
    "mcp_result_bytes_total",
    "mcp_result_bytes_mean",
    "mcp_result_bytes_observations",
    "mcp_unique_payload_bytes_total",
    "mcp_result_tokens_estimate_total",
    "mcp_output_truncation_count",
    "mcp_page_truncation_count",
    "mcp_verified_source_rate",
    "mcp_verified_source_denominator",
    "mcp_version_mismatch_count",
    "mcp_repeated_identical_calls",
    "mcp_repeated_after_error",
    "mcp_similar_calls",
    "mcp_cache_hit_rate",
    "mcp_cache_lookups",
)


def percentile(values, fraction):
    """Linear interpolation between closest ranks of the observed values (None if empty)."""
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def _known(calls, key):
    return [call[key] for call in calls if call.get(key) is not None]


def metrics(calls, client_attempted=0):
    """Metrics for server-recorded ``calls``; ``client_attempted`` counts calls the client saw."""
    attempted = max(len(calls), client_attempted)
    failed = [call for call in calls if call.get("is_error") is True]
    ok = [call for call in calls if call.get("is_error") is False]
    partial_known = [call for call in ok if call.get("partial") is not None]
    partial = [call for call in ok if call.get("partial") is True]
    durations = _known(calls, "duration_ms")
    result_bytes = _known(calls, "result_bytes")
    tokens = _known(calls, "result_tokens_estimate")
    unique = _known(calls, "useful_bytes")
    truncation = _known(calls, "output_truncated")
    page_truncation = _known(calls, "page_truncated")
    statuses = [call for call in calls if call.get("verification_status") is not None]
    verified = [
        call
        for call in statuses
        if call["verification_status"] == "verified" and (call.get("source_count") or 0) >= 1
    ]
    codes_unknown = any(call.get("error_codes") is None for call in failed)
    repeats = _known(calls, "repeat_kind")
    cache_calls = [call for call in calls if call.get("cache_hits") is not None]
    hits = sum(call["cache_hits"] for call in cache_calls)
    lookups = hits + sum(call.get("cache_network_requests") or 0 for call in cache_calls)
    return {
        "mcp_calls_attempted": attempted,
        "mcp_calls_succeeded": len(ok) - len(partial),
        "mcp_calls_failed": len(failed),
        "mcp_calls_partial": len(partial) if partial_known else None,
        "mcp_calls_unresolved": attempted - len(ok) - len(failed),
        "mcp_calls_completeness_unknown": len(ok) - len(partial_known),
        "mcp_latency_p50_ms": percentile(durations, 0.5),
        "mcp_latency_p95_ms": percentile(durations, 0.95),
        "mcp_latency_observations": len(durations),
        "mcp_result_bytes_total": sum(result_bytes) if result_bytes else None,
        "mcp_result_bytes_mean": round(sum(result_bytes) / len(result_bytes), 1)
        if result_bytes
        else None,
        "mcp_result_bytes_observations": len(result_bytes),
        "mcp_unique_payload_bytes_total": sum(unique) if unique else None,
        "mcp_result_tokens_estimate_total": sum(tokens) if tokens else None,
        "mcp_output_truncation_count": (
            sum(1 for flag in truncation if flag)
            if len(truncation) == len(calls) and calls
            else None
        ),
        "mcp_page_truncation_count": (
            sum(1 for flag in page_truncation if flag)
            if len(page_truncation) == len(calls) and calls
            else None
        ),
        "mcp_verified_source_rate": round(len(verified) / len(statuses), 4) if statuses else None,
        "mcp_verified_source_denominator": len(statuses),
        "mcp_version_mismatch_count": None
        if codes_unknown or not calls
        else sum(1 for call in failed if VERSION_CODES & set(call["error_codes"])),
        "mcp_repeated_identical_calls": sum(
            1 for kind in repeats if kind in {"identical", "identical_after_error"}
        )
        if repeats
        else None,
        "mcp_repeated_after_error": sum(1 for kind in repeats if kind == "identical_after_error")
        if repeats
        else None,
        "mcp_similar_calls": sum(1 for kind in repeats if kind == "similar") if repeats else None,
        "mcp_cache_hit_rate": round(hits / lookups, 4) if lookups else None,
        "mcp_cache_lookups": lookups if cache_calls else None,
    }


def calls_from_events(events):
    """(server calls, client calls) from normalized events.

    Client calls are merged by ``call_id``: a start without a terminal event is a call the
    client saw begin whose outcome is unknown (``is_error`` None), e.g. after Ctrl+C.
    """
    server, client = [], {}
    for event in events:
        kind = event.get("event_type")
        if kind not in TOOL_TERMINAL and kind != "mcp.tool.started":
            continue
        if event.get("source") != "mcp_server":
            entry = client.setdefault(
                event.get("call_id"), {"tool": event["tool"], "is_error": None}
            )
            if kind in TOOL_TERMINAL:
                entry["is_error"] = event.get("is_error")
            continue
        if kind not in TOOL_TERMINAL:
            continue
        server.append(
            {
                "tool": event["tool"],
                "is_error": event.get("is_error"),
                "duration_ms": event.get("duration_ms"),
                **{
                    key: event.get(key)
                    for key in (
                        "partial",
                        "result_bytes",
                        "useful_bytes",
                        "result_tokens_estimate",
                        "output_truncated",
                        "page_truncated",
                        "error_codes",
                        "verification_status",
                        "source_count",
                        "repeat_kind",
                        "cache_hits",
                        "cache_network_requests",
                    )
                },
            }
        )
    return server, list(client.values())


def calls_from_legacy_record(record):
    """Server calls from a result.json written before JSONL; absent facts stay unknown.

    The old log had no completeness, source, repeat or cache information, and its
    ``truncated`` flag also covered paging, so only ``truncated=False`` is trusted.
    """
    legacy = (record.get("mcp_telemetry") or {}).get("calls") or []
    calls = []
    for item in legacy:
        code = item.get("error_code")
        failed = item.get("status") == "error"
        calls.append(
            {
                "tool": item["tool_name"],
                "is_error": failed,
                "duration_ms": item.get("duration_ms"),
                "result_bytes": item.get("response_bytes"),
                "result_tokens_estimate": item.get("response_tokens_estimate"),
                "output_truncated": False if item.get("truncated") is False else None,
                "page_truncated": False if item.get("truncated") is False else None,
                "error_codes": item["error_codes"]
                if item.get("error_codes") is not None
                else ([code] if code else None if failed else []),
                "partial": None,
                "verification_status": None,
                "source_count": None,
                "repeat_kind": None,
                "cache_hits": None,
                "cache_network_requests": None,
                "useful_bytes": None,
            }
        )
    return calls


def api_usage(record):
    usage = record.get("usage") if isinstance(record.get("usage"), dict) else None
    return {
        "status": record.get("usage_status", "unavailable"),
        "input_tokens": (usage or {}).get("input_tokens"),
        "output_tokens": (usage or {}).get("output_tokens"),
        "total_tokens": (usage or {}).get("total_tokens"),
        "cost_status": record.get("cost_status", "unavailable"),
        "cost": record.get("cost"),
        "note": "Billed API usage only; result_tokens_estimate fields are separate estimates.",
    }


def trial_calls(record, events=()):
    """(outcome calls, client-observed calls per tool, source) for one trial.

    Server-recorded calls are the outcome source. Without them, an old result's server log is
    used, then the client's own item statuses; nothing is guessed beyond that.
    """
    server, client = calls_from_events(events)
    source = "telemetry_jsonl"
    if not server:
        server = calls_from_legacy_record(record)
        source = "legacy_server_log" if server else "none"
    if not server and client:
        # The server log was never collected: item statuses are the only observation, and
        # completeness plus every server-only fact stay unknown.
        server, client, source = [dict(call) for call in client], [], "agent_stream_only"
    client_by_tool = defaultdict(int)
    for call in client:
        client_by_tool[call["tool"]] += 1
    if not client and not events:
        for tool, count in ((record.get("mcp_usage") or {}).get("calls_by_tool") or {}).items():
            client_by_tool[tool] += count
    return server, client_by_tool, source


def summarize_trial(record, events=()):
    """Overall and per-tool metrics of one trial, from JSONL events when they exist."""
    server, client_by_tool, source = trial_calls(record, events)
    tools = sorted({call["tool"] for call in server} | set(client_by_tool))
    return {
        "trial_id": record.get("trial_id"),
        "mode": record.get("mode"),
        "source": source,
        "overall": metrics(server, sum(client_by_tool.values())),
        "by_tool": {
            tool: metrics(
                [call for call in server if call["tool"] == tool], client_by_tool.get(tool, 0)
            )
            for tool in tools
        },
        "api_usage": api_usage(record),
        "token_estimate_method": TOKEN_METHOD,
    }


def summarize_run(records, events=()):
    """Per-trial summaries plus metrics per tool over every trial of the run."""
    by_trial = defaultdict(list)
    for event in events:
        by_trial[event.get("trial_id")].append(event)
    trials = [summarize_trial(r, by_trial.get(r.get("trial_id"), ())) for r in records]
    pooled, attempted = defaultdict(list), defaultdict(int)
    for record, summary in zip(records, trials, strict=True):
        server, _, _ = trial_calls(record, by_trial.get(record.get("trial_id"), ()))
        for call in server:
            pooled[call["tool"]].append(call)
        for tool, values in summary["by_tool"].items():
            attempted[tool] += values["mcp_calls_attempted"]
    return {
        "trials": trials,
        "by_tool": {
            tool: metrics(calls, attempted[tool]) for tool, calls in sorted(pooled.items())
        },
    }


def metric_rows(summary):
    """Flat rows (one per trial and tool, tool ``*`` = all tools) for CSV export."""
    rows = []
    for trial in summary:
        for tool, values in (("*", trial["overall"]), *sorted(trial["by_tool"].items())):
            rows.append(
                {
                    "trial_id": trial["trial_id"],
                    "mode": trial["mode"],
                    "tool": tool,
                    "metrics_source": trial["source"],
                    **values,
                }
            )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aggregate MCP metrics of a finished run")
    parser.add_argument("run_dir")
    parser.add_argument("--output", help="write the JSON report to this file")
    args = parser.parse_args(argv)
    run = Path(args.run_dir)
    records = json.loads((run / "results.json").read_text(encoding="utf-8"))
    path = run / "telemetry.jsonl"
    events = (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        if path.is_file()
        else []
    )
    report = summarize_run(records, events)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
