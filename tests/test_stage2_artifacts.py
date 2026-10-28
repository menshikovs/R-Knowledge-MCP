"""Stage 2 committed artifacts: manifest, preregistration, frozen evidence, and synthetic runs.

These tests make the study reproducible and tamper-evident: the committed specification must be what
the pinned inputs regenerate, the preregistration must be a pure rendering of it, and the frozen
benchmark evidence must be byte-identical (modulo line endings) to the baseline commit.
"""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from benchmarks.codex_r import knowledge_pilot
from benchmarks.codex_r.hard import suite as hard
from benchmarks.codex_r.studies.stage2_validity_v1 import (
    calibration,
    cli,
    design,
    dryrun,
    manifest,
    power,
    prereg,
    protocol,
)

STUDY = Path(manifest.STUDY_DIR)
DOCS = (
    "README.md",
    "METHODOLOGY_AUDIT.md",
    "TASK_CALIBRATION.md",
    "SCORING_VALIDITY.md",
    "TELEMETRY_CONTRACT.md",
    "EXPERIMENT_DESIGN.md",
    "STATISTICAL_ANALYSIS_PLAN.md",
    "PREREGISTRATION.md",
    "POWER_AND_BUDGET.md",
    "REPRODUCIBILITY.md",
    "STAGE2_REPORT.md",
)


def load(name):
    return json.loads((STUDY / name).read_text(encoding="utf-8"))


def test_every_required_document_and_data_file_exists():
    for name in (
        *DOCS,
        "experiment_manifest.json",
        "frozen_evidence_digests.json",
        "task_catalog.json",
        "historical_calibration_summary.json",
        "power_simulation.json",
    ):
        assert (STUDY / name).is_file(), name


def test_committed_manifest_is_what_the_pinned_inputs_regenerate():
    assert manifest.build_manifest() == load("experiment_manifest.json")


def test_manifest_core_digest_and_draft_status():
    committed = load("experiment_manifest.json")
    core = {k: v for k, v in committed.items() if k != "core_sha256"}
    expected_sha = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
    assert committed["core_sha256"] == expected_sha
    assert committed["status"].startswith("DRAFT")
    assert committed["randomization"]["seed"] is None  # derived only at registration
    assert committed["budget"]["model_spend_limit"] is None
    assert committed["confirmatory_task_rule"]["current_eligible_tasks"] == 0


def test_preregistration_is_a_pure_rendering_of_the_manifest():
    text = (STUDY / "PREREGISTRATION.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert text == prereg.render(load("experiment_manifest.json"))
    assert "not yet derived" in text and "DRAFT" in text


def test_arm_instruction_digests_in_the_manifest_match_the_protocol():
    committed = load("experiment_manifest.json")
    base = protocol.base_instructions()
    assert committed["shared_instruction_sha256"] == protocol.sha256_text(base)
    assert (
        committed["arms"]["A"]["instructions_sha256"]
        == committed["arms"]["B"]["instructions_sha256"]
    )
    assert committed["arms"]["C"]["instructions_sha256"] == protocol.sha256_text(
        base + protocol.ENCOURAGEMENT
    )


def test_pilot_tasks_are_pinned_by_content_and_exist_in_the_catalogue():
    committed = load("experiment_manifest.json")
    catalogue = {t["task"] for t in load("task_catalog.json")["tasks"]}
    for entry in committed["pilot_tasks"]:
        assert entry["task"] in catalogue and entry["files"]
        for relative, digest in entry["files"].items():
            assert manifest.digest(manifest.ROOT / relative) == digest


def test_seed_is_derived_from_the_registration_commit_only():
    a = manifest.derive_seed("a" * 64, "c" * 40)
    assert a == manifest.derive_seed("a" * 64, "c" * 40)
    assert a != manifest.derive_seed("a" * 64, "d" * 40) != manifest.derive_seed("b" * 64, "c" * 40)


# --------------------------------------------------------- frozen evidence


def test_frozen_benchmark_evidence_is_unchanged():
    recorded = load("frozen_evidence_digests.json")
    assert recorded["baseline_commit"] == manifest.BASELINE_COMMIT
    assert len(recorded["files"]) > 200
    assert manifest.verify_frozen(recorded) == []


def test_frozen_check_notices_a_modified_or_missing_file():
    recorded = load("frozen_evidence_digests.json")
    name = next(n for n in recorded["files"] if n.endswith("knowledge_pilot_v21.py"))
    tampered = {**recorded, "files": {**recorded["files"], name: "0" * 64}}
    assert manifest.verify_frozen(tampered) == [f"changed: {name}"]
    missing = {**recorded, "files": {**recorded["files"], "benchmarks/codex_r/nope.txt": "0" * 64}}
    assert "missing: benchmarks/codex_r/nope.txt" in manifest.verify_frozen(missing)


def test_frozen_set_covers_scorers_verifiers_tasks_and_reports():
    names = set(load("frozen_evidence_digests.json")["files"])
    for needle in (
        "benchmarks/codex_r/knowledge_pilot_v21.py",
        "benchmarks/codex_r/hard/verifier/H10.R",
        "benchmarks/codex_r/knowledge_pilot/tasks/D01.md",
        "benchmarks/codex_r/tasks/R01/task.md",
        "benchmarks/codex_r/oracle/R01.R",
        "benchmarks/codex_r/manifest.json",
    ):
        assert needle in names
    assert any(n.startswith("benchmarks/codex_r/reports/") for n in names)
    assert not any(n.startswith("benchmarks/codex_r/studies/") for n in names)


# -------------------------------------------------------------- catalogue


def test_catalogue_covers_every_existing_task_exactly_once():
    ids = [e["task"] for e in calibration.CATALOG]
    assert len(ids) == len(set(ids))
    expected = (
        {f"R{i:02}" for i in range(1, 13)}
        | set(knowledge_pilot.PILOT_TASK_IDS)
        | set(hard.task_ids())
    )
    assert set(ids) == expected


def test_catalogue_dimensions_are_ordinal_and_complete():
    for entry in calibration.CATALOG:
        assert set(entry["dimensions"]) == set(calibration.DIMENSIONS)
        assert all(0 <= v <= 3 for v in entry["dimensions"].values())
        assert entry["expected_mcp_usefulness"] in ("none", "low", "plausible", "high")


def test_committed_catalogue_is_what_the_committed_summary_produces():
    summary = load("historical_calibration_summary.json")
    assert load("task_catalog.json") == calibration.build_catalog(summary)


def test_no_existing_task_is_confirmatory_eligible_today():
    counts = load("task_catalog.json")["stratum_counts"]
    assert counts.get("S1", 0) == 0 and counts["S2"] > 0 and counts["Q"] > 0 and counts["RC"] > 0


def test_screen_uses_only_the_baseline_arm_and_inclusion_ignores_mcp_outcomes(tmp_path):
    run = tmp_path / "run-1"
    run.mkdir()
    rows = []
    for mode, scores in (("without-mcp", [0.5, 0.5, 0.5]), ("with-mcp", [1.0, 1.0, 1.0])):
        for index, passed in enumerate(scores):
            rows.append(
                {
                    "task": "C04",
                    "mode": mode,
                    "status": "scored",
                    "score": {"passed": int(passed * 10), "total": 10},
                    "duration_seconds": 60 + index,
                    "run_id": "r",
                }
            )
    (run / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    summary = calibration.summarize_history(tmp_path)
    assert summary["arm_a_by_task"]["C04"] == {"n": 3, "mean": 0.5}
    assert "with-mcp" not in json.dumps(summary) and "1.0" not in json.dumps(
        summary["arm_a_by_task"]
    )
    # Making the MCP arm look wonderful or terrible must not change inclusion.
    entry = next(e for e in calibration.CATALOG if e["task"] == "C04")
    before = calibration.stratum(entry, calibration.screen(summary["arm_a_by_task"]["C04"]))
    for row in rows:
        if row["mode"] == "with-mcp":
            row["score"]["passed"] = 0
    (run / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    again = calibration.summarize_history(tmp_path)
    assert (
        calibration.stratum(entry, calibration.screen(again["arm_a_by_task"]["C04"]))
        == before
        == "S1"
    )


@pytest.mark.parametrize(
    ("history", "status"),
    [
        (None, "insufficient_data"),
        ({"n": 2, "mean": 0.5}, "insufficient_data"),
        ({"n": 5, "mean": 0.95}, "ceiling"),
        ({"n": 5, "mean": 0.05}, "floor"),
        ({"n": 5, "mean": 0.5}, "in_range"),
    ],
)
def test_arm_a_screen_thresholds(history, status):
    assert calibration.screen(history)["status"] == status


def test_historical_summary_records_the_known_limits():
    summary = load("historical_calibration_summary.json")
    assert summary["usage_observed"] <= 1  # tokens were almost never observed
    assert summary["trial_records"] > 90
    assert "with-mcp" not in json.dumps(summary)


def test_power_simulation_artifact_covers_positive_negative_and_type_i_checks():
    sim = load("power_simulation.json")
    assert sim["assumptions"] == asdict(power.Assumptions())
    deltas = {row["delta_non_saturated"] for row in sim["rows"]}
    assert {-0.2, -0.1, 0.0, 0.1, 0.2, 0.3} <= deltas
    hc = next(c for c in sim["type_i_check"] if c["tasks"] == 40 and c["repetitions"] == 5)
    assert hc["type_i_task_level"] <= 0.05 < hc["type_i_block_level"]


# --------------------------------------------------- synthetic validation set


def test_committed_synthetic_validation_reproduces_and_is_labelled_synthetic():
    base = STUDY / "synthetic_validation"
    summary = json.loads((base / "SUMMARY.json").read_text(encoding="utf-8"))
    assert summary["synthetic"] is True
    for name, row in summary["scenarios"].items():
        plan, recs = dryrun.read_inputs(base / name)
        result = dryrun.analyse(plan, recs, summary["seed"])
        assert dryrun.result_digest(result) == row["digest"], name
        assert result["synthetic"] is True and all(r["synthetic"] for r in recs)
    assert cli.main(["reanalyze", str(base / "positive"), "--seed", str(summary["seed"])]) == 0


def test_documents_state_that_no_empirical_effect_has_been_established():
    text = (STUDY / "STAGE2_REPORT.md").read_text(encoding="utf-8")
    assert "INFRASTRUCTURE READY" in text and "EMPIRICAL EFFECT ESTABLISHED" in text
    assert "not established" in text.lower() or "not reached" in text.lower()


def test_stage25_committed_reports_and_study_specifications():
    from benchmarks.codex_r.studies.stage2_validity_v1 import (
        isolation,
        scorer_calibration,
        study_configs,
    )

    scal = load("scorer_calibration_report.json")
    assert scal == scorer_calibration.run_scorer_calibration_suite()
    assert scal["all_probes_matched_expected_behavior"] is True

    specs = load("study_specifications.json")
    assert specs == study_configs.build_study_specifications()
    assert set(specs["configurations"]) == {"smoke_mock", "pilot_real_spec", "confirmatory_spec"}
    assert specs["configurations"]["smoke_mock"]["ready_to_execute"] is True
    assert specs["configurations"]["pilot_real_spec"]["ready_to_execute"] is False
    assert specs["configurations"]["confirmatory_spec"]["ready_to_execute"] is False
    assert specs["confirmatory_ready"] is False

    iso = load("isolation_probes_report.json")
    assert iso["synthetic_probes"] == isolation.run_synthetic_isolation_probes()
    assert iso["legacy_runner_audit"] == isolation.inspect_legacy_runner_isolation()

    readiness_doc = (STUDY / "STAGE25_PILOT_READINESS.md").read_text(encoding="utf-8")
    assert "STAGE 2.5 PARTIALLY COMPLETE" in readiness_doc
    assert "STAGE 2 INFRASTRUCTURE READY" in readiness_doc


def test_stage25_independent_reproducibility_workflow_in_temp_workspace(tmp_path):
    """Step 11: Simulate a fresh checkout workflow in an isolated temporary directory
    without relying on private git-ignored `benchmarks/codex_r/results/`."""
    # 1. Regenerate experiment manifest and compare with committed manifest
    fresh_manifest = manifest.build_manifest()
    assert fresh_manifest == load("experiment_manifest.json")

    # 2. Reproduce randomization schedule in tmp_path
    plan_out = tmp_path / "pilot_plan.json"
    assert (
        cli.main(["plan", "--design", "pilot", "--seed", "20261028", "--out", str(plan_out)]) == 0
    )
    plan_data = json.loads(plan_out.read_text(encoding="utf-8"))
    assert design.verify_plan(plan_data) == []

    # 3. Reproduce synthetic trial records via the Stage 2.5 smoke-runner CLI
    smoke_dir = tmp_path / "smoke_runner_out"
    assert cli.main(["smoke-runner", "--out", str(smoke_dir), "--seed", "20261028"]) == 0
    assert (smoke_dir / "plan.json").is_file()
    assert (smoke_dir / "trial_records.jsonl").is_file()
    assert (smoke_dir / "ledger_journal.jsonl").is_file()

    # 4. Reproduce the statistical analysis via the CLI on the generated plan + trial_records.jsonl
    analysis_out = tmp_path / "smoke_analysis.json"
    assert (
        cli.main(
            [
                "analyze",
                "--plan",
                str(smoke_dir / "plan.json"),
                "--records",
                str(smoke_dir / "trial_records.jsonl"),
                "--out",
                str(analysis_out),
            ]
        )
        == 0
    )
    analysis_data = json.loads(analysis_out.read_text(encoding="utf-8"))
    assert "primary" in analysis_data and "secondary" in analysis_data

    # 5. Validate immutable frozen evidence hashes
    assert cli.main(["frozen", "--verify"]) == 0
