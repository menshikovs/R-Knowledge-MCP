"""Free offline H/B/C/D/E readiness checks; never creates OpenAI sessions.

Reuses the existing reference/mutant scorers. Docker tests run with network=none.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from benchmarks.codex_r import knowledge_pilot as pilot
from benchmarks.codex_r import run_simple as simple
from benchmarks.codex_r.hard import selftest as hard_test

SCORER = "codex-r-benchmark:pilot-bioc"
EXECUTOR = "rkmcp-codex-runtime:codex-0.163.0-bioc"
BASE = "rkmcp-codex-runtime:codex-0.163.0"


def docker(*args):
    return subprocess.check_output(["docker", *map(str, args)], text=True, timeout=120)


def networkless(image, *args, entrypoint=None, mounts=()):
    flags = [
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--cpus=2",
        "--memory=2048m",
        "--memory-swap=2048m",
        "--pids-limit=256",
        "--tmpfs",
        "/tmp:rw,nosuid,size=256m,mode=1777",
        "--env",
        "HOME=/tmp",
        "--env",
        "CODEX_HOME=/tmp",
    ]
    for source, target, readonly in mounts:
        flags += [
            "--mount",
            f"type=bind,src={Path(source).resolve()},dst={target}"
            + (",readonly" if readonly else ""),
        ]
    if entrypoint:
        flags += ["--entrypoint", entrypoint]
    return docker(*flags, image, *args)


def executor_contract(executor):
    base = json.loads(docker("image", "inspect", BASE))[0]
    derived = json.loads(docker("image", "inspect", executor))[0]
    fields = (
        "User",
        "Entrypoint",
        "Cmd",
        "WorkingDir",
        "Env",
        "Healthcheck",
        "Volumes",
        "StopSignal",
    )
    assert all(base["Config"].get(key) == derived["Config"].get(key) for key in fields)
    assert derived["RootFS"]["Layers"][: len(base["RootFS"]["Layers"])] == base["RootFS"]["Layers"]
    version = networkless(executor, "--version").strip()
    assert version == "codex-cli 0.163.0"
    help_text = networkless(executor, "exec-server", "--help")
    assert "--remote" in help_text and "--environment-id" in help_text
    binary = "/opt/codex/bin/codex"
    original_sha = networkless(base["Id"], binary, entrypoint="sha256sum").split()[0]
    derived_sha = networkless(executor, binary, entrypoint="sha256sum").split()[0]
    assert original_sha == derived_sha
    # No raw Config.Env is retained in a report.
    return {
        "base_image": base["Id"],
        "derived_image": derived["Id"],
        "base_layers_preserved": True,
        "configuration_fields_equal": list(fields),
        "user": derived["Config"]["User"],
        "entrypoint": derived["Config"]["Entrypoint"],
        "cmd": derived["Config"]["Cmd"],
        "codex_version": version,
        "codex_binary_sha256": derived_sha,
        "exec_server_environment_id_and_remote_flags": True,
    }


LIBRARY_PROBE = """
lock <- jsonlite::fromJSON("/config/renv.lock", simplifyVector=FALSE)
stopifnot(all(vapply(lock$Packages, function(p)
  packageVersion(p$Package) == package_version(p$Version), TRUE)))
lib <- "/opt/benchmark-library"
stopifnot(setequal(list.files(lib), rownames(installed.packages(lib.loc=lib))))
stopifnot(!any(file.exists(c("/verifier", "/oracle", "/harness.R", "/benchmarks",
  "/candidate/solution.R", "/candidate/answer.json"))))
cat(jsonlite::toJSON(list(locked_cran_packages=length(lock$Packages),
  installed_library_packages=length(list.files(lib)), hidden_paths_absent=TRUE), auto_unbox=TRUE))
"""


WORKFLOW_PROBE = """
source("/reference.R")
counts <- read.csv("/counts.csv", row.names=1, check.names=FALSE)
samples <- read.csv("/samples.csv", row.names=1)
x <- run_rnaseq(counts, samples)
stopifnot(nrow(x$dds)==500L, ncol(x$dds)==6L,
  attr(DESeq2::dispersionFunction(x$dds), "fitType")=="parametric",
  all(is.finite(DESeq2::dispersions(x$dds))),
  x$results$log2FoldChange[x$results$gene=="gene_1"]>0,
  x$results$log2FoldChange[x$results$gene=="gene_11"]<0)
cat(jsonlite::toJSON(list(fit_type=attr(DESeq2::dispersionFunction(x$dds), "fitType"),
  dispersion_range=range(DESeq2::dispersions(x$dds)), results=x$results),
  auto_unbox=TRUE, digits=16, na="null"))
"""


def fixture_and_workflow(scorer, executor):
    fixture = pilot.PILOT / "fixtures/E02-counts.csv"
    generator = pilot.PILOT / "generate_E02_fixture.R"
    sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="rkmcp-e02-reproduce-") as temp:
        # The image intentionally stays uid 65534; WSL temp dirs start as 0700.
        Path(temp).chmod(0o777)
        for index in (1, 2):
            networkless(
                scorer,
                "--vanilla",
                "/generator.R",
                f"/output/{index}.csv",
                entrypoint="Rscript",
                mounts=[(generator, "/generator.R", True), (temp, "/output", False)],
            )
            assert hashlib.sha256((Path(temp) / f"{index}.csv").read_bytes()).hexdigest() == sha
    mounts = [
        (pilot.PILOT / "verifier/controls/E02/reference.R", "/reference.R", True),
        (fixture, "/counts.csv", True),
        (pilot.PILOT / "fixtures/E02-samples.csv", "/samples.csv", True),
    ]
    results = {}
    for role, image in (("scorer", scorer), ("executor", executor)):
        outputs = [
            networkless(
                image, "--vanilla", "-e", WORKFLOW_PROBE, entrypoint="Rscript", mounts=mounts
            )
            for _ in range(2)
        ]
        assert outputs[0] == outputs[1]
        parsed = json.loads(outputs[0])
        results[role] = {
            "workflow_sha256": hashlib.sha256(outputs[0].encode()).hexdigest(),
            "fit_type": parsed["fit_type"],
            "dispersion_range": parsed["dispersion_range"],
            "genes": len(parsed["results"]),
            "repetitions_equal": True,
        }
    assert results["scorer"]["workflow_sha256"] == results["executor"]["workflow_sha256"]
    return {
        "counts_sha256": sha,
        "generator_sha256": hashlib.sha256(generator.read_bytes()).hexdigest(),
        "two_generated_files_equal": True,
        "workflow": results,
    }


def validate(report_dir, *, scorer_tag=SCORER, executor_tag=EXECUTOR):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    images = {
        "scorer": hard_test.image_id(scorer_tag),
        "executor": hard_test.image_id(executor_tag),
        "mcp": hard_test.image_id("cran-knowledge-mcp:shiny-quarto"),
    }
    tasks = list(simple.FULL_VERIFIED_TASKS)
    versions = {
        role: pilot.verify_runtime_image(images[role], tasks, role=role)
        for role in ("scorer", "executor")
    }
    report = {
        "kind": "offline_reference_mutant_validation_not_model_trials",
        "api_calls": 0,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "images": images,
        "runtime_versions": versions,
        "network": "none",
        "tasks": {},
    }

    def save():
        (report_dir / "validation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    report["executor_contract"] = executor_contract(images["executor"])
    report["library_boundaries"] = {
        role: json.loads(
            networkless(images[role], "--vanilla", "-e", LIBRARY_PROBE, entrypoint="Rscript")
        )
        for role in ("scorer", "executor")
    }
    report["E02_reproducibility"] = fixture_and_workflow(images["scorer"], images["executor"])
    save()
    for task_id in tasks:
        if task_id in pilot.PILOT_TASK_IDS:
            outcome = pilot.selftest(images["scorer"], task_ids=[task_id])[task_id]
            assert outcome.get("reference", {}).get("fully_correct") is True, task_id
        else:
            outcome = hard_test.validate_task(task_id, images["scorer"])
            assert not outcome["problems"], (task_id, outcome["problems"])
        report["tasks"][task_id] = outcome
        save()
        print(f"{task_id}: reference and mutants passed", flush=True)
    args = SimpleNamespace(
        run_id="offline-full-plan",
        effort="medium",
        instructions="standard",
        modes=["without-mcp", "with-mcp"],
        repetitions=1,
        timeout=900,
        executor_image=executor_tag,
        scorer_image=scorer_tag,
        mcp_image="cran-knowledge-mcp:shiny-quarto",
        runtime_versions=versions,
    )
    report.update(status="passed", ready_tasks=tasks, planned_model_trials=2 * len(tasks))
    save()
    simple.write_experiment_manifest(report_dir, args, images, tasks)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=simple.bench.ROOT / "reports/full-offline-readiness-20261025",
    )
    parser.add_argument("--scorer-image", default=SCORER)
    parser.add_argument("--executor-image", default=EXECUTOR)
    args = parser.parse_args(argv)
    report = validate(
        args.report_dir, scorer_tag=args.scorer_image, executor_tag=args.executor_image
    )
    print(
        f"Ready: {len(report['ready_tasks'])} tasks; "
        f"{report['planned_model_trials']} planned trials. API calls: 0"
    )


if __name__ == "__main__":
    main()
