"""Tests for the Stage 3B Benchmark Expansion (30 tasks, offline scorer validation, integration).

All tests in this module are deterministic and offline (no Docker daemon or network access needed).
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.codex_r import run_simple
from benchmarks.codex_r.studies.stage2_validity_v1 import (
    calibration_pipeline,
    design,
    legacy_executor,
    records,
    runner,
    scorer_bindings,
)
from benchmarks.codex_r.studies.stage2_validity_v1 import (
    manifest as stage2_manifest,
)
from benchmarks.codex_r.studies.stage3b_expansion import build, suite

STAGE3B = suite.STAGE3B
EXPECTED_TASKS = [
    "XA01",
    "XA02",
    "XA03",
    "XA04",
    "XA05",
    "XA06",
    "XG01",
    "XG02",
    "XG03",
    "XG04",
    "XG05",
    "XM01",
    "XM02",
    "XM03",
    "XM04",
    "XP01",
    "XP02",
    "XP03",
    "XP04",
    "XP05",
    "XR01",
    "XR02",
    "XR03",
    "XR04",
    "XR05",
    "XV01",
    "XV02",
    "XV03",
    "XV04",
    "XV05",
]
EXPECTED_TARGET_CANDIDATES = [
    "XA06",
    "XM01",
    "XM03",
    "XM04",
    "XP04",
    "XR01",
    "XR04",
    "XR05",
    "XV01",
    "XV02",
    "XV04",
    "XV05",
]
EXPECTED_CONTROLS = [
    "XA01",
    "XA02",
    "XA03",
    "XA04",
    "XA05",
    "XG01",
    "XG02",
    "XG03",
    "XG05",
    "XM02",
    "XP01",
    "XP02",
    "XR03",
]
EXPECTED_EXPLORATORY = ["XG04", "XP03", "XP05", "XR02", "XV03"]
REQUIRED_DOCS = (
    "STAGE3B_REPORT.md",
    "TASK_BLUEPRINT.md",
    "TASK_CATALOG.md",
    "SCORER_VALIDATION.md",
    "REFERENCE_EVIDENCE.md",
    "CALIBRATION_PLAN.md",
    "INTEGRATION_NOTES.md",
)


def test_committed_manifest_and_catalog_are_in_sync():
    assert build.main(["--check"]) == 0


def test_thirty_tasks_across_six_families_and_classifications():
    assert suite.task_ids() == EXPECTED_TASKS
    catalog = json.loads(build.CATALOG.read_text(encoding="utf-8"))
    assert catalog["catalog_version"] == build.CATALOG_VERSION
    assert catalog["pool"] == build.POOL
    tasks = catalog["tasks"]
    assert len(tasks) == 30

    by_class: dict[str, list[str]] = {"target_candidate": [], "control": [], "exploratory": []}
    for entry in tasks:
        tid = entry["id"]
        derived = build.derived_classification(entry)
        assert entry["mcp_relevance"]["classification"] == derived
        by_class[derived].append(tid)
        # Never auto-promoted to S1/S2/RC/Q before real Arm-A calibration
        assert entry["pool"]["stratum"] is None
        assert entry["pool"]["confirmatory_eligible"] is False
        assert entry["pool"]["calibration_eligible"] is True
        assert not any("scorer validation gate" in b for b in entry["pool"]["blockers"])

    assert sorted(by_class["target_candidate"]) == EXPECTED_TARGET_CANDIDATES
    assert sorted(by_class["control"]) == EXPECTED_CONTROLS
    assert sorted(by_class["exploratory"]) == EXPECTED_EXPLORATORY


def test_independence_clusters_and_registry_traceability():
    registry = {s["id"] for s in json.loads(build.REGISTRY.read_text(encoding="utf-8"))["tasks"]}
    catalog = json.loads(build.CATALOG.read_text(encoding="utf-8"))
    clusters: dict[str, list[str]] = {}
    for entry in catalog["tasks"]:
        tid = entry["id"]
        assert entry["source_specs"], tid
        for spec_id in entry["source_specs"]:
            assert spec_id in registry, (tid, spec_id)
        ind = entry["independence"]
        assert isinstance(ind["cluster"], str) and ind["cluster"]
        assert isinstance(ind["shared_with"], list)
        clusters.setdefault(ind["cluster"], []).append(tid)
        if tid in ("XM01", "XM04"):
            assert ind["cluster"] == "bioconductor-workflows"
    assert len(clusters) == 23
    assert sorted(clusters["bioconductor-workflows"]) == ["XM01", "XM04"]
    for members in clusters.values():
        for tid in members:
            entry = next(e for e in catalog["tasks"] if e["id"] == tid)
            for peer in entry["independence"]["shared_with"]:
                assert peer in members and peer != tid, (tid, peer)


def test_validation_report_completeness_and_adversarial_controls():
    report = json.loads(build.VALIDATION.read_text(encoding="utf-8"))
    assert report["benchmark"] == suite.BENCHMARK_ID
    assert report["api_calls"] == 0
    assert report["gate"] == "passed"
    assert [t["task"] for t in report["tasks"]] == EXPECTED_TASKS

    catalog_by_id = {
        t["id"]: t for t in json.loads(build.CATALOG.read_text(encoding="utf-8"))["tasks"]
    }
    for task_rep in report["tasks"]:
        tid = task_rep["task"]
        cat_entry = catalog_by_id[tid]
        assert task_rep["gate"] == "passed", tid
        assert task_rep["problems"] == [], tid
        assert task_rep["task_sha256"] == cat_entry["hashes"]["task_sha256"]
        assert task_rep["scorer_sha256"] == cat_entry["hashes"]["scorer_sha256"]
        assert build.control_problems(tid) == []

        results = task_rep["results"]
        assert results["reference"]["fully_correct"] is True
        assert results["reference_repeat"]["fully_correct"] is True
        assert results["reference"]["passed"] == task_rep["checks"]
        assert results["empty"]["passed"] == 0
        assert results["syntax_error"]["status"] == "candidate_error"
        assert results["forged_result"]["passed"] <= results["reference"]["passed"]

        for ctrl in build.controls_of(tid):
            res = results[ctrl["name"]]
            if ctrl["expect"] == "pass":
                assert res["fully_correct"] is True, (tid, ctrl["name"])
            else:
                assert res["fully_correct"] is False, (tid, ctrl["name"])


def test_public_workspace_export_omits_private_metadata_and_verifiers(tmp_path):
    ws = tmp_path / "candidate"
    exported = suite.prepare("XM04", ws)
    assert exported["task"] == "XM04"
    assert (ws / "TASK.md").is_file()
    assert (ws / "renv.lock").is_file()
    assert (ws / "data" / "tx_counts.csv").is_file()
    assert not (ws / "task.json").exists()
    assert not any(p.suffix == ".R" for p in ws.rglob("*"))

    sealed_dir = tmp_path / "sealed"
    (ws / "solution.R").write_text("summarize_tx <- function(...) NULL\n", encoding="utf-8")
    hashes = suite.seal_artifacts("XM04", ws, sealed_dir)
    assert list(hashes) == ["solution.R"]
    assert (sealed_dir / "solution.R").is_file()

    cmd = suite.docker_command("sha256:" + "a" * 64, sealed_dir, "XM04")
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "none"
    assert "--read-only" in cmd
    assert "--user" in cmd and cmd[cmd.index("--user") + 1] == "65534:65534"


def test_run_simple_and_stage2_integration(tmp_path):
    assert run_simple.expand_tasks(["stage3b-pool"]) == EXPECTED_TASKS
    for tid in EXPECTED_TASKS:
        task_suite, toolset, allowed = run_simple.suite_for(tid)
        assert task_suite is suite
        assert toolset == "consolidated"
        assert "get_function_docs" in allowed
        meta = runner._task_and_scorer_meta(tid)
        assert meta["scorer_version"] == scorer_bindings.STAGE3B_SCORER
        assert len(meta["task_sha256"]) == 64 and len(meta["scorer_sha256"]) == 64
        iso = legacy_executor.scorer_isolation(tid)
        assert iso["exposed_files"] == []

    assert run_simple.default_image_refs(["XA01"])["scorer"] == "codex-r-benchmark:pilot"
    assert run_simple.default_image_refs(["XM01"])["scorer"] == "codex-r-benchmark:pilot-bioc"
    assert (
        run_simple.default_image_refs(["XM04"])["executor"]
        == "rkmcp-codex-runtime:codex-0.163.0-bioc"
    )

    # Historical 31-task catalogue and frozen digests remain untouched
    elig = calibration_pipeline.audit_task_eligibility()
    assert elig["total_benchmark_tasks"] == 31
    assert elig["confirmatory_eligible_count"] == 0
    recorded = json.loads(
        (Path(stage2_manifest.STUDY_DIR) / "frozen_evidence_digests.json").read_text("utf-8")
    )
    assert stage2_manifest.verify_frozen(recorded) == []

    # Stage 3B calibration schedule & mock execution
    assert calibration_pipeline.stage3b_calibration_candidate_tasks() == EXPECTED_TASKS
    sched = calibration_pipeline.build_stage3b_calibration_schedule()
    assert sched["study_id"] == "stage3b_baseline_calibration"
    assert sched["candidate_task_count"] == 30
    assert sched["total_planned_trials"] == 90
    assert sched["candidates_that_can_enter_s1"] == EXPECTED_TARGET_CANDIDATES
    assert calibration_pipeline.validate_calibration_schedule(sched) == []
    assert calibration_pipeline.live_execution_blockers(sched) == []

    mini = calibration_pipeline.build_stage3b_calibration_schedule(
        tasks=["XA06", "XM01", "XM04"], repetitions=1
    )
    res = calibration_pipeline.execute_calibration(mini, tmp_path / "cal", executor_mode="mock")
    assert res["finalized_count"] == 3
    assert res["dataset_problems"] == []
    assert all(records.validate_record(r) == [] for r in res["records"])

    # Pinned 3-arm plan with Stage 3B tasks
    plan = design.build_plan(["XA06", "XM03", "XV01"], ("A", "B", "C"), 2, 20261029, "stage3b_test")
    pinned = legacy_executor.pin_plan_identities(plan)
    assert design.verify_plan(pinned) == []
    assert legacy_executor.plan_identity_problems(pinned) == []


def test_required_stage3b_research_documents_exist():
    for name in REQUIRED_DOCS:
        path = STAGE3B / name
        assert path.is_file(), f"Missing required Stage 3B document: {name}"
        assert len(path.read_text(encoding="utf-8").strip()) > 200, name
