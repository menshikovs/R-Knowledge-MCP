"""Read-only Streamlit dashboard. Launch: python -m benchmarks.codex_r.analytics.dashboard"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from benchmarks.codex_r.analytics import DEFAULT_DATABASE, DEFAULT_RESULTS
from benchmarks.codex_r.analytics.import_results import connect
from benchmarks.codex_r.analytics.queries import (
    adoption_by_task,
    agent_telemetry,
    agent_traces,
    artifact_preview,
    audit_classifications,
    compare_runs,
    csv_export,
    default_run_id,
    markdown_export,
    observability_checkpoints,
    opportunity_assessments,
    opportunity_registry,
    run_catalog,
    run_metrics,
    tool_effectiveness,
    trace_spans,
    trials_frame,
)

TABS = (
    "Overview",
    "Adoption by Task",
    "Tool Effectiveness",
    "Scorer & Evidence",
    "Compare Runs",
    "Agent & Evidence",
)


def _missing(value):
    if value is None:
        return True
    return isinstance(value, float) and math.isnan(value)


def _show(value, fallback="Unavailable"):
    if _missing(value):
        return fallback
    return str(value)


def _json(value, fallback=None):
    if not isinstance(value, str):
        return fallback
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return fallback


def _ratio(passed, total):
    return (
        f"{int(passed)}/{int(total)}"
        if not _missing(passed) and not _missing(total)
        else "Unavailable"
    )


def _scorer_badge(connection, run_id):
    values = connection.execute(
        "SELECT DISTINCT scorer_version FROM trials WHERE run_id=? AND scorer_version IS NOT NULL",
        [run_id],
    ).fetchall()
    generations = {
        "V2"
        if "knowledge-pilot-v2" in str(row[0]).casefold() or str(row[0]).casefold().endswith("-v2")
        else "V1"
        for row in values
    }
    if len(generations) > 1:
        return "Mixed V1/V2"
    return next(iter(generations), "Unavailable")


def _run_label(row, scorer):
    created = _show(row.get("created_at_utc"))
    created = created[:10] if created != "Unavailable" else created
    suite_value = row.get("suite_label")
    suite = _show(row.get("benchmark_suite") if _missing(suite_value) else suite_value)
    tasks = len(_json(row.get("tasks_json"), []) or [])
    trials = _show(row.get("observed_trials"))
    experiment = f" | {row.get('experiment_id')}" if row.get("experiment_id") else ""
    return (
        f"{row.run_id} | {created} | {suite} | {_show(row.get('model'))}/"
        f"{_show(row.get('effort'))} | {tasks if tasks else 'Unavailable'} tasks / "
        f"{trials} trials{experiment} | {scorer} | {_show(row.get('full_status'), 'unknown')}"
    )


def table(frame, name, *, key=None):
    if frame is None or frame.empty:
        st.info("No data recorded for this selection.")
        return
    st.dataframe(frame, hide_index=True, width="stretch")
    left, right = st.columns(2)
    key = key or name
    left.download_button(
        "CSV",
        csv_export(frame),
        f"{name}.csv",
        "text/csv",
        key=f"csv-{key}",
    )
    right.download_button(
        "Markdown",
        markdown_export(frame),
        f"{name}.md",
        "text/markdown",
        key=f"md-{key}",
    )


def _markdown_report(title, run_id, metadata, metrics, warnings=()):
    fields = [
        ("Timestamp", metadata.get("created_at_utc")),
        ("Benchmark suite", metadata.get("benchmark_suite")),
        ("Model", metadata.get("model")),
        ("Reasoning effort", metadata.get("effort")),
        ("Scorer generation", _show(metrics.get("score_generations"))),
        ("Run status", metadata.get("full_status")),
    ]
    summary = "\n".join(f"- **{name}:** {_show(value)}" for name, value in fields)
    warning_block = (
        "\n".join(f"- {value}" for value in warnings) or "- No compatibility warning recorded."
    )
    return (
        f"# {title}\n\nRun ID: `{run_id}`\n\n{summary}\n\n"
        f"## Metrics\n\n{markdown_export(pd.DataFrame([metrics]))}\n\n"
        f"## Warnings and limits\n\n{warning_block}\n\n"
        "Metrics describe the saved trials. They do not prove a causal effect. "
        "Missing usage, cost, calls, or pairing data remains unavailable."
    )


def _metadata_frame(row, frame, connection):
    tasks = _json(row.get("tasks_json"), None)
    modes = _json(row.get("conditions_json"), None)
    scorer_versions = _json(row.get("scorer_versions_json"), None)
    environment = _json(row.get("environment_json"), None)
    registered = _json(row.get("registered_tools_json"), None)
    allowed = _json(row.get("allowed_tools_json"), None)
    config = {
        "Run ID": row.get("run_id"),
        "Experiment": row.get("experiment_id"),
        "Experiment version": row.get("experiment_version"),
        "Timestamp (UTC)": row.get("created_at_utc"),
        "Benchmark suite": row.get("benchmark_suite"),
        "Suite label": row.get("suite_label"),
        "Model": row.get("model"),
        "Reasoning effort": row.get("effort"),
        "Tasks": len(tasks) if isinstance(tasks, list) else None,
        "Trials observed / planned": (
            f"{_show(row.get('observed_trials'))} / {_show(row.get('trial_plan_count'))}"
        ),
        "Repetitions": row.get("repetitions"),
        "Conditions": ", ".join(modes) if isinstance(modes, list) and modes else None,
        "Scorer version(s)": json.dumps(scorer_versions, ensure_ascii=False, sort_keys=True)
        if scorer_versions
        else None,
        "MCP toolset": row.get("toolset"),
        "Registered tools": ", ".join(registered) if isinstance(registered, list) else None,
        "Allowed tools": ", ".join(allowed) if isinstance(allowed, list) else None,
        "Source digest": row.get("source_sha256"),
        "Repository revision": row.get("revision"),
        "Configuration digest": row.get("dirty_fingerprint"),
        "Environment": json.dumps(environment, ensure_ascii=False, sort_keys=True)
        if environment
        else None,
        "Technical completion": row.get("completion_state"),
        "Full-scope status": row.get("full_status"),
        "Full-scope reason": row.get("full_status_reason"),
        "Trial plan status": row.get("trial_plan_status"),
        "V1 telemetry": "present" if row.get("jsonl_present") else "unavailable",
        "V1 telemetry complete": row.get("jsonl_complete"),
        "V2 projection schema": row.get("v2_observation_schema"),
        "V2 projection status": row.get("v2_observation_status"),
        "Scorer generation in trials": _scorer_badge(connection, row["run_id"]),
        "API usage": f"observed in {frame.api_total_tokens.notna().sum()}/{len(frame)} trials"
        if not frame.empty
        else None,
        "API cost": f"observed in {frame.cost_amount.notna().sum()}/{len(frame)} trials"
        if not frame.empty
        else None,
        "Experiment metadata": row.get("experiment_metadata_json"),
    }
    return pd.DataFrame([{"Field": key, "Value": _show(value)} for key, value in config.items()])


def _score_sources(connection, run_id):
    rows = connection.execute(
        "SELECT DISTINCT revision_id,scorer_version,report_path FROM scoring_revisions "
        "WHERE run_id=? ORDER BY scorer_version,report_path",
        [run_id],
    ).fetchall()
    return {row[0]: f"{row[1]} · {row[2]}" for row in rows}


def _adoption_display(frame):
    if frame.empty:
        return frame
    display = frame.copy()
    display["delta_label"] = display.delta_checks.map(
        lambda value: "Unavailable" if _missing(value) else f"{int(value):+d} checks"
    )
    for column in ("fully_correct_a", "fully_correct_b", "mcp_available", "mcp_called"):
        display[column] = display[column].map(
            lambda value: "Unknown" if _missing(value) else "Yes" if bool(value) else "No"
        )
    display["tool_discovery_observed"] = display.tool_discovery_observed.map(
        lambda value: "Unknown" if _missing(value) else value
    )
    return display.rename(
        columns={
            "task_id": "Task",
            "trial_ids_a": "Trial ID A",
            "trial_ids_b": "Trial ID B",
            "score_a": "Score A",
            "score_b": "Score B",
            "delta_label": "Delta",
            "fully_correct_a": "Fully Correct A",
            "fully_correct_b": "Fully Correct B",
            "mcp_available": "MCP Available",
            "tool_discovery_observed": "Tool Discovery Observed",
            "mcp_called": "MCP Called",
            "mcp_calls": "MCP Calls",
            "mcp_errors": "MCP Errors",
            "tools_used": "Tools Used",
            "duration_a_seconds": "Duration A (seconds)",
            "duration_b_seconds": "Duration B (seconds)",
            "evidence_status": "Evidence Status",
            "call_observation": "Call Observation",
            "matched_repetitions": "Matched Repetitions",
            "planned_repetitions": "Planned Repetitions",
            "scorer_generation": "Scorer Generation",
            "run_id": "Run ID",
        }
    )[
        [
            "Run ID",
            "Task",
            "Trial ID A",
            "Trial ID B",
            "Score A",
            "Score B",
            "Delta",
            "Fully Correct A",
            "Fully Correct B",
            "MCP Available",
            "Tool Discovery Observed",
            "MCP Called",
            "MCP Calls",
            "MCP Errors",
            "Tools Used",
            "Duration A (seconds)",
            "Duration B (seconds)",
            "Evidence Status",
            "Call Observation",
            "Matched Repetitions",
            "Planned Repetitions",
            "Scorer Generation",
        ]
    ]


def _filtered_tasks(frame, selection):
    if selection == "MCP called":
        return frame[frame.mcp_called == True]  # noqa: E712
    if selection == "No MCP calls":
        return frame[frame.mcp_called == False]  # noqa: E712
    if selection == "Quality improved":
        return frame[frame.delta_checks > 0]
    if selection == "Quality unchanged":
        return frame[frame.delta_checks == 0]
    if selection == "Quality worsened":
        return frame[frame.delta_checks < 0]
    if selection == "Fully correct in B":
        return frame[frame.fully_correct_b == True]  # noqa: E712
    if selection == "Partially/incorrectly solved in B":
        return frame[frame.fully_correct_b == False]  # noqa: E712
    return frame


def _render_overview(connection, row, frame, run_id, scoring_id):
    metrics = run_metrics(connection, run_id, scoring_id=scoring_id)
    if metrics.get("experiment_id") == "b1-discovery":
        _render_b1_overview(connection, row, metrics, run_id)
        return
    if metrics["full_status"] != "full_comparable":
        st.warning(
            f"Selected run is {metrics['full_status'] or 'unknown'} "
            f"({metrics['full_status_reason'] or 'scope not established'}). "
            "Scores and call counts below are observations from this run only."
        )
    for warning in metrics["ab_warnings"]:
        st.warning(warning)
    if metrics["ab_comparable"]:
        st.caption(
            "A/B is paired within this Run ID by task, repetition, model, effort, instructions, "
            "configuration and scorer."
        )
    elif metrics["ab_warnings"]:
        st.info("A/B score delta is unavailable until the run has complete, compatible pairs.")

    quality = st.columns(4)
    quality[0].metric(
        "Passed checks A", _ratio(metrics["passed_checks_a"], metrics["total_checks_a"])
    )
    quality[1].metric(
        "Passed checks B", _ratio(metrics["passed_checks_b"], metrics["total_checks_b"])
    )
    quality[2].metric(
        "Delta B − A",
        f"{metrics['delta_checks']:+d} checks"
        if metrics["delta_checks"] is not None
        else "Unavailable",
    )
    quality[3].metric(
        "Fully correct A / B",
        f"{_ratio(metrics['fully_correct_a'], metrics['fully_correct_a_denominator'])} / "
        f"{_ratio(metrics['fully_correct_b'], metrics['fully_correct_b_denominator'])}",
    )
    st.subheader("Quality")
    st.caption(
        "Passed checks preserve the recorded denominators. Fully correct counts use known "
        "paired task outcomes."
    )
    score_chart = pd.DataFrame(
        [
            {"Condition": "Without MCP (A)", "Passed checks": metrics["passed_checks_a"]},
            {"Condition": "With MCP (B)", "Passed checks": metrics["passed_checks_b"]},
        ]
    ).dropna()
    if not score_chart.empty:
        st.bar_chart(score_chart, x="Condition", y="Passed checks")

    st.subheader("MCP behavior")
    behavior = st.columns(4)
    adoption_value = (
        f"{metrics['mcp_adoption_numerator']}/{metrics['mcp_adoption_denominator']} "
        f"({metrics['mcp_adoption']:.1%})"
        if metrics["mcp_adoption"] is not None
        else (
            f"Unavailable ({metrics['mcp_adoption_observations']}/"
            f"{metrics['mcp_adoption_denominator']} observed)"
        )
    )
    behavior[0].metric("MCP adoption", adoption_value)
    behavior[1].metric("MCP calls", _show(metrics["mcp_calls"]))
    behavior[2].metric("MCP errors", _show(metrics["mcp_errors"]))
    behavior[3].metric(
        "Error rate",
        f"{metrics['mcp_error_rate']:.1%}"
        if metrics["mcp_error_rate"] is not None
        else "Unavailable",
    )
    st.caption(
        "Adoption = tasks with at least one recorded MCP call / tasks assigned with MCP. "
        "Failed calls still count as attempts. tools/list discovery is reported separately "
        "from agent tool calls."
    )

    st.subheader("Efficiency and recorded usage")
    efficiency = st.columns(4)
    used_tasks = metrics["mcp_adoption_numerator"] or 0
    calls_per_used = (
        metrics["mcp_calls"] / used_tasks
        if metrics["mcp_calls"] is not None and used_tasks
        else None
    )
    efficiency[0].metric(
        "Calls per MCP-using task",
        f"{calls_per_used:.2f}" if calls_per_used is not None else "Unavailable",
    )
    efficiency[1].metric("Exact repeated calls", _show(metrics["exact_repeats"]))
    efficiency[2].metric(
        "Mean task duration B",
        f"{metrics['duration_b_seconds_mean']:.1f} s"
        if metrics["duration_b_seconds_mean"] is not None
        else "Unavailable",
    )
    efficiency[3].metric(
        "API usage B",
        f"{metrics['api_tokens_b']:,} tokens "
        f"({metrics['api_usage_observations_b']}/{metrics['api_usage_trials_b']})"
        if metrics["api_tokens_b"] is not None
        else (
            f"Unavailable ({metrics['api_usage_observations_b']}/"
            f"{metrics['api_usage_trials_b']} trials)"
        ),
    )
    costs = metrics["observed_costs_b"]
    cost_text = ", ".join(
        f"{amount:g} {currency or '(currency unavailable)'}" for currency, amount in costs.items()
    )
    st.caption(
        f"Observed API cost B: {cost_text} "
        f"({metrics['cost_observations_b']}/{metrics['cost_trials_b']} trials)"
        if costs
        else (
            f"Observed API cost B: Unavailable ({metrics['cost_observations_b']}/"
            f"{metrics['cost_trials_b']} trials). Missing usage and cost are not zero."
        )
    )

    tool_summary, _calls = tool_effectiveness(connection, run_id)
    if not tool_summary.empty:
        st.subheader("Observed tool distribution")
        st.bar_chart(tool_summary, x="tool_name", y="total_calls")
    st.caption(
        "No combined MCP effectiveness score is calculated. Adoption, answer quality, "
        "errors, latency and usage remain separate measures."
    )

    export_row = {
        "run_id": run_id,
        "created_at_utc": row.get("created_at_utc"),
        "benchmark_suite": row.get("benchmark_suite"),
        "model": row.get("model"),
        "effort": row.get("effort"),
        "scorer_generation": ", ".join(metrics["score_generations"]) or "Unavailable",
        "passed_a": metrics["passed_checks_a"],
        "total_a": metrics["total_checks_a"],
        "passed_b": metrics["passed_checks_b"],
        "total_b": metrics["total_checks_b"],
        "delta_checks": metrics["delta_checks"],
        "fully_correct_a": metrics["fully_correct_a"],
        "fully_correct_b": metrics["fully_correct_b"],
        "mcp_adoption_numerator": metrics["mcp_adoption_numerator"],
        "mcp_adoption_denominator": metrics["mcp_adoption_denominator"],
        "mcp_calls": metrics["mcp_calls"],
        "mcp_errors": metrics["mcp_errors"],
        "mcp_error_rate": metrics["mcp_error_rate"],
        "duration_b_seconds_mean": metrics["duration_b_seconds_mean"],
        "api_tokens_b": metrics["api_tokens_b"],
        "observed_costs_b": json.dumps(costs, ensure_ascii=False, sort_keys=True),
    }
    left, right = st.columns(2)
    left.download_button(
        "Export selected run overview CSV",
        csv_export(pd.DataFrame([export_row])),
        f"{run_id}-overview.csv",
        "text/csv",
        key="overview-csv",
    )
    right.download_button(
        "Export selected run overview Markdown",
        _markdown_report("Selected run overview", run_id, row, metrics, metrics["ab_warnings"]),
        f"{run_id}-overview.md",
        "text/markdown",
        key="overview-md",
    )


def _render_b1_overview(connection, row, metrics, run_id):
    st.caption(
        "Both conditions receive the same MCP tools. Control and Treatment differ only in "
        "the server-level description; scores are paired within each task and scorer."
    )
    conditions = pd.DataFrame(metrics["condition_metrics"])
    st.subheader("Control and Treatment observations")
    table(conditions, f"{run_id}-b1-conditions", key="b1-conditions")
    scores = pd.DataFrame(metrics["task_score_pairs"])
    st.subheader("Paired task scores")
    st.caption(
        "No score totals are pooled across tasks because C01 uses the legacy scorer while "
        "D01 and D03 use knowledge-pilot-v2."
    )
    table(scores, f"{run_id}-b1-task-scores", key="b1-task-scores")
    tool_summary, _calls = tool_effectiveness(connection, run_id)
    if not tool_summary.empty:
        st.subheader("Observed tool distribution by condition")
        table(tool_summary, f"{run_id}-b1-tools", key="b1-tools")
        chart = tool_summary.pivot_table(
            index="tool_name", columns="condition", values="total_calls", aggfunc="sum"
        ).fillna(0)
        st.bar_chart(chart)
    st.caption(
        "Missing token usage, cost, call counts, errors or duration remains unavailable; "
        "an observed zero is retained as zero. Server instructions do not require MCP use."
    )
    st.download_button(
        "Export B1 condition metrics CSV",
        csv_export(conditions),
        f"{run_id}-b1-conditions.csv",
        "text/csv",
        key="b1-conditions-csv",
    )


def _render_adoption(connection, run_id, scoring_id, selected_tasks, task_filter):
    data = adoption_by_task(connection, run_id, scoring_id=scoring_id)
    if selected_tasks:
        data = data[data.task_id.isin(selected_tasks)]
    if "condition_a" in data:
        display = data.rename(
            columns={
                "task_id": "Task",
                "condition_a": "Condition A",
                "condition_b": "Condition B",
                "trial_ids_a": "Control trial IDs",
                "trial_ids_b": "Treatment trial IDs",
                "score_a": "Control score",
                "score_b": "Treatment score",
                "delta_checks": "Treatment minus Control (checks)",
                "delta_score": "Treatment minus Control (normalized)",
                "scorer_identity": "Scorer",
                "scorer_generation": "Scorer generation",
                "matched_repetitions": "Matched repetitions",
                "planned_repetitions": "Planned repetitions",
                "mcp_calls_control": "Control MCP calls",
                "mcp_calls_treatment": "Treatment MCP calls",
                "mcp_errors_control": "Control MCP errors",
                "mcp_errors_treatment": "Treatment MCP errors",
                "docs_not_found_control": "Control docs_not_found",
                "docs_not_found_treatment": "Treatment docs_not_found",
                "exact_repeats_control": "Control exact repeats",
                "exact_repeats_treatment": "Treatment exact repeats",
                "duration_mean_control": "Control mean duration (seconds)",
                "duration_mean_treatment": "Treatment mean duration (seconds)",
            }
        )
        table(display, f"{run_id}-b1-adoption-by-task", key="b1-adoption")
        return
    data = _filtered_tasks(data, task_filter)
    st.caption(
        "Calls=0 means only that no call was observed. The agent’s reason is unknown. "
        "Server tools/list discovery is shown separately and is not counted as agent "
        "tool choice."
    )
    table(_adoption_display(data), f"{run_id}-adoption-by-task", key="adoption")


def _render_tools(connection, run_id, selected_tasks):
    summary, calls = tool_effectiveness(connection, run_id)
    if selected_tasks and not calls.empty and calls.task_id.notna().any():
        calls = calls[calls.task_id.isin(selected_tasks)]
        summary, _ = _summarize_filtered_calls(calls)
    elif selected_tasks and not calls.empty:
        st.info(
            "The saved V2 projection has no task IDs, so the task filter cannot be applied "
            "to these calls."
        )
    if calls.empty:
        st.info("No MCP call telemetry recorded for this run.")
        return
    if calls.telemetry_version.eq("2.0").all():
        st.info(
            "V2 projections are run-level only; the saved schema has no trial/task IDs. "
            "Calls are not assigned to individual tasks."
        )
    st.caption(
        "One canonical source is used per run. V1 uses counted server/legacy rows; V2 uses "
        "client observations plus unmatched server rows. Ordinal-linked V2 server rows "
        "are not counted again."
    )
    st.caption(
        "An application error such as docs_not_found is a recorded tool outcome; it may be "
        "a correct not-found response and does not by itself mean the server malfunctioned."
    )
    table(summary, f"{run_id}-tool-effectiveness", key="tool-effectiveness")
    if not summary.empty:
        st.bar_chart(summary, x="tool_name", y=["successful_calls", "application_errors"])
    if calls.task_id.notna().any():
        by_task = calls.groupby("task_id", as_index=False).size().rename(columns={"size": "calls"})
        st.bar_chart(by_task, x="task_id", y="calls")
    else:
        st.caption("Calls by task: unavailable for V2 run-level projections.")
    latency = calls[calls.server_duration_ms.notna()]
    if not latency.empty:
        histogram = (
            latency.server_duration_ms.value_counts(bins=min(10, len(latency)))
            .sort_index()
            .rename_axis("Server latency range (ms)")
            .reset_index(name="Calls")
        )
        # Altair cannot infer a Vega-Lite type from pandas IntervalDtype.
        # Keep the actual ranges as readable categorical labels in this chart.
        histogram["Server latency range (ms)"] = histogram["Server latency range (ms)"].astype(str)
        st.bar_chart(histogram, x="Server latency range (ms)", y="Calls")
    else:
        st.caption(
            "Server latency distribution unavailable; V2 client durations are not relabeled "
            "as server duration."
        )

    options = ["All tools", *sorted(calls.tool_name.dropna().unique().tolist())]
    selected_tool = st.selectbox("Inspect calls for tool", options, key="tool-drilldown")
    detail = calls if selected_tool == "All tools" else calls[calls.tool_name == selected_tool]
    detail = detail.copy()
    detail["application_status"] = detail.is_error.map(
        lambda value: "Unknown" if _missing(value) else "Error" if bool(value) else "Success"
    )
    detail["error_codes"] = detail.error_codes_json.map(_error_codes)
    detail["exact_repeat"] = detail.repeat_kind.map(
        lambda value: (
            "Unknown"
            if _missing(value)
            else "Yes"
            if value in {"identical", "identical_after_error"}
            else "No"
        )
    )
    columns = [
        "run_id",
        "task_id",
        "trial_id",
        "call_sequence",
        "tool_name",
        "application_status",
        "error_codes",
        "request_fingerprint",
        "exact_repeat",
        "package_name",
        "repository",
        "function_name",
        "request_bytes",
        "result_bytes",
        "server_duration_ms",
        "client_duration_ms",
        "repeat_count",
        "verification_status",
        "source_count",
        "event_evidence_reference",
        "correlation_quality",
        "request_projection_json",
        "response_projection_json",
    ]
    table(
        detail[[column for column in columns if column in detail]],
        f"{run_id}-tool-calls",
        key="tool-calls",
    )


def _render_agent_observability(connection, run_id, selected_tasks):
    observations = agent_telemetry(connection, run_id)
    if selected_tasks and not observations.empty:
        trial_rows = connection.execute(
            "SELECT trial_id,task_id FROM trials WHERE run_id=?", [run_id]
        ).fetchall()
        selected_trial_ids = {
            trial_id for trial_id, task_id in trial_rows if task_id in selected_tasks
        }
        observations = observations[
            observations.trial_id.isna() | observations.trial_id.isin(selected_trial_ids)
        ]
    if observations.empty:
        st.info(
            "Agent/evidence projections are unavailable for this run. Older runs remain "
            "importable; missing telemetry is not a measured zero."
        )
        return

    exposure = observations[observations.event_type == "mcp.exposure.configured"]
    if exposure.empty:
        st.caption("Tool exposure configuration was not recorded by this telemetry version.")
    else:
        display = exposure.copy()
        for column in (
            "registered_tools",
            "policy_allowed_tools",
            "configured_allowed_tools",
            "generated_agent_tool_names",
            "remote_discovered_tools",
        ):
            if column in display:
                display[column] = display[column].map(
                    lambda value: (
                        json.dumps(value, ensure_ascii=False)
                        if isinstance(value, list)
                        else "unknown"
                        if _missing(value)
                        else value
                    )
                )
        table(
            display[
                [
                    column
                    for column in (
                        "trial_id",
                        "toolset",
                        "function_discovery_policy",
                        "registered_tools",
                        "policy_allowed_tools",
                        "configured_allowed_tools",
                        "generated_agent_tool_names",
                        "remote_discovery_status",
                        "remote_discovered_tools",
                        "session_config_status",
                    )
                    if column in display
                ]
            ],
            f"{run_id}-tool-exposure",
            key="agent-tool-exposure",
        )
    response_echo = observations[observations.event_type == "mcp.exposure.response"]
    if not response_echo.empty:
        echo = response_echo.copy()
        if "returned_agent_tool_names" in echo:
            echo["returned_agent_tool_names"] = echo["returned_agent_tool_names"].map(
                lambda value: (
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, list)
                    else "unknown"
                    if _missing(value)
                    else value
                )
            )
        table(
            echo[
                [
                    column
                    for column in (
                        "trial_id",
                        "session_config_status",
                        "returned_agent_tool_names",
                        "session_config_match",
                    )
                    if column in echo
                ]
            ],
            f"{run_id}-session-config-echo",
            key="session-config-echo",
        )
    else:
        st.caption("Agents API session-tool response echo was unavailable or not recorded.")

    calls = observations[
        observations.event_type.isin(
            {"agent.tool.started", "agent.tool.completed", "agent.tool.failed"}
        )
    ]
    if calls.empty:
        st.caption("No agent tool lifecycle items were observed; coverage may be incomplete.")
    else:
        terminal = calls[calls.event_type != "agent.tool.started"]
        if terminal.empty:
            st.caption("Tool starts were observed, but no terminal tool outcomes were recorded.")
        else:
            summary = (
                terminal.groupby(["tool_class", "tool", "tool_outcome"], dropna=False)
                .size()
                .reset_index(name="observations")
            )
            table(summary, f"{run_id}-agent-tool-usage", key="agent-tool-usage")

    answers = observations[observations.event_type == "agent.answer.claims_observed"].copy()
    facts = observations[observations.event_type == "agent.evidence.observed"].copy()
    if answers.empty and facts.empty:
        st.caption("No projected answer claims or tool-result facts were recorded.")
    else:
        pins_row = connection.execute(
            "SELECT package_pins_json FROM runs WHERE run_id=?", [run_id]
        ).fetchone()
        pins = _json(pins_row[0]) if pins_row else None
        evidence_rows = []
        for _, answer in answers.iterrows():
            task_row = connection.execute(
                "SELECT task_id FROM trials WHERE run_id=? AND trial_id=?",
                [run_id, answer.get("trial_id")],
            ).fetchone()
            task = task_row[0] if task_row else None
            package = answer.get("package")
            stated = answer.get("package_version")
            pinned = (pins or {}).get(task, {}).get(package) if task and package else None
            matching = (
                facts[(facts.trial_id == answer.get("trial_id")) & (facts.package == package)]
                if not facts.empty
                else pd.DataFrame()
            )
            observed_versions = (
                sorted({str(value) for value in matching.package_version.dropna()})
                if not matching.empty
                else []
            )
            if observed_versions:
                tool_status = (
                    "supported_by_observed_tool_result"
                    if stated in observed_versions
                    else "contradicted_by_observed_tool_result"
                )
            elif (
                calls.empty
                or calls[
                    (calls.trial_id == answer.get("trial_id"))
                    & calls.event_type.isin({"agent.tool.completed", "agent.tool.failed"})
                ].empty
            ):
                tool_status = "no_observed_tool_evidence"
            else:
                tool_status = "insufficient_observability"
            evidence_rows.append(
                {
                    "trial_id": answer.get("trial_id"),
                    "package": package,
                    "stated_version": stated,
                    "pinned_version": pinned,
                    "reference_match": (
                        "unknown"
                        if pinned is None or stated is None
                        else "match"
                        if stated == pinned
                        else "mismatch"
                    ),
                    "observed_tool_versions": ", ".join(observed_versions) or "none recorded",
                    "tool_evidence_status": tool_status,
                }
            )
        if evidence_rows:
            table(
                pd.DataFrame(evidence_rows),
                f"{run_id}-answer-evidence-consistency",
                key="answer-evidence-consistency",
            )

    urls = observations[observations.event_type == "agent.url.mentioned"].copy()
    if urls.empty:
        st.caption(
            "No allowlisted official URLs were present in projected tool outputs or answers."
        )
    else:
        urls["citation_status"] = urls.source_access_status.map(
            lambda value: (
                "URL mentioned in answer"
                if value == "url_mention_only"
                else "MCP response identity observed"
                if value == "mcp_response_observed"
                else "source access unknown"
            )
        )
        columns = [
            "trial_id",
            "tool",
            "source_url",
            "url_role",
            "observation_location",
            "citation_status",
        ]
        table(
            urls[[column for column in columns if column in urls]],
            f"{run_id}-source-access",
            key="agent-source-access",
        )


def _render_p2_trace_analysis(connection, run_id, selected_tasks):
    """Render P2 traces, checkpoints and opportunity metrics in the existing dashboard."""
    st.divider()
    st.subheader("P2 Trace & MCP Opportunities")
    traces = agent_traces(connection, run_id)
    if traces.empty:
        st.info(
            "P2 trace data is unavailable for this historical analytics schema. "
            "Missing telemetry is not a measured zero."
        )
        return
    if selected_tasks:
        selected_ids = {
            trial_id
            for (trial_id,) in connection.execute(
                "SELECT trial_id FROM trials WHERE run_id=? AND task_id IN ("
                + ",".join("?" for _ in selected_tasks)
                + ")",
                [run_id, *selected_tasks],
            ).fetchall()
        }
        traces = traces[traces.trial_id.isin(selected_ids)]
    if traces.empty:
        st.info("No trials match the current task filter.")
        return
    st.caption(
        "Coverage uses expected instrumented checkpoints as its denominator. Observed and "
        "captured not-observed states count; unknown and unavailable do not."
    )
    table(traces, f"{run_id}-trace-summary", key="p2-trace-summary")
    selected_trial = st.selectbox(
        "Trial timeline", traces.trial_id.tolist(), key="p2-timeline-trial"
    )
    selected_trace = traces[traces.trial_id == selected_trial].iloc[0]
    if selected_trace.trace_completeness != "complete":
        st.warning(
            f"Trace is {selected_trace.trace_completeness}; missing events and durations "
            "remain unknown."
        )
    timeline = trace_spans(connection, run_id, trial_id=selected_trial)
    if timeline.empty:
        st.info("No observable span events were imported for this trial.")
    else:
        table(timeline, f"{run_id}-{selected_trial}-timeline", key="p2-trace-timeline")

    checkpoints = observability_checkpoints(
        connection, run_id, selected_tasks=selected_tasks or None
    )
    if checkpoints.empty:
        st.info("Tool-state checkpoints are unavailable for this run.")
    else:
        st.markdown("#### Tool visibility states")
        counts = (
            checkpoints.groupby(["checkpoint_type", "observation_status"], dropna=False)
            .size()
            .reset_index(name="checkpoint_count")
        )
        table(counts, f"{run_id}-checkpoint-counts", key="p2-checkpoint-counts")
        table(checkpoints, f"{run_id}-checkpoints", key="p2-checkpoint-details")
        st.caption(
            "An API response echo records what the API returned; it does not confirm "
            "remote MCP discovery."
        )

    registry = opportunity_registry(connection, run_id)
    assessments = opportunity_assessments(connection, run_id, selected_tasks=selected_tasks or None)
    if registry.empty:
        st.info("Researcher opportunity annotations are unavailable for this run.")
        return
    trial_tasks = {
        task_id
        for (task_id,) in connection.execute(
            "SELECT DISTINCT task_id FROM trials WHERE run_id=?", [run_id]
        ).fetchall()
    }
    unannotated = sorted(trial_tasks - set(registry.task_id.tolist()))
    if unannotated:
        st.info("Tasks without opportunity metadata: " + ", ".join(unannotated))
    if assessments.empty:
        st.info("No opportunity assessments are available for the selected tasks.")
        return
    st.markdown("#### Opportunity analysis")
    families = ["All families", *sorted(assessments.task_family.dropna().unique().tolist())]
    family = st.selectbox("Task family", families, key="p2-family-filter")
    capabilities = ["All capabilities", *sorted(assessments.capability.dropna().unique().tolist())]
    capability = st.selectbox("MCP capability", capabilities, key="p2-capability-filter")
    tools = {"All candidate tools"}
    for value in assessments.candidate_tools_json.dropna():
        try:
            tools.update(json.loads(value))
        except (TypeError, ValueError):
            continue
    selected_tool = st.selectbox("Candidate tool", sorted(tools), key="p2-tool-filter")
    models = ["All models", *sorted(assessments.model.dropna().unique().tolist())]
    model = st.selectbox("Model", models, key="p2-model-filter")
    configuration = assessments.configuration.fillna(assessments.condition).fillna(assessments.mode)
    configurations = ["All configurations", *sorted(configuration.dropna().unique().tolist())]
    selected_configuration = st.selectbox(
        "Experimental configuration", configurations, key="p2-configuration-filter"
    )
    outcomes = ["All outcomes", "Fully correct", "Not fully correct", "Unknown outcome"]
    outcome = st.selectbox("Outcome", outcomes, key="p2-outcome-filter")
    filtered = assessments.copy()
    if family != "All families":
        filtered = filtered[filtered.task_family == family]
    if capability != "All capabilities":
        filtered = filtered[filtered.capability == capability]
    if selected_tool != "All candidate tools":
        filtered = filtered[
            filtered.candidate_tools_json.map(
                lambda value: selected_tool in (json.loads(value) if isinstance(value, str) else [])
            )
        ]
    if model != "All models":
        filtered = filtered[filtered.model == model]
    filtered_configuration = filtered.configuration.fillna(filtered.condition).fillna(filtered.mode)
    if selected_configuration != "All configurations":
        filtered = filtered[filtered_configuration == selected_configuration]
    if outcome == "Fully correct":
        filtered = filtered[filtered.fully_correct == True]  # noqa: E712
    elif outcome == "Not fully correct":
        filtered = filtered[filtered.fully_correct == False]  # noqa: E712
    elif outcome == "Unknown outcome":
        filtered = filtered[filtered.fully_correct.isna()]
    if filtered.empty:
        st.info("No opportunity rows match the selected filters.")
        return

    def metrics(frame):
        applicable = frame[frame.applicability_status == "observed"]
        adequate = applicable[applicable.adequate_observation == True]  # noqa: E712
        utilization_numerator = int((adequate.assessment_state == "utilized").sum())
        utilization_denominator = len(adequate)
        visible = adequate[adequate.visibility_status == "observed"]
        missed_numerator = int((visible.assessment_state == "no_relevant_call_observed").sum())
        missed_denominator = len(visible)
        return {
            "applicable_opportunities": len(applicable),
            "utilization_numerator": utilization_numerator,
            "utilization_denominator": utilization_denominator,
            "utilization_rate": (
                utilization_numerator / utilization_denominator if utilization_denominator else None
            ),
            "missed_numerator_visibility_confirmed": missed_numerator,
            "missed_denominator_visibility_confirmed": missed_denominator,
            "missed_rate": missed_numerator / missed_denominator if missed_denominator else None,
            "unknown_count": int((frame.assessment_state == "unknown").sum()),
            "no_relevant_call_observed": int(
                (frame.assessment_state == "no_relevant_call_observed").sum()
            ),
            "not_applicable_count": int((frame.applicability_status == "not_applicable").sum()),
            "inadequate_observation_excluded": int(
                (applicable.adequate_observation != True).sum()  # noqa: E712
            ),
        }

    st.write(metrics(filtered))
    group_configuration = filtered.configuration.fillna(filtered.condition).fillna(filtered.mode)
    comparisons = []
    for label, indexes in group_configuration.groupby(
        group_configuration, dropna=False
    ).groups.items():
        group = filtered.loc[indexes]
        comparisons.append({"configuration": label, **metrics(group)})
    st.caption(
        "Utilization means a relevant call was observed. Missed rate requires a complete trace "
        "and an API echo confirming a candidate tool; neither metric measures motivation "
        "or quality."
    )
    table(
        pd.DataFrame(comparisons),
        f"{run_id}-opportunity-comparison",
        key="p2-opportunity-comparison",
    )
    table(filtered, f"{run_id}-opportunities", key="p2-opportunity-details")
    st.caption(
        "Opportunity relevance is researcher-defined. MCP use does not show that returned evidence "
        "influenced the answer or caused task success."
    )


def _error_codes(value):
    if not isinstance(value, str):
        return "Unavailable"
    try:
        codes = json.loads(value)
    except ValueError:
        return "Unavailable"
    return ", ".join(codes) if isinstance(codes, list) and codes else "None recorded"


def _summarize_filtered_calls(calls):
    rows = []
    group_columns = ["tool_name"]
    if "condition" in calls and calls.condition.notna().any():
        group_columns = ["condition", "tool_name"]
    for group_key, group in calls.groupby(group_columns, dropna=False, sort=True):
        condition, tool = group_key if isinstance(group_key, tuple) else (None, group_key)
        outcomes = group[group.is_error.notna()]
        repeats = group[group.repeat_kind.notna()]
        latency = group.server_duration_ms.dropna()
        rows.append(
            {
                "condition": condition,
                "tool_name": tool,
                "total_calls": len(group),
                "successful_calls": int(outcomes.is_error.eq(False).sum())
                if len(outcomes)
                else None,
                "application_errors": int(outcomes.is_error.eq(True).sum())
                if len(outcomes)
                else None,
                "error_rate": float(outcomes.is_error.eq(True).mean()) if len(outcomes) else None,
                "distinct_safe_requests": (
                    group.dropna(subset=["request_fingerprint"])
                    .drop_duplicates(["trial_id", "request_fingerprint"])
                    .shape[0]
                    or None
                ),
                "exact_repeats": int(
                    group.repeat_kind.isin(["identical", "identical_after_error"]).sum()
                )
                if len(repeats)
                else None,
                "repeat_rate": float(
                    group.loc[repeats.index, "repeat_kind"]
                    .isin(["identical", "identical_after_error"])
                    .mean()
                )
                if len(repeats)
                else None,
                "request_bytes": int(group.request_bytes.sum())
                if group.request_bytes.notna().any()
                else None,
                "response_bytes": int(group.result_bytes.sum())
                if group.result_bytes.notna().any()
                else None,
                "average_server_latency_ms": float(latency.mean()) if len(latency) else None,
                "median_server_latency_ms": float(latency.median()) if len(latency) else None,
                "server_latency_observations": len(latency),
                "tasks_using_tool": group.task_id.nunique()
                if group.task_id.notna().any()
                else None,
                "verified_source_responses": int(
                    (
                        (group.verification_status == "verified")
                        & group.source_count.fillna(0).gt(0)
                    ).sum()
                ),
                "telemetry_source": ", ".join(sorted(group.telemetry_version.dropna().unique())),
            }
        )
    return pd.DataFrame(rows), calls


def _render_evidence(connection, row, frame, run_id, scoring_id, results_root, selected_tasks):
    tasks = sorted(frame.task_id.dropna().unique().tolist())
    if not tasks:
        tasks = sorted(adoption_by_task(connection, run_id, scoring_id=scoring_id).task_id.tolist())
    if selected_tasks:
        tasks = [task for task in tasks if task in selected_tasks]
    if not tasks:
        st.info("No task identities are available in this run.")
        return
    task = st.selectbox("Task evidence", tasks, key="evidence-task")
    detail = frame[frame.task_id == task]
    if not detail.empty:
        st.subheader("Recorded A/B score")
        score_columns = [
            "run_id",
            "task_id",
            "trial_id",
            "mode",
            "condition",
            "execution_order",
            "repetition",
            "scorer_version",
            "status",
            "original_status",
            "revision_status",
            "passed",
            "total",
            "fully_correct",
            "original_fully_correct",
            "primary_error_json",
            "original_primary_error_json",
            "failed_checks_json",
        ]
        table(
            detail[[col for col in score_columns if col in detail]],
            f"{run_id}-{task}-scores",
            key="task-scores",
        )
        st.caption(
            "The selected scorer revision is shown beside the preserved original status and "
            "error. Unknown evidence remains null/unknown; V2 diagnostic dimensions are kept "
            "separate from the original score."
        )
    try:
        dimensions = connection.execute(
            """SELECT d.run_id,d.trial_id,t.task_id,t.mode,t.condition,t.execution_order,
                d.scoring_id,d.scorer_version,d.dimension,
                d.status,d.passed,d.total,d.checks_json
            FROM score_dimensions d JOIN trials t USING(run_id,trial_id)
            WHERE d.run_id=? AND t.task_id=? ORDER BY t.condition,t.mode,d.dimension""",
            [run_id, task],
        ).fetchdf()
    except duckdb.CatalogException:
        try:
            dimensions = connection.execute(
                """SELECT d.run_id,d.trial_id,t.task_id,t.mode,d.scorer_version,d.dimension,
                    d.status,d.passed,d.total,d.checks_json
                FROM score_dimensions d JOIN trials t USING(run_id,trial_id)
                WHERE d.run_id=? AND t.task_id=? ORDER BY t.mode,d.dimension""",
                [run_id, task],
            ).fetchdf()
        except duckdb.CatalogException:
            dimensions = pd.DataFrame()
    if not dimensions.empty:
        st.subheader("V2 diagnostic dimensions")
        table(dimensions, f"{run_id}-{task}-v2-dimensions", key="v2-dimensions")
    else:
        st.info(
            "No V2 diagnostic dimensions are present for this task. Historical V1 scores "
            "are not rewritten as V2 dimensions."
        )
    checks = connection.execute(
        """SELECT c.run_id,c.trial_id,t.task_id,t.mode,t.scorer_version,
            c.check_name,c.passed
        FROM score_checks c JOIN trials t USING(run_id,trial_id)
        WHERE c.run_id=? AND t.task_id=? AND c.scoring_id=?
        ORDER BY t.mode,c.check_name""",
        [run_id, task, scoring_id],
    ).fetchdf()
    failed = checks[checks.passed == False] if not checks.empty else checks  # noqa: E712
    st.subheader("Failed checks")
    table(failed, f"{run_id}-{task}-failed-checks", key="failed-checks")
    artifacts = connection.execute(
        "SELECT run_id,trial_id,relative_path,sha256,bytes,kind FROM artifacts "
        "WHERE run_id=? AND trial_id IN (SELECT trial_id FROM trials WHERE run_id=? AND task_id=?) "
        "ORDER BY trial_id,relative_path",
        [run_id, run_id, task],
    ).fetchdf()
    st.subheader("Saved evidence references")
    table(artifacts, f"{run_id}-{task}-evidence", key="saved-evidence")
    if not artifacts.empty:
        artifact = st.selectbox(
            "Preview local artifact", artifacts.relative_path.tolist(), key="artifact-preview-path"
        )
        if st.button("Preview saved artifact", key="preview-artifact"):
            selected = artifacts[artifacts.relative_path == artifact].iloc[0]
            try:
                text = artifact_preview(results_root, artifact, selected.sha256)
                st.code(text, language="r" if artifact.endswith(".R") else "json")
                st.download_button(
                    "Download redacted preview",
                    text,
                    Path(artifact).name,
                    key="artifact-preview-download",
                )
            except (ValueError, OSError, UnicodeDecodeError):
                st.warning(
                    "Artifact unavailable, changed, oversized, or outside the trusted results root."
                )
    audit = audit_classifications(run_id, task)
    if not audit.empty:
        st.subheader("Offline root-cause audit (secondary) ")
        st.caption(
            "These are offline audit classifications, not primary scorer outcomes. Evidence "
            "references are shown as text and are never followed as paths."
        )
        table(audit, f"{run_id}-{task}-audit-classification", key="audit-classifications")
    if detail.empty and checks.empty:
        st.info("No saved scorer result is available for this task.")


def _p2_comparison_rows(connection, run_id, selected_tasks=None):
    clauses = ["run_id=?"]
    parameters = [run_id]
    if selected_tasks:
        clauses.append("task_id IN (" + ",".join("?" for _ in selected_tasks) + ")")
        parameters.extend(selected_tasks)
    trials = connection.execute(
        """SELECT trial_id,task_id,configuration,condition,mode,model,fully_correct,
        mcp_calls_observed FROM trials WHERE """
        + " AND ".join(clauses),
        parameters,
    ).df()
    if trials.empty:
        return [], set(), set()
    trials["configuration_group"] = (
        trials.configuration.fillna(trials.condition).fillna(trials.mode).fillna("unknown")
    )
    traces = agent_traces(connection, run_id)
    if not traces.empty:
        traces = traces.merge(
            trials[["trial_id", "configuration_group"]], on="trial_id", how="inner"
        )
    assessments = opportunity_assessments(connection, run_id, selected_tasks=selected_tasks or None)
    if not assessments.empty:
        assessments["configuration_group"] = (
            assessments.configuration.fillna(assessments.condition)
            .fillna(assessments.mode)
            .fillna("unknown")
        )
    rows = []
    for group_name, group in trials.groupby("configuration_group", dropna=False):
        success = group.fully_correct.dropna()
        calls = group.mcp_calls_observed.dropna()
        group_traces = (
            traces[traces.configuration_group == group_name] if not traces.empty else pd.DataFrame()
        )
        group_assessments = (
            assessments[assessments.configuration_group == group_name]
            if not assessments.empty
            else pd.DataFrame()
        )
        assessment_available = not group_assessments.empty
        applicable = (
            group_assessments[group_assessments.applicability_status == "observed"]
            if not group_assessments.empty
            else pd.DataFrame()
        )
        adequately_observed = (
            applicable[applicable.adequate_observation == True]  # noqa: E712
            if not applicable.empty
            else pd.DataFrame()
        )
        visible = (
            adequately_observed[adequately_observed.visibility_status == "observed"]
            if not adequately_observed.empty
            else pd.DataFrame()
        )
        utilization_n = (
            int((adequately_observed.assessment_state == "utilized").sum())
            if not adequately_observed.empty
            else 0
        )
        utilization_d = len(adequately_observed)
        missed_n = (
            int((visible.assessment_state == "no_relevant_call_observed").sum())
            if not visible.empty
            else 0
        )
        expected_values = (
            group_traces.expected_checkpoint_count.dropna()
            if not group_traces.empty
            else pd.Series(dtype=float)
        )
        captured_values = (
            group_traces.captured_checkpoint_count.dropna()
            if not group_traces.empty
            else pd.Series(dtype=float)
        )
        expected_count = int(expected_values.sum()) if len(expected_values) else None
        captured_count = int(captured_values.sum()) if len(captured_values) else None
        duration_values = (
            group_traces.trial_duration_ms.dropna()
            if not group_traces.empty
            else pd.Series(dtype=float)
        )
        coverage = (
            captured_count / expected_count
            if expected_count is not None and expected_count > 0 and captured_count is not None
            else None
        )
        rows.append(
            {
                "run_id": run_id,
                "configuration": group_name,
                "models": ", ".join(sorted(group.model.dropna().unique().tolist())) or "unknown",
                "task_success_numerator": int(success.sum()) if len(success) else None,
                "task_success_denominator": len(success) if len(success) else None,
                "task_success_rate": float(success.mean()) if len(success) else None,
                "mcp_invoked_trials_numerator": int((calls > 0).sum()) if len(calls) else None,
                "mcp_invoked_trials_denominator": len(calls) if len(calls) else None,
                "opportunities_applicable": len(applicable) if assessment_available else None,
                "opportunity_utilization_numerator": utilization_n
                if assessment_available
                else None,
                "opportunity_utilization_denominator": utilization_d
                if assessment_available
                else None,
                "opportunity_utilization_rate": (
                    utilization_n / utilization_d
                    if assessment_available and utilization_d
                    else None
                ),
                "missed_rate_numerator_visibility_confirmed": missed_n
                if assessment_available
                else None,
                "missed_rate_denominator_visibility_confirmed": len(visible)
                if assessment_available
                else None,
                "missed_opportunity_rate": (
                    missed_n / len(visible) if assessment_available and len(visible) else None
                ),
                "unknown_opportunities": int(
                    (group_assessments.assessment_state == "unknown").sum()
                )
                if assessment_available
                else None,
                "median_trial_latency_ms": (
                    float(duration_values.median()) if len(duration_values) else None
                ),
                "latency_observations": len(duration_values),
                "checkpoint_captured_numerator": captured_count,
                "checkpoint_expected_denominator": expected_count,
                "observation_coverage": coverage,
            }
        )
    versions = set()
    if not assessments.empty:
        versions = set(assessments.opportunity_version.dropna().tolist())
    task_ids = set(trials.task_id.dropna().tolist())
    return rows, versions, task_ids


def _render_p2_comparison(connection, baseline_id, comparison_id, selected_tasks=None):
    st.subheader("Trace and opportunity comparison")
    before, before_versions, before_tasks = _p2_comparison_rows(
        connection, baseline_id, selected_tasks
    )
    after, after_versions, after_tasks = _p2_comparison_rows(
        connection, comparison_id, selected_tasks
    )
    if not before or not after:
        st.info("P2 comparison rows are unavailable for one or both runs.")
        return
    if before_versions != after_versions:
        st.warning(
            "Opportunity annotation versions differ or are unavailable; utilization rates "
            "should not be compared across these runs."
        )
    if before_tasks != after_tasks:
        st.warning(
            "Task scope differs; opportunity rates use different task denominators and need "
            "qualification."
        )
    table(
        pd.DataFrame([*before, *after]),
        f"{baseline_id}-vs-{comparison_id}-p2",
        key="p2-run-comparison",
    )
    st.caption(
        "Success, MCP invocation, opportunity utilization, latency, and checkpoint coverage "
        "retain their own observed denominators. Configuration labels are shown only when "
        "recorded; "
        "A/B/C are never inferred from tool counts."
    )


def _render_compare(connection, baseline_id, comparison_id, runs, selected_tasks=None):
    st.caption(
        "Select separate Run IDs. A single run comparison is descriptive; no significance "
        "test or causal claim is produced."
    )
    if comparison_id is None or comparison_id == baseline_id:
        st.info("Choose a comparison Run ID in the sidebar. The selected run is used as baseline.")
        return
    comparison, warnings, score_compatible = compare_runs(
        connection, baseline_id, comparison_id, scoring_id="original"
    )
    if not comparison.empty:
        for warning in warnings:
            st.warning(warning)
        if not score_compatible:
            st.info(
                "Task scores are omitted because task scope, scorer identity, V1/V2 generation, "
                "or denominators do not match."
            )
        for run_id in (baseline_id, comparison_id):
            selected = runs[runs.run_id == run_id]
            if not selected.empty:
                st.write(_run_label(selected.iloc[0], _scorer_badge(connection, run_id)))
        for index, record in comparison.iterrows():
            if score_compatible and record.metric == "Passed checks B":
                for column, run_id in (("baseline", baseline_id), ("comparison", comparison_id)):
                    metrics = run_metrics(connection, run_id, scoring_id="original")
                    if metrics[f"passed_checks_{'b' if column == 'baseline' else 'b'}"] is not None:
                        comparison.loc[index, column] = _ratio(
                            metrics[f"passed_checks_{'b' if column == 'baseline' else 'b'}"],
                            metrics[f"total_checks_{'b' if column == 'baseline' else 'b'}"],
                        )
            if score_compatible and record.metric == "Fully correct B":
                for column, run_id in (("baseline", baseline_id), ("comparison", comparison_id)):
                    metrics = run_metrics(connection, run_id, scoring_id="original")
                    comparison.loc[index, column] = _ratio(
                        metrics["fully_correct_b"], metrics["fully_correct_b_denominator"]
                    )
        table(comparison, f"{baseline_id}-vs-{comparison_id}", key="run-comparison")
        md = "# Experiment comparison\n\n"
        md += f"Baseline Run ID: `{baseline_id}`\n\nComparison Run ID: `{comparison_id}`\n\n"
        md += markdown_export(comparison)
        md += "\n\n## Compatibility warnings\n\n"
        md += (
            "\n".join(f"- {warning}" for warning in warnings)
            if warnings
            else "No recorded compatibility warnings."
        )
        md += (
            "\n\nOne run per condition is descriptive evidence and does not establish "
            "statistical significance or causality."
        )
        st.download_button(
            "Export comparison Markdown",
            md,
            f"{baseline_id}-vs-{comparison_id}.md",
            "text/markdown",
            key="compare-md",
        )
    _render_p2_comparison(connection, baseline_id, comparison_id, selected_tasks)


def render(database=DEFAULT_DATABASE, results_root=DEFAULT_RESULTS):
    st.set_page_config(page_title="R-Knowledge-MCP · Benchmark", layout="wide")
    st.title("R-Knowledge-MCP · Benchmark analytics")
    st.caption("Local read-only analysis · unknown ≠ zero · no benchmark or API execution")
    try:
        connection = connect(database, read_only=True)
    except (OSError, ValueError, RuntimeError, duckdb.Error):
        st.error("Analytics database unavailable. Run the importer first, then reload this page.")
        return
    with connection:
        runs = run_catalog(connection)
        if runs.empty:
            st.info("No imported benchmark runs. Import saved results to create a run catalog.")
            return
        run_ids = runs.run_id.tolist()
        scorer_labels = {run_id: _scorer_badge(connection, run_id) for run_id in run_ids}
        preferred = default_run_id(runs)
        default_id = preferred or run_ids[0]
        st.sidebar.header("Selected experiment")
        selected_run_id = st.sidebar.selectbox(
            "Run ID",
            run_ids,
            index=run_ids.index(default_id),
            format_func=lambda run_id: _run_label(
                runs[runs.run_id == run_id].iloc[0], scorer_labels[run_id]
            ),
            key="run-id-selector",
        )
        row = runs[runs.run_id == selected_run_id].iloc[0]
        score_sources = _score_sources(connection, selected_run_id)
        score_options = ["original", *score_sources]
        scoring_id = st.sidebar.selectbox(
            "Score source",
            score_options,
            format_func=lambda value: (
                "Original recorded scores" if value == "original" else score_sources[value]
            ),
        )
        selected_trials = trials_frame(
            connection, scoring_id=scoring_id, filters={"run_id": [selected_run_id]}
        )
        task_options = sorted(
            set(selected_trials.task_id.dropna().tolist())
            | set(
                adoption_by_task(
                    connection, selected_run_id, scoring_id=scoring_id
                ).task_id.tolist()
            )
        )
        selected_tasks = st.sidebar.multiselect("Task filter", task_options, key="run-task-filter")
        st.sidebar.caption(
            f"{len(runs)} imported runs · selected run has "
            f"{row.observed_trials} observed trials · {_show(row.full_status, 'unknown')} scope"
        )
        compare_options = [None, *[item for item in run_ids if item != selected_run_id]]
        comparison_id = st.sidebar.selectbox(
            "Comparison run (optional)",
            compare_options,
            format_func=lambda value: (
                "Choose comparison run"
                if value is None
                else _run_label(runs[runs.run_id == value].iloc[0], scorer_labels[value])
            ),
            key="comparison-run-selector",
        )
        if row.full_status != "full_comparable":
            st.warning(
                f"This run is not the verified full default ({_show(row.full_status)}: "
                f"{_show(row.full_status_reason)}). It was selected explicitly or no full "
                "run is available."
            )

        tabs = st.tabs(TABS, key="analytics-tabs", on_change="rerun")
        if tabs[0].open:
            with tabs[0]:
                st.subheader("Run overview")
                _render_overview(connection, row, selected_trials, selected_run_id, scoring_id)
                with st.expander("Run metadata", expanded=False):
                    table(
                        _metadata_frame(row, selected_trials, connection),
                        f"{selected_run_id}-metadata",
                        key="metadata",
                    )
        if tabs[1].open:
            with tabs[1]:
                st.subheader("Adoption by Task")
                task_filter = st.selectbox(
                    "Task view",
                    [
                        "All tasks",
                        "MCP called",
                        "No MCP calls",
                        "Quality improved",
                        "Quality unchanged",
                        "Quality worsened",
                        "Fully correct in B",
                        "Partially/incorrectly solved in B",
                    ],
                    key="adoption-task-filter",
                )
                _render_adoption(
                    connection, selected_run_id, scoring_id, selected_tasks, task_filter
                )
        if tabs[2].open:
            with tabs[2]:
                st.subheader("Tool Effectiveness")
                _render_tools(connection, selected_run_id, selected_tasks)
        if tabs[3].open:
            with tabs[3]:
                st.subheader("Scorer & Evidence")
                _render_evidence(
                    connection,
                    row,
                    selected_trials,
                    selected_run_id,
                    scoring_id,
                    results_root,
                    selected_tasks,
                )
        if tabs[4].open:
            with tabs[4]:
                st.subheader("Compare Runs")
                _render_compare(connection, selected_run_id, comparison_id, runs, selected_tasks)
        if tabs[5].open:
            with tabs[5]:
                st.subheader("Agent & Evidence")
                _render_p2_trace_analysis(connection, selected_run_id, selected_tasks)
                _render_agent_observability(connection, selected_run_id, selected_tasks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args, _ = parser.parse_known_args()
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    if get_script_run_ctx(suppress_warning=True) is not None:
        render(args.database, args.results)
        return
    from streamlit.web import cli

    sys.argv = [
        "streamlit",
        "run",
        str(Path(__file__).resolve()),
        "--server.address=127.0.0.1",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
        "--",
        "--database",
        str(args.database.resolve()),
        "--results",
        str(args.results.resolve()),
    ]
    raise SystemExit(cli.main())


if __name__ == "__main__":
    main()
