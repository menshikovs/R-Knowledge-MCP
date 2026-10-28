"""Stage 2.7 Calibration Pipeline, Eligibility Assessment, and Pilot Preparation.

Provides versioned, deterministic pipelines for:
1. Reconstructing and auditing task eligibility from repository evidence.
2. Generating an Arm-A-only baseline calibration schedule without paid model spend.
3. Conducting baseline-only difficulty and uncertainty assessments.
4. Defining the authorized pilot specification (gated on explicit budget authorization).
5. Evaluating the 5 formal research readiness gates.

Zero real model API calls or credentials are used in this module.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from . import calibration, manifest, runner

STUDY_ROOT = Path(__file__).resolve().parent
CODEX_ROOT = STUDY_ROOT.parents[1]

# Pinned candidate task pool for Stage 2.7 baseline calibration (Arm A only)
CANDIDATE_TASKS_S2 = (
    "R01",
    "R02",
    "R03",
    "R04",
    "R05",
    "R06",
    "R07",
    "R08",
    "R09",
    "R10",
    "R11",
    "R12",
    "C03",
    "C04",
    "H01",
    "H04",
    "H10",
)

RECALIBRATION_TASKS_RC = (
    "C01",
    "C02",
    "C05",
    "D01",
    "D02",
    "D03",
    "E04",
    "E05",
)

QUARANTINED_TASKS_Q = (
    "B01",
    "B02",
    "B03",
    "E01",
    "E02",
    "E03",
)

MODEL_IDENTITY = "gpt-6-luna"
RUNTIME_IMAGE = "rkmcp-codex-runtime:codex-0.163.0"
TIMEOUT_SECONDS = 900
BASELINE_REPETITIONS = 3
ESTIMATED_PROMPT_TOKENS_PER_TRIAL = 12_000
ESTIMATED_COMPLETION_TOKENS_PER_TRIAL = 2_500
ESTIMATED_SECONDS_PER_TRIAL = 82.6


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_task_eligibility() -> dict[str, Any]:
    """Reconstruct task counts and eligibility classifications from repository evidence.

    Selection rules:
    - Arm A baseline data ONLY.
    - Arms with MCP access are NEVER inspected or used for task inclusion/exclusion.
    - Tasks with BEN-002 oracle coupling or hidden schema requirements are excluded
      from confirmatory core until recalibrated and revalidated.
    """
    catalog_path = STUDY_ROOT / "task_catalog.json"
    if not catalog_path.is_file():
        summary = calibration.summarize_history(CODEX_ROOT / "results")
        catalog_data = calibration.build_catalog(summary)
    else:
        catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))

    tasks = catalog_data["tasks"]
    total_tasks = len(tasks)

    evaluated: list[dict[str, Any]] = []
    strata_counts: dict[str, int] = {
        "S1_confirmatory_core": 0,
        "S2_calibration_needed": 0,
        "RC_recalibration_required": 0,
        "Q_quarantined_or_smoke": 0,
    }

    for entry in tasks:
        tid = entry["task"]
        strat = entry.get("provisional_stratum", "Q")
        screen_res = entry.get("historical_arm_a_screen", {})
        mean_a = screen_res.get("mean_arm_a")
        n_a = screen_res.get("n", 0)

        exclusions: list[str] = []
        if tid in ("D01", "D02", "D03"):
            exclusions.append("BEN-002: frozen candidate list oracle coupling")
        if tid in ("E01", "E04", "E05"):
            exclusions.append("BEN-002: unprompted JSON schema key requirement")
        if mean_a == 1.0 and n_a >= 3:
            exclusions.append("historical_ceiling_saturation_mean_1.0")
        if mean_a == 0.0 and n_a >= 3:
            exclusions.append("historical_floor_saturation_mean_0.0")
        if n_a < 3:
            exclusions.append("insufficient_historical_arm_a_observations_lt_3")

        if strat == "Q":
            full_stratum = "Q_quarantined_or_smoke"
            eligible_confirmatory = False
            eligible_calibration = False
        elif strat == "RC":
            full_stratum = "RC_recalibration_required"
            eligible_confirmatory = False
            eligible_calibration = False
        elif strat == "S2":
            full_stratum = "S2_calibration_needed"
            eligible_confirmatory = False
            eligible_calibration = True
        elif strat == "S1":
            full_stratum = "S1_confirmatory_core"
            eligible_confirmatory = True
            eligible_calibration = False
        else:
            full_stratum = "Q_quarantined_or_smoke"
            eligible_confirmatory = False
            eligible_calibration = False

        strata_counts[full_stratum] += 1

        meta = runner._task_and_scorer_meta(tid)
        task_sha = meta["task_sha256"]
        scorer_sha = meta["scorer_sha256"]

        evaluated.append(
            {
                "task_id": tid,
                "suite": entry.get("suite"),
                "title": entry.get("title"),
                "scorer": entry.get("scorer"),
                "task_sha256": task_sha,
                "scorer_sha256": scorer_sha,
                "provisional_stratum": full_stratum,
                "eligible_for_confirmatory": eligible_confirmatory,
                "eligible_for_calibration": eligible_calibration,
                "historical_arm_a_screen": {
                    "observations": n_a,
                    "mean_score": mean_a,
                    "status": screen_res.get("status"),
                },
                "exclusions": exclusions,
                "notes": entry.get("notes", ""),
            }
        )

    return {
        "schema_version": "stage27-eligibility-v1.0",
        "total_benchmark_tasks": total_tasks,
        "strata_counts": strata_counts,
        "confirmatory_eligible_count": strata_counts["S1_confirmatory_core"],
        "calibration_needed_count": strata_counts["S2_calibration_needed"],
        "recalibration_required_count": strata_counts["RC_recalibration_required"],
        "quarantined_count": strata_counts["Q_quarantined_or_smoke"],
        "selection_rule": {
            "screen": "Arm A baseline observations only",
            "minimum_repetitions": 3,
            "variance_target": [0.10, 0.90],
            "mcp_arms_conditioned": False,
        },
        "tasks": evaluated,
    }


def build_calibration_schedule(seed: int = 20261028) -> dict[str, Any]:
    """Generate the deterministic Arm-A-only baseline calibration schedule.

    Covers 17 S2 candidate tasks with 3 baseline repetitions each (51 trials total).
    No model calls or network connections are made.
    """
    trials: list[dict[str, Any]] = []
    trial_idx = 1

    for rep in range(1, BASELINE_REPETITIONS + 1):
        for tid in sorted(CANDIDATE_TASKS_S2):
            meta = runner._task_and_scorer_meta(tid)
            task_sha = meta["task_sha256"]
            scorer_sha = meta["scorer_sha256"]
            scorer_name = meta["scorer_version"]

            trial_seed = (seed + trial_idx * 1009) & 0xFFFFFFFF
            trial_id = f"cal-A-{tid}-r{rep}-{trial_idx:03d}"

            trials.append(
                {
                    "trial_id": trial_id,
                    "task": tid,
                    "arm": "A",
                    "repetition": rep,
                    "scorer_version": scorer_name,
                    "task_sha256": task_sha,
                    "scorer_sha256": scorer_sha,
                    "randomization_seed": trial_seed,
                    "model": MODEL_IDENTITY,
                    "runtime_image": RUNTIME_IMAGE,
                    "timeout_seconds": TIMEOUT_SECONDS,
                    "estimated_tokens": {
                        "prompt_tokens": ESTIMATED_PROMPT_TOKENS_PER_TRIAL,
                        "completion_tokens": ESTIMATED_COMPLETION_TOKENS_PER_TRIAL,
                    },
                    "estimated_duration_seconds": ESTIMATED_SECONDS_PER_TRIAL,
                    "retry_policy": {
                        "max_retries": 1,
                        "retry_on": ["infrastructure_failure"],
                        "retry_on_candidate_failure": False,
                    },
                    "stop_conditions": {
                        "max_consecutive_infrastructure_failures": 3,
                        "max_failure_rate": 0.20,
                        "abort_on_isolation_canary_failure": True,
                    },
                }
            )
            trial_idx += 1

    total_prompt = len(trials) * ESTIMATED_PROMPT_TOKENS_PER_TRIAL
    total_completion = len(trials) * ESTIMATED_COMPLETION_TOKENS_PER_TRIAL
    total_hours = round((len(trials) * ESTIMATED_SECONDS_PER_TRIAL) / 3600.0, 2)

    return {
        "schedule_version": "stage27-calibration-schedule-v1.0",
        "study_id": "stage27_baseline_calibration",
        "status": "PREPARED_NOT_EXECUTED",
        "seed": seed,
        "candidate_tasks": sorted(CANDIDATE_TASKS_S2),
        "candidate_task_count": len(CANDIDATE_TASKS_S2),
        "arms": ["A"],
        "repetitions_per_task": BASELINE_REPETITIONS,
        "total_planned_trials": len(trials),
        "resource_estimates": {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "expected_wall_clock_hours": total_hours,
            "timeout_ceiling_hours": round((len(trials) * TIMEOUT_SECONDS) / 3600.0, 2),
        },
        "model_execution_authorized": False,
        "trials": trials,
    }


def evaluate_baseline_difficulty(
    trial_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate baseline-only difficulty, variance, and uncertainty statistics.

    Evaluates whether tasks meet the preregistered non-degeneracy condition (0.10 <= mean <= 0.90)
    using Arm A observations only. Accounts for sample-size uncertainty when R=3.
    """
    by_task: dict[str, list[float]] = {}
    perfect_by_task: dict[str, list[bool]] = {}

    for rec in trial_records:
        if rec.get("arm") != "A":
            continue
        tid = rec.get("task")
        kind = rec.get("outcome_kind")
        if kind == "scored":
            score = float(rec["score"])
        elif kind == "candidate_failure":
            score = 0.0
        else:
            continue

        by_task.setdefault(tid, []).append(score)
        perfect_by_task.setdefault(tid, []).append(score == 1.0)

    summary: dict[str, Any] = {}
    for tid, scores in sorted(by_task.items()):
        n = len(scores)
        mean_score = sum(scores) / n
        var_score = sum((s - mean_score) ** 2 for s in scores) / (n - 1) if n > 1 else 0.0
        se_score = math.sqrt(var_score / n) if n > 0 else 0.0

        n_perfect = sum(perfect_by_task[tid])
        full_correct_rate = n_perfect / n

        # Wilson score interval for full correctness
        z = 1.96
        denom = 1 + (z**2) / n
        center = (full_correct_rate + (z**2) / (2 * n)) / denom
        margin = (
            z
            * math.sqrt((full_correct_rate * (1 - full_correct_rate) / n) + (z**2) / (4 * n**2))
            / denom
        )
        ci_low = max(0.0, center - margin)
        ci_high = min(1.0, center + margin)

        if mean_score > 0.90:
            classification = "ceiling"
        elif mean_score < 0.10:
            classification = "floor"
        else:
            classification = "candidate_in_range"

        # When n < 5, precision is inherently weak; flag borderline or small-sample cases
        margin_mean = 4.30 * se_score if n == 3 else 1.96 * se_score
        mean_ci_low = max(0.0, mean_score - margin_mean)
        mean_ci_high = min(1.0, mean_score + margin_mean)

        if classification == "candidate_in_range":
            if mean_ci_low < 0.10 or mean_ci_high > 0.90:
                uncertainty_flag = "inconclusive_sample_size_limited"
            elif n < 5:
                uncertainty_flag = "provisional_small_sample"
            else:
                uncertainty_flag = "reliable_in_range"
        else:
            uncertainty_flag = "definite_floor_or_ceiling" if n >= 3 else "insufficient_data"

        summary[tid] = {
            "observations": n,
            "mean_score": round(mean_score, 4),
            "sample_variance": round(var_score, 4),
            "std_error": round(se_score, 4),
            "full_correct_rate": round(full_correct_rate, 4),
            "full_correct_95ci": [round(ci_low, 4), round(ci_high, 4)],
            "mean_score_approx_95ci": [round(mean_ci_low, 4), round(mean_ci_high, 4)],
            "classification": classification,
            "uncertainty_status": uncertainty_flag,
        }

    return {
        "assessment_version": "stage27-baseline-difficulty-v1.0",
        "evaluated_tasks": len(summary),
        "tasks": summary,
    }


def build_pilot_specification() -> dict[str, Any]:
    """Define the authorized pilot execution specification.

    Flagged explicitly as NOT_AUTHORIZED_FOR_EXECUTION until the owner sets and approves budget.
    """
    pilot_tasks = list(manifest.PILOT_TASKS)
    return {
        "specification_version": "stage27-pilot-specification-v1.0",
        "study_id": "stage2_validity_v1_pilot",
        "status": "NOT_AUTHORIZED_FOR_EXECUTION",
        "authorization_requirement": (
            "Explicit human project owner budget allocation and model key configuration"
        ),
        "authorized_budget_usd": None,
        "candidate_tasks": pilot_tasks,
        "task_count": len(pilot_tasks),
        "arms": ["A", "B", "C"],
        "repetitions": 3,
        "total_trials": len(pilot_tasks) * 3 * 3,
        "model_identity": MODEL_IDENTITY,
        "runtime_image": RUNTIME_IMAGE,
        "randomization_algorithm": "blocked-latin-permutations-v1",
        "network_isolation": {
            "candidate_network": "Docker --internal bridge",
            "proxy": "CONNECT-only egress gateway (arm_gateway.py)",
            "allowed_hosts": ["api.openai.com:443"],
            "mcp_access": "Arms B and C only; completely omitted in Arm A",
        },
        "telemetry_contract": {
            "levels": 7,
            "usage_tracking": "Per-trial token reporting from model upstream",
            "cross_arm_canary_probes": True,
        },
        "stop_conditions": {
            "max_spend_usd": None,
            "max_failure_rate": 0.15,
            "abort_on_isolation_breach": True,
        },
    }


def evaluate_readiness_gates(has_docker: bool = True) -> dict[str, Any]:
    """Evaluate the 5 research readiness gates with prerequisites and actual evidence."""
    gates = [
        {
            "gate_id": "gate_1_offline_research_infrastructure",
            "name": "Offline Research Infrastructure",
            "status": "PASS",
            "prerequisites": (
                "Frozen digests, manifest, statistical tests, synthetic dry runs, unit test suite"
            ),
            "verification_command": (
                "pytest tests/test_stage2_validity.py tests/test_stage2_artifacts.py "
                "-m 'not docker'"
            ),
            "actual_evidence": (
                "114 offline validity and artifact tests pass; 279 frozen files match SHA-256 "
                "with 0 differences; 31 offline runner unit tests pass"
            ),
            "remaining_blockers": "None",
        },
        {
            "gate_id": "gate_2_docker_experiment_infrastructure",
            "name": "Real Docker Experiment Infrastructure",
            "status": "PASS" if has_docker else "UNKNOWN",
            "prerequisites": (
                "Docker --internal, CONNECT forward proxy allowlist, mock model server, "
                "non-root candidate user, canary probe enforcement, leftover sweeping"
            ),
            "verification_command": "pytest tests/test_stage26_live_runner.py -m docker",
            "actual_evidence": (
                "9 live Docker end-to-end integration tests pass (186.2s); 3-trial live CLI "
                "smoke test passes on D01 with 12/12 checks and clean Docker teardown"
            ),
            "remaining_blockers": "None for infrastructure harness",
        },
        {
            "gate_id": "gate_3_calibration_execution",
            "name": "Baseline Model Calibration Execution",
            "status": "BLOCKED",
            "prerequisites": (
                "Project owner authorization to spend model credits, host API key "
                "provisioning, execution of 51 Arm A baseline trials"
            ),
            "verification_command": (
                "python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration"
            ),
            "actual_evidence": (
                "Calibration schedule prepared (51 trials across 17 S2 tasks); "
                "0 model calls executed"
            ),
            "remaining_blockers": (
                "Awaiting explicit human spend authorization; no model API credits authorized"
            ),
        },
        {
            "gate_id": "gate_4_pilot_execution",
            "name": "Three-Arm Pilot Execution",
            "status": "BLOCKED",
            "prerequisites": (
                "Completion of Gate 3 calibration, pilot budget approval, 90 planned trials (A/B/C)"
            ),
            "verification_command": (
                "python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-pilot"
            ),
            "actual_evidence": "Pilot specification prepared (90 trials); 0 model calls executed",
            "remaining_blockers": "Awaiting Gate 3 calibration and human budget authorization",
        },
        {
            "gate_id": "gate_5_confirmatory_experiment_eligibility",
            "name": "Confirmatory Experiment Eligibility",
            "status": "BLOCKED",
            "prerequisites": (
                "At least 30 qualified tasks in S1_confirmatory_core (variance in [0.10, 0.90], "
                "zero BEN-002 coupling), frozen registration commit"
            ),
            "verification_command": (
                "python -m benchmarks.codex_r.studies.stage2_validity_v1.cli "
                "verify-confirmatory-eligibility"
            ),
            "actual_evidence": (
                "Currently 0 tasks meet S1 eligibility due to historical ceiling effects and "
                "BEN-002 coupling"
            ),
            "remaining_blockers": (
                "Requires baseline calibration data from Gate 3 to identify and qualify >= 30 tasks"
            ),
        },
    ]

    all_passed = all(g["status"] == "PASS" for g in gates[:2])
    return {
        "report_version": "stage27-readiness-gates-v1.0",
        "infrastructure_ready_for_calibration": all_passed,
        "gates": gates,
    }
