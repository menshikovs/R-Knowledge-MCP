"""Infrastructure tests only: every trial/metric below is explicitly synthetic."""

import csv
import importlib.util
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from mcp.types import CallToolResult, TextContent, Tool

from cran_knowledge_mcp.server import create_server

pytestmark = pytest.mark.usefixtures("r01a_offline_guard")

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/codex_r"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"runner/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench, gateway = load("bench"), load("gateway")
IMAGE = "sha256:" + "a" * 64


def experiment():
    return bench.plan("synthetic-model-not-an-observation", "high", IMAGE)


def record(condition="A", passed=4, task="R01", repeat=1):
    plan = experiment()
    return {
        "trial_id": f"{task}-{condition}-{repeat}",
        "task": task,
        "condition": condition,
        **{
            k: plan[k]
            for k in ("model", "reasoning_effort", "image", "production_commit", "fingerprint")
        },
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:30+00:00",
        "status": "scored",
        "passed": passed,
        "total": 4,
        "isolation_verified": True,
        "artifacts": {"solution.R": "b" * 64},
        "usage": None,
        "mcp_calls": 0,
        "mcp_errors": 0,
        "invalid_api_calls": None,
        "repairs": None,
    }


def test_manifest_real_lock_and_independent_oracles():
    data = bench.manifest()
    assert len(data["tasks"]) == 12
    lock = bench.read_json(ROOT / "configs/renv.lock")
    assert lock["Packages"]["IRanges"]["Version"] == "2.44.0"
    assert len(lock["Packages"]) >= 80
    assert {t["area"] for t in data["tasks"]}.__len__() == 12
    for task in data["tasks"]:
        with (ROOT / task["fixture"]).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, strict=True))
        assert rows and all(None not in row for row in rows)


async def test_condition_tools_are_actual_public_interfaces(monkeypatch):
    monkeypatch.setenv("PROMPT_INTELLIGENCE_ENABLED", "true")
    # The benchmark gateway and run_simple pin MCP_TOOLSET=legacy for these conditions.
    actual = {t.name for t in await create_server(toolset="legacy").list_tools()}
    data = bench.manifest()
    for condition in "BC":
        assert set(data["conditions"][condition]["tools"]) <= actual
    assert not set(data["conditions"]["B"]["tools"]) & {
        "build_r_prompt",
        "improve_r_prompt",
        "get_r_prompt_context",
    }


def test_plan_randomized_balanced_and_reproducible():
    a, b = experiment(), experiment()
    assert a == b and len(a["trials"]) == 72
    for task in [f"R{i:02}" for i in range(1, 13)]:
        for repeat in (1, 2):
            assert {
                t["condition"] for t in a["trials"] if t["task"] == task and t["repeat"] == repeat
            } == set("ABC")
    assert bench.plan(a["model"], "high", IMAGE, seed=7)["trials"] != a["trials"]
    with pytest.raises(ValueError):
        bench.plan("default", "high", IMAGE)
    with pytest.raises(ValueError):
        bench.plan(a["model"], "high", "mutable-image-tag")


def test_plan_is_independent_of_current_working_directory(monkeypatch):
    expected = experiment()
    monkeypatch.chdir(ROOT)
    assert experiment() == expected


def test_prepare_has_only_public_inputs_and_reproducible_fixtures(tmp_path):
    first = bench.prepare("R03", tmp_path / "first")
    second = bench.prepare("R03", tmp_path / "second")
    assert first["files"] == second["files"]
    assert set(first["files"]) == {"TASK.md", "renv.lock", "data/measurements.csv"}
    assert not list((tmp_path / "first").rglob("*oracle*"))
    assert not list((tmp_path / "first").rglob("*solution*"))
    with pytest.raises(ValueError):
        bench.prepare("R03", ROOT / "must-not-create")


def test_candidate_container_cannot_mount_oracles(tmp_path):
    cmd = bench.docker_command(IMAGE, tmp_path)
    assert "/oracle" not in " ".join(cmd) and "/config" not in " ".join(cmd)
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "none"
    for value in ("--read-only", "no-new-privileges", "ALL", "2048m", "65534:65534"):
        assert value in cmd
    assert str(bench.REPO) not in " ".join(cmd)
    scored = bench.docker_command(IMAGE, tmp_path, scoring=True, task_id="R01")
    assert "target=/oracle,readonly" in " ".join(scored)
    assert "target=/candidate,readonly" in " ".join(scored)
    assert "timeout" in scored and "--pids-limit" in scored


def test_sealed_artifacts_are_bounded_allowlisted_and_not_candidate_data(tmp_path, monkeypatch):
    source, sealed = tmp_path / "candidate", tmp_path / "sealed"
    source.mkdir()
    (source / "solution.R").write_text("# synthetic artifact")
    (source / "secret.txt").write_text("synthetic distractor")
    (source / "data").mkdir()
    (source / "data/measurements.csv").write_text("candidate changed input")
    hashes = bench.seal_artifacts("R03", source, sealed)
    assert set(hashes) == {"solution.R"}
    assert not (sealed / "secret.txt").exists()
    assert (sealed / "data/measurements.csv").read_bytes() == (
        ROOT / "tasks/R03/data/measurements.csv"
    ).read_bytes()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p.name == "solution.R" or original(p))
    with pytest.raises(ValueError, match="regular"):
        bench.seal_artifacts("R03", source, tmp_path / "blocked")


@pytest.mark.parametrize(
    ("returncode", "payload", "expected", "passed"),
    [
        (0, b'BENCH_RESULT={"status":"scored","passed":3}\n', "scored", 3),
        (125, b"", "scoring_error", None),
        (137, b"", "candidate_error", 0),
        (0, b"", "candidate_error", 0),
        (124, b"", "candidate_timeout", 0),
        (0, b'BENCH_RESULT={"status":"scoring_error","passed":null}\n', "scoring_error", None),
    ],
)
def test_scoring_distinguishes_observations_from_infrastructure(
    tmp_path, returncode, payload, expected, passed
):
    (tmp_path / "solution.R").write_text("# synthetic candidate")

    def execute(command, **kwargs):
        assert command[0] == "docker" and kwargs["timeout"] == 190
        return subprocess.CompletedProcess(command, returncode, stdout=payload)

    result = bench.score("R01", tmp_path, IMAGE, executor=execute)
    assert (result["status"], result["passed"], result["total"]) == (expected, passed, 4)


def test_timeout_scores_zero_without_hiding_it(tmp_path):
    (tmp_path / "solution.R").write_text("# synthetic candidate")

    def execute(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    result = bench.score("R01", tmp_path, IMAGE, executor=execute)
    assert result["status"] == "candidate_timeout" and result["passed"] == 0


def test_output_resource_limit_is_a_candidate_failure(tmp_path):
    (tmp_path / "solution.R").write_text("# synthetic candidate")

    def execute(command, **kwargs):
        raise bench.OutputLimitExceeded("synthetic excessive output")

    result = bench.score("R01", tmp_path, IMAGE, executor=execute)
    assert result["status"] == "candidate_error" and result["passed"] == 0


def test_timeout_stops_the_actual_container_not_only_the_client(monkeypatch):
    process = SimpleNamespace(stdout=io.BytesIO(), stderr=io.BytesIO(), returncode=None)

    def wait(timeout):
        if process.returncode is None:
            raise subprocess.TimeoutExpired("synthetic docker client", timeout)
        return process.returncode

    process.wait = wait
    process.poll = lambda: process.returncode
    process.kill = lambda: setattr(process, "returncode", -9)
    removals = []
    monkeypatch.setattr(bench.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(bench.subprocess, "run", lambda command, **kwargs: removals.append(command))
    name = "codex-r-score-" + "b" * 32
    with pytest.raises(subprocess.TimeoutExpired):
        bench.execute_container(["docker", "run", "--name", name], timeout=1)
    assert process.returncode == -9
    assert removals == [["docker", "rm", "--force", name]]


def test_usage_is_actual_events_or_explicitly_missing():
    assert bench.usage_from_events([{"type": "item.completed", "text": "x" * 50000}]) is None
    assert bench.usage_from_events(
        [{"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 7}}]
    ) == {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("total", 10),
        ("model", "different"),
        ("isolation_verified", False),
        ("passed", True),
        ("mcp_calls", 1),
        ("completed_at", "2026-01-01T01:00:00+00:00"),
        ("usage", {"input_tokens": 2, "output_tokens": 3, "total_tokens": 99}),
    ],
)
def test_result_validation_rejects_unfair_or_invalid_records(key, value):
    sample = record()
    sample[key] = value
    with pytest.raises(ValueError):
        bench.validate_record(sample, experiment())


def test_json_schema_and_runtime_validation_agree():
    schema = bench.read_json(ROOT / "configs/result.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    sample = record()
    jsonschema.validate(sample, schema)
    assert bench.validate_record(sample, experiment()) == sample


def test_reports_missingness_paired_outcomes_and_no_fake_conclusion():
    plan = experiment()
    empty = bench.report(plan, [])
    assert "No comparative agent execution results are available yet." in empty
    assert "| A | 24 | 0 | 24 | 0/0 | unavailable |" in empty
    rows = [
        record("A", 2, "R01"),
        record("B", 4, "R01"),
        record("A", 4, "R02"),
        record("B", 2, "R02"),
    ]
    text = bench.report(plan, rows)
    assert "95% cluster interval" in text
    assert "invalid_api_calls: observed total=unavailable" in text
    with pytest.raises(ValueError, match="Duplicate"):
        bench.report(plan, [rows[0], rows[0]])


class Backend:
    def __init__(self):
        self.called = []
        self.names = bench.manifest()["conditions"]["C"]["tools"]

    async def list_tools(self):
        return SimpleNamespace(
            tools=[Tool(name=n, inputSchema={"type": "object"}) for n in self.names]
        )

    async def call_tool(self, name, arguments):
        self.called.append(name)
        return CallToolResult(
            isError=True,
            structuredContent={"verification_status": "failed"},
            content=[TextContent(type="text", text="synthetic upstream failure")],
        )


async def test_gateway_enforces_allowlist_and_preserves_upstream_errors():
    backend, log = Backend(), io.StringIO()
    g = gateway.Gateway("B", backend, log)
    tools = await g.tools()
    assert "build_r_prompt" not in {t.name for t in tools}
    assert (await g.call("build_r_prompt", {})).isError
    result = await g.call("get_package_info", {"package": "ggplot2"})
    assert result.isError and backend.called == ["get_package_info"]
    entries = [json.loads(line) for line in log.getvalue().splitlines()]
    assert entries[2]["arguments"] == {"package": "ggplot2"}
    assert entries[2]["result"]["structuredContent"]["verification_status"] == "failed"
    with pytest.raises(ValueError):
        gateway.Gateway("A", backend, log)


async def test_C_exposes_public_PI_and_fails_closed_on_drift():
    backend, log = Backend(), io.StringIO()
    g = gateway.Gateway("C", backend, log)
    assert "build_r_prompt" in {t.name for t in await g.tools()}
    await g.call("build_r_prompt", {"request": "synthetic task", "detail_level": "concise"})
    assert backend.called == ["build_r_prompt"]
    backend.names = []
    with pytest.raises(ValueError, match="differs"):
        await g.tools()


def test_external_record_derives_usage_and_rejects_treatment_leakage():
    sample = record()
    metadata = {
        k: sample[k]
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
    scoring = {k: sample[k] for k in ("status", "passed", "artifacts")}
    imported = bench.assemble_record(experiment(), "R01-A-1", metadata, scoring, [], [])
    assert imported == sample
    with pytest.raises(ValueError, match="unassigned"):
        bench.assemble_record(
            experiment(),
            "R01-A-1",
            metadata,
            scoring,
            [{"item": {"type": "mcp_tool_call", "tool": "build_r_prompt"}}],
            [],
        )
