"""Stage 2.5 executable study configurations, cost/runtime planning, and task backlog.

Provides the three required experimental configurations (Step 10):
  1. ``smoke_mock``: Small infrastructure smoke test using mock models (4x1x3 = 12 trials).
  2. ``pilot_real_spec``: Limited real-model pilot specification (10x2x3 = 60 trials).
  3. ``confirmatory_spec``: Confirmatory experiment specification (target 30x3x3 = 270 trials),
     explicitly gated on `len(eligible_s1_tasks) >= 30`.

Also provides the deterministic task-eligibility backlog (Step 9) mapping each of the 31
catalogue tasks to the exact offline/calibration actions required to graduate it into
`S1_confirmatory_core`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.codex_r.studies.stage2_validity_v1 import (
    design,
    manifest,
    protocol,
    runner,
)

# Observed historical duration quantiles from `historical_calibration_summary.json`:
HISTORICAL_MEDIAN_DURATION_SEC = 76.4
HISTORICAL_P90_DURATION_SEC = 186.0
MINIMUM_CONFIRMATORY_S1_TASKS = 30


def build_study_specifications() -> dict[str, Any]:
    """Return the three machine-readable Stage 2.5 experimental configurations."""
    catalog_path = Path(__file__).with_name("task_catalog.json")
    catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
    s1_tasks = [
        t["task"]
        for t in catalog_data["tasks"]
        if t.get("provisional_stratum") in {"S1", "S1_confirmatory_core"}
    ]
    s2_tasks = [
        t["task"]
        for t in catalog_data["tasks"]
        if t.get("provisional_stratum") in {"S2", "S2_calibration_needed"}
    ]
    rc_tasks = [
        t["task"]
        for t in catalog_data["tasks"]
        if t.get("provisional_stratum") in {"RC", "RC_recalibration_required"}
    ]
    q_tasks = [
        t["task"]
        for t in catalog_data["tasks"]
        if t.get("provisional_stratum") in {"Q", "Q_quarantined_or_smoke"}
    ]

    smoke_tasks = ["R03", "C03", "D01", "H10"]
    pilot_tasks = list(manifest.PILOT_TASKS.keys())  # 10 pinned pilot tasks

    def _spec_entry(
        *,
        config_id: str,
        title: str,
        tasks: list[str],
        repetitions: int,
        timeout_sec: int,
        max_infra_retries: int,
        execution_mode: str,
        ready_to_execute: bool,
        blockers: list[str],
    ) -> dict[str, Any]:
        arms = ["A", "B", "C"]
        planned_trials = len(tasks) * len(arms) * repetitions
        expected_serial_hours = round((planned_trials * HISTORICAL_MEDIAN_DURATION_SEC) / 3600.0, 2)
        p90_serial_hours = round((planned_trials * HISTORICAL_P90_DURATION_SEC) / 3600.0, 2)
        worst_case_timeout_hours = round((planned_trials * timeout_sec) / 3600.0, 2)
        return {
            "config_id": config_id,
            "title": title,
            "study_id": protocol.STUDY_ID,
            "execution_mode": execution_mode,
            "ready_to_execute": ready_to_execute,
            "blockers": blockers,
            "tasks": tasks,
            "task_count": len(tasks),
            "repetitions": repetitions,
            "arms": arms,
            "planned_trials": planned_trials,
            "model_sessions": 0 if execution_mode == "offline_mock" else planned_trials,
            "timeout_seconds_per_trial": timeout_sec,
            "wall_clock_budget": {
                "expected_serial_hours_at_median_76_4s": expected_serial_hours,
                "conservative_serial_hours_at_p90_186_0s": p90_serial_hours,
                "hard_ceiling_serial_hours_at_timeout": worst_case_timeout_hours,
            },
            "resource_requirements": {
                "executor_cpus": 2,
                "executor_memory_mb": 2048,
                "mcp_memory_mb": 512,
                "scorer_memory_mb": 2048,
                "docker_internal_network_required": True,
                "egress_proxy_required": True,
            },
            "token_measurement_limitations": (
                "Only 1 of 103 historical runs (0.97%) recorded observed API token usage "
                "(`usage.status == 'observed'`). Missing token counts must remain explicitly "
                "`unavailable` (`null`), never coerced to zero."
            ),
            "retry_allowance": {
                "max_infra_retries_per_trial": max_infra_retries,
                "candidate_failure_retried": False,
                "scoring_error_retried": False,
                "retry_linkage": (
                    "Every retry logs `retry_of_attempt_id` in `ledger_journal.jsonl`."
                ),
            },
            "stop_conditions": {
                "stop_on_invalidating_protocol_violation": True,
                "max_consecutive_infrastructure_failures": 3,
                "abort_on_corrupt_frozen_evidence_digest": True,
            },
            "estimated_cost_formula": {
                "verified_unit_prices_available": False,
                "monetary_estimate_usd": 0.0 if execution_mode == "offline_mock" else None,
                "formula": (
                    "0 USD (offline mock execution)"
                    if execution_mode == "offline_mock"
                    else (
                        "Total_Cost_USD = sum_{i=1..N_sessions} ("
                        "input_tokens_i * P_in_per_token + "
                        "cached_input_tokens_i * P_cache_per_token + "
                        "output_tokens_i * P_out_per_token"
                        "), where N_sessions = 3 * K * R * (1 + r_infra). "
                        "Monetary values are intentionally null until official `gpt-6-luna` "
                        "API unit prices and spend authorization are supplied."
                    )
                ),
            },
        }

    smoke_spec = _spec_entry(
        config_id="smoke_mock",
        title="Small Infrastructure Smoke Test (Mock Models)",
        tasks=smoke_tasks,
        repetitions=1,
        timeout_sec=60,
        max_infra_retries=1,
        execution_mode="offline_mock",
        ready_to_execute=True,
        blockers=[],
    )

    pilot_spec = _spec_entry(
        config_id="pilot_real_spec",
        title="Limited Real-Model 3-Arm Pilot Specification",
        tasks=pilot_tasks,
        repetitions=2,
        timeout_sec=300,
        max_infra_retries=1,
        execution_mode="live_model_requires_authorization",
        ready_to_execute=False,
        blockers=[
            (
                "Live Docker executor in `run_simple.py` creates a plain bridge network "
                "without `--internal` and `egress_proxy.py`."
            ),
            (
                "Live `run_simple.py` CLI only accepts 2 modes (`without-mcp`, `with-mcp`) and "
                "must be invoked through the Stage 2.5 3-arm adapter or updated to wire Arm C."
            ),
            "Paid model execution requires explicit human owner spend authorization.",
        ],
    )

    confirmatory_spec = _spec_entry(
        config_id="confirmatory_spec",
        title="Preregistered Confirmatory 3-Arm Experiment Specification",
        tasks=s1_tasks if len(s1_tasks) >= MINIMUM_CONFIRMATORY_S1_TASKS else [],
        repetitions=3,
        timeout_sec=600,
        max_infra_retries=1,
        execution_mode="live_model_requires_registration_and_authorization",
        ready_to_execute=False,
        blockers=[
            (
                f"Confirmatory eligibility requires >= {MINIMUM_CONFIRMATORY_S1_TASKS} tasks in "
                f"`S1_confirmatory_core`; currently {len(s1_tasks)} tasks qualify."
            ),
            (
                "Live container network isolation (`--internal` + `egress_proxy.py`) must be "
                "verified end-to-end before confirmatory trials."
            ),
            (
                "Preregistration commit hash must be frozen on Git before deriving the "
                "confirmatory randomization seed."
            ),
            "Paid model execution requires explicit human owner spend authorization.",
        ],
    )
    # Also record the target 30-task x 3-rep budget envelope for planning
    confirmatory_spec["target_design_envelope"] = {
        "target_tasks_k": 30,
        "target_repetitions_r": 3,
        "target_arms": 3,
        "target_planned_trials": 270,
        "target_expected_serial_hours_at_median_76_4s": round(
            (270 * HISTORICAL_MEDIAN_DURATION_SEC) / 3600.0, 2
        ),
        "target_conservative_serial_hours_at_p90_186_0s": round(
            (270 * HISTORICAL_P90_DURATION_SEC) / 3600.0, 2
        ),
    }

    backlog = [
        {
            "stratum": "S2_calibration_needed",
            "task_count": len(s2_tasks),
            "tasks": s2_tasks,
            "required_action": (
                "Run >= 3 baseline-only (Arm A) calibration trials per task under the pinned "
                "runtime image. Tasks with observed Arm A mean score in [0.10, 0.90] graduate "
                "directly to `S1_confirmatory_core` without inspecting Arm B/C outcomes."
            ),
        },
        {
            "stratum": "RC_recalibration_required",
            "task_count": len(rc_tasks),
            "tasks": rc_tasks,
            "required_action": (
                "For ceiling-saturated tasks (`C01`, `C02`, `C05`), harden edge-case requirements "
                "in a new task version. For `D01`–`D03` and `E04`–`E05` (`BEN-002`), decouple "
                "the scorer from narrow frozen package lists / extra-claim abstentions in a "
                "`knowledge-pilot-v2.2` revision, then re-screen on Arm A."
            ),
        },
        {
            "stratum": "Q_quarantined_or_smoke",
            "task_count": len(q_tasks),
            "tasks": q_tasks,
            "required_action": (
                "For `B01`–`B03` and `E02`–`E03`, execute Arm-A-only verification with the "
                "R container scorer (fixing historical `unsupported_for_automatic_scoring` runs) "
                "and harden difficulty if Arm A saturates at 1.0. For `E01`, resolve `BEN-002` "
                "extra-package abstention in `v2.2`."
            ),
        },
    ]

    return {
        "schema_version": 1,
        "study_id": protocol.STUDY_ID,
        "minimum_confirmatory_s1_tasks": MINIMUM_CONFIRMATORY_S1_TASKS,
        "current_eligible_s1_task_count": len(s1_tasks),
        "confirmatory_ready": len(s1_tasks) >= MINIMUM_CONFIRMATORY_S1_TASKS,
        "configurations": {
            "smoke_mock": smoke_spec,
            "pilot_real_spec": pilot_spec,
            "confirmatory_spec": confirmatory_spec,
        },
        "task_graduation_backlog": backlog,
    }


def run_smoke_mock_study(output_dir: Path, *, seed: int = 20261028) -> dict[str, Any]:
    """Execute the 12-trial `smoke_mock` configuration end-to-end using the mock executor."""
    specs = build_study_specifications()
    smoke = specs["configurations"]["smoke_mock"]
    plan = design.build_plan(
        tasks=smoke["tasks"],
        arms=("A", "B", "C"),
        repetitions=smoke["repetitions"],
        seed=seed,
        study_id=protocol.STUDY_ID,
    )
    cfg = runner.StudyExecutionConfig(
        study_id=protocol.STUDY_ID,
        stage="smoke_mock",
        timeout_seconds=smoke["timeout_seconds_per_trial"],
        max_infra_retries=smoke["retry_allowance"]["max_infra_retries_per_trial"],
        stop_on_invalidating_violation=True,
        synthetic=True,
    )
    executor = runner.make_mock_trial_executor(effect_b=0.25, effect_c_over_b=0.05)
    return runner.execute_study_plan(plan, cfg, output_dir, executor)
