"""Offline evidence-vs-answer classification tests."""

import json

import pytest

from benchmarks.codex_r.evidence_audit import _read_telemetry, audit_run
from benchmarks.codex_r.telemetry import recorder


def test_audit_separates_observed_tool_facts_from_pinned_reference(tmp_path):
    run_id = "20261027T000000Z-fixture"
    run = tmp_path / run_id
    trial_dir = run / "D01-B-1" / "artifacts"
    trial_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "model": "gpt-6-luna",
        "effort": "medium",
        "instructions": "standard",
        "function_discovery_policy": "enabled",
        "mcp_server": {
            "registered_tools": ["get_package", "list_package_functions"],
            "allowed_tools": ["get_package", "list_package_functions"],
        },
    }
    result = {
        "run_id": run_id,
        "trial_id": "D01-B-1",
        "task": "D01",
        "mode": "with-mcp",
        "status": "scored",
        "score": {"passed": 2, "total": 4, "failed_checks": ["version"]},
        "mcp_usage": {"calls": 1, "calls_by_tool": {"get_package": 1}, "item_types": {}},
        "mcp_telemetry": {"calls": [{"tool_name": "get_package", "status": "ok"}]},
    }
    answer = {
        "rationale": "must not appear in output",
        "recommendations": [
            {
                "package": "termr",
                "version": "0.1.0",
                "source_url": "https://CRAN.R-project.org/package=termr",
                "documentation_url": "https://cran.r-project.org/web/packages/termr/termr.pdf",
                "feature_ids": ["reactive_terminal_ui"],
                "caveat_ids": ["some_apis_experimental"],
            }
        ],
    }
    (run / "experiment.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "results.json").write_text(json.dumps([result]), encoding="utf-8")
    (trial_dir / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
    telemetry = recorder.RunTelemetry(run, run_id, strict=True)
    trial = telemetry.trial("D01-B-1")
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
    pinned = {
        "D01": {
            "termr": {
                "version": "1.0.1",
                "source_url": "https://cran.r-project.org/package=termr",
                "documentation_url": "https://stat.ethz.ch/CRAN/web/packages/termr/refman/termr.html",
            }
        }
    }
    audit = audit_run(tmp_path, run_id, pinned)
    claim = audit["answer_claims"][0]
    assert claim["reference_version_match"] is False
    assert claim["evidence_consistency"] == "contradicted_by_observed_tool_result"
    assert claim["observed_tool_versions_for_package"] == ["1.0.1"]
    assert claim["source_identity_matches_reference"] is True
    assert claim["documentation_identity_matches_reference"] is False
    assert claim["citations"][0]["source_access_status"] == "matching_source_access_observed"
    assert "rationale" not in json.dumps(audit)


def test_audit_keeps_reference_mismatch_distinct_when_access_is_unobservable(tmp_path):
    run_id = "run-offline"
    run = tmp_path / run_id
    trial_dir = run / "D01-B-1" / "artifacts"
    trial_dir.mkdir(parents=True)
    (run / "experiment.json").write_text(
        json.dumps({"run_id": run_id, "mcp_server": {"registered_tools": [], "allowed_tools": []}}),
        encoding="utf-8",
    )
    (run / "results.json").write_text(
        json.dumps(
            [
                {
                    "run_id": run_id,
                    "trial_id": "D01-B-1",
                    "task": "D01",
                    "mode": "with-mcp",
                    "score": {},
                    "mcp_usage": {"calls": 0, "item_types": {"command_execution": 1}},
                }
            ]
        ),
        encoding="utf-8",
    )
    (trial_dir / "answer.json").write_text(
        json.dumps(
            {
                "recommendations": [
                    {
                        "package": "termr",
                        "version": "0.1.0",
                        "source_url": "https://cran.r-project.org/package=termr",
                        "documentation_url": "https://cran.r-project.org/web/packages/termr/termr.pdf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    audit = audit_run(
        tmp_path,
        run_id,
        {"D01": {"termr": {"version": "1.0.1", "source_url": None, "documentation_url": None}}},
    )
    claim = audit["answer_claims"][0]
    assert claim["reference_version_match"] is False
    assert claim["observed_tool_versions_for_package"] == []
    assert claim["evidence_consistency"] == "insufficient_observability"
    assert claim["citations"][0]["source_access_status"] == "source_access_observability_unknown"


def test_audit_does_not_export_untrusted_answer_urls_or_unsafe_run_paths(tmp_path):
    run_id = "run-offline"
    run = tmp_path / run_id
    trial_dir = run / "D01-B-1" / "artifacts"
    trial_dir.mkdir(parents=True)
    (run / "experiment.json").write_text("{}", encoding="utf-8")
    (run / "results.json").write_text(
        json.dumps(
            [
                {
                    "run_id": run_id,
                    "trial_id": "D01-B-1",
                    "task": "D01",
                    "mode": "with-mcp",
                    "mcp_usage": {"calls": 0},
                }
            ]
        ),
        encoding="utf-8",
    )
    secret_url = "https://attacker.example/?token=not-for-report"
    (trial_dir / "answer.json").write_text(
        json.dumps(
            {
                "recommendations": [
                    {
                        "package": "termr",
                        "version": "0.1.0",
                        "source_url": secret_url,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    audit = audit_run(tmp_path, run_id, {"D01": {"termr": {"version": "1.0.1"}}})
    serialized = json.dumps(audit)

    assert "attacker.example" not in serialized
    assert "not-for-report" not in serialized
    citation = audit["answer_claims"][0]["citations"][0]
    assert citation["url_present_in_final_answer"] is True
    assert citation["url"] is None
    with pytest.raises(ValueError, match="invalid_audit_run_id"):
        audit_run(tmp_path, "../outside", {})


def test_telemetry_reader_rejects_oversized_jsonl_lines(tmp_path):
    path = tmp_path / "telemetry.jsonl"
    path.write_text(" " * ((1 << 20) + 1), encoding="utf-8")

    with pytest.raises(ValueError, match="audit_telemetry_limit_exceeded"):
        _read_telemetry(path)
