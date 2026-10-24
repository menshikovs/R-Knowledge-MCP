"""Offline verifier validation: no agents, no API calls, no network inside the scorer.

    python -m benchmarks.codex_r.hard.selftest --tasks H01 H04 H10

For every task the hidden checks run in the real scorer image against the trusted
reference (twice, for repeatability), every deliberately wrong control, and three
synthetic controls: an empty solution (no check may pass vacuously), a syntax
error, and a reference that forges its own BENCH_RESULT line. The gate fails unless
the reference is fully correct and every other control is not.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.codex_r.hard import suite

CONTROLS = suite.HARD / "verifier" / "controls"
SYNTHETIC = {
    "empty": "# defines nothing\n",
    "syntax_error": "this is not R (\n",
}


def image_id(name):
    result = subprocess.run(
        ["docker", "image", "inspect", name, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    value = result.stdout.strip()
    if result.returncode or not value.startswith("sha256:"):
        raise RuntimeError(f"Docker image unavailable: {name}")
    return value


def score_source(task_id, source, image):
    with tempfile.TemporaryDirectory(prefix="rkmcp-hard-selftest-") as temporary:
        artifacts = Path(temporary) / "artifacts"
        artifacts.mkdir()
        (artifacts / "solution.R").write_text(source, encoding="utf-8")
        started = time.monotonic()
        result = suite.score(task_id, artifacts, image)
        result["seconds"] = round(time.monotonic() - started, 2)
        return result


def validate_task(task_id, image):
    directory = CONTROLS / task_id
    reference = (directory / "reference.R").read_text(encoding="utf-8")
    controls = {"reference": reference, "reference_repeat": reference}
    for path in sorted(directory.glob("wrong_*.R")):
        controls[path.stem] = path.read_text(encoding="utf-8")
    controls.update(SYNTHETIC)
    controls["forged_result"] = (
        reference + '\ncat(\'BENCH_RESULT={"status":"scored","passed":999,"total":999}\\n\')\n'
    )
    results = {name: score_source(task_id, source, image) for name, source in controls.items()}
    problems = []
    for name in ("reference", "reference_repeat"):
        if not results[name]["fully_correct"]:
            problems.append(f"{name} is not fully correct: {results[name]['details'][:3]}")
    if results["reference"]["failed_checks"] != results["reference_repeat"]["failed_checks"]:
        problems.append("reference results are not repeatable")
    wrong = [name for name in controls if name.startswith("wrong_")]
    if len(wrong) < 2:
        problems.append("fewer than two deliberately wrong strategies")
    for name in wrong:
        if results[name]["fully_correct"] is not False:
            problems.append(f"{name} was not rejected")
    if results["empty"]["passed"] != 0:
        problems.append(f"checks pass without any implementation: {results['empty']}")
    if results["syntax_error"]["status"] != "candidate_error":
        problems.append(f"syntax_error produced {results['syntax_error']['status']}")
    # Candidate output goes to an isolated process, so a forged line must not
    # change the score: it is either rejected or scored like the reference.
    forged = results["forged_result"]
    if forged["status"] == "scored" and forged["passed"] > results["reference"]["passed"]:
        problems.append("a forged BENCH_RESULT line inflated the score")
    caught = {check for name in wrong for check in results[name]["failed_checks"] or []}
    total = suite.task_for(task_id)["checks"]
    return {
        "task": task_id,
        "checks": total,
        "checks_failed_by_some_wrong_control": len(caught),
        "results": {
            name: {k: v for k, v in result.items() if k != "artifacts"}
            for name, result in results.items()
        },
        "problems": problems,
        "gate": "passed" if not problems else "failed",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="+", default=None, choices=suite.task_ids())
    parser.add_argument("--scorer-image", default="codex-r-benchmark:pilot")
    parser.add_argument(
        "--report", type=Path, default=suite.HARD / "reports" / "offline-validation.json"
    )
    args = parser.parse_args(argv)
    # Windows consoles may not encode R's Unicode diagnostics.
    sys.stdout.reconfigure(errors="replace")
    image = image_id(args.scorer_image)
    tasks = args.tasks or suite.task_ids()
    report = {
        "benchmark": suite.manifest()["benchmark"],
        "validated_at": datetime.now(UTC).isoformat(),
        "scorer_image": {"name": args.scorer_image, "id": image},
        "api_calls": 0,
        "tasks": [],
    }
    for task_id in tasks:
        outcome = validate_task(task_id, image)
        report["tasks"].append(outcome)
        print(f"{task_id}: gate {outcome['gate']} ({outcome['checks']} checks)")
        for name, result in outcome["results"].items():
            failed = result["failed_checks"]
            print(
                f"  {name:<28} {result['status']:<16} {result['passed']}/{result['total']}"
                f"  {result['seconds']:>6}s  failed={len(failed) if failed is not None else '-'}"
            )
        for problem in outcome["problems"]:
            print(f"  PROBLEM: {problem}")
    report["gate"] = "passed" if all(t["gate"] == "passed" for t in report["tasks"]) else "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gate: {report['gate']}. Report: {args.report}")
    return 0 if report["gate"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
