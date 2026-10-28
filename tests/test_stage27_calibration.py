"""Tests for Stage 2.7 Calibration Pipeline, Eligibility, spend control and execution modes.

Offline only: the in-process mock executor and stubbed live executors. Docker-backed calibration
runs through the real topology live in ``test_stage27_docker_calibration.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.codex_r import knowledge_pilot_v2, knowledge_pilot_v21
from benchmarks.codex_r.studies.stage2_validity_v1 import (
    calibration_pipeline,
    cli,
    live_network,
    live_runner,
    manifest,
    records,
    runner,
    spend_control,
)

STUDY = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "codex_r"
    / "studies"
    / "stage2_validity_v1"
)
CATALOGUE = json.loads((STUDY / "task_catalog.json").read_text(encoding="utf-8"))["tasks"]
STRATA = {t["task"]: t["provisional_stratum"] for t in CATALOGUE}
CANDIDATES = sorted(t for t, s in STRATA.items() if s in ("S2", "RC"))


def _ceiling(**overrides):
    values = {
        "max_spend_usd": 1.0,
        "input_usd_per_million_tokens": 2.0,
        "output_usd_per_million_tokens": 8.0,
        "per_trial_reserve_usd": 0.05,
    }
    values.update(overrides)
    return spend_control.SpendCeiling(**values)


def _subset(tasks, reps=1):
    return calibration_pipeline.build_calibration_schedule(tasks=tasks, repetitions=reps)


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _journal(run_dir):
    return _lines(run_dir / "ledger_journal.jsonl")


# --------------------------------------------------------------------- eligibility / schedule


def test_task_eligibility_reconstructs_31_tasks_and_confirmatory_zero():
    rep = calibration_pipeline.audit_task_eligibility()
    assert rep["total_benchmark_tasks"] == 31
    assert rep["strata_counts"] == {
        "S1_target_confirmatory_core": 0,
        "S2_control_tool_use_tax": 17,
        "RC_recalibration_required": 8,
        "Q_quarantined_scorer_revision_required": 6,
    }
    assert rep["calibration_candidate_count"] == 25
    for task in rep["tasks"]:
        assert len(task["task_sha256"]) == 64
        assert len(task["scorer_sha256"]) == 64
        if task["task_id"] in ("D01", "D02", "D03", "E01", "E04", "E05"):
            assert any("BEN-002" in x for x in task["exclusions"])
        # Only RC tasks are targets by text that calibration can move into S1.
        assert task["can_enter_s1_via_calibration"] == (STRATA[task["task_id"]] == "RC")
        if STRATA[task["task_id"]] == "S2":
            assert task["target_by_features"] is False


def test_stratum_meanings_match_the_preregistered_manifest():
    declared = manifest.build_manifest()["confirmatory_task_rule"]["strata"]
    assert declared == {
        "S1": "target",
        "S2": "control (tool-use tax)",
        "RC": "recalibrate",
        "Q": "quarantined",
    }
    labels = calibration_pipeline.STRATUM_LABELS
    assert "control" in labels["S2"] and "calibration" not in labels["S2"]


def test_schedule_candidates_are_every_non_quarantined_catalogue_task():
    sched = calibration_pipeline.build_calibration_schedule()
    assert sched["candidate_tasks"] == CANDIDATES
    assert calibration_pipeline.calibration_candidate_tasks() == CANDIDATES
    assert sched["candidates_that_can_enter_s1"] == sorted(
        t for t, s in STRATA.items() if s == "RC"
    )
    # Regression: the earlier hard-coded 17-task list mixed 14 controls with 3 RC tasks and
    # omitted the other RC tasks and B01-B03. It is a strict subset of the corrected schedule.
    earlier = {f"R{i:02d}" for i in range(1, 13)} | {"C03", "C04", "H01", "H04", "H10"}
    assert earlier < set(sched["candidate_tasks"])
    assert not {t for t, s in STRATA.items() if s == "Q"} & set(sched["candidate_tasks"])


def test_calibration_schedule_is_deterministic_and_arm_a_only():
    sched1 = calibration_pipeline.build_calibration_schedule(seed=42)
    assert sched1 == calibration_pipeline.build_calibration_schedule(seed=42)
    assert sched1["arms"] == ["A"]
    assert sched1["total_planned_trials"] == 75
    assert sched1["candidate_task_count"] == 25
    assert sched1["repetitions_per_task"] == 3
    assert sched1["model_execution_authorized"] is False
    assert sched1["status"] == "PREPARED_NOT_EXECUTED"
    for trial in sched1["trials"]:
        assert trial["arm"] == "A"
        assert trial["model"] == "gpt-6-luna"
        assert trial["timeout_seconds"] == 900
        assert trial["retry_policy"]["max_retries"] == 1
        assert trial["retry_policy"]["retry_on_candidate_failure"] is False


def test_committed_stage27_artifacts_match_their_generators():
    def load(name):
        return json.loads((STUDY / name).read_text(encoding="utf-8"))

    assert load("calibration_schedule.json") == calibration_pipeline.build_calibration_schedule()
    assert load("calibration_eligibility_report.json") == (
        calibration_pipeline.audit_task_eligibility()
    )
    assert load("pilot_specification.json") == calibration_pipeline.build_pilot_specification()
    assert load("readiness_gates_report.json") == calibration_pipeline.evaluate_readiness_gates()


def test_validate_calibration_schedule_structure():
    sched = calibration_pipeline.build_calibration_schedule()
    validate = calibration_pipeline.validate_calibration_schedule
    assert validate(sched) == []
    assert "schedule must be a dictionary" in validate([])
    assert any("arms=['A']" in p for p in validate(dict(sched, arms=["A", "B"])))
    assert any("schedule_version" in p for p in validate(dict(sched, schedule_version="v0.0")))
    assert any(
        "expected 75 trials" in p for p in validate(dict(sched, trials=sched["trials"][:-1]))
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda t: t.update(task_sha256="0" * 64), "task_sha256 does not match"),
        (lambda t: t.update(scorer_sha256="0" * 64), "scorer_sha256 does not match"),
        (lambda t: t.update(scorer_version="knowledge-pilot-v2"), "scorer_version does not"),
        (lambda t: t.update(execution_index=99), "execution_index"),
        (lambda t: t.update(arm="B"), "expected 'A'"),
        (lambda t: t.update(position_in_block=2), "fresh single-trial block"),
        (lambda t: t.update(model="other-model"), "disagree on model"),
    ],
)
def test_schedule_with_tampered_trial_metadata_is_rejected(mutate, expected):
    sched = json.loads(json.dumps(calibration_pipeline.build_calibration_schedule()))
    mutate(sched["trials"][4])
    problems = calibration_pipeline.validate_calibration_schedule(sched)
    assert any(expected in p for p in problems), problems


def test_schedule_with_duplicate_trials_is_rejected():
    sched = json.loads(json.dumps(_subset(["B01"], reps=2)))
    sched["trials"][1]["trial_id"] = sched["trials"][0]["trial_id"]
    assert any(
        "duplicate trial_id" in p for p in calibration_pipeline.validate_calibration_schedule(sched)
    )
    sched = json.loads(json.dumps(_subset(["B01"], reps=2)))
    sched["trials"][1]["repetition"] = 1
    assert any(
        "duplicates task B01 repetition 1" in p
        for p in calibration_pipeline.validate_calibration_schedule(sched)
    )


def test_schedule_with_ineligible_or_unknown_tasks_is_rejected():
    quarantined = _subset(["D01"])
    assert any(
        "not eligible for calibration" in p
        for p in calibration_pipeline.validate_calibration_schedule(quarantined)
    )
    assert (
        calibration_pipeline.validate_calibration_schedule(quarantined, allow_ineligible_tasks=True)
        == []
    )
    unknown = json.loads(json.dumps(_subset(["B01"])))
    unknown["candidate_tasks"] = ["ZZ9"]
    unknown["trials"][0]["task"] = "ZZ9"
    assert any(
        "unknown task" in p
        for p in calibration_pipeline.validate_calibration_schedule(
            unknown, allow_ineligible_tasks=True
        )
    )


def test_wrong_hash_schedule_is_refused_before_any_file_is_written(tmp_path):
    sched = json.loads(json.dumps(_subset(["B01"])))
    sched["trials"][0]["scorer_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="scorer_sha256 does not match"):
        calibration_pipeline.execute_calibration(sched, tmp_path / "run", executor_mode="mock")
    assert not (tmp_path / "run").exists()


# ------------------------------------------------------------------------ spend ceiling


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"max_spend_usd": 0.0}, "max_spend_usd must be a finite number > 0"),
        ({"input_usd_per_million_tokens": float("nan")}, "finite"),
        ({"output_usd_per_million_tokens": -1.0}, "finite"),
        ({"per_trial_reserve_usd": True}, "per_trial_reserve_usd must be a number"),
        ({"per_trial_reserve_usd": 2.0}, "exceeds max_spend_usd"),
    ],
)
def test_spend_ceiling_rejects_invalid_values(overrides, expected):
    problems = _ceiling(**overrides).problems()
    assert any(expected in p for p in problems), problems
    with pytest.raises(ValueError):
        spend_control.SpendGuard(_ceiling(**overrides))


def test_spend_guard_prices_observed_usage_and_charges_reserve_when_unobservable():
    guard = spend_control.SpendGuard(_ceiling(max_spend_usd=0.1, per_trial_reserve_usd=0.04))
    guard.restore([])
    assert guard.before_attempt("t1", "t1__att01") is None
    fields, stop = guard.after_attempt(
        "t1",
        "t1__att01",
        {"usage": {"status": "observed", "input_tokens": 1000, "output_tokens": 500}},
    )
    assert stop is None and fields["charge_basis"] == "observed_usage"
    assert fields["charged_usd"] == pytest.approx(0.006)
    fields, stop = guard.after_attempt("t2", "t2__att01", {"usage": {"status": "unavailable"}})
    assert fields["charge_basis"] == "usage_unobservable_reserve_charged"
    assert fields["charged_usd"] == pytest.approx(0.04)
    assert guard.before_attempt("t3", "t3__att01") is None  # 0.046 + 0.04 <= 0.1
    guard.after_attempt("t3", "t3__att01", {"usage": {"status": "unavailable"}})
    assert guard.before_attempt("t4", "t4__att01") == spend_control.STOP_CEILING_REACHED


def test_spend_guard_stops_when_one_attempt_exceeds_its_reserve():
    guard = spend_control.SpendGuard(_ceiling(per_trial_reserve_usd=0.001))
    guard.restore([])
    _fields, stop = guard.after_attempt(
        "t1",
        "t1__att01",
        {"usage": {"status": "observed", "input_tokens": 10_000, "output_tokens": 10_000}},
    )
    assert stop == spend_control.STOP_RESERVE_EXCEEDED


def test_spend_guard_restore_charges_reserve_for_interrupted_attempts():
    guard = spend_control.SpendGuard(_ceiling(per_trial_reserve_usd=0.05))
    guard.restore(
        [
            {"event": "trial_attempt_started", "attempt_id": "a__att01"},
            {"event": "attempt_accounted", "attempt_id": "a__att01", "charged_usd": 0.01},
            {"event": "trial_attempt_started", "attempt_id": "b__att01"},  # interrupted
        ]
    )
    assert guard.spent_usd == pytest.approx(0.06)
    assert guard.reserve_charged_for_interruptions == ["b__att01"]


# --------------------------------------------------------------------- execution modes


def test_live_mode_requires_authorization_and_a_ceiling_then_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-sentinel-never-used")
    sched = calibration_pipeline.build_calibration_schedule()
    out = tmp_path / "live"
    with pytest.raises(RuntimeError, match="not authorized"):
        calibration_pipeline.execute_calibration(
            sched, out, executor_mode="live", spend_ceiling=_ceiling()
        )
    with pytest.raises(RuntimeError, match="without a ceiling is refused"):
        calibration_pipeline.execute_calibration(
            sched, out, executor_mode="live", authorize_spend=True
        )
    with pytest.raises(calibration_pipeline.LiveExecutionUnavailable) as exc:
        calibration_pipeline.execute_calibration(
            sched, out, executor_mode="live", authorize_spend=True, spend_ceiling=_ceiling()
        )
    assert [b["id"] for b in exc.value.blockers] == [
        "no_real_model_workload",
        "no_real_model_upstream_or_credential_path",
        "scorer_container_not_integrated",
    ]
    assert not out.exists()


def test_live_mode_rejects_test_hooks_invalid_ceilings_and_spend_flag_misuse(tmp_path):
    sched = calibration_pipeline.build_calibration_schedule()
    with pytest.raises(ValueError, match="neither test executors"):
        calibration_pipeline.execute_calibration(
            sched,
            tmp_path,
            executor_mode="live",
            authorize_spend=True,
            spend_ceiling=_ceiling(),
            executor=runner.make_mock_trial_executor(),
        )
    with pytest.raises(ValueError, match="Invalid spend ceiling"):
        calibration_pipeline.execute_calibration(
            sched,
            tmp_path,
            executor_mode="live",
            authorize_spend=True,
            spend_ceiling=_ceiling(max_spend_usd=-1.0),
        )
    with pytest.raises(ValueError, match="applies only to --executor live"):
        calibration_pipeline.execute_calibration(
            sched, tmp_path, executor_mode="mock", authorize_spend=True
        )
    with pytest.raises(ValueError, match="executor_mode must be one of"):
        calibration_pipeline.execute_calibration(sched, tmp_path, executor_mode="paid")


def test_live_blockers_are_computed_from_the_code_that_would_run():
    blockers = {b["id"]: b for b in calibration_pipeline.live_execution_blockers()}
    assert live_network.WORKLOAD_SCRIPT.endswith("mock_agent.py")
    assert "OPENAI_API_KEY" in live_network.HOST_SECRET_NAMES
    assert blockers["scorer_container_not_integrated"]["tasks"] == CANDIDATES


def test_docker_mock_model_refuses_a_schedule_it_cannot_score_before_touching_docker(
    tmp_path, monkeypatch
):
    def no_docker(*_a, **_k):
        raise AssertionError("docker must not be called")

    monkeypatch.setattr(live_network, "docker", no_docker)
    with pytest.raises(ValueError, match="cannot score 25 of 25"):
        calibration_pipeline.execute_calibration(
            calibration_pipeline.build_calibration_schedule(),
            tmp_path / "run",
            executor_mode="docker-mock-model",
        )
    assert not (tmp_path / "run").exists()


def test_host_scorable_mirrors_the_frozen_scorer_task_guards(tmp_path):
    # A parseable answer is needed: knowledge-pilot-v2 reads it before its task guard.
    (tmp_path / "answer.json").write_text("{}", encoding="utf-8")
    for task in [e["task_id"] for e in calibration_pipeline.audit_task_eligibility()["tasks"]]:
        for name, module in (
            ("knowledge-pilot-v2", knowledge_pilot_v2),
            ("knowledge-pilot-v2.1", knowledge_pilot_v21),
        ):
            try:
                module.score(task, tmp_path)
                accepted = True
            except ValueError as exc:
                accepted = "supports" not in str(exc)
            assert accepted == live_runner.host_scorable(task, name), (task, name)


def test_live_executor_records_unscorable_tasks_without_creating_containers(tmp_path, monkeypatch):
    def no_topology(*_a, **_k):
        raise AssertionError("no container may be created for an unscorable trial")

    monkeypatch.setattr(live_network, "TrialTopology", no_topology)
    cfg = runner.StudyExecutionConfig()
    execute = live_runner.make_docker_trial_executor()

    spec = runner.build_trial_invocation_spec(_subset(["B01"])["trials"][0], cfg)
    (tmp_path / "b").mkdir()
    out = execute(spec, 1, tmp_path / "b")["runner_record"]
    assert out["error_summary"]["primary_error"]["source_code"] == "scorer_container_required"

    def no_answer(_spec):
        raise live_runner.TrialScoringUnavailable("no mock answer")

    spec = runner.build_trial_invocation_spec(_subset(["D01"])["trials"][0], cfg)
    (tmp_path / "d").mkdir()
    out = live_runner.make_docker_trial_executor(answer_provider=no_answer)(
        spec, 1, tmp_path / "d"
    )["runner_record"]
    assert out["error_summary"]["primary_error"]["source_code"] == "mock_answer_unavailable"


def test_mock_calibration_persists_trials_through_the_stage2_ledger_and_resumes(tmp_path):
    sched = _subset(["B01"], reps=3)
    res = calibration_pipeline.execute_calibration(sched, tmp_path, executor_mode="mock")
    assert res["finalized_count"] == 3 == res["total_planned"]
    assert res["dataset_problems"] == [] and res["stopped_reason"] is None
    assert res["evidence_status"] == "synthetic_not_baseline_evidence"
    lines = _lines(tmp_path / "trial_records.jsonl")
    assert len(lines) == 3
    assert all(r["task"] == "B01" and r["arm"] == "A" and r["synthetic"] is True for r in lines)
    assert all(records.validate_record(r) == [] for r in lines)
    assert json.loads((tmp_path / "run_config.json").read_text())["synthetic"] is True
    assert (tmp_path / "plan.json").is_file() and (tmp_path / "attempts").is_dir()

    res2 = calibration_pipeline.execute_calibration(sched, tmp_path, executor_mode="mock")
    assert res2["finalized_count"] == 3
    assert len(_lines(tmp_path / "trial_records.jsonl")) == 3
    skipped = [e for e in _journal(tmp_path) if e["event"] == "trial_skipped_already_finalized"]
    assert len(skipped) == 3


def test_resume_with_a_different_schedule_or_ceiling_is_rejected(tmp_path):
    calibration_pipeline.execute_calibration(
        _subset(["B01"]), tmp_path, executor_mode="mock", spend_ceiling=_ceiling()
    )
    with pytest.raises(ValueError, match="spend ceiling differs"):
        calibration_pipeline.execute_calibration(
            _subset(["B01"]),
            tmp_path,
            executor_mode="mock",
            spend_ceiling=_ceiling(max_spend_usd=9.0),
        )
    with pytest.raises(ValueError, match="plan_sha256 differs"):
        calibration_pipeline.execute_calibration(
            _subset(["B02"]), tmp_path, executor_mode="mock", spend_ceiling=_ceiling()
        )


def test_mock_calibration_stops_fail_closed_when_the_ceiling_is_exhausted(tmp_path):
    # Each mock attempt reports 1210 input / 350 output tokens -> 0.00522 USD at these prices.
    ceiling = _ceiling(max_spend_usd=0.02, per_trial_reserve_usd=0.006)
    res = calibration_pipeline.execute_calibration(
        _subset(["B01", "B02"], reps=3), tmp_path, executor_mode="mock", spend_ceiling=ceiling
    )
    kinds = [r["outcome_kind"] for r in res["records"]]
    assert kinds == ["scored"] * 3 + ["not_executed"] * 3
    assert res["stopped_reason"] == spend_control.STOP_CEILING_REACHED
    assert res["spend"]["accounted_spend_usd"] == pytest.approx(3 * 0.00522)
    assert res["spend"]["accounted_spend_usd"] <= ceiling.max_spend_usd
    refused = [e for e in _journal(tmp_path) if e["event"] == "attempt_refused_by_controller"]
    assert len(refused) == 1 and refused[0]["reason"] == "spend_ceiling_reached"
    # Resume cannot spend past the ceiling either.
    again = calibration_pipeline.execute_calibration(
        _subset(["B01", "B02"], reps=3), tmp_path, executor_mode="mock", spend_ceiling=ceiling
    )
    assert again["finalized_count"] == 3


def test_interrupted_attempt_is_charged_the_reserve_and_resume_completes(tmp_path):
    sched = _subset(["B01"], reps=2)
    first_id = sched["trials"][0]["trial_id"]
    res = calibration_pipeline.execute_calibration(
        sched,
        tmp_path,
        executor_mode="mock",
        spend_ceiling=_ceiling(),
        executor=runner.make_mock_trial_executor(interrupt_on={(first_id, 1)}),
    )
    assert res["interrupted"] is True and res["finalized_count"] == 0
    res = calibration_pipeline.execute_calibration(
        sched, tmp_path, executor_mode="mock", spend_ceiling=_ceiling()
    )
    assert res["finalized_count"] == 2 and res["dataset_problems"] == []
    assert res["spend"]["reserve_charged_for_interrupted_attempts"] == [f"{first_id}__att01"]
    # Mock usage grows by 10 input tokens per attempt index: 1220 + 1210 input, 350 output each.
    assert res["spend"]["accounted_spend_usd"] == pytest.approx(0.05 + 0.00524 + 0.00522)


def test_duplicate_and_truncated_record_lines_are_quarantined_on_resume(tmp_path):
    sched = _subset(["B01"], reps=2)
    calibration_pipeline.execute_calibration(sched, tmp_path, executor_mode="mock")
    path = tmp_path / "trial_records.jsonl"
    text = path.read_text(encoding="utf-8")
    path.write_text(text + text.splitlines()[0] + "\n" + '{"trial_id": "cal-A', encoding="utf-8")
    res = calibration_pipeline.execute_calibration(sched, tmp_path, executor_mode="mock")
    assert res["finalized_count"] == 2 and res["dataset_problems"] == []
    assert len(_lines(path)) == 2
    events = [e["event"] for e in _journal(tmp_path)]
    assert "duplicate_trial_record_detected" in events
    assert "corrupt_jsonl_line_quarantined" in events


def test_candidate_failures_are_not_retried_and_infrastructure_failures_are(tmp_path):
    sched = _subset(["B01"], reps=2)
    t1, t2 = (t["trial_id"] for t in sched["trials"])
    res = calibration_pipeline.execute_calibration(
        sched,
        tmp_path,
        executor_mode="mock",
        executor=runner.make_mock_trial_executor(
            fail_trial_attempts={
                (t1, 1): "candidate_failure",
                (t2, 1): "infrastructure_failure",
            }
        ),
    )
    by_id = {r["trial_id"]: r for r in res["records"]}
    assert by_id[t1]["outcome_kind"] == "candidate_failure" and by_id[t1]["score"] == 0.0
    assert by_id[t2]["outcome_kind"] == "scored"
    started = [e for e in _journal(tmp_path) if e["event"] == "trial_attempt_started"]
    assert [e["attempt_id"] for e in started] == [f"{t1}__att01", f"{t2}__att01", f"{t2}__att02"]
    assert started[-1]["retry_of_attempt_id"] == f"{t2}__att01"


def test_refused_retry_commits_the_preceding_infrastructure_failure(tmp_path):
    sched = _subset(["B01"])
    tid = sched["trials"][0]["trial_id"]
    # After the failed attempt (0.00522 USD) a second 0.05 reserve no longer fits under 0.054.
    res = calibration_pipeline.execute_calibration(
        sched,
        tmp_path,
        executor_mode="mock",
        spend_ceiling=_ceiling(max_spend_usd=0.054, per_trial_reserve_usd=0.05),
        executor=runner.make_mock_trial_executor(
            fail_trial_attempts={(tid, 1): "infrastructure_failure"}
        ),
    )
    assert res["stopped_reason"] == spend_control.STOP_CEILING_REACHED
    rec = res["records"][0]
    assert rec["outcome_kind"] == "infrastructure_failure"
    assert _lines(tmp_path / "trial_records.jsonl")[0]["trial_id"] == tid


def test_schedule_failure_rate_stop_condition_is_enforced(tmp_path):
    sched = _subset(["B01", "B02", "B03"], reps=1)
    ids = [t["trial_id"] for t in sched["trials"]]
    res = calibration_pipeline.execute_calibration(
        sched,
        tmp_path,
        executor_mode="mock",
        executor=runner.make_mock_trial_executor(
            fail_trial_attempts={
                (ids[0], 1): "infrastructure_failure",
                (ids[0], 2): "infrastructure_failure",
            }
        ),
    )
    # 0.20 x 3 planned trials = 0.6: one trial failing after its retry exceeds the allowance.
    assert res["stopped_reason"] == "max_infrastructure_failure_rate_exceeded"
    assert [r["outcome_kind"] for r in res["records"]] == [
        "infrastructure_failure",
        "not_executed",
        "not_executed",
    ]


# ------------------------------------------------------------------ evidence separation


def test_baseline_evaluation_refuses_synthetic_and_unverifiable_records(tmp_path):
    calibration_pipeline.execute_calibration(
        _subset(["B01"], reps=3), tmp_path, executor_mode="mock"
    )
    recs = _lines(tmp_path / "trial_records.jsonl")
    with pytest.raises(calibration_pipeline.SyntheticEvidenceError, match="synthetic"):
        calibration_pipeline.evaluate_baseline_difficulty(recs)
    flipped = [dict(r, synthetic=False) for r in recs]
    # Editing the JSONL flag is not enough while the run directory says synthetic.
    (tmp_path / "trial_records.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in flipped), encoding="utf-8"
    )
    with pytest.raises(calibration_pipeline.SyntheticEvidenceError, match="run_config.json"):
        calibration_pipeline.load_baseline_evidence(tmp_path / "trial_records.jsonl")
    (tmp_path / "run_config.json").unlink()
    with pytest.raises(calibration_pipeline.SyntheticEvidenceError, match="calibration_run"):
        calibration_pipeline.load_baseline_evidence(tmp_path / "trial_records.jsonl")
    # Missing flag or schema-invalid records are not evidence either.
    bare = [{k: v for k, v in r.items() if k != "synthetic"} for r in recs]
    with pytest.raises(calibration_pipeline.SyntheticEvidenceError):
        calibration_pipeline.evaluate_baseline_difficulty(bare)
    with pytest.raises(calibration_pipeline.SyntheticEvidenceError, match="schema"):
        calibration_pipeline.evaluate_baseline_difficulty(
            [
                {
                    "arm": "A",
                    "task": "B01",
                    "outcome_kind": "scored",
                    "score": 0.5,
                    "synthetic": False,
                }
            ]
        )
    labelled = calibration_pipeline.evaluate_baseline_difficulty(recs, allow_synthetic=True)
    assert labelled["baseline_evidence"] is False
    assert labelled["evidence_status"] == "synthetic_not_baseline_evidence"


def test_evaluate_baseline_difficulty_evaluates_arm_a_and_identifies_uncertainty():
    rows = [
        ("A", "T01", "scored", 0.15),
        ("A", "T01", "scored", 0.25),
        ("A", "T01", "scored", 0.35),
        ("B", "T01", "scored", 1.00),  # Arm B must be ignored
        ("A", "T02", "candidate_failure", 0.0),
        ("A", "T02", "candidate_failure", 0.0),
        ("A", "T02", "candidate_failure", 0.0),
        ("A", "T03", "scored", 1.0),
        ("A", "T03", "scored", 1.0),
        ("A", "T03", "scored", 1.0),
        ("A", "T04", "scored", 0.55),
        ("A", "T04", "scored", 0.60),
        ("A", "T04", "scored", 0.65),
    ]
    recs = [{"arm": a, "task": t, "outcome_kind": k, "score": s} for a, t, k, s in rows]
    res = calibration_pipeline.evaluate_baseline_difficulty(recs, allow_synthetic=True)
    assert res["evaluated_tasks"] == 4 and res["baseline_evidence"] is False
    t1, t2, t3, t4 = (res["tasks"][k] for k in ("T01", "T02", "T03", "T04"))
    assert (t1["mean_score"], t1["classification"]) == (0.25, "candidate_in_range")
    assert t1["uncertainty_status"] == "inconclusive_sample_size_limited"
    assert (t2["mean_score"], t2["classification"]) == (0.0, "floor")
    assert (t3["classification"], t3["full_correct_rate"]) == ("ceiling", 1.0)
    assert (t4["mean_score"], t4["uncertainty_status"]) == (0.60, "provisional_small_sample")


# --------------------------------------------------------------------- readiness / gates


def test_pilot_specification_requires_explicit_spend_authorization():
    spec = calibration_pipeline.build_pilot_specification()
    assert spec["status"] == "NOT_AUTHORIZED_FOR_EXECUTION"
    assert spec["authorized_budget_usd"] is None
    assert spec["task_count"] == 10 and spec["total_trials"] == 90
    assert spec["arms"] == ["A", "B", "C"]
    assert spec["model_identity"] == "gpt-6-luna"


def test_readiness_distinguishes_mock_live_authorized_and_confirmatory():
    gates = calibration_pipeline.evaluate_readiness_gates(has_docker=True)
    assert gates["mock_infrastructure_ready"] is True
    assert gates["live_calibration_ready"] is False
    statuses = {k: v["status"] for k, v in gates["execution_readiness"].items()}
    assert statuses == {
        "mock_ready": "READY",
        "live_executor_ready": "NOT_READY",
        "calibration_authorized": "NOT_AUTHORIZED",
        "confirmatory_ready": "NOT_READY",
    }
    by_id = {g["gate_id"]: g for g in gates["gates"]}
    assert by_id["gate_1_offline_research_infrastructure"]["status"] == "PASS"
    assert by_id["gate_2_docker_experiment_infrastructure"]["status"] == "PASS"
    assert "no_real_model_workload" in by_id["gate_3_calibration_execution"]["remaining_blockers"]
    for gate in ("gate_3_calibration_execution", "gate_4_pilot_execution"):
        assert by_id[gate]["status"] == "BLOCKED"
    assert by_id["gate_5_confirmatory_experiment_eligibility"]["status"] == "BLOCKED"


def test_confirmatory_threshold_is_unreachable_with_the_current_catalogue():
    f = calibration_pipeline.confirmatory_feasibility()
    declared = manifest.build_manifest()["confirmatory_task_rule"]["minimum_tasks"]
    assert f["preregistered_minimum_tasks"] == declared == 30
    assert f["threshold_modified"] is False
    assert (f["catalogue_tasks"], f["quarantined_tasks"], f["non_quarantined_tasks"]) == (31, 6, 25)
    assert (f["current_s1_tasks"], f["scheduled_calibration_tasks"]) == (0, 25)
    # S2 controls can never become S1, so the 17 controls add nothing to the core.
    assert (f["control_tasks_never_s1"], f["recalibration_tasks"]) == (17, 8)
    assert f["max_s1_after_calibration_best_case"] == 8
    assert f["shortfall_after_calibration_best_case"] == 22
    assert f["max_s1_if_q_scorers_are_also_revised"] == 14
    assert f["min_new_target_tasks_required"] == 16
    assert f["reachable_with_current_catalogue"] is False


# ------------------------------------------------------------------------------- CLI


def test_cli_calibration_pipeline_and_readiness_gates(tmp_path):
    assert cli.main(["calibration-pipeline", "--out-dir", str(tmp_path)]) == 0
    for name in (
        "calibration_eligibility_report.json",
        "calibration_schedule.json",
        "pilot_specification.json",
    ):
        assert (tmp_path / name).is_file()
    gates_out = tmp_path / "gates.json"
    assert cli.main(["readiness-gates", "--out", str(gates_out)]) == 0
    gates = json.loads(gates_out.read_text(encoding="utf-8"))
    assert gates["mock_infrastructure_ready"] is True and gates["live_calibration_ready"] is False


def test_cli_execute_calibration_exit_codes_and_evidence_refusal(tmp_path, capsys):
    sched_path = tmp_path / "mini.json"
    sched_path.write_text(json.dumps(_subset(["B01", "B02"])), encoding="utf-8")
    base = ["execute-calibration", "--schedule", str(sched_path)]
    ceiling = [
        "--max-spend-usd",
        "1",
        "--input-usd-per-mtok",
        "2",
        "--output-usd-per-mtok",
        "8",
        "--per-trial-reserve-usd",
        "0.05",
    ]
    assert cli.main(base + ["--out-dir", str(tmp_path / "x")]) == 2  # no executor chosen
    assert cli.main(base + ["--out-dir", str(tmp_path / "x"), "--executor", "live"]) == 2
    assert (
        cli.main(
            base + ["--out-dir", str(tmp_path / "x"), "--executor", "live", "--authorize-spend"]
        )
        == 2
    )
    partial = ["--max-spend-usd", "1"]
    assert cli.main(base + ["--out-dir", str(tmp_path / "x"), "--executor", "mock", *partial]) == 2
    capsys.readouterr()
    live = base + ["--out-dir", str(tmp_path / "x"), "--executor", "live", "--authorize-spend"]
    assert cli.main(live + ceiling) == 3
    assert "UNAVAILABLE" in capsys.readouterr().out
    assert not (tmp_path / "x").exists()

    run_dir = tmp_path / "run"
    assert cli.main(base + ["--out-dir", str(run_dir), "--mock", *ceiling]) == 0
    records_path = str(run_dir / "trial_records.jsonl")
    eval_out = tmp_path / "eval.json"
    assert cli.main(["evaluate-baseline", "--records", records_path, "--out", str(eval_out)]) == 2
    assert not eval_out.exists()
    assert (
        cli.main(
            [
                "evaluate-calibration",
                "--records",
                records_path,
                "--out",
                str(eval_out),
                "--allow-synthetic",
            ]
        )
        == 0
    )
    rep = json.loads(eval_out.read_text(encoding="utf-8"))
    assert rep["baseline_evidence"] is False and set(rep["tasks"]) == {"B01", "B02"}
