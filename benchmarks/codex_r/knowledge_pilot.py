"""B/C/D/E tool-value pilot tasks and offline scorers for run_simple."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from benchmarks.codex_r.runner import bench

PILOT = Path(__file__).resolve().parent / "knowledge_pilot"
TASK_ID = re.compile(r"(?:B0[1-3]|C0[1-5]|D0[1-3]|E0[1-5])\Z")
PILOT_TASK_IDS = tuple(
    [f"B{number:02}" for number in range(1, 4)]
    + [f"C{number:02}" for number in range(1, 6)]
    + [f"D{number:02}" for number in range(1, 4)]
    + [f"E{number:02}" for number in range(1, 6)]
)
MAX_ANSWER_BYTES = 64 * 1024
# v1 compared source/documentation URLs with one curated string each (not recorded in runs).
# v2 accepts any URL from the frozen official CRAN allowlist of the recommended package.
D_SCORER_VERSION = "d-recommendation-2"
E_SCORER_VERSION = "e-compatibility-1"
OFFICIAL_HOSTS = frozenset({"cran.r-project.org", "stat.ethz.ch"})


def manifest():
    data = bench.read_json(PILOT / "manifest.json")
    if data.get("schema_version") != 1 or data.get("benchmark") != "r-knowledge-tool-value-v1":
        raise ValueError("Unsupported tool-value pilot manifest")
    lock = bench.read_json(bench.ROOT / data["environment"]["lockfile"])
    if lock["R"]["Version"] != data["environment"]["r"]:
        raise ValueError("Pilot R runtime and lock differ")
    seen = set()
    for task in data["tasks"]:
        if not TASK_ID.fullmatch(task["id"]) or task["id"] in seen:
            raise ValueError(f"Invalid or duplicate pilot task id: {task['id']}")
        seen.add(task["id"])
        metadata_path = bench.safe_file(PILOT, task["metadata"])
        spec_path = bench.safe_file(PILOT, task["spec"])
        metadata = bench.read_json(metadata_path)
        if (
            metadata.get("id") != task["id"]
            or metadata.get("environment", {}).get("r") != lock["R"]["Version"]
        ):
            raise ValueError(f"{task['id']}: task metadata identity/environment differs")
        if metadata.get("reference_package") != task.get("reference_package"):
            raise ValueError(f"{task['id']}: reference package version differs from manifest")
        if metadata.get("environment", {}).get("packages", {}) != task["packages"]:
            raise ValueError(f"{task['id']}: task metadata package pins differ")
        if task.get("required_packages", {}) != metadata.get("reference_packages", {}):
            if task.get("required_packages"):
                raise ValueError(f"{task['id']}: reference package pins differ")
        for package, version in task["packages"].items():
            locked = lock["Packages"].get(package, {}).get("Version")
            if locked != version:
                raise ValueError(f"{task['id']}: {package} is not pinned to {version}")
        if not spec_path.is_file():
            raise ValueError(f"{task['id']}: public task specification is missing")
        for item in task["public_files"]:
            bench.safe_file(PILOT, item["source"])
        if task["block"] in {"B", "C"} or (task["block"] == "E" and task.get("scorer") == "r"):
            verifier_path = bench.safe_file(PILOT, task["verifier"])
            check_count = len(re.findall(r'(?m)^check\("', verifier_path.read_text()))
            if check_count != task["checks"]:
                raise ValueError(f"{task['id']}: hidden check count differs")
            if task.get("starter"):
                starter_path = bench.safe_file(PILOT, task["starter"])
                if not starter_path.is_file():
                    raise ValueError(f"{task['id']}: starter is missing")
            controls_root = PILOT / "verifier" / "controls"
            controls = controls_root / task["id"]
            if (
                controls.is_symlink()
                or not controls.is_dir()
                or not controls.resolve().is_relative_to(controls_root.resolve())
            ):
                raise ValueError(f"{task['id']}: invalid private controls directory")
            bench.safe_file(controls, "reference.R")
            negative_controls = task.get("negative_controls", ["wrong.R"])
            if not isinstance(negative_controls, list) or not negative_controls:
                raise ValueError(f"{task['id']}: negative controls are missing")
            for control in negative_controls:
                if not isinstance(control, str) or not re.fullmatch(
                    r"(?:wrong|wrong_[a-z0-9_]+)\.R", control
                ):
                    raise ValueError(f"{task['id']}: invalid negative control name")
                bench.safe_file(controls, control)
        elif task["block"] == "D" or (task["block"] == "E" and task.get("scorer") == "json"):
            controls = PILOT / "verifier" / "controls" / task["id"]
            for control in ("reference.json", *task.get("negative_controls", ["wrong.json"])):
                bench.safe_file(controls, control)
            if task["block"] == "D":
                _validate_official_resources(task["id"])
        else:
            raise ValueError(f"{task['id']}: unsupported task block")
    expected_tasks = set(PILOT_TASK_IDS)
    if len(seen) != len(expected_tasks) or seen != expected_tasks:
        raise ValueError("Pilot must contain B01-B03, C01-C05, D01-D03 and E01-E05")
    configurations = data["configurations"]
    current = [key for key, value in configurations.items() if value["status"] == "current"]
    if len(current) != 1 or any(
        value["status"] not in {"current", "historical", "opt_in"}
        for value in configurations.values()
    ):
        raise ValueError("Manifest needs exactly one current configuration")
    return data


def configuration(configuration_id=None):
    """A named MCP/scorer configuration from the manifest; default is the single current one."""
    configurations = manifest()["configurations"]
    if configuration_id is None:
        (configuration_id,) = [
            key for key, value in configurations.items() if value["status"] == "current"
        ]
    if configuration_id not in configurations:
        raise ValueError(f"Unknown benchmark configuration: {configuration_id}")
    return {"id": configuration_id, **configurations[configuration_id]}


def official_resources():
    """Frozen official CRAN URLs per task and package; read from disk, never fetched."""
    data = bench.read_json(bench.safe_file(PILOT / "verifier", "official_resources.json"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported official resource allowlist")
    return data["tasks"]


def _validate_official_resources(task_id):
    candidates = bench.read_json(bench.safe_file(PILOT / "verifier", "candidates.json"))[task_id]
    frozen = official_resources().get(task_id, {})
    if set(frozen) != set(candidates):
        raise ValueError(f"{task_id}: official resource allowlist and candidates differ")
    for package, candidate in candidates.items():
        entry = frozen[package]
        if entry.get("resource_version") != candidate["version"]:
            raise ValueError(f"{task_id}/{package}: allowlist is frozen for another version")
        urls = {kind: _resource_urls(entry, kind) for kind in ("source", "documentation")}
        if not urls["source"] or not urls["documentation"]:
            raise ValueError(f"{task_id}/{package}: allowlist lacks source or documentation")
        for url in urls["source"] | urls["documentation"]:
            parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or parts.netloc not in OFFICIAL_HOSTS
                or parts.query
                or parts.fragment
                or package not in parts.path + parts.query
            ):
                raise ValueError(f"{task_id}/{package}: unofficial allowlist URL {url}")
        if (
            candidate["source_url"] not in urls["source"]
            or candidate["documentation_url"] not in urls["documentation"]
        ):
            raise ValueError(f"{task_id}/{package}: curated URLs are missing from the allowlist")


def _resource_urls(entry, kind):
    return {item["url"] for item in entry["resources"] if item["kind"] == kind}


def task_ids():
    return [task["id"] for task in manifest()["tasks"]]


def task_for(task_id):
    return next(task for task in manifest()["tasks"] if task["id"] == task_id)


def verify_scorer_image(image, task_ids, *, executor=bench.execute_container):
    return verify_runtime_image(image, task_ids, executor=executor, role="scorer")


def verify_runtime_image(image, task_ids, *, executor=bench.execute_container, role="scorer"):
    """Fail before agent turns if an R task's pinned packages are absent from the image."""
    required = {}
    for task_id in task_ids:
        if task_id not in PILOT_TASK_IDS:
            continue
        required.update(task_for(task_id).get("required_packages", {}))
    if not required:
        return {"status": "not_required", "packages": {}}
    required["BiocVersion"] = "3.22.0"
    package_names = sorted(required)
    r_vector = ",".join(json.dumps(name) for name in package_names)
    r_code = (
        "cat('BENCH_R=', as.character(getRversion()), '\\n', sep=''); "
        f"for (p in c({r_vector})) {{ v <- if (requireNamespace(p, quietly=TRUE)) "
        "as.character(utils::packageVersion(p)) else 'MISSING'; "
        "cat('BENCH_PACKAGE=', p, '=', v, '\\n', sep='') }"
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        "codex-r-score-" + uuid.uuid4().hex,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=32m,mode=1777",
        "--entrypoint",
        "Rscript",
        image,
        "--vanilla",
        "-e",
        r_code,
    ]
    result = executor(command, timeout=30)
    if result.returncode != 0:
        raise ValueError(f"{role}_image_probe_failed")
    output = result.stdout.decode("utf-8", errors="replace")
    runtime = re.search(r"(?m)^BENCH_R=(.+)$", output)
    observed = dict(re.findall(r"(?m)^BENCH_PACKAGE=([A-Za-z][A-Za-z0-9.]*)=(.+)$", output))
    if runtime is None or runtime.group(1) != "4.5.2":
        raise ValueError(f"{role} image must provide R 4.5.2 for E02/E03")
    mismatched = {
        package: {"expected": version, "actual": observed.get(package, "MISSING")}
        for package, version in required.items()
        if observed.get(package) != version
    }
    if mismatched:
        details = ", ".join(
            f"{package} expected {versions['expected']} (found {versions['actual']})"
            for package, versions in sorted(mismatched.items())
        )
        raise ValueError(f"{role} image lacks E task package pins: {details}")
    return {"status": "verified", "r": runtime.group(1), "packages": required}


def provenance(task_id, scorer_version="legacy"):
    """Return pinned environment/source and public input hashes for result files."""
    task = task_for(task_id)
    metadata = bench.read_json(bench.safe_file(PILOT, task["metadata"]))
    metadata["public_spec_sha256"] = bench.digest(bench.safe_file(PILOT, task["spec"]))
    metadata["public_inputs"] = {
        item["target"]: bench.digest(bench.safe_file(PILOT, item["source"]))
        for item in task["public_files"]
    }
    if metadata.get("snapshot"):
        snapshot = bench.safe_file(PILOT, metadata["snapshot"])
        metadata["source_snapshot_sha256"] = bench.digest(snapshot)
        checksum_manifest = bench.safe_file(PILOT, "metadata/E-source-snapshot.sha256")
        metadata["source_checksum_manifest_sha256"] = bench.digest(checksum_manifest)
    versioned_task = (
        scorer_version == "knowledge-pilot-v2"
        and task_id in {"D01", "D02", "D03", "E01", "E04", "E05"}
    ) or (scorer_version == "knowledge-pilot-v2.1" and task_id in {"D01", "D03"})
    if versioned_task:
        from benchmarks.codex_r import knowledge_pilot_v2 as v2

        metadata["scorer_version"] = scorer_version
        metadata["output_contract_sha256"] = bench.digest(v2.contract_path(task_id))
        if scorer_version == "knowledge-pilot-v2.1":
            from benchmarks.codex_r import knowledge_pilot_v21

            metadata["claim_evidence_sha256"] = knowledge_pilot_v21.evidence_digest()
    return metadata


def prepare(task_id, destination, scorer_version="legacy"):
    """Export only task text, pinned lock and explicit public inputs/starter."""
    task = task_for(task_id)
    if scorer_version == "knowledge-pilot-v2.1" and task_id not in {"D01", "D03"}:
        raise ValueError("knowledge-pilot-v2.1 supports D01 and D03 only")
    destination = Path(destination).absolute()
    if bench.inside(destination, bench.REPO):
        raise ValueError("Candidate workspace must be outside the repository")
    if destination.exists() or any(parent.is_symlink() for parent in destination.parents):
        raise ValueError("Use a new workspace without symlink parents")
    destination.mkdir(parents=True)
    task_text = bench.safe_file(PILOT, task["spec"]).read_text(encoding="utf-8")
    versioned_task = (
        scorer_version == "knowledge-pilot-v2"
        and task_id in {"D01", "D02", "D03", "E01", "E04", "E05"}
    ) or (scorer_version == "knowledge-pilot-v2.1" and task_id in {"D01", "D03"})
    if versioned_task:
        from benchmarks.codex_r import knowledge_pilot_v2

        (destination / "OUTPUT_SCHEMA.json").write_bytes(
            knowledge_pilot_v2.contract_path(task_id).read_bytes()
        )
        task_text += (
            f"\n\nOutput contract ({scorer_version}): follow the public JSON Schema "
            "in OUTPUT_SCHEMA.json and save the result as answer.json. Equivalent forms "
            "listed by the schema are accepted. Cite official sources in the requested "
            "sources field. An alternative package or claim outside the local frozen "
            "evidence may remain unsupported for automatic scoring.\n"
        )
    elif scorer_version not in {"legacy", "knowledge-pilot-v2", "knowledge-pilot-v2.1"}:
        raise ValueError("Unsupported knowledge pilot scorer version")
    (destination / "TASK.md").write_text(task_text, encoding="utf-8")
    (destination / "renv.lock").write_bytes(
        bench.safe_file(bench.ROOT, "configs/renv.lock").read_bytes()
    )
    if task.get("starter"):
        (destination / "solution.R").write_bytes(
            bench.safe_file(PILOT, task["starter"]).read_bytes()
        )
    for item in task["public_files"]:
        target = destination / item["target"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bench.safe_file(PILOT, item["source"]).read_bytes())
    exported_files = {
        "TASK.md": bench.digest(destination / "TASK.md"),
        **{
            item["target"]: bench.digest(destination / item["target"])
            for item in task["public_files"]
        },
    }
    if (destination / "OUTPUT_SCHEMA.json").is_file():
        exported_files["OUTPUT_SCHEMA.json"] = bench.digest(destination / "OUTPUT_SCHEMA.json")
    return {
        "task": task_id,
        "scorer_version": scorer_version,
        "files": exported_files,
    }


def seal_artifacts(task_id, source, destination):
    """Copy only declared regular UTF-8 artifacts into the sealed scorer directory."""
    task = task_for(task_id)
    source, destination = Path(source).absolute(), Path(destination)
    if any(parent.is_symlink() for parent in (source, *source.parents)):
        raise ValueError("Symlink artifact roots are not allowed")
    source = source.resolve()
    if not source.is_dir() or destination.exists():
        raise ValueError("Invalid artifact source/destination")
    files = {}
    total = 0
    for name in task["artifacts"]:
        content = bench.safe_file(source, name).read_bytes()
        total += len(content)
        if total > MAX_ANSWER_BYTES:
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
    if any(parent.is_symlink() for parent in (original, *original.parents)):
        raise ValueError("Symlink workspaces are not allowed")
    workspace = original.resolve()
    if bench.inside(workspace, bench.REPO) or not workspace.is_dir():
        raise ValueError("Use a separate candidate directory")
    mounts = [
        (workspace, "/candidate"),
        (PILOT / "verifier", "/verifier"),
        (bench.ROOT / "hard" / "verifier" / "harness.R", "/harness.R"),
        (bench.ROOT / "configs" / "renv.lock", "/config/renv.lock"),
    ]
    if any(c in str(path) for path, _ in mounts for c in (",", "\n", "\r")):
        raise ValueError("Path cannot be safely represented in a Docker mount")
    harness = bench.ROOT / "hard" / "verifier" / "harness.R"
    lockfile = bench.ROOT / "configs" / "renv.lock"
    return [
        "docker",
        "run",
        "--rm",
        "--pull=never",
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
        "2",
        "--memory",
        "2048m",
        "--memory-swap",
        "2048m",
        "--pids-limit",
        "256",
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m,mode=1777",
        "--tmpfs",
        "/work:rw,nosuid,size=256m,mode=1777",
        "--env",
        "TZ=UTC",
        "--env",
        "LC_ALL=C.UTF-8",
        "--mount",
        f"type=bind,source={workspace},target=/candidate,readonly",
        "--mount",
        f"type=bind,source={PILOT / 'verifier'},target=/verifier,readonly",
        "--mount",
        f"type=bind,source={harness},target=/harness.R,readonly",
        "--mount",
        f"type=bind,source={lockfile},target=/config/renv.lock,readonly",
        "--workdir",
        "/work",
        image,
        "timeout",
        "--kill-after=5",
        str(task["score_seconds"]),
        "Rscript",
        "--vanilla",
        "/verifier/run.R",
        task_id,
        "/candidate",
    ]


def _failure(status, task, hashes, reason):
    item = task_for(task)
    checks = item["checks"]
    return {
        "status": status,
        "passed": None if status == "scoring_error" else 0,
        "total": checks,
        "fully_correct": None if status == "scoring_error" else False,
        "reason": reason,
        "failed_checks": None,
        "details": [],
        "environment": None,
        "artifacts": hashes,
    }


def _copy_public_inputs(task, destination):
    for item in task["public_files"]:
        target = Path(item["target"])
        if target.is_absolute() or ".." in target.parts:
            raise ValueError("Public input target escapes the scorer workspace")
        source = bench.safe_file(PILOT, item["source"])
        path = destination / target
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError("Public input target escapes the scorer workspace")
        path.write_bytes(source.read_bytes())


def score(
    task_id,
    artifacts,
    image,
    *,
    executor=bench.execute_container,
    scorer_version="legacy",
):
    task = task_for(task_id)
    if (
        scorer_version == "knowledge-pilot-v2"
        and task["block"] in {"D", "E"}
        and task.get("scorer", "json") == "json"
    ):
        from benchmarks.codex_r import knowledge_pilot_v2

        return knowledge_pilot_v2.score(task_id, artifacts)
    if scorer_version == "knowledge-pilot-v2.1":
        if task_id not in {"D01", "D03"}:
            raise ValueError("knowledge-pilot-v2.1 supports D01 and D03 only")
        from benchmarks.codex_r import knowledge_pilot_v21

        return knowledge_pilot_v21.score(task_id, artifacts)
    if scorer_version not in {"legacy", "knowledge-pilot-v2"}:
        raise ValueError("Unsupported knowledge pilot scorer version")
    if task["block"] == "D":
        return _score_recommendation(task, artifacts)
    if task["block"] == "E" and task.get("scorer") == "json":
        return _score_compatibility(task, artifacts)
    with tempfile.TemporaryDirectory(prefix="rkmcp-tool-value-score-") as temp:
        sealed = Path(temp) / "sealed"
        hashes = seal_artifacts(task_id, artifacts, sealed)
        _copy_public_inputs(task, sealed)
        try:
            result = executor(
                docker_command(image, sealed, task_id), timeout=task["score_seconds"] + 15
            )
        except subprocess.TimeoutExpired:
            return _failure("candidate_timeout", task_id, hashes, "scorer_deadline")
        except bench.OutputLimitExceeded:
            return _failure("candidate_error", task_id, hashes, "output_limit")
        if result.returncode == 124:
            return _failure("candidate_timeout", task_id, hashes, "scorer_deadline")
        if result.returncode != 0:
            infrastructure = result.returncode in {125, 126, 127}
            return _failure(
                "scoring_error" if infrastructure else "candidate_error",
                task_id,
                hashes,
                f"exit_{result.returncode}",
            )
        try:
            stdout = result.stdout.decode("utf-8")
            records = [
                json.loads(line.removeprefix("BENCH_RESULT="))
                for line in stdout.splitlines()
                if line.startswith("BENCH_RESULT=")
            ]
        except (UnicodeError, json.JSONDecodeError):
            return _failure("candidate_error", task_id, hashes, "unparseable_result")
        if len(records) != 1:
            return _failure("candidate_error", task_id, hashes, "ambiguous_result")
        record = records[0]
        if record.get("status") == "scoring_error":
            return _failure("scoring_error", task_id, hashes, record.get("reason"))
        passed, total = record.get("passed"), record.get("total")
        if (
            record.get("status") not in {"scored", "candidate_error"}
            or total != task["checks"]
            or type(passed) is not int
            or not 0 <= passed <= total
        ):
            return _failure("candidate_error", task_id, hashes, "invalid_result_shape")
        return {
            "status": record["status"],
            "passed": passed,
            "total": total,
            "fully_correct": record["status"] == "scored" and passed == total,
            "reason": record.get("reason"),
            "failed_checks": [record["failed_checks"]]
            if isinstance(record.get("failed_checks"), str)
            else record.get("failed_checks") or [],
            "details": record.get("details") or [],
            "environment": record.get("environment"),
            "artifacts": hashes,
        }


def _is_frozen_url(url, frozen, kind):
    return isinstance(url, str) and url in _resource_urls(frozen, kind)


def _score_recommendation(task, artifacts):
    hashes = {}
    try:
        source = bench.safe_file(Path(artifacts), "answer.json")
        if source.stat().st_size > MAX_ANSWER_BYTES:
            return _failure("candidate_error", task["id"], hashes, "answer_too_large")
        hashes["answer.json"] = bench.digest(source)
        answer = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return _failure("candidate_error", task["id"], hashes, "invalid_json_answer")
    candidates = bench.read_json(bench.safe_file(PILOT / "verifier", "candidates.json"))[task["id"]]
    recommendations = answer.get("recommendations") if isinstance(answer, dict) else None
    recommendation = (
        recommendations[0]
        if isinstance(recommendations, list)
        and len(recommendations) == 1
        and isinstance(recommendations[0], dict)
        else {}
    )
    package = recommendation.get("package")
    package = package if isinstance(package, str) else None
    expected = candidates.get(package, {})
    frozen = official_resources().get(task["id"], {}).get(package)
    feature_ids = recommendation.get("feature_ids", [])
    caveat_ids = recommendation.get("caveat_ids", [])
    feature_ids_valid = isinstance(feature_ids, list) and all(
        isinstance(item, str) for item in feature_ids
    )
    caveat_ids_valid = isinstance(caveat_ids, list) and all(
        isinstance(item, str) for item in caveat_ids
    )
    rationale = answer.get("rationale") if isinstance(answer, dict) else None
    checks = {
        "answer_shape": isinstance(answer, dict)
        and answer.get("r_version") == manifest()["environment"]["r"]
        and isinstance(recommendations, list)
        and len(recommendations) == 1
        and bool(recommendation)
        and isinstance(rationale, str)
        and len(rationale.strip()) >= 40,
        "accepted_package_and_version": bool(expected)
        and recommendation.get("version") == expected.get("version"),
        # The frozen resources belong to one pinned version, so a URL is only accepted for the
        # package and version the answer states; any other CRAN-hosted URL is rejected.
        "official_source_and_docs": bool(expected)
        and frozen is not None
        and frozen.get("resource_version") == expected.get("version")
        and recommendation.get("version") == frozen["resource_version"]
        and _is_frozen_url(recommendation.get("source_url"), frozen, "source")
        and _is_frozen_url(recommendation.get("documentation_url"), frozen, "documentation"),
        "documented_fit_and_limits": bool(expected)
        and feature_ids_valid
        and set(expected.get("required_features", [])) <= set(feature_ids)
        and caveat_ids_valid
        and set(expected.get("required_caveats", [])) <= set(caveat_ids),
    }
    passed = sum(checks.values())
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "status": "scored",
        "scorer_version": D_SCORER_VERSION,
        "passed": passed,
        "total": task["checks"],
        "fully_correct": passed == task["checks"],
        "reason": None,
        "failed_checks": failed,
        "details": [f"{name}: {'pass' if ok else 'fail'}" for name, ok in checks.items()],
        "environment": {"r": manifest()["environment"]["r"], "packages": {}},
        "artifacts": hashes,
    }


def _score_compatibility(task, artifacts):
    """Score E01/E04/E05 compatibility claims against frozen official facts."""
    hashes = {}
    try:
        source = bench.safe_file(Path(artifacts), "answer.json")
        if source.stat().st_size > MAX_ANSWER_BYTES:
            return _failure("candidate_error", task["id"], hashes, "answer_too_large")
        hashes["answer.json"] = bench.digest(source)
        answer = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return _failure("candidate_error", task["id"], hashes, "invalid_json_answer")
    checks = _compatibility_checks(task["id"], answer)
    passed = sum(checks.values())
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "status": "scored",
        "scorer_version": E_SCORER_VERSION,
        "passed": passed,
        "total": task["checks"],
        "fully_correct": passed == task["checks"],
        "reason": None,
        "failed_checks": failed,
        "details": [f"{name}: {'pass' if ok else 'fail'}" for name, ok in checks.items()],
        "environment": {"r": manifest()["environment"]["r"], "packages": {}},
        "artifacts": hashes,
    }


def _compatibility_checks(task_id, answer):
    if not isinstance(answer, dict):
        answer = {}
    rationale = answer.get("rationale")
    sources = answer.get("sources")
    valid_rationale = isinstance(rationale, str) and len(rationale.strip()) >= 30
    valid_sources = isinstance(sources, list) and all(
        isinstance(url, str) and url.startswith("https://bioconductor.org/") for url in sources
    )
    if task_id == "E01":
        packages = answer.get("packages")
        packages = packages if isinstance(packages, dict) else {}
        edges = answer.get("dependency_edges")
        edge_ok = isinstance(edges, list) and all(
            isinstance(edge, dict)
            and isinstance(edge.get("package"), str)
            and isinstance(edge.get("depends_on"), str)
            and isinstance(edge.get("minimum_version"), str)
            and _version_at_least(
                _node_version(packages, edge["depends_on"]), edge["minimum_version"]
            )
            for edge in edges
        )
        return {
            "release_and_R_conflict_identified": answer.get("classification") == "incompatible",
            "valid_minimal_release_alignment": answer.get("r_version") == "4.5.2"
            and answer.get("bioconductor") == "3.22",
            "package_sources_and_pins": packages.get("DESeq2")
            == {"version": "1.50.2", "repository": "Bioconductor 3.22"}
            and packages.get("ggplot2") == {"version": "4.0.3", "repository": "CRAN"}
            and packages.get("SummarizedExperiment")
            == {"version": "1.40.0", "repository": "Bioconductor 3.22"},
            "dependency_graph_constraints_satisfied": edge_ok
            and any(
                edge.get("package") == "DESeq2"
                and edge.get("depends_on") == "SummarizedExperiment"
                and edge.get("minimum_version") == "1.1.6"
                for edge in edges
            )
            and any(
                edge.get("package") == "DESeq2"
                and edge.get("depends_on") == "ggplot2"
                and edge.get("minimum_version") == "3.4.0"
                for edge in edges
            ),
            "minimal_change_explained": answer.get("changed_fields") == ["r_version"]
            and valid_rationale,
            "official_evidence": valid_sources and any("3.22" in url for url in sources),
        }
    if task_id == "E04":
        packages = answer.get("packages")
        packages = packages if isinstance(packages, dict) else {}
        strategy = answer.get("install_strategy")
        versions = answer.get("versions")
        versions = versions if isinstance(versions, dict) else {}
        edges = answer.get("dependency_edges")
        return {
            "package_sources": packages.get("DESeq2") == "Bioconductor"
            and packages.get("ggplot2") == "CRAN"
            and packages.get("BiocGenerics") == "Bioconductor",
            "version_constraints": answer.get("r_version") == "4.5.2"
            and answer.get("bioconductor") == "3.22"
            and versions
            == {
                "DESeq2": "1.50.2",
                "SummarizedExperiment": "1.40.0",
                "BiocGenerics": "0.56.0",
                "ggplot2": "4.0.3",
            },
            "dependency_edge_reported": isinstance(edges, list)
            and any(
                isinstance(edge, dict)
                and edge.get("package") == "DESeq2"
                and edge.get("depends_on") == "SummarizedExperiment"
                for edge in edges
            ),
            "repository_aware_install": isinstance(strategy, list)
            and any(isinstance(item, str) and "BiocManager::install" in item for item in strategy)
            and any(isinstance(item, str) and "install.packages" in item for item in strategy),
            "evidence_and_reasoning": valid_rationale and valid_sources,
        }
    if task_id == "E05":
        cases = answer.get("cases")
        cases = cases if isinstance(cases, dict) else {}
        return {
            "verified_positive": cases.get("release_322_r452") == "compatible"
            and answer.get("positive_package") == {"name": "DESeq2", "version": "1.50.2"},
            "verified_negative": cases.get("release_322_r443") == "incompatible",
            "unknown_not_overclaimed": cases.get("unlisted_package_version") == "unverified",
            "reasoning_distinguishes_evidence": valid_rationale,
            "official_evidence": valid_sources and any("3.22" in url for url in sources),
        }
    return {"known_task": False}


def _version_at_least(actual, minimum):
    if not isinstance(actual, str) or not isinstance(minimum, str):
        return False
    try:
        left = tuple(int(part) for part in actual.split("."))
        right = tuple(int(part) for part in minimum.split("."))
    except ValueError:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) >= right + (0,) * (width - len(right))


def _node_version(packages, package):
    node = packages.get(package)
    return node.get("version") if isinstance(node, dict) else None


def _answer_summary(artifacts):
    """Package, version and URLs of the single recommendation, for the report only."""
    try:
        answer = json.loads(bench.safe_file(artifacts, "answer.json").read_text(encoding="utf-8"))
        item = answer["recommendations"][0]
        return {
            key: item.get(key) for key in ("package", "version", "source_url", "documentation_url")
        }
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def rescore_run(run_dir, output_dir=None):
    """Re-score the saved D answers of a finished run offline; never touches the run files.

    Writes ``<run>-<scorer_version>-rescore.{json,md}`` and returns the report. No network
    or Docker is used: D scoring reads only the answer, candidates.json and the frozen
    official_resources.json.
    """
    run = Path(run_dir).resolve()
    destination = Path(output_dir) if output_dir else PILOT.parent / "reports"
    if bench.inside(destination.resolve(), run):
        raise ValueError("Write the rescore report outside the original run directory")
    trials = []
    for result_path in sorted(run.glob("*/result.json")):
        original = json.loads(result_path.read_text(encoding="utf-8"))
        task = task_for(original["task"]) if original.get("task") else None
        if task is None or task["block"] != "D":
            continue
        artifacts = result_path.parent / "artifacts"
        recorded_hash = (original.get("score") or {}).get("artifacts", {}).get("answer.json")
        current_hash = bench.digest(bench.safe_file(artifacts, "answer.json"))
        rescored = _score_recommendation(task, artifacts)
        original_score = original.get("score") or {}
        trials.append(
            {
                "trial_id": original.get("trial_id"),
                "task": task["id"],
                "mode": original.get("mode"),
                "answer": _answer_summary(artifacts),
                "answer_sha256": current_hash,
                "answer_matches_original_record": current_hash == recorded_hash,
                "original": {
                    "passed": original_score.get("passed"),
                    "total": original_score.get("total"),
                    "failed_checks": original_score.get("failed_checks"),
                    "details": original_score.get("details"),
                },
                "rescored": {
                    "passed": rescored["passed"],
                    "total": rescored["total"],
                    "failed_checks": rescored["failed_checks"],
                    "details": rescored["details"],
                },
            }
        )
    report = {
        "report_type": "d-rescore",
        "scorer_version": D_SCORER_VERSION,
        "source_run": run.name,
        "source_files_modified": False,
        "network_used": False,
        "docker_used": False,
        "original_scorer": (
            "not recorded in the run files; compared source_url and documentation_url "
            "with one curated string per package (exact equality)"
        ),
        "candidates_sha256": bench.digest(PILOT / "verifier" / "candidates.json"),
        "official_resources_sha256": bench.digest(PILOT / "verifier" / "official_resources.json"),
        "official_resources_verified_at_utc": bench.read_json(
            PILOT / "verifier" / "official_resources.json"
        )["verified_at_utc"],
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trials": trials,
    }
    destination.mkdir(parents=True, exist_ok=True)
    stem = f"{run.name}-{D_SCORER_VERSION}-rescore"
    (destination / f"{stem}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (destination / f"{stem}.md").write_text(_rescore_markdown(report), encoding="utf-8")
    return report


def _rescore_markdown(report):
    lines = [
        f"# D rescore: {report['source_run']}",
        "",
        f"- Scorer: `{report['scorer_version']}` (offline; no network, no Docker, no API calls)",
        f"- Original scorer: {report['original_scorer']}",
        f"- Official resource allowlist verified at {report['official_resources_verified_at_utc']}"
        f" (sha256 `{report['official_resources_sha256'][:16]}`)",
        f"- Generated at {report['generated_at_utc']}; original run files were not modified.",
        "",
        "| Trial | Package | Version | Original | Rescored | Still failing |",
        "|---|---|---|---|---|---|",
    ]
    for trial in report["trials"]:
        answer = trial["answer"] or {}
        original, rescored = trial["original"], trial["rescored"]
        lines.append(
            f"| {trial['trial_id']} | {answer.get('package')} | {answer.get('version')} "
            f"| {original['passed']}/{original['total']} "
            f"| {rescored['passed']}/{rescored['total']} "
            f"| {', '.join(rescored['failed_checks']) or '-'} |"
        )
    mismatched = [
        t["trial_id"] for t in report["trials"] if not t["answer_matches_original_record"]
    ]
    if mismatched:
        lines += [
            "",
            f"WARNING: answer.json differs from the recorded hash: {', '.join(mismatched)}",
        ]
    return "\n".join(lines) + "\n"


def selftest(image, *, executor=bench.execute_container, task_ids=None):
    """Score private references and negative controls without Agents API use."""
    tasks = manifest()["tasks"]
    if task_ids is not None:
        requested = set(task_ids)
        if not requested or not requested <= set(PILOT_TASK_IDS):
            raise ValueError("Selftest task ids must be a non-empty subset of the pilot")
        tasks = [task for task in tasks if task["id"] in requested]
    report = {}
    for task in tasks:
        task_id = task["id"]
        controls = PILOT / "verifier" / "controls" / task_id
        if (
            controls.is_symlink()
            or not controls.is_dir()
            or not controls.resolve().is_relative_to((PILOT / "verifier" / "controls").resolve())
        ):
            raise ValueError(f"{task_id}: invalid private controls directory")
        if task["block"] == "D" or (task["block"] == "E" and task.get("scorer") == "json"):
            controls_to_check = task.get("negative_controls", ["wrong.json"])
            cases = {"reference": bench.safe_file(controls, "reference.json")}
            cases.update(
                {
                    control.removesuffix(".json"): bench.safe_file(controls, control)
                    for control in controls_to_check
                }
            )
        else:
            cases = {"reference": bench.safe_file(controls, "reference.R")}
            cases.update(
                {
                    control.removesuffix(".R"): bench.safe_file(controls, control)
                    for control in task.get("negative_controls", ["wrong.R"])
                }
            )
        report[task_id] = {}
        for label, control in cases.items():
            with tempfile.TemporaryDirectory(prefix="rkmcp-selftest-") as temp:
                workspace = Path(temp) / "candidate"
                workspace.mkdir()
                artifact_name = task["artifacts"][0]
                (workspace / artifact_name).write_bytes(control.read_bytes())
                result = score(task_id, workspace, image, executor=executor)
            if (
                label == "reference"
                and result.get("status") == "scoring_error"
                and result.get("reason") == "environment_mismatch"
            ):
                report[task_id] = {
                    "environment": "unavailable",
                    "reason": "required package versions are absent from scorer image",
                }
                break
            correct = result.get("fully_correct") is True
            if correct != (label == "reference"):
                raise AssertionError(
                    f"{task_id} {label} control scored unexpectedly: "
                    f"{result.get('status')} {result.get('passed')}/{result.get('total')} "
                    f"reason={result.get('reason')} failed={result.get('failed_checks')}"
                )
            report[task_id][label] = {
                "passed": result.get("passed"),
                "total": result.get("total"),
                "fully_correct": correct,
                "failed_checks": result.get("failed_checks"),
            }
    return report


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Offline D-block utilities")
    commands = parser.add_subparsers(dest="command", required=True)
    rescore = commands.add_parser("rescore", help="Re-score saved D answers of a finished run")
    rescore.add_argument("run_dir")
    rescore.add_argument("--output-dir")
    args = parser.parse_args(argv)
    report = rescore_run(args.run_dir, args.output_dir)
    print(_rescore_markdown(report))


if __name__ == "__main__":
    main()
