"""Stage 2.5 three-arm study runner adapter and fault-tolerant trial ledger.

Bridges the Stage 2 experimental design (`design.py`, `protocol.py`, `records.py`,
`telemetry.py`, `isolation.py`) with a deterministic execution controller that:

1. Supports Arm A (`without-mcp`), Arm B (`with-mcp` voluntary), and Arm C
   (`with-mcp-encouraged`) without modifying legacy `run_simple.py` execution paths.
2. Executes trials strictly in the counterbalanced `execution_index` order of a
   seeded Stage 2 `plan.json` with a fresh context and isolated workspace per trial.
3. Records exact model, effort, instruction SHA-256, toolset allow-list, task
   SHA-256, scorer SHA-256, and network isolation evidence per trial.
4. Integrates canonical schema-1.2 telemetry (`telemetry.py`) with Stage 2 trial
   records (`records.py`), preserving `unavailable` usage/cost and `ordinal_unconfirmed`
   correlation status.
5. Implements reproducible interruption recovery and fault tolerance (`TrialLedger`):
   - Process interruption before trial start -> remains `not_executed` in dataset.
   - Interruption during model execution -> recorded in journal as interrupted
     attempt; materializes `not_executed` or links an explicit retry if authorized.
   - Interruption after scoring before final JSONL persistence -> recovered from
     atomic `.staging.json` commit journal without re-running the trial.
   - Partially written / truncated JSONL tail line -> quarantined into journal and
     repaired without losing earlier finalized records.
   - Duplicate trial records -> detected and deduplicated idempotently in journal.
   - Explicit retry linkage -> every retry of an `infrastructure_failure` records
     `attempt_index` and `retry_of_attempt_id` in the audit journal while keeping
     completed valid trials immutable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from benchmarks.codex_r.studies.stage2_validity_v1 import (
    calibration,
    design,
    isolation,
    manifest,
    protocol,
    records,
    scorer_bindings,
)

DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_EFFORT = "medium"
DEFAULT_TIMEOUT_SECONDS = 300


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class StudyExecutionConfig:
    """Configuration for executing a Stage 2 / 2.5 three-arm trial plan."""

    study_id: str = protocol.STUDY_ID
    stage: str = "smoke_mock"
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_infra_retries: int = 0
    stop_on_invalidating_violation: bool = False
    max_consecutive_infra_failures: int = 3
    require_egress_log: bool = True
    synthetic: bool = True
    # Violations that every trial of a declared execution environment carries (the legacy
    # runner's plain bridge network). They are still recorded and still invalidating in the
    # analysis; they only do not trigger the operational stop_on_invalidating_violation.
    structural_violation_codes: tuple[str, ...] = ()
    # Preregistration amendment applied to this run's trials (None: protocol 1.0.0) and, for A1,
    # the capability policy every trial is compared against (identical across arms).
    protocol_amendment: str | None = None
    capability_policy: dict[str, Any] | None = None

    def expected_contract(self, scorer_version: str) -> dict[str, Any]:
        base = protocol.base_instructions()
        tools = list(manifest.mcp_tool_surface()["tools"])
        return {
            "model": self.model,
            "effort": self.effort,
            "scorer_version": scorer_version,
            "base_instructions": base,
            "mcp_tools": tools,
            "require_egress_log": self.require_egress_log,
            "protocol_amendment": self.protocol_amendment,
            "capability_policy": self.capability_policy,
        }

    def to_dict(self) -> dict[str, Any]:
        # JSON form, so a resumed run compares equal to its saved run_config.json.
        return {**asdict(self), "structural_violation_codes": list(self.structural_violation_codes)}


def _task_and_scorer_meta(task_id: str) -> dict[str, str]:
    """Return suite, scorer_version, task_sha256, and scorer_sha256 for ``task_id``."""
    entry = next((e for e in calibration.CATALOG if e["task"] == task_id), None)
    if entry is None:
        raise ValueError(f"Unknown task_id: {task_id!r}")
    files = manifest.task_files(task_id)
    file_digests = {
        str(p.relative_to(manifest.ROOT)).replace("\\", "/"): manifest.digest(p) for p in files
    }
    task_sha = hashlib.sha256(
        json.dumps(file_digests, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    # The digest covers the scorer that actually executes for this task, not merely the module
    # named by the catalogue label (see scorer_bindings).
    binding = scorer_bindings.bind(task_id, entry["scorer"])
    return {
        "suite": entry["suite"],
        "scorer_version": binding.scorer_version,
        "catalogue_scorer_label": entry["scorer"],
        "task_sha256": task_sha,
        "scorer_sha256": binding.digest(),
    }


def build_trial_invocation_spec(
    planned_trial: dict[str, Any],
    config: StudyExecutionConfig,
) -> dict[str, Any]:
    """Build the exact isolated session, instruction, tool, and network spec for one trial.

    This specification is pure data and never calls a live model endpoint.
    """
    arm_id = planned_trial["arm"]
    arm = protocol.ARMS[arm_id]
    task_id = planned_trial["task"]
    task_meta = _task_and_scorer_meta(task_id)
    scorer_version = task_meta["scorer_version"]
    base_text = protocol.base_instructions()
    instructions = arm.instructions(base_text)
    instructions_sha256 = protocol.sha256_text(instructions)
    mcp_tools = list(manifest.mcp_tool_surface()["tools"])
    allowed_tools = list(mcp_tools) if arm.mcp_available else []
    net_policy = isolation.policy_for_arm(arm_id)

    session_isolation_id = hashlib.sha256(
        f"{config.study_id}|{planned_trial['trial_id']}|{planned_trial['trial_seed']}".encode()
    ).hexdigest()[:24]
    # A plan that pins digests (the calibration schedule) is authoritative: the executor
    # re-measures the files and must see these values, not ones recomputed at spec time.
    task_sha256 = planned_trial.get("task_sha256") or task_meta["task_sha256"]
    scorer_sha256 = planned_trial.get("scorer_sha256") or task_meta["scorer_sha256"]

    return {
        "trial_id": planned_trial["trial_id"],
        "block_id": planned_trial["block_id"],
        "task": task_id,
        "suite": task_meta["suite"],
        "arm": arm_id,
        "arm_label": arm.label,
        "mode": (
            "without-mcp"
            if arm_id == "A"
            else "with-mcp"
            if arm_id == "B"
            else "with-mcp-encouraged"
        ),
        "repetition": planned_trial["repetition"],
        "execution_index": planned_trial["execution_index"],
        "position_in_block": planned_trial["position_in_block"],
        "trial_seed": planned_trial["trial_seed"],
        "fresh_context": True,
        "session_isolation_id": session_isolation_id,
        "model": config.model,
        "effort": config.effort,
        "timeout_seconds": config.timeout_seconds,
        "scorer_version": scorer_version,
        "task_sha256": task_sha256,
        "scorer_sha256": scorer_sha256,
        "instructions": instructions,
        "instructions_sha256": instructions_sha256,
        "mcp_container_started": arm.mcp_available,
        "allowed_tools": allowed_tools,
        "network_policy": net_policy.to_dict(),
    }


class TrialAttemptExecutor(Protocol):
    """Protocol for an injected per-trial executor (mock offline or future live Docker)."""

    def __call__(
        self,
        invocation_spec: dict[str, Any],
        attempt_index: int,
        workspace_dir: Path,
    ) -> dict[str, Any]:
        """Execute one trial attempt and return `runner_record` + `telemetry_events`."""
        ...


class AttemptController(Protocol):
    """Optional gate around every attempt (spend ceiling, failure-rate stop).

    ``restore`` sees the whole journal before any attempt so state survives resume. A non-None
    reason from ``before_attempt`` refuses the attempt; ``after_attempt`` returns journal fields
    and an optional stop reason. Both stop the run fail-closed.
    """

    def restore(self, journal: list[dict[str, Any]]) -> None: ...

    def before_attempt(self, trial_id: str, attempt_id: str) -> str | None: ...

    def after_attempt(
        self, trial_id: str, attempt_id: str, record: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]: ...


class InterruptionSimulated(KeyboardInterrupt):
    """Raised by deterministic fault-injection tests to simulate process interruption."""


class TrialLedger:
    """Durable, fault-tolerant ledger for Stage 2.5 trial execution and resume.

    Files managed inside ``run_dir``:
      - ``plan.json``: immutable copy of the randomized trial plan.
      - ``run_config.json``: immutable copy of ``StudyExecutionConfig``.
      - ``trial_records.jsonl``: finalized Stage 2 trial records (at most 1 per `trial_id`).
      - ``ledger_journal.jsonl``: append-only audit log of every attempt, interruption,
        staging recovery, corrupt-tail quarantine, duplicate detection, and retry link.
      - ``staging/<trial_id>.staging.json``: per-trial atomic commit staging marker.
    """

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.staging_dir = self.run_dir / "staging"
        self.plan_path = self.run_dir / "plan.json"
        self.config_path = self.run_dir / "run_config.json"
        self.records_path = self.run_dir / "trial_records.jsonl"
        self.journal_path = self.run_dir / "ledger_journal.jsonl"

    def initialize_or_verify(self, plan: dict[str, Any], config: StudyExecutionConfig) -> None:
        problems = design.verify_plan(plan)
        if problems:
            raise ValueError(f"Invalid study plan: {problems}")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        if self.plan_path.exists():
            saved_plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
            if saved_plan.get("plan_sha256") != plan.get("plan_sha256"):
                raise ValueError("Resume rejected: saved plan_sha256 differs from current plan")
        else:
            self.plan_path.write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

        if self.config_path.exists():
            saved_cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
            if saved_cfg != config.to_dict():
                raise ValueError(
                    "Resume rejected: saved run_config.json differs from current config"
                )
        else:
            self.config_path.write_text(
                json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    def emit_journal(self, event: str, **fields: Any) -> dict[str, Any]:
        entry = {"timestamp_utc": _utc_now(), "event": event, **fields}
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def journal_events(self) -> list[dict[str, Any]]:
        if not self.journal_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def write_staging(self, trial_id: str, payload: dict[str, Any]) -> Path:
        path = self.staging_dir / f"{trial_id}.staging.json"
        tmp = self.staging_dir / f"{trial_id}.staging.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path

    def clear_staging(self, trial_id: str) -> None:
        path = self.staging_dir / f"{trial_id}.staging.json"
        if path.exists():
            path.unlink()

    def write_attempt_evidence(self, attempt_id: str, payload: dict[str, Any]) -> None:
        """Keep the raw runner output of every attempt (failed ones included) for diagnosis."""
        directory = self.run_dir / "attempts"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{attempt_id}.json"
        tmp = directory / f"{attempt_id}.json.tmp"
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
        tmp.replace(path)

    def append_finalized_record(self, record: dict[str, Any]) -> None:
        problems = records.validate_record(record)
        if problems:
            raise ValueError(
                f"Refusing to persist invalid trial record {record.get('trial_id')}: {problems}"
            )
        with self.records_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def recover(self, plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Recover finalized records, quarantine corrupt tails, and commit scored staging files."""
        planned_ids = {t["trial_id"] for t in plan["trials"]}
        finalized: dict[str, dict[str, Any]] = {}
        needs_rewrite = False

        if self.records_path.exists():
            raw_lines = self.records_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for idx, line in enumerate(raw_lines, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rec = json.loads(stripped)
                except json.JSONDecodeError:
                    needs_rewrite = True
                    self.emit_journal(
                        "corrupt_jsonl_line_quarantined",
                        line_number=idx,
                        byte_length=len(stripped),
                    )
                    continue
                if not isinstance(rec, dict) or rec.get("trial_id") not in planned_ids:
                    needs_rewrite = True
                    self.emit_journal(
                        "unexpected_jsonl_record_quarantined",
                        line_number=idx,
                        trial_id=rec.get("trial_id") if isinstance(rec, dict) else None,
                    )
                    continue
                problems = records.validate_record(rec)
                if problems:
                    needs_rewrite = True
                    self.emit_journal(
                        "invalid_jsonl_record_quarantined",
                        line_number=idx,
                        trial_id=rec.get("trial_id"),
                        problems=problems,
                    )
                    continue
                tid = rec["trial_id"]
                if tid in finalized:
                    needs_rewrite = True
                    self.emit_journal(
                        "duplicate_trial_record_detected",
                        line_number=idx,
                        trial_id=tid,
                    )
                    continue
                finalized[tid] = rec

            if needs_rewrite:
                tmp = self.records_path.with_suffix(".jsonl.tmp")
                with tmp.open("w", encoding="utf-8") as handle:
                    for rec in finalized.values():
                        handle.write(json.dumps(rec, sort_keys=True) + "\n")
                tmp.replace(self.records_path)

        # Inspect staging files for interrupted trials
        if self.staging_dir.exists():
            for staging_file in sorted(self.staging_dir.glob("*.staging.json")):
                try:
                    staged = json.loads(staging_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self.emit_journal("corrupt_staging_file_removed", file=staging_file.name)
                    staging_file.unlink(missing_ok=True)
                    continue
                tid = staged.get("trial_id")
                stage = staged.get("stage")
                attempt_id = staged.get("attempt_id")
                attempt_index = staged.get("attempt_index", 1)
                if not isinstance(tid, str) or tid not in planned_ids:
                    staging_file.unlink(missing_ok=True)
                    continue
                if tid in finalized:
                    # Already persisted in trial_records.jsonl before crash; clean up staging.
                    self.emit_journal(
                        "staging_already_finalized_cleaned",
                        trial_id=tid,
                        attempt_id=attempt_id,
                    )
                    staging_file.unlink(missing_ok=True)
                    continue
                if stage == "scored_pending_commit" and isinstance(staged.get("record"), dict):
                    rec = staged["record"]
                    if not records.validate_record(rec):
                        self.append_finalized_record(rec)
                        finalized[tid] = rec
                        self.emit_journal(
                            "recovered_scored_pending_commit",
                            trial_id=tid,
                            attempt_id=attempt_id,
                            attempt_index=attempt_index,
                        )
                        staging_file.unlink(missing_ok=True)
                        continue
                # Otherwise interrupted during `executing` before scoring finished:
                self.emit_journal(
                    "interrupted_attempt_detected",
                    trial_id=tid,
                    stage=stage,
                    attempt_id=attempt_id,
                    attempt_index=attempt_index,
                )
                staging_file.unlink(missing_ok=True)

        return finalized

    def previous_attempts_for(self, trial_id: str) -> list[dict[str, Any]]:
        return [
            e
            for e in self.journal_events()
            if e.get("trial_id") == trial_id and e.get("event") == "trial_attempt_started"
        ]


def make_not_executed_record(
    planned_trial: dict[str, Any],
    config: StudyExecutionConfig,
) -> dict[str, Any]:
    """Build a valid Stage 2 `not_executed` record for a trial that never ran or was interrupted."""
    spec = build_trial_invocation_spec(planned_trial, config)
    expected = config.expected_contract(spec["scorer_version"])
    evidence = {
        "allowed_tools": spec["allowed_tools"],
        "mcp_container_started": spec["mcp_container_started"],
        "mcp_calls_observed": 0,
        "instructions_sha256": spec["instructions_sha256"],
        "model": config.model,
        "effort": config.effort,
        "scorer_version": spec["scorer_version"],
        "network_internal": True,
        "egress_destinations": [protocol.MODEL_ENDPOINT],
    }
    violations = protocol.capability_violations(planned_trial["arm"], evidence, expected)
    return {
        "trial_id": planned_trial["trial_id"],
        "block_id": planned_trial["block_id"],
        "task": planned_trial["task"],
        "arm": planned_trial["arm"],
        "repetition": planned_trial["repetition"],
        "execution_index": planned_trial["execution_index"],
        "model": config.model,
        "effort": config.effort,
        "scorer_version": spec["scorer_version"],
        "outcome_kind": "not_executed",
        "score": None,
        "checks_passed": None,
        "checks_total": None,
        "mcp": {
            "available": spec["mcp_container_started"],
            "listed": False,
            "attempted": 0,
            "completed": 0,
            "errored": 0,
            "server_calls": 0,
            "delivered": 0,
            "useful_bytes": 0,
            "correlation": "not_applicable",
            "egress_destinations": [protocol.MODEL_ENDPOINT],
        },
        "usage": {"status": "unavailable"},
        "violations": [v.as_dict() for v in violations],
        "synthetic": config.synthetic,
    }


def execute_study_plan(
    plan: dict[str, Any],
    config: StudyExecutionConfig,
    run_dir: Path,
    executor: TrialAttemptExecutor,
    *,
    before_commit_hook: Callable[[str, int], None] | None = None,
    attempt_controller: AttemptController | None = None,
) -> dict[str, Any]:
    """Execute or resume a Stage 2 / 2.5 study plan using an injected ``executor``.

     guarantees:
    - Completed valid trials already in ``trial_records.jsonl`` are never re-executed.
    - Trials interrupted after scoring (`scored_pending_commit`) are committed on
      recovery without re-invoking ``executor``.
    - Infrastructure failures may be retried up to ``config.max_infra_retries`` times;
      each retry is linked to the prior `attempt_id` in ``ledger_journal.jsonl``.
    - Candidate failures (`outcome_kind == "candidate_failure"`) are NEVER retried
      because they are outcomes of the evaluated condition (ITT score 0.0).
    - Every planned trial has a valid record in the returned dataset (`not_executed`
      if stopped early or interrupted).
    - An ``attempt_controller`` may refuse an attempt or stop the run after one; a refused
      retry commits the preceding infrastructure failure instead of dropping it.
    """
    ledger = TrialLedger(run_dir)
    ledger.initialize_or_verify(plan, config)
    finalized = ledger.recover(plan)
    if attempt_controller is not None:
        attempt_controller.restore(ledger.journal_events())

    ordered_trials = sorted(plan["trials"], key=lambda t: t["execution_index"])
    consecutive_infra_failures = 0
    stopped_reason: str | None = None
    interrupted = False

    for planned_trial in ordered_trials:
        tid = planned_trial["trial_id"]
        if tid in finalized:
            ledger.emit_journal("trial_skipped_already_finalized", trial_id=tid)
            continue

        if stopped_reason is not None:
            continue

        prior_attempts = ledger.previous_attempts_for(tid)
        prior_attempt_id = prior_attempts[-1]["attempt_id"] if prior_attempts else None
        max_attempts = 1 + max(0, config.max_infra_retries)
        start_attempt_idx = len(prior_attempts) + 1

        # If a previous run already exhausted all allowed attempts via interruption,
        # materialize an explicit `not_executed` record unless retries remain.
        if start_attempt_idx > max_attempts:
            rec = make_not_executed_record(planned_trial, config)
            ledger.append_finalized_record(rec)
            finalized[tid] = rec
            ledger.emit_journal(
                "trial_materialized_not_executed_after_interruption",
                trial_id=tid,
                prior_attempts=len(prior_attempts),
            )
            continue

        pending: tuple[str, int, dict[str, Any]] | None = None
        for attempt_idx in range(start_attempt_idx, max_attempts + 1):
            attempt_id = f"{tid}__att{attempt_idx:02d}"
            if attempt_controller is not None:
                refusal = attempt_controller.before_attempt(tid, attempt_id)
                if refusal is not None:
                    ledger.emit_journal(
                        "attempt_refused_by_controller",
                        trial_id=tid,
                        attempt_id=attempt_id,
                        attempt_index=attempt_idx,
                        reason=refusal,
                    )
                    stopped_reason = refusal
                    if pending is not None:
                        prev_id, prev_idx, prev_rec = pending
                        ledger.append_finalized_record(prev_rec)
                        finalized[tid] = prev_rec
                        ledger.emit_journal(
                            "trial_attempt_committed",
                            trial_id=tid,
                            attempt_id=prev_id,
                            attempt_index=prev_idx,
                            outcome_kind=prev_rec["outcome_kind"],
                            score=prev_rec["score"],
                            committed_because=refusal,
                        )
                    break
            spec = build_trial_invocation_spec(planned_trial, config)
            workspace_dir = ledger.run_dir / "workspaces" / attempt_id
            workspace_dir.mkdir(parents=True, exist_ok=True)

            ledger.write_staging(
                tid,
                {
                    "trial_id": tid,
                    "attempt_id": attempt_id,
                    "attempt_index": attempt_idx,
                    "retry_of_attempt_id": prior_attempt_id,
                    "stage": "executing",
                    "started_at_utc": _utc_now(),
                },
            )
            ledger.emit_journal(
                "trial_attempt_started",
                trial_id=tid,
                attempt_id=attempt_id,
                attempt_index=attempt_idx,
                retry_of_attempt_id=prior_attempt_id,
                arm=planned_trial["arm"],
                task=planned_trial["task"],
                repetition=planned_trial["repetition"],
            )

            try:
                raw_out = executor(spec, attempt_idx, workspace_dir)
                runner_record = raw_out["runner_record"]
                telemetry_events = raw_out.get("telemetry_events", [])
                ledger.write_attempt_evidence(
                    attempt_id,
                    {
                        "attempt_id": attempt_id,
                        "retry_of_attempt_id": prior_attempt_id,
                        "runner_record": runner_record,
                        "telemetry_events": telemetry_events,
                    },
                )
                expected = config.expected_contract(spec["scorer_version"])
                stage2_rec = records.from_runner_result(
                    planned_trial,
                    runner_record,
                    telemetry_events,
                    expected,
                )
                stage2_rec["synthetic"] = config.synthetic
                # Verify task/scorer digest integrity if reported by executor
                if (
                    "task_sha256" in runner_record
                    and runner_record["task_sha256"] != spec["task_sha256"]
                ):
                    stage2_rec["violations"].append(
                        {
                            "code": "task_hash_mismatch",
                            "detail": "observed task_sha256 differs from pinned catalogue digest",
                            "invalidating": True,
                        }
                    )
                if (
                    "scorer_sha256" in runner_record
                    and runner_record["scorer_sha256"] != spec["scorer_sha256"]
                ):
                    stage2_rec["violations"].append(
                        {
                            "code": "scorer_hash_mismatch",
                            "detail": "observed scorer_sha256 differs from pinned catalogue digest",
                            "invalidating": True,
                        }
                    )

                controller_stop: str | None = None
                if attempt_controller is not None:
                    accounting, controller_stop = attempt_controller.after_attempt(
                        tid, attempt_id, stage2_rec
                    )
                    ledger.emit_journal(
                        "attempt_accounted",
                        trial_id=tid,
                        attempt_id=attempt_id,
                        attempt_index=attempt_idx,
                        outcome_kind=stage2_rec["outcome_kind"],
                        stop_reason=controller_stop,
                        **accounting,
                    )

                ledger.write_staging(
                    tid,
                    {
                        "trial_id": tid,
                        "attempt_id": attempt_id,
                        "attempt_index": attempt_idx,
                        "retry_of_attempt_id": prior_attempt_id,
                        "stage": "scored_pending_commit",
                        "record": stage2_rec,
                    },
                )
                if before_commit_hook is not None:
                    before_commit_hook(tid, attempt_idx)

            except KeyboardInterrupt:
                interrupted = True
                stopped_reason = "interrupted_by_signal"
                ledger.emit_journal(
                    "trial_attempt_interrupted",
                    trial_id=tid,
                    attempt_id=attempt_id,
                    attempt_index=attempt_idx,
                )
                break

            outcome_kind = stage2_rec["outcome_kind"]
            primary_code = (
                (runner_record.get("error_summary") or {}).get("primary_error") or {}
            ).get("source_code")
            if (
                outcome_kind == "infrastructure_failure"
                and attempt_idx < max_attempts
                and controller_stop is None
            ):
                pending = (attempt_id, attempt_idx, stage2_rec)
                ledger.emit_journal(
                    "trial_attempt_infra_failure_retrying",
                    trial_id=tid,
                    attempt_id=attempt_id,
                    attempt_index=attempt_idx,
                    next_attempt_index=attempt_idx + 1,
                    primary_error_code=primary_code,
                )
                prior_attempt_id = attempt_id
                ledger.clear_staging(tid)
                continue

            # Commit finalized record
            ledger.append_finalized_record(stage2_rec)
            ledger.clear_staging(tid)
            finalized[tid] = stage2_rec
            ledger.emit_journal(
                "trial_attempt_committed",
                trial_id=tid,
                attempt_id=attempt_id,
                attempt_index=attempt_idx,
                retry_of_attempt_id=prior_attempt_id,
                outcome_kind=outcome_kind,
                primary_error_code=primary_code,
                score=stage2_rec["score"],
                invalidating_violations=sum(
                    1 for v in stage2_rec["violations"] if v.get("invalidating")
                ),
            )

            if outcome_kind == "infrastructure_failure":
                consecutive_infra_failures += 1
            else:
                consecutive_infra_failures = 0

            if config.stop_on_invalidating_violation and any(
                v.get("invalidating") and v.get("code") not in config.structural_violation_codes
                for v in stage2_rec["violations"]
            ):
                stopped_reason = f"invalidating_protocol_violation_in_{tid}"
            elif controller_stop is not None:
                stopped_reason = controller_stop
            elif consecutive_infra_failures >= config.max_consecutive_infra_failures:
                stopped_reason = "max_consecutive_infrastructure_failures_exceeded"
            break

        if interrupted:
            break

    # Build the complete dataset in planned execution_index order, filling any
    # unreached trials with explicit `not_executed` records.
    complete_dataset: list[dict[str, Any]] = []
    for planned_trial in ordered_trials:
        tid = planned_trial["trial_id"]
        if tid in finalized:
            complete_dataset.append(finalized[tid])
        else:
            complete_dataset.append(make_not_executed_record(planned_trial, config))

    dataset_problems = records.validate_dataset(
        complete_dataset, [t["trial_id"] for t in ordered_trials]
    )
    return {
        "study_id": config.study_id,
        "stage": config.stage,
        "synthetic": config.synthetic,
        "interrupted": interrupted,
        "stopped_reason": stopped_reason,
        "finalized_count": len(finalized),
        "planned_count": len(ordered_trials),
        "dataset_problems": dataset_problems,
        "records": complete_dataset,
    }


def make_mock_trial_executor(
    *,
    effect_b: float = 0.25,
    effect_c_over_b: float = 0.05,
    fail_trial_attempts: dict[tuple[str, int], str] | None = None,
    interrupt_on: set[tuple[str, int]] | None = None,
    leak_mcp_in_arm_a_trials: set[str] | None = None,
) -> TrialAttemptExecutor:
    """Create a deterministic offline mock trial executor for testing Stage 2.5 end-to-end.

    Simulates Arm A, Arm B, and Arm C execution, workspace preparation, schema-1.2
    telemetry event streams, and scorer outcomes without network or model API calls.
    """
    failures = fail_trial_attempts or {}
    interrupts = interrupt_on or set()
    leaks = leak_mcp_in_arm_a_trials or set()

    def _execute(
        spec: dict[str, Any],
        attempt_index: int,
        workspace_dir: Path,
    ) -> dict[str, Any]:
        tid = spec["trial_id"]
        arm = spec["arm"]
        if (tid, attempt_index) in interrupts:
            raise InterruptionSimulated(
                f"Simulated interruption during {tid} attempt {attempt_index}"
            )

        # Write deterministic candidate workspace marker
        (workspace_dir / "TASK_SHA256.txt").write_text(spec["task_sha256"], encoding="utf-8")

        forced_mode = failures.get((tid, attempt_index))
        leaked = arm == "A" and tid in leaks
        mcp_started = spec["mcp_container_started"] or leaked
        allowed_tools = (
            list(manifest.mcp_tool_surface()["tools"]) if leaked else spec["allowed_tools"]
        )

        events: list[dict[str, Any]] = []
        egress_destinations = [protocol.MODEL_ENDPOINT]

        if mcp_started:
            events.append(
                {
                    "event_type": "mcp.discovery.completed",
                    "source": "mcp_server",
                    "list_tools_requests": 1,
                }
            )
            should_call = arm == "C" or (arm == "B" and spec["trial_seed"] % 3 != 0) or leaked
            if should_call:
                cid = f"call-{tid}-{attempt_index}"
                events.extend(
                    [
                        {
                            "event_type": "mcp.tool.started",
                            "source": "agent_stream",
                            "call_id": cid,
                            "tool": "get_package_docs",
                            "sequence": 1,
                        },
                        {
                            "event_type": "mcp.tool.completed",
                            "source": "agent_stream",
                            "call_id": cid,
                            "tool": "get_package_docs",
                            "is_error": False,
                            "sequence": 2,
                        },
                        {
                            "event_type": "mcp.tool.completed",
                            "source": "mcp_server",
                            "call_id": f"srv-{cid}",
                            "tool": "get_package_docs",
                            "is_error": False,
                            "response_bytes": 2048,
                            "useful_bytes": 1800,
                            "sequence": 1,
                        },
                    ]
                )
                egress_destinations.append(protocol.MCP_ENDPOINT)

        total_checks = 4
        rng = design.seeded(spec["trial_seed"], "mock-score", tid)
        base_prob = 0.45 + 0.15 * rng.random()
        if arm == "B":
            prob = min(0.95, base_prob + effect_b)
        elif arm == "C":
            prob = min(0.98, base_prob + effect_b + effect_c_over_b)
        else:
            prob = base_prob
        passed_checks = sum(1 for _ in range(total_checks) if rng.random() < prob)

        if forced_mode == "infrastructure_failure":
            status = "error"
            score_obj = None
            err_summary = {
                "primary_error": {
                    "origin": "runner",
                    "category": "docker",
                    "source_code": "docker_daemon_unavailable",
                }
            }
        elif forced_mode == "candidate_failure":
            status = "error"
            score_obj = None
            err_summary = {
                "primary_error": {
                    "origin": "candidate",
                    "category": "artifact",
                    "source_code": "candidate_artifact_missing",
                }
            }
        elif forced_mode == "scoring_error":
            status = "unsupported_for_automatic_scoring"
            score_obj = None
            err_summary = {
                "primary_error": {
                    "origin": "scorer",
                    "category": "scorer",
                    "source_code": "unsupported_for_automatic_scoring",
                }
            }
        else:
            status = "scored"
            score_obj = {
                "status": "scored",
                "passed": passed_checks,
                "total": total_checks,
                "fully_correct": passed_checks == total_checks,
            }
            err_summary = {"primary_error": None}

        runner_record = {
            "trial_id": tid,
            "task": spec["task"],
            "mode": spec["mode"],
            "repetition": spec["repetition"],
            "model": spec["model"],
            "effort": spec["effort"],
            "scorer_identity": spec["scorer_version"],
            "task_sha256": spec["task_sha256"],
            "scorer_sha256": spec["scorer_sha256"],
            "status": status,
            "score": score_obj,
            "error_summary": err_summary,
            "allowed_tools": allowed_tools,
            "mcp_container_started": mcp_started,
            "agent_instructions_sha256": spec["instructions_sha256"],
            "network_internal": True,
            "egress_destinations": egress_destinations,
            "proxy_entries": None,
            "usage_status": "observed",
            "usage": {"input_tokens": 1200 + attempt_index * 10, "output_tokens": 350},
        }
        return {"runner_record": runner_record, "telemetry_events": events}

    return _execute
