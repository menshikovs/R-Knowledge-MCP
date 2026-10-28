"""Regression tests for the E02 input repair and the separate Bioconductor executor."""

import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.codex_r import full_selftest, line_endings
from benchmarks.codex_r import knowledge_pilot as pilot
from benchmarks.codex_r import run_simple as simple
from benchmarks.codex_r.telemetry import schema


def test_e02_fixture_is_nonnegative_integer_nb_input_with_provenance():
    metadata = pilot.provenance("E02")["fixture_provenance"]
    path = pilot.PILOT / "fixtures/E02-counts.csv"
    rows = list(csv.reader(path.read_text().splitlines()))
    assert rows[0] == ["gene", "ctrl_1", "ctrl_2", "ctrl_3", "treat_1", "treat_2", "treat_3"]
    assert len(rows) == 501 and len({row[0] for row in rows[1:]}) == 500
    assert all(len(row) == 7 and all(int(value) >= 0 for value in row[1:]) for row in rows[1:])
    assert metadata["seed"] == 20261025
    # Pins hold for the canonical (LF) and the legacy (CRLF) form of the same content (CI-004).
    assert line_endings.pin_matches(path, metadata["counts_sha256"])
    assert line_endings.pin_matches(
        pilot.PILOT / metadata["generator"], metadata["generator_sha256"]
    )
    # The trusted reference has not been changed to work around dispersion estimation.
    reference = pilot.PILOT / "verifier/controls/E02/reference.R"
    assert line_endings.pin_matches(
        reference, "a4da84f1cc568105444085a7898b251aa7ebc4a2d78394e837736e1ad5a511ce"
    )
    for line in (pilot.PILOT / "metadata/E-source-snapshot.sha256").read_text().splitlines():
        sha, relative = line.split("  ", 1)
        assert line_endings.pin_matches(pilot.PILOT / relative, sha)


@pytest.mark.parametrize("failed", ["one_failed_check", ["one_failed_check"], [], None])
def test_failed_checks_roundtrip_in_json_and_csv(tmp_path, failed):
    record = {
        "run_id": "r",
        "trial_id": "E02-B-1",
        "score": {"passed": 4, "total": 5, "failed_checks": failed},
    }
    simple.save_results(tmp_path, [record])
    expected = [failed] if isinstance(failed, str) else failed
    stored = json.loads((tmp_path / "results.json").read_text())[0]
    assert stored["score"]["failed_checks"] == expected
    with (tmp_path / "results.csv").open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert json.loads(row["score"])["failed_checks"] == expected
    assert (json.loads(row["failed_checks"]) if row["failed_checks"] else None) == expected


def test_diagnostic_trial_ids_and_full_pilot_are_resumable():
    plan = simple.planned_trials(["E02"], ["without-mcp", "with-mcp"], 1, "diagnostic")
    assert [row[3] for row in plan] == ["E02-A-1-diagnostic", "E02-B-1-diagnostic"]
    tasks = simple.expand_tasks(None, "full")
    assert tasks == [*simple.hard.task_ids(), *pilot.task_ids()]
    assert (
        len(tasks) == 19 and len(simple.planned_trials(tasks, ["without-mcp", "with-mcp"], 1)) == 38
    )


def test_manifest_registry_uses_bound_source_and_strips_keys(monkeypatch):
    for name in (*simple.KEY_NAMES, "CODEX_API_KEY"):
        monkeypatch.setenv(name, "local-test-secret")
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, '["get_function_docs"]', "")

    monkeypatch.setattr(simple.subprocess, "run", run)
    assert simple.registered_tools("consolidated") == ["get_function_docs"]
    assert seen["env"]["PYTHONPATH"] == str(simple.bench.REPO / "src")
    assert not set((*simple.KEY_NAMES, "CODEX_API_KEY")) & set(seen["env"])


@pytest.mark.parametrize("task_id", list(simple.FULL_VERIFIED_TASKS))
def test_agent_workspace_exports_only_declared_public_files(tmp_path, task_id):
    suite = simple.suite_for(task_id)[0]
    task = suite.task_for(task_id)
    workspace = tmp_path / task_id
    suite.prepare(task_id, workspace)
    expected = {"TASK.md", "renv.lock"}
    if suite is pilot:
        expected |= {item["target"] for item in task["public_files"]}
        if task.get("starter"):
            expected.add("solution.R")
            assert (workspace / "solution.R").read_bytes() != (
                pilot.PILOT / "verifier/controls" / task_id / "reference.R"
            ).read_bytes()
    else:
        expected |= {"data/" + Path(name).name for name in task["fixtures"]}
    actual = {
        path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file()
    }
    assert actual == expected


def stub_main_environment(monkeypatch):
    """Replace every image, Docker and session dependency of ``simple.main``; no money is spent."""
    monkeypatch.setattr(simple.sys, "platform", "linux")
    for name in simple.KEY_NAMES:
        monkeypatch.setenv(name, "local-fixture-key")
    monkeypatch.setattr(simple.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(
        simple,
        "registered_tools",
        lambda _: list(simple.hard.manifest()["mcp"]["tools"]),
    )
    monkeypatch.setattr(
        simple.telemetry_experiment, "git_state", lambda _: {"revision": "0" * 40, "dirty": False}
    )
    tags = []

    def image_id(tag):
        tags.append(tag)
        return "sha256:" + hashlib.sha256(tag.encode()).hexdigest()

    monkeypatch.setattr(simple, "image_id", image_id)
    monkeypatch.setattr(pilot, "verify_scorer_image", lambda *args: {"status": "verified"})
    monkeypatch.setattr(
        pilot, "verify_runtime_image", lambda *args, **kwargs: {"status": "verified"}
    )
    return tags, image_id


@pytest.mark.parametrize("first_error", [False, True])
def test_full_main_saves_valid_telemetry_and_resume_skips_finished_trials(
    tmp_path, monkeypatch, first_error
):
    tags, image_id = stub_main_environment(monkeypatch)
    calls = []

    def trial(
        args,
        task,
        mode,
        repetition,
        output,
        keys,
        images,
        *,
        condition=None,
        execution_order=None,
        planned_trial_id=None,
    ):
        calls.append((task, mode))
        trial_id = f"{task}-{'B' if mode == 'with-mcp' else 'A'}-{repetition}"
        # Standard plans carry no B1 condition or execution order.
        assert condition is None and execution_order is None
        assert planned_trial_id == trial_id
        failed = first_error and len(calls) == 1
        record = {
            "run_id": args.run_id,
            "trial_id": trial_id,
            "trial": trial_id,
            "task": task,
            "mode": mode,
            "repetition": repetition,
            "status": "error" if failed else "scored",
            "cleanup_completed": True,
            "score": None if failed else {"passed": 5, "total": 5, "failed_checks": []},
        }
        directory = output / trial_id
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps(record), encoding="utf-8")
        return record

    monkeypatch.setattr(simple, "run_trial", trial)
    assert simple.main(
        ["--effort", "medium", "--pilot", "full", "--results", str(tmp_path)]
    ) == int(first_error)
    assert len(calls) == 38 and full_selftest.EXECUTOR in tags and full_selftest.SCORER in tags
    output = next(path for path in tmp_path.iterdir() if path.is_dir())
    manifest = json.loads((output / "experiment.json").read_text())
    assert manifest["trial_count"] == 38 and manifest["images"]["executor"] == image_id(
        full_selftest.EXECUTOR
    )
    assert "E02" in manifest["task_inputs_sha256"]
    assert simple.main(["--effort", "medium", "--resume", str(output)]) == int(first_error)
    assert len(calls) == 38
    assert len(json.loads((output / "results.json").read_text())) == 38
    events = [json.loads(line) for line in (output / "telemetry.jsonl").read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "benchmark.run.started",
        "benchmark.run.completed",
    ] * 2
    assert all(schema.validate_event(event) == [] for event in events)


def test_b1_main_passes_control_and_treatment_to_every_trial(tmp_path, monkeypatch):
    stub_main_environment(monkeypatch)
    seen = []

    def trial(
        args,
        task,
        mode,
        repetition,
        output,
        keys,
        images,
        *,
        condition=None,
        execution_order=None,
        planned_trial_id=None,
    ):
        seen.append((task, mode, repetition, condition, execution_order, planned_trial_id))
        record = {
            "run_id": args.run_id,
            "trial_id": planned_trial_id,
            "trial": planned_trial_id,
            "task": task,
            "mode": mode,
            "repetition": repetition,
            "condition": condition,
            "execution_order": execution_order,
            "status": "scored",
            "cleanup_completed": True,
            "score": {"passed": 5, "total": 5, "failed_checks": []},
        }
        directory = output / planned_trial_id
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps(record), encoding="utf-8")
        return record

    monkeypatch.setattr(simple, "run_trial", trial)
    argv = [
        "--effort", "medium", "--experiment", "b1-discovery", "--tasks", "D03", "D01", "C01",
        "--repetitions", "2", "--knowledge-pilot-scorer", "knowledge-pilot-v2",
        "--results", str(tmp_path),
    ]  # fmt: skip
    assert simple.main(argv) == 0
    planned = simple.planned_b1_trials(list(simple.B1_DISCOVERY_TASKS), 2)
    assert seen == [
        (
            t["task"],
            "with-mcp",
            t["repetition"],
            t["condition"],
            t["execution_order"],
            t["trial_id"],
        )
        for t in planned
    ]
    assert {item[3] for item in seen} == {"control", "treatment"} and len(seen) == 12
    # Every task/repetition slot has exactly one Control and one Treatment, both with MCP.
    for task in simple.B1_DISCOVERY_TASKS:
        for repetition in (1, 2):
            slot = sorted(i[3] for i in seen if i[0] == task and i[2] == repetition)
            assert slot == ["control", "treatment"]
    assert all(item[1] == "with-mcp" for item in seen)
    output = next(path for path in tmp_path.iterdir() if path.is_dir())
    assert simple.main(["--effort", "medium", "--resume", str(output)]) == 0
    assert len(seen) == 12  # recorded trials are not repeated


@pytest.fixture(scope="module")
def images():
    if not shutil.which("docker"):
        pytest.skip("Docker CLI unavailable")
    result = {}
    for role, tag in (("scorer", full_selftest.SCORER), ("executor", full_selftest.EXECUTOR)):
        probe = subprocess.run(
            ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode:
            pytest.skip(f"Local {role} Bioconductor image unavailable")
        result[role] = probe.stdout.strip()
    return result


@pytest.mark.docker
def test_bioc_executor_contract_versions_and_library_boundary(images):
    report = full_selftest.executor_contract(images["executor"])
    assert report["codex_version"] == "codex-cli 0.163.0"
    for role, image in images.items():
        versions = pilot.verify_runtime_image(image, simple.FULL_VERIFIED_TASKS, role=role)
        assert versions["packages"]["BiocVersion"] == "3.22.0"
        assert versions["packages"]["DESeq2"] == "1.50.2"
        assert versions["packages"]["Biobase"] == "2.70.0"
        boundary = json.loads(
            full_selftest.networkless(
                image, "--vanilla", "-e", full_selftest.LIBRARY_PROBE, entrypoint="Rscript"
            )
        )
        assert boundary["hidden_paths_absent"] is True


def _unmountable_checkout_depth():
    """Docker Desktop (Windows) fails with "Input/output error" when bind-mounting a file whose host
    path has more than 16 components after the drive (measured: 16 mounts, 17 fails). The workflow
    mounts files from deep inside the checkout, so a deeply nested checkout cannot run it."""
    mounted = pilot.PILOT / "verifier/controls/E02/reference.R"
    return len(mounted.resolve().parts) - 1 if sys.platform == "win32" else 0


@pytest.mark.docker
@pytest.mark.skipif(
    _unmountable_checkout_depth() > 16,
    reason=(
        f"checkout path has {_unmountable_checkout_depth()} components after the drive; "
        "Docker Desktop cannot bind-mount files deeper than 16"
    ),
)
def test_e02_reproduction_and_standard_workflow_in_both_images(images):
    report = full_selftest.fixture_and_workflow(images["scorer"], images["executor"])
    assert report["two_generated_files_equal"] is True
    assert report["workflow"]["scorer"] == report["workflow"]["executor"]
    assert report["workflow"]["scorer"]["fit_type"] == "parametric"


@pytest.mark.docker
def test_e02_reference_and_mutants_on_bioc_scorer(images):
    result = pilot.selftest(images["scorer"], task_ids=["E02"])["E02"]
    assert result["reference"] == {
        "passed": 5,
        "total": 5,
        "fully_correct": True,
        "failed_checks": [],
    }
    assert result["wrong_counts"]["fully_correct"] is False
    assert result["wrong_design"]["failed_checks"] == ["reference_level_and_sign"]
