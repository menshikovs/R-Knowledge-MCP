"""Offline extraction tests; no runner, model, HTTP or R execution."""

import csv
import json
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from benchmarks.codex_r.audit_baseline import (
    analyze,
    check_outcome,
    event_calls,
    rescore_json,
    tool_rows,
    tree_digest,
    write_csv,
)


@pytest.fixture
def audit_tmp():
    # Python 3.14's Windows mode=0o700 temp directories can be inaccessible
    # to a managed workspace process. Normal inherited permissions suffice.
    directory = Path(tempfile.gettempdir()) / f"rkmcp-offline-audit-{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        yield directory
    finally:
        assert directory.resolve().parent == Path(tempfile.gettempdir()).resolve()
        assert directory.name.startswith("rkmcp-offline-audit-")
        shutil.rmtree(directory)


def event(identity="call1", kind="added", status="in_progress", tool="get_package"):
    return {
        "type": f"agent.session.turn.item.{kind}",
        "item": {
            "type": "mcp_call",
            "id": identity,
            "name": tool,
            "status": status,
            "payload_redacted": True,
        },
    }


def record(calls):
    return {
        "run_id": "test",
        "trial_id": "D01-B-1",
        "task": "D01",
        "mcp_telemetry": {"calls": calls},
    }


def test_added_done_duplicates_are_one_call():
    events = [event(), None, {}, {"item": None}, event(kind="done", status="completed")]
    calls = event_calls(events)
    assert len(calls) == 1
    assert calls[0]["event_indices"] == [0, 4]
    rows, aligned = tool_rows(
        record(
            [
                {
                    "tool_name": "get_package",
                    "status": "ok",
                    "response_bytes": 123,
                }
            ]
        ),
        events,
        "run/D01-B-1",
    )
    assert aligned
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["arguments_json"] is None
    assert rows[0]["response_payload_bytes_retained"] is None
    assert rows[0]["response_bytes_recorded"] == 123


def test_incomplete_event_does_not_become_success_or_zero_latency():
    rows, aligned = tool_rows(record([]), [event()], "run")
    assert aligned  # No completed observations and no telemetry to match.
    assert rows[0]["status"] == "unknown"
    assert rows[0]["latency_ms"] is None
    assert rows[0]["join_basis"] == "unmatched"


def test_mismatching_names_do_not_join_response_to_wrong_call():
    rows, aligned = tool_rows(
        record(
            [
                {
                    "tool_name": "get_function_docs",
                    "status": "error",
                    "duration_ms": 10,
                }
            ]
        ),
        [event(kind="done")],
        "run",
    )
    assert not aligned
    assert rows[0]["status"] == "unknown"
    assert rows[0]["latency_ms"] is None
    assert rows[0]["telemetry_evidence"] is None


def test_server_only_observation_is_preserved():
    rows, aligned = tool_rows(
        record(
            [
                {
                    "tool_name": "get_function_docs",
                    "status": "error",
                    "error_codes": ["docs_not_found"],
                    "repeat_kind": "similar",
                }
            ]
        ),
        [],
        "run",
    )
    assert not aligned
    assert rows[0]["status"] == "error"
    assert rows[0]["semantic_repeat"] == "unknown"
    assert rows[0]["event_evidence"] == ""
    assert rows[0]["join_basis"] == "telemetry_only"


def test_payload_secrets_are_not_copied_into_tables():
    raw = event(kind="done")
    raw["item"]["arguments"] = {"api_key": "private-value"}
    raw["item"]["result"] = {"text": "private-result"}
    rows, _ = tool_rows(record([]), [raw], "run")
    assert "private-value" not in json.dumps(rows)
    assert "private-result" not in json.dumps(rows)


def test_optional_rescore_selects_only_json_tasks(monkeypatch, audit_tmp):
    from benchmarks.codex_r import knowledge_pilot

    seen = []

    def fake_score(task, artifacts, image, *, executor):
        seen.append(task)
        with pytest.raises(AssertionError, match="JSON scorers"):
            executor()
        return {"status": "scored", "passed": 1, "total": 4}

    monkeypatch.setattr(knowledge_pilot, "score", fake_score)
    records = [
        {
            "task": task,
            "trial_id": task + "-B-1",
            "score": {
                "status": "scored",
                "passed": 1,
                "total": 4,
            },
        }
        for task in ["D01", "E01", "E02", "H10"]
    ]
    result = rescore_json(records, audit_tmp)
    assert seen == ["D01", "E01"]
    assert result["all_match"]


@pytest.mark.parametrize(
    "saved",
    [
        None,
        {},
        {"status": "scoring_error", "passed": None},
        {"status": "scored", "failed_checks": None},
    ],
)
def test_missing_score_or_failed_checks_stays_unknown(saved):
    assert check_outcome({"score": saved}, "x") == "unknown"


def test_single_failed_check_string_is_not_split_into_characters():
    assert check_outcome({"score": {"status": "scored", "failed_checks": "one"}}, "one") == "fail"


def test_csv_is_utf8_preserves_null_and_protects_formulas(audit_tmp):
    path = audit_tmp / "table.csv"
    write_csv(path, [{"text": "=SUM(1)", "number": -1, "unknown": None, "label": "тест"}])
    with path.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row == {"text": "'=SUM(1)", "number": "-1", "unknown": "", "label": "тест"}


def test_tree_digest_uses_case_sensitive_posix_order(audit_tmp):
    import hashlib

    (audit_tmp / "Z.R").write_bytes(b"Z")
    (audit_tmp / "a.R").write_bytes(b"a")
    digest = hashlib.sha256()
    for name, value in [("Z.R", b"Z"), ("a.R", b"a")]:
        digest.update(name.encode() + b"\0")
        digest.update(hashlib.sha256(value).digest())
    assert tree_digest(audit_tmp, ".R") == digest.hexdigest()


def test_output_cannot_overwrite_run(audit_tmp):
    with pytest.raises(ValueError, match="separate"):
        analyze(audit_tmp, audit_tmp / "reports")


def test_minimal_run_is_deterministic_and_keeps_sources_unchanged(audit_tmp):
    run = audit_tmp / "run"
    run.mkdir()
    (run / "experiment.json").write_text(
        json.dumps(
            {
                "run_id": "empty",
                "trial_plan": [],
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )
    (run / "results.json").write_text("[]", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    first = analyze(run, audit_tmp / "out1")
    second = analyze(run, audit_tmp / "out2")
    assert first == second
    assert first["inputs_unchanged"]
    assert before == {p.name: p.read_bytes() for p in run.iterdir()}
    assert (audit_tmp / "out1/baseline_audit_data.json").read_bytes() == (
        audit_tmp / "out2/baseline_audit_data.json"
    ).read_bytes()
