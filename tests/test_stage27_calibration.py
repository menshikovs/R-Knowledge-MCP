"""Tests for Stage 2.7 Calibration Pipeline, Eligibility, and Pilot Preparation."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.codex_r.studies.stage2_validity_v1 import calibration_pipeline, cli

STUDY = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "codex_r"
    / "studies"
    / "stage2_validity_v1"
)


def test_task_eligibility_reconstructs_31_tasks_and_confirmatory_zero():
    rep = calibration_pipeline.audit_task_eligibility()
    assert rep["total_benchmark_tasks"] == 31
    assert rep["confirmatory_eligible_count"] == 0
    assert rep["calibration_needed_count"] == 17
    assert rep["recalibration_required_count"] == 8
    assert rep["quarantined_count"] == 6

    strata = rep["strata_counts"]
    assert strata["S1_confirmatory_core"] == 0
    assert strata["S2_calibration_needed"] == 17
    assert strata["RC_recalibration_required"] == 8
    assert strata["Q_quarantined_or_smoke"] == 6

    # Every task has valid SHA-256 for task and scorer
    for task in rep["tasks"]:
        assert len(task["task_sha256"]) == 64
        assert len(task["scorer_sha256"]) == 64
        if task["task_id"] in ("D01", "D02", "D03", "E01", "E04", "E05"):
            assert any("BEN-002" in x for x in task["exclusions"])


def test_calibration_schedule_is_deterministic_and_arm_a_only():
    sched1 = calibration_pipeline.build_calibration_schedule(seed=42)
    sched2 = calibration_pipeline.build_calibration_schedule(seed=42)
    assert sched1 == sched2

    assert sched1["arms"] == ["A"]
    assert sched1["total_planned_trials"] == 51
    assert sched1["candidate_task_count"] == 17
    assert sched1["repetitions_per_task"] == 3
    assert sched1["model_execution_authorized"] is False
    assert sched1["status"] == "PREPARED_NOT_EXECUTED"

    # Verify trials structure
    for trial in sched1["trials"]:
        assert trial["arm"] == "A"
        assert trial["model"] == "gpt-6-luna"
        assert trial["timeout_seconds"] == 900
        assert len(trial["task_sha256"]) == 64
        assert len(trial["scorer_sha256"]) == 64
        assert trial["retry_policy"]["max_retries"] == 1
        assert trial["retry_policy"]["retry_on_candidate_failure"] is False


def test_evaluate_baseline_difficulty_evaluates_arm_a_and_identifies_uncertainty():
    # 3 repetitions with borderline mean (CI spans below 0.10)
    records = [
        {"arm": "A", "task": "T01", "outcome_kind": "scored", "score": 0.15},
        {"arm": "A", "task": "T01", "outcome_kind": "scored", "score": 0.25},
        {"arm": "A", "task": "T01", "outcome_kind": "scored", "score": 0.35},
        # Arm B records must be completely ignored
        {"arm": "B", "task": "T01", "outcome_kind": "scored", "score": 1.00},
        # Candidate failure in Arm A is scored as 0.0
        {"arm": "A", "task": "T02", "outcome_kind": "candidate_failure", "score": 0.0},
        {"arm": "A", "task": "T02", "outcome_kind": "candidate_failure", "score": 0.0},
        {"arm": "A", "task": "T02", "outcome_kind": "candidate_failure", "score": 0.0},
        # Ceiling task
        {"arm": "A", "task": "T03", "outcome_kind": "scored", "score": 1.0},
        {"arm": "A", "task": "T03", "outcome_kind": "scored", "score": 1.0},
        {"arm": "A", "task": "T03", "outcome_kind": "scored", "score": 1.0},
        # Centered provisional task
        {"arm": "A", "task": "T04", "outcome_kind": "scored", "score": 0.55},
        {"arm": "A", "task": "T04", "outcome_kind": "scored", "score": 0.60},
        {"arm": "A", "task": "T04", "outcome_kind": "scored", "score": 0.65},
    ]

    res = calibration_pipeline.evaluate_baseline_difficulty(records)
    assert res["evaluated_tasks"] == 4

    t1 = res["tasks"]["T01"]
    assert t1["observations"] == 3
    assert t1["mean_score"] == 0.25
    assert t1["classification"] == "candidate_in_range"
    assert t1["uncertainty_status"] == "inconclusive_sample_size_limited"

    t2 = res["tasks"]["T02"]
    assert t2["observations"] == 3
    assert t2["mean_score"] == 0.0
    assert t2["classification"] == "floor"

    t3 = res["tasks"]["T03"]
    assert t3["observations"] == 3
    assert t3["mean_score"] == 1.0
    assert t3["classification"] == "ceiling"
    assert t3["full_correct_rate"] == 1.0

    t4 = res["tasks"]["T04"]
    assert t4["observations"] == 3
    assert t4["mean_score"] == 0.60
    assert t4["classification"] == "candidate_in_range"
    assert t4["uncertainty_status"] == "provisional_small_sample"


def test_pilot_specification_requires_explicit_spend_authorization():
    spec = calibration_pipeline.build_pilot_specification()
    assert spec["status"] == "NOT_AUTHORIZED_FOR_EXECUTION"
    assert spec["authorized_budget_usd"] is None
    assert spec["task_count"] == 10
    assert spec["repetitions"] == 3
    assert spec["arms"] == ["A", "B", "C"]
    assert spec["total_trials"] == 90
    assert spec["model_identity"] == "gpt-6-luna"


def test_readiness_gates_accurately_report_infrastructure_pass_and_model_blocks():
    gates = calibration_pipeline.evaluate_readiness_gates(has_docker=True)
    assert gates["infrastructure_ready_for_calibration"] is True
    by_id = {g["gate_id"]: g for g in gates["gates"]}

    assert by_id["gate_1_offline_research_infrastructure"]["status"] == "PASS"
    assert by_id["gate_2_docker_experiment_infrastructure"]["status"] == "PASS"
    assert by_id["gate_3_calibration_execution"]["status"] == "BLOCKED"
    assert by_id["gate_4_pilot_execution"]["status"] == "BLOCKED"
    assert by_id["gate_5_confirmatory_experiment_eligibility"]["status"] == "BLOCKED"


def test_cli_calibration_pipeline_and_readiness_gates(tmp_path):
    rc1 = cli.main(["calibration-pipeline", "--out-dir", str(tmp_path)])
    assert rc1 == 0
    assert (tmp_path / "calibration_eligibility_report.json").is_file()
    assert (tmp_path / "calibration_schedule.json").is_file()
    assert (tmp_path / "pilot_specification.json").is_file()

    elig = json.loads(
        (tmp_path / "calibration_eligibility_report.json").read_text(encoding="utf-8")
    )
    assert elig["total_benchmark_tasks"] == 31

    gates_out = tmp_path / "gates.json"
    rc2 = cli.main(["readiness-gates", "--out", str(gates_out)])
    assert rc2 == 0
    assert gates_out.is_file()
    gates = json.loads(gates_out.read_text(encoding="utf-8"))
    assert gates["infrastructure_ready_for_calibration"] is True
