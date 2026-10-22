"""Fail-closed Codex controller preflight and offline adapter dry-run.

This module deliberately has no real-model launch path. The installed Codex CLI
reports aggregate token usage after a turn, which cannot enforce this benchmark's
30,000-token ceiling before additional model work is billed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runner"))
import bench  # noqa: E402

SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[^\s,;]+"),
)
SECRET_KEYS = re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)")


class ControllerError(ValueError):
    """Invalid controller or trial configuration."""


class FakeCodexProcess:
    """An offline process outcome used only by the dry-run and its tests."""

    def __init__(self, exit_code=0, elapsed_seconds=1.0, events=()):
        self.exit_code = exit_code
        self.elapsed_seconds = elapsed_seconds
        self.events = events


def validate_public_workspace(workspace, task_id):
    """Reject candidate roots inside the evaluator or containing hidden inputs."""
    task = bench.task_for(task_id)
    candidate = Path(workspace)
    if candidate.is_symlink() or not candidate.is_dir():
        raise ControllerError("Candidate workspace must be an existing regular directory")
    if candidate.resolve().is_relative_to(bench.REPO.resolve()):
        raise ControllerError("Candidate workspace is inside the evaluator repository")
    if any(parent.is_symlink() for parent in candidate.parents):
        raise ControllerError("Candidate workspace has a symlink parent")
    expected = {"TASK.md", "renv.lock", f"data/{Path(task['fixture']).name}"}
    paths = list(candidate.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ControllerError("Candidate workspace cannot contain symlinks")
    found = {p.relative_to(candidate).as_posix() for p in paths if p.is_file()}
    if found != expected:
        raise ControllerError("Initial workspace must contain only the assigned public inputs")
    return {"files": sorted(found), "boundary_verified": False}


def validate_tool_inventory(config, observed_tools):
    """Require the externally observed list to equal the assigned effective list."""
    expected = config["tools"]
    if len(observed_tools) != len(set(observed_tools)) or set(observed_tools) != set(expected):
        raise ControllerError("Effective MCP tools differ from the exact condition allowlist")
    return True


def redact_secrets(value):
    """Redact credential-shaped text recursively before writing any evidence."""
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_KEYS.search(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    return value


def build_trial_config(experiment, trial_id):
    """Resolve one assigned row against the checked-in, immutable protocol."""
    manifest = bench.manifest()
    assignment = next((t for t in experiment.get("trials", []) if t["trial_id"] == trial_id), None)
    if assignment is None:
        raise ControllerError("Trial is not assigned by this randomized plan")
    if experiment.get("fingerprint") != bench.experiment_fingerprint():
        raise ControllerError("Plan fingerprint differs from the current benchmark inputs")
    if experiment.get("production_commit") != manifest["production_commit"]:
        raise ControllerError("Plan production commit differs from the preregistered baseline")
    if experiment.get("image") is None or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", experiment["image"]
    ):
        raise ControllerError("An immutable image digest is required")
    condition = assignment["condition"]
    tools = list(manifest["conditions"][condition]["tools"])
    return {
        "trial_id": trial_id,
        "task": assignment["task"],
        "condition": condition,
        "model": experiment["model"],
        "reasoning_effort": experiment["reasoning_effort"],
        "image": experiment["image"],
        "production_commit": experiment["production_commit"],
        "fingerprint": experiment["fingerprint"],
        "tools": tools,
        "mcp_integrations": [] if condition == "A" else ["r-knowledge-benchmark-gateway"],
        "fresh_ephemeral_session": True,
        "resume_allowed": False,
        "wall_time_limit_seconds": manifest["protocol"]["candidate_seconds"],
        "model_token_limit": manifest["protocol"]["token_budget"],
        "candidate_mounts": ["public task workspace only", "frozen R image"],
        "denied_mounts": [
            "evaluator repository",
            "oracle",
            "reference solutions",
            "host Docker socket",
            "other trials",
            "credentials",
        ],
        "ordinary_network": "disabled",
        "model_endpoint_route": "not implemented",
        "actual_codex_argv": None,
        "real_execution_enabled": False,
    }


def preflight(config, *, observed_tools=None, image_verified=False, auth_verified=False):
    """Return blockers; never infer capabilities from configuration or token logs."""
    expected = set(config["tools"])
    blockers = [
        "No supported preemptive cumulative 30,000-token controller is available; "
        "Codex usage is reported after model work.",
        "No verified isolated Codex execution adapter and restricted model-endpoint "
        "route is installed.",
        "Authentication and exact provider-resolved model access have not been verified.",
        "The frozen R image has not been verified by this controller.",
    ]
    # The booleans are only parameters for future verified adapters. The current
    # preflight intentionally remains blocked because none of those adapters exists.
    _ = auth_verified, image_verified
    if observed_tools is None:
        blockers.append("Effective MCP inventory has not been probed for this execution boundary.")
    elif set(observed_tools) != expected or len(observed_tools) != len(expected):
        blockers.append(
            "Observed MCP tool inventory does not exactly match the condition allowlist."
        )
    return {
        "status": "blocked" if blockers else "ready",
        "launch_permitted": False,
        "condition": config["condition"],
        "expected_tools": sorted(expected),
        "observed_tools": sorted(observed_tools) if observed_tools is not None else None,
        "token_enforcement": "unavailable",
        "wall_clock_enforcement": "not implemented for real Codex sessions",
        "blockers": blockers,
    }


def dry_run(config, fake_process=None):
    """Exercise configuration/event/timeout handling without starting Codex."""
    fake_process = fake_process or FakeCodexProcess(
        events=({"type": "turn.completed", "usage": None},)
    )
    if config.get("real_execution_enabled") or config.get("actual_codex_argv") is not None:
        raise ControllerError("Dry-run refuses executable Codex configurations")
    timed_out = fake_process.elapsed_seconds > config["wall_time_limit_seconds"]
    events = redact_secrets(list(fake_process.events))
    failed = timed_out or fake_process.exit_code != 0
    return {
        "record_type": "controller_dry_run_not_trial",
        "synthetic": True,
        "trial_id": config["trial_id"],
        "condition": config["condition"],
        "status": "simulated_timeout"
        if timed_out
        else ("simulated_error" if failed else "simulated_ready"),
        "usage": None,
        "events": events,
        "terminated": bool(timed_out),
        "cleanup_complete": True,
        "benchmark_record_created": False,
        "launch_permitted": False,
    }


def read_plan(path):
    return bench.read_json(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "dry-run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--plan", type=Path, required=True)
        cmd.add_argument("--trial", required=True)
        cmd.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = build_trial_config(read_plan(args.plan), args.trial)
        result = preflight(config) if args.command == "preflight" else dry_run(config)
        payload = json.dumps(redact_secrets(result), indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(payload, encoding="utf-8", newline="\n")
        else:
            print(payload, end="")
        return 2 if args.command == "preflight" and result["status"] == "blocked" else 0
    except (ControllerError, KeyError, ValueError, OSError) as exc:
        print(json.dumps({"status": "invalid", "error": redact_secrets(str(exc))}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
