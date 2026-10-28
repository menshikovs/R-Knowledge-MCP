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


def test_validate_calibration_schedule():
    sched = calibration_pipeline.build_calibration_schedule()
    problems = calibration_pipeline.validate_calibration_schedule(sched)
    assert problems == []

    # Rejection of invalid schedule structures
    assert "schedule must be a dictionary" in (
        calibration_pipeline.validate_calibration_schedule([])
    )
    bad_arms = dict(sched, arms=["A", "B"])
    assert any(
        "arms=['A']" in p for p in calibration_pipeline.validate_calibration_schedule(bad_arms)
    )
    bad_ver = dict(sched, schedule_version="v0.0")
    assert any(
        "schedule_version" in p for p in calibration_pipeline.validate_calibration_schedule(bad_ver)
    )
    bad_count = dict(sched, trials=sched["trials"][:-1])
    assert any(
        "expected 51 trials" in p
        for p in calibration_pipeline.validate_calibration_schedule(bad_count)
    )


def test_execute_calibration_budget_authorization_guard(tmp_path):
    import pytest

    sched = calibration_pipeline.build_calibration_schedule()
    # Unprompted call without --mock or --authorize-spend must raise RuntimeError
    with pytest.raises(RuntimeError, match="Model execution budget not authorized"):
        calibration_pipeline.execute_calibration(sched, tmp_path, authorize_spend=False, mock=False)

    # Call with authorize_spend=True but missing OPENAI_API_KEY must raise RuntimeError
    import os

    orig_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
            calibration_pipeline.execute_calibration(
                sched, tmp_path, authorize_spend=True, mock=False
            )
    finally:
        if orig_key is not None:
            os.environ["OPENAI_API_KEY"] = orig_key


def test_execute_calibration_mock_persists_trials_and_resumes(tmp_path):
    sched = calibration_pipeline.build_calibration_schedule()
    # Execute a subset (3 trials for 1 task) to verify mock trial persistence
    mini_sched = dict(
        sched,
        candidate_tasks=["C03"],
        candidate_task_count=1,
        total_planned_trials=3,
        trials=[t for t in sched["trials"] if t["task"] == "C03"],
    )
    res = calibration_pipeline.execute_calibration(mini_sched, tmp_path, mock=True)
    assert res["finalized_count"] == 3
    assert res["total_planned"] == 3
    assert res["dataset_problems"] == []

    records_file = tmp_path / "trial_records.jsonl"
    journal_file = tmp_path / "ledger_journal.jsonl"
    assert records_file.is_file()
    assert journal_file.is_file()

    lines = [
        json.loads(x) for x in records_file.read_text(encoding="utf-8").splitlines() if x.strip()
    ]
    assert len(lines) == 3
    for rec in lines:
        assert rec["task"] == "C03"
        assert rec["arm"] == "A"
        assert rec["outcome_kind"] == "scored"
        assert rec["synthetic"] is True

    # Test idempotent resume: executing again into the same dir must not duplicate records
    res2 = calibration_pipeline.execute_calibration(mini_sched, tmp_path, mock=True)
    assert res2["finalized_count"] == 3
    lines2 = [
        json.loads(x) for x in records_file.read_text(encoding="utf-8").splitlines() if x.strip()
    ]
    assert len(lines2) == 3


def test_cli_calibration_commands_availability_and_processing(tmp_path):
    import pytest

    # Test CLI command availability via help
    with pytest.raises(SystemExit) as exc1:
        cli.main(["execute-calibration", "--help"])
    assert exc1.value.code == 0

    with pytest.raises(SystemExit) as exc2:
        cli.main(["evaluate-baseline", "--help"])
    assert exc2.value.code == 0

    with pytest.raises(SystemExit) as exc3:
        cli.main(["evaluate-calibration", "--help"])
    assert exc3.value.code == 0

    # Build calibration schedule
    sched_dir = tmp_path / "sched"
    assert cli.main(["calibration-pipeline", "--out-dir", str(sched_dir)]) == 0
    sched_path = sched_dir / "calibration_schedule.json"
    assert sched_path.is_file()

    # Execute mini mock calibration
    sched_data = json.loads(sched_path.read_text(encoding="utf-8"))
    sched_data["candidate_tasks"] = ["C03", "C04"]
    sched_data["candidate_task_count"] = 2
    sched_data["total_planned_trials"] = 6
    sched_data["trials"] = [t for t in sched_data["trials"] if t["task"] in ("C03", "C04")]
    mini_path = tmp_path / "mini_schedule.json"
    mini_path.write_text(json.dumps(sched_data), encoding="utf-8")

    run_dir = tmp_path / "run"
    rc_exec = cli.main(
        [
            "execute-calibration",
            "--schedule",
            str(mini_path),
            "--out-dir",
            str(run_dir),
            "--mock",
        ]
    )
    assert rc_exec == 0
    assert (run_dir / "trial_records.jsonl").is_file()

    # Evaluate baseline difficulty via CLI
    eval_out = tmp_path / "eval.json"
    rc_eval = cli.main(
        [
            "evaluate-baseline",
            "--records",
            str(run_dir / "trial_records.jsonl"),
            "--out",
            str(eval_out),
        ]
    )
    assert rc_eval == 0
    assert eval_out.is_file()

    rep = json.loads(eval_out.read_text(encoding="utf-8"))
    assert rep["evaluated_tasks"] == 2
    assert "C03" in rep["tasks"]
    assert "C04" in rep["tasks"]


def test_mathematical_blockers_prevent_reaching_30_confirmatory_tasks():
    rep = calibration_pipeline.audit_task_eligibility()
    s1_count = rep["strata_counts"]["S1_confirmatory_core"]
    s2_count = rep["strata_counts"]["S2_calibration_needed"]
    rc_count = rep["strata_counts"]["RC_recalibration_required"]
    q_count = rep["strata_counts"]["Q_quarantined_or_smoke"]
    total_tasks = rep["total_benchmark_tasks"]

    assert total_tasks == 31
    assert s1_count == 0
    assert s2_count == 17
    assert rc_count == 8
    assert q_count == 6

    # Mathematical Blocker 1: Maximum possible S1 yield from calibration schedule alone is 17 < 30
    assert s1_count + s2_count == 17
    assert s1_count + s2_count < 30

    # Mathematical Blocker 2: Even if all RC tasks are decoupled and 100% pass, 17 + 8 = 25 < 30
    assert s1_count + s2_count + rc_count == 25
    assert s1_count + s2_count + rc_count < 30

    # Conclusion: Catalogue expansion by at least +5 tasks is strictly required to reach 30
    deficit_from_schedule = 30 - (s1_count + s2_count)
    assert deficit_from_schedule == 13
    deficit_from_entire_usable_catalogue = 30 - (s1_count + s2_count + rc_count)
    assert deficit_from_entire_usable_catalogue == 5
