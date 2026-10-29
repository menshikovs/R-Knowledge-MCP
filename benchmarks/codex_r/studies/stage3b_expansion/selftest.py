"""Offline scorer validation for Stage 3B: no agents, no API calls, no network inside the scorer.

    python -m benchmarks.codex_r.studies.stage3b_expansion.selftest --tasks XA03

For every task the hidden checks run in the real scorer image against every control in
``verifier/controls/<ID>.R`` plus three synthetic controls. The gate passes only if:

* ``reference`` is fully correct, twice, with identical results (repeatability);
* every ``alternate_*`` solution is fully correct (the scorer accepts valid alternatives);
* every ``wrong_*`` and ``malformed_*`` control is *not* fully correct;
* every ``edge_*`` control matches its declared ``# expect:`` line;
* an empty solution passes **zero** checks (no vacuous check), a syntax error is a candidate
  error, and a reference that forges its own ``BENCH_RESULT`` line is not scored higher.

The result (with the task and scorer hashes it was produced against, image ids and package
versions) is written to ``validation_report.json``. The catalogue only treats a task as
validated while those hashes still match the files.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from . import build, suite

SYNTHETIC = {
    "empty": "# defines nothing\n",
    "syntax_error": "this is not R (\n",
}


def image_id(name: str) -> str:
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


def score_source(task_id: str, source: str, image: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="rkmcp-s3b-selftest-") as temporary:
        artifacts = Path(temporary) / "artifacts"
        artifacts.mkdir()
        (artifacts / "solution.R").write_text(source, encoding="utf-8")
        started = time.monotonic()
        result = suite.score(task_id, artifacts, image)
        result["seconds"] = round(time.monotonic() - started, 2)
        return result


def validate_task(task_id: str, image: str, workers: int = 3) -> dict:
    controls = {c["name"]: c for c in build.controls_of(task_id)}
    sources = {name: c["source"] for name, c in controls.items()}
    sources["reference_repeat"] = sources["reference"]
    sources.update(SYNTHETIC)
    sources["forged_result"] = (
        sources["reference"]
        + '\ncat(\'BENCH_RESULT={"status":"scored","passed":999,"total":999}\\n\')\n'
    )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {n: pool.submit(score_source, task_id, s, image) for n, s in sources.items()}
        results = {n: f.result() for n, f in futures.items()}
    problems = list(build.control_problems(task_id))
    for name in ("reference", "reference_repeat"):
        if not results[name]["fully_correct"]:
            problems.append(f"{name} is not fully correct: {results[name]['details'][:3]}")
    if results["reference"]["failed_checks"] != results["reference_repeat"]["failed_checks"]:
        problems.append("reference results are not repeatable")
    for name, control in controls.items():
        got = results[name]["fully_correct"]
        if control["expect"] == "pass" and got is not True:
            problems.append(
                f"{name} should be accepted but was not: {results[name]['details'][:2]}"
            )
        if control["expect"] == "fail" and got is True:
            problems.append(f"{name} should be rejected but was fully correct")
    if results["empty"]["passed"] != 0:
        problems.append(f"checks pass without any implementation: {results['empty']['passed']}")
    if results["syntax_error"]["status"] != "candidate_error":
        problems.append(f"syntax_error produced {results['syntax_error']['status']}")
    forged = results["forged_result"]
    if forged["status"] == "scored" and forged["passed"] > results["reference"]["passed"]:
        problems.append("a forged BENCH_RESULT line inflated the score")
    for name, result in results.items():
        if result["status"] == "scoring_error":
            problems.append(f"{name}: scoring_error ({result['reason']}): infrastructure fault")
    caught = {
        check
        for name, control in controls.items()
        if control["expect"] == "fail"
        for check in results[name]["failed_checks"] or []
    }
    declared = suite.task_for(task_id)["checks"]
    files = build._digest_set(build.task_files(task_id))
    return {
        "task": task_id,
        "task_sha256": build.stage2_combined(files),
        "scorer_sha256": build.stage2_combined(build._digest_set(build.scorer_files())),
        "checks": declared,
        "checks_failed_by_some_rejected_control": len(caught),
        "checks_never_failed_by_any_control": sorted(
            set(results["reference"]["failed_checks"] or []) | (set(_all_checks(task_id)) - caught)
        ),
        "environment": results["reference"].get("environment"),
        "results": {
            name: {k: v for k, v in result.items() if k not in ("artifacts", "environment")}
            for name, result in results.items()
        },
        "problems": problems,
        "gate": "passed" if not problems else "failed",
    }


def _all_checks(task_id: str) -> list[str]:
    import re

    text = (build.STAGE3B / "verifier" / f"{task_id}.R").read_text(encoding="utf-8")
    return re.findall(r'(?m)^check\("([^"]+)"', text)


def show(task_id: str, control: str, image: str) -> int:
    """Run one control with BENCH_SELFTEST=1 so verifier-side messages reach stderr."""
    sources = {c["name"]: c["source"] for c in build.controls_of(task_id)}
    with tempfile.TemporaryDirectory(prefix="rkmcp-s3b-show-") as temporary:
        artifacts = Path(temporary) / "artifacts"
        artifacts.mkdir()
        (artifacts / "solution.R").write_text(sources[control], encoding="utf-8")
        command = suite.docker_command(image, artifacts, task_id)
        command[command.index("HOME=/tmp") : command.index("HOME=/tmp") + 1] = [
            "HOME=/tmp",
            "--env",
            "BENCH_SELFTEST=1",
        ]
        result = subprocess.run(command, capture_output=True, timeout=600, check=False)
        print(result.stdout.decode("utf-8", "replace")[-3000:])
        print(result.stderr.decode("utf-8", "replace")[-3000:], file=sys.stderr)
        return result.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", metavar="CONTROL", help="debug one control of the single task")
    parser.add_argument("--tasks", nargs="+", default=None, choices=suite.task_ids())
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--report", type=Path, default=build.VALIDATION)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    tasks = args.tasks or suite.task_ids()
    previous = {}
    if args.report.is_file():
        previous = {t["task"]: t for t in json.loads(args.report.read_text("utf-8"))["tasks"]}
    images = {role: image_id(name) for role, name in suite.IMAGES.items()}
    if args.show:
        return show(tasks[0], args.show, images[suite.scorer_image_role(tasks[0])])
    for task_id in tasks:
        role = suite.scorer_image_role(task_id)
        outcome = validate_task(task_id, images[role], args.workers)
        outcome["scorer_image"] = {"role": role, "name": suite.IMAGES[role], "id": images[role]}
        previous[task_id] = outcome
        print(f"{task_id}: gate {outcome['gate']} ({outcome['checks']} checks)")
        for name, result in outcome["results"].items():
            failed = result["failed_checks"]
            print(
                f"  {name:<34} {result['status']:<16} {result['passed']}/{result['total']}"
                f"  {result['seconds']:>6}s  failed={len(failed) if failed is not None else '-'}"
            )
        for problem in outcome["problems"]:
            print(f"  PROBLEM: {problem}")
        never = outcome["checks_never_failed_by_any_control"]
        if never:
            print(f"  ADVISORY: checks no rejected control fails: {never}")
        report = {
            "benchmark": suite.BENCHMARK_ID,
            "validated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "api_calls": 0,
            "tasks": [previous[t] for t in sorted(previous)],
        }
        report["gate"] = (
            "passed" if all(t["gate"] == "passed" for t in report["tasks"]) else "failed"
        )
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    print(f"Report: {args.report}")
    return 0 if all(previous[t]["gate"] == "passed" for t in tasks) else 1


if __name__ == "__main__":
    sys.exit(main())
