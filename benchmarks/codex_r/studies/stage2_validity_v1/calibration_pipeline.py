"""Stage 2.7 Calibration Pipeline, Eligibility Assessment, and Pilot Preparation.

Provides versioned, deterministic pipelines for:
1. Reconstructing and auditing task eligibility from repository evidence.
2. Generating an Arm-A-only baseline calibration schedule without paid model spend.
3. Conducting baseline-only difficulty and uncertainty assessments.
4. Defining the authorized pilot specification (gated on explicit budget authorization).
5. Evaluating the 5 formal research readiness gates.

Zero real model API calls or credentials are used in this module. Live (real-model)
calibration is fail-closed and currently unavailable; see ``live_execution_blockers``.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from . import calibration, design, manifest, records, runner, spend_control

STUDY_ROOT = Path(__file__).resolve().parent
CODEX_ROOT = STUDY_ROOT.parents[1]

# Candidate, recalibration and quarantine sets are derived from task_catalog.json (the
# provisional strata) by audit_task_eligibility(); they are deliberately not hard-coded here.
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


# Stratum meanings are the preregistered ones (manifest confirmatory_task_rule.strata):
# S1 target, S2 control (tool-use tax), RC recalibrate, Q quarantined. S1 needs a target task by
# its text (calibration.target_by_features) *and* an in-range Arm-A screen, so calibration can
# move RC tasks into S1 but never S2 controls.
STRATUM_LABELS = {
    "S1": "S1_target_confirmatory_core",
    "S2": "S2_control_tool_use_tax",
    "RC": "RC_recalibration_required",
    "Q": "Q_quarantined_scorer_revision_required",
}
# Every non-quarantined task is calibrated: RC to decide S1 membership, S2 to measure the
# baseline difficulty of the controls. Q stays out until its scorer is revised (BEN-002).
CALIBRATION_STRATA = ("RC", "S2")


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
    evaluated: list[dict[str, Any]] = []
    strata_counts = {label: 0 for label in STRATUM_LABELS.values()}

    for entry in tasks:
        tid = entry["task"]
        strat = entry.get("provisional_stratum", "Q")
        if strat not in STRATUM_LABELS:
            strat = "Q"
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

        label = STRATUM_LABELS[strat]
        strata_counts[label] += 1
        target = calibration.target_by_features(entry)
        meta = runner._task_and_scorer_meta(tid)

        evaluated.append(
            {
                "task_id": tid,
                "suite": entry.get("suite"),
                "title": entry.get("title"),
                "scorer": entry.get("scorer"),
                "task_sha256": meta["task_sha256"],
                "scorer_sha256": meta["scorer_sha256"],
                "provisional_stratum": label,
                "target_by_features": target,
                "eligible_for_confirmatory": strat == "S1",
                "eligible_for_calibration": strat in CALIBRATION_STRATA,
                "can_enter_s1_via_calibration": strat == "RC",
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
        "schema_version": "stage27-eligibility-v1.1",
        "stratum_meanings": {
            "S1": "target: MCP plausibly useful by task text and Arm-A screen in range",
            "S2": "control (tool-use tax): MCP not expected to help; can never become S1",
            "RC": "target by task text; Arm-A screen insufficient, ceiling or floor",
            "Q": "quarantined until the scorer is revised and revalidated (BEN-002)",
        },
        "total_benchmark_tasks": len(tasks),
        "strata_counts": strata_counts,
        "confirmatory_eligible_count": strata_counts[STRATUM_LABELS["S1"]],
        "control_count": strata_counts[STRATUM_LABELS["S2"]],
        "recalibration_required_count": strata_counts[STRATUM_LABELS["RC"]],
        "quarantined_count": strata_counts[STRATUM_LABELS["Q"]],
        "calibration_candidate_count": sum(1 for t in evaluated if t["eligible_for_calibration"]),
        "selection_rule": {
            "screen": "Arm A baseline observations only",
            "minimum_repetitions": 3,
            "variance_target": [0.10, 0.90],
            "mcp_arms_conditioned": False,
            "calibrated_strata": list(CALIBRATION_STRATA),
        },
        "tasks": evaluated,
    }


SCHEDULE_VERSION = "stage27-calibration-schedule-v1.1"
EXECUTOR_MODES = ("mock", "docker-mock-model", "live")
EVIDENCE_SYNTHETIC = "synthetic_not_baseline_evidence"


class LiveExecutionUnavailable(RuntimeError):
    """No real-model calibration executor exists; nothing was started or written."""

    def __init__(self, blockers: list[dict[str, Any]]) -> None:
        self.blockers = blockers
        super().__init__(
            "live calibration executor unavailable: " + "; ".join(b["id"] for b in blockers)
        )


class SyntheticEvidenceError(ValueError):
    """Synthetic or unverifiable records were offered as baseline evidence."""


def calibration_candidate_tasks() -> list[str]:
    """Tasks eligible for Arm-A calibration: catalogue strata in ``CALIBRATION_STRATA``."""
    return sorted(
        t["task_id"] for t in audit_task_eligibility()["tasks"] if t["eligible_for_calibration"]
    )


def validate_calibration_schedule(
    schedule: dict[str, Any], *, allow_ineligible_tasks: bool = False
) -> list[str]:
    """Validate structural and methodological integrity of a baseline calibration schedule.

    Pinned task/scorer digests and scorer versions are compared with the files as they are now;
    a schedule prepared against other task or scorer content is rejected before anything runs.
    ``allow_ineligible_tasks`` admits other tasks for synthetic infrastructure tests only.
    Returns a list of problems (empty if valid).
    """
    problems: list[str] = []
    if not isinstance(schedule, dict):
        return ["schedule must be a dictionary"]

    if schedule.get("schedule_version") != SCHEDULE_VERSION:
        problems.append("invalid or missing schedule_version")

    arms = schedule.get("arms")
    if arms != ["A"]:
        problems.append(f"baseline calibration schedule must specify arms=['A'], got {arms!r}")

    tasks = schedule.get("candidate_tasks")
    if not isinstance(tasks, list) or not tasks:
        problems.append("candidate_tasks must be a non-empty list")
        tasks = None
    elif len(set(tasks)) != len(tasks):
        problems.append("duplicate tasks in candidate_tasks")
    elif not allow_ineligible_tasks:
        eligible = set(calibration_candidate_tasks())
        outside = sorted(set(tasks) - eligible)
        if outside:
            problems.append(f"tasks not eligible for calibration (catalogue stratum): {outside}")

    reps = schedule.get("repetitions_per_task")
    if isinstance(reps, bool) or not isinstance(reps, int) or reps < 1:
        problems.append("repetitions_per_task must be an integer >= 1")
        reps = None

    trials = schedule.get("trials")
    if not isinstance(trials, list):
        problems.append("trials must be a list")
        return problems

    if tasks is not None and reps is not None:
        expected_count = len(tasks) * reps
        if len(trials) != expected_count:
            problems.append(
                f"expected {expected_count} trials ({len(tasks)} tasks x {reps} reps), "
                f"got {len(trials)}"
            )

    measured: dict[str, dict[str, str] | None] = {}
    trial_ids: set[str] = set()
    block_ids: set[str] = set()
    task_reps: set[tuple[Any, Any]] = set()
    indices: list[Any] = []
    shared = {"model": set(), "runtime_image": set(), "timeout_seconds": set()}
    for idx, trial in enumerate(trials, start=1):
        if not isinstance(trial, dict):
            problems.append(f"trial {idx} is not a dictionary")
            continue
        tid = trial.get("trial_id")
        if not tid:
            problems.append(f"trial {idx} missing trial_id")
        elif tid in trial_ids:
            problems.append(f"duplicate trial_id: {tid}")
        else:
            trial_ids.add(tid)
        block = trial.get("block_id")
        if not block or block in block_ids:
            problems.append(f"trial {idx} ({tid}) has a missing or duplicate block_id")
        block_ids.add(block)

        task = trial.get("task")
        if not task or (tasks is not None and task not in tasks):
            problems.append(f"trial {idx} has invalid task: {task!r}")

        arm = trial.get("arm")
        if arm != "A":
            problems.append(f"trial {idx} ({tid}) specifies arm {arm!r}, expected 'A'")

        rep = trial.get("repetition")
        if not isinstance(rep, int) or rep < 1 or (reps is not None and rep > reps):
            problems.append(f"trial {idx} ({tid}) has invalid repetition: {rep!r}")
        elif (task, rep) in task_reps:
            problems.append(f"trial {idx} ({tid}) duplicates task {task} repetition {rep}")
        task_reps.add((task, rep))

        indices.append(trial.get("execution_index"))
        if trial.get("position_in_block") != 1 or trial.get("fresh_context") is not True:
            problems.append(f"trial {idx} ({tid}) must be a fresh single-trial block")
        if isinstance(trial.get("trial_seed"), bool) or not isinstance(
            trial.get("trial_seed"), int
        ):
            problems.append(f"trial {idx} ({tid}) missing integer trial_seed")
        for key in shared:
            shared[key].add(json.dumps(trial.get(key)))

        for key in ("scorer_version", "task_sha256", "scorer_sha256"):
            if not trial.get(key):
                problems.append(f"trial {idx} ({tid}) missing required metadata key: {key}")
        if isinstance(task, str) and task not in measured:
            try:
                measured[task] = runner._task_and_scorer_meta(task)
            except ValueError:
                measured[task] = None
                problems.append(f"trial {idx} ({tid}) names unknown task {task!r}")
        current = measured.get(task) if isinstance(task, str) else None
        if current is not None:
            for key in ("scorer_version", "task_sha256", "scorer_sha256"):
                if trial.get(key) and trial.get(key) != current[key]:
                    problems.append(
                        f"trial {idx} ({tid}) {key} does not match the current repository files"
                    )

    if sorted(i for i in indices if isinstance(i, int)) != list(range(1, len(trials) + 1)):
        problems.append("execution_index values must be exactly 1..N")
    for key, values in shared.items():
        if len(values) > 1:
            problems.append(f"trials disagree on {key}")
    return problems


def build_calibration_schedule(
    seed: int = 20261028,
    *,
    tasks: list[str] | None = None,
    repetitions: int = BASELINE_REPETITIONS,
) -> dict[str, Any]:
    """Generate the deterministic Arm-A-only baseline calibration schedule.

    By default covers every calibration candidate (catalogue RC and S2) with 3 baseline
    repetitions each. ``tasks`` builds a subset (or, for infrastructure tests only, a schedule of
    other tasks that validation rejects unless explicitly allowed). No model calls are made.
    """
    candidates = sorted(tasks) if tasks is not None else calibration_candidate_tasks()
    trials: list[dict[str, Any]] = []
    trial_idx = 1

    for rep in range(1, repetitions + 1):
        for tid in candidates:
            meta = runner._task_and_scorer_meta(tid)
            trial_seed = (seed + trial_idx * 1009) & 0xFFFFFFFF
            trials.append(
                {
                    "trial_id": f"cal-A-{tid}-r{rep}-{trial_idx:03d}",
                    "block_id": f"cal-block-{trial_idx:03d}",
                    "task": tid,
                    "arm": "A",
                    "repetition": rep,
                    "execution_index": trial_idx,
                    "position_in_block": 1,
                    "fresh_context": True,
                    "scorer_version": meta["scorer_version"],
                    "task_sha256": meta["task_sha256"],
                    "scorer_sha256": meta["scorer_sha256"],
                    "randomization_seed": trial_seed,
                    "trial_seed": trial_seed,
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
        "schedule_version": SCHEDULE_VERSION,
        "study_id": "stage27_baseline_calibration",
        "status": "PREPARED_NOT_EXECUTED",
        "seed": seed,
        "candidate_source": "task_catalog.json provisional_stratum in "
        + "/".join(CALIBRATION_STRATA),
        "candidates_that_can_enter_s1": [
            t for t in candidates if calibration_strata_by_task().get(t) == "RC"
        ],
        "candidate_tasks": candidates,
        "candidate_task_count": len(candidates),
        "arms": ["A"],
        "repetitions_per_task": repetitions,
        "total_planned_trials": len(trials),
        "resource_estimates": {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "expected_wall_clock_hours": total_hours,
            "timeout_ceiling_hours": round((len(trials) * TIMEOUT_SECONDS) / 3600.0, 2),
            "basis": "planning estimates, not usage caps; no price is assumed for any model",
        },
        "model_execution_authorized": False,
        "trials": trials,
    }


def calibration_strata_by_task() -> dict[str, str]:
    catalogue = json.loads((STUDY_ROOT / "task_catalog.json").read_text(encoding="utf-8"))
    return {e["task"]: e["provisional_stratum"] for e in catalogue["tasks"]}


def schedule_to_plan(schedule: dict[str, Any]) -> dict[str, Any]:
    """Express a validated schedule as a Stage 2 plan (single-arm blocks) for the ledger."""
    canonical = json.dumps(schedule, sort_keys=True, separators=(",", ":")).encode()
    plan = {
        "study_id": schedule.get("study_id", "stage27_baseline_calibration"),
        "algorithm": "stage27-arm-a-calibration-schedule",
        "schedule_sha256": hashlib.sha256(canonical).hexdigest(),
        "seed": schedule["seed"],
        "tasks": list(schedule["candidate_tasks"]),
        "arms": ["A"],
        "repetitions": schedule["repetitions_per_task"],
        "trials": [
            {
                key: t[key]
                for key in (
                    "trial_id",
                    "block_id",
                    "task",
                    "repetition",
                    "arm",
                    "execution_index",
                    "position_in_block",
                    "fresh_context",
                    "trial_seed",
                    "task_sha256",
                    "scorer_sha256",
                )
            }
            for t in sorted(schedule["trials"], key=lambda t: t["execution_index"])
        ],
    }
    plan["plan_sha256"] = design.plan_digest(plan)
    return plan


def live_execution_blockers(schedule: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Why a real-model calibration cannot run, computed from the code that would run it."""
    from . import live_network, live_runner

    schedule = schedule if schedule is not None else build_calibration_schedule()
    blockers: list[dict[str, Any]] = []
    if live_network.WORKLOAD_SCRIPT.endswith("mock_agent.py"):
        blockers.append(
            {
                "id": "no_real_model_workload",
                "detail": (
                    f"the candidate container runs {live_network.WORKLOAD_SCRIPT} in "
                    f"{live_network.PYTHON_IMAGE}; no code path starts the agent runtime "
                    f"{schedule['trials'][0]['runtime_image']} inside the isolated topology"
                ),
            }
        )
    if live_network.MODEL_UPSTREAM_SCRIPT.endswith("mock_model_server.py"):
        blockers.append(
            {
                "id": "no_real_model_upstream_or_credential_path",
                "detail": (
                    f"the gateway tunnels {live_network.MODEL_AUTHORITY} only to the local "
                    f"{live_network.MODEL_UPSTREAM_SCRIPT}; OPENAI_API_KEY is withheld from every "
                    "container and nothing injects a real credential outside the candidate"
                ),
            }
        )
    scheduled = sorted({(t["task"], t["scorer_version"]) for t in schedule["trials"]})
    unscorable = [task for task, scorer in scheduled if not live_runner.host_scorable(task, scorer)]
    if unscorable:
        blockers.append(
            {
                "id": "scorer_container_not_integrated",
                "detail": (
                    f"{len(unscorable)} of {len(scheduled)} scheduled tasks need the R scorer "
                    "container, which the live runner does not run; they could only produce "
                    "infrastructure failures"
                ),
                "tasks": unscorable,
            }
        )
    return blockers


class _CalibrationController:
    """Spend ceiling (optional) plus the schedule's infrastructure failure-rate stop.

    The rate counts trials whose final allowed attempt was an infrastructure failure, so a
    retried attempt that later succeeds does not count; the run stops once the count exceeds
    ``max_failure_rate`` x planned trials, i.e. once the schedule can no longer meet it.
    """

    def __init__(
        self,
        guard: spend_control.SpendGuard | None,
        *,
        planned_trials: int,
        max_failure_rate: float,
        max_attempts: int,
    ) -> None:
        self.guard = guard
        self.max_infra_failures = max_failure_rate * planned_trials
        self.max_attempts = max_attempts
        self.infra_failures = 0

    def _final_infra_failure(self, attempt_index: int, outcome_kind: str) -> bool:
        return outcome_kind == "infrastructure_failure" and attempt_index >= self.max_attempts

    def restore(self, journal: list[dict[str, Any]]) -> None:
        if self.guard is not None:
            self.guard.restore(journal)
        self.infra_failures = sum(
            1
            for e in journal
            if e.get("event") == "attempt_accounted"
            and self._final_infra_failure(e["attempt_index"], e["outcome_kind"])
        )

    def before_attempt(self, trial_id: str, attempt_id: str) -> str | None:
        if self.guard is not None:
            return self.guard.before_attempt(trial_id, attempt_id)
        return None

    def after_attempt(
        self, trial_id: str, attempt_id: str, record: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        fields: dict[str, Any] = {}
        stop = None
        if self.guard is not None:
            fields, stop = self.guard.after_attempt(trial_id, attempt_id, record)
        attempt_index = int(attempt_id.rsplit("__att", 1)[1])
        if self._final_infra_failure(attempt_index, record["outcome_kind"]):
            self.infra_failures += 1
            if stop is None and self.infra_failures > self.max_infra_failures:
                stop = "max_infrastructure_failure_rate_exceeded"
        return fields, stop


def execute_calibration(
    schedule: dict[str, Any] | Path,
    out_dir: Path,
    *,
    executor_mode: str,
    authorize_spend: bool = False,
    spend_ceiling: spend_control.SpendCeiling | None = None,
    executor: runner.TrialAttemptExecutor | None = None,
    docker_settings: Any = None,
    allow_ineligible_tasks: bool = False,
) -> dict[str, Any]:
    """Execute the Arm-A-only baseline calibration schedule through the Stage 2 ledger.

    ``executor_mode``:

    * ``mock``: in-process deterministic executor (``runner.make_mock_trial_executor``).
    * ``docker-mock-model``: the real Stage 2.6 Docker topology (internal network, egress
      gateway, canary, fresh workspace) with the local mock model and mock agent.
    * ``live``: real model. Requires ``authorize_spend`` *and* a valid ``spend_ceiling``, and
      then raises ``LiveExecutionUnavailable`` listing ``live_execution_blockers()``: no
      real-model executor exists, so nothing is started and nothing is written.

    Every record produced here is synthetic and labelled so; ``evaluate_baseline_difficulty``
    refuses such records as baseline evidence. Resume, staging recovery, duplicate-line
    quarantine, retry linkage and stop conditions are the unchanged ``runner`` contracts.
    """
    if executor_mode not in EXECUTOR_MODES:
        raise ValueError(f"executor_mode must be one of {EXECUTOR_MODES}, got {executor_mode!r}")
    if isinstance(schedule, (str, Path)):
        schedule_data = json.loads(Path(schedule).read_text(encoding="utf-8"))
    else:
        schedule_data = schedule

    live = executor_mode == "live"
    if live and (allow_ineligible_tasks or executor is not None):
        raise ValueError("live execution accepts neither test executors nor ineligible tasks")
    problems = validate_calibration_schedule(
        schedule_data, allow_ineligible_tasks=allow_ineligible_tasks
    )
    if problems:
        raise ValueError(f"Invalid calibration schedule: {problems}")
    if spend_ceiling is not None and spend_ceiling.problems():
        raise ValueError(f"Invalid spend ceiling: {spend_ceiling.problems()}")

    if live:
        if not authorize_spend:
            raise RuntimeError(
                "Model execution not authorized: live mode requires --authorize-spend "
                "and an explicit spend ceiling."
            )
        if spend_ceiling is None:
            raise RuntimeError(
                "Spend authorization without a ceiling is refused: pass --max-spend-usd, "
                "--input-usd-per-mtok, --output-usd-per-mtok and --per-trial-reserve-usd."
            )
        raise LiveExecutionUnavailable(live_execution_blockers(schedule_data))
    if authorize_spend:
        raise ValueError("--authorize-spend applies only to --executor live")
    if executor_mode == "docker-mock-model" and executor is None:
        from . import live_runner

        unscorable = sorted(
            {
                t["task"]
                for t in schedule_data["trials"]
                if not live_runner.host_scorable(t["task"], t["scorer_version"])
            }
        )
        if unscorable:
            raise ValueError(
                f"docker-mock-model cannot score {len(unscorable)} of "
                f"{len(schedule_data['candidate_tasks'])} scheduled tasks {unscorable} (R scorer "
                "container not integrated); it would record only infrastructure failures"
            )

    first = schedule_data["trials"][0]
    cfg = runner.StudyExecutionConfig(
        study_id=schedule_data.get("study_id", "stage27_baseline_calibration"),
        stage=f"baseline_calibration_{executor_mode.replace('-', '_')}",
        model=first["model"],
        timeout_seconds=first["timeout_seconds"],
        max_infra_retries=first["retry_policy"]["max_retries"],
        stop_on_invalidating_violation=True,
        max_consecutive_infra_failures=first["stop_conditions"][
            "max_consecutive_infrastructure_failures"
        ],
        synthetic=True,
    )
    plan = schedule_to_plan(schedule_data)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    binding = {
        "executor_mode": executor_mode,
        "spend_ceiling": spend_ceiling.to_dict() if spend_ceiling else None,
        "evidence_status": EVIDENCE_SYNTHETIC,
        "baseline_evidence": False,
    }
    binding_path = out_dir / "calibration_run.json"
    if binding_path.exists():
        saved = json.loads(binding_path.read_text(encoding="utf-8"))
        if saved != binding:
            raise ValueError(
                "Resume rejected: executor mode or spend ceiling differs from the original run"
            )
    else:
        binding_path.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n", "utf-8")
    schedule_copy = out_dir / "schedule.json"
    if not schedule_copy.exists():
        schedule_copy.write_text(
            json.dumps(schedule_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    guard = spend_control.SpendGuard(spend_ceiling) if spend_ceiling else None
    controller = _CalibrationController(
        guard,
        planned_trials=len(plan["trials"]),
        max_failure_rate=first["stop_conditions"]["max_failure_rate"],
        max_attempts=1 + cfg.max_infra_retries,
    )
    if executor_mode == "mock":
        result = runner.execute_study_plan(
            plan,
            cfg,
            out_dir,
            executor or runner.make_mock_trial_executor(effect_b=0.0, effect_c_over_b=0.0),
            attempt_controller=controller,
        )
    else:
        from . import live_runner

        result = live_runner.execute_live_study(
            plan, cfg, out_dir, docker_settings, executor=executor, attempt_controller=controller
        )
    result.update(
        executor_mode=executor_mode,
        evidence_status=EVIDENCE_SYNTHETIC,
        total_planned=result["planned_count"],
        records_path=str(out_dir / "trial_records.jsonl"),
        journal_path=str(out_dir / "ledger_journal.jsonl"),
        spend=guard.summary() if guard else None,
    )
    return result


def load_baseline_evidence(
    records_path: Path, *, allow_synthetic: bool = False
) -> list[dict[str, Any]]:
    """Read records for baseline evaluation, refusing synthetic runs unless explicitly allowed.

    Besides each record's own ``synthetic`` flag, the run directory's ``run_config.json`` and
    ``calibration_run.json`` are consulted, so editing the flag in the JSONL alone is not enough.
    """
    records_path = Path(records_path)
    lines = records_path.read_text(encoding="utf-8").splitlines()
    recs = [json.loads(x) for x in lines if x.strip()]
    if allow_synthetic:
        return recs
    run_dir = records_path.parent
    for name, key, bad in (
        ("run_config.json", "synthetic", True),
        ("calibration_run.json", "baseline_evidence", False),
    ):
        path = run_dir / name
        if path.is_file() and json.loads(path.read_text(encoding="utf-8")).get(key) is bad:
            raise SyntheticEvidenceError(f"{name} marks this run as synthetic")
    _require_baseline_evidence(recs)
    return recs


def _require_baseline_evidence(trial_records: list[dict[str, Any]]) -> None:
    synthetic = [r.get("trial_id") for r in trial_records if r.get("synthetic") is not False]
    if synthetic:
        raise SyntheticEvidenceError(
            f"{len(synthetic)} record(s) are synthetic or lack synthetic=false "
            f"(first: {synthetic[0]!r}); they are not baseline evidence"
        )
    invalid = [r.get("trial_id") for r in trial_records if records.validate_record(r)]
    if invalid:
        raise SyntheticEvidenceError(
            f"{len(invalid)} record(s) fail the Stage 2 record schema (first: {invalid[0]!r})"
        )


def evaluate_baseline_difficulty(
    trial_records: list[dict[str, Any]],
    *,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """Calculate baseline-only difficulty, variance, and uncertainty statistics.

    Evaluates whether tasks meet the preregistered non-degeneracy condition (0.10 <= mean <= 0.90)
    using Arm A observations only. Accounts for sample-size uncertainty when R=3.

    By default every record must declare ``synthetic: false`` and satisfy the Stage 2 record
    schema; otherwise ``SyntheticEvidenceError`` is raised. ``allow_synthetic`` computes the same
    statistics for pipeline checks and labels the report as not being baseline evidence.
    """
    if not allow_synthetic:
        _require_baseline_evidence(trial_records)
    any_synthetic = any(r.get("synthetic") is not False for r in trial_records)
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
        "assessment_version": "stage27-baseline-difficulty-v1.1",
        "evidence_status": (
            EVIDENCE_SYNTHETIC if any_synthetic else "records_declared_non_synthetic"
        ),
        "baseline_evidence": not any_synthetic,
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
            "Explicit owner budget allocation with a spend ceiling, model key "
            "configuration, and a real-model live executor (none exists yet)"
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


def confirmatory_feasibility(eligibility: dict[str, Any] | None = None) -> dict[str, Any]:
    """Upper bounds on the confirmatory (S1) core given the current catalogue.

    The preregistered minimum (``manifest`` ``confirmatory_task_rule.minimum_tasks``) is read,
    never adjusted. S1 requires a target task by its text, so S2 controls cannot qualify however
    they calibrate; only RC tasks can, and Q tasks only after a scorer revision. Bounds assume
    every such task calibrates in range, which is the best case.
    """
    elig = eligibility or audit_task_eligibility()
    required = manifest.build_manifest()["confirmatory_task_rule"]["minimum_tasks"]
    s1 = elig["confirmatory_eligible_count"]
    rc = elig["recalibration_required_count"]
    q = elig["quarantined_count"]
    q_target = sum(
        1
        for t in elig["tasks"]
        if t["provisional_stratum"] == STRATUM_LABELS["Q"] and t["target_by_features"]
    )
    after_calibration = s1 + rc
    after_scorer_revision = after_calibration + q_target
    return {
        "preregistered_minimum_tasks": required,
        "catalogue_tasks": elig["total_benchmark_tasks"],
        "quarantined_tasks": q,
        "non_quarantined_tasks": elig["total_benchmark_tasks"] - q,
        "current_s1_tasks": s1,
        "control_tasks_never_s1": elig["control_count"],
        "recalibration_tasks": rc,
        "scheduled_calibration_tasks": elig["calibration_candidate_count"],
        "max_s1_after_calibration_best_case": after_calibration,
        "max_s1_if_q_scorers_are_also_revised": after_scorer_revision,
        "shortfall_after_calibration_best_case": max(0, required - after_calibration),
        "min_new_target_tasks_required": max(0, required - after_scorer_revision),
        "reachable_with_current_catalogue": after_scorer_revision >= required,
        "threshold_modified": False,
        "resolution": (
            "Add new, independently specified target tasks (S1 by task text), or amend the "
            "preregistration through a documented, dated protocol change made before any "
            "confirmatory data are seen. The threshold is not lowered to pass a gate."
        ),
    }


def execution_readiness(schedule: dict[str, Any] | None = None) -> dict[str, Any]:
    """Four separate statuses; none implies the next."""
    sched = schedule if schedule is not None else build_calibration_schedule()
    blockers = live_execution_blockers(sched)
    feasibility = confirmatory_feasibility()
    return {
        "mock_ready": {
            "status": "READY",
            "meaning": (
                "Calibration schedules run end to end through the Stage 2 ledger with the "
                "in-process mock executor and through the real Docker topology with the local "
                "mock model; every record is synthetic"
            ),
            "commands": [
                "execute-calibration --executor mock",
                "execute-calibration --executor docker-mock-model",
            ],
        },
        "live_executor_ready": {
            "status": "NOT_READY" if blockers else "READY",
            "blockers": blockers,
        },
        "calibration_authorized": {
            "status": "NOT_AUTHORIZED",
            "detail": (
                "No owner-approved spend ceiling is recorded (schedule "
                "model_execution_authorized=false). Authorization would require --authorize-spend "
                "plus an explicit ceiling, and is moot while the live executor is not ready"
            ),
        },
        "confirmatory_ready": {
            "status": "NOT_READY",
            "detail": (
                f"{feasibility['current_s1_tasks']} S1 tasks; at most "
                f"{feasibility['max_s1_after_calibration_best_case']} after calibration (RC "
                f"only; the {feasibility['control_tasks_never_s1']} S2 controls cannot qualify) "
                f"and {feasibility['max_s1_if_q_scorers_are_also_revised']} if the Q scorers are "
                "also revised, against a preregistered minimum of "
                f"{feasibility['preregistered_minimum_tasks']}"
            ),
            "feasibility": feasibility,
        },
    }


def evaluate_readiness_gates(has_docker: bool = True) -> dict[str, Any]:
    """Evaluate the 5 research readiness gates with prerequisites and actual evidence."""
    schedule = build_calibration_schedule()
    readiness = execution_readiness(schedule)
    blockers = readiness["live_executor_ready"]["blockers"]
    feasibility = readiness["confirmatory_ready"]["feasibility"]
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
                "tests/test_stage26_live_runner.py tests/test_stage27_calibration.py "
                "-m 'not docker' && python -m benchmarks.codex_r.studies.stage2_validity_v1.cli "
                "frozen --verify"
            ),
            "actual_evidence": "Recorded in STAGE27_CALIBRATION_READINESS.md section 6",
            "remaining_blockers": "None",
        },
        {
            "gate_id": "gate_2_docker_experiment_infrastructure",
            "name": "Docker Experiment Infrastructure (mock model only)",
            "status": "PASS" if has_docker else "UNKNOWN",
            "prerequisites": (
                "Docker --internal, CONNECT forward proxy allowlist, mock model server, "
                "non-root candidate user, canary probe enforcement, leftover sweeping"
            ),
            "verification_command": (
                "pytest tests/test_stage26_live_runner.py tests/test_stage27_calibration.py "
                "-m docker"
            ),
            "actual_evidence": "Recorded in STAGE27_CALIBRATION_READINESS.md section 6",
            "remaining_blockers": (
                "Covers the mock model and mock agent only; it is not evidence of a real-model "
                "executor (gate 3)"
            ),
        },
        {
            "gate_id": "gate_3_calibration_execution",
            "name": "Baseline Model Calibration Execution",
            "status": "BLOCKED",
            "prerequisites": (
                "A real-model executor inside the isolated topology, scorer-container "
                "integration for the scheduled tasks, an owner-approved spend ceiling, and "
                f"execution of the {len(schedule['trials'])} scheduled Arm A trials"
            ),
            "verification_command": (
                "python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration "
                "--executor live ... (currently exits 3: UNAVAILABLE)"
            ),
            "actual_evidence": "0 model calls executed; live mode refuses before any side effect",
            "remaining_blockers": [b["id"] for b in blockers] + ["spend_not_authorized"],
        },
        {
            "gate_id": "gate_4_pilot_execution",
            "name": "Three-Arm Pilot Execution",
            "status": "BLOCKED",
            "prerequisites": (
                "Completion of Gate 3 calibration, pilot budget approval, 90 planned trials (A/B/C)"
            ),
            "verification_command": "none: no pilot execution command exists",
            "actual_evidence": "Pilot specification prepared (90 trials); 0 model calls executed",
            "remaining_blockers": "Gate 3, the same live-executor blockers, and budget approval",
        },
        {
            "gate_id": "gate_5_confirmatory_experiment_eligibility",
            "name": "Confirmatory Experiment Eligibility",
            "status": "BLOCKED",
            "prerequisites": (
                f"At least {feasibility['preregistered_minimum_tasks']} qualified tasks in "
                "S1_confirmatory_core (Arm A mean in [0.10, 0.90], zero BEN-002 coupling), "
                "frozen registration commit"
            ),
            "verification_command": (
                "python -m benchmarks.codex_r.studies.stage2_validity_v1.cli readiness-gates"
            ),
            "actual_evidence": readiness["confirmatory_ready"]["detail"],
            "remaining_blockers": (
                "Not reachable with the current catalogue: at least "
                f"{feasibility['min_new_target_tasks_required']} new target tasks "
                "even in the best case (realistically more, after calibration attrition)"
            ),
        },
    ]

    return {
        "report_version": "stage27-readiness-gates-v1.1",
        "mock_infrastructure_ready": all(g["status"] == "PASS" for g in gates[:2]),
        "live_calibration_ready": False,
        "execution_readiness": readiness,
        "gates": gates,
    }
