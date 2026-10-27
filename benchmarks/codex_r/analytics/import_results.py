"""Rebuild/update local DuckDB analytics from immutable benchmark files.

No runner, network clients, raw events.json, MCP arguments/results or reasoning are
loaded into the database. Each run is replaced atomically from a stable snapshot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from benchmarks.codex_r.analytics import DEFAULT_DATABASE, DEFAULT_REPORTS, DEFAULT_RESULTS, ROOT
from benchmarks.codex_r.analytics.safety import (
    boolean,
    confined,
    digest,
    error,
    number,
    package_pins,
    read_bytes,
    token,
    tokens,
)
from benchmarks.codex_r.telemetry import opportunities, schema, trace_model
from benchmarks.codex_r.telemetry import projection as projection_v2
from benchmarks.codex_r.telemetry.aggregate import METRIC_COLUMNS

TABLES = (
    "trial_opportunity_assessments",
    "task_mcp_opportunities",
    "task_opportunity_registry",
    "observability_checkpoints",
    "agent_spans",
    "agent_traces",
    "mcp_observations_v2",
    "agent_telemetry",
    "score_checks",
    "score_dimensions",
    "mcp_calls",
    "events",
    "scoring_revisions",
    "artifacts",
    "source_files",
    "trial_plan",
    "run_metadata",
    "trials",
    "runs",
    "import_issues",
)
MODES = {"with-mcp", "without-mcp"}
_COLUMNS = {}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else None


def connect(database=DEFAULT_DATABASE, *, read_only=False):
    connection = duckdb.connect(
        str(database), read_only=read_only, config={"enable_external_access": False}
    )
    if not read_only:
        connection.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        _migrate_score_dimensions_key(connection)
        _COLUMNS.clear()
    versions = connection.execute("SELECT schema_version FROM analytics_meta").fetchall()
    supported_versions = (
        ([(1,)], [(2,)], [(3,)], [(4,)], [(5,)], [(6,)]) if read_only else ([(6,)],)
    )
    if versions not in supported_versions:
        connection.close()
        raise ValueError("unsupported_analytics_schema")
    return connection


def _migrate_score_dimensions_key(connection):
    rows = connection.execute("PRAGMA table_info('score_dimensions')").fetchall()
    primary_key = tuple(row[1] for row in sorted(rows, key=lambda row: row[5]) if row[5])
    expected = ("run_id", "trial_id", "scoring_id", "dimension")
    if primary_key == expected:
        return
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            """CREATE TABLE score_dimensions_key_migration (
                run_id VARCHAR, trial_id VARCHAR, scoring_id VARCHAR, scorer_version VARCHAR,
                dimension VARCHAR, status VARCHAR, passed INTEGER, total INTEGER,
                checks_json VARCHAR,
                PRIMARY KEY (run_id, trial_id, scoring_id, dimension)
            )"""
        )
        connection.execute(
            """INSERT INTO score_dimensions_key_migration
            SELECT run_id,trial_id,coalesce(scoring_id,'original'),
                coalesce(scorer_version,'unrecorded'),dimension,status,passed,total,checks_json
            FROM score_dimensions"""
        )
        connection.execute("DROP TABLE score_dimensions")
        connection.execute("ALTER TABLE score_dimensions_key_migration RENAME TO score_dimensions")
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def insert(connection, table, row):
    # Only internal table/column names are interpolated. All values are parameters.
    if table not in TABLES:
        raise ValueError("unknown_analytics_table")
    if table not in _COLUMNS:
        _COLUMNS[table] = {
            item[1] for item in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        }
    columns = _COLUMNS[table]
    if not row or not set(row) <= columns:
        raise ValueError("unknown_analytics_column")
    names = ",".join(f'"{name}"' for name in row)
    connection.execute(
        f"INSERT INTO {table} ({names}) VALUES ({','.join('?' for _ in row)})", list(row.values())
    )


class Snapshot:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.files = {}
        self.issues = Counter()

    def read(self, relative):
        relative = Path(relative).as_posix()
        content, sha, stamp = read_bytes(self.root, relative)
        self.files[relative] = (sha, stamp)
        return content

    def json(self, relative, default=None):
        if not confined(self.root, relative).exists():
            return default
        try:
            return json.loads(self.read(relative))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.issues["partial_or_invalid_json"] += 1
            return default

    def stable(self):
        for relative, (_, stamp) in self.files.items():
            stat = confined(self.root, relative).stat()
            if (stat.st_size, stat.st_mtime_ns) != stamp:
                raise ValueError("source_changed_during_import")


def csv_records(snapshot, relative):
    rows = list(csv.DictReader(io.StringIO(snapshot.read(relative).decode("utf-8-sig"))))
    if len(rows) > 100000:
        raise ValueError("too_many_csv_rows")
    for row in rows:
        for key, value in row.items():
            if value in ("True", "False"):
                row[key] = value == "True"
                continue
            if value in (None, "", "null", "None"):
                row[key] = None
                continue
            text = value[1:] if value.startswith(("'{", "'[")) else value
            try:
                row[key] = json.loads(text)
            except (ValueError, TypeError):
                row[key] = text
    return rows


def read_events(snapshot, run_id):
    relative = f"{run_id}/telemetry.jsonl"
    if not confined(snapshot.root, relative).exists():
        return [], False, False
    content = snapshot.read(relative)
    complete = not content or content.endswith(b"\n")
    lines = content.splitlines()
    if len(lines) > 200000:
        raise ValueError("too_many_telemetry_events")
    if not complete:
        lines = lines[:-1]
        snapshot.issues["partial_jsonl_tail"] += 1
    events, seen = [], set()
    for line in lines:
        if len(line) > 1 << 20:
            snapshot.issues["oversized_jsonl_line"] += 1
            complete = False
            continue
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            snapshot.issues["invalid_jsonl_line"] += 1
            complete = False
            continue
        if schema.validate_event(event) or event.get("run_id") != run_id:
            snapshot.issues["invalid_telemetry_event"] += 1
            complete = False
            continue
        # Schema rejects all free-text fields before we retain any event.
        if any(_contains_secret(value) for value in event.values()):
            snapshot.issues["unsafe_telemetry_identifier"] += 1
            complete = False
            continue
        event_id = hashlib.sha256(encoded(event).encode()).hexdigest()
        if event_id not in seen:
            events.append((event_id, event))
            seen.add(event_id)
    stream_problems = schema.validate_stream([event for _, event in events])
    if stream_problems:
        snapshot.issues["invalid_telemetry_stream"] += len(stream_problems)
        complete = False
    return events, True, complete


def read_v2_observations(snapshot, run_id):
    """Read the separately versioned closed projection; rows remain run-scoped."""
    relative = f"{run_id}/mcp_observations_v2.jsonl"
    if not confined(snapshot.root, relative).exists():
        return [], False, None
    content = snapshot.read(relative)
    if len(content) > projection_v2.MAX_FILE_BYTES:
        snapshot.issues["oversized_v2_observations"] += 1
        return [], True, False
    complete = not content or content.endswith(b"\n")
    lines = content.splitlines()
    if len(lines) > projection_v2.MAX_RECORDS:
        snapshot.issues["too_many_v2_observations"] += 1
        return [], True, False
    if not complete:
        lines = lines[:-1]
        snapshot.issues["partial_v2_jsonl_tail"] += 1
    rows = []
    seen = set()
    for line in lines:
        if len(line) > projection_v2.MAX_LINE_BYTES:
            snapshot.issues["oversized_v2_jsonl_line"] += 1
            complete = False
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            snapshot.issues["invalid_v2_jsonl_line"] += 1
            complete = False
            continue
        if not projection_v2.validate_record(record) or projection_v2._walk_for_secrets(record):
            snapshot.issues["invalid_v2_observation"] += 1
            complete = False
            continue
        observation_id = hashlib.sha256(encoded(record).encode()).hexdigest()
        if observation_id not in seen:
            rows.append((observation_id, record))
            seen.add(observation_id)
    return rows, True, complete


def SECRET_VALUE(value):
    # Do not read environment variables to redact them: accept closed identifiers.
    from benchmarks.codex_r.analytics.safety import SECRET

    return isinstance(value, str) and SECRET.search(value) is not None


def _contains_secret(value):
    if SECRET_VALUE(value):
        return True
    if isinstance(value, dict):
        return any(_contains_secret(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


def read_records(snapshot, run_id):
    records = snapshot.json(f"{run_id}/results.json")
    if isinstance(records, dict):
        if records.get("schema_version") not in (1, "1.0"):
            raise ValueError("unsupported_results_schema")
        records = records.get("results")
    if records is None and confined(snapshot.root, f"{run_id}/results.csv").is_file():
        records = csv_records(snapshot, f"{run_id}/results.csv")
    merged = {}
    for record in records or []:
        if not isinstance(record, dict):
            raise ValueError("invalid_trial_record")
        trial_id = token(record.get("trial_id") or record.get("trial"))
        if trial_id:
            merged[trial_id] = record
        else:
            snapshot.issues["record_without_trial_id"] += 1
    for path in sorted(confined(snapshot.root, run_id).iterdir()):
        if path.is_symlink():
            snapshot.issues["symlink_skipped"] += 1
            continue
        if path.is_dir() and token(path.name) and (path / "result.json").is_file():
            record = snapshot.json(f"{run_id}/{path.name}/result.json")
            if not isinstance(record, dict):
                continue
            if record.get("trial_id", record.get("trial")) != path.name:
                raise ValueError("trial_directory_identity_mismatch")
            merged[path.name] = record
    return merged


def historical_configuration(run_id):
    # Explicit historical registry, never guessed from dates, scores or behavior.
    manifest = json.loads((ROOT / "knowledge_pilot/manifest.json").read_text(encoding="utf-8"))
    matches = [
        name
        for name, value in manifest["configurations"].items()
        if run_id in value.get("runs", [])
    ]
    return matches[0] if len(matches) == 1 else None


def score_values(score):
    score = score if isinstance(score, dict) else {}
    return {
        "passed": number(score.get("passed"), integer=True),
        "total": number(score.get("total"), integer=True),
        "fully_correct": boolean(score.get("fully_correct")),
        "failed_checks_json": encoded(tokens(score.get("failed_checks"))),
    }


def score_checks(connection, run_id, trial_id, score, scoring_id="original"):
    checks = {name: False for name in tokens(score.get("failed_checks")) or []}
    for detail in score.get("details") or []:
        if not isinstance(detail, str) or ": " not in detail:
            continue
        name, status = detail.rsplit(": ", 1)
        if token(name) and status in {"pass", "fail"}:
            checks[name] = status == "pass"
    for dimension, detail in (score.get("dimensions") or {}).items():
        if not token(dimension) or not isinstance(detail, dict):
            continue
        for name, status in (detail.get("checks") or {}).items():
            if token(name) and status in {"pass", "fail"}:
                checks[f"{dimension}.{name}"] = status == "pass"
    for name, passed in checks.items():
        insert(
            connection,
            "score_checks",
            dict(
                run_id=run_id,
                trial_id=trial_id,
                scoring_id=scoring_id,
                check_name=name,
                passed=passed,
            ),
        )


_DIMENSIONS = {
    "schema_validity",
    "factual_correctness",
    "version_repository_identity",
    "dependency_correctness",
    "source_quality",
    "unsupported_claims",
    "evidence_quality",
    "uncertainty_handling",
}
_DIMENSION_STATUSES = {
    "pass",
    "fail",
    "unsupported",
    "unknown",
    "not_evaluated",
    "not_applicable",
}


def score_dimensions(connection, run_id, trial_id, score, scorer_version, scoring_id="original"):
    """Persist known V2 diagnostic dimensions separately from original V1 checks."""
    dimensions = score.get("dimensions") if isinstance(score, dict) else None
    if not isinstance(dimensions, dict):
        return
    for name, value in dimensions.items():
        if name not in _DIMENSIONS or not isinstance(value, dict):
            continue
        status = value.get("status")
        if status not in _DIMENSION_STATUSES:
            continue
        checks = value.get("checks")
        safe_checks = None
        if isinstance(checks, dict):
            safe_checks = {
                key: result
                for key, result in checks.items()
                if token(key) and isinstance(result, str) and result in _DIMENSION_STATUSES
            }
        insert(
            connection,
            "score_dimensions",
            {
                "run_id": run_id,
                "trial_id": trial_id,
                "scoring_id": scoring_id,
                "scorer_version": token(scorer_version, "unrecorded"),
                "dimension": name,
                "status": status,
                "passed": number(value.get("passed"), integer=True),
                "total": number(value.get("total"), integer=True),
                "checks_json": encoded(safe_checks),
            },
        )


def normalized_call(item, *, source, call_id):
    is_error = boolean(item.get("is_error"))
    if is_error is None and item.get("status") in {"error", "ok"}:
        is_error = item["status"] == "error"
    codes = tokens(item.get("error_codes"))
    if codes is None and token(item.get("error_code")):
        codes = [item["error_code"]]
    row = {
        "observation_source": source,
        "call_id": call_id,
        "tool_name": token(item.get("tool") or item.get("tool_name")),
        "counted": False,
        "call_sequence": number(
            item.get("server_call_number", item.get("call_number")), integer=True
        ),
        "request_fingerprint": item.get("argument_fingerprint")
        if isinstance(item.get("argument_fingerprint"), str)
        and re.fullmatch(r"[a-f0-9]{12}", item["argument_fingerprint"])
        else None,
        "package_name": token(item.get("package")),
        "repository": item.get("repository")
        if item.get("repository") in {"cran", "bioconductor", "all"}
        else None,
        "function_name": item.get("function")
        if isinstance(item.get("function"), str)
        and re.fullmatch(r"[A-Za-z0-9._:<>$@%&*+/=!?|^~-]{1,64}", item["function"])
        else None,
        "is_error": is_error,
        "status": "error" if is_error else "ok" if is_error is False else "unknown",
        "partial": boolean(item.get("partial")),
        "duration_ms": number(item.get("duration_ms")),
        "request_bytes": number(item.get("request_bytes"), integer=True),
        "result_bytes": number(item.get("result_bytes", item.get("response_bytes")), integer=True),
        "useful_bytes": number(item.get("useful_bytes"), integer=True),
        "result_tokens_estimate": number(
            item.get("result_tokens_estimate", item.get("response_tokens_estimate")), integer=True
        ),
        "error_codes_json": encoded(codes),
        "verification_status": token(item.get("verification_status")),
        "version_mismatch": boolean(item.get("version_mismatch")),
        "source_count": number(item.get("source_count"), integer=True),
        "output_truncated": boolean(item.get("output_truncated")),
        "page_truncated": boolean(item.get("page_truncated")),
        "repeat_kind": token(item.get("repeat_kind")),
        "repeat_count": number(item.get("repeat_count"), integer=True),
        "cache_hits": number(item.get("cache_hits"), integer=True),
        "cache_network_requests": number(item.get("cache_network_requests"), integer=True),
        "correlation": token(item.get("correlation")),
        "correlated_call_id": token(item.get("correlated_call_id")),
    }
    return row if row["tool_name"] else None


def import_calls(connection, run_id, trial_id, record, events, csv_calls):
    observed = {}
    for _, event in events:
        if event.get("trial_id") != trial_id or event["event_type"] not in schema.TOOL_EVENTS:
            continue
        source = "server_telemetry" if event["source"] == "mcp_server" else "client_events"
        call_id = event["call_id"]
        key = (source, call_id)
        if key in observed and event["event_type"] == "mcp.tool.started":
            continue
        observed[key] = normalized_call(event, source=source, call_id=call_id)
    server = [row for (source, _), row in observed.items() if source == "server_telemetry" and row]
    if not server:
        legacy = (record.get("mcp_telemetry") or {}).get("calls") or csv_calls
        for index, item in enumerate(legacy, 1):
            if item.get("run_id", run_id) != run_id or item.get("trial_id", trial_id) != trial_id:
                raise ValueError("call_identity_mismatch")
            call_id = f"legacy-call-{number(item.get('call_number'), integer=True) or index}"
            observed[("legacy_logs", call_id)] = normalized_call(
                item, source="legacy_logs", call_id=call_id
            )
    canonical = (
        "server_telemetry"
        if server
        else "legacy_logs"
        if any(k[0] == "legacy_logs" for k in observed)
        else "client_events"
    )
    counts = Counter()
    for row in observed.values():
        if row is None:
            continue
        row["counted"] = row["observation_source"] == canonical
        counts[row["observation_source"]] += 1
        insert(connection, "mcp_calls", {"run_id": run_id, "trial_id": trial_id, **row})
    return counts, canonical if observed else None


def import_event(connection, run_id, event_id, event):
    errors = [error(event.get("error")), error(event.get("primary_error"))]
    errors += [error(item) for item in event.get("cleanup_errors", [])]
    insert(
        connection,
        "events",
        {
            "run_id": run_id,
            "event_id": event_id,
            "trial_id": token(event.get("trial_id")),
            "event_type": event["event_type"],
            "timestamp_utc": event["timestamp_utc"],
            "monotonic_offset_ms": event.get("monotonic_offset_ms"),
            "clock": event.get("clock"),
            "source": event["source"],
            "call_id": token(event.get("call_id")),
            "tool_name": token(event.get("tool")),
            "correlation": token(event.get("correlation")),
            "cleanup_operation": token(event.get("cleanup_operation")),
            "cleanup_status": token(event.get("cleanup_status")),
            "error_json": encoded([item for item in errors if item]),
        },
    )


OBSERVABILITY_EVENT_TYPES = frozenset(
    {
        "agent.tool.started",
        "agent.tool.completed",
        "agent.tool.failed",
        "agent.evidence.observed",
        "agent.url.mentioned",
        "agent.answer.claims_observed",
        "mcp.exposure.configured",
        "mcp.exposure.response",
    }
)


def import_agent_telemetry(connection, run_id, event_id, event):
    """Persist only schema-validated, closed observability events."""
    if event["event_type"] not in OBSERVABILITY_EVENT_TYPES:
        return
    insert(
        connection,
        "agent_telemetry",
        {
            "run_id": run_id,
            "event_id": event_id,
            "trial_id": token(event.get("trial_id")),
            "event_type": event["event_type"],
            "event_projection_json": encoded(event),
        },
    )


def _trace_id_for_trial(events, trial_id):
    return next(
        (
            event.get("trace_id")
            for _, event in events
            if event.get("trial_id") == trial_id and event.get("trace_id") is not None
        ),
        None,
    )


def _trial_event_items(events, trial_id):
    return [(event_id, event) for event_id, event in events if event.get("trial_id") == trial_id]


def _mcp_timing(events):
    start = next(
        (event for _, event in events if event.get("event_type") == "benchmark.trial.started"),
        None,
    )
    if not start:
        return None
    calls = [
        event
        for _, event in events
        if event.get("event_type") == "mcp.tool.started"
        and event.get("source") == "agent_stream"
        and event.get("clock") == start.get("clock")
        and type(event.get("monotonic_offset_ms")) in (int, float)
    ]
    if not calls:
        return None
    first = min(event["monotonic_offset_ms"] for event in calls)
    elapsed = first - start.get("monotonic_offset_ms", 0)
    return round(elapsed, 3) if elapsed >= 0 else None


def import_trace_evidence(
    connection,
    run_id,
    records,
    events,
    *,
    jsonl_present,
    jsonl_complete,
    opportunity_manifest,
    opportunity_sha256,
):
    """Persist deterministic trace, checkpoint and opportunity projections in this run txn."""
    opportunity_version = opportunity_manifest["opportunity_version"]
    task_annotations = {item["task_id"]: item for item in opportunity_manifest["tasks"]}
    for task_id, task in task_annotations.items():
        source_path = task.get("source")
        insert(
            connection,
            "task_opportunity_registry",
            {
                "run_id": run_id,
                "opportunity_version": opportunity_version,
                "task_id": task_id,
                "task_family": task["task_family"],
                "annotation_status": "researcher_annotation",
                "source_path": source_path,
                "source_file_sha256": task.get("source_sha256"),
                "opportunity_manifest_sha256": opportunity_sha256,
                "opportunity_count": len(task["opportunities"]),
            },
        )
        for item in task["opportunities"]:
            insert(
                connection,
                "task_mcp_opportunities",
                {
                    "run_id": run_id,
                    "opportunity_version": opportunity_version,
                    "task_id": task_id,
                    "opportunity_id": item["opportunity_id"],
                    "task_family": task["task_family"],
                    "capability": item["capability"],
                    "candidate_tools_json": encoded(item["candidate_tools"]),
                    "relevance": item["relevance"],
                    "source": item["source"],
                    "source_path": source_path,
                    "rationale": item["rationale"],
                    "evidence_class": item["evidence_class"],
                    "source_file_sha256": task.get("source_sha256"),
                    "opportunity_manifest_sha256": opportunity_sha256,
                },
            )
    telemetry_available = bool(jsonl_present)
    for trial_id, record in records.items():
        task_id = token(record.get("task"))
        trial_events = _trial_event_items(events, trial_id)
        trace_id = _trace_id_for_trial(events, trial_id)
        completeness = trace_model.trace_completeness(
            trial_events, jsonl_present=jsonl_present, jsonl_complete=jsonl_complete
        )
        if not telemetry_available:
            spans = []
            integrity_issues = []
            integrity_status = "unavailable"
            checkpoints, assessments = opportunities.derive_trial_evidence(
                run_id=run_id,
                trial_id=trial_id,
                task_id=task_id,
                record=record,
                events=[],
                manifest=opportunity_manifest,
                trace_status="unavailable",
                telemetry_available=False,
                manifest_sha256=opportunity_sha256,
            )
            expected_count = captured_count = missing_count = completeness_ratio = None
            schema_status = "unavailable"
        else:
            spans = (
                trace_model.derive_spans(
                    trial_events, run_id=run_id, trial_id=trial_id, trace_id=trace_id
                )
                if trace_id
                else []
            )
            integrity_issues = (
                trace_model.validate_trace_spans(spans) if trace_id else ["trace_id_unavailable"]
            )
            integrity_status = "invalid" if integrity_issues else "valid"
            schema_status = "valid" if jsonl_complete else "partial"
            checkpoints, assessments = opportunities.derive_trial_evidence(
                run_id=run_id,
                trial_id=trial_id,
                task_id=task_id,
                record=record,
                events=trial_events,
                manifest=opportunity_manifest,
                trace_status=completeness,
                telemetry_available=True,
                manifest_sha256=opportunity_sha256,
            )
            expected = [row for row in checkpoints if row["expected"]]
            captured = [
                row for row in expected if row["observation_status"] in {"observed", "not_observed"}
            ]
            expected_count = len(expected)
            captured_count = len(captured)
            missing_count = expected_count - captured_count
            completeness_ratio = captured_count / expected_count if expected_count else None
        for span in spans:
            insert(
                connection,
                "agent_spans",
                {key: value for key, value in span.items() if key != "_events"},
            )
        for checkpoint in checkpoints:
            insert(connection, "observability_checkpoints", checkpoint)
        for assessment in assessments:
            insert(connection, "trial_opportunity_assessments", assessment)
        trial_span = next((span for span in spans if span["span_kind"] == "trial"), None)
        insert(
            connection,
            "agent_traces",
            {
                "run_id": run_id,
                "trial_id": trial_id,
                "trace_id": trace_id,
                "trace_model_version": trace_model.TRACE_MODEL_VERSION,
                "trace_completeness": completeness,
                "integrity_status": integrity_status,
                "schema_validation_status": schema_status,
                "expected_checkpoint_count": expected_count,
                "captured_checkpoint_count": captured_count,
                "missing_checkpoint_count": missing_count,
                "capture_completeness": completeness_ratio,
                "trial_duration_ms": trial_span.get("duration_ms") if trial_span else None,
                "time_to_first_mcp_ms": _mcp_timing(trial_events),
                "event_count": len(trial_events) if telemetry_available else None,
                "integrity_issues_json": encoded(integrity_issues) if telemetry_available else None,
                "opportunity_manifest_version": opportunity_version,
                "opportunity_manifest_sha256": opportunity_sha256,
            },
        )


def usage_values(record):
    usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    inputs, outputs = (
        usage.get("input_tokens_details") or {},
        usage.get("output_tokens_details") or {},
    )
    values = {
        "api_input_tokens": number(usage.get("input_tokens"), integer=True),
        "api_output_tokens": number(usage.get("output_tokens"), integer=True),
        "api_total_tokens": number(usage.get("total_tokens"), integer=True),
        "api_cached_tokens": number(inputs.get("cached_tokens"), integer=True),
        "api_reasoning_tokens": number(outputs.get("reasoning_tokens"), integer=True),
    }
    values["usage_status"] = (
        "observed" if any(v is not None for v in values.values()) else "unavailable"
    )
    cost = record.get("cost")
    amount = (
        number(cost)
        if type(cost) in (int, float)
        else number(cost.get("amount", cost.get("total_cost")))
        if isinstance(cost, dict)
        else None
    )
    values.update(
        cost_amount=amount,
        cost_currency=token(cost.get("currency")) if isinstance(cost, dict) else None,
        cost_status="observed" if amount is not None else "unavailable",
    )
    return values


def manifest_scorer_version(scorer_versions, task_id, record, task_scorers=None):
    """Resolve task scorer only from explicit suite identity and manifest provenance."""
    if isinstance(task_scorers, dict) and token(task_scorers.get(task_id)):
        return token(task_scorers[task_id])
    if not isinstance(scorer_versions, dict):
        return None
    suite = token(record.get("suite"))
    if suite == "hard-v1" or task_id.startswith("H"):
        return token(scorer_versions.get("hard"))
    if suite == "knowledge-tool-value-v1" or task_id[:1] in {"B", "C", "D", "E"}:
        if task_id.startswith("D"):
            return token(scorer_versions.get("d_recommendation"))
        if task_id in {"E01", "E04", "E05"}:
            return token(scorer_versions.get("e_compatibility"))
        return token(scorer_versions.get("knowledge_pilot"))
    if suite in {"codex-r", "codex-r-pilot-v1"}:
        return token(scorer_versions.get("codex_r"))
    return None


def import_trial(
    connection,
    snapshot,
    run,
    trial_id,
    record,
    events,
    csv_calls,
    csv_metrics,
    scorer_versions=None,
    task_scorers=None,
):
    run_id = run["run_id"]
    if record.get("schema_version", 1) not in (1, "1.0"):
        raise ValueError("unsupported_trial_schema")
    for key in (
        "score",
        "usage",
        "mcp_usage",
        "mcp_telemetry",
        "mcp_metrics",
        "mcp_server_audit",
        "error_summary",
    ):
        if record.get(key) is not None and not isinstance(record[key], dict):
            raise ValueError("invalid_trial_schema")
    if record.get("run_id", run_id) != run_id:
        raise ValueError("trial_run_identity_mismatch")
    task, mode = token(record.get("task")), record.get("mode")
    condition = record.get("condition")
    if condition is not None and condition not in {"control", "treatment"}:
        raise ValueError("invalid_trial_condition")
    if not task or mode not in MODES:
        raise ValueError("missing_trial_task_or_mode")
    calls, provenance = import_calls(connection, run_id, trial_id, record, events, csv_calls)
    usage = record.get("mcp_usage") or {}
    declared = number(usage.get("calls", record.get("mcp_calls")), integer=True)
    known_counts = [value for value in [declared, *calls.values()] if value is not None]
    if mode == "without-mcp" and declared is None:
        known_counts = []  # Do not infer measured counts merely from the assigned condition.
    score = record.get("score") or {}
    if not score and record.get("passed") is not None:
        score = {
            key: record.get(key) for key in ("passed", "total", "failed_checks", "fully_correct")
        }
    scorer_version = token(score.get("scorer_version")) or manifest_scorer_version(
        scorer_versions, task, record, task_scorers
    )
    summary = record.get("error_summary") or {}
    primary = error(summary.get("primary_error"))
    if primary is None and record.get("error"):
        primary = {
            "origin": "runner",
            "category": "unclassified",
            "reason_code": token(record.get("error_type"), "LEGACY_ERROR"),
            "source_code": None,
            "count": 1,
        }
    cleanup = [error(item) for item in summary.get("cleanup_errors", [])]
    if not cleanup and record.get("cleanup_errors"):
        cleanup = [
            {
                "origin": "cleanup",
                "category": "unclassified",
                "reason_code": "LEGACY_CLEANUP_ERROR",
                "source_code": None,
                "count": len(record["cleanup_errors"]),
            }
        ]
    metrics = (record.get("mcp_metrics") or {}).get("overall") or csv_metrics or {}
    metrics = {key: number(metrics.get(key)) for key in METRIC_COLUMNS if key in metrics}
    fingerprint = {
        key: run[key]
        for key in (
            "configuration",
            "source_sha256",
            "images_json",
            "package_pins_json",
            "revision",
            "dirty_fingerprint",
            "toolset",
            "telemetry_schema",
        )
    }
    fingerprint.update(
        model=record.get("model", run["model"]),
        effort=record.get("effort", run["effort"]),
        instructions=record.get("instructions", run["instructions"]),
    )
    if not run["source_sha256"]:
        fingerprint["unrecorded_source_scope"] = run_id
    row = {
        "run_id": run_id,
        "trial_id": trial_id,
        "task_id": task,
        "block": task[0],
        "mode": mode,
        "condition": condition,
        "execution_order": number(record.get("execution_order"), integer=True),
        "experiment_id": token(record.get("experiment_id")),
        "scorer_digest": digest(record.get("scorer_sha256")),
        "prompt_digest": digest(record.get("task_prompt_sha256")),
        "repetition": number(record.get("repetition"), integer=True)
        or (
            int(trial_id.split("-")[2])
            if len(trial_id.split("-")) >= 3 and trial_id.split("-")[2].isdigit()
            else None
        ),
        "model": token(record.get("model"), run["model"]),
        "effort": token(record.get("effort"), run["effort"]),
        "configuration": token(record.get("configuration_id"), run["configuration"]),
        "instructions": token(record.get("instructions"), run["instructions"]),
        "compatibility_key": hashlib.sha256(encoded(fingerprint).encode()).hexdigest()[:16],
        "status": token(record.get("status")),
        "finalized": bool(record.get("completed_at")),
        "scorer_version": scorer_version,
        **score_values(score),
        "duration_seconds": number(record.get("duration_seconds")),
        "agent_seconds": number(record.get("agent_seconds")),
        "mcp_calls_observed": max(known_counts) if known_counts else None,
        "client_calls": declared if declared is not None else calls.get("client_events"),
        "server_calls": calls.get("server_telemetry", calls.get("legacy_logs")),
        "list_tools": number(
            (record.get("mcp_server_audit") or {}).get(
                "list_tools_requests", record.get("server_list_tools")
            ),
            integer=True,
        ),
        "tool_search_calls": number(
            usage.get("tool_search_calls", record.get("tool_search_calls")), integer=True
        ),
        "metrics_source": provenance,
        "metrics_json": encoded(metrics),
        "primary_error_json": encoded(primary),
        "cleanup_errors_json": encoded([item for item in cleanup if item]),
        "cleanup_completed": boolean(record.get("cleanup_completed")),
        "session_deleted": boolean(record.get("session_deleted")),
        "interrupted": boolean(record.get("interrupted")),
        **usage_values(record),
        "started_at": record.get("started_at")
        if schema.TIMESTAMP.fullmatch(str(record.get("started_at")))
        else None,
        "completed_at": record.get("completed_at")
        if schema.TIMESTAMP.fullmatch(str(record.get("completed_at")))
        else None,
    }
    insert(connection, "trials", row)
    score_checks(connection, run_id, trial_id, score)
    score_dimensions(connection, run_id, trial_id, score, scorer_version)
    for artifact in ("answer.json", "solution.R"):
        relative = f"{run_id}/{trial_id}/artifacts/{artifact}"
        if confined(snapshot.root, relative).is_file():
            content = snapshot.read(relative)
            expected = (record.get("artifact_sources") or {}).get(artifact) or (
                score.get("artifacts") or {}
            ).get(artifact)
            if digest(expected) and expected != hashlib.sha256(content).hexdigest():
                snapshot.issues["artifact_original_checksum_mismatch"] += 1
            insert(
                connection,
                "artifacts",
                dict(
                    run_id=run_id,
                    trial_id=trial_id,
                    relative_path=relative,
                    sha256=hashlib.sha256(content).hexdigest(),
                    bytes=len(content),
                    kind=artifact,
                ),
            )
    return row


def import_revisions(connection, run_id, trial_ids, reports):
    for path in sorted(Path(reports).glob("*rescore*.json")):
        if not token(path.name):
            continue
        content, sha, _ = read_bytes(reports, path.name)
        report = json.loads(content)
        if report.get("report_type") != "d-rescore" or report.get("source_run") != run_id:
            continue
        scorer_metadata = report.get("scorer")
        scorer_metadata = scorer_metadata if isinstance(scorer_metadata, dict) else {}
        version = token(report.get("scorer_version") or scorer_metadata.get("version"))
        if not version:
            raise ValueError("rescore_missing_version")
        for trial in report.get("trials", []):
            trial_id = token(trial.get("trial_id"))
            if trial_id not in trial_ids:
                continue
            if trial.get("rescored") is None:
                continue
            score = trial["rescored"]
            values = score_values(score)
            if values["fully_correct"] is None and values["total"]:
                values["fully_correct"] = values["passed"] == values["total"]
            insert(
                connection,
                "scoring_revisions",
                {
                    "run_id": run_id,
                    "trial_id": trial_id,
                    "revision_id": sha,
                    "scorer_version": token(trial.get("rescored_scorer_version"), version),
                    "report_path": path.name,
                    "report_sha256": sha,
                    "generated_at": report.get("generated_at_utc")
                    if schema.TIMESTAMP.fullmatch(str(report.get("generated_at_utc")))
                    else None,
                    "status": token(score.get("status")),
                    "dimensions_json": encoded(score.get("dimensions")),
                    "claim_audit_json": encoded(score.get("claim_audit")),
                    "primary_error_json": encoded(
                        error((trial.get("rescored_error_summary") or {}).get("primary_error"))
                    ),
                    **values,
                    "answer_sha256": digest(trial.get("answer_sha256")),
                    "answer_matches_original": boolean(trial.get("answer_matches_original_record")),
                },
            )
            revision_version = token(trial.get("rescored_scorer_version"), version)
            score_checks(connection, run_id, trial_id, score, sha)
            score_dimensions(connection, run_id, trial_id, score, revision_version, sha)


def _canonical_task_sets():
    """Return task rosters from the checked-in benchmark manifests only."""
    sets = {}
    for relative in ("hard/manifest.json", "knowledge_pilot/manifest.json"):
        path = ROOT / relative
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tasks = value.get("tasks")
        ids = (
            {token(item.get("id")) for item in tasks if isinstance(item, dict)}
            if isinstance(tasks, list)
            else set()
        )
        ids.discard(None)
        if ids:
            benchmark = token(value.get("benchmark"))
            label = "hard-v1" if relative.startswith("hard/") else "knowledge-tool-value-v1"
            sets[label] = (ids, benchmark)
    if len(sets) == 2:
        sets["combined"] = (
            set().union(*(value[0] for value in sets.values())),
            "combined-registered-benchmark-suites",
        )
    return sets


def _safe_digest_map(value):
    if not isinstance(value, dict):
        return None
    result = {}
    for key, raw in value.items():
        task = token(key)
        if not task or not isinstance(raw, dict):
            continue
        spec_hash = digest(raw.get("spec"))
        inputs = raw.get("inputs")
        input_hashes = (
            {name: value for name, item in inputs.items() if (value := digest(item))}
            if isinstance(inputs, dict)
            else {}
        )
        if spec_hash is None and not input_hashes:
            continue
        result[task] = hashlib.sha256(
            encoded({"spec": spec_hash, "inputs": input_hashes}).encode()
        ).hexdigest()
    return result or None


def _safe_b1_metadata(manifest):
    """Keep only bounded B1 identifiers and digests; never store supplied prompt text."""
    if manifest.get("experiment_id") != "b1-discovery":
        return None
    tasks = {"D03", "D01", "C01"}

    def digest_map(value):
        if not isinstance(value, dict):
            return None
        safe = {key: digest(raw) for key, raw in value.items() if key in tasks}
        return safe if safe and all(safe.values()) else None

    raw_scorers = manifest.get("task_scorers")
    scorers = (
        {
            key: value
            for key, value in raw_scorers.items()
            if key in tasks and isinstance(value, str) and value in {"legacy", "knowledge-pilot-v2"}
        }
        if isinstance(raw_scorers, dict)
        else None
    )
    raw_discovery = manifest.get("mcp_discovery")
    conditions = raw_discovery.get("conditions") if isinstance(raw_discovery, dict) else None
    discovery = {}
    if isinstance(conditions, dict):
        for condition in ("control", "treatment"):
            entry = conditions.get(condition)
            if not isinstance(entry, dict):
                continue
            clean = {"server_description_sha256": digest(entry.get("server_description_sha256"))}
            for field in (
                "advertised_interface_sha256_by_task",
                "advertised_toolset_sha256_by_task",
                "tool_schemas_sha256_by_task",
                "individual_tool_descriptions_sha256_by_task",
            ):
                clean[field] = digest_map(entry.get(field))
            if all(clean.values()):
                discovery[condition] = clean
    return {
        "condition_order_design": "balanced_pairs_v1"
        if manifest.get("condition_order_design") == "balanced_pairs_v1"
        else None,
        "conditions": ["control", "treatment"]
        if manifest.get("conditions") == ["control", "treatment"]
        else None,
        "task_scorers": scorers,
        "scorer_sha256_by_task": digest_map(manifest.get("scorer_sha256_by_task")),
        "task_manifest_sha256": digest(manifest.get("task_manifest_sha256")),
        "prompt_sha256_by_task": digest_map(manifest.get("prompt_sha256_by_task")),
        "agent_instructions_sha256": digest(manifest.get("agent_instructions_sha256")),
        "mcp_discovery": {"conditions": discovery} if len(discovery) == 2 else None,
    }


def _b1_records_match_manifest(records, plan, manifest):
    """Verify task-scoped scorer, prompt, description and interface identities."""
    safe_metadata = _safe_b1_metadata(manifest) or {}
    discovery_metadata = safe_metadata.get("mcp_discovery")
    conditions = (
        discovery_metadata.get("conditions", {}) if isinstance(discovery_metadata, dict) else {}
    )
    scorer_map = safe_metadata.get("scorer_sha256_by_task")
    prompt_map = safe_metadata.get("prompt_sha256_by_task")
    task_scorers = safe_metadata.get("task_scorers")
    if not all(isinstance(value, dict) for value in (scorer_map, prompt_map, task_scorers)):
        return False
    for planned in plan:
        trial = records.get(planned["planned_trial_id"])
        if not isinstance(trial, dict):
            return False
        condition, task = planned["condition"], planned["task_id"]
        condition_metadata = conditions.get(condition)
        if not isinstance(condition_metadata, dict):
            return False
        expected = {
            "experiment_id": "b1-discovery",
            "experiment_version": manifest.get("experiment_version"),
            "condition": condition,
            "mcp_discovery_variant": condition,
            "scorer_identity": task_scorers.get(task),
            "scorer_sha256": scorer_map.get(task),
            "task_prompt_sha256": prompt_map.get(task),
            "task_manifest_sha256": safe_metadata.get("task_manifest_sha256"),
            "agent_instructions_sha256": safe_metadata.get("agent_instructions_sha256"),
            "mcp_server_description_sha256": condition_metadata.get("server_description_sha256"),
            "mcp_advertised_interface_sha256": condition_metadata[
                "advertised_interface_sha256_by_task"
            ].get(task),
            "mcp_advertised_toolset_sha256": condition_metadata[
                "advertised_toolset_sha256_by_task"
            ].get(task),
            "mcp_tool_schemas_sha256": condition_metadata["tool_schemas_sha256_by_task"].get(task),
            "mcp_individual_tool_descriptions_sha256": condition_metadata[
                "individual_tool_descriptions_sha256_by_task"
            ].get(task),
        }
        if any(value is None or trial.get(key) != value for key, value in expected.items()):
            return False
    return True


def _trial_plan(manifest):
    """Return only validated planned identities; unknown metadata stays unknown."""
    plan = manifest.get("trial_plan")
    tasks = tokens(manifest.get("tasks"))
    modes = tokens(manifest.get("modes"))
    repetitions = number(manifest.get("repetitions"), integer=True)
    if not isinstance(plan, list) or len(plan) > 10000:
        return [], "unknown"
    b1 = manifest.get("experiment_id") == "b1-discovery"
    rows, seen, orders = [], set(), set()
    valid = bool(tasks) and bool(modes) and repetitions is not None and repetitions > 0
    valid = valid and set(modes or []) <= MODES and len(modes or []) == len(set(modes or []))
    if b1:
        valid = valid and tasks == ["D03", "D01", "C01"]
        valid = valid and modes == ["with-mcp"] and repetitions == 2
        valid = valid and manifest.get("conditions") == ["control", "treatment"]
    for item in plan:
        if not isinstance(item, dict):
            valid = False
            continue
        trial_id = token(item.get("trial_id"))
        task = token(item.get("task"))
        mode = item.get("mode")
        repetition = number(item.get("repetition"), integer=True)
        condition = item.get("condition")
        execution_order = number(item.get("execution_order"), integer=True)
        if (
            not trial_id
            or not task
            or task not in (tasks or [])
            or mode not in MODES
            or mode not in (modes or [])
            or repetition is None
            or repetition < 1
            or repetition > (repetitions or 0)
            or trial_id in seen
            or (b1 and condition not in {"control", "treatment"})
            or (not b1 and condition is not None)
            or (b1 and (execution_order is None or execution_order < 1 or execution_order > 12))
            or (not b1 and execution_order is not None)
            or (b1 and execution_order in orders)
        ):
            valid = False
            continue
        seen.add(trial_id)
        if execution_order is not None:
            orders.add(execution_order)
        rows.append(
            {
                "planned_trial_id": trial_id,
                "task_id": task,
                "mode": mode,
                "repetition": repetition,
                "condition": condition,
                "execution_order": execution_order,
            }
        )
    if b1:
        expected = {
            (task, "with-mcp", repetition, condition)
            for task in (tasks or [])
            for repetition in range(1, (repetitions or 0) + 1)
            for condition in ("control", "treatment")
        }
        actual = {
            (row["task_id"], row["mode"], row["repetition"], row["condition"]) for row in rows
        }
        valid = valid and orders == set(range(1, 13))
        ordered = sorted(rows, key=lambda row: row["execution_order"])
        first_conditions = {}
        for row in ordered:
            first_conditions.setdefault((row["task_id"], row["repetition"]), row["condition"])
        valid = valid and Counter(first_conditions.values()) == Counter(
            {"control": 3, "treatment": 3}
        )
    else:
        expected = {
            (task, mode, repetition)
            for task in (tasks or [])
            for mode in (modes or [])
            for repetition in range(1, (repetitions or 0) + 1)
        }
        actual = {(row["task_id"], row["mode"], row["repetition"]) for row in rows}
    if not valid or actual != expected or len(rows) != len(expected):
        return rows, "invalid"
    return rows, "valid"


def _run_metadata(
    manifest,
    records,
    plan,
    plan_status,
    completion_state,
    trial_rows,
    v2_rows,
    v2_present,
    v2_complete,
    issues,
):
    task_ids = tokens(manifest.get("tasks"))
    modes = tokens(manifest.get("modes"))
    suites = sorted({value for record in records.values() if (value := token(record.get("suite")))})
    suite_label = " + ".join(suites) if suites else None
    suites_catalog = _canonical_task_sets()
    task_set = set(task_ids or [])
    benchmark_suite = token(manifest.get("benchmark_suite") or manifest.get("benchmark"))
    suite_source = "manifest" if benchmark_suite else None
    if not benchmark_suite:
        for label, (ids, benchmark) in suites_catalog.items():
            if task_set and task_set == ids:
                benchmark_suite = benchmark
                suite_label = label
                suite_source = "registered_task_roster"
                break
        if not benchmark_suite and suites:
            benchmark_suite = suite_label
            suite_source = "trial_records"
    scorer_versions = manifest.get("scorer_versions")
    scorer_versions = (
        {
            key: value
            for key, raw in scorer_versions.items()
            if token(key)
            and isinstance(raw, str)
            and not SECRET_VALUE(raw)
            and len(raw) <= 160
            and (token(raw) or digest(raw))
        }
        if isinstance(scorer_versions, dict)
        else None
    )
    prompt_versions = manifest.get("prompt_versions")
    prompt_versions = (
        {
            key: value
            for key, raw in prompt_versions.items()
            if token(key)
            and isinstance(raw, str)
            and not SECRET_VALUE(raw)
            and len(raw) <= 160
            and (token(raw) or digest(raw))
        }
        if isinstance(prompt_versions, dict)
        else None
    )
    task_hashes = _safe_digest_map(manifest.get("task_inputs_sha256"))
    environment = manifest.get("environment")
    environment = environment if isinstance(environment, dict) else {}
    env_projection = {
        "r_version": token(environment.get("r_version")),
        "renv_lock_sha256": digest(environment.get("renv_lock_sha256")),
        "task_package_pins": package_pins(environment.get("task_package_pins", {})),
    }
    env_projection = {key: value for key, value in env_projection.items() if value is not None}
    observed_v2_schemas = {row["schema_version"] for _, row in v2_rows}
    v2_schema = (
        next(iter(observed_v2_schemas))
        if len(observed_v2_schemas) == 1
        else "mixed"
        if observed_v2_schemas
        else None
    )
    if not v2_schema:
        declared = (manifest.get("scorer_versions") or {}).get("mcp_observation_schema_version")
        if declared in projection_v2.SUPPORTED_SCHEMA_VERSIONS:
            v2_schema = declared
    instructions = token(manifest.get("instructions"))
    planned_ids = {row["planned_trial_id"] for row in plan}
    actual_by_id = {row["trial_id"]: row for row in trial_rows}
    results_complete = bool(plan) and planned_ids == set(actual_by_id)
    if results_complete:
        plan_by_id = {row["planned_trial_id"]: row for row in plan}
        results_complete = all(
            row["finalized"]
            and row["passed"] is not None
            and row["total"] is not None
            and row["passed"] <= row["total"]
            and row["status"] in {"scored", "completed"}
            and row["interrupted"] is not True
            and row["task_id"] == plan_by_id[row["trial_id"]]["task_id"]
            and row["mode"] == plan_by_id[row["trial_id"]]["mode"]
            and row["repetition"] == plan_by_id[row["trial_id"]]["repetition"]
            and row.get("condition") == plan_by_id[row["trial_id"]].get("condition")
            and row.get("execution_order") == plan_by_id[row["trial_id"]].get("execution_order")
            for row in actual_by_id.values()
        )
    pairing_compatible = results_complete
    if pairing_compatible and manifest.get("experiment_id") == "b1-discovery":
        safe_metadata = _safe_b1_metadata(manifest) or {}
        pairing_compatible = safe_metadata.get(
            "condition_order_design"
        ) == "balanced_pairs_v1" and _b1_records_match_manifest(records, plan, manifest)
    if pairing_compatible:
        b1 = manifest.get("experiment_id") == "b1-discovery"
        if b1:
            safe_metadata = _safe_b1_metadata(manifest) or {}
            discovery_metadata = safe_metadata.get("mcp_discovery")
            discovery = (
                discovery_metadata.get("conditions", {})
                if isinstance(discovery_metadata, dict)
                else {}
            )
            control = discovery.get("control", {})
            treatment = discovery.get("treatment", {})
            interface_fields = (
                "advertised_interface_sha256_by_task",
                "advertised_toolset_sha256_by_task",
                "tool_schemas_sha256_by_task",
                "individual_tool_descriptions_sha256_by_task",
            )
            pairing_compatible = bool(
                control
                and treatment
                and control.get("server_description_sha256")
                != treatment.get("server_description_sha256")
                and all(control.get(field) == treatment.get(field) for field in interface_fields)
            )
        rows_by_slot = {
            (
                row["task_id"],
                row["repetition"],
                row["condition"] if b1 else row["mode"],
            ): row
            for row in actual_by_id.values()
        }
        for task in task_set if pairing_compatible else ():
            for repetition in range(
                1, (number(manifest.get("repetitions"), integer=True) or 0) + 1
            ):
                a = rows_by_slot.get((task, repetition, "control" if b1 else "without-mcp"))
                b = rows_by_slot.get((task, repetition, "treatment" if b1 else "with-mcp"))
                if (
                    a is None
                    or b is None
                    or not a["scorer_version"]
                    or a["scorer_version"] != b["scorer_version"]
                    or a["total"] != b["total"]
                    or a["model"] != b["model"]
                    or a["effort"] != b["effort"]
                    or a["configuration"] != b["configuration"]
                    or a["instructions"] != b["instructions"]
                    or a["instructions"] != instructions
                ):
                    pairing_compatible = False
                    break
            if not pairing_compatible:
                break
    created = manifest.get("created_at_utc")
    if not isinstance(created, str) or not schema.TIMESTAMP.fullmatch(created):
        created = None
    if (
        "selftest" in str(manifest.get("purpose", "")).casefold()
        or "selftest" in str(manifest.get("run_id", "")).casefold()
    ):
        full_status, reason = "diagnostic", "scorer_selftest"
    elif instructions is not None and instructions != "standard":
        full_status, reason = "diagnostic", "nonstandard_instructions"
    elif plan_status != "valid":
        full_status, reason = "unknown", "trial_plan_" + plan_status
    elif issues:
        full_status, reason = "partial", "import_issues"
    elif created is None:
        full_status, reason = "unknown", "run_timestamp_unavailable"
    elif completion_state != "completed" or not results_complete:
        full_status, reason = "partial", "results_or_run_incomplete"
    elif not pairing_compatible:
        full_status, reason = "partial", "pair_or_scorer_incompatible"
    else:
        recognized = any(task_set == ids for ids, _ in suites_catalog.values())
        both_conditions = set(modes or []) == MODES and len(modes or []) == 2
        b1_scope = (
            manifest.get("experiment_id") == "b1-discovery"
            and task_ids == ["D03", "D01", "C01"]
            and set(manifest.get("conditions") or []) == {"control", "treatment"}
            and len(plan) == 12
        )
        if (recognized and both_conditions or b1_scope) and instructions == "standard":
            full_status, reason = "full_comparable", "plan_matches_registered_scope"
        else:
            full_status, reason = "partial", "plan_scope_not_full"
    return {
        "created_at_utc": created,
        "benchmark_suite": benchmark_suite,
        "suite_source": suite_source,
        "suite_label": suite_label,
        "tasks_json": encoded(sorted(task_set)) if task_ids is not None else None,
        "conditions_json": encoded(
            sorted(set(manifest.get("conditions") or []))
            if manifest.get("experiment_id") == "b1-discovery"
            else sorted(set(modes or []))
        )
        if modes is not None
        else None,
        "repetitions": number(manifest.get("repetitions"), integer=True),
        "trial_plan_count": len(plan) if plan_status != "unknown" else None,
        "scorer_versions_json": encoded(scorer_versions),
        "prompt_versions_json": encoded(prompt_versions),
        "task_input_hashes_json": encoded(task_hashes),
        "environment_json": encoded(env_projection or None),
        "timeout_seconds": number(manifest.get("timeout_seconds")),
        "trial_plan_status": plan_status,
        "full_status": full_status,
        "full_status_reason": reason,
        "v2_observation_schema": v2_schema,
        "v2_observation_status": "missing"
        if not v2_present
        else "complete"
        if v2_complete
        else "incomplete",
        "experiment_id": token(manifest.get("experiment_id")),
        "experiment_version": token(manifest.get("experiment_version")),
        "experiment_metadata_json": encoded(_safe_b1_metadata(manifest)),
    }


def import_run(connection, results_root, run_id, *, reports=DEFAULT_REPORTS):
    if not token(run_id):
        raise ValueError("invalid_run_id")
    snapshot = Snapshot(results_root)
    opportunity_manifest, opportunity_sha256 = opportunities.load_opportunity_manifest()
    manifest = snapshot.json(f"{run_id}/experiment.json", {})
    if manifest and (manifest.get("schema_version") != 1 or manifest.get("run_id") != run_id):
        raise ValueError("unsupported_manifest_schema_or_identity")
    if manifest.get("telemetry_schema_version") not in (None, "1.0", "1.1", "1.2"):
        raise ValueError("unsupported_telemetry_schema")
    records = read_records(snapshot, run_id)
    events, jsonl_present, jsonl_complete = read_events(snapshot, run_id)
    v2_rows, v2_present, v2_complete = read_v2_observations(snapshot, run_id)
    plan, plan_status = _trial_plan(manifest)
    plan_by_id = {item["planned_trial_id"]: item for item in plan}
    for _, event in events:
        if event["event_type"] == "benchmark.trial.started" and event["trial_id"] not in records:
            planned = plan_by_id.get(event["trial_id"], {})
            records[event["trial_id"]] = {
                "run_id": run_id,
                "trial_id": event["trial_id"],
                "task": event["task"],
                "mode": event["mode"],
                "repetition": event.get("repetition"),
                "condition": planned.get("condition"),
                "execution_order": planned.get("execution_order"),
                "experiment_id": manifest.get("experiment_id"),
                "status": "in_progress",
            }
    configuration = token(manifest.get("configuration_id"))
    configuration_source = "experiment_manifest" if configuration else None
    declared_configurations = {
        token(record.get("configuration_id")) for record in records.values()
    } - {None}
    b1 = manifest.get("experiment_id") == "b1-discovery"
    if configuration and declared_configurations - {configuration} and not b1:
        raise ValueError("conflicting_trial_configurations")
    if not configuration and not b1:
        configurations = {token(record.get("configuration_id")) for record in records.values()} - {
            None
        }
        if len(configurations) > 1:
            raise ValueError("conflicting_trial_configurations")
        configuration = next(iter(configurations), None)
        configuration_source = "trial_record" if configuration else None
    if not configuration:
        configuration = historical_configuration(run_id)
        configuration_source = "explicit_historical_registry" if configuration else "unrecorded"
    first = next(iter(records.values()), {})
    mcp = manifest.get("mcp_server") or {}
    repo = manifest.get("repository") or {}
    expected = number(manifest.get("trial_count"), integer=True)
    if expected is None and manifest.get("experiment_id") == "b1-discovery":
        expected = len(plan) if plan_status == "valid" else None
    if expected is None and all(key in manifest for key in ("tasks", "modes", "repetitions")):
        expected = len(manifest["tasks"]) * len(set(manifest["modes"])) * manifest["repetitions"]
    run = {
        "run_id": run_id,
        "relative_path": run_id,
        "import_state": "incomplete",
        "completion_state": "incomplete",
        "configuration": configuration,
        "configuration_source": configuration_source,
        "model": token(manifest.get("model"), token(first.get("model"))),
        "effort": token(manifest.get("effort"), token(first.get("effort"))),
        "instructions": token(manifest.get("instructions"), token(first.get("instructions"))),
        "revision": digest(repo.get("revision")),
        "dirty": boolean(repo.get("dirty")),
        "dirty_fingerprint": digest(repo.get("working_tree_sha256")),
        "source_sha256": digest(mcp.get("source_sha256")),
        "images_json": encoded(
            {
                key: digest(value)
                for key, value in (manifest.get("images") or first.get("images") or {}).items()
                if key in {"executor", "scorer", "mcp"}
            }
        ),
        "package_pins_json": encoded(
            package_pins((manifest.get("environment") or {}).get("task_package_pins", {}))
        ),
        "registered_tools_json": encoded(tokens(mcp.get("registered_tools"))),
        "allowed_tools_json": encoded(tokens(mcp.get("allowed_tools"))),
        "toolset": token(mcp.get("toolset"))
        or next(
            (token(r.get("mcp_toolset")) for r in records.values() if token(r.get("mcp_toolset"))),
            None,
        ),
        "telemetry_schema": (
            next(
                (
                    version
                    for version in ("1.2", "1.1", "1.0")
                    if any(event.get("schema_version") == version for _, event in events)
                ),
                "1.0",
            )
            if jsonl_present
            else None
        ),
        "manifest_schema": manifest.get("schema_version"),
        "expected_trials": expected,
        "observed_trials": len(records),
        "jsonl_present": jsonl_present,
        "jsonl_complete": jsonl_complete if jsonl_present else None,
        "imported_at": datetime.now(UTC).replace(tzinfo=None),
    }
    csv_calls = {}
    if confined(snapshot.root, f"{run_id}/mcp_calls.csv").is_file():
        for call in csv_records(snapshot, f"{run_id}/mcp_calls.csv"):
            csv_calls.setdefault(call.get("trial_id"), []).append(call)
    csv_metrics = {}
    if confined(snapshot.root, f"{run_id}/mcp_metrics.csv").is_file():
        for metric in csv_records(snapshot, f"{run_id}/mcp_metrics.csv"):
            if metric.get("tool") == "*":
                csv_metrics[metric.get("trial_id")] = metric
    connection.execute("BEGIN TRANSACTION")
    try:
        for table in TABLES:
            connection.execute(f"DELETE FROM {table} WHERE run_id = ?", [run_id])
        rows = [
            import_trial(
                connection,
                snapshot,
                run,
                trial_id,
                record,
                events,
                csv_calls.get(trial_id, []),
                csv_metrics.get(trial_id),
                manifest.get("scorer_versions"),
                manifest.get("task_scorers"),
            )
            for trial_id, record in records.items()
        ]
        for observation_id, observation in v2_rows:
            insert(
                connection,
                "mcp_observations_v2",
                {
                    "run_id": run_id,
                    "observation_id": observation_id,
                    "source": observation["source"],
                    "client_call_number": observation["client_call_number"],
                    "client_item_id": observation["client_item_id"],
                    "server_call_number": observation["server_call_number"],
                    "tool_name": observation["tool"],
                    "correlation_quality": observation["correlation_quality"],
                    "request_projection_json": encoded(observation["request_projection"]),
                    "response_projection_json": encoded(observation["response_projection"]),
                    "duration_ms": number(observation["duration_ms"]),
                },
            )
        task_hashes = _safe_digest_map(manifest.get("task_inputs_sha256")) or {}
        for planned in plan:
            insert(
                connection,
                "trial_plan",
                {
                    "run_id": run_id,
                    **planned,
                    "task_input_sha256": task_hashes.get(planned["task_id"]),
                },
            )
        for event_id, event in events:
            if event.get("trial_id") and event["trial_id"] not in records:
                snapshot.issues["event_without_trial"] += 1
                continue
            import_event(connection, run_id, event_id, event)
            import_agent_telemetry(connection, run_id, event_id, event)
        import_trace_evidence(
            connection,
            run_id,
            records,
            events,
            jsonl_present=jsonl_present,
            jsonl_complete=jsonl_complete,
            opportunity_manifest=opportunity_manifest,
            opportunity_sha256=opportunity_sha256,
        )
        import_revisions(connection, run_id, records, reports)
        finalized = bool(rows) and all(
            row["finalized"] and row["interrupted"] is not True for row in rows
        )
        ends = [event for _, event in events if event["event_type"] == "benchmark.run.completed"]
        started = [event for _, event in events if event["event_type"] == "benchmark.run.started"]
        if expected is None and started:
            run["expected_trials"] = expected = started[-1]["trial_count"]
        if jsonl_present:
            if (
                jsonl_complete
                and ends
                and ends[-1].get("status") in {"completed", "completed_with_errors"}
                and finalized
                and expected == len(rows)
            ):
                run["completion_state"] = "completed"
        elif finalized:
            run["completion_state"] = (
                "legacy_finalized_scope_unknown"
                if expected is None
                else "completed"
                if expected == len(rows)
                else "incomplete"
            )
        metadata = _run_metadata(
            manifest,
            records,
            plan,
            plan_status,
            run["completion_state"],
            rows,
            v2_rows,
            v2_present,
            v2_complete,
            snapshot.issues,
        )
        run["import_state"] = (
            "incomplete"
            if snapshot.issues or run["completion_state"] == "incomplete"
            else "imported"
        )
        run["source_fingerprint"] = hashlib.sha256(
            encoded({key: value[0] for key, value in snapshot.files.items()}).encode()
        ).hexdigest()
        snapshot.stable()
        insert(connection, "runs", run)
        insert(connection, "run_metadata", {"run_id": run_id, **metadata})
        for relative, (sha, stamp) in snapshot.files.items():
            insert(
                connection,
                "source_files",
                dict(run_id=run_id, relative_path=relative, sha256=sha, bytes=stamp[0]),
            )
        for code, count in snapshot.issues.items():
            insert(
                connection, "import_issues", dict(run_id=run_id, issue_code=code, occurrences=count)
            )
        connection.execute("COMMIT")
        return {
            "run_id": run_id,
            "trials": len(rows),
            "state": run["completion_state"],
            "issues": dict(snapshot.issues),
        }
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def discover_runs(root):
    found = []
    for path in sorted(Path(root).iterdir()):
        if not path.is_dir() or path.is_symlink() or not token(path.name):
            continue
        markers = ("results.json", "results.csv", "experiment.json", "telemetry.jsonl")
        if any((path / name).is_file() for name in markers):
            found.append(path.name)
            continue
        if any(
            (child / "result.json").is_file()
            for child in path.iterdir()
            if child.is_dir() and not child.is_symlink() and token(child.name)
        ):
            found.append(path.name)
    return found


def import_directory(
    database=DEFAULT_DATABASE,
    results_root=DEFAULT_RESULTS,
    *,
    runs=None,
    reports=DEFAULT_REPORTS,
    rebuild=False,
):
    root = Path(results_root).resolve()
    database = Path(database).resolve()
    if database.is_relative_to(root):
        raise ValueError("analytics_database_must_be_outside_source_results")
    summaries = []
    with connect(database) as connection:
        if rebuild:
            connection.execute("BEGIN TRANSACTION")
            for table in TABLES:
                connection.execute(f"DELETE FROM {table}")
            connection.execute("COMMIT")
        selected = runs or discover_runs(root)
        for run_id in selected:
            if not token(run_id):
                summaries.append(
                    {
                        "run_id": "invalid",
                        "state": "snapshot_rejected",
                        "reason_code": "invalid_run_id",
                    }
                )
                continue
            try:
                summaries.append(import_run(connection, root, run_id, reports=reports))
            except (ValueError, OSError, TypeError, KeyError, AttributeError, duckdb.Error) as exc:
                # Never echo raw JSON, API messages or exception text.
                reason = (
                    str(exc)
                    if isinstance(exc, ValueError) and token(str(exc))
                    else "source_io_error"
                    if isinstance(exc, OSError)
                    else "invalid_snapshot"
                )
                connection.execute(
                    "UPDATE runs SET import_state='snapshot_rejected', "
                    "completion_state='unknown' WHERE run_id=?",
                    [run_id],
                )
                connection.execute(
                    "DELETE FROM import_issues WHERE run_id=? AND issue_code='snapshot_rejected'",
                    [run_id],
                )
                insert(
                    connection,
                    "import_issues",
                    dict(run_id=run_id, issue_code="snapshot_rejected", occurrences=1),
                )
                summaries.append(
                    {
                        "run_id": token(run_id, "invalid"),
                        "state": "snapshot_rejected",
                        "reason_code": reason,
                    }
                )
    return summaries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--runs", nargs="+")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild derived tables only; source files are read-only",
    )
    args = parser.parse_args(argv)
    try:
        summaries = import_directory(
            args.database, args.results, reports=args.reports, runs=args.runs, rebuild=args.rebuild
        )
    except (ValueError, OSError, duckdb.Error) as exc:
        code = (
            str(exc)
            if isinstance(exc, ValueError) and token(str(exc))
            else "database_or_source_unavailable"
        )
        print(json.dumps({"state": "import_failed", "reason_code": code}))
        return 1
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return int(any(item["state"] == "snapshot_rejected" for item in summaries))


if __name__ == "__main__":
    raise SystemExit(main())
