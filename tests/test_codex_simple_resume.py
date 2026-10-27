import pytest

from benchmarks.codex_r import run_simple as simple


def test_full_pilot_is_only_the_recorded_verified_set():
    tasks = simple.expand_tasks(None, pilot="full")
    assert tasks == [
        "H01",
        "H04",
        "H10",
        "B01",
        "B02",
        "B03",
        "C01",
        "C02",
        "C03",
        "C04",
        "C05",
        "D01",
        "D02",
        "D03",
        "E01",
        "E02",
        "E03",
        "E04",
        "E05",
    ]
    assert len(simple.planned_trials(tasks, ["without-mcp", "with-mcp"], 1)) == 38
    assert simple.MODEL == "gpt-6-luna"
    assert all(simple.suite_for(task)[1] == "consolidated" for task in tasks)


def test_resume_plan_preserves_order_and_configuration_identity():
    trials = simple.planned_trials(["C04", "D01"], ["without-mcp", "with-mcp"], 2)
    assert [trial[3] for trial in trials] == [
        "C04-A-1",
        "C04-B-1",
        "D01-A-1",
        "D01-B-1",
        "C04-A-2",
        "C04-B-2",
        "D01-A-2",
        "D01-B-2",
    ]
    saved = {"created_at_utc": "old", "effort": "medium", "source": "sha256:a"}
    current = {"created_at_utc": "new", "effort": "medium", "source": "sha256:a"}
    simple.validate_resume_configuration(saved, current)
    with pytest.raises(ValueError, match="source"):
        simple.validate_resume_configuration(saved, {**current, "source": "sha256:b"})


def test_experiment_manifest_records_reference_package_versions():
    pins = simple.experiment_package_pins(["D01", "C04", "E01", "E02", "H01"])
    assert pins["D01"]["termr"] == "1.0.1"
    assert pins["D01"]["climenu"] == "0.2.0"
    assert pins["C04"]["cranlogs"] == "2.1.1"
    assert pins["E01"]["DESeq2"] == "1.50.2"
    assert pins["E02"]["SummarizedExperiment"] == "1.40.0"
    assert pins["H01"]["dplyr"] == "1.2.1"


def test_resume_recovers_finalized_trial_and_ignores_unstarted_assignments():
    plan = [
        {"trial_id": "C04-A-1", "task": "C04", "mode": "without-mcp", "repetition": 1},
        {"trial_id": "C04-B-1", "task": "C04", "mode": "with-mcp", "repetition": 1},
    ]
    record = {
        "run_id": "run-test",
        "trial_id": "C04-A-1",
        "task": "C04",
        "mode": "without-mcp",
        "repetition": 1,
        "status": "scored",
    }
    records, completed = simple.merge_resume_records(
        {"run_id": "run-test", "trial_plan": plan, "trial_count": len(plan)},
        [],
        {record["trial_id"]: record},
        {record["trial_id"]},
    )
    assert [item["trial_id"] for item in records] == ["C04-A-1"]
    assert completed == {"C04-A-1"}


def test_resume_refuses_to_repeat_ambiguous_trial():
    plan = [
        {
            "trial_id": "C04-A-1",
            "task": "C04",
            "mode": "without-mcp",
            "repetition": 1,
        }
    ]
    with pytest.raises(ValueError, match="refusing to repeat"):
        simple.merge_resume_records(
            {"run_id": "run-test", "trial_plan": plan, "trial_count": 1},
            [],
            {},
            {"C04-A-1"},
        )
