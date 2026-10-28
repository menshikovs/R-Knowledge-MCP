"""Stage 2.7 calibration through the real Docker execution path with a local mock model API.

Each test drives ``calibration_pipeline.execute_calibration(executor_mode="docker-mock-model")``,
which runs ``live_runner.execute_live_study``: frozen-evidence check, Docker ``--internal``
topology, egress gateway, canary, fresh workspace, mock agent, mock model server, host scoring
and verified teardown. No real model, no credentials, no network beyond local containers.

The calibration candidates (S2) need the R scorer container, which this path does not run, so
the schedules here use D01 (host-scorable, deterministic mock answer) with
``allow_ineligible_tasks=True``. That flag exists for these infrastructure tests only.
"""

from __future__ import annotations

import json
import os

import pytest

from benchmarks.codex_r.studies.stage2_validity_v1 import (
    calibration_pipeline,
    live_network,
    live_runner,
    runner,
    spend_control,
)

SENTINEL = "sk-stage27-sentinel-must-not-leak"
_STATUS = None


@pytest.fixture
def docker_ready(monkeypatch):
    global _STATUS
    if _STATUS is None:
        _STATUS = live_network.docker_status()
    if not _STATUS["ready"]:
        pytest.skip(f"live Docker verification unavailable: {_STATUS['reason']}")
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    return _STATUS


class _Capture:
    def __init__(self, inner):
        self.inner = inner
        self.calls: list[tuple[str, int]] = []

    def __call__(self, spec, attempt_index, workspace_dir):
        self.calls.append((spec["trial_id"], attempt_index))
        return self.inner(spec, attempt_index, workspace_dir)


def _settings(name):
    return live_runner.LiveExecutorSettings(run_label=f"s27-{name}-{os.getpid()}")


def _schedule(reps):
    return calibration_pipeline.build_calibration_schedule(tasks=["D01"], repetitions=reps)


def _run(schedule, run_dir, settings, executor, ceiling=None):
    return calibration_pipeline.execute_calibration(
        schedule,
        run_dir,
        executor_mode="docker-mock-model",
        spend_ceiling=ceiling,
        executor=executor,
        docker_settings=settings,
        allow_ineligible_tasks=True,
    )


def _journal(run_dir):
    text = (run_dir / "ledger_journal.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def _attempt(run_dir, attempt_id):
    return json.loads((run_dir / "attempts" / f"{attempt_id}.json").read_text(encoding="utf-8"))


def _assert_clean(result):
    assert result["resource_cleanup"]["remaining_after"] == {"containers": [], "networks": []}


@pytest.mark.docker
def test_docker_calibration_scores_bills_usage_and_stops_at_the_spend_ceiling(
    docker_ready, tmp_path
):
    settings = _settings("budget")
    capture = _Capture(live_runner.make_docker_trial_executor(settings))
    # Mock model usage is ~1035 input / 42 output tokens -> ~0.0108 USD per trial at 10/10.
    ceiling = spend_control.SpendCeiling(0.04, 10.0, 10.0, 0.02)
    res = _run(_schedule(3), tmp_path / "run", settings, capture, ceiling)

    kinds = [r["outcome_kind"] for r in res["records"]]
    assert kinds == ["scored", "scored", "not_executed"]
    assert res["stopped_reason"] == spend_control.STOP_CEILING_REACHED
    assert len(capture.calls) == 2  # the third attempt was refused before any container
    assert all(r["synthetic"] is True for r in res["records"])
    for rec in res["records"][:2]:
        assert rec["score"] == 1.0 and rec["violations"] == []
        assert rec["usage"]["status"] == "observed"
    assert 0 < res["spend"]["accounted_spend_usd"] <= ceiling.max_spend_usd
    assert res["dataset_problems"] == []
    first = _attempt(tmp_path / "run", f"{res['records'][0]['trial_id']}__att01")
    evidence = first["runner_record"]["live_evidence"]
    assert evidence["canary"]["ok"] is True and evidence["enforcement"]["ok"] is True
    assert evidence["host_secret_names_in_candidate"] == []
    assert SENTINEL not in json.dumps(first)
    _assert_clean(res)
    with pytest.raises(calibration_pipeline.SyntheticEvidenceError):
        calibration_pipeline.load_baseline_evidence(tmp_path / "run" / "trial_records.jsonl")


@pytest.mark.docker
def test_docker_calibration_partial_usage_telemetry_is_charged_the_full_reserve(
    docker_ready, tmp_path
):
    settings = _settings("partial")
    schedule = _schedule(1)
    tid = schedule["trials"][0]["trial_id"]
    executor = live_runner.make_docker_trial_executor(
        settings, topology_faults={(tid, 1): "model_usage_partial"}
    )
    ceiling = spend_control.SpendCeiling(1.0, 10.0, 10.0, 0.25)
    res = _run(schedule, tmp_path / "run", settings, executor, ceiling)

    rec = res["records"][0]
    assert rec["outcome_kind"] == "scored"
    assert rec["usage"] == {"status": "unavailable"}  # output_tokens missing upstream
    raw = _attempt(tmp_path / "run", f"{tid}__att01")["runner_record"]
    assert "output_tokens" not in raw["usage"] and "input_tokens" in raw["usage"]
    accounted = [e for e in _journal(tmp_path / "run") if e["event"] == "attempt_accounted"]
    assert accounted[0]["charge_basis"] == "usage_unobservable_reserve_charged"
    assert res["spend"]["accounted_spend_usd"] == pytest.approx(0.25)
    _assert_clean(res)


@pytest.mark.docker
def test_docker_calibration_retries_infrastructure_but_not_candidate_failures(
    docker_ready, tmp_path
):
    settings = _settings("fail")
    schedule = _schedule(2)
    t1, t2 = (t["trial_id"] for t in schedule["trials"])
    capture = _Capture(
        live_runner.make_docker_trial_executor(
            settings,
            topology_faults={(t1, 1): "gateway_policy_invalid"},
            answer_provider=lambda s: (
                None if s["trial_id"] == t2 else live_runner.mock_gold_answer(s["task"])
            ),
        )
    )
    res = _run(schedule, tmp_path / "run", settings, capture)

    by_id = {r["trial_id"]: r for r in res["records"]}
    assert by_id[t1]["outcome_kind"] == "scored" and by_id[t1]["score"] == 1.0
    assert by_id[t2]["outcome_kind"] == "candidate_failure" and by_id[t2]["score"] == 0.0
    assert capture.calls == [(t1, 1), (t1, 2), (t2, 1)]
    first = _attempt(tmp_path / "run", f"{t1}__att01")["runner_record"]
    assert first["error_summary"]["primary_error"]["category"] == "isolation"
    journal = _journal(tmp_path / "run")
    retry = [e for e in journal if e["event"] == "trial_attempt_infra_failure_retrying"]
    assert [e["trial_id"] for e in retry] == [t1]
    started = {e["attempt_id"]: e for e in journal if e["event"] == "trial_attempt_started"}
    assert started[f"{t1}__att02"]["retry_of_attempt_id"] == f"{t1}__att01"
    assert res["stopped_reason"] is None and res["dataset_problems"] == []
    _assert_clean(res)


@pytest.mark.docker
def test_docker_calibration_detects_scorer_change_at_execution_and_stops(
    docker_ready, tmp_path, monkeypatch
):
    settings = _settings("hash")
    inner = live_runner.make_docker_trial_executor(settings)
    original = runner._task_and_scorer_meta

    def scorer_changed_mid_run(spec, attempt_index, workspace_dir):
        def altered(task):
            return dict(original(task), scorer_sha256="f" * 64)

        monkeypatch.setattr(runner, "_task_and_scorer_meta", altered)
        try:
            return inner(spec, attempt_index, workspace_dir)
        finally:
            monkeypatch.setattr(runner, "_task_and_scorer_meta", original)

    res = _run(_schedule(2), tmp_path / "run", settings, scorer_changed_mid_run)

    first, second = res["records"]
    assert first["outcome_kind"] == "infrastructure_failure"
    assert "scorer_hash_mismatch" in {v["code"] for v in first["violations"]}
    assert second["outcome_kind"] == "not_executed"
    assert res["stopped_reason"].startswith("invalidating_protocol_violation")
    raw = _attempt(tmp_path / "run", f"{first['trial_id']}__att01")["runner_record"]
    assert raw["error_summary"]["primary_error"]["source_code"] == "task_or_scorer_hash_mismatch"
    _assert_clean(res)


@pytest.mark.docker
def test_docker_calibration_interruption_resume_and_duplicate_lines(docker_ready, tmp_path):
    settings = _settings("resume")
    schedule = _schedule(2)
    t1, t2 = (t["trial_id"] for t in schedule["trials"])
    ceiling = spend_control.SpendCeiling(1.0, 10.0, 10.0, 0.1)
    run_dir = tmp_path / "run"

    interrupted = _run(
        schedule,
        run_dir,
        settings,
        live_runner.make_docker_trial_executor(settings, interrupt_before_workload={(t1, 1)}),
        ceiling,
    )
    assert interrupted["interrupted"] is True and interrupted["finalized_count"] == 0
    _assert_clean(interrupted)

    capture = _Capture(live_runner.make_docker_trial_executor(settings))
    resumed = _run(schedule, run_dir, settings, capture, ceiling)
    assert capture.calls == [(t1, 2), (t2, 1)]
    assert [r["outcome_kind"] for r in resumed["records"]] == ["scored", "scored"]
    assert resumed["spend"]["reserve_charged_for_interrupted_attempts"] == [f"{t1}__att01"]
    assert resumed["spend"]["accounted_spend_usd"] > 0.1
    _assert_clean(resumed)

    records_path = run_dir / "trial_records.jsonl"
    lines = records_path.read_text(encoding="utf-8").splitlines()
    records_path.write_text("\n".join(lines + [lines[0]]) + "\n", encoding="utf-8")
    capture = _Capture(live_runner.make_docker_trial_executor(settings))
    again = _run(schedule, run_dir, settings, capture, ceiling)
    assert capture.calls == []
    assert again["finalized_count"] == 2 and again["dataset_problems"] == []
    assert len(records_path.read_text(encoding="utf-8").splitlines()) == 2
    assert "duplicate_trial_record_detected" in {e["event"] for e in _journal(run_dir)}
