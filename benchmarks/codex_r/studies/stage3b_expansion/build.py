"""Build and verify the Stage 3B manifest and catalogue (pure functions of the files on disk).

    python -m benchmarks.codex_r.studies.stage3b_expansion.build --write   # regenerate
    python -m benchmarks.codex_r.studies.stage3b_expansion.build --check   # verify committed files

``manifest.json`` is what the runner reads (suite protocol, environment pins, one entry per task).
``catalog.json`` is the machine-readable research catalogue: authoring metadata from each
``tasks/<ID>/task.json``, content hashes of the task and scorer files, the *derived* MCP relevance
classification, and the candidate-pool status. Neither file contains hidden-check source.

Classification is derived, not asserted. A task is a ``target_candidate`` exactly when the Stage 2
rule holds on its hand-assigned dimensions (expected MCP usefulness plausible/high and a version,
documentation or API-verification dimension of at least 2). The authored classification must agree,
so a task cannot become a target merely because it names a package, and no model outcome is used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from benchmarks.codex_r.studies.stage2_validity_v1 import calibration
from benchmarks.codex_r.studies.stage2_validity_v1 import manifest as stage2

from . import suite

STAGE3B = suite.STAGE3B
MANIFEST = STAGE3B / "manifest.json"
CATALOG = STAGE3B / "catalog.json"
VALIDATION = STAGE3B / "validation_report.json"
REGISTRY = suite.bench.ROOT / "expansion" / "registry-v1.json"

CATALOG_VERSION = "stage3b-catalog-v1.0"
POOL = "stage3b-candidate-pool-v1"
CLASSIFICATIONS = ("target_candidate", "control", "exploratory")
USEFULNESS = ("none", "low", "plausible", "high")
RATINGS = ("none", "low", "moderate", "high")

# Packages not in configs/renv.lock are pinned here. Versions were read from the pinned scorer
# and executor images (identical package sets) and are re-verified by the scorer preflight.
PINS = {
    "stats": "4.5.2",
    "utils": "4.5.2",
    "tools": "4.5.2",
    "MASS": "7.3-65",
    "nlme": "3.1-168",
    "survival": "3.8-3",
    "BiocVersion": "3.22.0",
    "Biobase": "2.70.0",
    "SummarizedExperiment": "1.40.0",
    "DESeq2": "1.50.2",
}

REQUIRED_CONTROL_ROLES = ("reference",)
PROTOCOL = {
    "score_seconds": 240,
    "memory_mb": 2048,
    "cpus": 2,
    "pids": 256,
    "artifact_bytes": 1048576,
    "primary_metric": "fully_correct: every hidden behavioral check passes",
    "secondary_metric": "passed/total hidden checks",
    "outcome_classes": [
        "scored (fully_correct true: all checks pass)",
        "scored (fully_correct false: partially correct or incorrect)",
        "candidate_error (solution.R does not load, or output limit)",
        "candidate_timeout",
        "scoring_error (environment or verifier fault; never a candidate failure)",
    ],
}


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    return str(path.relative_to(STAGE3B)).replace("\\", "/")


def authoring() -> list[dict]:
    """All task.json files, validated, in task-id order."""
    tasks = []
    for path in sorted((STAGE3B / "tasks").glob("*/task.json")):
        task = _read(path)
        if task.get("schema_version") != 1:
            raise ValueError(f"{path}: unsupported task schema")
        if path.parent.name != task["id"] or not suite.TASK_ID.fullmatch(task["id"]):
            raise ValueError(f"{path}: id does not match its directory or the id pattern")
        tasks.append(task)
    return tasks


def derived_classification(task: dict) -> str:
    entry = {
        "dimensions": task["dimensions"],
        "expected_mcp_usefulness": task["expected_mcp_usefulness"],
    }
    if calibration.target_by_features(entry):
        return "target_candidate"
    d = task["dimensions"]
    low_need = max(d["version_sensitivity"], d["documentation_dependence"]) <= 1 and (
        d["package_api_verification_need"] <= 1
    )
    if task["expected_mcp_usefulness"] in ("none", "low") and low_need:
        return "control"
    return "exploratory"


def controls_of(task_id: str) -> list[dict]:
    """Sections of verifier/controls/<ID>.R: name, expectation (pass/fail), source text."""
    text = (STAGE3B / "verifier" / "controls" / f"{task_id}.R").read_text(encoding="utf-8")
    sections = []
    for block in re.split(r"(?m)^#### control: ", text)[1:]:
        name, _, source = block.partition("\n")
        name = name.strip()
        match = re.search(r"(?m)^# expect: (pass|fail)\s*$", source)
        if match:
            expectation = match.group(1)
        elif name == "reference" or name.startswith("alternate_"):
            expectation = "pass"
        elif name.startswith(("wrong_", "malformed_")):
            expectation = "fail"
        else:
            raise ValueError(f"{task_id}: control {name!r} needs an '# expect:' line")
        sections.append({"name": name, "expect": expectation, "source": source})
    return sections


def control_problems(task_id: str) -> list[str]:
    names = [c["name"] for c in controls_of(task_id)]
    problems = []
    if len(names) != len(set(names)):
        problems.append("duplicate control names")
    if "reference" not in names:
        problems.append("no reference control")
    if not any(n.startswith("alternate_") for n in names):
        problems.append("no alternate valid solution")
    if sum(n.startswith("wrong_") for n in names) < 2:
        problems.append("fewer than two wrong strategies")
    if not any(n.startswith("edge_") for n in names):
        problems.append("no edge/boundary control")
    if not any(n.startswith("malformed_") for n in names):
        problems.append("no incomplete/malformed control")
    return problems


def task_files(task_id: str) -> list[Path]:
    """Files that define a task: prompt, authoring metadata, fixtures, its hidden checks."""
    base = STAGE3B / "tasks" / task_id
    task = _read(base / "task.json")
    files = [base / "prompt.md", base / "task.json"]
    files += [base / fixture for fixture in task["fixtures"]]
    files.append(STAGE3B / "verifier" / f"{task_id}.R")
    return files


def scorer_files() -> list[Path]:
    """Scorer implementation shared by every task (including the reused hard-v1 harness)."""
    return [
        STAGE3B / "suite.py",
        STAGE3B / "verifier" / "run.R",
        STAGE3B / "verifier" / "lib.R",
        suite.hard.HARD / "verifier" / "harness.R",
    ]


def _digest_set(paths: list[Path]) -> dict[str, str]:
    root = suite.bench.REPO
    return {str(p.relative_to(root)).replace("\\", "/"): stage2.digest(p) for p in paths}


def build_manifest() -> dict:
    tasks = []
    for task in authoring():
        task_id = task["id"]
        verifier = STAGE3B / "verifier" / f"{task_id}.R"
        checks = len(re.findall(r'(?m)^check\("', verifier.read_text(encoding="utf-8")))
        entry = {
            "id": task_id,
            "title": task["title"],
            "category": task["category"],
            "image": task["image"],
            "packages": task["packages"],
            "spec": f"tasks/{task_id}/prompt.md",
            "fixtures": [f"tasks/{task_id}/{f}" for f in task["fixtures"]],
            "metadata": f"tasks/{task_id}/task.json",
            "verifier": f"verifier/{task_id}.R",
            "checks": checks,
            "artifacts": ["solution.R"],
        }
        if "score_seconds" in task:
            entry["score_seconds"] = task["score_seconds"]
        tasks.append(entry)
    return {
        "schema_version": 1,
        "benchmark": suite.BENCHMARK_ID,
        "status": "candidate pool: offline-validated verifiers, no paid runs, no stratum assigned",
        "environment": {
            "r": "4.5.2",
            "lockfile": "configs/renv.lock",
            "pins": PINS,
            "images": {"scorer": suite.IMAGES, "executor": suite.EXECUTOR_IMAGES},
            "note": "Scorer and executor images have identical package sets (2026-10-29).",
        },
        "protocol": PROTOCOL,
        "mcp": suite.hard.manifest()["mcp"],
        "tasks": tasks,
    }


def build_catalog(validation: dict | None = None) -> dict:
    """The research catalogue. ``validation`` (validation_report.json) is merged when current."""
    registry = {s["id"] for s in _read(REGISTRY)["tasks"]} if REGISTRY.is_file() else set()
    scorer = _digest_set(scorer_files())
    scorer_sha = stage2_combined(scorer)
    reports = {t["task"]: t for t in (validation or {}).get("tasks", [])}
    entries = []
    for task in authoring():
        task_id = task["id"]
        files = _digest_set(task_files(task_id))
        task_sha = stage2_combined(files)
        derived = derived_classification(task)
        authored = task["mcp_relevance"]["classification"]
        if authored != derived:
            raise ValueError(f"{task_id}: authored classification {authored} != derived {derived}")
        if authored not in CLASSIFICATIONS or task["expected_mcp_usefulness"] not in USEFULNESS:
            raise ValueError(f"{task_id}: unknown classification or usefulness vocabulary")
        if any(v not in range(4) for v in task["dimensions"].values()) or set(
            task["dimensions"]
        ) != set(calibration.DIMENSIONS):
            raise ValueError(f"{task_id}: dimensions must be exactly the Stage 2 set, values 0..3")
        if task["category"] != suite.CATEGORIES[task_id[1]]:
            raise ValueError(f"{task_id}: category does not match the id letter")
        for spec in task["source_specs"]:
            if registry and spec not in registry:
                raise ValueError(f"{task_id}: source spec {spec} is not in the expansion registry")
        problems = control_problems(task_id)
        report = reports.get(task_id)
        current = bool(
            report
            and report.get("task_sha256") == task_sha
            and report.get("scorer_sha256") == scorer_sha
        )
        validated = current and report.get("gate") == "passed"
        blockers = list(task["calibration_risks"]["blockers"]) + problems
        if not validated:
            blockers.append(
                "scorer validation gate not passed on the current files"
                if report
                else "scorer validation gate not run"
            )
        entries.append(
            {
                **{k: v for k, v in task.items() if k != "checks_documented_in"},
                "mcp_relevance": {**task["mcp_relevance"], "classification": derived},
                "hashes": {
                    "task_sha256": task_sha,
                    "scorer_sha256": scorer_sha,
                    "task_files": files,
                },
                "scorer": {
                    "identity": "stage3b-expansion-hidden-checks",
                    "version": "1.0",
                    "contract": "solution.R functions; hidden checks; passed/total; fully_correct",
                    "checks": len(
                        re.findall(
                            r'(?m)^check\("',
                            (STAGE3B / "verifier" / f"{task_id}.R").read_text(encoding="utf-8"),
                        )
                    ),
                    "controls": [c["name"] for c in controls_of(task_id)],
                },
                "validation": {
                    "gate": report.get("gate") if current else None,
                    "current": current,
                    "validated_at": report.get("validated_at") if current else None,
                },
                "pool": {
                    "pool": POOL,
                    "stratum": None,
                    "stratum_if_calibrated": {
                        "target_candidate": (
                            "RC-like: target by task text; enters S1 only if its Arm-A screen "
                            "falls in [0.10, 0.90] over >= 3 trials"
                        ),
                        "control": "S2-like control (tool-use tax); can never become S1",
                        "exploratory": "none until a versioned review assigns a role",
                    }[derived],
                    "calibration_eligible": validated,
                    "confirmatory_eligible": False,
                    "blockers": blockers,
                },
            }
        )
    return {
        "catalog_version": CATALOG_VERSION,
        "benchmark": suite.BENCHMARK_ID,
        "pool": POOL,
        "stratum_policy": (
            "No Stage 3B task is assigned S1, S2, RC or Q. Strata are assigned by a later, "
            "versioned review of Arm-A calibration data; thresholds are the preregistered ones."
        ),
        "scorer_files": scorer,
        "tasks": entries,
    }


def stage2_combined(digests: dict[str, str]) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def dump(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    validation = _read(VALIDATION) if VALIDATION.is_file() else None
    built = {MANIFEST: dump(build_manifest()), CATALOG: dump(build_catalog(validation))}
    status = 0
    for path, text in built.items():
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.name}")
        else:
            same = path.is_file() and path.read_text(encoding="utf-8") == text
            print(f"{path.name}: {'identical' if same else 'DIFFERENT'}")
            status |= 0 if same else 1
    return status


if __name__ == "__main__":
    sys.exit(main())
