"""Preregistration amendment A1: originals kept, scope limited, nothing removed or backdated."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from benchmarks.codex_r.studies.stage2_validity_v1 import (
    amendment,
    design,
    legacy_executor,
    manifest,
    protocol,
    records,
    runner,
)

POLICY = {
    "study_configuration": "study1_mcp_vs_model_knowledge",
    "non_mcp_tools": [],
    "executor_image": "sha256:" + "e" * 64,
    "network": legacy_executor.LEGACY_NETWORK,
    "model_transport": legacy_executor.MODEL_TRANSPORT,
    "web_access_policy": "none",
}


def _capability(**overrides):
    cap = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "non_mcp_tools": [],
        "executor_image": POLICY["executor_image"],
        "network": POLICY["network"],
        "model_transport": POLICY["model_transport"],
        "web_access_policy": "none",
        "scorer_isolation": {"exposed_files": []},
        "observed": {"web_access_calls": 0, "reference_access_hits": []},
    }
    cap.update(overrides)
    return cap


def _record(capability, *, amended=True):
    planned = design.build_plan(["R01"], ("A", "B"), 1, 3, protocol.STUDY_ID)["trials"][0]
    cfg = runner.StudyExecutionConfig(
        protocol_amendment="A1" if amended else None,
        capability_policy=POLICY if amended else None,
    )
    runner_record = {
        "status": "scored",
        "score": {"status": "scored", "passed": 4, "total": 4},
        "model": cfg.model,
        "effort": cfg.effort,
        "scorer_identity": "legacy",
        "allowed_tools": [],
        "mcp_container_started": False,
        "agent_instructions_sha256": protocol.sha256_text(protocol.base_instructions()),
        "network_internal": False,
        "egress_destinations": None,
        "capability": capability,
    }
    planned = {**planned, "arm": "A"}
    return records.from_runner_result(planned, runner_record, [], cfg.expected_contract("legacy"))


def test_amendment_record_pins_the_unchanged_originals_and_its_document():
    built = amendment.build_amendment_record()
    saved = json.loads(amendment.RECORD.read_text(encoding="utf-8"))
    assert saved == built  # regenerate with `cli amendment --write` only on a deliberate change
    assert built["protocol_version"] == "1.1.0" and built["amends_protocol_version"] == "1.0.0"
    assert built["registered_before_any_real_trial"] is True
    assert (
        built["base"]["experiment_manifest_core_sha256"] == manifest.build_manifest()["core_sha256"]
    )
    assert set(built["rules"]["superseded_violation_codes"]) == {
        "egress_not_restricted",
        "egress_unverified",
    }


def test_original_preregistration_still_states_the_1_0_0_rules():
    built = manifest.build_manifest()
    assert built["version"] == protocol.STUDY_VERSION == "1.0.0"
    assert {"egress_not_restricted", "egress_unverified"} <= set(
        built["exclusions"]["invalidating_violations"]
    )


def test_a1_keeps_superseded_codes_and_makes_a_compliant_trial_eligible():
    rec = _record(_capability())
    assert rec["protocol_version"] == "1.1.0+A1"
    superseded = [v for v in rec["violations"] if v.get("superseded_by") == "A1"]
    assert {v["code"] for v in superseded} == set(amendment.SUPERSEDED_VIOLATIONS)
    assert all(v["invalidating"] is False and v["detail"] for v in superseded)
    assert records.analysis_value(rec) == (1.0, "scored")


def test_without_the_amendment_the_same_trial_stays_excluded():
    rec = _record(_capability(), amended=False)
    assert rec["protocol_version"] == "1.0.0"
    assert records.analysis_value(rec) == (None, "invalidating_protocol_violation")


def test_trials_before_the_effective_time_are_not_made_eligible_retroactively():
    rec = _record(_capability(started_at_utc="2026-10-27T16:19:30+00:00"))
    assert "pre_amendment_trial" in {v["code"] for v in rec["violations"] if v["invalidating"]}
    assert records.analysis_value(rec)[0] is None
    assert "pre_amendment_trial" in {
        v["code"] for v in _record(_capability(started_at_utc=None))["violations"]
    }


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"non_mcp_tools": ["web_search"]}, "non_mcp_capabilities_differ"),
        ({"executor_image": "sha256:" + "f" * 64}, "non_mcp_capabilities_differ"),
        ({"network": "internal"}, "execution_environment_differs"),
        ({"model_transport": "responses_api"}, "execution_environment_differs"),
        ({"web_access_policy": "equal_web_search"}, "web_access_policy_differs"),
        (
            {"observed": {"web_access_calls": 2, "reference_access_hits": []}},
            "web_access_policy_deviation",
        ),
        ({"scorer_isolation": {"exposed_files": ["src/x/verifier.R"]}}, "scorer_material_exposed"),
        ({"scorer_isolation": {}}, "capability_configuration_unrecorded"),
        (
            {
                "observed": {
                    "web_access_calls": 0,
                    "reference_access_hits": ["benchmarks/codex_r/oracle"],
                }
            },
            "reference_access_suspected",
        ),
    ],
)
def test_capability_deviations_are_invalidating_and_logged(override, code):
    rec = _record(_capability(**override))
    hits = [v for v in rec["violations"] if v["code"] == code]
    assert hits and all(v["invalidating"] and v["rule"] == "A1" for v in hits)
    assert rec["capability"]  # the delivered configuration is kept with the record
    assert records.analysis_value(rec)[0] is None


def test_missing_capability_configuration_is_invalidating():
    rec = _record(None)
    assert "capability_configuration_unrecorded" in {v["code"] for v in rec["violations"]}


def test_unknown_amendment_is_refused():
    cfg = runner.StudyExecutionConfig(protocol_amendment="A9")
    planned = design.build_plan(["R01"], ("A", "B"), 1, 3, protocol.STUDY_ID)["trials"][0]
    with pytest.raises(ValueError, match="unknown protocol amendment"):
        records.from_runner_result(
            planned, {"status": "error"}, [], cfg.expected_contract("legacy")
        )


def test_resume_under_a_different_protocol_version_is_rejected(tmp_path):
    plan = design.build_plan(["R01"], ("A", "B"), 1, 3, protocol.STUDY_ID)
    executor = runner.make_mock_trial_executor()
    a1 = runner.StudyExecutionConfig(protocol_amendment="A1", capability_policy=POLICY)
    runner.execute_study_plan(plan, a1, tmp_path, executor)
    with pytest.raises(ValueError, match="run_config"):
        runner.execute_study_plan(plan, runner.StudyExecutionConfig(), tmp_path, executor)


def test_no_catalogue_task_exposes_scorer_or_reference_files_to_candidate_mounts():
    from benchmarks.codex_r.studies.stage2_validity_v1 import calibration

    for entry in calibration.CATALOG:
        isolation = legacy_executor.scorer_isolation(entry["task"])
        assert isolation["exposed_files"] == [] and isolation["checked_files"] >= 2


def test_reference_access_heuristic_reads_only_non_mcp_tool_items(tmp_path):
    trial = tmp_path / "t-A"
    trial.mkdir()
    events = [
        {
            "item": {
                "type": "command_execution",
                "command": "curl https://github.com/menshikovs/R-Knowledge-MCP/raw/x",
            }
        },
        {
            "item": {
                "type": "mcp_tool_call",
                "tool": "get_package",
                "output": "benchmarks/codex_r/oracle",
            }
        },
        {"item": {"type": "command_execution", "command": "Rscript solution.R"}},
    ]
    (trial / "events.json").write_text(json.dumps(events), encoding="utf-8")
    assert legacy_executor.reference_access_hits(tmp_path, "t-A") == ["menshikovs/r-knowledge-mcp"]
    assert legacy_executor.reference_access_hits(tmp_path, "missing") == []
