"""Offline analytics checks, including the three immutable historical result sets."""

import csv
import hashlib
import json
import socket

import pytest

duckdb = pytest.importorskip("duckdb")
pd = pytest.importorskip("pandas")

from benchmarks.codex_r.analytics import (  # noqa: E402
    DEFAULT_REPORTS,
    DEFAULT_RESULTS,
    ROOT,
    queries,  # noqa: E402
)
from benchmarks.codex_r.analytics.import_results import (  # noqa: E402
    TABLES,
    _canonical_task_sets,
    _trial_plan,
    connect,
    import_directory,
    import_run,
    import_trace_evidence,
    insert,
)
from benchmarks.codex_r.telemetry import opportunities as opportunity_telemetry  # noqa: E402
from benchmarks.codex_r.telemetry import projection as projection_v2  # noqa: E402
from benchmarks.codex_r.telemetry import recorder as telemetry_recorder  # noqa: E402
from benchmarks.codex_r.telemetry import schema as telemetry_schema  # noqa: E402

HISTORICAL = (
    "20261025T083653Z-ca1d5503",
    "20261025T100159Z-a939d94f",
    "20261025T100740Z-9746f577",
)
STAMP = "2026-10-25T10:10:17.929Z"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect

    def blocked(sock, address):
        # Windows asyncio.socketpair uses a loopback connection internally.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1", "localhost"}:
            return original(sock, address)
        if sock.family == getattr(socket, "AF_UNIX", None):
            return original(sock, address)
        raise AssertionError("Analytics must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def historical():
    if any(not (DEFAULT_RESULTS / run_id).is_dir() for run_id in HISTORICAL):
        pytest.skip("optional historical result directories are not available")
    with connect(":memory:") as connection:
        for run_id in HISTORICAL:
            import_run(connection, DEFAULT_RESULTS, run_id)
        yield connection


def make_run(tmp_path, *, run_id="local-run", calls=1):
    root = tmp_path / "results"
    run = root / run_id
    run.mkdir(parents=True)
    record = {
        "run_id": run_id,
        "trial_id": "D01-B-1",
        "task": "D01",
        "mode": "with-mcp",
        "repetition": 1,
        "model": "gpt-6-luna",
        "effort": "medium",
        "status": "scored",
        "completed_at": STAMP,
        "cleanup_completed": True,
        "score": {
            "passed": 3,
            "total": 4,
            "fully_correct": False,
            "failed_checks": ["docs"],
            "details": ["shape: pass", "docs: fail"],
        },
        "mcp_usage": {"calls": calls, "tool_search_calls": 0},
    }
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "tasks": ["D01"],
        "modes": ["with-mcp"],
        "repetitions": 1,
        "configuration_id": "local-test",
    }
    (run / "experiment.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "results.json").write_text(json.dumps([record]), encoding="utf-8")
    return root, run, record


def make_full_baseline(tmp_path, run_id, *, created_at="2026-10-25T14:00:28Z", calls=True):
    """Synthetic test-only full scope with the preserved baseline score/call totals."""
    root = tmp_path / "results"
    run = root / run_id
    run.mkdir(parents=True)
    task_ids = sorted(_canonical_task_sets()["combined"][0])
    manifests = [
        json.loads((ROOT / relative).read_text(encoding="utf-8"))
        for relative in ("hard/manifest.json", "knowledge_pilot/manifest.json")
    ]
    totals = {item["id"]: item["checks"] for manifest in manifests for item in manifest["tasks"]}
    scores = {
        "B01": (5, 5),
        "B02": (5, 5),
        "B03": (5, 5),
        "C01": (5, 5),
        "C02": (5, 5),
        "C03": (5, 5),
        "C04": (9, 9),
        "C05": (7, 7),
        "D01": (1, 4),
        "D02": (1, 4),
        "D03": (2, 4),
        "E01": (0, 6),
        "E02": (5, 5),
        "E03": (4, 4),
        "E04": (0, 5),
        "E05": (1, 5),
        "H01": (18, 18),
        "H04": (17, 17),
        "H10": (18, 18),
    }
    assert set(task_ids) == set(totals) == set(scores)
    scorer_versions = {
        "codex_r": "codex-r-pilot-v1",
        "hard": "r-knowledge-mcp-hard-v1",
        "knowledge_pilot": "r-knowledge-tool-value-v1",
        "d_recommendation": "d-recommendation-2",
        "e_compatibility": "e-compatibility-1",
    }
    plan, records = [], []
    for task in task_ids:
        block = task[0]
        suite = "hard-v1" if block == "H" else "knowledge-tool-value-v1"
        for mode, letter in (("without-mcp", "A"), ("with-mcp", "B")):
            trial_id = f"{task}-{letter}-1"
            plan.append({"trial_id": trial_id, "task": task, "mode": mode, "repetition": 1})
            passed = scores[task][0]
            if mode == "with-mcp":
                passed += {"D01": 3, "E04": 1, "H10": -1}.get(task, 0)
            total = totals[task]
            failed = [f"check-{i}" for i in range(passed, total)]
            call_rows = []
            tool_counts = {}
            if calls and mode == "with-mcp" and task in {"D01", "D02"}:
                distribution = (
                    ["get_function_docs"] * 40 + ["get_package"] * 4 + ["search_packages"]
                    if task == "D01"
                    else ["get_function_docs"] * 9 + ["get_package"] * 3
                )
                for index, tool in enumerate(distribution, 1):
                    is_doc = tool == "get_function_docs"
                    error_call = is_doc and (index <= 25 if task == "D01" else index == 1)
                    repeated = task == "D01" and is_doc and 1 <= index <= 4
                    fingerprint = "a" * 12 if repeated else f"{index:012x}"
                    call_rows.append(
                        {
                            "call_number": index,
                            "tool_name": tool,
                            "status": "error" if error_call else "ok",
                            "is_error": error_call,
                            "error_code": "docs_not_found" if error_call else None,
                            "argument_fingerprint": fingerprint,
                            "repeat_kind": "first"
                            if repeated and index == 1
                            else "identical"
                            if repeated
                            else "first",
                            "repeat_count": 1 if repeated and index > 1 else 0,
                            "request_bytes": 100,
                            "response_bytes": 500,
                            "duration_ms": 1.5,
                        }
                    )
                    tool_counts[tool] = tool_counts.get(tool, 0) + 1
            calls_count = len(call_rows)
            details = [f"check-{i}: pass" for i in range(passed)] + [
                f"check-{i}: fail" for i in range(passed, total)
            ]
            records.append(
                {
                    "run_id": run_id,
                    "trial_id": trial_id,
                    "task": task,
                    "suite": suite,
                    "mode": mode,
                    "repetition": 1,
                    "model": "gpt-6-luna",
                    "effort": "medium",
                    "instructions": "standard",
                    "status": "scored",
                    "started_at": STAMP,
                    "completed_at": STAMP,
                    "score": {
                        "passed": passed,
                        "total": total,
                        "fully_correct": passed == total,
                        "failed_checks": failed,
                        "details": details,
                    },
                    "mcp_usage": {
                        "calls": calls_count,
                        "tool_names": sorted(tool_counts),
                        "calls_by_tool": tool_counts,
                        "tool_search_calls": 0,
                    },
                    "mcp_telemetry": {"calls": call_rows} if call_rows else None,
                    "mcp_server_audit": {"list_tools_requests": 1 if mode == "with-mcp" else 0},
                }
            )
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at_utc": created_at,
        "configuration_id": "same-config",
        "model": "gpt-6-luna",
        "effort": "medium",
        "instructions": "standard",
        "tasks": task_ids,
        "modes": ["without-mcp", "with-mcp"],
        "repetitions": 1,
        "trial_count": len(plan),
        "trial_plan": plan,
        "scorer_versions": scorer_versions,
    }
    (run / "experiment.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "results.json").write_text(json.dumps(records), encoding="utf-8")
    return root, run, manifest, records


def event(run_id, kind, **fields):
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "event_type": kind,
        "timestamp_utc": STAMP,
        "monotonic_offset_ms": 0.0,
        "source": "runner",
        **fields,
    }


def test_historical_old_d01_new_d01_d02_and_missing_jsonl(historical):
    rows = historical.execute(
        "SELECT run_id, completion_state, jsonl_present FROM runs ORDER BY run_id"
    ).fetchall()
    assert rows == [
        (HISTORICAL[0], "legacy_finalized_scope_unknown", False),
        (HISTORICAL[1], "completed", True),
        (HISTORICAL[2], "completed", True),
    ]
    assert historical.execute(
        "SELECT task_id,count(*) FROM trials GROUP BY task_id ORDER BY task_id"
    ).fetchall() == [("D01", 4), ("D02", 2)]
    counts = historical.execute(
        "SELECT run_id,count(*),sum(is_error::INT) FROM mcp_calls "
        "WHERE counted GROUP BY run_id ORDER BY run_id"
    ).fetchall()
    assert counts == [(HISTORICAL[0], 55, 41), (HISTORICAL[2], 23, 9)]


def test_idempotence_and_sources_unchanged(historical):
    sources = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for run_id in HISTORICAL
        for path in (DEFAULT_RESULTS / run_id).rglob("*")
        if path.is_file()
    }
    counts = {
        table: historical.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES
    }
    for run_id in HISTORICAL:
        import_run(historical, DEFAULT_RESULTS, run_id)
    assert counts == {
        table: historical.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES
    }
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == sha for path, sha in sources.items()
    )


def test_unknown_usage_cost_and_legacy_partial_remain_null(historical):
    assert historical.execute(
        "SELECT count(api_total_tokens),count(cost_amount) FROM trials"
    ).fetchone() == (0, 0)
    assert historical.execute(
        "SELECT count(partial),count(useful_bytes),count(cache_hits) FROM mcp_calls "
        "WHERE observation_source='legacy_logs'"
    ).fetchone() == (0, 0, 0)
    assert queries.overview(historical).observed_total_tokens.isna().all()


def test_revisions_do_not_replace_original_scores(historical):
    revision = historical.execute("SELECT DISTINCT revision_id FROM scoring_revisions").fetchone()[
        0
    ]
    original = queries.trials_frame(historical)
    rescored = queries.trials_frame(historical, scoring_id=revision)
    assert len(original) == 6 and len(rescored) == 2
    assert original.query("run_id == @HISTORICAL[0] and mode == 'with-mcp'").passed.iloc[0] == 3
    assert rescored.query("mode == 'with-mcp'").passed.iloc[0] == 4
    assert set(rescored.scorer_key) == {"d-recommendation-2"}
    assert historical.execute(
        "SELECT passed FROM score_checks WHERE scoring_id=? AND trial_id='D01-B-1' "
        "AND check_name='official_source_and_docs'",
        [revision],
    ).fetchone() == (True,)


def test_v21_rescore_import_retains_original_status_errors_and_claim_audit(tmp_path):
    run_id = "v21-rescore-test"
    root, run, record = make_run(tmp_path, run_id=run_id)
    record["error_summary"] = {
        "primary_error": {
            "origin": "mcp_server",
            "category": "upstream",
            "reason_code": "MCP_PROVIDER_ERROR",
            "source_code": "source_unavailable",
            "severity": "recoverable",
        }
    }
    record["score"]["dimensions"] = {
        "unsupported_claims": {
            "status": "pass",
            "passed": 1,
            "total": 1,
            "checks": {"all_asserted_claims_supported": "pass"},
        }
    }
    (run / "results.json").write_text(json.dumps([record]), encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    report = {
        "report_type": "d-rescore",
        "source_run": run_id,
        "generated_at_utc": "2026-10-26T12:00:00Z",
        "scorer": {"version": "knowledge-pilot-v2.1"},
        "trials": [
            {
                "trial_id": "D01-B-1",
                "rescored_scorer_version": "knowledge-pilot-v2.1",
                "answer_sha256": "a" * 64,
                "answer_matches_original_record": True,
                "rescored": {
                    "status": "unsupported_for_automatic_scoring",
                    "reason": "unsupported_claims_unknown",
                    "scorer_version": "knowledge-pilot-v2.1",
                    "passed": None,
                    "total": None,
                    "fully_correct": None,
                    "dimensions": {
                        "unsupported_claims": {
                            "status": "unknown",
                            "passed": None,
                            "total": None,
                            "checks": {"all_asserted_claims_supported": "unknown"},
                        }
                    },
                    "claim_audit": {
                        "status": "unknown",
                        "supported": ["caveats:some_apis_experimental"],
                        "unknown": ["features:keyboard_single_multi_select"],
                        "contradicted": [],
                        "required_missing": [],
                    },
                },
                "rescored_error_summary": {
                    "primary_error": {
                        "origin": "scorer",
                        "category": "evidence_insufficiency",
                        "reason_code": "SCORER_UNSUPPORTED_CLAIMS",
                        "source_code": "unsupported_claims_unknown",
                        "severity": "recoverable",
                    }
                },
            }
        ],
    }
    (reports / "b1_scorer_v21_rescore_test.json").write_text(json.dumps(report), encoding="utf-8")
    with connect(":memory:") as connection:
        import_run(connection, root, run_id, reports=reports)
        revision = connection.execute(
            "SELECT revision_id FROM scoring_revisions WHERE run_id=?", [run_id]
        ).fetchone()[0]
        revised = queries.trials_frame(connection, scoring_id=revision)
        assert revised.iloc[0].revision_status == "unsupported_for_automatic_scoring"
        assert revised.iloc[0].original_status == "scored"
        assert pd.isna(revised.iloc[0].fully_correct)
        assert json.loads(revised.iloc[0].claim_audit_json)["unknown"] == [
            "features:keyboard_single_multi_select"
        ]
        assert json.loads(revised.iloc[0].primary_error_json)["reason_code"] == (
            "SCORER_UNSUPPORTED_CLAIMS"
        )
        errors = queries.errors_frame(
            revised, queries.calls_frame(connection, [f"{run_id}/D01-B-1"])
        )
        assert set(errors.scope) == {"primary", "original_primary"}
        assert set(errors.reason_code) == {"SCORER_UNSUPPORTED_CLAIMS", "MCP_PROVIDER_ERROR"}
        dimension_rows = connection.execute(
            "SELECT scoring_id,status,scorer_version FROM score_dimensions "
            "WHERE run_id=? AND trial_id='D01-B-1' AND dimension='unsupported_claims' "
            "ORDER BY scoring_id",
            [run_id],
        ).fetchall()
        assert {row[0] for row in dimension_rows} == {"original", revision}
        assert {row[1] for row in dimension_rows} == {"pass", "unknown"}


def test_legacy_score_dimension_primary_key_is_migrated(tmp_path):
    database = tmp_path / "legacy-analytics.duckdb"
    with connect(database) as connection:
        connection.execute("DROP TABLE score_dimensions")
        connection.execute(
            """CREATE TABLE score_dimensions (
                run_id VARCHAR, trial_id VARCHAR, scorer_version VARCHAR,
                dimension VARCHAR, status VARCHAR, passed INTEGER, total INTEGER,
                checks_json VARCHAR, PRIMARY KEY (run_id,trial_id,dimension)
            )"""
        )
        connection.execute(
            "INSERT INTO score_dimensions VALUES ('legacy','D01-B-1','knowledge-pilot-v2',"
            "'schema_validity','pass',1,1,'{}')"
        )
    with connect(database) as connection:
        key = tuple(
            row[1]
            for row in sorted(
                (
                    row
                    for row in connection.execute(
                        "PRAGMA table_info('score_dimensions')"
                    ).fetchall()
                    if row[5]
                ),
                key=lambda row: row[5],
            )
        )
        assert key == ("run_id", "trial_id", "scoring_id", "dimension")
        assert connection.execute(
            "SELECT scoring_id,scorer_version FROM score_dimensions WHERE run_id='legacy'"
        ).fetchone() == ("original", "knowledge-pilot-v2")


def test_no_double_counting_client_and_server(historical):
    rows = historical.execute(
        "SELECT observation_source,count(*),sum(counted::INT) FROM mcp_calls WHERE run_id=? "
        "GROUP BY observation_source ORDER BY observation_source",
        [HISTORICAL[2]],
    ).fetchall()
    assert rows == [("client_events", 23, 0), ("server_telemetry", 23, 23)]
    links = historical.execute(
        "SELECT DISTINCT correlation FROM mcp_calls WHERE observation_source='server_telemetry'"
    ).fetchall()
    assert links == [("ordinal_unconfirmed",)]


def test_pairs_sql_aggregates_and_configuration_filtering(historical):
    pairs = queries.paired_trials(historical)
    assert pairs.delta_score.tolist() == [0.25, -0.25, 0.5]
    frame = queries.trials_frame(
        historical, filters={"configuration": ["consolidated-v1.1"], "task_id": ["D01"]}
    )
    assert len(frame) == 2 and set(frame.run_id) == {HISTORICAL[2]}
    summary = queries.tool_summary(historical, queries.selection_keys(frame))
    assert summary.observed_calls.sum() == 23
    assert summary.failed.sum() == 9
    docs = summary[summary.tool_name == "get_function_docs"].iloc[0]
    assert docs.useful_bytes == 50498 and docs.cache_hit_rate > 0.98
    assert docs.p50_ms == pytest.approx(0.971)
    assert len(queries.overview(historical).configuration_key.unique()) == 2
    with pytest.raises(ValueError, match="unknown_filter"):
        queries.trials_frame(historical, filters={"raw SQL": ["anything"]})


def test_synthetic_baseline_metrics_tasks_tools_and_run_selector(tmp_path):
    root, _, _, _ = make_full_baseline(tmp_path, "20261025T135949Z-9ff06c47")
    with connect(":memory:") as connection:
        imported = import_run(connection, root, "20261025T135949Z-9ff06c47")
        assert imported["state"] == "completed"
        catalog = queries.run_catalog(connection)
        assert catalog.iloc[0].full_status == "full_comparable"
        assert queries.default_run_id(catalog) == "20261025T135949Z-9ff06c47"
        metrics = queries.run_metrics(connection, "20261025T135949Z-9ff06c47")
        assert (
            metrics["passed_checks_a"],
            metrics["total_checks_a"],
            metrics["passed_checks_b"],
            metrics["total_checks_b"],
            metrics["delta_checks"],
        ) == (113, 136, 116, 136, 3)
        assert (metrics["fully_correct_a"], metrics["fully_correct_b"]) == (13, 13)
        assert (
            metrics["mcp_adoption_numerator"],
            metrics["mcp_adoption_denominator"],
            metrics["mcp_calls"],
            metrics["mcp_errors"],
            metrics["exact_repeats"],
        ) == (2, 19, 57, 26, 3)
        tasks = queries.adoption_by_task(connection, "20261025T135949Z-9ff06c47")
        controls = tasks.set_index("task_id")
        assert (controls.loc["D01", "delta_checks"], controls.loc["D01", "mcp_calls"]) == (
            3,
            45,
        )
        assert (controls.loc["D02", "delta_checks"], controls.loc["D02", "mcp_calls"]) == (
            0,
            12,
        )
        assert controls.loc["E01", "delta_checks"] == controls.loc["E05", "delta_checks"] == 0
        assert controls.loc["E01", "mcp_calls"] == controls.loc["E05", "mcp_calls"] == 0
        assert controls.loc["E04", "delta_checks"] == 1
        assert controls.loc["E04", "mcp_calls"] == 0
        assert controls.loc["H10", "delta_checks"] == -1
        assert controls.loc["H10", "mcp_calls"] == 0
        tool_summary, calls = queries.tool_effectiveness(connection, "20261025T135949Z-9ff06c47")
        tools = tool_summary.set_index("tool_name")
        assert tools.loc[
            "get_function_docs", ["total_calls", "successful_calls", "application_errors"]
        ].tolist() == [49, 23, 26]
        assert tools.loc[
            "get_package", ["total_calls", "successful_calls", "application_errors"]
        ].tolist() == [7, 7, 0]
        assert tools.loc[
            "search_packages", ["total_calls", "successful_calls", "application_errors"]
        ].tolist() == [1, 1, 0]
        doc_calls = calls[calls.tool_name == "get_function_docs"]
        error_codes = [
            code for item in doc_calls.error_codes_json.dropna() for code in json.loads(item)
        ]
        assert error_codes.count("docs_not_found") == 26
        assert calls.trial_id.notna().all()
        assert metrics["api_tokens_b"] is None and metrics["observed_costs_b"] == {}


def test_error_count_stays_unknown_without_per_call_error_observations(tmp_path):
    root, run, record = make_run(tmp_path, run_id="call-count-only", calls=1)
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        task = queries.adoption_by_task(connection, run.name).iloc[0]
        assert task.mcp_calls == 1
        assert pd.isna(task.mcp_errors)


def test_newer_partial_d01_rerun_smoke_and_bad_metadata_do_not_replace_full(tmp_path):
    root, _, _, _ = make_full_baseline(
        tmp_path, "full-baseline", created_at="2026-10-24T12:00:00Z", calls=False
    )
    partial_root, partial, record = make_run(tmp_path, run_id="d01-later", calls=12)
    assert partial_root == root
    manifest = json.loads((partial / "experiment.json").read_text(encoding="utf-8"))
    manifest.update(
        created_at_utc="2026-10-26T12:00:00Z",
        tasks=["D01"],
        modes=["with-mcp"],
        repetitions=1,
        trial_count=1,
        trial_plan=[
            {"trial_id": record["trial_id"], "task": "D01", "mode": "with-mcp", "repetition": 1}
        ],
        instructions="standard",
    )
    (partial / "experiment.json").write_text(json.dumps(manifest), encoding="utf-8")
    smoke_root, smoke, _ = make_run(tmp_path, run_id="smoke-run", calls=0)
    smoke_manifest = json.loads((smoke / "experiment.json").read_text(encoding="utf-8"))
    smoke_manifest["instructions"] = "diagnostic"
    (smoke / "experiment.json").write_text(json.dumps(smoke_manifest), encoding="utf-8")
    corrupt_root, corrupt, _ = make_run(tmp_path, run_id="corrupt-run", calls=0)
    (corrupt / "experiment.json").write_text("{invalid", encoding="utf-8")
    assert smoke_root == corrupt_root == root
    with connect(":memory:") as connection:
        for run_id in ("full-baseline", "d01-later", "smoke-run", "corrupt-run"):
            import_run(connection, root, run_id)
        catalog = queries.run_catalog(connection)
        states = catalog.set_index("run_id").full_status
        assert states["full-baseline"] == "full_comparable"
        assert states["d01-later"] != "full_comparable"
        assert states["smoke-run"] == "diagnostic"
        assert states["corrupt-run"] == "unknown"
        assert queries.default_run_id(catalog) == "full-baseline"


def test_incomplete_scoring_error_and_scorer_mismatch_never_make_full_delta(tmp_path):
    root, run, _, records = make_full_baseline(tmp_path, "scoring-error", calls=False)
    _, baseline, _, _ = make_full_baseline(tmp_path, "full-baseline", calls=False)
    records[-1]["status"] = "scoring_error"
    records[-1]["score"] = None
    (run / "results.json").write_text(json.dumps(records), encoding="utf-8")
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        import_run(connection, root, baseline.name)
        state = connection.execute(
            "SELECT full_status FROM run_metadata WHERE run_id=?", [run.name]
        ).fetchone()[0]
        metrics = queries.run_metrics(connection, run.name)
        assert state == "partial"
        assert metrics["delta_checks"] is None
        assert queries.default_run_id(queries.run_catalog(connection)) == baseline.name
        comparison, warnings, score_compatible = queries.compare_runs(
            connection, baseline.name, run.name
        )
        assert not score_compatible
        assert any("score delta is unavailable" in warning for warning in warnings)
        assert comparison.loc[comparison.metric == "Passed checks B", "baseline"].isna().all()

    root2, run2, _, records2 = make_full_baseline(tmp_path, "scorer-mismatch", calls=False)
    records2 = [dict(record) for record in records2]
    for record in records2:
        record["score"] = dict(record["score"])
        if record["trial_id"] == "D01-B-1":
            record["score"]["scorer_version"] = "different-scorer-v1"
    (run2 / "results.json").write_text(json.dumps(records2), encoding="utf-8")
    with connect(":memory:") as connection:
        import_run(connection, root2, run2.name)
        state = connection.execute(
            "SELECT full_status FROM run_metadata WHERE run_id=?", [run2.name]
        ).fetchone()[0]
        task = queries.adoption_by_task(connection, run2.name).set_index("task_id")
        assert state == "partial"
        assert pd.isna(task.loc["D01", "delta_checks"])
        assert queries.default_run_id(queries.run_catalog(connection)) is None


def test_repetition_pairing_null_scores_and_v2_dimensions_are_separate(tmp_path):
    root, run, record = make_run(tmp_path, run_id="repeat-run", calls=1)
    manifest = json.loads((run / "experiment.json").read_text(encoding="utf-8"))
    manifest.update(
        created_at_utc="2026-10-25T12:00:00Z",
        modes=["without-mcp", "with-mcp"],
        repetitions=2,
        trial_count=4,
        trial_plan=[
            {
                "trial_id": f"D01-{'A' if mode == 'without-mcp' else 'B'}-{rep}",
                "task": "D01",
                "mode": mode,
                "repetition": rep,
            }
            for rep in (1, 2)
            for mode in ("without-mcp", "with-mcp")
        ],
    )
    records = []
    for repetition in (1, 2):
        for mode, letter in (("without-mcp", "A"), ("with-mcp", "B")):
            trial = dict(record)
            trial.update(
                trial_id=f"D01-{letter}-{repetition}",
                trial=f"D01-{letter}-{repetition}",
                mode=mode,
                repetition=repetition,
                mcp_usage={"calls": 2 if mode == "with-mcp" else 0},
                score={
                    "passed": 2 if mode == "without-mcp" else 3,
                    "total": 4,
                    "fully_correct": False,
                    "scorer_version": "knowledge-pilot-v2",
                    "failed_checks": ["docs"],
                    "dimensions": {
                        "schema_validity": {
                            "status": "pass",
                            "passed": 1,
                            "total": 1,
                            "checks": {"public_contract": "pass"},
                        }
                    },
                },
            )
            records.append(trial)
    (run / "experiment.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "results.json").write_text(json.dumps(records), encoding="utf-8")
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        pairs = queries.paired_trials(connection)
        assert len(pairs) == 2 and set(pairs.repetition) == {1, 2}
        task = queries.adoption_by_task(connection, run.name).iloc[0]
        assert task.matched_repetitions == 2
        assert task.delta_checks == 2
        dimensions = connection.execute(
            "SELECT count(*) FROM score_dimensions WHERE run_id=?", [run.name]
        ).fetchone()[0]
        assert dimensions == 4
        assert queries.run_metrics(connection, run.name)["passed_checks_b"] == 6
        assert queries.run_metrics(connection, run.name)["delta_checks"] is None
        assert queries.run_catalog(connection).iloc[0].v2_observation_schema is None


def test_v2_projections_import_safely_without_double_counting(tmp_path):
    root, run, record = make_run(tmp_path, run_id="v2-run", calls=2)
    rows = [
        {
            "schema_version": "2.0",
            "event_type": "mcp.call.observed",
            "source": "agent_stream",
            "client_call_number": 1,
            "client_item_id": "item-1",
            "server_call_number": 1,
            "tool": "get_function_docs",
            "correlation_quality": "inferred_ordinal",
            "request_projection": {"status": "projected", "function": "plot", "request_bytes": 48},
            "response_projection": {
                "status": "projected",
                "is_error": True,
                "error_codes": ["docs_not_found"],
                "response_bytes": 12,
            },
            "duration_ms": 3.0,
            "client_protocol_call_id": None,
            "server_protocol_call_id": None,
        },
        {
            "schema_version": "2.0",
            "event_type": "mcp.call.observed",
            "source": "mcp_server",
            "client_call_number": None,
            "client_item_id": None,
            "server_call_number": 1,
            "tool": "get_function_docs",
            "correlation_quality": "inferred_ordinal",
            "request_projection": {"status": "unavailable"},
            "response_projection": {
                "status": "projected",
                "is_error": True,
                "error_codes": ["docs_not_found"],
                "response_bytes": 12,
            },
            "duration_ms": 2.0,
            "client_protocol_call_id": None,
            "server_protocol_call_id": None,
        },
        {
            "schema_version": "2.0",
            "event_type": "mcp.call.observed",
            "source": "mcp_server",
            "client_call_number": None,
            "client_item_id": None,
            "server_call_number": 2,
            "tool": "get_package",
            "correlation_quality": "unmatched_server",
            "request_projection": {"status": "unavailable"},
            "response_projection": {
                "status": "projected",
                "is_error": False,
                "package": "termr",
                "repository": "cran",
                "response_bytes": 40,
            },
            "duration_ms": 5.0,
            "client_protocol_call_id": None,
            "server_protocol_call_id": None,
        },
    ]
    assert all(projection_v2.validate_record(row) for row in rows)
    (run / "mcp_observations_v2.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    secret = "sk-test-secret-canary-123456789"
    record["reasoning"] = secret
    (run / "results.json").write_text(json.dumps([record]), encoding="utf-8")
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        table, calls = queries.tool_effectiveness(connection, run.name)
        assert table.total_calls.sum() == 2
        assert table.application_errors.sum() == 1
        assert calls.trial_id.isna().all()
        assert calls.task_id.isna().all()
        assert any("plot" in value for value in calls.request_projection_json)
        stored = repr(connection.execute("SELECT * FROM mcp_observations_v2").fetchall())
        assert secret not in stored and "arguments" not in stored
        metadata = queries.run_catalog(connection).iloc[0]
        assert metadata.v2_observation_schema == "2.0"
        assert metadata.v2_observation_status == "complete"


@pytest.mark.parametrize(
    ("client_sequence", "server_sequence", "expected"),
    [
        (pd.NA, 7, 7),
        (None, 7, 7),
        (0, 7, 0),
        (3, None, 3),
        (3, 7, 3),
        (None, None, None),
        (pd.NA, pd.NA, None),
    ],
)
def test_nullable_v2_call_sequence_prefers_client_without_boolean_coercion(
    client_sequence, server_sequence, expected
):
    result = queries._first_non_null(client_sequence, server_sequence)
    if expected is None:
        assert result is None
    else:
        assert result == expected


def test_mixed_v1_v2_scores_are_never_pooled(tmp_path):
    root, run, _, records = make_full_baseline(tmp_path, "mixed-score", calls=False)
    for record in records:
        if record["task"] == "D01":
            record["score"]["scorer_version"] = "knowledge-pilot-v2"
            record["score"]["dimensions"] = {
                "schema_validity": {
                    "status": "pass",
                    "passed": 1,
                    "total": 1,
                    "checks": {"contract": "pass"},
                }
            }
    (run / "results.json").write_text(json.dumps(records), encoding="utf-8")
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        metrics = queries.run_metrics(connection, run.name)
        assert metrics["score_generations"] == ["V1", "V2"]
        assert metrics["passed_checks_a"] is None
        assert metrics["passed_checks_b"] is None
        assert metrics["delta_checks"] is None
        dimensions = connection.execute(
            "SELECT count(*) FROM score_dimensions WHERE run_id=? AND dimension='schema_validity'",
            [run.name],
        ).fetchone()[0]
        assert dimensions == 2


def test_partial_jsonl_is_not_completed_and_events_stay_idempotent(tmp_path):
    root, run, _ = make_run(tmp_path)
    events = [
        event(run.name, "benchmark.run.started", trial_count=1),
        event(run.name, "benchmark.run.completed", status="completed"),
    ]
    valid = "".join(json.dumps(item) + "\n" for item in events)
    (run / "telemetry.jsonl").write_text(valid + '{"schema_version":', encoding="utf-8")
    with connect(":memory:") as connection:
        first = import_run(connection, root, run.name)
        assert first["state"] == "incomplete" and first["issues"] == {"partial_jsonl_tail": 1}
        assert connection.execute("SELECT count(*) FROM events").fetchone() == (2,)
        import_run(connection, root, run.name)
        assert connection.execute("SELECT count(*) FROM events").fetchone() == (2,)
        (run / "telemetry.jsonl").write_text(valid, encoding="utf-8")
        assert import_run(connection, root, run.name)["state"] == "completed"


def test_client_only_unfinished_call_preserves_unknown_outcome(tmp_path):
    root, run, _ = make_run(tmp_path)
    call = event(
        run.name,
        "mcp.tool.started",
        trial_id="D01-B-1",
        trace_id="trace-1",
        call_id="client-call-1",
        tool="get_function_docs",
        source="agent_stream",
    )
    (run / "telemetry.jsonl").write_text(
        json.dumps(call) + "\n" + json.dumps(call) + "\n", encoding="utf-8"
    )
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        assert connection.execute(
            "SELECT observation_source,counted,is_error,duration_ms,result_bytes,"
            "correlated_call_id FROM mcp_calls"
        ).fetchall() == [("client_events", True, None, None, None, None)]
        assert connection.execute("SELECT count(*) FROM events").fetchone() == (1,)
        row = queries.tool_summary(connection, [f"{run.name}/D01-B-1"]).iloc[0]
        assert pd.isna(row.failed) and pd.isna(row.p50_ms)


def test_invalid_future_events_are_rejected_without_payloads(tmp_path):
    root, run, _ = make_run(tmp_path)
    future = event(run.name, "benchmark.run.completed", status="completed")
    future["schema_version"] = "99.0"
    future["reasoning"] = "sensitive-event-canary"
    (run / "telemetry.jsonl").write_text(json.dumps(future) + "\n", encoding="utf-8")
    with connect(":memory:") as connection:
        result = import_run(connection, root, run.name)
        assert result["state"] == "incomplete"
        assert result["issues"] == {"invalid_telemetry_event": 1}
        assert connection.execute("SELECT count(*) FROM events").fetchone() == (0,)


def test_finalized_trial_survives_missing_aggregate(tmp_path):
    root, run, record = make_run(tmp_path)
    trial = run / record["trial_id"]
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps(record), encoding="utf-8")
    (run / "results.json").unlink()
    with connect(":memory:") as connection:
        assert import_run(connection, root, run.name)["trials"] == 1
        assert connection.execute("SELECT passed,total FROM trials").fetchone() == (3, 4)


def test_schema_validation_missing_identifiers_and_atomic_rollback(tmp_path):
    root, run, record = make_run(tmp_path)
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        record["task"] = None
        (run / "results.json").write_text(json.dumps([record]), encoding="utf-8")
        with pytest.raises(ValueError, match="missing_trial_task_or_mode"):
            import_run(connection, root, run.name)
        assert connection.execute("SELECT count(*) FROM trials").fetchone() == (1,)
        (run / "experiment.json").write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
        with pytest.raises(ValueError, match="unsupported_manifest"):
            import_run(connection, root, run.name)


def test_closed_projection_blocks_secrets_arguments_and_reasoning(tmp_path):
    root, run, record = make_run(tmp_path)
    secret = "sk-test-secret-canary-123456789"
    record.update(
        error=f"Authorization: Bearer {secret}",
        error_type="RuntimeError",
        arguments={"password": secret},
        reasoning="private-canary-reasoning",
        environment={"OPENAI_API_KEY": secret},
    )
    record["mcp_telemetry"] = {
        "calls": [
            {
                "tool_name": "get_function_docs",
                "call_number": 1,
                "status": "error",
                "arguments": {"password": secret},
                "result": secret,
                "response_bytes": 1000,
            }
        ]
    }
    (run / "results.json").write_text(json.dumps([record]), encoding="utf-8")
    (run / "events.json").write_text("raw reasoning must never be read", encoding="utf-8")
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        data = repr([connection.execute(f"SELECT * FROM {table}").fetchall() for table in TABLES])
        assert secret not in data and "private-canary-reasoning" not in data
        assert "OPENAI_API_KEY" not in data and "password" not in data
        assert connection.execute("SELECT cost_amount,api_total_tokens FROM trials").fetchone() == (
            None,
            None,
        )


def test_agent_observability_import_is_safe_idempotent_and_legacy_compatible(tmp_path):
    root, run, _ = make_run(tmp_path, run_id="observed-run")
    manifest = json.loads((run / "experiment.json").read_text(encoding="utf-8"))
    manifest["telemetry_schema_version"] = "1.1"
    manifest["environment"] = {"task_package_pins": {"D01": {"termr": "1.0.1"}}}
    (run / "experiment.json").write_text(json.dumps(manifest), encoding="utf-8")
    writer = telemetry_recorder.RunTelemetry(run, run.name, strict=True)
    trial = writer.trial("D01-B-1")
    trial.emit(
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
    trial.emit(
        "mcp.exposure.response",
        source="agents_api",
        session_config_status="response_echo_unavailable",
        returned_agent_tool_names=None,
        session_config_match=None,
    )
    call_id = trial.agent_tool_started("item-1", "get_package", "mcp", "mcp_tool_call")
    trial.agent_tool_finished("item-1", "get_package", "mcp", "mcp_tool_call", "success")
    trial.emit(
        "agent.evidence.observed",
        call_id=call_id,
        tool="get_package",
        evidence_source="agent_tool_result",
        source_access_status="mcp_response_observed",
        package="termr",
        package_version="1.0.1",
        repository="cran",
        verification_status="verified",
    )
    trial.emit(
        "agent.url.mentioned",
        call_id=call_id,
        tool="get_package",
        source_url="https://cran.r-project.org/package=termr",
        url_role="unknown",
        observation_location="tool_output",
        source_access_status="mcp_response_observed",
    )
    events = [json.loads(line) for line in writer.path.read_text(encoding="utf-8").splitlines()]
    assert all(telemetry_schema.validate_event(event) == [] for event in events)
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        first_count = connection.execute(
            "SELECT count(*) FROM agent_telemetry WHERE run_id=?", [run.name]
        ).fetchone()[0]
        imported = queries.agent_telemetry(connection, run.name)
        assert first_count == 6 and len(imported) == 6
        exposure = imported[imported.event_type == "mcp.exposure.configured"].iloc[0]
        assert exposure.remote_discovery_status == "unknown"
        assert pd.isna(exposure.remote_discovered_tools)
        echo = imported[imported.event_type == "mcp.exposure.response"].iloc[0]
        assert echo.session_config_status == "response_echo_unavailable"
        assert pd.isna(echo.session_config_match)
        assert (
            imported[imported.event_type == "agent.evidence.observed"].iloc[0].package_version
            == "1.0.1"
        )
        trace = queries.agent_traces(connection, run.name)
        assert len(trace) == 1
        assert trace.iloc[0].trace_completeness == "partial"
        assert trace.iloc[0].integrity_status == "valid"
        spans = queries.trace_spans(connection, run.name, trial_id="D01-B-1")
        assert not spans.empty and spans.span_id.is_unique
        assert set(spans.span_kind) >= {"trial", "agent_tool", "evidence_observation"}
        checkpoints = queries.observability_checkpoints(connection, run.name)
        discovery = checkpoints[
            (checkpoints.checkpoint_type == "discovery_confirmed")
            & (checkpoints.subject == "get_package")
        ].iloc[0]
        assert discovery.observation_status == "unknown"
        assessments = queries.opportunity_assessments(connection, run.name)
        package_discovery = assessments[assessments.opportunity_id == "D01-PACKAGE-DISCOVERY"].iloc[
            0
        ]
        assert package_discovery.assessment_state == "utilized"
        assert package_discovery.discovery_status == "unknown"
        import_run(connection, root, run.name)
        assert (
            connection.execute(
                "SELECT count(*) FROM agent_telemetry WHERE run_id=?", [run.name]
            ).fetchone()[0]
            == first_count
        )
        assert connection.execute("SELECT schema_version FROM analytics_meta").fetchall() == [(6,)]
        assert queries.agent_telemetry(connection, "old-run").empty


def test_agent_dashboard_marks_legacy_telemetry_unavailable(monkeypatch):
    pytest.importorskip("streamlit")
    from benchmarks.codex_r.analytics import dashboard

    messages = []

    class StreamlitStub:
        def info(self, message):
            messages.append(message)

    monkeypatch.setattr(dashboard, "st", StreamlitStub())
    connection = duckdb.connect(":memory:")
    try:
        dashboard._render_agent_observability(connection, "old-run", [])
    finally:
        connection.close()

    assert len(messages) == 1
    assert "unavailable" in messages[0].lower()
    assert "not a measured zero" in messages[0].lower()


def test_p2_trace_and_opportunity_import_is_idempotent_and_transactional():
    run_id = "synthetic-p2-run"
    trial_id = "D01-B-1"

    def event(event_type, offset, **fields):
        return {
            "schema_version": "1.2",
            "event_type": event_type,
            "run_id": run_id,
            "trial_id": trial_id,
            "trace_id": "trace-synthetic0001",
            "timestamp_utc": "2026-10-27T10:00:00Z",
            "monotonic_offset_ms": offset,
            "clock": "trial",
            "source": "runner",
            **fields,
        }

    values = [
        event("benchmark.trial.started", 0, task="D01", mode="with-mcp"),
        event(
            "provider.request.started", 1, call_id="provider-1", provider_operation="session_create"
        ),
        event(
            "provider.response.received",
            3,
            call_id="provider-1",
            provider_operation="session_create",
            provider_status="success",
            duration_ms=2,
        ),
        event(
            "mcp.exposure.configured",
            3,
            generated_agent_tool_names=["get_package"],
            configured_allowed_tools=["get_package"],
            remote_discovery_status="unknown",
            remote_discovered_tools=None,
        ),
        event(
            "mcp.exposure.response",
            3,
            source="agents_api",
            returned_agent_tool_names=["get_package"],
        ),
        event("agent.turn.started", 4, source="agent_stream"),
        event(
            "mcp.tool.started",
            5,
            source="agent_stream",
            call_id="client-call-0001",
            tool="get_package",
        ),
        event(
            "mcp.tool.completed",
            6,
            source="agent_stream",
            call_id="client-call-0001",
            tool="get_package",
            is_error=False,
        ),
        event("agent.turn.completed", 8, source="agent_stream"),
        event("benchmark.trial.completed", 10, status="scored", interrupted=False),
    ]
    events = [
        (hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(), value)
        for value in values
    ]
    records = {trial_id: {"task": "D01", "mode": "with-mcp", "session_creation_attempted": True}}
    annotation, annotation_sha = opportunity_telemetry.load_opportunity_manifest()
    p2_tables = (
        "trial_opportunity_assessments",
        "task_mcp_opportunities",
        "task_opportunity_registry",
        "observability_checkpoints",
        "agent_spans",
        "agent_traces",
    )
    with connect(":memory:") as connection:
        insert(
            connection,
            "trials",
            {
                "run_id": run_id,
                "trial_id": trial_id,
                "task_id": "D01",
                "mode": "with-mcp",
                "configuration": "B",
                "model": "synthetic-model",
                "fully_correct": True,
                "mcp_calls_observed": 1,
            },
        )

        def replace_p2_rows():
            connection.execute("BEGIN TRANSACTION")
            try:
                for table_name in p2_tables:
                    connection.execute(f"DELETE FROM {table_name} WHERE run_id=?", [run_id])
                import_trace_evidence(
                    connection,
                    run_id,
                    records,
                    events,
                    jsonl_present=True,
                    jsonl_complete=True,
                    opportunity_manifest=annotation,
                    opportunity_sha256=annotation_sha,
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

        replace_p2_rows()
        counts = {
            table_name: connection.execute(
                f"SELECT count(*) FROM {table_name} WHERE run_id=?", [run_id]
            ).fetchone()[0]
            for table_name in p2_tables
        }
        trace = queries.agent_traces(connection, run_id).iloc[0]
        assert trace.trace_completeness == "complete"
        assert trace.integrity_status == "valid"
        assert trace.trial_duration_ms == 10
        assert trace.time_to_first_mcp_ms == 5
        spans = queries.trace_spans(connection, run_id, trial_id=trial_id)
        span_ids = set(spans.span_id)
        assert all(
            pd.isna(parent) or parent in span_ids for parent in spans.parent_span_id.tolist()
        )
        opportunity = queries.opportunity_assessments(connection, run_id).iloc[0]
        assert opportunity.assessment_state == "utilized"
        assert opportunity.candidate_calls == 1
        assert opportunity.opportunity_manifest_sha256 == annotation_sha
        insert(
            connection,
            "trials",
            {
                "run_id": run_id,
                "trial_id": "D01-A-1",
                "task_id": "D01",
                "mode": "without-mcp",
                "configuration": "A",
                "model": "synthetic-model",
                "fully_correct": False,
                "mcp_calls_observed": 0,
            },
        )
        from benchmarks.codex_r.analytics import dashboard

        comparisons, opportunity_versions, comparison_tasks = dashboard._p2_comparison_rows(
            connection, run_id
        )
        assert opportunity_versions == {"p2-opportunities-1.0"}
        assert comparison_tasks == {"D01"}
        assert {row["configuration"] for row in comparisons} == {"A", "B"}
        by_configuration = {row["configuration"]: row for row in comparisons}
        observed = by_configuration["B"]
        assert observed["task_success_numerator"] == 1
        assert observed["task_success_denominator"] == 1
        assert observed["task_success_rate"] == 1.0
        assert observed["mcp_invoked_trials_numerator"] == 1
        assert observed["mcp_invoked_trials_denominator"] == 1
        assert observed["median_trial_latency_ms"] == 10.0
        assert observed["opportunity_utilization_numerator"] >= 1
        assert observed["opportunity_utilization_denominator"] >= 1
        assert observed["checkpoint_captured_numerator"] is not None
        assert observed["checkpoint_expected_denominator"] > 0
        unobserved = by_configuration["A"]
        assert unobserved["task_success_rate"] == 0.0
        assert unobserved["mcp_invoked_trials_numerator"] == 0
        assert unobserved["opportunity_utilization_denominator"] is None
        assert unobserved["median_trial_latency_ms"] is None
        replace_p2_rows()
        assert counts == {
            table_name: connection.execute(
                f"SELECT count(*) FROM {table_name} WHERE run_id=?", [run_id]
            ).fetchone()[0]
            for table_name in p2_tables
        }

        before_rollback = {
            table_name: connection.execute(
                f"SELECT count(*) FROM {table_name} WHERE run_id=?", [run_id]
            ).fetchone()[0]
            for table_name in p2_tables
        }
        connection.execute("BEGIN TRANSACTION")
        for table_name in p2_tables:
            connection.execute(f"DELETE FROM {table_name} WHERE run_id=?", [run_id])
        import_trace_evidence(
            connection,
            run_id,
            records,
            events,
            jsonl_present=True,
            jsonl_complete=True,
            opportunity_manifest=annotation,
            opportunity_sha256=annotation_sha,
        )
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                "INSERT INTO agent_traces SELECT * FROM agent_traces WHERE run_id=?", [run_id]
            )
        connection.execute("ROLLBACK")
        assert before_rollback == {
            table_name: connection.execute(
                f"SELECT count(*) FROM {table_name} WHERE run_id=?", [run_id]
            ).fetchone()[0]
            for table_name in p2_tables
        }


def test_p2_dashboard_historical_schema_has_explicit_unavailable_state(monkeypatch):
    pytest.importorskip("streamlit")
    from benchmarks.codex_r.analytics import dashboard

    messages = []

    class StreamlitStub:
        def divider(self):
            pass

        def subheader(self, _message):
            pass

        def info(self, message):
            messages.append(message)

    monkeypatch.setattr(dashboard, "st", StreamlitStub())
    connection = duckdb.connect(":memory:")
    try:
        dashboard._render_p2_trace_analysis(connection, "old-run", [])
    finally:
        connection.close()
    assert len(messages) == 1
    assert "unavailable" in messages[0].lower()
    assert "not a measured zero" in messages[0].lower()


def test_analytics_schema_five_migrates_additively_to_six():
    legacy = duckdb.connect(":memory:")
    legacy.execute("CREATE TABLE analytics_meta(schema_version INTEGER PRIMARY KEY)")
    legacy.execute("INSERT INTO analytics_meta VALUES (5)")
    legacy.execute(
        """CREATE TABLE score_dimensions (
            run_id VARCHAR, trial_id VARCHAR, scoring_id VARCHAR, scorer_version VARCHAR,
            dimension VARCHAR, status VARCHAR, passed INTEGER, total INTEGER, checks_json VARCHAR,
            PRIMARY KEY (run_id,trial_id,scoring_id,dimension)
        )"""
    )
    legacy.execute((ROOT / "analytics" / "schema.sql").read_text(encoding="utf-8"))
    assert legacy.execute("SELECT schema_version FROM analytics_meta").fetchall() == [(6,)]
    expected = {
        "agent_traces",
        "agent_spans",
        "observability_checkpoints",
        "task_opportunity_registry",
        "task_mcp_opportunities",
        "trial_opportunity_assessments",
    }
    actual = {row[0] for row in legacy.execute("SHOW TABLES").fetchall()}
    assert expected <= actual
    legacy.close()


def test_csv_fallback_known_usage_and_cost(tmp_path):
    root, run, record = make_run(tmp_path)
    record.update(
        usage={
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 20},
            "output_tokens": 10,
            "output_tokens_details": {"reasoning_tokens": 5},
            "total_tokens": 110,
        },
        cost={"amount": 0.123, "currency": "USD"},
    )
    (run / "results.json").unlink()
    with (run / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=record)
        writer.writeheader()
        writer.writerow(
            {
                key: json.dumps(value) if isinstance(value, (dict, list, bool)) else value
                for key, value in record.items()
            }
        )
    with connect(":memory:") as connection:
        import_run(connection, root, run.name)
        assert connection.execute(
            "SELECT api_total_tokens,api_cached_tokens,api_reasoning_tokens,cost_amount,"
            "cost_currency FROM trials"
        ).fetchone() == (110, 20, 5, 0.123, "USD")


def test_safe_artifact_preview_and_export(tmp_path):
    artifact = tmp_path / "run" / "trial" / "artifacts" / "answer.json"
    artifact.parent.mkdir(parents=True)
    content = json.dumps(
        {
            "package": "termr",
            "reasoning": "private",
            "environment": {"OPENAI_API_KEY": "secret"},
            "source_url": "https://example.org/?token=sk-abcdef123456789",
        }
    ).encode()
    artifact.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    preview = queries.artifact_preview(tmp_path, "run/trial/artifacts/answer.json", sha)
    assert "reasoning" not in preview and "OPENAI_API_KEY" not in preview and "sk-" not in preview
    with pytest.raises(ValueError, match="unsafe_relative"):
        queries.artifact_preview(tmp_path, "../run/trial/artifacts/answer.json", sha)
    with pytest.raises(ValueError, match="checksum"):
        queries.artifact_preview(tmp_path, "run/trial/artifacts/answer.json", "0" * 64)
    exported = queries.csv_export(pd.DataFrame({"text": ["=1+1", "ordinary"]})).decode("utf-8-sig")
    assert "'=1+1" in exported
    assert "\\|" in queries.markdown_export(pd.DataFrame({"text": ["a|b"]}))


def test_database_rebuild_read_only_and_run_catalog(tmp_path):
    if any(not (DEFAULT_RESULTS / run_id).is_dir() for run_id in HISTORICAL):
        pytest.skip("optional historical result directories are not available")
    database = tmp_path / "analytics.duckdb"
    import_directory(database, DEFAULT_RESULTS, runs=list(HISTORICAL), reports=DEFAULT_REPORTS)
    import_directory(database, DEFAULT_RESULTS, runs=list(HISTORICAL), rebuild=True)
    with connect(database, read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM trials").fetchone() == (6,)
        with pytest.raises(duckdb.Error):
            connection.execute("DELETE FROM trials")
        assert len(queries.run_catalog(connection)) == 3
        assert queries.default_run_id(queries.run_catalog(connection)) is None
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_b1_plan_import_and_dashboard_queries_keep_condition_pairs_separate():
    from benchmarks.codex_r.run_simple import planned_b1_trials

    plan = planned_b1_trials(["D03", "D01", "C01"], 2)
    manifest = {
        "experiment_id": "b1-discovery",
        "tasks": ["D03", "D01", "C01"],
        "modes": ["with-mcp"],
        "repetitions": 2,
        "conditions": ["control", "treatment"],
        "trial_plan": plan,
    }
    assert _trial_plan(manifest)[1] == "valid"
    broken = {**manifest, "trial_plan": [*plan[:-1], {**plan[-1], "condition": "treatment"}]}
    assert _trial_plan(broken)[1] == "invalid"

    run_id = "synthetic-b1"
    with connect(":memory:") as connection:
        insert(
            connection,
            "runs",
            {
                "run_id": run_id,
                "relative_path": run_id,
                "import_state": "imported",
                "completion_state": "completed",
                "model": "gpt-6-luna",
                "effort": "medium",
                "instructions": "standard",
                "expected_trials": 12,
                "observed_trials": 12,
                "manifest_schema": 1,
            },
        )
        insert(
            connection,
            "run_metadata",
            {
                "run_id": run_id,
                "conditions_json": '["control","treatment"]',
                "tasks_json": '["C01","D01","D03"]',
                "repetitions": 2,
                "trial_plan_count": 12,
                "trial_plan_status": "valid",
                "full_status": "full_comparable",
                "experiment_id": "b1-discovery",
                "experiment_version": "1.0",
            },
        )
        for item in plan:
            insert(
                connection,
                "trial_plan",
                {
                    "run_id": run_id,
                    "planned_trial_id": item["trial_id"],
                    "task_id": item["task"],
                    "mode": item["mode"],
                    "repetition": item["repetition"],
                    "condition": item["condition"],
                    "execution_order": item["execution_order"],
                },
            )
            scorer = "legacy" if item["task"] == "C01" else "knowledge-pilot-v2"
            control = item["condition"] == "control"
            insert(
                connection,
                "trials",
                {
                    "run_id": run_id,
                    "trial_id": item["trial_id"],
                    "task_id": item["task"],
                    "block": item["task"][0],
                    "mode": "with-mcp",
                    "condition": item["condition"],
                    "execution_order": item["execution_order"],
                    "experiment_id": "b1-discovery",
                    "repetition": item["repetition"],
                    "model": "gpt-6-luna",
                    "effort": "medium",
                    "configuration": "v2" if scorer.endswith("v2") else "legacy",
                    "instructions": "standard",
                    "compatibility_key": f"{item['task']}-{item['repetition']}",
                    "status": "scored",
                    "finalized": True,
                    "scorer_version": scorer,
                    "passed": 2 if control else 3,
                    "total": 4,
                    "fully_correct": False,
                    "mcp_calls_observed": 0 if control else 1,
                    "client_calls": 0 if control else 1,
                    "server_calls": 0 if control else 1,
                    "list_tools": 1,
                    "tool_search_calls": 0 if control else 1,
                    "api_total_tokens": 100,
                    "usage_status": "observed",
                    "duration_seconds": 10.0,
                    "cost_amount": 0.01,
                    "cost_currency": "USD",
                },
            )
            if not control:
                insert(
                    connection,
                    "mcp_calls",
                    {
                        "run_id": run_id,
                        "trial_id": item["trial_id"],
                        "observation_source": "server_telemetry",
                        "call_id": "1",
                        "tool_name": "get_package",
                        "counted": True,
                        "status": "error",
                        "call_sequence": 1,
                        "is_error": True,
                        "error_codes_json": '["docs_not_found"]',
                        "repeat_kind": "first",
                    },
                )
        pairs = queries.paired_trials(connection, filters={"run_id": [run_id]})
        assert len(pairs) == 6
        assert set(pairs.condition_a) == {"control"}
        assert set(pairs.condition_b) == {"treatment"}
        metrics = queries.run_metrics(connection, run_id)
        assert "passed_checks_a" not in metrics
        assert {item["condition"] for item in metrics["condition_metrics"]} == {
            "control",
            "treatment",
        }
        assert [item["mcp_calls"] for item in metrics["condition_metrics"]] == [0, 6]
        assert len(metrics["task_score_pairs"]) == 3
        tools, calls = queries.tool_effectiveness(connection, run_id)
        assert len(calls) == 6
        assert set(tools.condition) == {"treatment"}


def test_dashboard_markdown_report_and_comparison_export_are_text(monkeypatch):
    pytest.importorskip("streamlit")
    from types import SimpleNamespace

    from benchmarks.codex_r.analytics import dashboard

    report = dashboard._markdown_report(
        "Run report",
        "run-test",
        {"created_at_utc": "2026-10-26T00:00:00Z"},
        {"metric": "MCP calls", "value": 1},
    )
    assert isinstance(report, str) and "| metric | value |" in report

    exports = []
    fake_streamlit = SimpleNamespace(
        caption=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        write=lambda *args, **kwargs: None,
        download_button=lambda label, data, *args, **kwargs: exports.append(data),
    )
    monkeypatch.setattr(dashboard, "st", fake_streamlit)
    monkeypatch.setattr(dashboard, "table", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "_render_p2_comparison", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        dashboard,
        "compare_runs",
        lambda *args, **kwargs: (
            pd.DataFrame([{"metric": "MCP calls", "baseline": 1, "comparison": 2}]),
            [],
            False,
        ),
    )
    monkeypatch.setattr(dashboard, "_scorer_badge", lambda *args: "V1")
    monkeypatch.setattr(dashboard, "_run_label", lambda *args: "run")
    runs = pd.DataFrame(
        [
            {"run_id": "baseline", "suite_label": "standard"},
            {"run_id": "comparison", "suite_label": "standard"},
        ]
    )
    dashboard._render_compare(object(), "baseline", "comparison", runs)
    assert len(exports) == 1 and isinstance(exports[0], str)
    assert "Baseline Run ID: `baseline`" in exports[0]
