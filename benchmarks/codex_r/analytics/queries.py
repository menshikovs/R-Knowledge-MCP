"""Fixed, parameterized DuckDB queries and safe local exports for the dashboard."""

from __future__ import annotations

import csv
import io
import json

import duckdb
import pandas as pd

from benchmarks.codex_r.analytics import DEFAULT_REPORTS
from benchmarks.codex_r.analytics.safety import (
    MAX_PREVIEW,
    SECRET,
    read_bytes,
    redact_preview,
    token,
)
from benchmarks.codex_r.telemetry import schema as telemetry_schema
from benchmarks.codex_r.telemetry.errors import classify_mcp_events

FILTERS = {
    "run_id",
    "block",
    "task_id",
    "model",
    "effort",
    "configuration",
    "compatibility_key",
    "mode",
    "condition",
    "experiment_id",
}


def agent_telemetry(connection, run_id):
    """Return validated closed agent/exposure/evidence projections for one run.

    Databases imported before analytics schema 5 have no such table. Those runs remain
    selectable and return an empty frame so the dashboard can display observability as
    unavailable instead of treating absent rows as a measured zero.
    """
    present = connection.execute(
        """SELECT count(*) FROM information_schema.tables
        WHERE table_schema='main' AND table_name='agent_telemetry'"""
    ).fetchone()[0]
    columns = ["event_type", "trial_id", "call_id", "tool", "tool_class", "tool_outcome"]
    if not present:
        return pd.DataFrame(columns=columns)
    rows = connection.execute(
        """SELECT event_type, trial_id, event_projection_json
        FROM agent_telemetry WHERE run_id=? ORDER BY trial_id,event_type,event_id""",
        [run_id],
    ).fetchall()
    projected = []
    for event_type, trial_id, value in rows:
        try:
            event = json.loads(value)
        except (ValueError, TypeError):
            continue
        if (
            not isinstance(event, dict)
            or event.get("run_id") != run_id
            or event.get("trial_id") != trial_id
            or event.get("event_type") != event_type
            or telemetry_schema.validate_event(event)
        ):
            continue
        projected.append(
            {
                key: item
                for key, item in event.items()
                if key not in {"schema_version", "run_id", "trace_id", "timestamp_utc"}
            }
        )
    return pd.DataFrame(projected, columns=None if projected else columns)


def _table_exists(connection, table_name):
    return (
        connection.execute(
            """SELECT count(*) FROM information_schema.tables
        WHERE table_schema='main' AND table_name=?""",
            [table_name],
        ).fetchone()[0]
        > 0
    )


def agent_traces(connection, run_id):
    """Return P2 trace summaries, or an empty frame for historical schema versions."""
    columns = [
        "trial_id",
        "trace_id",
        "trace_completeness",
        "integrity_status",
        "schema_validation_status",
        "expected_checkpoint_count",
        "captured_checkpoint_count",
        "missing_checkpoint_count",
        "capture_completeness",
        "trial_duration_ms",
        "time_to_first_mcp_ms",
    ]
    if not _table_exists(connection, "agent_traces"):
        return pd.DataFrame(columns=columns)
    return connection.execute(
        """SELECT trial_id,trace_id,trace_completeness,integrity_status,
        schema_validation_status,expected_checkpoint_count,captured_checkpoint_count,
        missing_checkpoint_count,capture_completeness,trial_duration_ms,time_to_first_mcp_ms
        FROM agent_traces WHERE run_id=? ORDER BY trial_id""",
        [run_id],
    ).df()


def trace_spans(connection, run_id, *, trial_id=None, selected_tasks=None):
    """Return safe, ordered span rows for a selected run and optional task filter."""
    columns = [
        "trial_id",
        "task_id",
        "trace_id",
        "span_id",
        "parent_span_id",
        "span_kind",
        "event_type",
        "status",
        "capture_source",
        "verification_status",
        "timestamp_start_utc",
        "timestamp_end_utc",
        "clock",
        "start_offset_ms",
        "end_offset_ms",
        "duration_ms",
        "call_id",
        "tool_name",
    ]
    if not _table_exists(connection, "agent_spans"):
        return pd.DataFrame(columns=columns)
    clauses = ["s.run_id=?"]
    params = [run_id]
    if trial_id is not None:
        clauses.append("s.trial_id=?")
        params.append(trial_id)
    if selected_tasks:
        clauses.append("t.task_id IN (" + ",".join("?" for _ in selected_tasks) + ")")
        params.extend(selected_tasks)
    return connection.execute(
        """SELECT s.trial_id,t.task_id,s.trace_id,s.span_id,s.parent_span_id,s.span_kind,
        s.event_type,s.status,s.capture_source,s.verification_status,s.timestamp_start_utc,
        s.timestamp_end_utc,s.clock,s.start_offset_ms,s.end_offset_ms,s.duration_ms,
        s.call_id,s.tool_name FROM agent_spans s
        LEFT JOIN trials t ON t.run_id=s.run_id AND t.trial_id=s.trial_id
        WHERE """
        + " AND ".join(clauses)
        + " ORDER BY s.trial_id,s.clock,s.start_offset_ms NULLS LAST,s.span_id",
        params,
    ).df()


def observability_checkpoints(connection, run_id, *, trial_id=None, selected_tasks=None):
    """Return distinct tool-state checkpoints; absent P2 tables stay unavailable."""
    columns = [
        "trial_id",
        "task_id",
        "checkpoint_type",
        "subject",
        "observation_status",
        "expected",
        "capture_source",
        "verification_status",
        "evidence_reference",
        "reason_code",
    ]
    if not _table_exists(connection, "observability_checkpoints"):
        return pd.DataFrame(columns=columns)
    clauses = ["c.run_id=?"]
    params = [run_id]
    if trial_id is not None:
        clauses.append("c.trial_id=?")
        params.append(trial_id)
    if selected_tasks:
        clauses.append("t.task_id IN (" + ",".join("?" for _ in selected_tasks) + ")")
        params.extend(selected_tasks)
    return connection.execute(
        """SELECT c.trial_id,t.task_id,c.checkpoint_type,c.subject,c.observation_status,
        c.expected,c.capture_source,c.verification_status,c.evidence_reference,c.reason_code
        FROM observability_checkpoints c
        LEFT JOIN trials t ON t.run_id=c.run_id AND t.trial_id=c.trial_id
        WHERE """
        + " AND ".join(clauses)
        + " ORDER BY c.trial_id,c.checkpoint_type,c.subject",
        params,
    ).df()


def opportunity_assessments(connection, run_id, *, selected_tasks=None):
    """Return assessments joined to trial configuration and researcher annotations."""
    columns = [
        "trial_id",
        "task_id",
        "task_family",
        "opportunity_id",
        "capability",
        "candidate_tools_json",
        "opportunity_version",
        "configuration",
        "condition",
        "mode",
        "model",
        "fully_correct",
        "applicability_status",
        "configured_status",
        "visibility_status",
        "discovery_status",
        "invocation_status",
        "success_status",
        "assessment_state",
        "adequate_observation",
        "utilized",
        "missed",
        "candidate_calls",
        "repeated_calls",
        "evidence_class",
        "opportunity_manifest_sha256",
        "rationale",
        "relevance",
        "source_path",
    ]
    if not _table_exists(connection, "trial_opportunity_assessments"):
        return pd.DataFrame(columns=columns)
    clauses = ["a.run_id=?"]
    params = [run_id]
    if selected_tasks:
        clauses.append("a.task_id IN (" + ",".join("?" for _ in selected_tasks) + ")")
        params.extend(selected_tasks)
    return connection.execute(
        """SELECT a.trial_id,a.task_id,o.task_family,a.opportunity_id,o.capability,
        o.candidate_tools_json,a.opportunity_version,t.configuration,t.condition,t.mode,t.model,t.fully_correct,
        a.applicability_status,a.configured_status,a.visibility_status,a.discovery_status,
        a.invocation_status,a.success_status,a.assessment_state,a.adequate_observation,
        a.utilized,a.missed,a.candidate_calls,a.repeated_calls,a.evidence_class,
        a.opportunity_manifest_sha256,o.rationale,
        o.relevance,o.source_path
        FROM trial_opportunity_assessments a
        LEFT JOIN trials t ON t.run_id=a.run_id AND t.trial_id=a.trial_id
        LEFT JOIN task_mcp_opportunities o ON o.run_id=a.run_id
            AND o.opportunity_version=a.opportunity_version AND o.task_id=a.task_id
            AND o.opportunity_id=a.opportunity_id
        WHERE """
        + " AND ".join(clauses)
        + " ORDER BY a.task_id,a.opportunity_id,a.trial_id",
        params,
    ).df()


def opportunity_registry(connection, run_id):
    """Return task annotations including explicitly declared zero-opportunity tasks."""
    columns = [
        "task_id",
        "task_family",
        "annotation_status",
        "source_path",
        "opportunity_count",
    ]
    if not _table_exists(connection, "task_opportunity_registry"):
        return pd.DataFrame(columns=columns)
    return connection.execute(
        """SELECT task_id,task_family,annotation_status,source_path,opportunity_count
        FROM task_opportunity_registry WHERE run_id=? ORDER BY task_id""",
        [run_id],
    ).df()


def trial_query(*, scoring_id="original", filters=None, keys=None, revision_columns=None):
    params = []
    if scoring_id == "original":
        selection = "t.*"
        join = ""
    else:
        revision_columns = set(revision_columns or ())
        replacements = [
            "s.passed AS passed",
            "s.total AS total",
            "s.fully_correct AS fully_correct",
            "s.failed_checks_json AS failed_checks_json",
            "s.scorer_version AS scorer_version",
        ]
        extra = []
        if "status" in revision_columns:
            replacements.append("s.status AS status")
            extra.append("s.status AS revision_status")
        if "primary_error_json" in revision_columns:
            replacements.append("s.primary_error_json AS primary_error_json")
        if "dimensions_json" in revision_columns:
            extra.append("s.dimensions_json AS revision_dimensions_json")
        if "claim_audit_json" in revision_columns:
            extra.append("s.claim_audit_json AS claim_audit_json")
        selection = f"t.* REPLACE ({', '.join(replacements)})"
        if extra:
            selection += ", " + ", ".join(extra)
        join = (
            "JOIN scoring_revisions s ON t.run_id=s.run_id AND t.trial_id=s.trial_id "
            "AND s.revision_id=?"
        )
        params.append(scoring_id)
    clauses = []
    for column, values in (filters or {}).items():
        if column not in FILTERS:
            raise ValueError("unknown_filter")
        if values:
            clauses.append(f"t.{column} IN (SELECT unnest(?))")
            params.append(list(values))
    if keys is not None:
        clauses.append("concat(t.run_id, '/', t.trial_id) IN (SELECT unnest(?))")
        params.append(list(keys))
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return (
        f"""SELECT {selection}, t.status AS original_status,
        t.fully_correct AS original_fully_correct,
        t.primary_error_json AS original_primary_error_json,
        t.passed AS original_passed, t.total AS original_total,
        t.failed_checks_json AS original_failed_checks_json,
        r.import_state, r.completion_state,
        coalesce(t.configuration, 'unrecorded@' || t.run_id) AS configuration_key,
        coalesce({"s" if join else "t"}.scorer_version, 'unrecorded@' || t.run_id) AS scorer_key
        FROM trials t JOIN runs r USING(run_id) {join} {where}""",
        params,
    )


def trials_frame(connection, **options):
    options.setdefault("revision_columns", _revision_columns(connection))
    sql, params = trial_query(**options)
    return connection.execute(sql + " ORDER BY run_id, trial_id", params).fetchdf()


def _revision_columns(connection):
    return {
        row[1] for row in connection.execute("PRAGMA table_info('scoring_revisions')").fetchall()
    }


def run_catalog(connection):
    """One explicit row per run, including normalized plan metadata and observed trials."""
    try:
        return connection.execute(
            """SELECT r.run_id, r.relative_path, r.import_state, r.completion_state,
            r.configuration, r.configuration_source, r.model, r.effort, r.instructions,
            r.revision, r.dirty, r.dirty_fingerprint, r.source_sha256, r.images_json,
            r.package_pins_json, r.registered_tools_json, r.allowed_tools_json,
            r.toolset, r.telemetry_schema, r.manifest_schema, r.expected_trials,
            r.observed_trials, r.source_fingerprint, r.jsonl_present, r.jsonl_complete,
            m.created_at_utc, m.benchmark_suite, m.suite_source, m.suite_label,
            m.tasks_json, m.conditions_json, m.repetitions, m.trial_plan_count,
            m.scorer_versions_json, m.prompt_versions_json, m.task_input_hashes_json,
            m.environment_json, m.timeout_seconds, m.trial_plan_status,
            m.full_status, m.full_status_reason, m.v2_observation_schema,
            m.v2_observation_status, m.experiment_id, m.experiment_version,
            m.experiment_metadata_json
        FROM runs r LEFT JOIN run_metadata m USING(run_id)
            ORDER BY m.created_at_utc DESC NULLS LAST, r.run_id DESC"""
        ).fetchdf()
    except duckdb.CatalogException:
        # Keep v1/v2 databases inspectable without fabricating B1 metadata.
        try:
            frame = connection.execute(
                """SELECT r.*,m.created_at_utc,m.benchmark_suite,m.suite_source,
                m.suite_label,m.tasks_json,m.conditions_json,m.repetitions,m.trial_plan_count,
                m.scorer_versions_json,m.prompt_versions_json,m.task_input_hashes_json,
                m.environment_json,m.timeout_seconds,m.trial_plan_status,m.full_status,
                m.full_status_reason,m.v2_observation_schema,m.v2_observation_status
                FROM runs r LEFT JOIN run_metadata m USING(run_id) ORDER BY r.run_id DESC"""
            ).fetchdf()
        except duckdb.CatalogException:
            frame = connection.execute("SELECT * FROM runs ORDER BY run_id DESC").fetchdf()
        for column in (
            "created_at_utc",
            "benchmark_suite",
            "suite_source",
            "suite_label",
            "tasks_json",
            "conditions_json",
            "repetitions",
            "trial_plan_count",
            "scorer_versions_json",
            "prompt_versions_json",
            "task_input_hashes_json",
            "environment_json",
            "timeout_seconds",
            "trial_plan_status",
            "full_status",
            "full_status_reason",
            "v2_observation_schema",
            "v2_observation_status",
            "experiment_id",
            "experiment_version",
            "experiment_metadata_json",
        ):
            if column not in frame:
                frame[column] = None
        return frame


def default_run_id(runs):
    """Latest strictly complete registered-scope run; stable tie-break on run_id."""
    if runs.empty or "full_status" not in runs:
        return None
    complete = runs[runs.full_status == "full_comparable"].copy()
    if complete.empty:
        return None
    complete["_timestamp"] = complete.created_at_utc.fillna("")
    complete = complete.sort_values(["_timestamp", "run_id"], ascending=[False, False])
    return complete.iloc[0].run_id


def scorer_generation(scorer_version):
    if not isinstance(scorer_version, str):
        return "unknown"
    if scorer_version.startswith("unrecorded@"):
        return "unknown"
    if "knowledge-pilot-v2" in scorer_version.casefold() or scorer_version.casefold().endswith(
        "-v2"
    ):
        return "V2"
    return "V1"


def overview(connection, **options):
    options.setdefault("revision_columns", _revision_columns(connection))
    sql, params = trial_query(**options)
    return connection.execute(
        f"""WITH selected AS ({sql})
        SELECT configuration_key, scorer_key, model, effort, compatibility_key, mode,
            count(*) AS trials, count(DISTINCT run_id) AS runs,
            count(passed) AS score_observations,
            avg(passed::DOUBLE / nullif(total, 0)) AS mean_score,
            count(fully_correct) AS fully_correct_observations,
            avg(fully_correct::INTEGER) AS fully_correct_rate,
            avg(duration_seconds) AS mean_seconds,
            median(duration_seconds) AS median_seconds,
            count(duration_seconds) AS duration_observations,
            count(api_total_tokens) AS usage_observations,
            sum(api_total_tokens) AS observed_total_tokens,
            count(cost_amount) AS cost_observations,
            count(mcp_calls_observed) AS adoption_observations,
            avg(CASE WHEN mode='with-mcp' THEN
                CASE WHEN mcp_calls_observed IS NULL THEN NULL
                     WHEN mcp_calls_observed>0 THEN 1.0 ELSE 0.0 END END) AS adoption_rate
        FROM selected GROUP BY ALL ORDER BY configuration_key, scorer_key, mode""",
        params,
    ).fetchdf()


def paired_trials(connection, **options):
    options.setdefault("revision_columns", _revision_columns(connection))
    sql, params = trial_query(**options)
    columns = {row[1] for row in connection.execute("PRAGMA table_info('trials')").fetchall()}
    if "experiment_id" not in columns:
        return connection.execute(
            f"""WITH selected AS ({sql}), unique_trials AS (
            SELECT *,count(*) OVER (PARTITION BY run_id,task_id,repetition,mode,model,effort,
                instructions,configuration_key,scorer_key) AS identities
            FROM selected WHERE finalized AND passed IS NOT NULL AND total>0
                AND repetition IS NOT NULL AND model IS NOT NULL AND effort IS NOT NULL
                AND import_state<>'snapshot_rejected'
            ) SELECT a.run_id,a.task_id,a.repetition,a.model,a.effort,a.configuration_key,
                a.compatibility_key,a.scorer_key,a.trial_id AS without_trial,
                b.trial_id AS with_trial,a.passed AS without_passed,a.total AS without_total,
                b.passed AS with_passed,b.total AS with_total,
                a.fully_correct AS without_fully_correct,b.fully_correct AS with_fully_correct,
                b.passed::DOUBLE/b.total-a.passed::DOUBLE/a.total AS delta_score,
                b.duration_seconds-a.duration_seconds AS delta_seconds,
                a.failed_checks_json AS without_failed_checks,
                b.failed_checks_json AS with_failed_checks
            FROM unique_trials a JOIN unique_trials b ON a.run_id=b.run_id
                AND a.task_id=b.task_id AND a.repetition IS NOT DISTINCT FROM b.repetition
                AND a.model IS NOT DISTINCT FROM b.model AND a.effort IS NOT DISTINCT FROM b.effort
                AND a.instructions IS NOT DISTINCT FROM b.instructions
                AND a.configuration_key=b.configuration_key AND a.scorer_key=b.scorer_key
            WHERE a.mode='without-mcp' AND b.mode='with-mcp'
                AND a.identities=1 AND b.identities=1
            ORDER BY a.run_id,a.task_id,a.repetition""",
            params,
        ).fetchdf()
    return connection.execute(
        f"""WITH selected AS ({sql}), unique_trials AS (
        SELECT *, count(*) OVER (PARTITION BY run_id, task_id, repetition, mode, condition,
            model, effort, instructions, configuration_key, scorer_key) AS identities
        FROM selected WHERE finalized AND passed IS NOT NULL AND total>0
            AND repetition IS NOT NULL AND model IS NOT NULL AND effort IS NOT NULL
            AND import_state <> 'snapshot_rejected'
    ), legacy_pairs AS (
    SELECT a.run_id, a.task_id, a.repetition, a.model, a.effort, a.configuration_key,
        a.compatibility_key,
        a.scorer_key, a.trial_id AS without_trial, b.trial_id AS with_trial,
        a.passed AS without_passed, a.total AS without_total,
        b.passed AS with_passed, b.total AS with_total,
        a.fully_correct AS without_fully_correct,
        b.fully_correct AS with_fully_correct,
        b.passed::DOUBLE/b.total-a.passed::DOUBLE/a.total AS delta_score,
        b.duration_seconds-a.duration_seconds AS delta_seconds,
        a.failed_checks_json AS without_failed_checks,
        b.failed_checks_json AS with_failed_checks,
        'without-mcp' AS condition_a, 'with-mcp' AS condition_b,
        a.execution_order AS execution_order_a, b.execution_order AS execution_order_b
    FROM unique_trials a JOIN unique_trials b
        ON a.run_id=b.run_id AND a.task_id=b.task_id
        AND a.repetition IS NOT DISTINCT FROM b.repetition
        AND a.model IS NOT DISTINCT FROM b.model AND a.effort IS NOT DISTINCT FROM b.effort
        AND a.instructions IS NOT DISTINCT FROM b.instructions
        AND a.configuration_key=b.configuration_key AND a.scorer_key=b.scorer_key
    WHERE a.mode='without-mcp' AND b.mode='with-mcp'
        AND a.experiment_id IS DISTINCT FROM 'b1-discovery'
        AND b.experiment_id IS DISTINCT FROM 'b1-discovery'
        AND a.identities=1 AND b.identities=1
    ), b1_pairs AS (
    SELECT a.run_id, a.task_id, a.repetition, a.model, a.effort, a.configuration_key,
        a.compatibility_key, a.scorer_key,
        a.trial_id AS without_trial, b.trial_id AS with_trial,
        a.passed AS without_passed, a.total AS without_total,
        b.passed AS with_passed, b.total AS with_total,
        a.fully_correct AS without_fully_correct,
        b.fully_correct AS with_fully_correct,
        b.passed::DOUBLE/b.total-a.passed::DOUBLE/a.total AS delta_score,
        b.duration_seconds-a.duration_seconds AS delta_seconds,
        a.failed_checks_json AS without_failed_checks,
        b.failed_checks_json AS with_failed_checks,
        'control' AS condition_a, 'treatment' AS condition_b,
        a.execution_order AS execution_order_a, b.execution_order AS execution_order_b
    FROM unique_trials a JOIN unique_trials b
        ON a.run_id=b.run_id AND a.task_id=b.task_id
        AND a.repetition IS NOT DISTINCT FROM b.repetition
        AND a.model IS NOT DISTINCT FROM b.model AND a.effort IS NOT DISTINCT FROM b.effort
        AND a.instructions IS NOT DISTINCT FROM b.instructions
        AND a.configuration_key=b.configuration_key AND a.scorer_key=b.scorer_key
    WHERE a.experiment_id='b1-discovery' AND b.experiment_id='b1-discovery'
        AND a.condition='control' AND b.condition='treatment'
        AND a.mode='with-mcp' AND b.mode='with-mcp'
        AND a.identities=1 AND b.identities=1
    ) SELECT * FROM legacy_pairs UNION ALL SELECT * FROM b1_pairs
        ORDER BY run_id,task_id,repetition""",
        params,
    ).fetchdf()


def adoption_by_task(connection, run_id, *, scoring_id="original"):
    """Build one task row without merging repetitions or inferring missing calls."""
    trials = trials_frame(connection, scoring_id=scoring_id, filters={"run_id": [run_id]})
    try:
        experiment_id = connection.execute(
            "SELECT experiment_id FROM run_metadata WHERE run_id=?", [run_id]
        ).fetchone()[0]
    except (duckdb.CatalogException, TypeError):
        experiment_id = None
    if experiment_id == "b1-discovery":
        return _b1_adoption_by_task(connection, run_id, trials, scoring_id)
    try:
        plan = connection.execute(
            "SELECT planned_trial_id, task_id, mode, repetition FROM trial_plan "
            "WHERE run_id=? ORDER BY task_id,repetition,mode",
            [run_id],
        ).fetchdf()
    except duckdb.CatalogException:
        plan = pd.DataFrame(columns=["planned_trial_id", "task_id", "mode", "repetition"])
    pairs = paired_trials(connection, scoring_id=scoring_id, filters={"run_id": [run_id]})
    if plan.empty:
        tasks = sorted(trials.task_id.dropna().unique().tolist()) if not trials.empty else []
    else:
        tasks = sorted(plan.task_id.dropna().unique().tolist())
    call_rows = calls_frame(connection, selection_keys(trials), counted_only=True)
    output = []
    for task in tasks:
        planned = plan[plan.task_id == task]
        expected_repetitions = sorted(
            set(planned[planned["mode"] == "without-mcp"].repetition.dropna().tolist())
            | set(planned[planned["mode"] == "with-mcp"].repetition.dropna().tolist())
        )
        expected_pairs = len(expected_repetitions) if not plan.empty else None
        task_pairs = pairs[pairs.task_id == task] if not pairs.empty else pairs
        if expected_pairs is None:
            expected_pairs = len(task_pairs)
        pair_count = len(task_pairs)
        complete_pairing = expected_pairs > 0 and pair_count == expected_pairs
        same_denominator = (
            complete_pairing and task_pairs.without_total.eq(task_pairs.with_total).all()
        )
        if pair_count:
            a_passed = int(task_pairs.without_passed.sum())
            b_passed = int(task_pairs.with_passed.sum())
            a_total = int(task_pairs.without_total.sum())
            b_total = int(task_pairs.with_total.sum())
            score_a = f"{a_passed}/{a_total}" + (
                "" if complete_pairing else f" (matched {pair_count}/{expected_pairs})"
            )
            score_b = f"{b_passed}/{b_total}" + (
                "" if complete_pairing else f" (matched {pair_count}/{expected_pairs})"
            )
            delta = b_passed - a_passed if complete_pairing and same_denominator else None
            normalized_delta = (
                b_passed / b_total - a_passed / a_total
                if complete_pairing and a_total and b_total
                else None
            )
        else:
            a_passed = b_passed = a_total = b_total = None
            score_a = score_b = None
            delta = normalized_delta = None
        a_correct = _all_correct(task_pairs.without_fully_correct) if pair_count else None
        b_correct = _all_correct(task_pairs.with_fully_correct) if pair_count else None
        if not complete_pairing:
            a_correct = b_correct = None

        b_trials = trials[(trials.task_id == task) & (trials["mode"] == "with-mcp")]
        a_trials = trials[(trials.task_id == task) & (trials["mode"] == "without-mcp")]
        eligible = bool(
            len(planned[planned["mode"] == "with-mcp"]) if not plan.empty else len(b_trials)
        )
        expected_b = (
            len(planned[planned["mode"] == "with-mcp"]) if not plan.empty else len(b_trials)
        )
        known_call_counts = b_trials.mcp_calls_observed.dropna()
        calls_known = (
            expected_b > 0 and len(b_trials) == expected_b and len(known_call_counts) == expected_b
        )
        call_count = int(known_call_counts.sum()) if calls_known else None
        selected_calls = (
            call_rows[call_rows.trial_id.isin(b_trials.trial_id.tolist())]
            if not call_rows.empty
            else call_rows
        )
        tools = (
            sorted(selected_calls.tool_name.dropna().unique().tolist())
            if not selected_calls.empty
            else []
        )
        if calls_known and call_count == 0:
            error_count = 0
        elif (
            calls_known
            and len(selected_calls) == call_count
            and selected_calls.is_error.notna().all()
        ):
            error_count = int(selected_calls.is_error.eq(True).sum())
        else:
            error_count = None
        discovery = b_trials.list_tools
        if len(b_trials) == expected_b and expected_b and discovery.notna().all():
            discovery_status = "Observed" if discovery.gt(0).any() else "Not observed"
        else:
            discovery_status = "Unknown"
        duration_a = (
            float(a_trials.duration_seconds.mean())
            if len(a_trials) and a_trials.duration_seconds.notna().all()
            else None
        )
        duration_b = (
            float(b_trials.duration_seconds.mean())
            if len(b_trials) and b_trials.duration_seconds.notna().all()
            else None
        )
        if call_count == 0:
            call_note = "No MCP call observed — reason unknown"
        elif call_count is None:
            call_note = "MCP call count unavailable"
        else:
            call_note = "MCP call observed"
        evidence = (
            "Complete unique A/B pairing"
            if complete_pairing and same_denominator
            else "Partial or incompatible A/B pairing"
            if pair_count
            else "No comparable scored pair"
        )
        output.append(
            {
                "run_id": run_id,
                "task_id": task,
                "trial_ids_a": "; ".join(sorted(a_trials.trial_id.tolist()))
                if len(a_trials)
                else None,
                "trial_ids_b": "; ".join(sorted(b_trials.trial_id.tolist()))
                if len(b_trials)
                else None,
                "score_a": score_a,
                "score_b": score_b,
                "passed_a": a_passed,
                "total_a": a_total,
                "passed_b": b_passed,
                "total_b": b_total,
                "delta_checks": delta,
                "delta_score": normalized_delta,
                "fully_correct_a": a_correct,
                "fully_correct_b": b_correct,
                "mcp_available": eligible if not plan.empty else True if len(b_trials) else None,
                "tool_discovery_observed": discovery_status,
                "mcp_called": (call_count > 0) if call_count is not None else None,
                "mcp_calls": call_count,
                "mcp_errors": error_count,
                "tools_used": ", ".join(tools) if tools else None,
                "duration_a_seconds": duration_a,
                "duration_b_seconds": duration_b,
                "evidence_status": evidence,
                "call_observation": call_note,
                "matched_repetitions": pair_count,
                "planned_repetitions": expected_pairs,
                "scorer_generation": scorer_generation(
                    task_pairs.scorer_key.iloc[0] if pair_count else None
                ),
            }
        )
    return pd.DataFrame(output)


def _b1_adoption_by_task(connection, run_id, trials, scoring_id):
    """Task-level matched scores and condition-specific telemetry for B1."""
    try:
        plan = connection.execute(
            "SELECT planned_trial_id,task_id,mode,repetition,condition "
            "FROM trial_plan WHERE run_id=? ORDER BY task_id,repetition,condition",
            [run_id],
        ).fetchdf()
    except duckdb.CatalogException:
        plan = pd.DataFrame(
            columns=["planned_trial_id", "task_id", "mode", "repetition", "condition"]
        )
    pairs = paired_trials(connection, scoring_id=scoring_id, filters={"run_id": [run_id]})
    calls = run_tool_calls(connection, run_id)
    tasks = sorted(set(plan.task_id.dropna()) | set(trials.task_id.dropna()))
    output = []
    for task in tasks:
        task_pairs = pairs[pairs.task_id == task] if not pairs.empty else pairs
        task_plan = plan[plan.task_id == task]
        expected = int(task_plan.repetition.nunique()) if not task_plan.empty else None
        matched = len(task_pairs)
        complete = expected is not None and expected > 0 and matched == expected
        same_denominators = bool(
            complete and task_pairs.without_total.eq(task_pairs.with_total).all()
        )
        if matched:
            passed_control = int(task_pairs.without_passed.sum())
            total_control = int(task_pairs.without_total.sum())
            passed_treatment = int(task_pairs.with_passed.sum())
            total_treatment = int(task_pairs.with_total.sum())
            score_control = f"{passed_control}/{total_control}"
            score_treatment = f"{passed_treatment}/{total_treatment}"
            delta_checks = (
                passed_treatment - passed_control if complete and same_denominators else None
            )
            delta_score = (
                passed_treatment / total_treatment - passed_control / total_control
                if complete and total_control and total_treatment
                else None
            )
            correct_control = _all_correct(task_pairs.without_fully_correct) if complete else None
            correct_treatment = _all_correct(task_pairs.with_fully_correct) if complete else None
            scorer = task_pairs.scorer_key.iloc[0]
        else:
            passed_control = total_control = passed_treatment = total_treatment = None
            score_control = score_treatment = None
            delta_checks = delta_score = correct_control = correct_treatment = scorer = None

        condition_metrics = {}
        for condition in ("control", "treatment"):
            assigned = (
                trials[(trials.task_id == task) & (trials.condition == condition)]
                if not trials.empty
                else trials
            )
            planned = task_plan[task_plan.condition == condition]
            expected_trials = len(planned) if not task_plan.empty else len(assigned)
            counts = assigned.mcp_calls_observed.dropna()
            calls_known = (
                expected_trials > 0
                and len(assigned) == expected_trials
                and len(counts) == expected_trials
            )
            call_count = int(counts.sum()) if calls_known else None
            adopters = int(counts.gt(0).sum()) if calls_known else None
            selected_calls = (
                calls[
                    (calls.task_id == task)
                    & (calls.condition == condition)
                    & calls.trial_id.isin(assigned.trial_id.tolist())
                ]
                if not calls.empty
                else calls
            )
            tools = (
                sorted(selected_calls.tool_name.dropna().unique().tolist())
                if not selected_calls.empty
                else []
            )
            if calls_known and call_count == 0:
                errors = docs_not_found = repeats = 0
            else:
                errors = (
                    int(selected_calls.is_error.eq(True).sum())
                    if calls_known
                    and len(selected_calls) == call_count
                    and selected_calls.is_error.notna().all()
                    else None
                )
                docs_not_found = None
                if calls_known and len(selected_calls) == call_count:
                    codes = []
                    for raw in selected_calls.error_codes_json.dropna():
                        try:
                            value = json.loads(raw) if isinstance(raw, str) else raw
                        except (TypeError, ValueError):
                            value = []
                        codes.extend(value if isinstance(value, list) else [])
                    docs_not_found = sum(value == "docs_not_found" for value in codes)
                repeats = (
                    int(
                        selected_calls.repeat_kind.isin(
                            ["identical", "identical_after_error"]
                        ).sum()
                    )
                    if calls_known
                    and len(selected_calls) == call_count
                    and selected_calls.repeat_kind.notna().all()
                    else None
                )
            duration_values = assigned.duration_seconds.dropna()
            usage_values = assigned.api_total_tokens.dropna()
            list_values = assigned.list_tools.dropna()
            condition_metrics.update(
                {
                    f"trials_{condition}": expected_trials,
                    f"observed_trials_{condition}": len(assigned),
                    f"mcp_calls_{condition}": call_count,
                    f"mcp_adoption_numerator_{condition}": adopters,
                    f"mcp_adoption_denominator_{condition}": expected_trials
                    if calls_known
                    else len(counts),
                    f"mcp_adoption_rate_{condition}": adopters / expected_trials
                    if calls_known and expected_trials
                    else None,
                    f"mcp_errors_{condition}": errors,
                    f"docs_not_found_{condition}": docs_not_found,
                    f"exact_repeats_{condition}": repeats,
                    f"tools_used_{condition}": ", ".join(tools) if tools else None,
                    f"list_tools_{condition}": int(list_values.sum())
                    if len(assigned) == expected_trials
                    and expected_trials > 0
                    and len(list_values) == expected_trials
                    else None,
                    f"duration_mean_{condition}": float(duration_values.mean())
                    if len(duration_values)
                    else None,
                    f"duration_observations_{condition}": int(len(duration_values)),
                    f"api_tokens_{condition}": int(usage_values.sum())
                    if len(usage_values)
                    else None,
                    f"api_usage_observations_{condition}": int(len(usage_values)),
                    f"observed_costs_{condition}": assigned[assigned.cost_amount.notna()]
                    .groupby("cost_currency", dropna=False)
                    .cost_amount.sum()
                    .to_dict(),
                }
            )
        output.append(
            {
                "run_id": run_id,
                "task_id": task,
                "condition_a": "control",
                "condition_b": "treatment",
                "trial_ids_a": "; ".join(
                    sorted(
                        trials[(trials.task_id == task) & (trials.condition == "control")].trial_id
                    )
                )
                or None,
                "trial_ids_b": "; ".join(
                    sorted(
                        trials[
                            (trials.task_id == task) & (trials.condition == "treatment")
                        ].trial_id
                    )
                )
                or None,
                "score_a": score_control,
                "score_b": score_treatment,
                "passed_a": passed_control,
                "total_a": total_control,
                "passed_b": passed_treatment,
                "total_b": total_treatment,
                "delta_checks": delta_checks,
                "delta_score": delta_score,
                "fully_correct_a": correct_control,
                "fully_correct_b": correct_treatment,
                "matched_repetitions": matched,
                "planned_repetitions": expected,
                "complete_pairing": complete and same_denominators,
                "scorer_identity": scorer,
                "scorer_generation": scorer_generation(scorer),
                **condition_metrics,
            }
        )
    return pd.DataFrame(output)


def _all_correct(values):
    if values.isna().any():
        return None
    return bool(values.astype(bool).all())


def run_metrics(connection, run_id, *, scoring_id="original"):
    runs = run_catalog(connection)
    selected = runs[runs.run_id == run_id]
    metadata = selected.iloc[0].to_dict() if not selected.empty else {}
    if metadata.get("experiment_id") == "b1-discovery":
        return _b1_run_metrics(connection, run_id, scoring_id, metadata)
    tasks = adoption_by_task(connection, run_id, scoring_id=scoring_id)
    trials = trials_frame(connection, scoring_id=scoring_id, filters={"run_id": [run_id]})
    pairs = paired_trials(connection, scoring_id=scoring_id, filters={"run_id": [run_id]})
    generations = (
        set(pairs.scorer_key.map(scorer_generation).tolist()) if not pairs.empty else set()
    )
    one_generation = len(generations) <= 1 and "unknown" not in generations
    task_scores_known = (
        not tasks.empty and tasks.passed_b.notna().all() and tasks.total_b.notna().all()
    )
    full_and_complete = (
        metadata.get("full_status") == "full_comparable"
        and not tasks.empty
        and tasks.evidence_status.eq("Complete unique A/B pairing").all()
    )
    ab_comparable = bool(full_and_complete and one_generation)
    reasons = []
    if metadata.get("full_status") != "full_comparable":
        reasons.append("Run scope is not a verified full registered benchmark scope.")
    if not one_generation:
        reasons.append("V1/V2 or unknown scorer generations are not pooled.")
    if not tasks.empty and not tasks.evidence_status.eq("Complete unique A/B pairing").all():
        reasons.append("At least one task has incomplete or ambiguous A/B pairing.")

    def pair_counts(column):
        if pairs.empty or not one_generation:
            return None, None
        count = pairs[column].notna().sum()
        total = pairs[column.replace("passed", "total")].sum() if count else None
        value = pairs[column].sum() if count else None
        return (int(value), int(total)) if value is not None and total is not None else (None, None)

    passed_a, total_a = pair_counts("without_passed")
    passed_b, total_b = pair_counts("with_passed")
    fully_a = tasks.fully_correct_a if not tasks.empty else pd.Series(dtype=object)
    fully_b = tasks.fully_correct_b if not tasks.empty else pd.Series(dtype=object)
    known_fully_a = fully_a.dropna()
    known_fully_b = fully_b.dropna()
    fully_correct_a = int(known_fully_a.astype(bool).sum()) if len(known_fully_a) else None
    fully_correct_b = int(known_fully_b.astype(bool).sum()) if len(known_fully_b) else None
    eligible = tasks[tasks.mcp_available == True] if not tasks.empty else tasks  # noqa: E712
    known_adoption = eligible.mcp_called.dropna() if not eligible.empty else pd.Series(dtype=object)
    adoption = (
        float(known_adoption.astype(bool).sum() / len(eligible))
        if len(eligible) and len(known_adoption) == len(eligible)
        else None
    )
    call_counts = eligible.mcp_calls.dropna() if not eligible.empty else pd.Series(dtype=object)
    calls_total = (
        int(call_counts.sum()) if len(call_counts) == len(eligible) and len(eligible) else None
    )
    error_counts = eligible.mcp_errors.dropna() if not eligible.empty else pd.Series(dtype=object)
    errors_total = (
        int(error_counts.sum()) if len(error_counts) == len(eligible) and len(eligible) else None
    )
    error_rate = (
        errors_total / calls_total
        if errors_total is not None and calls_total
        else (0.0 if errors_total == 0 and calls_total == 0 else None)
    )
    calls = run_tool_calls(connection, run_id)
    repeats_known = calls.repeat_kind.notna() if not calls.empty else pd.Series(dtype=bool)
    exact_repeats = (
        int(
            calls.loc[repeats_known, "repeat_kind"]
            .isin(["identical", "identical_after_error"])
            .sum()
        )
        if repeats_known.any()
        else None
    )
    b_trials = trials[trials["mode"] == "with-mcp"]
    duration_b = (
        float(b_trials.duration_seconds.mean())
        if not b_trials.empty and b_trials.duration_seconds.notna().any()
        else None
    )
    usage_values = b_trials.api_total_tokens.dropna()
    usage = int(usage_values.sum()) if len(usage_values) else None
    cost_rows = b_trials[b_trials.cost_amount.notna()]
    costs = (
        cost_rows.groupby("cost_currency", dropna=False).cost_amount.sum().to_dict()
        if not cost_rows.empty
        else {}
    )
    return {
        "run_id": run_id,
        "full_status": metadata.get("full_status"),
        "full_status_reason": metadata.get("full_status_reason"),
        "score_generations": sorted(generations),
        "passed_checks_a": passed_a,
        "total_checks_a": total_a,
        "passed_checks_b": passed_b,
        "total_checks_b": total_b,
        "delta_checks": passed_b - passed_a
        if ab_comparable and passed_a is not None and passed_b is not None and total_a == total_b
        else None,
        "fully_correct_a": fully_correct_a,
        "fully_correct_b": fully_correct_b,
        "fully_correct_a_denominator": int(known_fully_a.count()),
        "fully_correct_b_denominator": int(known_fully_b.count()),
        "mcp_adoption": adoption,
        "mcp_adoption_numerator": int(known_adoption.astype(bool).sum())
        if len(known_adoption)
        else None,
        "mcp_adoption_denominator": len(eligible),
        "mcp_adoption_observations": len(known_adoption),
        "mcp_calls": calls_total,
        "mcp_errors": errors_total,
        "mcp_error_rate": error_rate,
        "exact_repeats": exact_repeats,
        "duration_b_seconds_mean": duration_b,
        "api_tokens_b": usage,
        "api_usage_observations_b": int(len(usage_values)),
        "api_usage_trials_b": int(len(b_trials)),
        "observed_costs_b": costs,
        "cost_observations_b": int(len(cost_rows)),
        "cost_trials_b": int(len(b_trials)),
        "ab_comparable": ab_comparable,
        "ab_warnings": reasons,
        "tool_calls_source": "V2 run-level projections"
        if not calls.empty and calls.telemetry_version.eq("2.0").all()
        else "V1 trial telemetry"
        if not calls.empty
        else "unavailable",
        "task_scores_known": task_scores_known,
    }


def _b1_run_metrics(connection, run_id, scoring_id, metadata):
    trials = trials_frame(connection, scoring_id=scoring_id, filters={"run_id": [run_id]})
    task_pairs = adoption_by_task(connection, run_id, scoring_id=scoring_id)
    calls = run_tool_calls(connection, run_id)
    condition_metrics = []
    for condition in ("control", "treatment"):
        assigned = trials[trials.condition == condition] if not trials.empty else trials
        counts = assigned.mcp_calls_observed.dropna()
        calls_known = len(assigned) == 6 and len(counts) == 6
        call_count = int(counts.sum()) if calls_known else None
        adopters = int(counts.gt(0).sum()) if calls_known else None
        selected_calls = calls[calls.condition == condition] if not calls.empty else calls
        if calls_known and call_count == 0:
            errors = docs_not_found = repeats = 0
        else:
            errors = (
                int(selected_calls.is_error.eq(True).sum())
                if calls_known
                and len(selected_calls) == call_count
                and selected_calls.is_error.notna().all()
                else None
            )
            docs_not_found = None
            if calls_known and len(selected_calls) == call_count:
                error_codes = []
                for raw in selected_calls.error_codes_json.dropna():
                    try:
                        values = json.loads(raw) if isinstance(raw, str) else raw
                    except (TypeError, ValueError):
                        values = []
                    error_codes.extend(values if isinstance(values, list) else [])
                docs_not_found = sum(value == "docs_not_found" for value in error_codes)
            repeats = (
                int(selected_calls.repeat_kind.isin(["identical", "identical_after_error"]).sum())
                if calls_known
                and len(selected_calls) == call_count
                and selected_calls.repeat_kind.notna().all()
                else None
            )
        usage = assigned.api_total_tokens.dropna()
        costs = assigned[assigned.cost_amount.notna()]
        duration = assigned.duration_seconds.dropna()
        condition_metrics.append(
            {
                "condition": condition,
                "planned_trials": 6,
                "observed_trials": int(len(assigned)),
                "scored_trials": int(assigned.passed.notna().sum()) if not assigned.empty else 0,
                "mcp_calls": call_count,
                "mcp_adoption_numerator": adopters,
                "mcp_adoption_denominator": 6 if calls_known else int(len(counts)),
                "mcp_adoption_rate": adopters / 6 if calls_known else None,
                "mcp_errors": errors,
                "docs_not_found": docs_not_found,
                "exact_repeats": repeats,
                "tool_search_calls": int(assigned.tool_search_calls.sum())
                if len(assigned) == 6 and assigned.tool_search_calls.notna().all()
                else None,
                "duration_mean_seconds": float(duration.mean()) if len(duration) else None,
                "duration_observations": int(len(duration)),
                "api_tokens": int(usage.sum()) if len(usage) else None,
                "api_usage_observations": int(len(usage)),
                "observed_costs": costs.groupby("cost_currency", dropna=False)
                .cost_amount.sum()
                .to_dict(),
                "cost_observations": int(len(costs)),
            }
        )
    score_columns = [
        "task_id",
        "scorer_identity",
        "scorer_generation",
        "matched_repetitions",
        "planned_repetitions",
        "score_a",
        "score_b",
        "delta_checks",
        "delta_score",
        "complete_pairing",
    ]
    task_scores = (
        task_pairs[score_columns].to_dict(orient="records") if not task_pairs.empty else []
    )
    return {
        "run_id": run_id,
        "experiment_id": "b1-discovery",
        "full_status": metadata.get("full_status"),
        "full_status_reason": metadata.get("full_status_reason"),
        "ab_comparable": False,
        "ab_warnings": [
            "B1 uses different scorer versions across tasks; compare scores only within "
            "each matched task."
        ],
        "condition_metrics": condition_metrics,
        "task_score_pairs": task_scores,
        "tool_calls_source": "V1 trial telemetry" if not calls.empty else "unavailable",
    }


def compare_runs(connection, baseline_id, comparison_id, *, scoring_id="original"):
    """Descriptive comparison; exposes compatibility blockers and confounding metadata."""
    catalog = run_catalog(connection)
    base_row = catalog[catalog.run_id == baseline_id]
    comp_row = catalog[catalog.run_id == comparison_id]
    if base_row.empty or comp_row.empty or baseline_id == comparison_id:
        return pd.DataFrame(), ["Choose two different imported Run IDs."], False
    base_meta, comp_meta = base_row.iloc[0], comp_row.iloc[0]
    warnings = []
    score_compatible = True
    for column, label in (("tasks_json", "task scope"), ("conditions_json", "conditions")):
        if base_meta.get(column) != comp_meta.get(column):
            warnings.append(f"{label.title()} differ; score delta is unavailable.")
            score_compatible = False
    if base_meta.get("repetitions") != comp_meta.get("repetitions"):
        warnings.append("Repetition counts differ; score delta is unavailable.")
        score_compatible = False
    base_trials = trials_frame(connection, scoring_id=scoring_id, filters={"run_id": [baseline_id]})
    comp_trials = trials_frame(
        connection, scoring_id=scoring_id, filters={"run_id": [comparison_id]}
    )
    base_signature = _scorer_signature(base_trials)
    comp_signature = _scorer_signature(comp_trials)
    if base_signature != comp_signature or not base_signature:
        warnings.append("Scorer versions differ or are unavailable; score delta is unavailable.")
        score_compatible = False
    base_gen = {scorer_generation(value) for values in base_signature.values() for value in values}
    comp_gen = {scorer_generation(value) for values in comp_signature.values() for value in values}
    if len(base_gen | comp_gen) > 1 or "unknown" in (base_gen | comp_gen):
        warnings.append("V1 and V2 scorer results cannot be compared on one score scale.")
        score_compatible = False
    base_tasks = adoption_by_task(connection, baseline_id, scoring_id=scoring_id)
    comp_tasks = adoption_by_task(connection, comparison_id, scoring_id=scoring_id)
    base_denominators = {
        row.task_id: int(row.total_b) for row in base_tasks.itertuples() if pd.notna(row.total_b)
    }
    comp_denominators = {
        row.task_id: int(row.total_b) for row in comp_tasks.itertuples() if pd.notna(row.total_b)
    }
    if base_denominators != comp_denominators:
        warnings.append("Per-task score denominators differ; score delta is unavailable.")
        score_compatible = False
    for column, label in (
        ("model", "model"),
        ("effort", "reasoning effort"),
        ("benchmark_suite", "benchmark suite"),
        ("prompt_versions_json", "prompt versions"),
        ("task_input_hashes_json", "task prompt/input identity"),
        ("environment_json", "environment"),
        ("toolset", "MCP toolset"),
        ("source_sha256", "MCP source digest"),
        ("images_json", "image digests"),
        ("package_pins_json", "package pins"),
    ):
        left, right = base_meta.get(column), comp_meta.get(column)
        if left is not None and right is not None and left != right:
            warnings.append(f"{label.title()} differ; causal interpretation is limited.")
        elif (left is None) != (right is None):
            warnings.append(f"{label.title()} are unavailable for one run.")
    if (
        base_meta.get("full_status") != "full_comparable"
        or comp_meta.get("full_status") != "full_comparable"
    ):
        warnings.append(
            "At least one run is partial or has unknown scope; score delta is unavailable."
        )
        score_compatible = False
    if not score_compatible:
        warnings.append("Non-score telemetry remains descriptive where observed.")

    base_metrics = run_metrics(connection, baseline_id, scoring_id=scoring_id)
    comp_metrics = run_metrics(connection, comparison_id, scoring_id=scoring_id)
    rows = []
    metric_pairs = [
        (
            "Fully correct B",
            base_metrics["fully_correct_b"] if score_compatible else None,
            comp_metrics["fully_correct_b"] if score_compatible else None,
            score_compatible,
        ),
        (
            "Passed checks B",
            base_metrics["passed_checks_b"] if score_compatible else None,
            comp_metrics["passed_checks_b"] if score_compatible else None,
            score_compatible,
        ),
        ("MCP adoption", base_metrics["mcp_adoption"], comp_metrics["mcp_adoption"], True),
        ("MCP calls", base_metrics["mcp_calls"], comp_metrics["mcp_calls"], True),
        ("MCP error rate", base_metrics["mcp_error_rate"], comp_metrics["mcp_error_rate"], True),
        ("Exact repeats", base_metrics["exact_repeats"], comp_metrics["exact_repeats"], True),
        (
            "Duration B (seconds)",
            base_metrics["duration_b_seconds_mean"],
            comp_metrics["duration_b_seconds_mean"],
            True,
        ),
        ("API tokens B", base_metrics["api_tokens_b"], comp_metrics["api_tokens_b"], True),
    ]
    for name, before, after, compatible in metric_pairs:
        delta = after - before if compatible and before is not None and after is not None else None
        rows.append(
            {
                "baseline_run_id": baseline_id,
                "comparison_run_id": comparison_id,
                "metric": name,
                "baseline": before,
                "comparison": after,
                "delta": delta,
            }
        )
    base_costs = base_metrics["observed_costs_b"]
    comp_costs = comp_metrics["observed_costs_b"]
    currencies = set(base_costs) | set(comp_costs)
    if len(currencies) == 1:
        currency = next(iter(currencies))
        before, after = base_costs.get(currency), comp_costs.get(currency)
        rows.append(
            {
                "baseline_run_id": baseline_id,
                "comparison_run_id": comparison_id,
                "metric": f"Observed cost B ({currency or 'currency unavailable'})",
                "baseline": before,
                "comparison": after,
                "delta": after - before if before is not None and after is not None else None,
            }
        )
    else:
        rows.append(
            {
                "baseline_run_id": baseline_id,
                "comparison_run_id": comparison_id,
                "metric": "Observed cost B (mixed or unavailable currency)",
                "baseline": None,
                "comparison": None,
                "delta": None,
            }
        )
    return pd.DataFrame(rows), warnings, score_compatible


def _scorer_signature(trials):
    if trials.empty:
        return {}
    result = {}
    for task, rows in trials.groupby("task_id", dropna=False):
        result[str(task)] = tuple(sorted(set(rows.scorer_version.dropna().tolist())))
    return result


def selection_keys(frame):
    return (frame.run_id + "/" + frame.trial_id).tolist()


def _first_non_null(primary, fallback):
    """Prefer the client sequence while treating pandas.NA as missing, not false."""
    for value in (primary, fallback):
        if value is None:
            continue
        missing = pd.isna(value)
        if missing is not pd.NA and bool(missing):
            continue
        return value
    return None


def calls_frame(connection, keys, *, counted_only=False):
    return connection.execute(
        """SELECT * FROM mcp_calls
        WHERE concat(run_id, '/', trial_id) IN (SELECT unnest(?))"""
        + (" AND counted" if counted_only else "")
        + " ORDER BY run_id, trial_id, observation_source, call_id",
        [list(keys)],
    ).fetchdf()


def run_tool_calls(connection, run_id):
    """Return one canonical per-call source for the selected run."""
    try:
        b1 = connection.execute(
            "SELECT experiment_id='b1-discovery' FROM run_metadata WHERE run_id=?", [run_id]
        ).fetchone()[0]
    except (duckdb.CatalogException, TypeError):
        b1 = False
    try:
        v2 = connection.execute(
            """SELECT * FROM mcp_observations_v2 WHERE run_id=?
            ORDER BY coalesce(client_call_number,server_call_number),observation_id""",
            [run_id],
        ).fetchdf()
    except duckdb.CatalogException:
        v2 = pd.DataFrame()
    if b1:
        # B1 attribution depends on trial condition; V2 projections are run-only.
        v2 = pd.DataFrame()
    if not v2.empty:
        rows = []
        # A client row represents one observed attempt. Add only server-only rows;
        # ordinal-linked server rows would double count and have no confirmed call id.
        canonical = v2[
            (v2.source == "agent_stream")
            | ((v2.source == "mcp_server") & (v2.correlation_quality == "unmatched_server"))
        ]
        for _, row in canonical.iterrows():
            request = json.loads(row.request_projection_json)
            response = json.loads(row.response_projection_json)
            rows.append(
                {
                    "run_id": run_id,
                    "task_id": None,
                    "trial_id": None,
                    "condition": None,
                    "call_sequence": _first_non_null(
                        row.client_call_number, row.server_call_number
                    ),
                    "tool_name": row.tool_name,
                    "observation_source": row.source,
                    "status": response.get("status", "unknown"),
                    "is_error": response.get("is_error"),
                    "error_codes_json": json.dumps(response.get("error_codes"))
                    if response.get("error_codes") is not None
                    else None,
                    "request_fingerprint": request.get("query_fingerprint"),
                    "package_name": request.get("package") or response.get("package"),
                    "repository": request.get("repository") or response.get("repository"),
                    "function_name": request.get("function"),
                    "request_bytes": request.get("request_bytes"),
                    "result_bytes": response.get("response_bytes"),
                    "server_duration_ms": row.duration_ms
                    if row.source == "mcp_server" and row.correlation_quality == "unmatched_server"
                    else None,
                    "client_duration_ms": row.duration_ms if row.source == "agent_stream" else None,
                    "repeat_kind": None,
                    "repeat_count": None,
                    "verification_status": response.get("verification_status"),
                    "source_count": response.get("source_count"),
                    "event_evidence_reference": (
                        f"mcp_observations_v2.jsonl::{row.observation_id[:16]}"
                    ),
                    "telemetry_version": "2.0",
                    "correlation_quality": row.correlation_quality,
                    "request_projection_json": row.request_projection_json,
                    "response_projection_json": row.response_projection_json,
                }
            )
        return pd.DataFrame(rows)
    try:
        trials = connection.execute(
            "SELECT trial_id,task_id,condition FROM trials WHERE run_id=?", [run_id]
        ).fetchdf()
    except duckdb.CatalogException:
        trials = connection.execute(
            "SELECT trial_id,task_id FROM trials WHERE run_id=?", [run_id]
        ).fetchdf()
        trials["condition"] = None
    keys = [f"{run_id}/{trial_id}" for trial_id in trials.trial_id.tolist()]
    calls = calls_frame(connection, keys, counted_only=True)
    if calls.empty:
        return pd.DataFrame(
            columns=[
                "run_id",
                "task_id",
                "trial_id",
                "condition",
                "call_sequence",
                "tool_name",
                "observation_source",
                "status",
                "is_error",
                "error_codes_json",
                "request_fingerprint",
                "package_name",
                "repository",
                "function_name",
                "request_bytes",
                "result_bytes",
                "server_duration_ms",
                "client_duration_ms",
                "repeat_kind",
                "repeat_count",
                "verification_status",
                "source_count",
                "event_evidence_reference",
                "telemetry_version",
                "correlation_quality",
                "request_projection_json",
                "response_projection_json",
            ]
        )
    calls = calls.merge(trials, on=["trial_id"], how="left", validate="many_to_one")
    for column in (
        "call_sequence",
        "request_fingerprint",
        "package_name",
        "repository",
        "function_name",
        "duration_ms",
        "request_bytes",
        "result_bytes",
        "repeat_kind",
        "repeat_count",
        "verification_status",
        "source_count",
        "correlation",
        "error_codes_json",
        "is_error",
        "telemetry_version",
    ):
        if column not in calls:
            calls[column] = None
    calls["server_duration_ms"] = calls.duration_ms
    calls["client_duration_ms"] = None
    calls["event_evidence_reference"] = calls.apply(
        lambda row: f"telemetry.jsonl::{row.trial_id}::{row.call_id}", axis=1
    )
    calls["telemetry_version"] = calls.observation_source
    calls["correlation_quality"] = calls.correlation
    calls["request_projection_json"] = None
    calls["response_projection_json"] = None
    return calls.rename(
        columns={
            "call_sequence": "call_sequence",
            "error_codes_json": "error_codes_json",
        }
    )


def tool_effectiveness(connection, run_id):
    calls = run_tool_calls(connection, run_id)
    columns = [
        "condition",
        "tool_name",
        "total_calls",
        "successful_calls",
        "application_errors",
        "error_rate",
        "distinct_safe_requests",
        "exact_repeats",
        "repeat_rate",
        "request_bytes",
        "response_bytes",
        "average_server_latency_ms",
        "median_server_latency_ms",
        "server_latency_observations",
        "tasks_using_tool",
        "verified_source_responses",
        "telemetry_source",
    ]
    if calls.empty:
        return pd.DataFrame(columns=columns), calls
    output = []
    group_columns = ["tool_name"]
    if "condition" in calls and calls.condition.notna().any():
        group_columns = ["condition", "tool_name"]
    for group_key, group in calls.groupby(group_columns, dropna=False, sort=True):
        if len(group_columns) == 1:
            condition = None
            tool = group_key[0] if isinstance(group_key, tuple) else group_key
        else:
            condition, tool = group_key
        outcomes = group[group.is_error.notna()]
        repeats = group[group.repeat_kind.notna()]
        latency = group.server_duration_ms.dropna()
        request_rows = group[group.request_fingerprint.notna()]
        distinct_requests = (
            request_rows.drop_duplicates(
                ["trial_id", "request_fingerprint"]
                if "trial_id" in request_rows and request_rows.trial_id.notna().any()
                else ["request_fingerprint"]
            ).shape[0]
            if len(request_rows) and request_rows.trial_id.notna().any()
            else None
        )
        verified = group[
            (group.verification_status == "verified") & group.source_count.fillna(0).gt(0)
        ]
        output.append(
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
                "distinct_safe_requests": int(distinct_requests)
                if distinct_requests is not None
                else None,
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
                "tasks_using_tool": int(group.task_id.nunique())
                if group.task_id.notna().any()
                else None,
                "verified_source_responses": len(verified) if not group.empty else None,
                "telemetry_source": ", ".join(sorted(group.telemetry_version.dropna().unique())),
            }
        )
    return pd.DataFrame(output, columns=columns).sort_values(
        ["total_calls", "condition", "tool_name"], ascending=[False, True, True]
    ), calls


def tool_summary(connection, keys, *, scoring_id="original"):
    sql, params = trial_query(
        scoring_id=scoring_id, keys=keys, revision_columns=_revision_columns(connection)
    )
    return connection.execute(
        f"""WITH selected AS ({sql}) SELECT tool_name, observation_source,
        t.configuration_key, t.scorer_key, t.compatibility_key,
        count(*) AS observed_calls,
        sum(CASE WHEN is_error THEN 1 WHEN is_error=false THEN 0 END) AS failed,
        sum(CASE WHEN is_error=false THEN 1 WHEN is_error THEN 0 END) AS ok_responses,
        sum(partial::INTEGER) AS partial,
        count(is_error) AS outcome_observations, count(partial) AS partial_observations,
        quantile_cont(duration_ms, 0.5) AS p50_ms,
        quantile_cont(duration_ms, 0.95) AS p95_ms,
        count(duration_ms) AS latency_observations,
        sum(result_bytes) AS result_bytes, sum(useful_bytes) AS useful_bytes,
        sum(CASE WHEN repeat_kind IN ('identical', 'identical_after_error') THEN 1
            WHEN repeat_kind IS NOT NULL THEN 0 END) AS repeated_identical,
        sum(CASE WHEN repeat_kind='identical_after_error' THEN 1
            WHEN repeat_kind IS NOT NULL THEN 0 END) AS repeated_after_error,
        sum(CASE WHEN cache_hits IS NOT NULL AND cache_network_requests IS NOT NULL
            THEN cache_hits END)::DOUBLE /
            nullif(sum(CASE WHEN cache_hits IS NOT NULL AND cache_network_requests IS NOT NULL
                THEN cache_hits+cache_network_requests END),0) AS cache_hit_rate,
        sum(version_mismatch::INTEGER) AS version_mismatch
        FROM mcp_calls c JOIN selected t USING(run_id,trial_id) WHERE c.counted
        GROUP BY tool_name, observation_source, t.configuration_key, t.scorer_key,
            t.compatibility_key
        ORDER BY observed_calls DESC, tool_name""",
        params,
    ).fetchdf()


def errors_frame(trials, calls):
    rows = []
    for _, trial in trials.iterrows():
        scopes = [("primary", "primary_error_json"), ("cleanup", "cleanup_errors_json")]
        if "original_primary_error_json" in trial.index:
            scopes.append(("original_primary", "original_primary_error_json"))
        for scope, field in scopes:
            value = trial[field]
            items = json.loads(value) if isinstance(value, str) else []
            items = [items] if isinstance(items, dict) else items
            for item in items or []:
                rows.append(
                    {
                        "run_id": trial.run_id,
                        "trial_id": trial.trial_id,
                        "task_id": trial.task_id,
                        "tool_name": None,
                        "scope": scope,
                        **item,
                        "count": item.get("count") if item.get("count") is not None else 1,
                    }
                )
    for _, call in calls[calls.counted].iterrows():
        codes = (
            json.loads(call.error_codes_json) if isinstance(call.error_codes_json, str) else None
        )
        for problem in classify_mcp_events(
            [
                {
                    "is_error": None if pd.isna(call.is_error) else bool(call.is_error),
                    "partial": None if pd.isna(call.partial) else bool(call.partial),
                    "error_codes": codes,
                }
            ]
        ):
            rows.append(
                {
                    "run_id": call.run_id,
                    "trial_id": call.trial_id,
                    "task_id": call.trial_id.split("-")[0],
                    "tool_name": call.tool_name,
                    "scope": "mcp",
                    **problem,
                    "observation_source": call.observation_source,
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "run_id",
            "trial_id",
            "task_id",
            "tool_name",
            "scope",
            "origin",
            "category",
            "reason_code",
            "source_code",
            "count",
            "observation_source",
        ],
    )


def csv_export(frame):
    safe = frame.copy()
    for column in safe.select_dtypes(include=["object", "string"]).columns:
        safe[column] = safe[column].map(
            lambda value: (
                "'" + value
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                else value
            )
        )
    return safe.to_csv(index=False).encode("utf-8-sig")


def markdown_export(frame):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    return "\n".join(
        [
            "| " + " | ".join(map(cell, frame.columns)) + " |",
            "| " + " | ".join("---" for _ in frame.columns) + " |",
            *(
                "| " + " | ".join(map(cell, row)) + " |"
                for row in frame.itertuples(index=False, name=None)
            ),
        ]
    )


def artifact_preview(results_root, relative_path, expected_sha256):
    if (
        not relative_path.endswith(("/answer.json", "/solution.R"))
        or "/artifacts/" not in relative_path
    ):
        raise ValueError("unsupported_preview_artifact")
    content, sha, _ = read_bytes(results_root, relative_path, limit=MAX_PREVIEW)
    if sha != expected_sha256:
        raise ValueError("artifact_checksum_changed")
    text = content.decode("utf-8")
    if relative_path.endswith(".json"):
        value = json.loads(text)

        def project(item, depth=0):
            if depth > 8:
                return "[depth limit]"
            if isinstance(item, dict):
                return {
                    key: project(value, depth + 1)
                    for key, value in list(item.items())[:100]
                    if not any(
                        word in key.lower()
                        for word in (
                            "reasoning",
                            "analysis",
                            "chain_of_thought",
                            "environment",
                            "authorization",
                            "secret",
                            "password",
                            "api_key",
                            "token",
                            "arguments",
                        )
                    )
                }
            if isinstance(item, list):
                return [project(value, depth + 1) for value in item[:100]]
            return redact_preview(item[:5000]) if isinstance(item, str) else item

        text = json.dumps(project(value), ensure_ascii=False, indent=2)
    return redact_preview(text) if relative_path.endswith(".R") else text


def audit_classifications(run_id, task_id=None):
    """Read the fixed offline audit CSV as secondary text; never follow its paths."""
    path = DEFAULT_REPORTS / "baseline_failure_matrix.csv"
    if not path.is_file():
        return pd.DataFrame()
    try:
        content, _, _ = read_bytes(DEFAULT_REPORTS, path.name, limit=4 << 20)
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        selected = []
        for index, row in enumerate(reader):
            if index >= 5000:
                break
            if row.get("run_id") != run_id or (task_id and row.get("task") != task_id):
                continue
            selected.append(
                {
                    "run_id": run_id,
                    "task_id": token(row.get("task")),
                    "row_type": _bounded_text(row.get("row_type")),
                    "check_id": _bounded_text(row.get("check_id")),
                    "primary_cause": _bounded_text(row.get("primary_cause")),
                    "secondary_causes": _bounded_text(row.get("secondary_causes")),
                    "confidence": _bounded_text(row.get("confidence")),
                    "evidence_level": _bounded_text(row.get("evidence_level")),
                    "observed": _bounded_text(row.get("observed")),
                    "mcp_remedy": _bounded_text(row.get("mcp_remedy")),
                    "additional_verification": _bounded_text(row.get("additional_verification")),
                    "evidence_reference": _bounded_text(row.get("evidence")),
                    "artifact_reference": _bounded_text(row.get("artifact_evidence")),
                }
            )
        return pd.DataFrame(selected)
    except (OSError, UnicodeDecodeError, ValueError):
        return pd.DataFrame()


def _bounded_text(value):
    if not isinstance(value, str) or not value:
        return None
    value = SECRET.sub("[REDACTED]", value)
    return value[:4000]
