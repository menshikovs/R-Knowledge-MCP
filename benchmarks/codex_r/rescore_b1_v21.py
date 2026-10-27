"""Read-only, checksum-verified offline rescoring for the saved B1 Discovery run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.codex_r import knowledge_pilot_v21, run_simple
from benchmarks.codex_r.telemetry import errors as telemetry_errors

RUN_ID = "20261026T104750Z-f78eabf1"
RESULTS_ROOT = Path(__file__).resolve().parent / "results"
REPORTS_ROOT = Path(__file__).resolve().parent / "reports"
REPO_ROOT = Path(__file__).resolve().parents[2]
JSON_NAME = "b1_scorer_v21_rescore_20261026.json"
MARKDOWN_NAME = "b1_scorer_v21_rescore_20261026.md"
EXPECTED_TASKS = {"D01": 4, "D03": 4, "C01": 4}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("rescore_input_missing_or_symlink")
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_evidence_basis() -> None:
    evidence = json.loads(knowledge_pilot_v21.EVIDENCE_PATH.read_text(encoding="utf-8"))
    for item in [
        evidence["basis"]["candidate_facts"],
        evidence["basis"]["official_resource_inventory"],
    ]:
        if _sha256(REPO_ROOT / item["path"]) != item["sha256"]:
            raise ValueError("frozen_claim_evidence_basis_mismatch")
    for item in evidence["basis"]["task_metadata"].values():
        if _sha256(REPO_ROOT / item["path"]) != item["sha256"]:
            raise ValueError("frozen_task_metadata_mismatch")


def _dimension_changes(original, rescored):
    old_dims = (original or {}).get("dimensions") or {}
    new_dims = (rescored or {}).get("dimensions") or {}
    changes = []
    for dimension in sorted(set(old_dims) | set(new_dims)):
        old = old_dims.get(dimension) or {}
        new = new_dims.get(dimension) or {}
        old_checks, new_checks = old.get("checks") or {}, new.get("checks") or {}
        for check in sorted(set(old_checks) | set(new_checks)):
            before, after = old_checks.get(check), new_checks.get(check)
            if before != after:
                changes.append(
                    {
                        "dimension": dimension,
                        "check": check,
                        "original": before,
                        "rescored": after,
                    }
                )
        if old.get("status") != new.get("status"):
            changes.append(
                {
                    "dimension": dimension,
                    "check": "$dimension_status",
                    "original": old.get("status"),
                    "rescored": new.get("status"),
                }
            )
    return changes


def _mcp_calls(record):
    calls = (record.get("mcp_telemetry") or {}).get("calls") or []
    return [
        {
            "is_error": call.get("status") == "error"
            if call.get("status") in {"ok", "error"}
            else None,
            "partial": call.get("partial"),
            "error_codes": call.get("error_codes"),
        }
        for call in calls
    ]


def _artifact_for(task_id, trial_dir, result):
    artifact_name = (
        "answer.json" if task_id in knowledge_pilot_v21.SUPPORTED_TASKS else "solution.R"
    )
    path = trial_dir / "artifacts" / artifact_name
    if path.is_symlink() or not path.is_file():
        raise ValueError("rescore_artifact_missing_or_symlink")
    checksum = _sha256(path)
    recorded = ((result.get("score") or {}).get("artifacts") or {}).get(artifact_name) or (
        result.get("artifact_sources") or {}
    ).get(artifact_name)
    if checksum != recorded:
        raise ValueError("original_artifact_checksum_mismatch")
    return artifact_name, path, checksum


def _changed_reason(task_id, rescored, changes):
    if task_id == "C01":
        return (
            "C01 remains on its original legacy scorer; the D-task V2.1 contract was not applied."
        )
    claim_audit = rescored.get("claim_audit") or {}
    if claim_audit.get("unknown"):
        return (
            "Additional claim IDs are now explicitly unknown from retained offline evidence. "
            "Automatic scoring abstains; no unsupported claim is upgraded to supported."
        )
    if changes:
        return "The versioned claim registry and scorer checks were applied; see changed_checks."
    return "No score-check outcome changed under the new claim evidence classification."


def _input_snapshot(run_dir, result_rows):
    paths = [run_dir / "experiment.json", run_dir / "results.json", run_dir / "b1_comparison.json"]
    evidence = json.loads(knowledge_pilot_v21.EVIDENCE_PATH.read_text(encoding="utf-8"))
    paths.extend(
        REPO_ROOT / item["path"]
        for item in [
            evidence["basis"]["candidate_facts"],
            evidence["basis"]["official_resource_inventory"],
            *evidence["basis"]["task_metadata"].values(),
        ]
    )
    for item in result_rows:
        trial_id = item.get("trial_id") or item.get("trial")
        if not isinstance(trial_id, str) or not re.fullmatch(
            r"b1-discovery-[A-Za-z0-9-]+", trial_id
        ):
            raise ValueError("invalid_trial_identity")
        trial_dir = run_dir / trial_id
        paths.extend(
            (
                trial_dir / "result.json",
                trial_dir
                / "artifacts"
                / (
                    "answer.json"
                    if item.get("task") in knowledge_pilot_v21.SUPPORTED_TASKS
                    else "solution.R"
                ),
            )
        )
    return {
        path.relative_to(run_dir).as_posix()
        if path.is_relative_to(run_dir)
        else path.relative_to(REPO_ROOT).as_posix(): _sha256(path)
        for path in paths
    }


def _compare_records(records, experiment):
    comparison = run_simple.build_b1_comparison(records, experiment)
    for row in comparison["pairs"]:
        row["original_score_comparable"] = next(
            (
                item.get("score_comparable")
                for item in (experiment.get("original_comparison_pairs") or [])
                if item.get("task") == row["task"] and item.get("repetition") == row["repetition"]
            ),
            None,
        )
    return comparison


def _markdown(report):
    lines = [
        "# B1 Discovery — V2.1 versioned offline rescore",
        "",
        f"Run: `{report['source_run']}`  ",
        f"Original results checksum: `{report['source_results_sha256']}`  ",
        f"V2.1 evaluator: `{report['scorer']['evaluator_sha256']}`  ",
        f"Claim evidence: `{report['scorer']['claim_evidence_sha256']}`",
        "",
        "## Summary",
        "",
        f"Read-only rescore verified {len(report['trials'])} original trial records "
        "and answer/artifact checksums. No original result, artifact, experiment manifest, "
        "task, prompt, or condition digest was rewritten.",
        "C01 remains under its original legacy scorer. D01/D03 use "
        "`knowledge-pilot-v2.1`; unknown claims remain unscored.",
        "",
        "## Trial outcomes",
        "",
        "| Trial | Original | V2.1 / retained status | Original fully correct | "
        "New fully correct | Claim state | Changes |",
        "|---|---|---|---:|---:|---|---:|",
    ]
    for item in report["trials"]:
        score = item.get("rescored") or {}
        claim = score.get("claim_audit") or {}
        state = claim.get("status", "legacy retained")
        lines.append(
            f"| `{item['trial_id']}` | {item['original_status']} | {item['rescored_status']} | "
            f"{item.get('original_fully_correct')} | {score.get('fully_correct')} | {state} | "
            f"{len(item['changed_checks'])} |"
        )
    lines.extend(
        [
            "",
            "## Claim evidence results",
            "",
            "| Trial | Supported claims | Unknown claims | Contradicted claims |",
            "|---|---|---|---|",
        ]
    )
    for item in report["trials"]:
        audit = (item.get("rescored") or {}).get("claim_audit") or {}
        if audit:
            lines.append(
                f"| `{item['trial_id']}` | {', '.join(audit.get('supported', [])) or '—'} | "
                f"{', '.join(audit.get('unknown', [])) or '—'} | "
                f"{', '.join(audit.get('contradicted', [])) or '—'} |"
            )
    lines.extend(
        [
            "",
            "## Revised paired comparison",
            "",
            "| Task | Rep | Comparable | Metric | Original comparable | Delta |",
            "|---|---:|---:|---|---:|---:|",
        ]
    )
    for pair in report["comparison"]["pairs"]:
        lines.append(
            f"| {pair['task']} | {pair['repetition']} | {pair['score_comparable']} | "
            f"{pair.get('comparison_metric') or '—'} | {pair.get('original_score_comparable')} | "
            f"{pair.get('delta_score')} |"
        )
    lines.extend(
        [
            "",
            "## Error taxonomy",
            "",
            "Scorer abstentions use `origin=scorer`, `category=evidence_insufficiency`, "
            "`reason_code=SCORER_UNSUPPORTED_CLAIMS`. Partial and provider MCP diagnostics "
            "remain in `mcp_errors`; they do not replace the scorer abstention as `primary_error`.",
            "",
            "## Provenance and verification",
            "",
            f"- Scorer version: `{report['scorer']['version']}`.",
            f"- Contract digest: `{report['scorer']['contracts_sha256']}`.",
            f"- Frozen basis verified: `{report['frozen_basis_verified']}`.",
            f"- Original inputs unchanged after rescore: `{report['source_files_preserved']}`.",
            "- Original scorer digests retained per trial: yes.",
            "- No model, Agents API, Docker, web, CRAN or Bioconductor calls were made.",
            "- The saved D01/D03 documentation bodies are unavailable; their unregistered "
            "claims remain unknown.",
            "",
        ]
    )
    return "\n".join(lines)


def rescore_run(run_dir=RESULTS_ROOT / RUN_ID, output_dir=REPORTS_ROOT):
    source_path = Path(run_dir)
    if source_path.is_symlink():
        raise ValueError("unexpected_rescore_run")
    run_dir = source_path.resolve(strict=True)
    if run_dir.name != RUN_ID:
        raise ValueError("unexpected_rescore_run")
    experiment_path, results_path = run_dir / "experiment.json", run_dir / "results.json"
    experiment = _read_json(experiment_path)
    original_comparison_path = run_dir / "b1_comparison.json"
    original_comparison = _read_json(original_comparison_path)
    experiment["original_comparison_pairs"] = original_comparison.get("pairs", [])
    result_rows = _read_json(results_path)
    if experiment.get("run_id") != RUN_ID or len(result_rows) != 12:
        raise ValueError("unexpected_b1_run_shape")
    counts = {task: sum(row.get("task") == task for row in result_rows) for task in EXPECTED_TASKS}
    if counts != EXPECTED_TASKS:
        raise ValueError("unexpected_b1_task_counts")
    _verify_evidence_basis()
    input_hashes = _input_snapshot(run_dir, result_rows)
    records_for_comparison = []
    trials = []
    for original in result_rows:
        trial_id = original.get("trial_id") or original.get("trial")
        task_id = original.get("task")
        trial_dir = run_dir / trial_id
        saved_result = _read_json(trial_dir / "result.json")
        if saved_result.get("trial_id") != trial_id:
            raise ValueError("trial_result_identity_mismatch")
        artifact_name, artifact_path, artifact_sha = _artifact_for(task_id, trial_dir, saved_result)
        old_score = saved_result.get("score") or {}
        original_scorer = old_score.get("scorer_version") or saved_result.get("scorer_identity")
        if task_id in knowledge_pilot_v21.SUPPORTED_TASKS:
            rescored = knowledge_pilot_v21.score(task_id, artifact_path.parent)
            revised_record = dict(saved_result)
            revised_record["score"] = rescored
            revised_record["status"] = rescored["status"]
            revised_record["scorer_identity"] = knowledge_pilot_v21.SCORER_VERSION
            mcp_calls = _mcp_calls(saved_result)
            rescored_error = telemetry_errors.classify_trial(revised_record, mcp_calls)
            revised_record["error_summary"] = rescored_error
            changes = _dimension_changes(old_score, rescored)
            unknown_claims = (rescored.get("claim_audit") or {}).get("unknown", [])
            unsupported_claims = (rescored.get("claim_audit") or {}).get("unsupported", [])
            contradicted_claims = (rescored.get("claim_audit") or {}).get("contradicted", [])
            rescored_status = rescored["status"]
            rescored_version = knowledge_pilot_v21.SCORER_VERSION
        else:
            rescored = None
            rescored_error = saved_result.get("error_summary")
            changes = []
            unknown_claims = unsupported_claims = contradicted_claims = []
            rescored_status = "legacy_retained"
            rescored_version = original_scorer or "legacy"
            revised_record = dict(saved_result)
        records_for_comparison.append(revised_record)
        trials.append(
            {
                "trial_id": trial_id,
                "condition": saved_result.get("condition"),
                "task": task_id,
                "original_scorer_version": original_scorer,
                "rescored_scorer_version": rescored_version,
                "original_scorer_sha256": saved_result.get("scorer_sha256"),
                "rescored_scorer_sha256": knowledge_pilot_v21.evaluator_digest()
                if rescored
                else None,
                "original_status": saved_result.get("status"),
                "rescored_status": rescored_status,
                "original_score": old_score,
                "rescored": rescored,
                "original_fully_correct": old_score.get("fully_correct"),
                "evidence_status": (rescored or {}).get("claim_audit", {}).get("status")
                if rescored
                else "legacy_retained",
                "unknown_claims": unknown_claims,
                "unsupported_claims": unsupported_claims,
                "contradicted_claims": contradicted_claims,
                "changed_checks": changes,
                "reason_for_change": _changed_reason(task_id, rescored or {}, changes),
                "artifact_name": artifact_name,
                "artifact_sha256": artifact_sha,
                "answer_sha256": artifact_sha if artifact_name == "answer.json" else None,
                "answer_matches_original_record": True,
                "evidence_sha256": knowledge_pilot_v21.evidence_digest() if rescored else None,
                "original_error_summary": saved_result.get("error_summary"),
                "rescored_error_summary": rescored_error,
            }
        )
    source_preserved = _input_snapshot(run_dir, result_rows) == input_hashes
    report = {
        "report_type": "d-rescore",
        "report_version": "1.0",
        "source_run": RUN_ID,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_results_sha256": _sha256(results_path),
        "source_experiment_sha256": _sha256(experiment_path),
        "source_comparison_sha256": _sha256(original_comparison_path),
        "scorer": {
            "version": knowledge_pilot_v21.SCORER_VERSION,
            "evaluator_sha256": knowledge_pilot_v21.evaluator_digest(),
            "contracts_sha256": knowledge_pilot_v21.contract_digest(),
            "claim_evidence_sha256": knowledge_pilot_v21.evidence_digest(),
            "claim_evidence_version": "knowledge-pilot-claims-v2.1",
        },
        "frozen_basis_verified": True,
        "source_files_preserved": source_preserved,
        "original_results_modified": False,
        "original_answers_modified": False,
        "experiment_metadata_modified": False,
        "trials": trials,
        "comparison": _compare_records(records_for_comparison, experiment),
    }
    if not source_preserved:
        raise RuntimeError("offline_rescore_modified_source_files")
    report["comparison"]["original_scored_pairs"] = original_comparison.get("scored_pairs")
    output_dir = Path(output_dir).resolve()
    if output_dir.is_relative_to(run_dir):
        raise ValueError("rescore_reports_must_be_outside_source_run")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, markdown_path = output_dir / JSON_NAME, output_dir / MARKDOWN_NAME
    if json_path.exists() or markdown_path.exists():
        raise FileExistsError("offline_rescore_report_already_exists")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return report, json_path, markdown_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=RESULTS_ROOT / RUN_ID)
    parser.add_argument("--output-dir", type=Path, default=REPORTS_ROOT)
    args = parser.parse_args(argv)
    report, json_path, markdown_path = rescore_run(args.run_dir, args.output_dir)
    print(
        json.dumps(
            {
                "run_id": report["source_run"],
                "trials": len(report["trials"]),
                "scored_pairs": report["comparison"]["scored_pairs"],
                "json": str(json_path),
                "markdown": str(markdown_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
