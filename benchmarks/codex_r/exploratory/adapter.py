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
INTERNAL_PROBE_FLAG = "--internal-local-timeout-probe"
SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[^\s,;]+"),
)
SECRET_KEY = re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)")


class AdapterError(ValueError):
    """Invalid single-trial input or a blocked execution request."""


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


def build_trial_context(plan: dict, trial_id: str, workspace: Path | None = None) -> dict:
    """Resolve one exploratory assignment and bind its exact control values."""
    pilot.validate_plan(plan)
    selected = next((row for row in plan["trials"] if row["trial_id"] == trial_id), None)
    if selected is None:
        raise AdapterError("Trial ID is not assigned by the nine-trial pilot plan")
    expected_tools = set(pilot.bench.manifest()["conditions"][selected["condition"]]["tools"])
    context = {
        "trial_id": selected["trial_id"],
        "task": selected["task"],
        "condition": selected["condition"],
        "model": pilot.MODEL,
        "reasoning_effort": pilot.REASONING_EFFORT,
        "timeout_seconds": pilot.TRIAL_TIMEOUT_SECONDS,
        "expected_tools": sorted(expected_tools),
        "environment_fingerprint": environment_fingerprint(selected["task"]),
        "controller_version": CONTROLLER_VERSION,
        "workspace": str(workspace.resolve()) if workspace is not None else None,
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
) -> dict:
    """Create a narrowly scoped, short-lived consent record (never starts Codex)."""
    expected_confirmation = f"AUTHORIZE ONE PAID TRIAL {context['trial_id']}"
    if typed_confirmation != expected_confirmation:
        raise AdapterError("Typed confirmation must name exactly the selected paid trial")
    if ttl_seconds < 1 or ttl_seconds > MAX_AUTHORIZATION_TTL_SECONDS:
        raise AdapterError("Authorization lifetime must be between 1 and 300 seconds")
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise AdapterError("Authorization timestamp must be UTC-aware")
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
                "task",
                "condition",
                "model",
                "reasoning_effort",
                "environment_fingerprint",
                "workspace",
                "controller_version",
            )
        },
        "typed_confirmation": expected_confirmation,
        "consumed": False,
    }


def validate_authorization(
    authorization: dict, context: dict, *, now: datetime | None = None
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
        "consumed",
    }
    if not isinstance(authorization, dict) or set(authorization) != required:
        raise AdapterError("Authorization fields do not match the single-trial schema")
    if authorization["schema_version"] != 1 or authorization["authorized"] is not True:
        raise AdapterError("Explicit paid-trial authorization is missing")
    if authorization["consumed"] is not False:
        raise AdapterError("Authorization has already been consumed")
    if not re.fullmatch(r"[a-f0-9]{32}", str(authorization["authorization_id"])):
        raise AdapterError("Authorization ID is invalid")
    if authorization["typed_confirmation"] != f"AUTHORIZE ONE PAID TRIAL {context['trial_id']}":
        raise AdapterError("Authorization confirmation does not match this trial")
    scope = authorization["scope"]
    expected_scope = {
        key: context[key]
        for key in (
            "trial_id",
            "task",
            "condition",
            "model",
            "reasoning_effort",
            "environment_fingerprint",
            "workspace",
            "controller_version",
        )
    }
    if scope != expected_scope:
        raise AdapterError("Authorization scope differs from the prepared trial context")
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
    return authorization


class SingleTrialLease(AbstractContextManager):
    """Cross-process exclusive lock; keep it after unsafe/incomplete cleanup."""

    def __init__(self, state_directory: Path, trial_id: str):
        self.state_directory = Path(state_directory)
        self.trial_id = trial_id
        self.lock_path = self.state_directory / "active-trial.lock"
        self.acquired = False
        self.cleanup_verified = False

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
                            "created_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    + "\n"
                )
        except FileExistsError as exc:
            raise AdapterError(
                "Another trial is active or a stale lock needs operator review"
            ) from exc
        self.acquired = True
        return self

    def mark_cleanup_verified(self):
        self.cleanup_verified = True

    def __exit__(self, exc_type, exc, tb):
        if self.acquired and self.cleanup_verified:
            self.lock_path.unlink(missing_ok=True)
        return False


def consume_authorization(authorization: dict, context: dict, state_directory: Path) -> Path:
    """Atomically mark a valid authorization as used; markers are never auto-removed."""
    validate_authorization(authorization, context)
    root = Path(state_directory).resolve()
    if root.is_relative_to(REPO.resolve()):
        raise AdapterError("Authorization state must be outside the evaluator repository")
    consumed = root / "consumed-authorizations"
    consumed.mkdir(parents=True, exist_ok=True)
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


def run_one(*, plan: dict, trial_id: str, authorization: dict, state_directory: Path):
    """Phase B entry point; deliberately refuses while no secure backend is verified."""
    context = build_trial_context(plan, trial_id)
    report = build_preflight(context)
    if report["blocking_conditions"]:
        raise AdapterError(
            "Single-trial execution is blocked: " + ", ".join(report["blocking_conditions"])
        )
    # No runtime implementation may be selected by user-supplied configuration.
    validate_authorization(authorization, context)
    raise AdapterError("No secure Codex execution backend is installed")


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
    docker_timeout_parser = sub.add_parser("docker-timeout-probe")
    docker_timeout_parser.add_argument("--image", required=True)
    docker_timeout_parser.add_argument("--timeout-seconds", type=float, default=1.0)
    run_parser = sub.add_parser("run-one")
    run_parser.add_argument("--trial", required=True)
    run_parser.add_argument("--authorization", type=Path, required=True)
    run_parser.add_argument("--state-directory", type=Path, required=True)
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
        elif args.command in {"docker-isolation", "docker-timeout-probe"}:
            from docker_runtime import DockerCandidateRuntime

            runtime = DockerCandidateRuntime(args.image)
            if args.command == "docker-isolation":
                result = runtime.run_boundary_probe(args.workspace, trial_id=args.trial)
            else:
                result = runtime.run_timeout_probe(timeout_seconds=args.timeout_seconds)
            code = (
                0
                if result.get("container_cleanup_verified", result.get("container_removed"))
                else 2
            )
        else:
            authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
            run_one(
                plan=pilot.make_plan(),
                trial_id=args.trial,
                authorization=authorization,
                state_directory=args.state_directory,
            )
            raise AdapterError("Unexpected return from blocked run-one gate")
    except (
        AdapterError,
        pilot.PilotError,
        OSError,
        RuntimeError,
        json.JSONDecodeError,
        KeyError,
    ) as exc:
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
