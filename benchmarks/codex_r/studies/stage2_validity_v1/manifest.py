"""Machine-readable experiment specification and frozen-evidence digests (stage2_validity_v1).

`build_manifest()` is a pure function of files that must not change while the study is open (task
statements, metadata, verifiers, scorer modules, the tool-neutral instruction text, the MCP tool
names). Regenerating it must reproduce the committed `experiment_manifest.json` byte for byte; a
difference means a pinned input changed after the specification was written.

The manifest is a DRAFT until it is registered: registration = commit the final manifest and its
rendered PREREGISTRATION.md, then derive the randomization seed from that commit (`derive_seed`).
Nothing here authorises a model run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from benchmarks.codex_r import line_endings

from . import calibration, protocol

ROOT = line_endings.ROOT
CODEX = ROOT / "benchmarks" / "codex_r"
STUDY_DIR = Path(__file__).resolve().parent
BASELINE_COMMIT = "08ef9e9e2711e1174ed6796b3e3e60bf0ad7ca58"

PILOT_TASKS = {
    "D01": "exploratory_replication",
    "D02": "exploratory_replication",
    "D03": "exploratory_replication",
    "C01": "recalibration",
    "C04": "recalibration",
    "E02": "recalibration",
    "E03": "recalibration",
    "E05": "scorer_reliability",
    "R01": "control",
    "H10": "control",
}
SCORER_MODULES = (
    "knowledge_pilot.py",
    "knowledge_pilot_v2.py",
    "knowledge_pilot_v21.py",
    "hard/suite.py",
)
FROZEN_PATTERNS = (
    "benchmarks/codex_r/tasks",
    "benchmarks/codex_r/oracle",
    "benchmarks/codex_r/knowledge_pilot",
    "benchmarks/codex_r/hard",
    "benchmarks/codex_r/reports",
    "benchmarks/codex_r/scorer_evidence",
    "benchmarks/codex_r/configs",
    "benchmarks/codex_r/expansion",
    "benchmarks/codex_r/manifest.json",
    "benchmarks/codex_r/knowledge_pilot.py",
    "benchmarks/codex_r/knowledge_pilot_v2.py",
    "benchmarks/codex_r/knowledge_pilot_v21.py",
    "benchmarks/codex_r/rescore_b1_v21.py",
    "benchmarks/codex_r/LINE_ENDING_MIGRATION-v1.json",
)


def digest(path: Path) -> str:
    return line_endings.canonical_sha256(path)


def task_files(task: str) -> list[Path]:
    """Every repository file that defines a task: statement, metadata, fixtures-verifier."""
    candidates = []
    if task.startswith("R"):
        candidates = [CODEX / "tasks" / task / "task.md", CODEX / "oracle" / f"{task}.R"]
    elif task.startswith("H"):
        base = CODEX / "hard"
        candidates = [
            base / "tasks" / task / "prompt.md",
            base / "tasks" / task / "metadata.json",
            base / "verifier" / f"{task}.R",
        ]
    elif task.startswith("X"):
        # Stage 3B expansion tasks (separate, versioned catalogue; the 31-task one is unchanged).
        from benchmarks.codex_r.studies.stage3b_expansion import build as stage3b_build

        candidates = stage3b_build.task_files(task)
    else:
        base = CODEX / "knowledge_pilot"
        candidates = [
            base / "tasks" / f"{task}.md",
            base / "metadata" / f"{task}.json",
            base / "verifier" / f"{task}.R",
        ]
    return [p for p in candidates if p.is_file()]


def derive_seed(manifest_core_sha256: str, registration_commit: str) -> int:
    """Seed fixed by the registration commit, so it cannot be tuned after seeing the plan."""
    raw = hashlib.sha256(f"{manifest_core_sha256}|{registration_commit}".encode()).digest()
    return int.from_bytes(raw[:6], "big")


def mcp_tool_surface() -> dict:
    """Stable identity of the MCP surface: tool names and parameter names (not full schemas)."""
    import asyncio

    from cran_knowledge_mcp.server import create_server

    coro = create_server(toolset="consolidated").list_tools()
    try:
        coro.send(None)
    except StopIteration as stop:
        tools = stop.value
    else:
        tools = asyncio.run(coro)
    surface = sorted((t.name, sorted(t.inputSchema.get("properties", {}))) for t in tools)
    return {
        "toolset": "consolidated",
        "tools": [name for name, _ in surface],
        "surface_sha256": hashlib.sha256(json.dumps(surface).encode()).hexdigest(),
    }


def build_manifest() -> dict:
    base = protocol.base_instructions()
    pilot = []
    for task, role in PILOT_TASKS.items():
        files = task_files(task)
        entry = next(e for e in calibration.CATALOG if e["task"] == task)
        pilot.append(
            {
                "task": task,
                "role": role,
                "suite": entry["suite"],
                "scorer": entry["scorer"],
                "files": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in files},
            }
        )
    scorers = {m: digest(CODEX / m) for m in SCORER_MODULES}
    surface = mcp_tool_surface()
    core = {
        "study_id": protocol.STUDY_ID,
        "version": protocol.STUDY_VERSION,
        "status": "DRAFT - not registered; no confirmatory run is authorised",
        "baseline_commit": BASELINE_COMMIT,
        "research_question": (
            "Does making R-Knowledge-MCP available improve an agent's task performance compared "
            "with an otherwise equivalent agent without it?"
        ),
        "primary_hypothesis": {
            "H0": "mean within-task score difference (B - A) over the task population is 0",
            "H1": "it is not 0 (two-sided); the direction is not assumed",
        },
        "primary_estimand": (
            "Average over tasks of the within-task mean score difference B - A, by assignment of "
            "tool access (intention to treat); never conditioned on whether a tool was called."
        ),
        "primary_outcome": {
            "metric": (
                "task score = passed checks / total checks of the preregistered scorer, in [0,1]"
            ),
            "aggregation": (
                "mean over blocks within task, then mean over tasks (equal task weights)"
            ),
            "candidate_failure": "scored as 0",
            "missing": ["infrastructure_failure", "scoring_error", "not_executed"],
        },
        "secondary_outcomes": [
            "C - B",
            "C - A",
            "B - A fully_correct",
            "adoption",
            "cost",
            "latency",
        ],
        "arms": {
            arm.id: {
                "label": arm.label,
                "mcp_available": arm.mcp_available,
                "encouraged": arm.encouraged,
                "instructions_sha256": protocol.sha256_text(arm.instructions(base)),
                "description": arm.description,
            }
            for arm in protocol.ARMS.values()
        },
        "shared_instruction_sha256": protocol.sha256_text(base),
        "encouragement_sentence": protocol.ENCOURAGEMENT.strip(),
        "model": {
            "identity": "gpt-6-luna",
            "effort": "medium",
            "note": (
                "historical default; the exact model version string must be pinned at registration"
            ),
        },
        "tools": {"mcp": surface, "other_tools": "identical executor tools in every arm"},
        "egress_policy": {
            "all_arms": "internal network with an observing allow-list proxy",
            "arm_A": [protocol.MODEL_ENDPOINT],
            "arms_B_C": [protocol.MODEL_ENDPOINT, protocol.MCP_ENDPOINT],
            "violation_codes": [
                "egress_not_restricted",
                "egress_unverified",
                "egress_unexpected_destination",
            ],
            "implementation_status": "NOT IMPLEMENTED in the runner (plain bridge network)",
        },
        "randomization": {
            "algorithm": "blocked-latin-permutations-v1",
            "block": "task x repetition",
            "seed": None,
            "seed_rule": "derive_seed(sha256(core manifest), registration commit)",
            "fresh_context_per_trial": True,
        },
        "designs": {
            "pilot": {"tasks": len(PILOT_TASKS), "repetitions": 3, "arms": ["A", "B", "C"]},
            "recommended_confirmatory": {"tasks": 30, "repetitions": 3, "arms": ["A", "B", "C"]},
            "higher_confidence": {"tasks": 40, "repetitions": 5, "arms": ["A", "B", "C"]},
        },
        "pilot_tasks": pilot,
        "confirmatory_task_rule": {
            "minimum_tasks": 30,
            "eligibility": [
                "verifier kept private (only its SHA-256 is committed until the study ends)",
                "reference solution and >= 3 wrong strategies pass/fail as expected",
                ">= 5 independently written correct alternatives all pass (0 false negatives)",
                "dimensions classified before any trial from task text only",
                "arm-A calibration screen: mean in [0.10, 0.90] over >= 3 trials",
                "outcomes of arms with MCP access never used for inclusion",
            ],
            "strata": {
                "S1": "target",
                "S2": "control (tool-use tax)",
                "RC": "recalibrate",
                "Q": "quarantined",
            },
            "current_eligible_tasks": 0,
        },
        "scorers": {"modules": scorers, "versions": ["knowledge-pilot-v2.1", "hard-v1", "legacy"]},
        "analysis": {
            "plan": "STATISTICAL_ANALYSIS_PLAN.md",
            "primary_test": (
                "task-level sign-flip test on task mean differences (exact <= 16 tasks, else "
                "Monte Carlo); block-level flip as sensitivity analysis"
            ),
            "interval": "two-stage percentile bootstrap (tasks, then blocks within task)",
            "alpha": 0.05,
            "secondary_correction": "Holm over C-B, C-A, B-A fully_correct",
            "monte_carlo_permutations": 19999,
            "bootstrap_resamples": 5000,
        },
        "exclusions": {
            "invalidating_violations": [
                "arm_a_mcp_reachable",
                "arm_a_mcp_called",
                "treatment_not_delivered",
                "instructions_mismatch",
                "model_mismatch",
                "effort_mismatch",
                "scorer_version_mismatch",
                "egress_not_restricted",
                "egress_unverified",
                "egress_unexpected_destination",
                "tool_allowlist_unrecorded",
            ],
            "rule": (
                "excluded from the primary analysis, reported, and bounded by sensitivity analyses"
            ),
        },
        "failure_handling": {
            "retry_allowance": (
                "one re-run per infrastructure failure, same assignment, at most 10% of trials"
            ),
            "never": "a failed or missing trial is never deleted or replaced by a different task",
        },
        "stopping": (
            "fixed sample size; no interim looks; stop only for budget exhaustion or a safety issue"
        ),
        "budget": {
            "model_spend_limit": None,
            "status": "not authorised - a limit must be set and approved before any paid run",
            "timeout_seconds_per_trial": 900,
        },
        "exploratory_analyses": [
            "per-stratum and per-task effects",
            "adoption by task",
            "descriptive comparison of trials with and without tool calls (confounded)",
            "tool-result use proxy",
            "token and latency tradeoffs",
        ],
    }
    core_sha = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
    return {**core, "core_sha256": core_sha}


def frozen_digests() -> dict:
    """Canonical SHA-256 of every tracked frozen benchmark file, read from git HEAD blobs."""
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", *FROZEN_PATTERNS],
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    files = {}
    for raw in sorted(p for p in listing if p):
        name = raw.decode()
        blob = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{BASELINE_COMMIT}:{name}"], capture_output=True
        )
        if blob.returncode == 0:
            files[name] = hashlib.sha256(line_endings.lf(blob.stdout)).hexdigest()
    return {
        "schema_version": 1,
        "baseline_commit": BASELINE_COMMIT,
        "digest_basis": "SHA-256 of LF-normalised content at the baseline commit",
        "patterns": list(FROZEN_PATTERNS),
        "files": files,
    }


def verify_frozen(recorded: dict) -> list[str]:
    """Differences between recorded digests and the working tree (empty = nothing changed)."""
    problems = []
    for name, expected in recorded["files"].items():
        path = ROOT / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif digest(path) != expected:
            problems.append(f"changed: {name}")
    return problems
