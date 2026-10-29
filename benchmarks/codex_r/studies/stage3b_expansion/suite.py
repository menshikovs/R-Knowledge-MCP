"""Stage 3B expansion suite: registry, public export, sealed artifacts and scoring.

Same interface as ``hard.suite`` (``prepare``, ``seal_artifacts``, ``score``, ``task_for``) so
``run_simple.py`` can run it unchanged apart from suite dispatch, and the same contract:

* An agent sees only ``tasks/<ID>/prompt.md`` (exported as ``TASK.md``), the lockfile and the
  declared public fixtures under ``data/``. ``task.json`` (classification, MCP relevance, source
  mapping), the verifier and its controls are never exported.
* Exactly one artifact, ``solution.R``, defining the functions the prompt names. Hidden checks
  call those functions in an isolated ``callr`` session on withheld data variants and compare
  returned plain values against independent oracles.
* Scoring runs in the networkless, read-only, non-root scorer container after the agent session.

The hard-v1 harness (``hard/verifier/harness.R``) is mounted read-only and reused unchanged; the
hard-v1 suite, its manifest and its hashes are not modified.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from benchmarks.codex_r.hard import suite as hard
from benchmarks.codex_r.runner import bench

STAGE3B = Path(__file__).resolve().parent
BENCHMARK_ID = "r-knowledge-mcp-stage3b-v1"
TASK_ID = re.compile(r"X[AGPVRM][0-9]{2}\Z")
CATEGORIES = {
    "A": "anova_statistical_inference",
    "G": "ggplot2_visualization",
    "P": "package_discovery",
    "V": "version_sensitive_api",
    "R": "code_repair_migration",
    "M": "multi_step_workflow",
}
IMAGES = {"base": "codex-r-benchmark:pilot", "bioc": "codex-r-benchmark:pilot-bioc"}
EXECUTOR_IMAGES = {
    "base": "rkmcp-codex-runtime:codex-0.163.0",
    "bioc": "rkmcp-codex-runtime:codex-0.163.0-bioc",
}


def manifest():
    data = bench.read_json(STAGE3B / "manifest.json")
    if data.get("schema_version") != 1 or data.get("benchmark") != BENCHMARK_ID:
        raise ValueError("Unsupported stage 3B manifest")
    lock = bench.read_json(bench.ROOT / data["environment"]["lockfile"])
    if lock["R"]["Version"] != data["environment"]["r"]:
        raise ValueError("R runtime and lock differ")
    pins = data["environment"]["pins"]
    seen = set()
    for task in data["tasks"]:
        if not TASK_ID.fullmatch(task["id"]) or task["id"] in seen:
            raise ValueError(f"Invalid or duplicate task id: {task['id']}")
        seen.add(task["id"])
        if task["artifacts"] != ["solution.R"]:
            raise ValueError("Stage 3B tasks declare exactly one solution.R artifact")
        if task["image"] not in IMAGES:
            raise ValueError(f"{task['id']}: unknown image role")
        for key in ("spec", "verifier", "metadata"):
            bench.safe_file(STAGE3B, task[key])
        for fixture in task["fixtures"]:
            bench.safe_file(STAGE3B, fixture)
        declared = bench.safe_file(STAGE3B, task["verifier"]).read_text(encoding="utf-8")
        if len(re.findall(r'(?m)^check\("', declared)) != task["checks"]:
            raise ValueError(f"{task['id']}: verifier check count differs from the manifest")
        for package in task["packages"]:
            if package not in lock["Packages"] and package not in pins:
                raise ValueError(f"{task['id']}: package {package} is neither locked nor pinned")
    if set(data["mcp"]["tools"]) & {"build_r_prompt", "validate_r_prompt", "get_r_prompt_context"}:
        raise ValueError("Prompt-construction tools are outside the with-mcp condition")
    return data


def task_ids():
    return [task["id"] for task in manifest()["tasks"]]


def task_for(task_id):
    return next(t for t in manifest()["tasks"] if t["id"] == task_id)


def owns(task_id):
    """Whether ``task_id`` is a registered Stage 3B task (cheap pattern test first)."""
    return bool(TASK_ID.fullmatch(str(task_id))) and task_id in task_ids()


def scorer_image_role(task_id):
    return task_for(task_id)["image"]


def prepare(task_id, destination):
    """Export only the public prompt, lockfile and fixtures; never the verifier or task.json."""
    task = task_for(task_id)
    destination = Path(destination).absolute()
    if bench.inside(destination, bench.REPO):
        raise ValueError("Candidate workspace must be outside the repository")
    if destination.exists() or any(p.is_symlink() for p in destination.parents):
        raise ValueError("Use a new workspace without symlink parents")
    destination.mkdir(parents=True)
    public = {
        "TASK.md": STAGE3B / task["spec"],
        "renv.lock": bench.ROOT / manifest()["environment"]["lockfile"],
        **{f"data/{Path(fixture).name}": STAGE3B / fixture for fixture in task["fixtures"]},
    }
    for name, source in public.items():
        target = destination / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(source.read_bytes())
    return {"task": task_id, "files": {n: bench.digest(destination / n) for n in public}}


def seal_artifacts(task_id, source, destination):
    """Copy only the declared regular UTF-8 deliverables (no symlinks, bounded size)."""
    task = task_for(task_id)
    source, destination = Path(source).absolute(), Path(destination)
    if any(p.is_symlink() for p in (source, *source.parents)):
        raise ValueError("Symlink artifact roots are not allowed")
    source = source.resolve()
    if not source.is_dir() or destination.exists():
        raise ValueError("Invalid artifact source/destination")
    files, total = {}, 0
    for name in task["artifacts"]:
        content = bench.safe_file(source, name).read_bytes()
        total += len(content)
        if total > manifest()["protocol"]["artifact_bytes"]:
            raise ValueError("Artifact size limit exceeded")
        content.decode("utf-8", errors="strict")
        files[name] = content
    destination.mkdir()
    for name, content in files.items():
        (destination / name).write_bytes(content)
    return {name: bench.digest(destination / name) for name in files}


def docker_command(image, workspace, task_id):
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("Immutable image ID required")
    task = task_for(task_id)
    original = Path(workspace).absolute()
    if any(p.is_symlink() for p in (original, *original.parents)):
        raise ValueError("Symlink workspaces are not allowed")
    workspace = original.resolve()
    if bench.inside(workspace, bench.REPO) or not workspace.is_dir():
        raise ValueError("Use a separate candidate directory")
    verifier = STAGE3B / "verifier"
    for path in (workspace, verifier, hard.HARD, bench.ROOT):
        if any(c in str(path) for c in (",", "\n", "\r")):
            raise ValueError("Path cannot be safely represented in a Docker mount")
    p = manifest()["protocol"]
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        "codex-r-score-" + uuid.uuid4().hex,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--cpus",
        str(p["cpus"]),
        "--memory",
        f"{p['memory_mb']}m",
        "--memory-swap",
        f"{p['memory_mb']}m",
        "--pids-limit",
        str(p["pids"]),
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m,mode=1777",
        "--tmpfs",
        "/work:rw,nosuid,size=256m,mode=1777",
        "--env",
        "HOME=/tmp",
        "--env",
        "TZ=UTC",
        "--env",
        "LC_ALL=C.UTF-8",
        "--env",
        "BENCH_TASK_PACKAGES=" + ",".join(task["packages"]),
        "--env",
        "BENCH_PINS="
        + ",".join(
            f"{name}={version}" for name, version in manifest()["environment"]["pins"].items()
        ),
        "--mount",
        f"type=bind,source={workspace},target=/candidate,readonly",
        "--mount",
        f"type=bind,source={verifier},target=/verifier,readonly",
        "--mount",
        f"type=bind,source={hard.HARD / 'verifier'},target=/hardv,readonly",
        "--mount",
        f"type=bind,source={bench.ROOT / 'configs'},target=/config,readonly",
        "--workdir",
        "/work",
        image,
        "timeout",
        "--kill-after=5",
        str(task.get("score_seconds", p["score_seconds"])),
        "Rscript",
        "--vanilla",
        "/verifier/run.R",
        task_id,
        "/candidate",
    ]


def _failure(status, task, hashes, reason):
    infrastructure = status == "scoring_error"
    return {
        "status": status,
        "passed": None if infrastructure else 0,
        "total": task["checks"],
        "fully_correct": None if infrastructure else False,
        "reason": reason,
        "failed_checks": None,
        "details": [],
        "environment": None,
        "artifacts": hashes,
    }


def score(task_id, artifacts, image, *, executor=bench.execute_container):
    """Run the hidden checks on sealed artifacts in a bounded, networkless container.

    Outcome classes: ``scored`` (all checks ran; ``fully_correct`` iff every check passed),
    ``candidate_error`` (malformed or non-loading solution, output limit, unparseable result),
    ``candidate_timeout``, and ``scoring_error`` (environment or verifier fault, never a
    candidate failure: ``passed`` and ``fully_correct`` are ``None``).
    """
    task = task_for(task_id)
    with tempfile.TemporaryDirectory(prefix="codex-r-stage3b-score-") as temp:
        sealed = Path(temp) / "sealed"
        hashes = seal_artifacts(task_id, artifacts, sealed)
        command = docker_command(image, sealed, task_id)
        limit = task.get("score_seconds", manifest()["protocol"]["score_seconds"])
        try:
            result = executor(command, timeout=limit + 15)
        except subprocess.TimeoutExpired:
            return _failure("candidate_timeout", task, hashes, "scorer_deadline")
        except bench.OutputLimitExceeded:
            return _failure("candidate_error", task, hashes, "output_limit")
        if result.returncode == 124:
            return _failure("candidate_timeout", task, hashes, "scorer_deadline")
        if result.returncode != 0:
            infrastructure = result.returncode in {125, 126, 127}
            return _failure(
                "scoring_error" if infrastructure else "candidate_error",
                task,
                hashes,
                f"exit_{result.returncode}",
            )
        try:
            records = [
                json.loads(line[len("BENCH_RESULT=") :])
                for line in result.stdout.decode("utf-8").splitlines()
                if line.startswith("BENCH_RESULT=")
            ]
        except (UnicodeError, json.JSONDecodeError):
            return _failure("candidate_error", task, hashes, "unparseable_result")
        # A candidate that prints its own result line cannot forge a score.
        if len(records) != 1:
            return _failure("candidate_error", task, hashes, "ambiguous_result")
        record = records[0]
        status = record.get("status")
        if status == "scoring_error":
            return _failure("scoring_error", task, hashes, record.get("reason"))
        if status not in {"scored", "candidate_error"}:
            raise ValueError("Invalid scorer status")
        passed, total = record.get("passed"), record.get("total")
        if total != task["checks"] or type(passed) is not int or not 0 <= passed <= total:
            raise ValueError("Hidden-check counts differ from the manifest")
        return {
            "status": status,
            "passed": passed,
            "total": total,
            "fully_correct": status == "scored" and passed == total,
            "reason": record.get("reason"),
            "failed_checks": [record["failed_checks"]]
            if isinstance(record.get("failed_checks"), str)
            else record.get("failed_checks") or [],
            "details": record.get("details") or [],
            "environment": record.get("environment"),
            "artifacts": hashes,
        }
