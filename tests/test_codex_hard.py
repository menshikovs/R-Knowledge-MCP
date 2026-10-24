"""Hard benchmark v1 suite: registry, public export, sealing, scoring and runner wiring."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from benchmarks.codex_r import run_simple
from benchmarks.codex_r.hard import selftest, suite

PILOT = ["H01", "H04", "H10"]


def test_registry_lists_the_pilot_with_counted_checks():
    data = suite.manifest()
    assert suite.task_ids() == PILOT
    for task in data["tasks"]:
        assert task["artifacts"] == ["solution.R"]
        assert task["checks"] >= 15
        metadata = json.loads((suite.HARD / task["metadata"]).read_text(encoding="utf-8"))
        for key in ("source", "packages", "difficulty_hypothesis", "expected_mcp_relevance"):
            assert metadata[key]
    assert "substitution" in json.loads(
        (suite.HARD / suite.task_for("H04")["metadata"]).read_text(encoding="utf-8")
    )
    assert not set(data["mcp"]["tools"]) & {"build_r_prompt", "get_r_prompt_context"}


@pytest.mark.parametrize("task_id", PILOT)
def test_prepare_exports_only_public_inputs(task_id, tmp_path):
    workspace = tmp_path / "candidate"
    exported = suite.prepare(task_id, workspace)
    task = suite.task_for(task_id)
    files = sorted(
        str(p.relative_to(workspace)).replace("\\", "/")
        for p in workspace.rglob("*")
        if p.is_file()
    )
    assert files == sorted(
        ["TASK.md", "renv.lock", *(f"data/{Path(f).name}" for f in task["fixtures"])]
    )
    assert set(exported["files"]) == set(files)
    assert (workspace / "TASK.md").read_bytes() == (suite.HARD / task["spec"]).read_bytes()
    hidden = [p.read_text(encoding="utf-8") for p in (suite.HARD / "verifier").rglob("*.R")]
    markers = ["_oracle <- function", "call_candidate(", "Trusted reference"]
    for path in workspace.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert not any(marker in text for marker in markers)
            assert not any(text == source for source in hidden)


def test_prepare_refuses_existing_or_repository_workspaces(tmp_path):
    with pytest.raises(ValueError):
        suite.prepare("H01", suite.HARD / "should-not-exist")
    existing = tmp_path / "exists"
    existing.mkdir()
    with pytest.raises(ValueError):
        suite.prepare("H01", existing)


def test_seal_rejects_missing_symlinked_and_non_utf8_artifacts(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError):
        suite.seal_artifacts("H10", source, tmp_path / "sealed-missing")
    (source / "solution.R").write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(UnicodeDecodeError):
        suite.seal_artifacts("H10", source, tmp_path / "sealed-bytes")
    (source / "solution.R").unlink()
    target = tmp_path / "elsewhere.R"
    target.write_text("pool_estimates <- function(...) NULL\n", encoding="utf-8")
    try:
        os.symlink(target, source / "solution.R")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")
    with pytest.raises(ValueError):
        suite.seal_artifacts("H10", source, tmp_path / "sealed-link")


def fake_executor(stdout=b"", returncode=0):
    def run(command, *, timeout):
        assert command[command.index("--network") + 1] == "none"
        assert "--read-only" in command and "ALL" in command
        assert any(part.endswith("target=/candidate,readonly") for part in command)
        return subprocess.CompletedProcess(command, returncode, stdout, b"")

    return run


def artifacts(tmp_path):
    path = tmp_path / "artifacts"
    path.mkdir(parents=True)
    (path / "solution.R").write_text("dynamic_summary <- function(...) NULL\n", encoding="utf-8")
    return path


IMAGE = "sha256:" + "a" * 64


def result_line(**fields):
    return ("BENCH_RESULT=" + json.dumps(fields) + "\n").encode()


def test_score_reports_fully_correct_only_when_every_check_passes(tmp_path):
    full = result_line(
        status="scored", passed=18, total=18, failed_checks=[], environment={"r": "4.5.2"}
    )
    score = suite.score("H01", artifacts(tmp_path), IMAGE, executor=fake_executor(full))
    assert score["fully_correct"] is True and score["environment"] == {"r": "4.5.2"}
    partial = result_line(status="scored", passed=17, total=18, failed_checks=["x"])
    score = suite.score("H01", artifacts(tmp_path / "b"), IMAGE, executor=fake_executor(partial))
    assert score["fully_correct"] is False and score["failed_checks"] == ["x"]


def test_score_separates_candidate_and_infrastructure_failures(tmp_path):
    forged = result_line(status="scored", passed=18, total=18) * 2
    score = suite.score("H01", artifacts(tmp_path), IMAGE, executor=fake_executor(forged))
    assert score["status"] == "candidate_error" and score["fully_correct"] is False
    timeout = suite.score(
        "H01", artifacts(tmp_path / "t"), IMAGE, executor=fake_executor(returncode=124)
    )
    assert timeout["status"] == "candidate_timeout" and timeout["passed"] == 0
    broken = suite.score(
        "H01", artifacts(tmp_path / "s"), IMAGE, executor=fake_executor(returncode=125)
    )
    assert broken["status"] == "scoring_error"
    assert broken["passed"] is None and broken["fully_correct"] is None
    preflight = result_line(status="scoring_error", reason="environment_preflight_failed")
    failed = suite.score("H01", artifacts(tmp_path / "p"), IMAGE, executor=fake_executor(preflight))
    assert failed["status"] == "scoring_error" and failed["fully_correct"] is None


def test_score_rejects_check_counts_that_differ_from_the_registry(tmp_path):
    wrong = result_line(status="scored", passed=3, total=3)
    with pytest.raises(ValueError):
        suite.score("H01", artifacts(tmp_path), IMAGE, executor=fake_executor(wrong))


def test_runner_routes_hard_tasks_to_the_hard_suite_and_consolidated_tools():
    task_suite, toolset, tools = run_simple.suite_for("H04")
    assert task_suite is suite and toolset == "consolidated"
    assert tools == suite.manifest()["mcp"]["tools"]
    legacy_suite, legacy_toolset, legacy_tools = run_simple.suite_for("R01")
    assert legacy_toolset == "legacy" and "get_package_info" in legacy_tools


def test_mcp_usage_counts_only_observed_tool_calls():
    events = [
        {"type": "agent.session.turn.item.done", "item": {"type": "reasoning"}},
        {"type": "agent.session.turn.item.done", "item": {"type": "mcp_list_tools"}},
        {
            "type": "agent.session.turn.item.done",
            "item": {"type": "mcp_call", "name": "get_function_docs"},
        },
        {
            "type": "agent.session.turn.item.done",
            "item": {"type": "mcp_call", "name": "get_package"},
        },
        {"type": "agent.session.turn.item.added", "item": {"type": "mcp_call", "name": "ignored"}},
    ]
    usage = run_simple.mcp_usage(events)
    assert usage["calls"] == 2
    assert usage["tool_names"] == ["get_function_docs", "get_package"]
    assert run_simple.mcp_usage([])["calls"] == 0


def test_missing_usage_and_cost_stay_null_and_marked_unavailable():
    record = {"usage": None, "cost": None}
    run_simple.observed_usage(record, [{"type": "agent.session.turn.completed", "usage": None}])
    assert record == {
        "usage": None,
        "cost": None,
        "usage_status": "unavailable",
        "cost_status": "unavailable",
    }
    observed = {"usage": None, "cost": 0.0}
    run_simple.observed_usage(
        observed, [{"type": "agent.session.turn.completed", "usage": {"input_tokens": 5}}]
    )
    assert observed["usage"] == {"input_tokens": 5}
    assert observed["usage_status"] == "observed" and observed["cost_status"] == "observed"


def test_hard_pilot_selector_is_accepted_without_starting_trials(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EXECUTOR_API_KEY", raising=False)
    code = run_simple.main(
        ["--effort", "medium", "--tasks", "hard-pilot", "--results", str(tmp_path)]
    )
    assert code == 1
    (results,) = list(tmp_path.glob("*/results.json"))
    record = json.loads(results.read_text(encoding="utf-8"))[0]
    assert record["status"] == "startup_error" and "OPENAI_API_KEY" in record["error"]


def docker_image_available():
    if not shutil.which("docker"):
        return False
    try:
        selftest.image_id("codex-r-benchmark:pilot")
    except Exception:
        return False
    return True


@pytest.mark.docker
@pytest.mark.parametrize("task_id", PILOT)
def test_verifier_gate_passes_in_the_pinned_scorer_image(task_id):
    if not docker_image_available():
        pytest.skip("Docker or the pinned scorer image is unavailable")
    outcome = selftest.validate_task(task_id, selftest.image_id("codex-r-benchmark:pilot"))
    assert outcome["problems"] == []
    assert outcome["results"]["reference"]["fully_correct"] is True


async def test_with_mcp_allowed_tools_exist_on_the_consolidated_server():
    from cran_knowledge_mcp.server import create_server

    names = {tool.name for tool in await create_server(toolset="consolidated").list_tools()}
    assert set(suite.manifest()["mcp"]["tools"]) <= names
