"""Fail-closed single-trial execution readiness and offline lifecycle checks.

This module intentionally does not launch Codex. The current workstation has no
verified isolated Codex runtime, credential broker, restricted egress route, or
candidate-visible recording gateway. `run-one` therefore remains blocked until a
separately verified backend supplies all of those controls.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
_PILOT_SPEC = importlib.util.spec_from_file_location(
    "codex_r_exploratory_pilot", ROOT / "exploratory" / "pilot.py"
)
if _PILOT_SPEC is None or _PILOT_SPEC.loader is None:
    raise RuntimeError("Exploratory pilot module could not be loaded")
pilot = importlib.util.module_from_spec(_PILOT_SPEC)
_PILOT_SPEC.loader.exec_module(pilot)


def _load_controller():
    spec = importlib.util.spec_from_file_location(
        "codex_r_single_trial_controller", ROOT / "runner" / "controller.py"
    )
    if spec is None or spec.loader is None:
        raise AdapterError("Benchmark controller could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTROLLER_VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_EVENT_LINE_BYTES = 1 << 20
MAX_EVENT_STREAM_BYTES = 32 << 20
MAX_EVENT_COUNT = 100_000
MAX_AUTHORIZATION_TTL_SECONDS = 300
RECOVERY_ATTEMPT_ID = "R01-A/recovery-after-attempt-2"
FINAL_CONTINUATION_ATTEMPT_ID = "R01-A/final-continuation"
SESSION_QUIESCENCE_SOURCE = "https://api.openai.com/v1/agents/sessions"
SESSION_QUIESCENCE_CONFIRMATION = "CONFIRM NO ACTIVE MANAGED AGENTS SESSIONS R01-A"
SESSION_QUIESCENCE_MAX_AGE_SECONDS = 300
INTERNAL_PROBE_FLAG = "--internal-local-timeout-probe"
SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[^\s,;]+"),
)
SECRET_KEY = re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)")


class AdapterError(ValueError):
    """Invalid single-trial input or a blocked execution request."""


def default_state_directory() -> Path:
    """Use one fixed per-user WSL state root so a new path cannot replay R01-A."""
    return Path.home() / ".local" / "state" / "r-knowledge-mcp" / "r01a"


def redact(value):
    """Return JSON-safe evidence with common credential-shaped values removed."""
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    return value


def parse_jsonl_events(data: bytes) -> list[dict]:
    """Parse bounded complete JSONL events; reject corrupt/truncated records."""
    if not isinstance(data, bytes) or len(data) > MAX_EVENT_STREAM_BYTES:
        raise AdapterError("Codex event stream exceeds its byte limit")
    if data and not data.endswith(b"\n"):
        raise AdapterError("Codex event stream ends with a partial JSONL record")
    events = []
    for line in data.splitlines():
        if not line:
            continue
        if len(line) > MAX_EVENT_LINE_BYTES:
            raise AdapterError("Codex event line exceeds its byte limit")
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdapterError("Codex event stream contains invalid JSONL") from exc
        if not isinstance(event, dict):
            raise AdapterError("Codex event records must be JSON objects")
        events.append(redact(event))
        if len(events) > MAX_EVENT_COUNT:
            raise AdapterError("Codex event stream exceeds its event-count limit")
    return events


def environment_fingerprint(task_id: str) -> str:
    """Hash only reviewed benchmark inputs that determine one candidate runtime."""
    task = pilot.bench.task_for(task_id)
    paths = [
        ROOT / "manifest.json",
        ROOT / "configs" / "Dockerfile",
        ROOT / "configs" / "renv.lock",
        ROOT / task["spec"],
        ROOT / task["fixture"],
    ]
    digest = hashlib.sha256()
    for path in paths:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(ROOT.resolve()):
            raise AdapterError("Fingerprint input escaped the benchmark root")
        digest.update(resolved.relative_to(ROOT.resolve()).as_posix().encode())
        digest.update(b"\0")
        digest.update(resolved.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def execution_configuration_fingerprint() -> str:
    """Bind authorization to the reviewed Codex image recipe and Docker policy."""
    digest = hashlib.sha256()
    for path in (
        ROOT / "runtime" / "candidate.Dockerfile",
        ROOT / "exploratory" / "docker_runtime.py",
        ROOT / "exploratory" / "egress_proxy.py",
        ROOT / "exploratory" / "managed_agents.py",
        ROOT / "exploratory" / "executor_contract.py",
        ROOT / "exploratory" / "lifecycle.py",
        Path(__file__).resolve(),
    ):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(ROOT.resolve()):
            raise AdapterError("Execution configuration escaped the benchmark root")
        digest.update(resolved.relative_to(ROOT.resolve()).as_posix().encode())
        digest.update(b"\0")
        digest.update(resolved.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_trial_context(
    plan: dict,
    trial_id: str,
    workspace: Path | None = None,
    *,
    candidate_image_digest: str | None = None,
    state_directory: Path | None = None,
    attempt_id: str = "R01-A/attempt-1",
    previous_attempt_result: Path | None = None,
    first_attempt_result: Path | None = None,
    previous_attempt_authorization: Path | None = None,
    first_attempt_authorization: Path | None = None,
    attempt_two_result: Path | None = None,
    attempt_two_authorization: Path | None = None,
    session_quiescence_evidence: Path | None = None,
) -> dict:
    """Resolve one exploratory assignment and bind its exact control values."""
    pilot.validate_plan(plan)
    selected = next((row for row in plan["trials"] if row["trial_id"] == trial_id), None)
    if selected is None:
        raise AdapterError("Trial ID is not assigned by the nine-trial pilot plan")
    if candidate_image_digest is not None and not re.fullmatch(
        r"sha256:[a-f0-9]{64}", candidate_image_digest
    ):
        raise AdapterError("Candidate image must be identified by an immutable sha256 digest")
    expected_tools = set(pilot.bench.manifest()["conditions"][selected["condition"]]["tools"])
    if attempt_id not in {
        "R01-A/attempt-1",
        "R01-A/attempt-2",
        RECOVERY_ATTEMPT_ID,
        FINAL_CONTINUATION_ATTEMPT_ID,
    }:
        raise AdapterError(
            "Only the first two attempts or one separately authorized recovery are supported"
        )
    previous_audit_sha256 = None
    previous_failure_classification = None
    previous_provider_status = None
    recovery_first_audit_sha256 = None
    previous_authorization_sha256 = None
    final_provenance = None
    if attempt_id == "R01-A/attempt-2":
        if previous_attempt_result is None:
            raise AdapterError("Attempt 2 requires the preserved first-attempt cleanup audit")
        prior_failure = _verify_first_attempt_for_retry(
            state_directory or default_state_directory(), previous_attempt_result
        )
        previous_failure_classification = prior_failure["classification"]
        previous_provider_status = prior_failure["provider_status"]
        previous_audit_sha256 = hashlib.sha256(
            Path(previous_attempt_result).read_bytes()
        ).hexdigest()
    elif attempt_id == RECOVERY_ATTEMPT_ID:
        if (
            not first_attempt_result
            or not previous_attempt_result
            or not previous_attempt_authorization
        ):
            raise AdapterError(
                "Recovery requires both preserved audits and the expired attempt-2 authorization"
            )
        recovery = _verify_attempt_two_for_recovery(
            state_directory or default_state_directory(),
            Path(first_attempt_result),
            Path(previous_attempt_result),
            Path(previous_attempt_authorization),
        )
        previous_audit_sha256 = recovery["attempt_two_audit_sha256"]
        recovery_first_audit_sha256 = recovery["first_audit_sha256"]
        previous_authorization_sha256 = recovery["authorization_sha256"]
        previous_failure_classification = "attempt_two_pre_session_local_failure"
        previous_provider_status = "not_contacted"
    elif attempt_id == FINAL_CONTINUATION_ATTEMPT_ID:
        paths = (
            first_attempt_result,
            first_attempt_authorization,
            attempt_two_result,
            attempt_two_authorization,
            previous_attempt_result,
            previous_attempt_authorization,
            session_quiescence_evidence,
        )
        if any(path is None for path in paths):
            raise AdapterError(
                "Final continuation requires all prior audits, authorizations, and session evidence"
            )
        final_provenance = _verify_final_continuation_provenance(
            state_directory or default_state_directory(),
            Path(first_attempt_result),
            Path(first_attempt_authorization),
            Path(attempt_two_result),
            Path(attempt_two_authorization),
            Path(previous_attempt_result),
            Path(previous_attempt_authorization),
            Path(session_quiescence_evidence),
        )
    context = {
        "trial_id": selected["trial_id"],
        "attempt_id": attempt_id,
        "previous_attempt_audit_sha256": previous_audit_sha256,
        "previous_attempt_failure_classification": previous_failure_classification,
        "previous_attempt_provider_status": previous_provider_status,
        "recovery_first_attempt_audit_sha256": recovery_first_audit_sha256,
        "previous_attempt_authorization_sha256": previous_authorization_sha256,
        "final_continuation_provenance": final_provenance,
        "previous_attempt_result": (
            str(Path(previous_attempt_result).resolve())
            if previous_attempt_result is not None
            else None
        ),
        "first_attempt_result": (
            str(Path(first_attempt_result).resolve()) if first_attempt_result is not None else None
        ),
        "previous_attempt_authorization": (
            str(Path(previous_attempt_authorization).resolve())
            if previous_attempt_authorization is not None
            else None
        ),
        "first_attempt_authorization": str(Path(first_attempt_authorization).resolve())
        if first_attempt_authorization
        else None,
        "attempt_two_result": str(Path(attempt_two_result).resolve())
        if attempt_two_result
        else None,
        "attempt_two_authorization": str(Path(attempt_two_authorization).resolve())
        if attempt_two_authorization
        else None,
        "session_quiescence_evidence": str(Path(session_quiescence_evidence).resolve())
        if session_quiescence_evidence
        else None,
        "task": selected["task"],
        "condition": selected["condition"],
        "model": pilot.MODEL,
        "reasoning_effort": pilot.REASONING_EFFORT,
        "timeout_seconds": pilot.TRIAL_TIMEOUT_SECONDS,
        "expected_tools": sorted(expected_tools),
        "environment_fingerprint": environment_fingerprint(selected["task"]),
        "execution_config_digest": execution_configuration_fingerprint(),
        "candidate_image_digest": candidate_image_digest,
        "controller_version": CONTROLLER_VERSION,
        "workspace": str(workspace.resolve()) if workspace is not None else None,
        "state_directory": (
            str(Path(state_directory).resolve()) if state_directory is not None else None
        ),
    }
    if workspace is not None:
        try:
            workspace_report = _load_controller().validate_public_workspace(
                workspace, selected["task"]
            )
        except (OSError, ValueError) as exc:
            raise AdapterError("Candidate workspace failed public-input validation") from exc
        if workspace_report["boundary_verified"] is not False:
            raise AdapterError("Workspace validator returned an invalid boundary claim")
        context["workspace_files"] = workspace_report["files"]
    else:
        context["workspace_files"] = None
    return context


def probe_docker() -> dict:
    """Check daemon availability without building images or creating containers."""
    executable = shutil.which("docker")
    if executable is None:
        return {"status": "unavailable", "failure": "docker_cli_not_found"}
    try:
        result = subprocess.run(
            [executable, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "failure": "docker_daemon_probe_timeout"}
    except OSError:
        return {"status": "unavailable", "failure": "docker_daemon_probe_failed"}
    version = result.stdout.strip()[:64] if result.returncode == 0 else None
    if result.returncode != 0 or not version:
        return {"status": "unavailable", "failure": "docker_daemon_not_reachable"}
    # A running daemon is not evidence of an isolated candidate boundary.
    return {
        "status": "daemon_available_boundary_unverified",
        "server_version": version,
        "isolation_verified": False,
    }


def build_preflight(context: dict, *, cli_report: dict | None = None, docker_report=None) -> dict:
    """Produce evidence-based gates; configuration declarations never prove isolation."""
    cli_report = cli_report if cli_report is not None else pilot.local_cli_metadata()
    docker_report = docker_report if docker_report is not None else probe_docker()
    blockers = []

    def gate(name: str, status: str, detail: str):
        if status != "verified":
            blockers.append(name)
        return {"status": status, "detail": detail}

    gates = {
        "trial_identity": gate("TRIAL_IDENTITY_INVALID", "verified", context["trial_id"]),
        "fixed_model_controls": gate(
            "MODEL_OR_REASONING_MISMATCH",
            "verified"
            if context["model"] == pilot.MODEL
            and context["reasoning_effort"] == pilot.REASONING_EFFORT
            else "blocked",
            f"{context['model']} / {context['reasoning_effort']}",
        ),
        "cli_metadata": gate(
            "CODEX_CLI_CAPABILITIES_UNVERIFIED",
            "verified" if cli_report.get("status") == "verified" else "unverified",
            "version/help metadata only; no model request or authentication probe",
        ),
        "account_model_access": gate(
            "MODEL_ACCESS_UNVERIFIED",
            "unverified",
            "No paid probe or session was authorized; account access remains unknown",
        ),
        "docker_daemon": gate(
            "DOCKER_DAEMON_UNAVAILABLE",
            "verified" if docker_report.get("status") != "unavailable" else "blocked",
            docker_report.get("failure") or docker_report.get("status", "unknown"),
        ),
        "candidate_isolation": gate(
            "AGENT_ISOLATION_UNVERIFIED",
            "unverified",
            "No measured disposable Codex-agent container/VM boundary is available",
        ),
        "hidden_oracle_exclusion": gate(
            "HIDDEN_ORACLE_EXPOSURE_UNVERIFIED",
            "unverified",
            "No candidate runtime exists in which hidden-input inaccessibility can be probed",
        ),
        "credential_boundary": gate(
            "CREDENTIAL_ISOLATION_UNVERIFIED",
            "unverified",
            "No trusted model credential broker is configured; host CODEX_HOME is not mounted",
        ),
        "restricted_egress": gate(
            "CONTROLLED_MODEL_EGRESS_UNVERIFIED",
            "unverified",
            "No enforced model-only egress proxy or network policy is configured",
        ),
        "gateway_boundary": gate(
            "TRUSTED_GATEWAY_ROUTE_UNAVAILABLE",
            "unverified" if context["condition"] in {"B", "C"} else "verified",
            "B/C require the trusted recording gateway outside candidate-visible storage"
            if context["condition"] in {"B", "C"}
            else "Condition A exposes no MCP tools",
        ),
        "effective_tools": gate(
            "EFFECTIVE_AGENT_TOOL_INVENTORY_UNVERIFIED",
            "unverified",
            f"Expected {len(context['expected_tools'])} tools; no actual agent session to inspect",
        ),
        "frozen_r_environment": gate(
            "FROZEN_R_IMAGE_NOT_VERIFIED",
            "unverified",
            "Manifest pins an image source but no built runtime digest was probed",
        ),
        "real_backend": gate(
            "SECURE_CODEX_EXECUTION_BACKEND_NOT_IMPLEMENTED",
            "unverified",
            "Host Codex CLI cannot safely be substituted for an isolated agent runtime",
        ),
    }
    return {
        "schema_version": 1,
        "record_type": "single_trial_execution_readiness_not_trial",
        "checked_at": datetime.now(UTC).isoformat(),
        "context": context,
        "codex_cli": {
            key: cli_report.get(key)
            for key in (
                "status",
                "version",
                "metadata_verified",
                "capabilities_verified",
                "supports_model_flag",
                "supports_config_override",
                "supports_reasoning_effort_override",
                "supports_json_events",
                "supports_ephemeral_mode",
                "checked_without_inference",
                "inference_performed",
                "failure",
            )
        },
        "docker": docker_report,
        "gates": gates,
        "blocking_conditions": blockers,
        "launch_permitted": False,
        "sessions_created": 0,
        "paid_calls_made": 0,
        "status": "blocked" if blockers else "ready_for_separate_authorization",
    }


def create_authorization(
    context: dict,
    *,
    typed_confirmation: str,
    now: datetime | None = None,
    ttl_seconds: int = 300,
    available_balance_cents: int,
    reserve_cents: int,
    estimated_spend_cents: int,
    balance_source: str,
    balance_checked_at: str,
    restricted_key_scope_confirmation: str,
    attempt_id: str = "R01-A/attempt-1",
    previous_attempt_result: Path | None = None,
    first_attempt_result: Path | None = None,
    previous_attempt_authorization: Path | None = None,
    first_attempt_authorization: Path | None = None,
    attempt_two_result: Path | None = None,
    attempt_two_authorization: Path | None = None,
    session_quiescence_evidence: Path | None = None,
) -> dict:
    """Create a narrowly scoped, short-lived consent record (never starts Codex)."""
    if (
        not isinstance(context, dict)
        or context.get("trial_id") != "R01-A"
        or context.get("task") != "R01"
        or context.get("condition") != "A"
        or context.get("model") != pilot.MODEL
        or context.get("reasoning_effort") != pilot.REASONING_EFFORT
        or context.get("timeout_seconds") != pilot.TRIAL_TIMEOUT_SECONDS
        or context.get("expected_tools") != []
    ):
        raise AdapterError("Authorization is restricted to the fixed R01-A configuration")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", str(context.get("candidate_image_digest", ""))):
        raise AdapterError("Authorization requires the reviewed immutable candidate image digest")
    if not re.fullmatch(r"[a-f0-9]{64}", str(context.get("execution_config_digest", ""))):
        raise AdapterError("Authorization requires the reviewed execution configuration digest")
    state_directory = context.get("state_directory")
    if not isinstance(state_directory, str) or not state_directory:
        raise AdapterError("Authorization requires the fixed external state directory")
    if Path(state_directory).resolve().is_relative_to(REPO.resolve()):
        raise AdapterError("Authorization state must be outside the evaluator repository")
    workspace = context.get("workspace")
    if not isinstance(workspace, str) or not workspace:
        raise AdapterError("Authorization requires the prepared public R01 workspace")
    try:
        workspace_report = _load_controller().validate_public_workspace(workspace, "R01")
    except (OSError, ValueError) as exc:
        raise AdapterError("Authorization workspace is not the exact public R01 input set") from exc
    if workspace_report["files"] != ["TASK.md", "data/records.csv", "renv.lock"]:
        raise AdapterError("Authorization workspace inventory differs from R01 inputs")
    if context.get("attempt_id") != attempt_id or attempt_id not in {
        "R01-A/attempt-1",
        "R01-A/attempt-2",
        RECOVERY_ATTEMPT_ID,
        FINAL_CONTINUATION_ATTEMPT_ID,
    }:
        raise AdapterError("Authorization attempt or recovery identity is invalid")
    if attempt_id == "R01-A/attempt-2":
        if previous_attempt_result is None:
            raise AdapterError("Attempt 2 requires the preserved first-attempt audit")
        if not (Path(state_directory) / "consumed-trials" / "R01-A.json").is_file():
            raise AdapterError("Attempt 1 authorization marker is missing")
        _verify_first_attempt_for_retry(Path(state_directory), previous_attempt_result)
    elif attempt_id == RECOVERY_ATTEMPT_ID:
        if (
            not first_attempt_result
            or not previous_attempt_result
            or not previous_attempt_authorization
        ):
            raise AdapterError(
                "Recovery requires both audits and the expired attempt-2 authorization"
            )
        if not (Path(state_directory) / "consumed-trials" / "R01-A.json").is_file():
            raise AdapterError("Attempt 1 authorization marker is missing")
        recovery = _verify_attempt_two_for_recovery(
            Path(state_directory),
            Path(first_attempt_result),
            Path(previous_attempt_result),
            Path(previous_attempt_authorization),
        )
        if (
            recovery["first_audit_sha256"] != context["recovery_first_attempt_audit_sha256"]
            or recovery["attempt_two_audit_sha256"] != context["previous_attempt_audit_sha256"]
            or recovery["authorization_sha256"] != context["previous_attempt_authorization_sha256"]
        ):
            raise AdapterError("Recovery provenance changed after preparation")
    elif attempt_id == FINAL_CONTINUATION_ATTEMPT_ID:
        if any(
            path is None
            for path in (
                first_attempt_result,
                first_attempt_authorization,
                attempt_two_result,
                attempt_two_authorization,
                previous_attempt_result,
                previous_attempt_authorization,
                session_quiescence_evidence,
            )
        ):
            raise AdapterError("Final continuation requires all prior provenance inputs")
        verified = _verify_final_continuation_provenance(
            Path(state_directory),
            Path(first_attempt_result),
            Path(first_attempt_authorization),
            Path(attempt_two_result),
            Path(attempt_two_authorization),
            Path(previous_attempt_result),
            Path(previous_attempt_authorization),
            Path(session_quiescence_evidence),
        )
        if verified != context.get("final_continuation_provenance"):
            raise AdapterError("Final continuation provenance changed after preparation")
    elif (Path(state_directory) / "consumed-trials" / "R01-A.json").exists():
        raise AdapterError("Attempt 1 has already been consumed; it cannot be replayed")
    confirmation_scope = context["trial_id"] if attempt_id == "R01-A/attempt-1" else attempt_id
    expected_confirmation = f"AUTHORIZE ONE PAID TRIAL {confirmation_scope}"
    if typed_confirmation != expected_confirmation:
        raise AdapterError("Typed confirmation must name exactly the selected paid trial")
    if restricted_key_scope_confirmation != "CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A":
        raise AdapterError("The separate environment-key scope confirmation is required")
    if ttl_seconds < 1 or ttl_seconds > MAX_AUTHORIZATION_TTL_SECONDS:
        raise AdapterError("Authorization lifetime must be between 1 and 300 seconds")
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise AdapterError("Authorization timestamp must be UTC-aware")
    try:
        ledger = pilot.BalanceAwareLedger(
            available_balance_cents,
            reserve_cents=reserve_cents,
            balance_source=balance_source,
            checked_at=balance_checked_at,
        )
        ledger.authorize_one(
            "R01-A", operator_authorized=True, estimated_spend_cents=estimated_spend_cents
        )
    except pilot.PilotError as exc:
        raise AdapterError(f"Balance-aware authorization was rejected: {exc}") from exc
    return {
        "schema_version": 1,
        "authorization_id": uuid.uuid4().hex,
        "authorized": True,
        "issued_at": now.astimezone(UTC).isoformat(),
        "expires_at": (now.astimezone(UTC) + timedelta(seconds=ttl_seconds)).isoformat(),
        "scope": {
            key: context[key]
            for key in (
                "trial_id",
                "attempt_id",
                "previous_attempt_audit_sha256",
                "previous_attempt_failure_classification",
                "previous_attempt_provider_status",
                "recovery_first_attempt_audit_sha256",
                "previous_attempt_authorization_sha256",
                "previous_attempt_result",
                "first_attempt_result",
                "previous_attempt_authorization",
                "final_continuation_provenance",
                "first_attempt_authorization",
                "attempt_two_result",
                "attempt_two_authorization",
                "session_quiescence_evidence",
                "task",
                "condition",
                "model",
                "reasoning_effort",
                "environment_fingerprint",
                "candidate_image_digest",
                "execution_config_digest",
                "workspace",
                "state_directory",
                "controller_version",
            )
        },
        "typed_confirmation": expected_confirmation,
        "attempt_id": attempt_id,
        "restricted_key_scope_operator_attested": True,
        "consumed": False,
        "balance_snapshot": {
            "available_balance_cents": available_balance_cents,
            "reserve_cents": reserve_cents,
            "estimated_spend_cents": estimated_spend_cents,
            "balance_source": balance_source,
            "checked_at": balance_checked_at,
            "estimate_is_binding": False,
            "ledger_is_hard_limit": False,
        },
    }


def validate_authorization(
    authorization: dict,
    context: dict,
    *,
    now: datetime | None = None,
    lease: SingleTrialLease | None = None,
) -> dict:
    """Reject expired, reused, malformed, or differently scoped consent records."""
    required = {
        "schema_version",
        "authorization_id",
        "authorized",
        "issued_at",
        "expires_at",
        "scope",
        "typed_confirmation",
        "attempt_id",
        "restricted_key_scope_operator_attested",
        "consumed",
        "balance_snapshot",
    }
    if not isinstance(authorization, dict) or set(authorization) != required:
        raise AdapterError("Authorization fields do not match the single-trial schema")
    if authorization["schema_version"] != 1 or authorization["authorized"] is not True:
        raise AdapterError("Explicit paid-trial authorization is missing")
    if authorization["restricted_key_scope_operator_attested"] is not True:
        raise AdapterError("Separate executor-key scope attestation is missing")
    if authorization["consumed"] is not False:
        raise AdapterError("Authorization has already been consumed")
    if not re.fullmatch(r"[a-f0-9]{32}", str(authorization["authorization_id"])):
        raise AdapterError("Authorization ID is invalid")
    confirmation_scope = (
        context["trial_id"]
        if context.get("attempt_id") == "R01-A/attempt-1"
        else context.get("attempt_id")
    )
    if authorization["typed_confirmation"] != f"AUTHORIZE ONE PAID TRIAL {confirmation_scope}":
        raise AdapterError("Authorization confirmation does not match this trial")
    if authorization["attempt_id"] != context.get("attempt_id"):
        raise AdapterError("Authorization attempt identity does not match")
    scope = authorization["scope"]
    expected_scope = {
        key: context[key]
        for key in (
            "trial_id",
            "attempt_id",
            "previous_attempt_audit_sha256",
            "previous_attempt_failure_classification",
            "previous_attempt_provider_status",
            "recovery_first_attempt_audit_sha256",
            "previous_attempt_authorization_sha256",
            "previous_attempt_result",
            "first_attempt_result",
            "previous_attempt_authorization",
            "final_continuation_provenance",
            "first_attempt_authorization",
            "attempt_two_result",
            "attempt_two_authorization",
            "session_quiescence_evidence",
            "task",
            "condition",
            "model",
            "reasoning_effort",
            "environment_fingerprint",
            "candidate_image_digest",
            "execution_config_digest",
            "workspace",
            "state_directory",
            "controller_version",
        )
    }
    if scope != expected_scope:
        raise AdapterError("Authorization scope differs from the prepared trial context")
    if context.get("attempt_id") == "R01-A/attempt-2":
        previous_path = context.get("previous_attempt_result")
        if (
            not previous_path
            or not _verify_first_attempt_for_retry(
                Path(context["state_directory"]), Path(previous_path), lease=lease
            )
            or hashlib.sha256(Path(previous_path).read_bytes()).hexdigest()
            != context.get("previous_attempt_audit_sha256")
        ):
            raise AdapterError("Attempt 1 audit or cleanup verification changed")
    elif context.get("attempt_id") == RECOVERY_ATTEMPT_ID:
        first_path = context.get("first_attempt_result")
        second_path = context.get("previous_attempt_result")
        previous_auth_path = context.get("previous_attempt_authorization")
        if not first_path or not second_path or not previous_auth_path:
            raise AdapterError("Recovery provenance files are missing")
        recovery = _verify_attempt_two_for_recovery(
            Path(context["state_directory"]),
            Path(first_path),
            Path(second_path),
            Path(previous_auth_path),
            lease=lease,
        )
        if (
            recovery["first_audit_sha256"] != context["recovery_first_attempt_audit_sha256"]
            or recovery["attempt_two_audit_sha256"] != context["previous_attempt_audit_sha256"]
            or recovery["authorization_sha256"] != context["previous_attempt_authorization_sha256"]
        ):
            raise AdapterError("Recovery audit or authorization provenance changed")
    elif context.get("attempt_id") == FINAL_CONTINUATION_ATTEMPT_ID:
        verified = _verify_final_continuation_provenance(
            Path(context["state_directory"]),
            Path(context["first_attempt_result"]),
            Path(context["first_attempt_authorization"]),
            Path(context["attempt_two_result"]),
            Path(context["attempt_two_authorization"]),
            Path(context["previous_attempt_result"]),
            Path(context["previous_attempt_authorization"]),
            Path(context["session_quiescence_evidence"]),
            lease=lease,
        )
        if verified != context.get("final_continuation_provenance"):
            raise AdapterError("Final continuation provenance or session evidence changed")
        consumed_marker = (
            Path(context["state_directory"])
            / "consumed-authorizations"
            / f"{authorization['authorization_id']}.json"
        )
        if consumed_marker.exists() or consumed_marker.is_symlink():
            raise AdapterError("Final-continuation authorization has already been consumed")
    try:
        issued = datetime.fromisoformat(authorization["issued_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(authorization["expires_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise AdapterError("Authorization timestamps are invalid") from exc
    now = now or datetime.now(UTC)
    if any(moment.utcoffset() != timedelta(0) for moment in (issued, expires)):
        raise AdapterError("Authorization timestamps must be UTC")
    if expires <= issued or expires - issued > timedelta(seconds=MAX_AUTHORIZATION_TTL_SECONDS):
        raise AdapterError("Authorization lifetime exceeds the permitted window")
    if now < issued or now >= expires:
        raise AdapterError("Authorization is not currently valid")
    snapshot = authorization["balance_snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "available_balance_cents",
        "reserve_cents",
        "estimated_spend_cents",
        "balance_source",
        "checked_at",
        "estimate_is_binding",
        "ledger_is_hard_limit",
    }:
        raise AdapterError("Authorization balance snapshot is invalid")
    if (
        snapshot["estimate_is_binding"] is not False
        or snapshot["ledger_is_hard_limit"] is not False
        or not isinstance(snapshot["balance_source"], str)
        or not snapshot["balance_source"].strip()
    ):
        raise AdapterError("Authorization balance metadata is invalid")
    try:
        balance_checked_at = datetime.fromisoformat(snapshot["checked_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise AdapterError("Authorization balance timestamp is invalid") from exc
    if (
        balance_checked_at.utcoffset() != timedelta(0)
        or balance_checked_at > now
        or now - balance_checked_at > timedelta(seconds=MAX_AUTHORIZATION_TTL_SECONDS)
    ):
        raise AdapterError("Authorization requires a fresh UTC balance snapshot")
    try:
        ledger = pilot.BalanceAwareLedger(
            snapshot["available_balance_cents"],
            reserve_cents=snapshot["reserve_cents"],
            balance_source=snapshot["balance_source"],
            checked_at=snapshot["checked_at"],
        )
        ledger.authorize_one(
            "R01-A",
            operator_authorized=True,
            estimated_spend_cents=snapshot["estimated_spend_cents"],
        )
    except (pilot.PilotError, TypeError) as exc:
        raise AdapterError("Authorization balance snapshot failed validation") from exc
    return authorization


class SingleTrialLease(AbstractContextManager):
    """Cross-process exclusive lock; keep it after unsafe/incomplete cleanup."""

    def __init__(self, state_directory: Path, trial_id: str):
        self.state_directory = Path(state_directory)
        self.trial_id = trial_id
        self.lock_path = self.state_directory / "active-trial.lock"
        self.acquired = False
        self.cleanup_verified = False
        self.lease_id = uuid.uuid4().hex
        self._file_identity: tuple[int, int] | None = None

    def __enter__(self):
        root = self.state_directory.resolve()
        if root.is_relative_to(REPO.resolve()):
            raise AdapterError("Execution state must be outside the evaluator repository")
        root.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock_path.open("x", encoding="utf-8") as lock:
                lock.write(
                    json.dumps(
                        {
                            "trial_id": self.trial_id,
                            "pid": os.getpid(),
                            "lease_id": self.lease_id,
                            "created_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    + "\n"
                )
                lock.flush()
                os.fsync(lock.fileno())
                info = os.fstat(lock.fileno())
                self._file_identity = (info.st_dev, info.st_ino)
        except FileExistsError as exc:
            raise AdapterError(
                "Another trial is active or a stale lock needs operator review"
            ) from exc
        self.acquired = True
        return self

    def owns_lock(self) -> bool:
        """Prove the on-disk lease is this process's exact lock instance."""
        if not self.acquired or self._file_identity is None:
            return False
        try:
            if self.lock_path.is_symlink():
                return False
            with self.lock_path.open("r", encoding="utf-8") as lock:
                info = os.fstat(lock.fileno())
                if (info.st_dev, info.st_ino) != self._file_identity:
                    return False
                payload = json.load(lock)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("trial_id") == self.trial_id
            and payload.get("pid") == os.getpid()
            and payload.get("lease_id") == self.lease_id
        )

    def mark_cleanup_verified(self):
        self.cleanup_verified = True

    def __exit__(self, exc_type, exc, tb):
        if self.acquired and self.cleanup_verified and self.owns_lock():
            self.lock_path.unlink(missing_ok=True)
        return False


def consume_authorization(
    authorization: dict,
    context: dict,
    state_directory: Path,
    *,
    lease: SingleTrialLease | None = None,
) -> Path:
    """Atomically mark a valid authorization as used; markers are never auto-removed."""
    validate_authorization(authorization, context, lease=lease)
    root = Path(state_directory).resolve()
    if root.is_relative_to(REPO.resolve()):
        raise AdapterError("Authorization state must be outside the evaluator repository")
    consumed = root / "consumed-authorizations"
    consumed.mkdir(parents=True, exist_ok=True)
    consumed_trials = root / "consumed-trials"
    consumed_trials.mkdir(parents=True, exist_ok=True)
    attempt_id = context.get("attempt_id", "R01-A/attempt-1")
    if attempt_id not in {
        "R01-A/attempt-1",
        "R01-A/attempt-2",
        RECOVERY_ATTEMPT_ID,
        FINAL_CONTINUATION_ATTEMPT_ID,
    }:
        raise AdapterError("No authorization beyond the one final continuation is permitted")
    marker_name = {
        "R01-A/attempt-1": f"{context['trial_id']}.json",
        "R01-A/attempt-2": f"{context['trial_id']}-attempt-2.json",
        RECOVERY_ATTEMPT_ID: f"{context['trial_id']}-recovery-after-attempt-2.json",
        FINAL_CONTINUATION_ATTEMPT_ID: f"{context['trial_id']}-final-continuation.json",
    }[attempt_id]
    trial_marker = consumed_trials / marker_name
    if attempt_id == "R01-A/attempt-2":
        first_marker = consumed_trials / "R01-A.json"
        previous_path = context.get("previous_attempt_result")
        if not first_marker.is_file() or not previous_path:
            raise AdapterError("The consumed first attempt and its audit must be preserved")
        _verify_first_attempt_for_retry(root, Path(previous_path), lease=lease)
        if hashlib.sha256(Path(previous_path).read_bytes()).hexdigest() != context.get(
            "previous_attempt_audit_sha256"
        ):
            raise AdapterError("Attempt 1 audit changed after authorization")
    elif attempt_id == RECOVERY_ATTEMPT_ID:
        first_path = context.get("first_attempt_result")
        previous_path = context.get("previous_attempt_result")
        previous_auth_path = context.get("previous_attempt_authorization")
        if not first_path or not previous_path or not previous_auth_path:
            raise AdapterError("Recovery provenance files are missing")
        recovery = _verify_attempt_two_for_recovery(
            root,
            Path(first_path),
            Path(previous_path),
            Path(previous_auth_path),
            lease=lease,
        )
        if (
            recovery["first_audit_sha256"] != context["recovery_first_attempt_audit_sha256"]
            or recovery["attempt_two_audit_sha256"] != context["previous_attempt_audit_sha256"]
            or recovery["authorization_sha256"] != context["previous_attempt_authorization_sha256"]
        ):
            raise AdapterError("Recovery audit or authorization changed after authorization")
    elif attempt_id == FINAL_CONTINUATION_ATTEMPT_ID:
        verified = _verify_final_continuation_provenance(
            root,
            Path(context["first_attempt_result"]),
            Path(context["first_attempt_authorization"]),
            Path(context["attempt_two_result"]),
            Path(context["attempt_two_authorization"]),
            Path(context["previous_attempt_result"]),
            Path(context["previous_attempt_authorization"]),
            Path(context["session_quiescence_evidence"]),
            lease=lease,
        )
        if verified != context.get("final_continuation_provenance"):
            raise AdapterError("Final continuation provenance changed after authorization")
    try:
        with trial_marker.open("x", encoding="utf-8") as output:
            json.dump(
                {
                    "trial_id": context["trial_id"],
                    "authorization_id": authorization["authorization_id"],
                    "consumed_at": datetime.now(UTC).isoformat(),
                },
                output,
            )
            output.write("\n")
    except FileExistsError as exc:
        raise AdapterError("This pilot trial already has a consumed authorization") from exc
    marker = consumed / f"{authorization['authorization_id']}.json"
    try:
        with marker.open("x", encoding="utf-8") as output:
            json.dump(
                {
                    "authorization_id": authorization["authorization_id"],
                    "trial_id": context["trial_id"],
                    "consumed_at": datetime.now(UTC).isoformat(),
                },
                output,
            )
            output.write("\n")
    except FileExistsError as exc:
        raise AdapterError("Authorization was already consumed") from exc
    return marker


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AdapterError("A required R01-A runtime module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _private_json_write(
    path: Path, value: dict, *, exclusive: bool = True, redact_content: bool = True
) -> None:
    """Write bounded local authorization or result records with owner-only mode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(
                redact(value) if redact_content else value, output, indent=2, ensure_ascii=False
            )
            output.write("\n")
    except BaseException:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def create_authorization_file(
    *,
    plan: dict,
    trial_id: str,
    workspace: Path,
    candidate_image_digest: str,
    state_directory: Path,
    typed_confirmation: str,
    available_balance_cents: int,
    reserve_cents: int,
    estimated_spend_cents: int,
    balance_source: str,
    balance_checked_at: str,
    restricted_key_scope_confirmation: str,
    output: Path,
    attempt_id: str = "R01-A/attempt-1",
    previous_attempt_result: Path | None = None,
    first_attempt_result: Path | None = None,
    previous_attempt_authorization: Path | None = None,
    first_attempt_authorization: Path | None = None,
    attempt_two_result: Path | None = None,
    attempt_two_authorization: Path | None = None,
    session_quiescence_evidence: Path | None = None,
) -> dict:
    """Create a one-use authorization without contacting Docker or OpenAI."""
    if Path(output).resolve().is_relative_to(REPO.resolve()):
        raise AdapterError("Authorization files must be stored outside the evaluator repository")
    context = build_trial_context(
        plan,
        trial_id,
        Path(workspace),
        candidate_image_digest=candidate_image_digest,
        state_directory=state_directory,
        attempt_id=attempt_id,
        previous_attempt_result=previous_attempt_result,
        first_attempt_result=first_attempt_result,
        previous_attempt_authorization=previous_attempt_authorization,
        first_attempt_authorization=first_attempt_authorization,
        attempt_two_result=attempt_two_result,
        attempt_two_authorization=attempt_two_authorization,
        session_quiescence_evidence=session_quiescence_evidence,
    )
    authorization = create_authorization(
        context,
        typed_confirmation=typed_confirmation,
        available_balance_cents=available_balance_cents,
        reserve_cents=reserve_cents,
        estimated_spend_cents=estimated_spend_cents,
        balance_source=balance_source,
        balance_checked_at=balance_checked_at,
        restricted_key_scope_confirmation=restricted_key_scope_confirmation,
        attempt_id=attempt_id,
        previous_attempt_result=previous_attempt_result,
        first_attempt_result=first_attempt_result,
        previous_attempt_authorization=previous_attempt_authorization,
        first_attempt_authorization=first_attempt_authorization,
        attempt_two_result=attempt_two_result,
        attempt_two_authorization=attempt_two_authorization,
        session_quiescence_evidence=session_quiescence_evidence,
    )
    validate_authorization(authorization, context)
    # This file is owner-only and must retain the opaque nonce used to reject replay.
    _private_json_write(output, authorization, redact_content=False)
    return {
        "status": "authorized_one_trial",
        "trial_id": trial_id,
        "authorization_file": str(output),
    }


def _make_live_controller(context: dict, authorization: dict, state_directory: Path):
    """Build only the reviewed production components for the fixed R01-A row."""
    docker_runtime = _load_module(ROOT / "exploratory" / "docker_runtime.py", "r01a_docker_runtime")
    lifecycle = _load_module(ROOT / "exploratory" / "lifecycle.py", "r01a_lifecycle")
    managed_agents = _load_module(ROOT / "exploratory" / "managed_agents.py", "r01a_managed_agents")
    application_key = os.environ.get("OPENAI_API_KEY", "")
    environment_key = os.environ.get("OPENAI_EXECUTOR_API_KEY", "")
    if not application_key:
        raise AdapterError("Controller-side OPENAI_API_KEY is unavailable")
    if not environment_key:
        raise AdapterError("Restricted OPENAI_EXECUTOR_API_KEY is unavailable")
    if application_key == environment_key:
        raise AdapterError("Application and restricted executor keys must be distinct")
    if context.get("condition") != "A" or context.get("expected_tools") != []:
        raise AdapterError("Condition A must have zero MCP tools")
    image_digest = context.get("candidate_image_digest")
    runtime = docker_runtime.CodexCandidateRuntime(image_digest)
    candidate_report = runtime.verify_candidate_image()
    if candidate_report["image_id"] != image_digest:
        raise AdapterError("Verified Codex image differs from the authorized digest")
    r_runtime = docker_runtime.DockerCandidateRuntime(docker_runtime.FROZEN_R_IMAGE_ID)
    r_image_report = r_runtime.verify_engine_and_image()
    if r_image_report["image_id"] != docker_runtime.FROZEN_R_IMAGE_ID:
        raise AdapterError("Frozen R scorer image is not verified")
    workspace_report = runtime._validate_workspace(Path(context["workspace"]))
    if workspace_report["files"] != ["TASK.md", "data/records.csv", "renv.lock"]:
        raise AdapterError("Public R01 workspace differs from the authorized file set")

    snapshot = authorization["balance_snapshot"]
    ledger = pilot.BalanceAwareLedger(
        snapshot["available_balance_cents"],
        reserve_cents=snapshot["reserve_cents"],
        balance_source=snapshot["balance_source"],
        checked_at=snapshot["checked_at"],
    )
    topology = docker_runtime.RestrictedEgressNetwork(runtime.docker)
    client = managed_agents.ManagedAgentsClient(application_key)

    def live_gates():
        return {
            "docker_candidate_image": candidate_report["image_id"] == image_digest,
            "frozen_r_scorer_image": r_image_report["image_id"] == docker_runtime.FROZEN_R_IMAGE_ID,
            "public_workspace": workspace_report["files"]
            == ["TASK.md", "data/records.csv", "renv.lock"],
            "controller_application_credential": bool(application_key),
            "restricted_environment_key_present_and_separate": bool(environment_key)
            and environment_key != application_key,
            "restricted_environment_key_scope_operator_attested": authorization.get(
                "restricted_key_scope_operator_attested"
            )
            is True,
            "condition_a_zero_tools": context["condition"] == "A"
            and context["expected_tools"] == [],
        }

    bench = _load_module(ROOT / "runner" / "bench.py", "r01a_scorer")

    def checkpoint_review(record: dict) -> dict:
        usage = _usage_from_lifecycle_events(record.get("events", []))
        print("\nR01-A lifecycle ended. Review this real score and usage before checkpoint:")
        print(json.dumps({"scoring": record.get("scoring"), "usage": usage}, indent=2))
        spend = _prompt_nonnegative_int(
            "Provider-reported session spend in cents (blank = unavailable): "
        )
        remaining = _prompt_nonnegative_int(
            "Fresh available balance in cents (blank = unavailable): "
        )
        correctness = input(
            "Correctness review note after inspecting the independent score: "
        ).strip()
        source = input("Source of the fresh balance (for example platform dashboard): ").strip()
        confirmed = input("Do spend and balance reconcile? type yes/no: ").strip().lower() == "yes"
        return {
            "reported_spend_cents": spend,
            "usage": usage,
            "correctness_review": correctness or None,
            "remaining_balance_cents": remaining,
            "reconciled": confirmed,
            "balance_source": source or None,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    return lifecycle.R01ALifecycleController(
        client=client,
        runtime=runtime,
        topology=topology,
        ledger=ledger,
        authorize=validate_authorization,
        consume_authorization=consume_authorization,
        lease_factory=lambda trial: SingleTrialLease(state_directory, trial),
        score=lambda task, artifacts, image: bench.score(task, artifacts, image),
        frozen_r_image_id=docker_runtime.FROZEN_R_IMAGE_ID,
        environment_key=environment_key,
        estimated_spend_cents=snapshot["estimated_spend_cents"],
        checkpoint_review=checkpoint_review,
        current_live_gates=live_gates,
        trial_timeout_seconds=900,
    )


def _prompt_nonnegative_int(prompt: str) -> int | None:
    raw = input(prompt).strip()
    if not raw:
        return None
    try:
        result = int(raw)
    except ValueError:
        return None
    return result if result >= 0 else None


def _usage_from_lifecycle_events(events: list[dict]) -> dict | None:
    """Extract only explicit usage attached to completed Managed Agents turns."""
    inputs = outputs = reasoning = 0
    found = False
    for event in events:
        if event.get("type") not in {"agent.session.turn.completed", "turn.completed"}:
            continue
        turn = event.get("turn")
        usage = turn.get("usage") if isinstance(turn, dict) else event.get("usage")
        if not isinstance(usage, dict):
            continue
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        reasoning_tokens = usage.get("reasoning_tokens", 0)
        if any(type(value) is not int or value < 0 for value in (input_tokens, output_tokens)):
            return None
        if type(reasoning_tokens) is not int or reasoning_tokens < 0:
            return None
        inputs += input_tokens
        outputs += output_tokens
        reasoning += reasoning_tokens
        found = True
    if not found:
        return None
    return {
        "input_tokens": inputs,
        "output_tokens": outputs,
        "reasoning_tokens": reasoning,
        "total_tokens": inputs + outputs,
    }


def run_one(
    *,
    plan: dict,
    trial_id: str,
    authorization: dict,
    state_directory: Path,
    workspace: Path,
    candidate_image_digest: str,
    attempt_id: str = "R01-A/attempt-1",
    previous_attempt_result: Path | None = None,
    first_attempt_result: Path | None = None,
    previous_attempt_authorization: Path | None = None,
    first_attempt_authorization: Path | None = None,
    attempt_two_result: Path | None = None,
    attempt_two_authorization: Path | None = None,
    session_quiescence_evidence: Path | None = None,
):
    """Run exactly one fully authorized R01-A lifecycle; never retries or batches."""
    context = build_trial_context(
        plan,
        trial_id,
        Path(workspace),
        candidate_image_digest=candidate_image_digest,
        state_directory=Path(state_directory),
        attempt_id=attempt_id,
        previous_attempt_result=previous_attempt_result,
        first_attempt_result=first_attempt_result,
        previous_attempt_authorization=previous_attempt_authorization,
        first_attempt_authorization=first_attempt_authorization,
        attempt_two_result=attempt_two_result,
        attempt_two_authorization=attempt_two_authorization,
        session_quiescence_evidence=session_quiescence_evidence,
    )
    validate_authorization(authorization, context)
    controller = _make_live_controller(context, authorization, Path(state_directory))
    return controller.run_one(
        context=context, authorization=authorization, state_directory=state_directory
    )


def verify_cleanup(
    state_directory: Path,
    result_path: Path,
    docker: str | None = None,
    *,
    lease: SingleTrialLease | None = None,
) -> dict:
    """Verify the saved live audit plus local lock, containers, and egress networks."""
    state_directory = Path(state_directory).resolve()
    if state_directory.is_relative_to(REPO.resolve()):
        raise AdapterError("Execution state must be outside the evaluator repository")
    lock_path = state_directory / "active-trial.lock"
    lock_exists = lock_path.exists() or lock_path.is_symlink()
    lock_owned = bool(
        lease and lease.state_directory.resolve() == state_directory and lease.owns_lock()
    )
    docker = docker or shutil.which("docker")
    if not docker:
        raise AdapterError("Docker CLI is unavailable for cleanup verification")
    result = subprocess.run(
        [docker, "ps", "--all", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise AdapterError("Docker cleanup state could not be verified")
    names = [line for line in result.stdout.splitlines() if line.startswith("rkmcp-")]
    network_result = subprocess.run(
        [docker, "network", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if network_result.returncode != 0:
        raise AdapterError("Docker network cleanup state could not be verified")
    networks = [
        line
        for line in network_result.stdout.splitlines()
        if line.startswith(("rkmcp-candidate-R01-A-", "rkmcp-egress-R01-A-"))
    ]
    result_path = Path(result_path)
    if (
        result_path.is_symlink()
        or not result_path.is_file()
        or result_path.stat().st_size > (8 << 20)
    ):
        raise AdapterError("Lifecycle audit is missing, linked, or oversized")
    try:
        audit = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError("Lifecycle cleanup audit is unavailable or invalid") from exc
    live_audit_clean = (
        isinstance(audit, dict)
        and audit.get("record_type") == "managed_agents_r01a_lifecycle_audit_not_benchmark_result"
        and audit.get("synthetic") is False
        and audit.get("cleanup_verified") is True
        and audit.get("session_deleted_verified") is True
        and audit.get("container_termination_verified") is True
        and audit.get("topology_cleanup_verified") is True
    )
    return {
        "record_type": "r01a_cleanup_verification_not_trial",
        "checked_at": datetime.now(UTC).isoformat(),
        "active_trial_lock_present": lock_exists,
        "active_trial_lock_owned_by_caller": lock_owned,
        "remaining_rkmcp_containers": names,
        "remaining_r01a_networks": networks,
        "live_lifecycle_cleanup_verified": live_audit_clean,
        "local_cleanup_verified": (
            (not lock_exists if lease is None else lock_owned) and not names and not networks
        ),
        "cleanup_verified": (
            live_audit_clean
            and (not lock_exists if lease is None else lock_owned)
            and not names
            and not networks
        ),
    }


def _validate_legacy_first_authorization(auth: dict, state_directory: Path) -> None:
    """Accept only the original, pre-attempt-id R01-A authorization schema."""
    legacy_fields = {
        "schema_version",
        "authorization_id",
        "authorized",
        "issued_at",
        "expires_at",
        "scope",
        "typed_confirmation",
        "restricted_key_scope_operator_attested",
        "consumed",
        "balance_snapshot",
    }
    scope_fields = {
        "trial_id",
        "task",
        "condition",
        "model",
        "reasoning_effort",
        "environment_fingerprint",
        "candidate_image_digest",
        "execution_config_digest",
        "workspace",
        "state_directory",
        "controller_version",
    }
    balance_fields = {
        "available_balance_cents",
        "reserve_cents",
        "estimated_spend_cents",
        "balance_source",
        "checked_at",
        "estimate_is_binding",
        "ledger_is_hard_limit",
    }
    scope = auth.get("scope") if isinstance(auth, dict) else None
    balance = auth.get("balance_snapshot") if isinstance(auth, dict) else None
    if (
        not isinstance(auth, dict)
        or set(auth) != legacy_fields
        or auth.get("schema_version") != 1
        or auth.get("authorized") is not True
        or auth.get("consumed") is not False
        or auth.get("typed_confirmation") != "AUTHORIZE ONE PAID TRIAL R01-A"
        or auth.get("restricted_key_scope_operator_attested") is not True
        or not re.fullmatch(r"[a-f0-9]{32}", str(auth.get("authorization_id", "")))
        or not isinstance(scope, dict)
        or set(scope) != scope_fields
        or scope.get("trial_id") != "R01-A"
        or scope.get("task") != "R01"
        or scope.get("condition") != "A"
        or scope.get("model") != pilot.MODEL
        or scope.get("reasoning_effort") != pilot.REASONING_EFFORT
        or not re.fullmatch(r"[a-f0-9]{64}", str(scope.get("environment_fingerprint", "")))
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(scope.get("candidate_image_digest", "")))
        or not re.fullmatch(r"[a-f0-9]{64}", str(scope.get("execution_config_digest", "")))
        or not isinstance(scope.get("workspace"), str)
        or not Path(scope["workspace"]).is_absolute()
        or scope.get("state_directory") != str(state_directory.resolve())
        or not isinstance(scope.get("controller_version"), str)
        or not scope["controller_version"]
        or not isinstance(balance, dict)
        or set(balance) != balance_fields
        or any(
            type(balance.get(key)) is not int or balance[key] < 0
            for key in ("available_balance_cents", "reserve_cents", "estimated_spend_cents")
        )
        or not isinstance(balance.get("balance_source"), str)
        or not balance["balance_source"]
        or not isinstance(balance.get("checked_at"), str)
        or balance.get("estimate_is_binding") is not False
        or balance.get("ledger_is_hard_limit") is not False
    ):
        raise AdapterError("Original attempt-1 authorization does not match its legacy contract")
    try:
        issued = datetime.fromisoformat(auth["issued_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(auth["expires_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise AdapterError("Original attempt-1 authorization timestamps are invalid") from exc
    if (
        issued.utcoffset() != timedelta(0)
        or expires.utcoffset() != timedelta(0)
        or expires <= issued
        or expires - issued > timedelta(seconds=MAX_AUTHORIZATION_TTL_SECONDS)
    ):
        raise AdapterError("Original attempt-1 authorization lifetime is invalid")


def _verify_final_continuation_provenance(
    state_directory: Path,
    first_result_path: Path,
    first_auth_path: Path,
    second_result_path: Path,
    second_auth_path: Path,
    third_result_path: Path,
    third_auth_path: Path,
    session_evidence_path: Path,
    *,
    lease: SingleTrialLease | None = None,
) -> dict[str, object]:
    """Validate immutable history and fresh, independent session-quiescence evidence."""
    root = Path(state_directory).resolve()
    paths = [
        Path(path)
        for path in (
            first_result_path,
            first_auth_path,
            second_result_path,
            second_auth_path,
            third_result_path,
            third_auth_path,
            session_evidence_path,
        )
    ]
    if any(not path.resolve().is_relative_to(root) for path in paths):
        raise AdapterError(
            "Final-continuation provenance must remain inside the external state directory"
        )

    def read_json(path: Path, limit: int) -> tuple[bytes, dict]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise AdapterError("Final-continuation provenance is linked, missing, or oversized")
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AdapterError("Final-continuation provenance is unavailable or invalid") from exc
        if not isinstance(value, dict):
            raise AdapterError("Final-continuation provenance must contain JSON objects")
        return raw, value

    first_raw, first = read_json(paths[0], 8 << 20)
    first_auth_raw, first_auth = read_json(paths[1], 64 << 10)
    second_raw, second = read_json(paths[2], 8 << 20)
    second_auth_raw, second_auth = read_json(paths[3], 64 << 10)
    third_raw, third = read_json(paths[4], 8 << 20)
    third_auth_raw, third_auth = read_json(paths[5], 64 << 10)
    evidence_raw, evidence = read_json(paths[6], 8 << 20)

    # Reuse the original attempt-1 contract; the old attempt-2 audit remains a
    # pre-session local failure and is checked without making deletion claims.
    _verify_first_attempt_for_retry(root, paths[0], lease=lease)
    second_states = (
        tuple(
            item.get("state") if isinstance(item, dict) else item
            for item in second.get("states", [])
        )
        if isinstance(second.get("states"), list)
        else ()
    )
    if not (
        second.get("record_type") == "managed_agents_r01a_lifecycle_audit_not_benchmark_result"
        and second.get("synthetic") is False
        and second.get("trial_id") == "R01-A"
        and second.get("attempt_id") == "R01-A/attempt-2"
        and second.get("failure_category") == "AdapterError"
        and second_states
        in {
            ("prepare", "terminate_container", "cleanup"),
            ("prepare", "consume_authorization", "terminate_container", "cleanup"),
        }
        and second.get("session_creation_attempted") is False
        and second.get("sessions_created_count") == 0
        and second.get("session_creation_uncertain") is False
        and second.get("task_submission_attempted") is False
        and second.get("task_submission_uncertain") is False
        and second.get("task_submissions_attempted_count") == 0
        and second.get("inference_submitted") is False
        and second.get("cleanup_verified") is True
        and second.get("container_termination_verified") is True
        and second.get("topology_cleanup_verified") is True
    ):
        raise AdapterError("Attempt-2 audit does not match the preserved pre-session failure")

    third_failure = third.get("failure")
    third_category = (
        third_failure.get("category")
        if isinstance(third_failure, dict)
        else third.get("failure_category")
    )
    third_statuses = []
    if isinstance(third_failure, dict) and third_failure.get("http_status") is not None:
        third_statuses.append(third_failure.get("http_status"))
    if third.get("session_creation_http_status") is not None:
        third_statuses.append(third.get("session_creation_http_status"))
    legacy_response_state = (
        third.get("session_created") is False
        and type(third.get("sessions_created_count")) is int
        and third.get("sessions_created_count") == 0
    )
    current_response_state = (
        third.get("session_created") is True
        and type(third.get("sessions_created_count")) is int
        and third.get("sessions_created_count") == 1
    )
    if not (
        third.get("record_type") == "managed_agents_r01a_lifecycle_audit_not_benchmark_result"
        and third.get("synthetic") is False
        and third.get("trial_id") == "R01-A"
        and third.get("attempt_id") == RECOVERY_ATTEMPT_ID
        and third.get("session_creation_attempted") is True
        and (legacy_response_state or current_response_state)
        and third_statuses
        and all(type(status) is int and status == 201 for status in third_statuses)
        and isinstance(third_failure, dict)
        and third_failure.get("operation") == "create_session"
        and third_category == "response_schema_validation"
        and (
            third.get("failure_category") is None
            or third_failure.get("category") == third.get("failure_category")
        )
        and third.get("task_submission_attempted") is not True
        and third.get("task_submission_uncertain") is not True
        and type(third.get("task_submissions_attempted_count")) is int
        and third.get("task_submissions_attempted_count") == 0
        and third.get("inference_submitted") is False
        and third.get("container_termination_verified") is True
        and third.get("topology_cleanup_verified") is True
    ):
        raise AdapterError(
            "Third-attempt audit does not prove the recorded HTTP 201 pre-task failure"
        )
    local_cleanup = verify_cleanup(root, paths[4], lease=lease)
    if not local_cleanup.get("local_cleanup_verified"):
        raise AdapterError(
            "Third-attempt local Docker/network cleanup is not independently verified"
        )

    # The old audit format cannot establish remote session deletion. A true
    # session_deleted_verified value is deliberately not accepted as evidence.
    third_remote_state = "unknown_until_independent_inventory"
    ignored_legacy_deletion_claim = third.get("session_deleted_verified") is True

    auth_specs = (
        (first_auth, "R01-A/attempt-1", "R01-A"),
        (second_auth, "R01-A/attempt-2", "R01-A-attempt-2"),
        (third_auth, RECOVERY_ATTEMPT_ID, "R01-A-recovery-after-attempt-2"),
    )
    auth_ids = []
    for auth_index, (auth, expected_attempt, marker_stem) in enumerate(auth_specs):
        auth_id = auth.get("authorization_id")
        if auth_index == 0:
            _validate_legacy_first_authorization(auth, root)
        elif (
            auth.get("authorized") is not True
            or auth.get("attempt_id") != expected_attempt
            or not re.fullmatch(r"[a-f0-9]{32}", str(auth_id))
            or not isinstance(auth.get("scope"), dict)
            or auth["scope"].get("attempt_id") != expected_attempt
            or auth["scope"].get("trial_id") != "R01-A"
        ):
            raise AdapterError("Prior authorization history has an invalid identity")
        if not re.fullmatch(r"[a-f0-9]{32}", str(auth_id)):
            raise AdapterError("Prior authorization history has an invalid identity")
        auth_ids.append(auth_id)
        if expected_attempt != "R01-A/attempt-2":
            marker_path = root / "consumed-trials" / f"{marker_stem}.json"
            if marker_path.is_symlink() or not marker_path.is_file():
                raise AdapterError("A consumed historical trial marker is missing")
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise AdapterError("A historical consumed marker is invalid") from exc
            if (
                not isinstance(marker, dict)
                or marker.get("trial_id") != "R01-A"
                or marker.get("authorization_id") != auth_id
            ):
                raise AdapterError("Historical consumed marker does not match its authorization")
            consumed_auth = root / "consumed-authorizations" / f"{auth_id}.json"
            if consumed_auth.is_symlink() or not consumed_auth.is_file():
                raise AdapterError("A historical authorization-consumption marker is missing")
            try:
                consumed_record = json.loads(consumed_auth.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise AdapterError("A historical authorization marker is invalid") from exc
            if (
                not isinstance(consumed_record, dict)
                or consumed_record.get("authorization_id") != auth_id
                or consumed_record.get("trial_id") != "R01-A"
            ):
                raise AdapterError("Historical authorization marker has a mismatched identity")
        else:
            marker_path = root / "consumed-trials" / "R01-A-attempt-2.json"
            if marker_path.exists() or marker_path.is_symlink():
                raise AdapterError(
                    "Attempt 2 already has a consumed marker; no further continuation is allowed"
                )
            if (root / "consumed-authorizations" / f"{auth_id}.json").exists():
                raise AdapterError(
                    "Attempt-2 authorization was consumed; no further continuation is allowed"
                )
            first_digest = hashlib.sha256(first_raw).hexdigest()
            if auth["scope"].get("previous_attempt_audit_sha256") != first_digest:
                raise AdapterError("Attempt-2 authorization does not bind the first audit")
            try:
                second_expires = datetime.fromisoformat(auth["expires_at"].replace("Z", "+00:00"))
            except (KeyError, AttributeError, ValueError) as exc:
                raise AdapterError("Attempt-2 authorization expiration is invalid") from exc
            if second_expires.utcoffset() != timedelta(0) or second_expires > datetime.now(UTC):
                raise AdapterError("Attempt-2 authorization must remain expired and unreusable")

    if len(set(auth_ids)) != 3:
        raise AdapterError("Historical authorizations must have distinct identities")
    if third.get("authorization_id") not in (None, auth_ids[2], "[REDACTED]"):
        raise AdapterError("Third-attempt audit does not match its authorization")
    if (
        third_auth.get("scope", {}).get("previous_attempt_audit_sha256")
        != hashlib.sha256(second_raw).hexdigest()
        or third_auth.get("scope", {}).get("recovery_first_attempt_audit_sha256")
        != hashlib.sha256(first_raw).hexdigest()
        or third_auth.get("scope", {}).get("previous_attempt_authorization_sha256")
        != hashlib.sha256(second_auth_raw).hexdigest()
    ):
        raise AdapterError(
            "Third authorization does not bind the preserved first and second history"
        )
    final_marker = root / "consumed-trials" / "R01-A-final-continuation.json"
    if final_marker.exists() or final_marker.is_symlink():
        raise AdapterError(
            "The one final-continuation marker already exists; a fifth attempt is forbidden"
        )

    if (
        evidence.get("record_type") != "managed_agents_session_quiescence_evidence"
        or evidence.get("source_url") != SESSION_QUIESCENCE_SOURCE
        or evidence.get("operator_confirmation") != SESSION_QUIESCENCE_CONFIRMATION
        or evidence.get("not_based_on_agents_logs") is not True
        or evidence.get("all_pages_checked") is not True
    ):
        raise AdapterError("Independent session inventory confirmation is missing or invalid")
    try:
        checked_at = datetime.fromisoformat(str(evidence["checked_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise AdapterError("Session inventory timestamp is invalid") from exc
    now = datetime.now(UTC)
    if (
        checked_at.utcoffset() != timedelta(0)
        or checked_at > now
        or now - checked_at > timedelta(seconds=SESSION_QUIESCENCE_MAX_AGE_SECONDS)
    ):
        raise AdapterError("Independent session inventory must be fresh and UTC-timestamped")
    pages = evidence.get("pages")
    if not isinstance(pages, list) or not pages:
        raise AdapterError(
            "Session inventory must include every page of the official list response"
        )
    session_ids: set[str] = set()
    # The official AgentSession enum is idle/in_progress/requires_action/failed.
    # Only failed is terminal; idle can still accept another turn.
    terminal = {"failed"}
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise AdapterError("Session inventory page is malformed")
        if type(page.get("has_more")) is not bool or page["has_more"] != (index < len(pages) - 1):
            raise AdapterError("Session inventory pagination is incomplete or inconsistent")
        if index:
            previous_last_id = pages[index - 1].get("last_id")
            if (
                not isinstance(previous_last_id, str)
                or not previous_last_id
                or page.get("after") != previous_last_id
            ):
                raise AdapterError("Session inventory pagination cursor chain is inconsistent")
        if page["has_more"]:
            last_session = page["data"][-1] if page["data"] else None
            if (
                not isinstance(last_session, dict)
                or not isinstance(page.get("last_id"), str)
                or not page["last_id"]
                or page["last_id"] != last_session.get("id")
            ):
                raise AdapterError(
                    "Session inventory page does not provide a valid continuation cursor"
                )
        for session in page["data"]:
            if not isinstance(session, dict) or not isinstance(session.get("id"), str):
                raise AdapterError("Session inventory contains an unidentifiable record")
            session_id = session["id"]
            if session_id in session_ids:
                raise AdapterError("Session inventory contains duplicate records")
            session_ids.add(session_id)
            status = session.get("status")
            if not isinstance(status, str) or status.casefold() not in terminal:
                raise AdapterError("An active or unrecognized Managed Agents session remains")

    return {
        "first_audit_sha256": hashlib.sha256(first_raw).hexdigest(),
        "first_authorization_sha256": hashlib.sha256(first_auth_raw).hexdigest(),
        "attempt_two_audit_sha256": hashlib.sha256(second_raw).hexdigest(),
        "attempt_two_authorization_sha256": hashlib.sha256(second_auth_raw).hexdigest(),
        "third_audit_sha256": hashlib.sha256(third_raw).hexdigest(),
        "third_authorization_sha256": hashlib.sha256(third_auth_raw).hexdigest(),
        "session_evidence_sha256": hashlib.sha256(evidence_raw).hexdigest(),
        "third_server_session_state": third_remote_state,
        "legacy_session_deletion_claim_ignored": ignored_legacy_deletion_claim,
        "independent_inventory_active_sessions": 0,
    }


def _verify_first_attempt_for_retry(
    state_directory: Path, result_path: Path, *, lease: SingleTrialLease | None = None
) -> dict[str, object]:
    """Require the immutable, clean audit for the already-consumed first try."""
    cleanup = verify_cleanup(state_directory, result_path, lease=lease)
    if not cleanup["local_cleanup_verified"]:
        raise AdapterError("Attempt 1 cleanup is not verified; attempt 2 remains blocked")
    audit = json.loads(Path(result_path).read_text(encoding="utf-8"))
    if not isinstance(audit, dict):
        raise AdapterError("First-attempt audit is not an object")
    common_valid = (
        audit.get("record_type") == "managed_agents_r01a_lifecycle_audit_not_benchmark_result"
        and audit.get("trial_id") == "R01-A"
        and audit.get("attempt_id", "R01-A/attempt-1") == "R01-A/attempt-1"
        and audit.get("session_created") is False
        and type(audit.get("sessions_created_count")) is int
        and audit.get("sessions_created_count") == 0
        and audit.get("inference_submitted") is False
        and audit.get("task_submission_attempted") is not True
        and type(audit.get("task_submissions_attempted_count")) is int
        and audit.get("task_submissions_attempted_count") == 0
        and audit.get("container_termination_verified") is True
        and audit.get("session_deleted_verified") is True
        and audit.get("topology_cleanup_verified") is True
        and audit.get("cleanup_verified") is True
    )
    if not common_valid:
        raise AdapterError("First-attempt audit reports work or cleanup that is not verified")

    failure = audit.get("failure")
    status = failure.get("http_status") if isinstance(failure, dict) else None
    if (
        isinstance(failure, dict)
        and failure.get("operation") == "create_session"
        and failure.get("category") == "http_rejection"
        and type(status) is int
        and 400 <= status < 500
    ):
        if audit.get("session_creation_attempted") is not True:
            raise AdapterError("First-attempt audit does not confirm one session-creation attempt")
        return {"classification": "http_rejection", "provider_status": status}

    # Older audit schema from before structured diagnostics. Do not infer or
    # synthesize an HTTP status; unknown status remains explicit uncertainty.
    legacy_valid = (
        "failure" not in audit
        and audit.get("failure_category") == "ManagedAgentsError"
        and audit.get("session_creation_attempted") is True
    )
    if legacy_valid:
        return {
            "classification": "legacy_create_session_failure_unclassified",
            "provider_status": "unknown",
        }
    raise AdapterError("First-attempt failure is not an eligible session-creation rejection")


def _verify_attempt_two_for_recovery(
    state_directory: Path,
    first_result_path: Path,
    attempt_two_result_path: Path,
    attempt_two_authorization_path: Path,
    *,
    lease: SingleTrialLease | None = None,
) -> dict[str, str]:
    """Verify an expired, pre-session attempt-2 failure for one new consent scope."""
    root = Path(state_directory).resolve()
    first_path = Path(first_result_path)
    second_path = Path(attempt_two_result_path)
    auth_path = Path(attempt_two_authorization_path)
    if any(
        not path.resolve().is_relative_to(root) for path in (first_path, second_path, auth_path)
    ):
        raise AdapterError("Recovery provenance must remain inside the external state directory")
    _verify_first_attempt_for_retry(root, first_path, lease=lease)
    cleanup = verify_cleanup(root, second_path, lease=lease)
    if not cleanup["local_cleanup_verified"] or not cleanup["live_lifecycle_cleanup_verified"]:
        raise AdapterError("Attempt 2 cleanup is not independently verified")

    def read_json(path: Path, limit: int) -> tuple[bytes, dict]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise AdapterError("Recovery provenance file is linked, missing, or oversized")
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AdapterError("Recovery provenance file is unavailable or invalid") from exc
        if not isinstance(value, dict):
            raise AdapterError("Recovery provenance must be a JSON object")
        return raw, value

    first_raw, _first_audit = read_json(first_path, 8 << 20)
    second_raw, audit = read_json(second_path, 8 << 20)
    auth_raw, prior_auth = read_json(auth_path, 64 << 10)
    state_names = (
        [item.get("state") if isinstance(item, dict) else item for item in audit.get("states", [])]
        if isinstance(audit.get("states"), list)
        else []
    )
    allowed_state_sequences = {
        ("prepare", "terminate_container", "cleanup"),
        ("prepare", "consume_authorization", "terminate_container", "cleanup"),
    }
    failure = audit.get("failure")
    failure_matches = failure is None or (
        isinstance(failure, dict)
        and failure.get("operation") == "consume_authorization"
        and failure.get("category") in {"local_validation", "local_error"}
    )
    audit_matches = (
        audit.get("record_type") == "managed_agents_r01a_lifecycle_audit_not_benchmark_result"
        and audit.get("synthetic") is False
        and audit.get("trial_id") == "R01-A"
        and audit.get("attempt_id") == "R01-A/attempt-2"
        and (
            audit.get("authorization_id") is None
            or audit.get("authorization_id") == prior_auth.get("authorization_id")
        )
        and audit.get("failure_category") == "AdapterError"
        and tuple(state_names) in allowed_state_sequences
        and audit.get("restricted_egress") is None
        and audit.get("checkpoint") is None
        and failure_matches
        and audit.get("session_creation_attempted") is False
        and audit.get("session_created") is False
        and type(audit.get("sessions_created_count")) is int
        and audit.get("sessions_created_count") == 0
        and audit.get("session_creation_uncertain") is not True
        and audit.get("task_submission_attempted") is not True
        and audit.get("task_submission_uncertain") is not True
        and type(audit.get("task_submissions_attempted_count")) is int
        and audit.get("task_submissions_attempted_count") == 0
        and audit.get("inference_submitted") is False
        and audit.get("cleanup_verified") is True
        and audit.get("container_termination_verified") is True
        and audit.get("session_deleted_verified") is True
        and audit.get("topology_cleanup_verified") is True
    )
    if not audit_matches:
        raise AdapterError(
            "Attempt 2 audit does not prove a pre-session local failure and clean shutdown"
        )

    markers = root / "consumed-trials"
    first_marker = markers / "R01-A.json"
    attempt_two_marker = markers / "R01-A-attempt-2.json"
    recovery_marker = markers / "R01-A-recovery-after-attempt-2.json"
    if first_marker.is_symlink() or not first_marker.is_file():
        raise AdapterError("The consumed first-attempt marker is missing")
    try:
        marker_data = json.loads(first_marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError("The consumed first-attempt marker is invalid") from exc
    if not isinstance(marker_data, dict) or marker_data.get("trial_id") != "R01-A":
        raise AdapterError("The consumed first-attempt marker has the wrong identity")
    if (
        attempt_two_marker.exists()
        or attempt_two_marker.is_symlink()
        or recovery_marker.exists()
        or recovery_marker.is_symlink()
    ):
        raise AdapterError("A prior attempt-2 or recovery marker already exists")

    prior_auth_id = prior_auth.get("authorization_id")
    if (
        prior_auth.get("attempt_id") != "R01-A/attempt-2"
        or prior_auth.get("authorized") is not True
        or prior_auth.get("consumed") is not False
        or prior_auth.get("typed_confirmation") != "AUTHORIZE ONE PAID TRIAL R01-A/attempt-2"
        or not re.fullmatch(r"[a-f0-9]{32}", str(prior_auth_id))
        or not isinstance(prior_auth.get("scope"), dict)
        or prior_auth["scope"].get("attempt_id") != "R01-A/attempt-2"
        or prior_auth["scope"].get("trial_id") != "R01-A"
        or prior_auth["scope"].get("previous_attempt_result") != str(first_path.resolve())
        or prior_auth["scope"].get("previous_attempt_audit_sha256")
        != hashlib.sha256(first_raw).hexdigest()
    ):
        raise AdapterError("Prior attempt-2 authorization does not match the preserved first audit")
    try:
        prior_issued = datetime.fromisoformat(prior_auth["issued_at"].replace("Z", "+00:00"))
        prior_expires = datetime.fromisoformat(prior_auth["expires_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError) as exc:
        raise AdapterError("Prior attempt-2 authorization timestamps are invalid") from exc
    if (
        prior_issued.utcoffset() != timedelta(0)
        or prior_expires.utcoffset() != timedelta(0)
        or prior_expires <= prior_issued
        or prior_expires - prior_issued > timedelta(seconds=MAX_AUTHORIZATION_TTL_SECONDS)
        or prior_expires > datetime.now(UTC)
    ):
        raise AdapterError("Prior attempt-2 authorization is not confirmed expired")
    if prior_auth["scope"].get("state_directory") != str(root):
        raise AdapterError("Prior attempt-2 authorization belongs to another state directory")
    consumed_auth_marker = root / "consumed-authorizations" / f"{prior_auth_id}.json"
    if consumed_auth_marker.exists() or consumed_auth_marker.is_symlink():
        raise AdapterError("Attempt-2 authorization already has a consumed marker")

    return {
        "first_audit_sha256": hashlib.sha256(first_raw).hexdigest(),
        "attempt_two_audit_sha256": hashlib.sha256(second_raw).hexdigest(),
        "authorization_sha256": hashlib.sha256(auth_raw).hexdigest(),
    }


def cancel_running_trial(state_directory: Path) -> dict:
    """Send SIGINT only to the adapter process named by the active-trial lock."""
    if os.name == "nt" or not Path("/proc").is_dir():
        raise AdapterError("Use Ctrl+C in the WSL2 run-one terminal to cancel this trial")
    state_directory = Path(state_directory).resolve()
    if state_directory.is_relative_to(REPO.resolve()):
        raise AdapterError("Execution state must be outside the evaluator repository")
    lock_path = state_directory / "active-trial.lock"
    if lock_path.is_symlink():
        raise AdapterError("Active-trial lock must not be a symbolic link")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        pid = lock["pid"]
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AdapterError("An active-trial process could not be verified") from exc
    if type(pid) is not int or b"adapter.py" not in command or b"run-one" not in command:
        raise AdapterError("Active-trial PID does not identify the R01-A run-one process")
    os.kill(pid, signal.SIGINT)
    return {"status": "sigint_sent_to_verified_run_one", "pid": pid, "trial_id": "R01-A"}


def inspect_result(path: Path) -> dict:
    """Read one bounded lifecycle audit without converting it to benchmark data."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > (8 << 20):
        raise AdapterError("Result must be a regular file no larger than 8 MiB")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError("Result JSON is unavailable or invalid") from exc
    allowed = {
        "managed_agents_r01a_lifecycle_audit_not_benchmark_result",
        "synthetic_r01a_lifecycle_audit_not_benchmark_result",
    }
    if not isinstance(record, dict) or record.get("record_type") not in allowed:
        raise AdapterError("File is not a recognized R01-A lifecycle audit")
    return {
        "record_type": record["record_type"],
        "synthetic": record.get("synthetic"),
        "trial_id": record.get("trial_id"),
        "status": record.get("status"),
        "scoring": record.get("scoring"),
        "usage": _usage_from_lifecycle_events(record.get("events", [])),
        "checkpoint": record.get("checkpoint"),
        "cleanup_verified": record.get("cleanup_verified"),
        "session_deleted_verified": record.get("session_deleted_verified"),
        "container_termination_verified": record.get("container_termination_verified"),
        "topology_cleanup_verified": record.get("topology_cleanup_verified"),
        "benchmark_importable": False,
    }


def _internal_sleep_probe() -> int:
    """Spawn a harmless child and sleep so the offline supervisor can test cleanup."""
    child_code = "import time; time.sleep(60)"
    if os.name == "nt":
        # Windows taskkill/pipe inheritance is not reliable in restricted
        # developer sandboxes. Do not claim descendant cleanup from this probe.
        print(json.dumps({"child_spawn_failure": "windows_tree_probe_unavailable"}), flush=True)
    else:
        try:
            child = subprocess.Popen(
                [sys.executable, "-c", child_code],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            print(json.dumps({"child_spawn_failure": type(exc).__name__}), flush=True)
        else:
            print(json.dumps({"child_pid": child.pid}), flush=True)
    time.sleep(60)
    return 0


def _terminate_process_tree(process: subprocess.Popen) -> dict:
    """Terminate only the process group created by the fixed offline probe."""
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return {"method": "taskkill_tree", "exit_code": result.returncode}
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            return {"method": "root_only_fallback", "exit_code": None}
    try:
        os.killpg(process.pid, signal.SIGKILL)
        return {"method": "process_group_sigkill", "exit_code": 0}
    except ProcessLookupError:
        return {"method": "already_exited", "exit_code": 0}


def _pid_is_running(pid: int) -> bool:
    """Check a known probe descendant without enumerating unrelated processes."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    if sys.platform.startswith("linux"):
        try:
            # A zombie has terminated; it only awaits collection by its parent.
            return Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()[2] != "Z"
        except (OSError, IndexError):
            return False
    return True


def run_local_timeout_probe(timeout_seconds: float = 0.25) -> dict:
    """Exercise real local process-tree timeout cleanup without invoking Codex."""
    if not 0 < timeout_seconds <= 5:
        raise AdapterError("Offline process probe timeout must be between 0 and 5 seconds")
    argv = [sys.executable, str(Path(__file__).resolve()), INTERNAL_PROBE_FLAG]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL if os.name == "nt" else subprocess.PIPE,
        stderr=subprocess.DEVNULL if os.name == "nt" else subprocess.PIPE,
        start_new_session=os.name != "nt",
        creationflags=creationflags,
        text=os.name != "nt",
    )
    started = time.monotonic()
    try:
        stdout = stderr = ""
        try:
            if os.name == "nt":
                process.wait(timeout=timeout_seconds)
            else:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            timed_out = False
            termination = {"method": "not_needed", "exit_code": None}
        except subprocess.TimeoutExpired:
            timed_out = True
            termination = _terminate_process_tree(process)
            if os.name == "nt":
                process.wait(timeout=5)
            else:
                stdout, stderr = process.communicate(timeout=5)
        child_pid = None
        child_spawn_failure = "windows_tree_probe_unavailable" if os.name == "nt" else None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and type(event.get("child_pid")) is int:
                child_pid = event["child_pid"]
            if isinstance(event, dict) and isinstance(event.get("child_spawn_failure"), str):
                child_spawn_failure = event["child_spawn_failure"]
        descendant_cleanup_verified = False
        if child_pid is not None and termination.get("exit_code") == 0:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and _pid_is_running(child_pid):
                time.sleep(0.05)
            descendant_cleanup_verified = not _pid_is_running(child_pid)
        return {
            "record_type": "local_process_cleanup_probe_not_trial",
            "synthetic": True,
            "codex_started": False,
            "model_requests": 0,
            "timed_out": timed_out,
            "process_exited": process.poll() is not None,
            "process_tree_termination": termination,
            "child_pid_observed": child_pid is not None,
            "child_spawn_failure": child_spawn_failure,
            "descendant_cleanup_verified": descendant_cleanup_verified,
            "elapsed_seconds": time.monotonic() - started,
            "stderr_redacted": redact(stderr)[:4096],
        }
    except BaseException:
        _terminate_process_tree(process)
        if os.name == "nt":
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
        raise


def prepare_workspace(task_id: str, destination: Path) -> dict:
    """Export only the public task fixture, then validate its exact file set."""
    destination = Path(destination)
    if destination.resolve().is_relative_to(REPO.resolve()):
        raise AdapterError("Candidate workspace must be outside the evaluator repository")
    if destination.exists():
        raise AdapterError("Candidate workspace destination must not already exist")
    pilot.bench.prepare(task_id, destination)
    context = build_trial_context(pilot.make_plan(), f"{task_id}-A", destination)
    return {
        "record_type": "public_candidate_workspace_prepared_not_isolation_proof",
        "task": task_id,
        "workspace": context["workspace"],
        "files": context["workspace_files"],
        "environment_fingerprint": context["environment_fingerprint"],
        "boundary_verified": False,
    }


def main(argv=None) -> int:
    if argv is None and len(sys.argv) == 2 and sys.argv[1] == INTERNAL_PROBE_FLAG:
        return _internal_sleep_probe()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--trial", required=True)
    preflight_parser.add_argument("--output", type=Path)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--task", required=True, choices=pilot.TASKS)
    prepare_parser.add_argument("--workspace", type=Path, required=True)
    dry_parser = sub.add_parser("dry-run")
    dry_parser.add_argument("--timeout-seconds", type=float, default=0.25)
    docker_parser = sub.add_parser("docker-isolation")
    docker_parser.add_argument("--trial", required=True, choices=["R01-A"])
    docker_parser.add_argument("--image", required=True)
    docker_parser.add_argument("--workspace", type=Path, required=True)
    egress_parser = sub.add_parser("docker-egress-probe")
    egress_parser.add_argument("--image", required=True)
    egress_parser.add_argument("--workspace", type=Path, required=True)
    proxy_probe_parser = sub.add_parser("docker-proxy-probe")
    proxy_probe_parser.add_argument("--image", required=True)
    proxy_probe_parser.add_argument("--workspace", type=Path, required=True)
    codex_probe_parser = sub.add_parser("codex-runtime-probe")
    codex_probe_parser.add_argument("--image", required=True)
    codex_probe_parser.add_argument("--workspace", type=Path, required=True)
    codex_probe_parser.add_argument("--timeout-seconds", type=float, default=5)
    docker_timeout_parser = sub.add_parser("docker-timeout-probe")
    docker_timeout_parser.add_argument("--image", required=True)
    docker_timeout_parser.add_argument("--timeout-seconds", type=float, default=1.0)
    auth_parser = sub.add_parser("authorize-one")
    auth_parser.add_argument("--trial", required=True, choices=["R01-A"])
    auth_parser.add_argument(
        "--attempt-id",
        required=True,
        choices=[
            "R01-A/attempt-1",
            "R01-A/attempt-2",
            RECOVERY_ATTEMPT_ID,
            FINAL_CONTINUATION_ATTEMPT_ID,
        ],
    )
    auth_parser.add_argument("--workspace", type=Path, required=True)
    auth_parser.add_argument("--image", required=True)
    auth_parser.add_argument("--available-balance-cents", type=int, required=True)
    auth_parser.add_argument("--reserve-cents", type=int, required=True)
    auth_parser.add_argument("--estimated-spend-cents", type=int, required=True)
    auth_parser.add_argument("--balance-source", required=True)
    auth_parser.add_argument("--balance-checked-at", required=True)
    auth_parser.add_argument("--confirm", required=True)
    auth_parser.add_argument("--confirm-restricted-key-scope", required=True)
    auth_parser.add_argument("--authorization-output", type=Path, required=True)
    auth_parser.add_argument("--previous-attempt-result", type=Path)
    auth_parser.add_argument("--first-attempt-result", type=Path)
    auth_parser.add_argument("--previous-attempt-authorization", type=Path)
    auth_parser.add_argument("--first-attempt-authorization", type=Path)
    auth_parser.add_argument("--attempt-two-result", type=Path)
    auth_parser.add_argument("--attempt-two-authorization", type=Path)
    auth_parser.add_argument("--session-quiescence-evidence", type=Path)
    run_parser = sub.add_parser("run-one")
    run_parser.add_argument("--trial", required=True, choices=["R01-A"])
    run_parser.add_argument(
        "--attempt-id",
        required=True,
        choices=[
            "R01-A/attempt-1",
            "R01-A/attempt-2",
            RECOVERY_ATTEMPT_ID,
            FINAL_CONTINUATION_ATTEMPT_ID,
        ],
    )
    run_parser.add_argument("--workspace", type=Path, required=True)
    run_parser.add_argument("--image", required=True)
    run_parser.add_argument("--authorization", type=Path, required=True)
    run_parser.add_argument("--result", type=Path, required=True)
    run_parser.add_argument("--previous-attempt-result", type=Path)
    run_parser.add_argument("--first-attempt-result", type=Path)
    run_parser.add_argument("--previous-attempt-authorization", type=Path)
    run_parser.add_argument("--first-attempt-authorization", type=Path)
    run_parser.add_argument("--attempt-two-result", type=Path)
    run_parser.add_argument("--attempt-two-authorization", type=Path)
    run_parser.add_argument("--session-quiescence-evidence", type=Path)
    sub.add_parser("cancel-one")
    cleanup_parser = sub.add_parser("verify-cleanup")
    cleanup_parser.add_argument("--result", type=Path, required=True)
    result_parser = sub.add_parser("inspect-result")
    result_parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            context = build_trial_context(pilot.make_plan(), args.trial)
            result = build_preflight(context)
            code = 2 if result["blocking_conditions"] else 0
        elif args.command == "prepare":
            result = prepare_workspace(args.task, args.workspace)
            code = 0
        elif args.command == "dry-run":
            result = run_local_timeout_probe(args.timeout_seconds)
            code = 0 if result["timed_out"] and result["process_exited"] else 2
        elif args.command == "authorize-one":
            state_directory = default_state_directory()
            if state_directory.resolve().is_relative_to(REPO.resolve()):
                raise AdapterError("Execution state must be outside the evaluator repository")
            try:
                balance_checked_at = datetime.fromisoformat(
                    args.balance_checked_at.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise AdapterError("Balance check time must be an ISO-8601 UTC timestamp") from exc
            if balance_checked_at.utcoffset() != timedelta(0):
                raise AdapterError("Balance check time must be UTC")
            result = create_authorization_file(
                plan=pilot.make_plan(),
                trial_id=args.trial,
                workspace=args.workspace,
                candidate_image_digest=args.image,
                state_directory=state_directory,
                typed_confirmation=args.confirm,
                available_balance_cents=args.available_balance_cents,
                reserve_cents=args.reserve_cents,
                estimated_spend_cents=args.estimated_spend_cents,
                balance_source=args.balance_source,
                balance_checked_at=balance_checked_at.isoformat(),
                restricted_key_scope_confirmation=args.confirm_restricted_key_scope,
                output=args.authorization_output,
                attempt_id=args.attempt_id,
                previous_attempt_result=args.previous_attempt_result,
                first_attempt_result=args.first_attempt_result,
                previous_attempt_authorization=args.previous_attempt_authorization,
                first_attempt_authorization=args.first_attempt_authorization,
                attempt_two_result=args.attempt_two_result,
                attempt_two_authorization=args.attempt_two_authorization,
                session_quiescence_evidence=args.session_quiescence_evidence,
            )
            code = 0
        elif args.command == "cancel-one":
            result = cancel_running_trial(default_state_directory())
            code = 0
        elif args.command == "verify-cleanup":
            result = verify_cleanup(default_state_directory(), args.result)
            code = 0 if result["cleanup_verified"] else 2
        elif args.command == "inspect-result":
            result = inspect_result(args.result)
            code = 0
        elif args.command in {
            "docker-isolation",
            "docker-egress-probe",
            "docker-proxy-probe",
            "docker-timeout-probe",
            "codex-runtime-probe",
        }:
            from docker_runtime import (
                CodexCandidateRuntime,
                DockerCandidateRuntime,
                run_codex_proxy_transport_probe,
                run_restricted_egress_probe,
            )

            if args.command == "codex-runtime-probe":
                runtime = CodexCandidateRuntime(args.image)
                result = runtime.run_offline_executor_probe(
                    args.workspace, timeout_seconds=args.timeout_seconds
                )
            elif args.command == "docker-egress-probe":
                result = run_restricted_egress_probe(args.image, args.workspace)
            elif args.command == "docker-proxy-probe":
                result = run_codex_proxy_transport_probe(args.image, args.workspace)
            else:
                runtime = DockerCandidateRuntime(args.image)
            if args.command == "docker-isolation":
                result = runtime.run_boundary_probe(args.workspace, trial_id=args.trial)
            elif args.command == "docker-timeout-probe":
                result = runtime.run_timeout_probe(timeout_seconds=args.timeout_seconds)
            if args.command in {"docker-egress-probe", "docker-proxy-probe"}:
                code = (
                    0
                    if result.get("candidate_container_removed")
                    and (
                        result.get("egress_proxy_and_networks_removed")
                        or result.get("local_proxy_container_removed")
                    )
                    and (
                        result.get("isolated_network_removed")
                        or result.get("egress_proxy_and_networks_removed")
                    )
                    else 2
                )
            else:
                code = (
                    0
                    if result.get("container_cleanup_verified", result.get("container_removed"))
                    else 2
                )
        elif args.command == "run-one":
            if args.authorization.is_symlink() or args.authorization.stat().st_size > (64 << 10):
                raise AdapterError("Authorization must be a regular bounded file")
            if args.result.is_symlink() or args.result.exists():
                raise AdapterError("Choose a new result path before authorizing the trial")
            if args.result.resolve().is_relative_to(REPO.resolve()):
                raise AdapterError(
                    "Lifecycle results must be stored outside the evaluator repository"
                )
            authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
            result = run_one(
                plan=pilot.make_plan(),
                trial_id=args.trial,
                authorization=authorization,
                state_directory=default_state_directory(),
                workspace=args.workspace,
                candidate_image_digest=args.image,
                attempt_id=args.attempt_id,
                previous_attempt_result=args.previous_attempt_result,
                first_attempt_result=args.first_attempt_result,
                previous_attempt_authorization=args.previous_attempt_authorization,
                first_attempt_authorization=args.first_attempt_authorization,
                attempt_two_result=args.attempt_two_result,
                attempt_two_authorization=args.attempt_two_authorization,
                session_quiescence_evidence=args.session_quiescence_evidence,
            )
            _private_json_write(args.result, result)
            code = 0 if result.get("cleanup_verified") else 2
    except (
        AdapterError,
        pilot.PilotError,
        OSError,
        RuntimeError,
        json.JSONDecodeError,
        KeyError,
    ) as exc:
        audit = getattr(exc, "audit_record", None)
        if getattr(args, "command", None) == "run-one" and isinstance(audit, dict):
            try:
                _private_json_write(args.result, audit)
                result = audit
            except OSError:
                result = {
                    "record_type": "single_trial_preflight_error",
                    "error": "Lifecycle failed and its audit record could not be persisted",
                }
        else:
            result = {"record_type": "single_trial_preflight_error", "error": redact(str(exc))}
        code = 2
    payload = json.dumps(redact(result), indent=2, ensure_ascii=False) + "\n"
    if getattr(args, "output", None):
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
