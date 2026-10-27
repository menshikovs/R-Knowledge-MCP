"""Offline checks for the B/C/D/E pilot registry, scorers and telemetry exports."""

import csv
import json
import shutil
import subprocess

import pytest

from benchmarks.codex_r import knowledge_pilot as pilot
from benchmarks.codex_r import run_simple as simple
from benchmarks.codex_r.hard import suite as hard


def _score_json(task_id, answer, tmp_path):
    workspace = tmp_path / f"{task_id}-{len(list(tmp_path.iterdir()))}"
    workspace.mkdir()
    (workspace / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
    return pilot.score(task_id, workspace, "unused-for-json-scorer")


def test_manifest_pins_sixteen_tasks_and_public_inputs_do_not_include_oracles(tmp_path):
    manifest = pilot.manifest()
    assert pilot.task_ids() == list(pilot.PILOT_TASK_IDS)
    assert len(manifest["tasks"]) == 16
    assert {"C04", "C05"} <= set(pilot.task_ids())
    assert {"E01", "E02", "E03", "E04", "E05"} <= set(pilot.task_ids())
    assert simple.expand_tasks(None, "tool-value") == list(pilot.PILOT_TASK_IDS)
    assert simple.expand_tasks(["hard-pilot"]) == hard.task_ids()
    assert simple.expand_tasks(None) == ["R01"]

    pilot.prepare("B01", tmp_path / "public")
    exported = {
        path.relative_to(tmp_path / "public").as_posix()
        for path in (tmp_path / "public").rglob("*")
    }
    assert "TASK.md" in exported and "solution.R" in exported
    assert "data/ledger.csv" in exported
    assert not any("verifier" in path or "metadata" in path for path in exported)


@pytest.mark.parametrize("task_id", ["E01", "E04", "E05"])
def test_e_compatibility_references_and_negative_controls(task_id, tmp_path):
    controls = pilot.PILOT / "verifier" / "controls" / task_id
    reference = json.loads((controls / "reference.json").read_text(encoding="utf-8"))
    assert _score_json(task_id, reference, tmp_path)["fully_correct"] is True
    for wrong_name in pilot.task_for(task_id)["negative_controls"]:
        wrong = json.loads((controls / wrong_name).read_text(encoding="utf-8"))
        score = _score_json(task_id, wrong, tmp_path)
        assert score["status"] == "scored" and score["fully_correct"] is False


def test_e_release_conflict_inputs_provenance_and_hidden_outputs():
    snapshot = json.loads(
        (pilot.PILOT / "metadata" / "E-source-snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["facts"]["bioconductor_3.22"]["r_major_minor"] == "4.5"
    assert snapshot["facts"]["packages"]["DESeq2"]["version"] == "1.50.2"
    assert snapshot["facts"]["api_change"]["new_namespace"] == "SummarizedExperiment"
    assert pilot.task_for("E02")["required_packages"] == {
        "DESeq2": "1.50.2",
        "SummarizedExperiment": "1.40.0",
    }
    assert pilot.task_for("E03")["required_packages"]["GenomicRanges"] == "1.62.0"
    provenance = pilot.provenance("E01")
    assert len(provenance["source_snapshot_sha256"]) == 64
    assert len(provenance["source_checksum_manifest_sha256"]) == 64
    lock = json.loads((pilot.PILOT / "fixtures" / "E01-renv.lock").read_text())
    assert lock["R"]["Version"] == "4.4.3"
    assert lock["R"]["Repositories"]["BioCsoft"].endswith("/3.22/bioc")
    for task_id in ("E02", "E03"):
        workspace = pilot.PILOT / "tasks" / f"{task_id}.md"
        assert workspace.is_file()
        controls = pilot.PILOT / "verifier" / "controls" / task_id
        assert (controls / "reference.R").is_file()
        assert all(
            (controls / name).is_file() for name in pilot.task_for(task_id)["negative_controls"]
        )


def test_e_scorer_image_is_checked_before_any_model_turn():
    seen = {}

    def executor(command, *, timeout):
        seen["command"] = command
        seen["timeout"] = timeout
        return subprocess.CompletedProcess(
            command,
            0,
            b"BENCH_R=4.5.2\nBENCH_PACKAGE=DESeq2=1.50.2\n"
            b"BENCH_PACKAGE=SummarizedExperiment=1.40.0\nBENCH_PACKAGE=BiocVersion=3.22.0\n",
            b"",
        )

    result = pilot.verify_scorer_image("sha256:" + "a" * 64, ["E02"], executor=executor)
    assert result["status"] == "verified"
    assert seen["timeout"] == 30 and "--network" in seen["command"]
    assert seen["command"][seen["command"].index("--network") + 1] == "none"
    assert seen["command"][seen["command"].index("--entrypoint") + 1] == "Rscript"
    pilot.verify_runtime_image(
        "sha256:" + "a" * 64, ["H01", "E02"], executor=executor, role="executor"
    )
    assert pilot.verify_scorer_image("unused", ["H01"])["status"] == "not_required"

    def missing_executor(command, *, timeout):
        return subprocess.CompletedProcess(
            command, 0, b"BENCH_R=4.5.2\nBENCH_PACKAGE=DESeq2=MISSING\n", b""
        )

    with pytest.raises(ValueError, match="scorer image lacks E task package pins"):
        pilot.verify_scorer_image("sha256:" + "a" * 64, ["E02"], executor=missing_executor)


def test_cranlogs_tasks_are_paired_private_fixture_tasks_with_pinned_docs(tmp_path):
    assert simple.expand_tasks(["C04", "C05"]) == ["C04", "C05"]
    assert simple.suite_for("C04")[0] is pilot and simple.suite_for("C05")[0] is pilot
    for task_id in ("C04", "C05"):
        task = pilot.task_for(task_id)
        metadata = pilot.provenance(task_id)
        assert task["block"] == "C" and task["packages"] == {} and task["public_files"] == []
        assert metadata["reference_package"] == {"name": "cranlogs", "version": "2.1.1"}
        assert metadata["sources"][0]["url"] == (
            "https://cran.r-project.org/web/packages/cranlogs/cranlogs.pdf"
        )
        assert len(task.get("negative_controls", [])) == 3
        for filename in ("reference.R", *task["negative_controls"]):
            assert (pilot.PILOT / "verifier" / "controls" / task_id / filename).is_file()
        assert task_id in task["spec"]
        workspace = tmp_path / f"public-{task_id}"
        pilot.prepare(task_id, workspace)
        exported = {path.relative_to(workspace).as_posix() for path in workspace.rglob("*")}
        assert "TASK.md" in exported
        assert not any("verifier" in path or "fixtures" in path for path in exported)
        assert ("solution.R" in exported) is (task_id == "C04")
        fixture = json.loads(
            (pilot.PILOT / "verifier" / "fixtures" / f"{task_id}.json").read_text(encoding="utf-8")
        )
        assert fixture["request"]["packages"] == "ggplot2"
        assert fixture["request"]["from"] and fixture["request"]["to"]
        assert isinstance(fixture["response"], list)
        bad_when = (pilot.PILOT / "verifier" / "controls" / task_id / "wrong_when_all.R").read_text(
            encoding="utf-8"
        )
        assert 'when="all"' in bad_when
    assert 'when = "all"' not in (pilot.PILOT / "tasks" / "C05.md").read_text()
    assert 'when = "all"' in (pilot.PILOT / "tasks" / "C04.md").read_text()


def test_pilot_tasks_use_consolidated_tools_without_forcing_mcp():
    suite, toolset, tools = simple.suite_for("D01")
    assert suite is pilot and toolset == "consolidated"
    assert tools == hard.manifest()["mcp"]["tools"]
    assert simple.INSTRUCTION_VARIANTS["standard"] == simple.STANDARD_INSTRUCTIONS


@pytest.mark.parametrize("task_id", ["D01", "D02", "D03"])
def test_d_recommendation_reference_and_bad_control(task_id, tmp_path):
    controls = pilot.PILOT / "verifier" / "controls" / task_id
    reference = json.loads((controls / "reference.json").read_text(encoding="utf-8"))
    wrong = json.loads((controls / "wrong.json").read_text(encoding="utf-8"))
    assert _score_json(task_id, reference, tmp_path)["fully_correct"] is True
    result = _score_json(task_id, wrong, tmp_path)
    assert result["status"] == "scored" and result["fully_correct"] is False


@pytest.mark.parametrize(
    ("task_id", "package", "version", "source_url", "documentation_url", "features", "caveats"),
    [
        (
            "D01",
            "climenu",
            "0.2.0",
            "https://cran.r-project.org/package=climenu",
            "https://cran.r-project.org/web/packages/climenu/climenu.pdf",
            ["keyboard_single_multi_select", "stable_return_values"],
            ["menu_focused"],
        ),
        (
            "D02",
            "webfakes",
            "1.5.0",
            "https://cran.r-project.org/package=webfakes",
            "https://cran.r-project.org/web/packages/webfakes/webfakes.pdf",
            ["local_fake_server", "real_http_roundtrip"],
            ["server_process_required"],
        ),
        (
            "D03",
            "pointblank",
            "0.12.4",
            "https://cran.r-project.org/package=pointblank",
            "https://cran.r-project.org/web/packages/pointblank/pointblank.pdf",
            ["declarative_rules", "pipeline_validation", "row_level_failure_reports"],
            ["broader_validation_framework"],
        ),
    ],
)
def test_d_scorer_accepts_documented_alternatives(
    task_id, package, version, source_url, documentation_url, features, caveats, tmp_path
):
    answer = {
        "r_version": "4.5.2",
        "rationale": (
            "This documented package fits the requested workflow and has a clear scope tradeoff."
        ),
        "recommendations": [
            {
                "package": package,
                "version": version,
                "source_url": source_url,
                "documentation_url": documentation_url,
                "feature_ids": features,
                "caveat_ids": caveats,
            }
        ],
    }
    assert _score_json(task_id, answer, tmp_path)["fully_correct"] is True


def test_d_scorer_accepts_every_curated_candidate(tmp_path):
    candidates = json.loads(
        pilot.bench.safe_file(pilot.PILOT / "verifier", "candidates.json").read_text(
            encoding="utf-8"
        )
    )
    for task_id, packages in candidates.items():
        for package, metadata in packages.items():
            answer = {
                "r_version": "4.5.2",
                "rationale": (
                    "This package matches the requested workflow and has a "
                    "documented scope tradeoff."
                ),
                "recommendations": [
                    {
                        "package": package,
                        "version": metadata["version"],
                        "source_url": metadata["source_url"],
                        "documentation_url": metadata["documentation_url"],
                        "feature_ids": metadata["required_features"],
                        "caveat_ids": metadata["required_caveats"],
                    }
                ],
            }
            assert _score_json(task_id, answer, tmp_path)["fully_correct"] is True


def test_mcp_event_storage_redacts_arguments_and_responses():
    safe = simple.redact_mcp_events(
        [
            {
                "type": "agent.session.turn.item.done",
                "sequence_number": 4,
                "item": {
                    "type": "mcp_tool_call",
                    "id": "item-1",
                    "server": "r_knowledge",
                    "tool": "get_function_docs",
                    "arguments": {"secret_argument": "do-not-save"},
                    "result": {"documentation": "do-not-save-either"},
                    "status": "completed",
                },
            },
            {
                "type": "agent.session.turn.item.done",
                "item": {"type": "tool_search_call", "query": "also private", "results": []},
            },
            {
                "type": "agent.session.turn.item.done",
                "item": {
                    "type": "command_execution",
                    "command": "private command",
                    "cwd": "C:/private/path",
                    "output": "private output",
                    "status": "completed",
                },
            },
            {
                "type": "agent.session.turn.item.done",
                "item": {"type": "reasoning", "summary": "private reasoning"},
            },
        ]
    )
    encoded = json.dumps(safe)
    assert "get_function_docs" in encoded
    assert all(
        value not in encoded
        for value in (
            "do-not-save",
            "also private",
            "private command",
            "C:/private/path",
            "private output",
            "private reasoning",
        )
    )
    assert safe[0]["item"]["payload_redacted"] is True
    assert "arguments" not in safe[0]["item"] and "result" not in safe[0]["item"]
    assert safe[1]["item"]["payload_redacted"] is True


def test_results_export_per_call_aggregates_and_actual_usage(tmp_path):
    calls = [
        {
            "run_id": "run-1",
            "trial_id": "B01-B-1",
            "tool_name": "get_function_docs",
            "call_number": 1,
            "status": "ok",
            "request_bytes": 68,
            "response_bytes": 1200,
            "response_tokens_estimate": 300,
            "response_token_estimate_method": "ceil(UTF-8 result JSON bytes / 4)",
            "duration_ms": 12.5,
            "error_code": None,
            "error_type": None,
            "truncated": False,
        }
    ]
    record = {
        "run_id": "run-1",
        "trial_id": "B01-B-1",
        "task": "B01",
        "mode": "with-mcp",
        "repetition": 2,
        "model": "gpt-6-luna",
        "effort": "medium",
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 25},
            "output_tokens": 40,
            "output_tokens_details": {"reasoning_tokens": 5},
            "total_tokens": 140,
        },
        "usage_status": "observed",
        "cost": None,
        "cost_status": "unavailable",
        "mcp_usage": {
            "calls": 1,
            "tool_names": ["get_function_docs"],
            "calls_by_tool": {"get_function_docs": 1},
            "tool_search_calls": 0,
        },
        "mcp_server_audit": {"list_tools_requests": 1, "call_tool_requests": 1},
        "mcp_telemetry": {
            "calls": calls,
            "aggregates_by_tool": simple._telemetry_aggregates(calls),
            "reconciliation": {"status": "matched"},
        },
        "score": {"passed": 5, "total": 5, "failed_checks": []},
    }
    simple.save_results(tmp_path, [record])

    calls_csv = (tmp_path / "mcp_calls.csv").read_text(encoding="utf-8")
    aggregates_csv = (tmp_path / "mcp_tool_aggregates.csv").read_text(encoding="utf-8")
    results_csv = (tmp_path / "results.csv").read_text(encoding="utf-8")
    assert "get_function_docs" in calls_csv and ",1200,300," in calls_csv
    assert "get_function_docs,1,1,0,68,1200,0,300,0,12.5,0" in aggregates_csv
    assert "api_input_tokens" in results_csv and "api_cached_input_tokens" in results_csv
    assert "api_reasoning_tokens" in results_csv and "cost_status" in results_csv
    # The score is a JSON cell and failed_checks has its own JSON column; both survive a
    # CSV round trip, and "no failed checks" ([]) stays distinct from "unknown" (empty cell).
    with (tmp_path / "results.csv").open(newline="", encoding="utf-8") as stream:
        (row,) = list(csv.DictReader(stream))
    assert json.loads(row["failed_checks"]) == []
    assert json.loads(row["score"]) == {"passed": 5, "total": 5, "failed_checks": []}
    assert (row["passed"], row["total"]) == ("5", "5")
    assert "repetition" in results_csv


@pytest.mark.docker
def test_r_hidden_reference_and_mutants_against_frozen_scorer():
    if not shutil.which("docker"):
        pytest.skip("Docker CLI is unavailable")
    image = subprocess.run(
        ["docker", "image", "inspect", "codex-r-benchmark:pilot", "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if image.returncode or not image.stdout.strip():
        pytest.skip("frozen benchmark scorer image is unavailable")
    image_id = image.stdout.strip()
    report = pilot.selftest(image_id)
    assert set(report) == set(pilot.PILOT_TASK_IDS)
    assert all(
        value.get("reference", {}).get("fully_correct") is True
        or (task_id in {"E02", "E03"} and value.get("environment") == "unavailable")
        for task_id, value in report.items()
    )
    assert all(
        not case["fully_correct"]
        for value in report.values()
        for label, case in value.items()
        if label not in {"reference", "environment", "reason"}
    )


@pytest.mark.docker
def test_cranlogs_reference_and_negative_controls_against_frozen_scorer():
    if not shutil.which("docker"):
        pytest.skip("Docker CLI is unavailable")
    image = subprocess.run(
        ["docker", "image", "inspect", "codex-r-benchmark:pilot", "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if image.returncode or not image.stdout.strip():
        pytest.skip("frozen benchmark scorer image is unavailable")
    report = pilot.selftest(image.stdout.strip(), task_ids=("C04", "C05"))
    assert set(report) == {"C04", "C05"}
    for task in report.values():
        assert task["reference"]["fully_correct"] is True
        assert len(task) == 4  # reference plus three distinct negative controls
        assert all(
            not case["fully_correct"] for label, case in task.items() if label != "reference"
        )


def test_results_csv_distinguishes_no_failed_checks_from_unscored(tmp_path):
    scored = {
        "run_id": "r",
        "trial_id": "t1",
        "score": {"passed": 2, "total": 4, "failed_checks": ["a"]},
    }
    clean = {
        "run_id": "r",
        "trial_id": "t2",
        "score": {"passed": 4, "total": 4, "failed_checks": []},
    }
    unscored = {"run_id": "r", "trial_id": "t3", "score": None}
    simple.save_results(tmp_path, [scored, clean, unscored])
    with (tmp_path / "results.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["trial_id"]: row for row in csv.DictReader(stream)}
    assert json.loads(rows["t1"]["failed_checks"]) == ["a"]
    assert json.loads(rows["t2"]["failed_checks"]) == []
    assert rows["t3"]["failed_checks"] == "" and rows["t3"]["score"] == ""
