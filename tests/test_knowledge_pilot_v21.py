import copy
import json

import pytest

from benchmarks.codex_r import (
    knowledge_pilot,
    rescore_b1_v21,
    run_simple,
)
from benchmarks.codex_r import (
    knowledge_pilot_v21 as v21,
)


def _answer(task_id, package):
    facts = v21._evidence()["tasks"][task_id]["packages"][package]
    return {
        "r_version": "4.5.2",
        "rationale": "This package fits the requested workflow and states a documented tradeoff.",
        "recommendations": [
            {
                "package": package,
                "version": facts["version"],
                "source_url": f"https://cran.r-project.org/package={package}",
                "documentation_url": facts["source_urls"][0],
                "feature_ids": list(facts["required_features"]),
                "caveat_ids": list(facts["required_caveats"]),
            }
        ],
    }


def _score(tmp_path, task_id, answer):
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(answer), encoding="utf-8")
    return v21.score(task_id, tmp_path)


def test_v21_known_required_claims_score_and_include_versioned_provenance(tmp_path):
    result = _score(tmp_path, "D03", _answer("D03", "pointblank"))
    assert result["scorer_version"] == "knowledge-pilot-v2.1"
    assert result["status"] == "scored" and result["fully_correct"] is True
    assert result["claim_audit"]["status"] == "supported"
    assert result["claim_audit"]["unknown"] == []
    assert "features:cross_record_rules" not in result["claim_audit"]["required"]
    assert "features:pipeline_validation" in result["claim_audit"]["required"]
    assert result["provenance"]["claim_evidence_sha256"] == v21.evidence_digest()
    assert result["provenance"]["contracts_sha256"] == v21.contract_digest()


def test_v21_unknown_task_allowed_feature_abstains_without_marking_it_false(tmp_path):
    answer = _answer("D03", "pointblank")
    answer["recommendations"][0]["feature_ids"].append("cross_record_rules")
    result = _score(tmp_path, "D03", answer)
    assert result["status"] == "unsupported_for_automatic_scoring"
    assert result["fully_correct"] is None
    assert result["claim_audit"]["unknown"] == ["features:cross_record_rules"]
    assert result["claim_audit"]["contradicted"] == []
    assert result["dimensions"]["unsupported_claims"]["status"] == "unknown"


def test_v21_unknown_claim_keeps_overall_outcome_abstained_even_with_known_check_failure(
    tmp_path,
):
    answer = _answer("D03", "pointblank")
    answer["recommendations"][0]["feature_ids"].append("cross_record_rules")
    answer["recommendations"][0]["source_url"] = "https://example.invalid/package"
    result = _score(tmp_path, "D03", answer)
    assert result["status"] == "unsupported_for_automatic_scoring"
    assert result["fully_correct"] is None
    assert result["dimensions"]["version_repository_identity"]["status"] == "fail"
    assert result["claim_audit"]["unknown"] == ["features:cross_record_rules"]


def test_v21_accepts_a_supported_extra_feature_not_in_required_minimums(tmp_path, monkeypatch):
    evidence = copy.deepcopy(v21._evidence())
    pointblank = evidence["tasks"]["D03"]["packages"]["pointblank"]
    pointblank["unknown_features"].remove("cross_record_rules")
    pointblank["supported_features"].append("cross_record_rules")
    monkeypatch.setattr(v21, "_evidence", lambda: evidence)
    answer = _answer("D03", "pointblank")
    answer["recommendations"][0]["feature_ids"].append("cross_record_rules")
    result = _score(tmp_path, "D03", answer)
    assert result["status"] == "scored" and result["fully_correct"] is True
    assert result["claim_audit"]["unknown"] == []
    assert "features:cross_record_rules" in result["claim_audit"]["supported"]


def test_v21_contradicted_claim_fails_without_becoming_unknown(tmp_path, monkeypatch):
    evidence = copy.deepcopy(v21._evidence())
    pointblank = evidence["tasks"]["D03"]["packages"]["pointblank"]
    pointblank["unknown_features"].remove("cross_record_rules")
    pointblank["contradicted_features"].append("cross_record_rules")
    monkeypatch.setattr(v21, "_evidence", lambda: evidence)
    answer = _answer("D03", "pointblank")
    answer["recommendations"][0]["feature_ids"].append("cross_record_rules")
    result = _score(tmp_path, "D03", answer)
    assert result["status"] == "scored" and result["fully_correct"] is False
    assert result["claim_audit"]["contradicted"] == ["features:cross_record_rules"]
    assert result["claim_audit"]["unknown"] == []


def test_v21_missing_required_claim_and_caveat_remains_a_known_failure(tmp_path):
    answer = _answer("D01", "termr")
    answer["recommendations"][0]["caveat_ids"].remove("some_apis_experimental")
    result = _score(tmp_path, "D01", answer)
    assert result["status"] == "scored" and result["fully_correct"] is False
    assert result["claim_audit"]["required_missing"] == ["caveats:some_apis_experimental"]
    assert result["dimensions"]["factual_correctness"]["checks"]["documented_limits"] == "fail"


def test_v21_termr_multi_select_claim_is_unknown_not_a_false_fact(tmp_path):
    answer = _answer("D01", "termr")
    answer["recommendations"][0]["feature_ids"].append("keyboard_single_multi_select")
    result = _score(tmp_path, "D01", answer)
    assert result["status"] == "unsupported_for_automatic_scoring"
    assert result["claim_audit"]["unknown"] == ["features:keyboard_single_multi_select"]


def test_v21_invalid_task_feature_id_fails_public_schema(tmp_path):
    answer = _answer("D03", "pointblank")
    answer["recommendations"][0]["feature_ids"].append("invented_feature")
    result = _score(tmp_path, "D03", answer)
    assert result["dimensions"]["schema_validity"]["status"] == "fail"
    assert result["dimensions"]["unsupported_claims"]["status"] == "not_evaluated"
    assert result["status"] == "scored" and result["fully_correct"] is False


def test_v21_prepare_and_score_selection_are_explicit(tmp_path):
    workspace = tmp_path / "candidate"
    prepared = knowledge_pilot.prepare("D03", workspace, "knowledge-pilot-v2.1")
    assert prepared["scorer_version"] == "knowledge-pilot-v2.1"
    assert (workspace / "OUTPUT_SCHEMA.json").is_file()
    assert "knowledge-pilot-v2.1" in (workspace / "TASK.md").read_text(encoding="utf-8")
    try:
        knowledge_pilot.prepare("D02", tmp_path / "unsupported-task", "knowledge-pilot-v2.1")
    except ValueError as exc:
        assert "D01 and D03" in str(exc)
    else:
        raise AssertionError("V2.1 accepted an unsupported task")


def test_b1_comparison_uses_binary_v2_outcome_when_check_counts_are_null():
    plan = [
        {
            "trial_id": "D01-control-1",
            "task": "D01",
            "repetition": 1,
            "condition": "control",
            "execution_order": 1,
        },
        {
            "trial_id": "D01-treatment-1",
            "task": "D01",
            "repetition": 1,
            "condition": "treatment",
            "execution_order": 2,
        },
    ]
    records = [
        {
            "trial_id": item["trial_id"],
            "status": "scored",
            "scorer_identity": "knowledge-pilot-v2",
            "score": {"passed": None, "total": None, "fully_correct": True},
        }
        for item in plan
    ]
    result = run_simple.build_b1_comparison(records, {"trial_plan": plan})
    assert result["scored_pairs"] == 1
    assert result["pairs"][0]["score_comparable"] is True
    assert result["pairs"][0]["comparison_metric"] == "fully_correct"
    assert result["pairs"][0]["delta_score"] == 0


def test_saved_b1_rescore_preserves_all_sources_and_corrects_d01_r1_pairing(tmp_path):
    run_dir = rescore_b1_v21.RESULTS_ROOT / rescore_b1_v21.RUN_ID
    if not run_dir.is_dir():
        pytest.skip("saved B1 run is not present")
    results_path = run_dir / "results.json"
    original_results_sha = rescore_b1_v21._sha256(results_path)
    report, json_path, markdown_path = rescore_b1_v21.rescore_run(run_dir, tmp_path / "reports")
    assert json_path.is_file() and markdown_path.is_file()
    assert len(report["trials"]) == 12
    assert report["source_files_preserved"] is True
    assert report["source_results_sha256"] == original_results_sha
    assert rescore_b1_v21._sha256(results_path) == original_results_sha
    d01_r1 = next(
        item
        for item in report["comparison"]["pairs"]
        if item["task"] == "D01" and item["repetition"] == 1
    )
    assert d01_r1["score_comparable"] is True
    assert d01_r1["original_score_comparable"] is False
    assert all(
        item["answer_sha256"] for item in report["trials"] if item["task"] in v21.SUPPORTED_TASKS
    )
