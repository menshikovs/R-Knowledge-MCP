"""Hard benchmark v1 suite: registry, public export, sealed artifacts and scoring.

It mirrors ``runner.bench``'s interface (``prepare``, ``seal_artifacts``, ``score``,
``task_for``) so ``run_simple.py`` can run either suite, and reuses its file-safety
helpers and bounded container executor. Like ``bench``, it never starts agents and
never reads credentials. The suite lives outside ``runner/`` so the original
experiment fingerprint is unchanged.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from benchmarks.codex_r.runner import bench

HARD = Path(__file__).resolve().parent
TASK_ID = re.compile(r"H(0[1-9]|10)\Z")


def manifest():
    data = bench.read_json(HARD / "manifest.json")
    if data.get("schema_version") != 1 or data.get("benchmark") != "r-knowledge-mcp-hard-v1":
        raise ValueError("Unsupported hard-benchmark manifest")
    lock = bench.read_json(bench.ROOT / data["environment"]["lockfile"])
    if lock["R"]["Version"] != data["environment"]["r"]:
        raise ValueError("R runtime and lock differ")
    seen = set()
    for task in data["tasks"]:
        if not TASK_ID.fullmatch(task["id"]) or task["id"] in seen:
            raise ValueError(f"Invalid or duplicate task id: {task['id']}")
        seen.add(task["id"])
        if task["artifacts"] != ["solution.R"]:
            raise ValueError("Hard tasks declare exactly one solution.R artifact")
        for key in ("spec", "verifier", "metadata"):
            bench.safe_file(HARD, task[key])
        for fixture in task["fixtures"]:
            bench.safe_file(HARD, fixture)
        declared = bench.safe_file(HARD, task["verifier"]).read_text(encoding="utf-8")
        if len(re.findall(r'(?m)^check\("', declared)) != task["checks"]:
            raise ValueError(f"{task['id']}: verifier check count differs from the manifest")
        for package in task["packages"]:
            if package not in lock["Packages"]:
                raise ValueError(f"{task['id']}: unlocked package {package}")
    if set(data["mcp"]["tools"]) & {"build_r_prompt", "validate_r_prompt", "get_r_prompt_context"}:
        raise ValueError("Prompt-construction tools are outside the with-mcp condition")
    return data


def task_ids():
    return [task["id"] for task in manifest()["tasks"]]


def task_for(task_id):
    return next(t for t in manifest()["tasks"] if t["id"] == task_id)


def prepare(task_id, destination):
    """Export only the public prompt, lockfile and fixtures; never the verifier."""
    task = task_for(task_id)
    destination = Path(destination).absolute()
    if bench.inside(destination, bench.REPO):
        raise ValueError("Candidate workspace must be outside the repository")
    if destination.exists() or any(p.is_symlink() for p in destination.parents):
        raise ValueError("Use a new workspace without symlink parents")
    destination.mkdir(parents=True)
    public = {
        "TASK.md": HARD / task["spec"],
        "renv.lock": bench.ROOT / manifest()["environment"]["lockfile"],
        **{f"data/{Path(fixture).name}": HARD / fixture for fixture in task["fixtures"]},
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
    task_for(task_id)
    original = Path(workspace).absolute()
    if any(p.is_symlink() for p in (original, *original.parents)):
        raise ValueError("Symlink workspaces are not allowed")
    workspace = original.resolve()
    if bench.inside(workspace, bench.REPO) or not workspace.is_dir():
        raise ValueError("Use a separate candidate directory")
    for path in (workspace, HARD, bench.ROOT):
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
        "--mount",
        f"type=bind,source={workspace},target=/candidate,readonly",
        "--mount",
        f"type=bind,source={HARD / 'verifier'},target=/verifier,readonly",
        "--mount",
        f"type=bind,source={bench.ROOT / 'configs'},target=/config,readonly",
        "--workdir",
        "/work",
        image,
        "timeout",
        "--kill-after=5",
        str(p["score_seconds"]),
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
    """Run the hidden checks on sealed artifacts in a bounded, networkless container."""
    task = task_for(task_id)
    with tempfile.TemporaryDirectory(prefix="codex-r-hard-score-") as temp:
        sealed = Path(temp) / "sealed"
        hashes = seal_artifacts(task_id, artifacts, sealed)
        command = docker_command(image, sealed, task_id)
        try:
            result = executor(command, timeout=manifest()["protocol"]["score_seconds"] + 15)
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
