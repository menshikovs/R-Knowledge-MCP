"""Offline experiment planning, safe artifact import and bounded Docker scoring.

This file never starts Codex or reads credentials. Run it directly; it is not part
of the production wheel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import statistics
import subprocess
import tempfile
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
MAX_JSON = 8 << 20


def read_json(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_JSON:
        raise ValueError("JSON file must be regular and bounded")
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inside(path, parent):
    return path.resolve().is_relative_to(parent.resolve())


def safe_file(root, relative):
    path = root / relative
    if path.is_symlink() or not inside(path, root) or not path.is_file():
        raise ValueError("File escapes its declared root or is not a regular file")
    # Reject symlink parents too, even if their resolved target stays under root.
    if any(p.is_symlink() for p in path.parents if p != root.parent):
        raise ValueError("Symlink parents are not allowed")
    return path


def manifest():
    data = read_json(ROOT / "manifest.json")
    if data["schema_version"] != 1:
        raise ValueError("Unsupported manifest")
    if [t["id"] for t in data["tasks"]] != [f"R{i:02}" for i in range(1, 13)]:
        raise ValueError("Exactly R01..R12 are required")
    if data["conditions"]["A"]["tools"]:
        raise ValueError("Baseline must have no MCP tools")
    b = set(data["conditions"]["B"]["tools"])
    c = set(data["conditions"]["C"]["tools"])
    if not b < c or "build_r_prompt" in b or "build_r_prompt" not in c:
        raise ValueError("Invalid condition separation")
    lock = read_json(ROOT / data["environment"]["lockfile"])
    if lock["R"]["Version"] != data["environment"]["r"]:
        raise ValueError("R runtime and lock differ")
    if lock["Bioconductor"]["Version"] != data["environment"]["bioconductor"]:
        raise ValueError("Bioconductor release and lock differ")
    for task in data["tasks"]:
        if task["groups"] != 4:
            raise ValueError("Scoring weights must remain fixed")
        for key in ("spec", "fixture", "oracle"):
            safe_file(ROOT, task[key])
        if safe_file(ROOT, task["oracle"]).read_text().count("test_that(") != 4:
            raise ValueError("Each oracle must declare four scored groups")
        for package in task["packages"]:
            if package not in lock["Packages"]:
                raise ValueError(f"Unlocked package: {package}")
    return data


def task_for(task_id):
    return next(t for t in manifest()["tasks"] if t["id"] == task_id)


def experiment_fingerprint():
    """Freeze public inputs, hidden oracles, environment and scoring code."""
    files = [ROOT / "manifest.json", ROOT / "configs/renv.lock"]
    for directory in ("tasks", "oracle", "runner", "configs"):
        files.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file()
            and p.suffix not in {".pyc"}
            and "__pycache__" not in p.parts
            and p.name != "renv.lock"
        )
    payload = {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(files))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def plan(model, effort, image, repetitions=2, seed=1729):
    data = manifest()
    if not model.strip() or model.casefold() in {"latest", "default"}:
        raise ValueError("An explicit model identifier is required")
    if effort not in {"low", "medium", "high", "xhigh"}:
        raise ValueError("Explicit supported reasoning effort required")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("Use a locally verified immutable Docker image ID")
    if not 1 <= repetitions <= 3:
        raise ValueError("Pilot supports one to three repetitions")
    rng = random.Random(seed)
    trials = []
    for repeat in range(1, repetitions + 1):
        ids = [t["id"] for t in data["tasks"]]
        rng.shuffle(ids)
        for task_id in ids:
            conditions = list("ABC")
            rng.shuffle(conditions)
            for condition in conditions:
                trials.append(
                    {
                        "trial_id": f"{task_id}-{condition}-{repeat}",
                        "task": task_id,
                        "condition": condition,
                        "repeat": repeat,
                    }
                )
    return {
        "schema_version": 1,
        "benchmark": data["benchmark"],
        "production_commit": data["production_commit"],
        "fingerprint": experiment_fingerprint(),
        "seed": seed,
        "model": model,
        "reasoning_effort": effort,
        "image": image,
        "protocol": data["protocol"],
        "trials": trials,
        "execution": "external; no agent sessions started",
    }


def prepare(task_id, destination):
    """Export only public inputs; no scorer, expected outputs, or solutions."""
    task = task_for(task_id)
    destination = Path(destination).absolute()
    if inside(destination, REPO):
        raise ValueError("Candidate workspace must be outside the repository")
    if destination.exists() or any(p.is_symlink() for p in destination.parents):
        raise ValueError("Use a new workspace without symlink parents")
    destination.mkdir(parents=True)
    public = {
        "TASK.md": ROOT / task["spec"],
        "renv.lock": ROOT / "configs/renv.lock",
        f"data/{Path(task['fixture']).name}": ROOT / task["fixture"],
    }
    for name, source in public.items():
        target = destination / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(source.read_bytes())
    return {"task": task_id, "files": {n: digest(destination / n) for n in public}}


def docker_command(image, workspace, *, scoring=False, task_id=None):
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("Immutable image ID required")
    original = Path(workspace).absolute()
    if any(p.is_symlink() for p in (original, *original.parents)):
        raise ValueError("Symlink workspaces are not allowed")
    workspace = original.resolve()
    if inside(workspace, REPO) or not workspace.is_dir():
        raise ValueError("Use a separate candidate directory")
    if any(c in str(workspace) for c in (",", "\n", "\r")):
        raise ValueError("Path cannot be safely represented in a Docker mount")
    p = manifest()["protocol"]
    command = [
        "docker",
        "run",
        "--rm",
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
        f"type=bind,source={workspace},target=/candidate" + (",readonly" if scoring else ""),
    ]
    if scoring:
        task_for(task_id)
        command += [
            "--name",
            "codex-r-score-" + uuid.uuid4().hex,
            "--mount",
            f"type=bind,source={ROOT / 'oracle'},target=/oracle,readonly",
            "--mount",
            f"type=bind,source={ROOT / 'configs'},target=/config,readonly",
            "--workdir",
            "/work",
            image,
            "timeout",
            "--kill-after=5",
            str(p["score_seconds"]),
            "Rscript",
            "--vanilla",
            "/oracle/run.R",
            task_id,
            "/candidate",
        ]
    else:
        # This is a tool-execution shell, not an invented Codex automation adapter.
        command += ["--workdir", "/candidate", image, "bash"]
    return command


def seal_artifacts(task_id, source, destination):
    """Allow only regular, UTF-8 source deliverables; ignore candidate outputs."""
    task = task_for(task_id)
    source, destination = Path(source).absolute(), Path(destination)
    if any(p.is_symlink() for p in (source, *source.parents)):
        raise ValueError("Symlink artifact roots are not allowed")
    source = source.resolve()
    if not source.is_dir() or destination.exists():
        raise ValueError("Invalid artifact source/destination")
    total = 0
    files = {}
    for name in task["artifacts"]:
        path = safe_file(source, name)
        content = path.read_bytes()
        total += len(content)
        if total > manifest()["protocol"]["artifact_bytes"]:
            raise ValueError("Artifact size limit exceeded")
        content.decode("utf-8", errors="strict")
        files[name] = content
    destination.mkdir()
    for name, content in files.items():
        (destination / name).write_bytes(content)
    # Include fixed PUBLIC input fixtures, not arbitrary files from the candidate.
    task_data = destination / "data"
    task_data.mkdir()
    fixture = ROOT / task["fixture"]
    (task_data / fixture.name).write_bytes(fixture.read_bytes())
    return {name: digest(destination / name) for name in files}


class OutputLimitExceeded(ValueError):
    pass


def execute_container(command, *, timeout):
    """Bound both output streams and stop the actual container on every exit path."""
    name = command[command.index("--name") + 1]
    if not re.fullmatch(r"codex-r-score-[a-f0-9]{32}", name):
        raise ValueError("Invalid disposable container name")
    captured = {}
    overflow = threading.Event()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def drain(stream, key):
        content = bytearray()
        while chunk := stream.read(8192):
            if len(content) + len(chunk) > MAX_JSON:
                overflow.set()
                process.kill()
                break
            content.extend(chunk)
        captured[key] = bytes(content)

    readers = [
        threading.Thread(target=drain, args=(stream, key), daemon=True)
        for stream, key in ((process.stdout, "stdout"), (process.stderr, "stderr"))
    ]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        # Killing a Docker CLI alone does NOT stop its running container.
        subprocess.run(
            ["docker", "rm", "--force", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        for reader in readers:
            reader.join(timeout=5)
    if overflow.is_set():
        raise OutputLimitExceeded("Candidate output exceeded the capture limit")
    return subprocess.CompletedProcess(
        command, process.returncode, captured.get("stdout", b""), captured.get("stderr", b"")
    )


def score(task_id, artifacts, image, *, executor=execute_container):
    """Execute untrusted candidate R only in a bounded, networkless container."""
    with tempfile.TemporaryDirectory(prefix="codex-r-score-") as temp:
        sealed = Path(temp) / "sealed"
        hashes = seal_artifacts(task_id, artifacts, sealed)
        command = docker_command(image, sealed, scoring=True, task_id=task_id)
        try:
            result = executor(command, timeout=manifest()["protocol"]["score_seconds"] + 10)
            output = result.stdout
        except subprocess.TimeoutExpired:
            return {"status": "candidate_timeout", "passed": 0, "total": 4, "artifacts": hashes}
        except OutputLimitExceeded:
            return {"status": "candidate_error", "passed": 0, "total": 4, "artifacts": hashes}
        if result.returncode != 0:
            if result.returncode == 124:
                return {"status": "candidate_timeout", "passed": 0, "total": 4, "artifacts": hashes}
            infrastructure = result.returncode in {125, 126, 127}
            return {
                "status": "scoring_error" if infrastructure else "candidate_error",
                "passed": None if infrastructure else 0,
                "total": 4,
                "artifacts": hashes,
            }
        try:
            lines = output.decode("utf-8").splitlines()
            records = [
                json.loads(line[len("BENCH_RESULT=") :])
                for line in lines
                if line.startswith("BENCH_RESULT=")
            ]
        except (UnicodeError, json.JSONDecodeError):
            return {"status": "candidate_error", "passed": 0, "total": 4, "artifacts": hashes}
        if len(records) != 1:
            return {"status": "candidate_error", "passed": 0, "total": 4, "artifacts": hashes}
        record = records[0]
        if record["status"] not in {"scored", "candidate_error", "scoring_error"}:
            raise ValueError("Invalid scorer status")
        passed = record["passed"]
        if record["status"] != "scoring_error" and (
            type(passed) is not int or not 0 <= passed <= 4
        ):
            raise ValueError("Invalid hidden-test score")
        return {**record, "total": 4, "artifacts": hashes}


def usage_from_events(events):
    """Only actual Codex turn usage; characters are never converted into tokens."""
    usage = [e["usage"] for e in events if e.get("type") == "turn.completed" and "usage" in e]
    if not usage:
        return None
    for u in usage:
        if any(type(u.get(k)) is not int or u[k] < 0 for k in ("input_tokens", "output_tokens")):
            raise ValueError("Invalid token usage")
    inp = sum(u["input_tokens"] for u in usage)
    out = sum(u["output_tokens"] for u in usage)
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}


def read_jsonl(path):
    path = Path(path)
    if path.stat().st_size > (64 << 20) or path.is_symlink():
        raise ValueError("JSONL file must be bounded and regular")
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def assemble_record(experiment, trial_id, metadata, scoring, events, audit):
    """Import an external run, deriving usage and calls from recorded evidence."""
    trial = next(t for t in experiment["trials"] if t["trial_id"] == trial_id)
    condition = trial["condition"]
    allowed = set(manifest()["conditions"][condition]["tools"])
    exposures = [r for r in audit if r.get("event") == "exposure"]
    calls = [r for r in audit if r.get("event") == "call"]
    if condition == "A":
        if audit:
            raise ValueError("Baseline cannot have an MCP audit")
    elif (
        len(exposures) != 1
        or exposures[0]["condition"] != condition
        or {t["name"] for t in exposures[0]["tools"]} != allowed
    ):
        raise ValueError("Tool exposure differs from the condition")
    if any(r["condition"] != condition or r["tool"] not in allowed for r in calls):
        raise ValueError("Non-protocol MCP call in the audit")
    for event in events:
        item = event.get("item", {})
        if item.get("type") == "mcp_tool_call" and item.get("tool") not in allowed:
            raise ValueError("External agent used an unassigned MCP tool")
    record = {
        k: metadata[k]
        for k in (
            "started_at",
            "completed_at",
            "isolation_verified",
            "model",
            "reasoning_effort",
            "image",
            "production_commit",
            "fingerprint",
            "invalid_api_calls",
            "repairs",
        )
    }
    record.update(
        {
            "trial_id": trial_id,
            "task": trial["task"],
            "condition": condition,
            "status": scoring["status"],
            "passed": scoring["passed"],
            "total": 4,
            "artifacts": scoring["artifacts"],
            "usage": usage_from_events(events),
            "mcp_calls": len(calls),
            "mcp_errors": sum(bool(r["result"].get("isError")) for r in calls),
        }
    )
    return validate_record(record, experiment)


def validate_record(record, experiment):
    required = {
        "trial_id",
        "task",
        "condition",
        "model",
        "reasoning_effort",
        "image",
        "production_commit",
        "fingerprint",
        "started_at",
        "completed_at",
        "status",
        "passed",
        "total",
        "isolation_verified",
        "artifacts",
        "usage",
        "mcp_calls",
        "mcp_errors",
        "invalid_api_calls",
        "repairs",
    }
    if set(record) != required:
        raise ValueError("Result fields differ from the documented schema")
    planned = next((x for x in experiment["trials"] if x["trial_id"] == record["trial_id"]), None)
    if not planned or any(record[k] != planned[k] for k in ("task", "condition")):
        raise ValueError("Result does not match an assigned trial")
    for key in ("model", "reasoning_effort", "image", "production_commit", "fingerprint"):
        if record[key] != experiment[key]:
            raise ValueError(f"Treatment control changed: {key}")
    if record["isolation_verified"] is not True:
        raise ValueError("Unblinded/unverified trials cannot enter the comparative cohort")
    if record["status"] not in {
        "scored",
        "candidate_error",
        "candidate_timeout",
        "security_violation",
        "scoring_error",
    }:
        raise ValueError("Unknown outcome")
    if record["total"] != 4:
        raise ValueError("Scoring denominator changed")
    passed = record["passed"]
    if record["status"] == "scoring_error":
        if passed is not None:
            raise ValueError("Infrastructure failure is missing data")
    elif type(passed) is not int or not 0 <= passed <= 4:
        raise ValueError("Invalid score")
    elif record["status"] != "scored" and passed != 0:
        raise ValueError("Candidate failures score zero")
    times = [
        datetime.fromisoformat(record[k].replace("Z", "+00:00"))
        for k in ("started_at", "completed_at")
    ]
    if any(t.utcoffset() is None for t in times) or times[1] < times[0]:
        raise ValueError("Invalid UTC-aware timestamps")
    seconds = (times[1] - times[0]).total_seconds()
    if seconds > experiment["protocol"]["candidate_seconds"] and record["status"] == "scored":
        raise ValueError("Candidate exceeded the predeclared deadline")
    for key in ("mcp_calls", "mcp_errors", "invalid_api_calls", "repairs"):
        if record[key] is not None and (type(record[key]) is not int or record[key] < 0):
            raise ValueError(f"Invalid metric: {key}")
    if record["mcp_calls"] is None or record["mcp_errors"] is None:
        raise ValueError("MCP gateway audit is required, including zero calls")
    if record["mcp_errors"] > record["mcp_calls"]:
        raise ValueError("More MCP errors than calls")
    if record["condition"] == "A" and record["mcp_calls"]:
        raise ValueError("Baseline accessed MCP")
    if record["usage"] is not None:
        u = record["usage"]
        if set(u) != {"input_tokens", "output_tokens", "total_tokens"}:
            raise ValueError("Invalid usage fields")
        if any(type(v) is not int or v < 0 for v in u.values()):
            raise ValueError("Invalid usage counts")
        if u["total_tokens"] != u["input_tokens"] + u["output_tokens"]:
            raise ValueError("Inconsistent token totals")
        if u["total_tokens"] > experiment["protocol"]["token_budget"]:
            raise ValueError("Token budget exceeded")
    if not isinstance(record["artifacts"], dict) or any(
        not re.fullmatch(r"[a-f0-9]{64}", h) for h in record["artifacts"].values()
    ):
        raise ValueError("Invalid artifact hashes")
    expected_artifacts = set(task_for(record["task"])["artifacts"])
    if not set(record["artifacts"]) <= expected_artifacts:
        raise ValueError("Unexpected artifact names")
    if record["status"] == "scored" and set(record["artifacts"]) != expected_artifacts:
        raise ValueError("Scored trials require sealed artifacts")
    return record


def report(experiment, records):
    ids = [r["trial_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate trials would bias the analysis")
    for r in records:
        validate_record(r, experiment)
    lines = [
        "# Codex R pilot results",
        "",
        f"Assigned trials: {len(experiment['trials'])}; recorded trials: {len(records)}.",
        "Scoring infrastructure failures and absent trials are missing data.",
        "",
    ]
    if not records:
        lines += ["No comparative agent execution results are available yet.", ""]
    lines += [
        "| Condition | Assigned | Evaluable | Missing | Full success | Mean score |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in "ABC":
        assigned = sum(t["condition"] == c for t in experiment["trials"])
        rows = [r for r in records if r["condition"] == c and r["passed"] is not None]
        success = sum(r["passed"] == 4 for r in rows)
        per_task = defaultdict(list)
        for row in rows:
            per_task[row["task"]].append(row["passed"] / 4)
        mean = statistics.mean(statistics.mean(v) for v in per_task.values()) if rows else None
        lines.append(
            f"| {c} | {assigned} | {len(rows)} | {assigned - len(rows)} | "
            f"{success}/{len(rows)} | {mean if mean is not None else 'unavailable'} |"
        )
    lines += [
        "",
        "## Per-task scores (mean; missing stays unavailable)",
        "",
        "| Task | A | B | C |",
        "| --- | ---: | ---: | ---: |",
    ]
    for task in manifest()["tasks"]:
        scores = []
        for c in "ABC":
            values = [
                r["passed"] / 4
                for r in records
                if r["task"] == task["id"] and r["condition"] == c and r["passed"] is not None
            ]
            scores.append(f"{statistics.mean(values):.3f}" if values else "unavailable")
        lines.append(f"| {task['id']} | " + " | ".join(scores) + " |")
    lines += [
        "",
        "## Paired differences",
        "Paired mean hidden-test score differences; 95% task-cluster bootstrap "
        "intervals are descriptive, not evidence of significance.",
        "",
    ]
    index = {r["trial_id"]: r for r in records if r["passed"] is not None}
    for c in "BC":
        blocks = defaultdict(list)
        for trial in experiment["trials"]:
            if trial["condition"] != c:
                continue
            a = index.get(f"{trial['task']}-A-{trial['repeat']}")
            other = index.get(trial["trial_id"])
            if a and other:
                blocks[trial["task"]].append((other["passed"] - a["passed"]) / 4)
        means = [statistics.mean(v) for v in blocks.values()]
        if len(means) < 2:
            lines.append(f"- {c} − A: unavailable (fewer than two paired task clusters).")
        else:
            rng = random.Random(experiment["seed"])
            draws = sorted(statistics.mean(rng.choices(means, k=len(means))) for _ in range(2000))
            lines.append(
                f"- {c} − A: {statistics.mean(means):.3f}; "
                f"95% cluster interval [{draws[49]:.3f}, {draws[1949]:.3f}]; "
                f"{len(means)} task clusters."
            )
    lines += ["", "## Timing, usage, failures and missing metrics", ""]
    for c in "ABC":
        rows = [r for r in records if r["condition"] == c]
        times = [
            (
                datetime.fromisoformat(r["completed_at"]) - datetime.fromisoformat(r["started_at"])
            ).total_seconds()
            for r in rows
        ]
        failures = sum(r["status"] != "scored" or r["passed"] != 4 for r in rows)
        lines.append(
            f"- {c}: recorded failures={failures}; "
            f"elapsed seconds min/median/max="
            f"{(min(times), statistics.median(times), max(times)) if times else 'unavailable'}."
        )
        for metric in ("usage", "mcp_calls", "mcp_errors", "invalid_api_calls", "repairs"):
            known = [r[metric] for r in rows if r[metric] is not None]
            if metric == "usage":
                known = [v["total_tokens"] for v in known]
            lines.append(
                f"  - {metric}: observed total={sum(known) if known else 'unavailable'}; "
                f"missing={len(rows) - len(known)}/{len(rows)}."
            )
        usage = [r["usage"] for r in rows if r["usage"] is not None]
        if usage:
            lines.append(
                f"  - Actual input/output tokens: "
                f"{sum(u['input_tokens'] for u in usage)}/"
                f"{sum(u['output_tokens'] for u in usage)}."
            )
        api_counts = [r["invalid_api_calls"] for r in rows if r["invalid_api_calls"] is not None]
        lines.append(
            f"  - Trials with independently observed invalid API use: "
            f"{sum(n > 0 for n in api_counts)}/{len(api_counts)}."
        )
    lines += [
        "",
        "Raw trial records remain authoritative. No token estimates or cost estimates "
        "are substituted. Invalid-API counts require an independent human/instrumented "
        "audit; unavailable counts cannot establish API correctness. Small samples, "
        "optional tool use, correlated trials and incomplete compliance limit inference.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("validate")
    p = sub.add_parser("plan")
    p.add_argument("--model", required=True)
    p.add_argument("--reasoning-effort", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--repetitions", type=int, default=2)
    p.add_argument("--seed", type=int, default=1729)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--task", required=True)
    p.add_argument("--workspace", type=Path, required=True)
    p = sub.add_parser("container")
    p.add_argument("--image", required=True)
    p.add_argument("--workspace", type=Path, required=True)
    p = sub.add_parser("score")
    p.add_argument("--task", required=True)
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--image", required=True)
    for action in ("import", "report"):
        p = sub.add_parser(action)
        p.add_argument("--plan", type=Path, required=True)
        p.add_argument("--input", type=Path, required=True)
    p = sub.add_parser("record")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--trial", required=True)
    for name in ("metadata", "score", "events", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--audit", type=Path)
    args = parser.parse_args()
    if args.action == "validate":
        data = manifest()
        print(json.dumps({"tasks": len(data["tasks"]), "fingerprint": experiment_fingerprint()}))
    elif args.action == "plan":
        data = plan(args.model, args.reasoning_effort, args.image, args.repetitions, args.seed)
        args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    elif args.action == "prepare":
        print(json.dumps(prepare(args.task, args.workspace)))
    elif args.action == "container":
        print(json.dumps(docker_command(args.image, args.workspace)))
    elif args.action == "score":
        print(json.dumps(score(args.task, args.artifacts, args.image)))
    elif args.action == "record":
        experiment = read_json(args.plan)
        if experiment["fingerprint"] != experiment_fingerprint():
            raise ValueError("Experiment files changed since pre-registration")
        record = assemble_record(
            experiment,
            args.trial,
            read_json(args.metadata),
            read_json(args.score),
            read_jsonl(args.events),
            read_jsonl(args.audit) if args.audit else [],
        )
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(record) + "\n")
    else:
        experiment, records = read_json(args.plan), read_jsonl(args.input)
        if experiment["fingerprint"] != experiment_fingerprint():
            raise ValueError("Experiment files changed since pre-registration")
        if args.action == "report":
            print(report(experiment, records), end="")
        else:
            report(experiment, records)  # Includes duplicate-ID and cross-field validation.
            print(
                json.dumps(
                    {
                        "validated_records": len(records),
                        "status": "import validated; no candidate execution performed",
                    }
                )
            )


if __name__ == "__main__":
    main()
