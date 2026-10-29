"""Stage 3A end to end: the real benchmark runner with a mocked model (Linux + Docker only).

Real: ``run_simple.run_trial`` (session lifecycle, Docker network, R-Knowledge-MCP container and
its log-derived telemetry, artifact sealing, cleanup), the R scorer image, the Stage 2 ledger,
records, spend control and the preregistered analysis.

Mocked, and only these: the Agents API (an ``httpx.MockTransport``) and what the executor does.
The scripted executor writes fixed solution files and, in arms B/C, runs a real container on the
trial network that performs a genuine MCP ``tools/list`` + ``tools/call`` against the real server.
Scripted files are fixtures, not model output: nothing here measures model capability.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from benchmarks.codex_r import run_simple
from benchmarks.codex_r.studies.stage2_validity_v1 import (
    amendment,
    analysis,
    calibration_pipeline,
    design,
    legacy_executor,
    live_runner,
    manifest,
    protocol,
    records,
    runner,
    spend_control,
)

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(sys.platform != "linux", reason="run_simple uses Linux SIGALRM"),
]
LIVE_ASSETS = Path(legacy_executor.__file__).with_name("live_assets")
HARD_CONTROLS = manifest.CODEX / "hard" / "verifier" / "controls" / "H01"
IMAGES = {
    "executor": "rkmcp-codex-runtime:codex-0.163.0",
    "scorer": "codex-r-benchmark:pilot",
    "mcp": "cran-knowledge-mcp:shiny-quarto",
    "probe": "python:3.11-slim",
}
USAGE = {"input_tokens": 1500, "output_tokens": 300}
CEILING = spend_control.SpendCeiling(1.0, 2.0, 8.0, 0.05)

R01_CORRECT = """clean_records <- function(data) {
  if (!is.data.frame(data) || !all(c("id", "value") %in% names(data))) {
    stop("data must have id and value columns")
  }
  if (!is.character(data$id) || !is.numeric(data$value)) stop("wrong column types")
  id <- trimws(data$id)
  value <- as.double(data$value)
  keep <- !is.na(id) & nzchar(id) & is.finite(value)
  id <- id[keep]
  value <- value[keep]
  first <- !duplicated(id)
  id <- id[first]
  value <- value[first]
  o <- order(id, method = "radix")
  data.frame(id = id[o], value = value[o], stringsAsFactors = FALSE)
}
"""
R01_WRONG = "clean_records <- function(data) data\n"


def _image_ids():
    try:
        return {role: run_simple.image_id(ref) for role, ref in IMAGES.items()}
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"local Docker images unavailable: {exc}")


@dataclass
class Current:
    trial_id: str
    task: str
    mode: str


class ScriptedModel:
    """Mocked Agents API + scripted executor. Session events describe what the executor did."""

    def __init__(self, solutions, interrupt=()):
        self.solutions = solutions  # (trial_id, task) -> {filename: text}
        self.interrupt = set(interrupt)
        self.current: Current | None = None
        self.sessions: dict[str, dict] = {}
        self.mcp_results: dict[str, dict] = {}

    # run_trial wrapper: remember which trial the next session belongs to.
    def run_trial(self, args, task, mode, repetition, output, keys, images, *, planned_trial_id):
        self.current = Current(planned_trial_id, task, mode)
        return run_simple.run_trial(
            args, task, mode, repetition, output, keys, images, planned_trial_id=planned_trial_id
        )

    def respond(self, request):
        path, method = request.url.path, request.method
        if method == "POST" and path.endswith("/sessions"):
            body = json.loads(request.content)
            sid = f"sess_{len(self.sessions) + 1:04d}"
            self.sessions[sid] = {"agent": body["agent"], "done": threading.Event(), "items": []}
            return httpx.Response(
                200,
                json={
                    "id": sid,
                    "agent": body["agent"],
                    "environment": {
                        "type": "self_hosted",
                        "id": f"env_{sid}",
                        "remote_url": "https://api.openai.com/v1/agents/api",
                    },
                },
            )
        sid = path.split("/sessions/")[1].split("/")[0]
        session = self.sessions[sid]
        if method == "GET" and path.endswith("/events"):
            assert session["done"].wait(120), "scripted executor never finished"
            events = [{"type": "agent.session.environment.connected"}]
            for index, item in enumerate(session["items"], start=1):
                item = {"id": f"item_{index:03d}", **item}
                events.append({"type": "agent.session.turn.item.added", "item": item})
                events.append(
                    {
                        "type": "agent.session.turn.item.done",
                        "item": {**item, "status": "completed"},
                    }
                )
            events.append({"type": "agent.session.turn.completed"})
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                text="".join(f"data: {json.dumps(e)}\n\n" for e in events),
            )
        if method == "DELETE":
            return httpx.Response(200, json={"id": sid, "deleted": True})
        if method == "GET":
            return httpx.Response(200, json={"id": sid, "usage": USAGE, "cost": None})
        return httpx.Response(200, json={})  # task submission

    def start_executor(self, name, network, image, workspace, environment, key):
        sid = environment["session_id"]
        session = self.sessions[sid]
        cur = self.current
        try:
            if cur.trial_id in self.interrupt:
                self.interrupt.discard(cur.trial_id)
                raise KeyboardInterrupt("scripted interruption before the agent ran")
            for filename, text in self.solutions[(cur.trial_id, cur.task)].items():
                Path(workspace, filename).write_text(text, encoding="utf-8")
            session["items"].append({"type": "command_execution", "command": "Rscript -e 1"})
            script = (
                "import json,sys; sys.path.insert(0,'/opt/stage26'); import mock_agent; "
                "print('MCP_RESULT ' + json.dumps(mock_agent.mcp_workflow("
                + json.dumps(live_runner.MOCK_TOOL_CALL)
                + ")))"
                if cur.mode == "with-mcp"
                else "print('no mcp')"
            )
            proc = subprocess.run(
                [
                    "docker",
                    "run",
                    "--name",
                    name,
                    "--network",
                    network,
                    "--mount",
                    f"type=bind,source={LIVE_ASSETS},target=/opt/stage26,readonly",
                    IMAGES["probe"],
                    "python",
                    "-c",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
            for line in proc.stdout.splitlines():
                if line.startswith("MCP_RESULT "):
                    result = json.loads(line[len("MCP_RESULT ") :])
                    self.mcp_results[cur.trial_id] = result
                    for call in result.get("calls", []):
                        session["items"].append(
                            {"type": "mcp_tool_call", "server": "r_knowledge", "tool": call["tool"]}
                        )
        finally:
            session["done"].set()


@pytest.fixture
def scripted(monkeypatch):
    images = _image_ids()
    created = []

    def install(solutions, interrupt=()):
        model = ScriptedModel(solutions, interrupt)
        original = run_simple.SimpleClient
        monkeypatch.setattr(
            run_simple,
            "SimpleClient",
            lambda *keys: original(*keys, transport=httpx.MockTransport(model.respond)),
        )
        monkeypatch.setattr(run_simple, "start_executor", model.start_executor)
        created.append(model)
        return model

    ctx = legacy_executor.LegacyExecutionContext(
        study=legacy_executor.STUDIES["study1"],
        effort="medium",
        timeout_seconds=300,
        images={k: v for k, v in images.items() if k != "probe"},
        keys=("application-test-key", "executor-test-key"),
        synthetic=True,  # the model is mocked
    )
    yield install, ctx
    leftovers = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=rkmcp-simple-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    ).stdout.split()
    assert leftovers == [], f"run_trial left containers behind: {leftovers}"


def _spec(task, trial_id="t-A", arm="A"):
    planned = legacy_executor.pin_plan_identities(
        design.build_plan([task], ("A", "B"), 1, 7, protocol.STUDY_ID)
    )["trials"]
    trial = next(t for t in planned if t["arm"] == arm)
    return runner.build_trial_invocation_spec(
        {**trial, "trial_id": trial_id}, runner.StudyExecutionConfig()
    )


def test_full_abc_lifecycle_through_the_real_runner_with_resume_and_analysis(scripted, tmp_path):
    install, ctx = scripted
    # 1-3: manifest, identities, randomized plan.
    built = manifest.build_manifest()
    saved = json.loads(
        (Path(legacy_executor.__file__).with_name("experiment_manifest.json")).read_text()
    )
    assert built == saved
    plan = legacy_executor.pin_plan_identities(
        design.build_plan(["R01"], ("A", "B", "C"), 1, 20261028, protocol.STUDY_ID)
    )
    assert legacy_executor.plan_identity_problems(plan) == []
    ordered = [t["trial_id"] for t in sorted(plan["trials"], key=lambda t: t["execution_index"])]
    model = install(
        {(tid, "R01"): {"solution.R": R01_CORRECT} for tid in ordered}, interrupt={ordered[1]}
    )
    executor = legacy_executor.make_legacy_trial_executor(ctx, run_trial=model.run_trial)

    # 4-11 with an interruption, then 12: resume.
    first = legacy_executor.execute_study(
        plan, tmp_path, ctx, spend_ceiling=CEILING, executor=executor
    )
    assert first["interrupted"] is True and first["finalized_count"] == 1
    second = legacy_executor.execute_study(
        plan, tmp_path, ctx, spend_ceiling=CEILING, executor=executor
    )
    assert second["finalized_count"] == 3 and second["dataset_problems"] == []
    assert second["spend"]["reserve_charged_for_interrupted_attempts"] == [f"{ordered[1]}__att01"]
    attempts = sorted(p.name for p in (tmp_path / "workspaces").iterdir())
    assert attempts == sorted(
        [
            f"{ordered[0]}__att01",
            f"{ordered[1]}__att01",
            f"{ordered[1]}__att02",
            f"{ordered[2]}__att01",
        ]
    )

    by_arm = {r["arm"]: r for r in second["records"]}
    for rec in by_arm.values():
        assert records.validate_record(rec) == []
        assert rec["outcome_kind"] == "scored" and rec["score"] == 1.0  # real R verifier, 4/4
        assert rec["synthetic"] is True and rec["usage"]["status"] == "observed"
        # Amendment A1: the 1.0.0 egress codes stay recorded (superseded), nothing invalidating.
        assert rec["protocol_version"] == "1.1.0+A1"
        assert {v["code"] for v in rec["violations"]} == set(legacy_executor.STRUCTURAL_VIOLATIONS)
        assert all(v["superseded_by"] == "A1" and not v["invalidating"] for v in rec["violations"])
        assert rec["agent_tools"]["used"].get("command_execution") == 1
        cap = rec["capability"]  # measured from the real run_trial, per trial
        assert cap["non_mcp_tools"] == [] and cap["executor_image"] == ctx.images["executor"]
        assert cap["scorer_isolation"]["exposed_files"] == []
        assert cap["observed"]["reference_access_hits"] == []
        assert cap["started_at_utc"] >= amendment.EFFECTIVE_FROM_UTC[:10]
    assert by_arm["A"]["mcp"]["available"] is False and by_arm["A"]["mcp"]["attempted"] == 0
    for arm in ("B", "C"):
        mcp = by_arm[arm]["mcp"]
        assert mcp["available"] and mcp["listed"] is True
        assert mcp["attempted"] == mcp["completed"] == 1
        assert mcp["delivered"] >= 1  # from the real server's own telemetry log

    evidence = {}
    for rec in second["records"]:
        attempt = sorted((tmp_path / "attempts").glob(f"{rec['trial_id']}__att*.json"))[-1]
        evidence[rec["arm"]] = json.loads(attempt.read_text())["runner_record"]
    shas = {arm: e["agent_instructions_sha256"] for arm, e in evidence.items()}
    assert shas["A"] == shas["B"] == protocol.sha256_text(protocol.ARMS["B"].instructions())
    assert shas["C"] == protocol.sha256_text(protocol.ARMS["C"].instructions())
    assert evidence["A"]["allowed_tools"] == []
    assert evidence["B"]["allowed_tools"] == evidence["C"]["allowed_tools"]
    assert sorted(evidence["B"]["allowed_tools"]) == sorted(manifest.mcp_tool_surface()["tools"])
    assert all(e["legacy_result"]["session_deleted"] is True for e in evidence.values())

    # 13: regenerate the analysis. Under amendment A1 these capability-equivalent trials are
    # eligible; the same trials evaluated under protocol 1.0.0 would all be excluded.
    once = analysis.run_preregistered_analysis(second["records"], 7, n_perm=99, n_boot=99)
    again = analysis.run_preregistered_analysis(second["records"], 7, n_perm=99, n_boot=99)
    assert json.dumps(once, sort_keys=True, default=str) == json.dumps(
        again, sort_keys=True, default=str
    )
    values = [records.analysis_value(r) for r in second["records"]]
    assert values == [(1.0, "scored")] * 3
    as_1_0_0 = [
        {**r, "violations": [{**v, "invalidating": True} for v in r["violations"]]}
        for r in second["records"]
    ]
    assert [records.analysis_value(r)[0] for r in as_1_0_0] == [None] * 3


@pytest.mark.parametrize(
    ("task", "files", "passed"),
    [
        ("R01", {"solution.R": R01_CORRECT}, True),
        ("R01", {"solution.R": R01_WRONG}, False),
        ("H01", {"solution.R": (HARD_CONTROLS / "reference.R").read_text()}, True),
        ("H01", {"solution.R": (HARD_CONTROLS / "wrong_filter_then_group.R").read_text()}, False),
    ],
)
def test_real_r_scorer_passes_correct_and_fails_incorrect_solutions(
    scripted, tmp_path, task, files, passed
):
    install, ctx = scripted
    spec = _spec(task)
    model = install({(spec["trial_id"], task): files})
    executor = legacy_executor.make_legacy_trial_executor(ctx, run_trial=model.run_trial)
    out = executor(spec, 1, tmp_path)
    record = out["runner_record"]
    score = record["score"]
    assert record["legacy_result"]["status"] in {"scored", "candidate_error"}
    assert score["total"] and isinstance(score["passed"], int)
    assert (score["passed"] == score["total"]) is passed
    stage2 = records.from_runner_result(
        {**spec, "block_id": "b", "execution_index": 1},
        record,
        out["telemetry_events"],
        runner.StudyExecutionConfig().expected_contract(spec["scorer_version"]),
    )
    assert stage2["outcome_kind"] in {"scored", "candidate_failure"}
    assert (stage2["score"] == 1.0) is passed
    assert (tmp_path / spec["trial_id"] / "artifacts" / "solution.R").read_text() == files[
        "solution.R"
    ]


def test_multidimensional_d01_keeps_the_canonical_scorer_result(scripted, tmp_path):
    install, ctx = scripted
    spec = _spec("D01")
    answer = json.dumps(live_runner.mock_gold_answer("D01"))
    model = install({(spec["trial_id"], "D01"): {"answer.json": answer}})
    out = legacy_executor.make_legacy_trial_executor(ctx, run_trial=model.run_trial)(
        spec, 1, tmp_path
    )
    raw = out["runner_record"]["score"]
    assert raw["scorer_version"] == "knowledge-pilot-v2.1"
    assert raw["passed"] is None and raw["total"] is None and raw["overall_score"] is None
    stage2 = records.from_runner_result(
        {**spec, "block_id": "b", "execution_index": 1},
        out["runner_record"],
        out["telemetry_events"],
        runner.StudyExecutionConfig().expected_contract(spec["scorer_version"]),
    )
    assert stage2["outcome_kind"] == "scoring_error" and stage2["score"] is None
    result = stage2["scorer_result"]
    assert result["primary_metric"] == "undefined_by_canonical_scorer"
    assert result["fully_correct"] == raw["fully_correct"]
    assert set(result["dimensions"]) == set(raw["dimensions"])


def test_live_calibration_runs_on_the_real_runner_with_a_mocked_model(scripted, tmp_path):
    install, ctx = scripted
    schedule = calibration_pipeline.build_calibration_schedule(tasks=["R01"], repetitions=2)
    model = install(
        {(t["trial_id"], "R01"): {"solution.R": R01_CORRECT} for t in schedule["trials"]}
    )
    executor = legacy_executor.make_legacy_trial_executor(ctx, run_trial=model.run_trial)
    original = legacy_executor.make_legacy_trial_executor
    try:
        legacy_executor.make_legacy_trial_executor = lambda _ctx: executor
        res = calibration_pipeline.execute_calibration(
            schedule,
            tmp_path,
            executor_mode="live",
            authorize_spend=True,
            spend_ceiling=CEILING,
            legacy_context=ctx,
        )
    finally:
        legacy_executor.make_legacy_trial_executor = original
    assert res["finalized_count"] == 2 and res["dataset_problems"] == []
    assert [r["score"] for r in res["records"]] == [1.0, 1.0]
    assert res["evidence_status"] == calibration_pipeline.EVIDENCE_SYNTHETIC  # mocked model
    expected = 2 * CEILING.price(USAGE["input_tokens"], USAGE["output_tokens"])
    assert res["spend"]["accounted_spend_usd"] == pytest.approx(expected)
    with pytest.raises(calibration_pipeline.SyntheticEvidenceError):
        calibration_pipeline.load_baseline_evidence(tmp_path / "trial_records.jsonl")
