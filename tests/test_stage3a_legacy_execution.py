"""Stage 3A: Stage 2 trials executed through the existing benchmark runner (offline tests).

``run_simple.run_trial`` is replaced by a recorder that returns legacy-shaped results, so these
tests run on every platform without Docker, credentials or a model. The real ``run_trial`` with
real Docker, MCP and R scorers is exercised in ``test_stage3a_end_to_end.py`` (Linux + Docker).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from benchmarks.codex_r import run_simple
from benchmarks.codex_r.studies.stage2_validity_v1 import (
    amendment,
    cli,
    design,
    legacy_executor,
    manifest,
    protocol,
    records,
    runner,
    scorer_bindings,
    spend_control,
)

MCP_TOOLS = manifest.mcp_tool_surface()["tools"]
CEILING = spend_control.SpendCeiling(1.0, 2.0, 8.0, 0.05)


def _ctx(study="study1", synthetic=True):
    return legacy_executor.LegacyExecutionContext(
        study=legacy_executor.STUDIES[study],
        effort="medium",
        timeout_seconds=120,
        images={"executor": "sha256:" + "e" * 64, "scorer": "sha256:" + "s" * 64},
        keys=("application-test-key", "executor-test-key"),
        synthetic=synthetic,
    )


def _plan(tasks=("R01",), reps=1, arms=("A", "B", "C")):
    return legacy_executor.pin_plan_identities(
        design.build_plan(list(tasks), arms, reps, 20261028, protocol.STUDY_ID)
    )


class FakeRunTrial:
    """Stands in for run_simple.run_trial: records its inputs, returns a legacy result."""

    def __init__(self, outcomes=None, interrupt=()):
        self.calls = []
        self.outcomes = outcomes or {}
        self.interrupt = set(interrupt)

    def __call__(self, args, task, mode, repetition, output, keys, images, *, planned_trial_id):
        self.calls.append(
            {
                "trial_id": planned_trial_id,
                "task": task,
                "mode": mode,
                "instructions": args.instructions,
                "override": args.mcp_tool_override,
                "scorer": args.knowledge_pilot_scorer,
                "output": Path(output),
                "keys": keys,
            }
        )
        legacy = {
            "run_id": args.run_id,
            "trial_id": planned_trial_id,
            "task": task,
            "mode": mode,
            "model": run_simple.MODEL,
            "effort": args.effort,
            "status": "scored",
            "score": {"status": "scored", "passed": 3, "total": 4, "fully_correct": False},
            "allowed_tools": list(args.mcp_tool_override[1]) if args.mcp_tool_override else [],
            "mcp_toolset": "consolidated" if mode == "with-mcp" else None,
            "session_creation_attempted": True,
            "session_instructions_sha256": hashlib.sha256(
                run_simple.instruction_text(args.instructions).encode()
            ).hexdigest(),
            "mcp_server_audit": (
                {"list_tools_requests": 1, "call_tool_requests": 0} if mode == "with-mcp" else None
            ),
            "usage": {"input_tokens": 1000, "output_tokens": 100},
            "usage_status": "observed",
            "cost": None,
            "cost_status": "unavailable",
            "interrupted": planned_trial_id in self.interrupt,
            # Fields run_trial records and amendment A1 checks.
            "started_at": datetime.now(UTC).isoformat(),
            "images": dict(images),
            "session_tool_types": ["mcp"] if mode == "with-mcp" else [],
        }
        legacy.update(self.outcomes.get(planned_trial_id, {}))
        if planned_trial_id in self.interrupt:
            self.interrupt.discard(planned_trial_id)
            legacy["status"] = "interrupted"
        # The real run_trial writes telemetry.jsonl into the output directory.
        events = [
            {"event_type": "agent.tool.started", "trial_id": planned_trial_id, "tool": tool}
            for tool in legacy.pop("_agent_tools", ["command_execution"])
        ]
        if mode == "with-mcp":
            events.append(
                {
                    "event_type": "mcp.discovery.completed",
                    "trial_id": planned_trial_id,
                    "source": "mcp_server",
                    "list_tools_requests": 1,
                }
            )
        with (Path(output) / "telemetry.jsonl").open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")
        return legacy


# ------------------------------------------------------------------- arms and the session


def test_arm_c_adds_only_the_preregistered_sentence_and_legacy_cli_is_unchanged():
    assert run_simple.MCP_ENCOURAGEMENT == protocol.ENCOURAGEMENT
    assert run_simple.instruction_text("standard") == protocol.ARMS["A"].instructions()
    assert run_simple.instruction_text("standard") == protocol.ARMS["B"].instructions()
    assert run_simple.instruction_text("mcp-encouraged") == protocol.ARMS["C"].instructions()
    # Study-only variant: not a legacy CLI choice (the R launcher mirrors these choices).
    assert set(run_simple.INSTRUCTION_VARIANTS) == {"standard", "diagnostic"}
    with pytest.raises(SystemExit):
        run_simple.main(["--effort", "medium", "--instructions", "mcp-encouraged"])


@pytest.mark.parametrize("arm", ["A", "B", "C"])
def test_session_request_per_arm_carries_the_arm_instructions_and_tools(arm):
    sent = {}

    def respond(request):
        body = json.loads(request.content)
        sent.update(body)
        return httpx.Response(
            200,
            json={
                "id": "sess_test",
                "agent": body["agent"],
                "environment": {
                    "type": "self_hosted",
                    "id": "env_test",
                    "remote_url": "https://api.openai.com/v1/agents/api",
                },
            },
        )

    mode, variant = legacy_executor.ARM_INVOCATION[arm]
    client = run_simple.SimpleClient("app-key", "exec-key", transport=httpx.MockTransport(respond))
    try:
        client.create_simple_session("medium", mode == "with-mcp", MCP_TOOLS, variant)
    finally:
        client.close()
    agent = sent["agent"]
    assert agent["instructions"] == protocol.ARMS[arm].instructions()
    assert client.sent_instructions_sha256 == protocol.sha256_text(agent["instructions"])
    if arm == "A":
        assert agent["tools"] == []
    else:
        assert agent["tools"][0]["allowed_tools"] == MCP_TOOLS
        assert agent["tools"][0]["required"] is True  # server connection, not a forced call


def test_executor_maps_arms_to_run_trial_inputs_in_plan_order(tmp_path):
    fake = FakeRunTrial()
    plan = _plan(("R01", "H01"))
    executor = legacy_executor.make_legacy_trial_executor(_ctx(), run_trial=fake)
    result = legacy_executor.execute_study(
        plan, tmp_path, _ctx(), spend_ceiling=None, executor=executor
    )
    assert result["dataset_problems"] == [] and result["finalized_count"] == 6
    order = [t["trial_id"] for t in sorted(plan["trials"], key=lambda t: t["execution_index"])]
    assert [c["trial_id"] for c in fake.calls] == order
    by_arm = {}
    for call in fake.calls:
        arm = call["trial_id"].rsplit("-", 1)[1]
        by_arm.setdefault(arm, []).append(call)
        # Fresh output directory per attempt, owned by the Stage 2 ledger.
        assert call["output"] == tmp_path / "workspaces" / f"{call['trial_id']}__att01"
    assert {c["mode"] for c in by_arm["A"]} == {"without-mcp"}
    assert {c["mode"] for c in by_arm["B"] + by_arm["C"]} == {"with-mcp"}
    assert {c["instructions"] for c in by_arm["A"] + by_arm["B"]} == {"standard"}
    assert {c["instructions"] for c in by_arm["C"]} == {"mcp-encouraged"}
    assert all(c["override"] is None for c in by_arm["A"])
    assert all(c["override"] == ("consolidated", tuple(MCP_TOOLS)) for c in by_arm["B"])
    assert [c["override"] for c in by_arm["B"]] == [c["override"] for c in by_arm["C"]]


def test_a1_records_keep_superseded_egress_codes_and_log_capabilities(tmp_path):
    fake = FakeRunTrial()
    plan = _plan(("R01",))
    executor = legacy_executor.make_legacy_trial_executor(_ctx(), run_trial=fake)
    result = legacy_executor.execute_study(
        plan, tmp_path, _ctx(), spend_ceiling=None, executor=executor
    )
    assert result["stopped_reason"] is None and result["finalized_count"] == 3
    saved = json.loads((tmp_path / "run_config.json").read_text(encoding="utf-8"))
    assert saved["protocol_amendment"] == "A1"
    for rec in result["records"]:
        assert records.validate_record(rec) == []
        assert rec["protocol_version"] == "1.1.0+A1"
        # 1.0.0 egress codes are still recorded, with their detail, but superseded by A1.
        superseded = {v["code"]: v for v in rec["violations"] if v.get("superseded_by")}
        assert set(superseded) == set(amendment.SUPERSEDED_VIOLATIONS)
        assert all(v["invalidating"] is False for v in superseded.values())
        assert not [v for v in rec["violations"] if v["invalidating"]]
        assert records.analysis_value(rec) == (0.75, "scored")
        cap = rec["capability"]
        assert cap["non_mcp_tools"] == [] and cap["web_access_policy"] == "none"
        assert cap["executor_image"] == _ctx().images["executor"]
        assert cap["scorer_isolation"]["exposed_files"] == []
        assert cap["mcp_tools"] == ([] if rec["arm"] == "A" else MCP_TOOLS)
        tools = rec["agent_tools"]
        assert tools["study_configuration"] == "study1_mcp_vs_model_knowledge"
        assert tools["available"]["web_access"] is False
        assert tools["available"]["r_knowledge_mcp"] is (rec["arm"] != "A")
        assert tools["used"] == {"command_execution": 1}
    by_arm = {r["arm"]: r for r in result["records"]}
    assert by_arm["A"]["mcp"]["available"] is False and by_arm["B"]["mcp"]["listed"] is True


def test_study1_records_web_access_use_as_a_capability_finding(tmp_path):
    plan = _plan(("R01",), arms=("A", "B"))
    first = sorted(plan["trials"], key=lambda t: t["execution_index"])[0]["trial_id"]
    fake = FakeRunTrial({first: {"_agent_tools": ["command_execution", "web_search_call"]}})
    executor = legacy_executor.make_legacy_trial_executor(_ctx(), run_trial=fake)
    result = legacy_executor.execute_study(
        plan, tmp_path, _ctx(), spend_ceiling=None, executor=executor
    )
    rec = next(r for r in result["records"] if r["trial_id"] == first)
    assert rec["agent_tools"]["web_access_calls"] == 1
    assert rec["agent_tools"]["findings"]


# ------------------------------------------------------------------------- outcomes


@pytest.mark.parametrize(
    ("legacy", "kind", "origin"),
    [
        ({"status": "scored"}, "scored", None),
        (
            {"status": "candidate_error", "score": {"status": "candidate_error", "reason": "x"}},
            "candidate_failure",
            "candidate",
        ),
        (
            {"status": "candidate_timeout", "score": {"status": "candidate_timeout"}},
            "candidate_failure",
            "candidate",
        ),
        (
            {"status": "error", "error_type": "TimeoutError", "score": None},
            "candidate_failure",
            "candidate",
        ),
        (
            {
                "status": "unsupported_for_automatic_scoring",
                "score": {"status": "unsupported_for_automatic_scoring"},
            },
            "scoring_error",
            "scorer",
        ),
        (
            {"status": "scoring_error", "score": {"status": "scoring_error"}},
            "scoring_error",
            "scorer",
        ),
        (
            {
                "status": "error",
                "error_type": "RuntimeError",
                "turn_failure": "turn_failed",
                "score": None,
            },
            "infrastructure_failure",
            "runner",
        ),
        ({"status": "cleanup_error", "score": None}, "infrastructure_failure", "runner"),
    ],
)
def test_legacy_outcomes_are_classified_without_inventing_scores(legacy, kind, origin):
    spec = runner.build_trial_invocation_spec(
        _plan(("R01",), arms=("A", "B"))["trials"][0], runner.StudyExecutionConfig()
    )
    base = {
        "mode": "without-mcp",
        "model": run_simple.MODEL,
        "effort": "medium",
        "score": {"status": "scored", "passed": 4, "total": 4, "fully_correct": True},
        "allowed_tools": [],
        "usage_status": "unavailable",
    }
    measured = runner._task_and_scorer_meta("R01")
    record = legacy_executor.translate(
        spec, {**base, **legacy}, measured, legacy_executor.STUDIES["study1"], []
    )
    assert (record["error_summary"]["primary_error"] or {}).get("origin") == origin
    expected = runner.StudyExecutionConfig().expected_contract(spec["scorer_version"])
    planned = {**_plan(("R01",), arms=("A", "B"))["trials"][0]}
    stage2 = records.from_runner_result(planned, record, [], expected)
    assert stage2["outcome_kind"] == kind
    if kind == "candidate_failure":
        assert stage2["score"] == 0.0
    elif kind != "scored":
        assert stage2["score"] is None


def test_multidimensional_canonical_result_is_preserved_not_aggregated():
    """knowledge-pilot-v2.1 reports dimensions and fully_correct but no passed/total."""
    planned = _plan(("D01",), arms=("A", "B"))["trials"][0]
    v21 = {
        "status": "scored",
        "scorer_version": "knowledge-pilot-v2.1",
        "passed": None,
        "total": None,
        "fully_correct": None,  # abstention: an unknown claim, never counted as true or false
        "overall_score": None,
        "dimensions": {
            "schema_validity": {"status": "passed", "passed": 1, "total": 1},
            "factual_correctness": {"status": "passed", "passed": 3, "total": 3},
        },
    }
    rec = records.from_runner_result(
        planned,
        {"status": "scored", "score": v21, "model": "m", "effort": "e"},
        [],
        runner.StudyExecutionConfig().expected_contract("knowledge-pilot-v2.1"),
    )
    # The former Stage 2.7 rule would have summed dimensions to 4/4 = "fully correct".
    assert rec["outcome_kind"] == "scoring_error" and rec["score"] is None
    assert rec["checks_passed"] is None and rec["checks_total"] is None
    result = rec["scorer_result"]
    assert result["primary_metric"] == "undefined_by_canonical_scorer"
    assert result["fully_correct"] is None
    assert result["dimensions"]["factual_correctness"] == {
        "status": "passed",
        "passed": 3,
        "total": 3,
    }
    assert records.validate_record(rec) == []


# ---------------------------------------------------------------- scorer identity


def test_scorer_bindings_pin_the_scorer_that_actually_executes():
    r01 = scorer_bindings.bind("R01", "legacy")
    d01 = scorer_bindings.bind("D01", "knowledge-pilot-v2.1")
    b01 = scorer_bindings.bind("B01", "knowledge-pilot-v2.1")
    assert (r01.scorer_version, r01.label_executable) == ("legacy", True)
    assert (d01.scorer_version, d01.multidimensional) == ("knowledge-pilot-v2.1", True)
    # v2.1 cannot score B01; the binding says so instead of hashing a module that never runs.
    assert (b01.scorer_version, b01.label_executable) == ("legacy", False)
    assert runner._task_and_scorer_meta("B01")["scorer_sha256"] == b01.digest()
    assert runner._task_and_scorer_meta("B01")["catalogue_scorer_label"] == "knowledge-pilot-v2.1"
    with pytest.raises(ValueError):
        scorer_bindings.bind("R01", "hard-v1")


def test_pinning_keeps_the_assignment_and_detects_drift(tmp_path, monkeypatch):
    raw = design.build_plan(["R01", "H01"], ("A", "B", "C"), 2, 20261028, protocol.STUDY_ID)
    pinned = legacy_executor.pin_plan_identities(raw)
    keep = ("trial_id", "block_id", "task", "arm", "repetition", "execution_index", "trial_seed")
    assert [{k: t[k] for k in keep} for t in raw["trials"]] == [
        {k: t[k] for k in keep} for t in pinned["trials"]
    ]
    assert design.verify_plan(pinned) == []
    assert legacy_executor.plan_identity_problems(raw)  # unpinned
    assert legacy_executor.plan_identity_problems(pinned) == []
    stale = json.loads(json.dumps(pinned))
    stale["trials"][0]["scorer_sha256"] = "f" * 64
    stale["plan_sha256"] = design.plan_digest(stale)
    with pytest.raises(ValueError, match="drifted"):
        legacy_executor.execute_study(stale, tmp_path / "run", _ctx(), spend_ceiling=None)
    assert not (tmp_path / "run").exists()


def test_files_changed_after_planning_are_refused_before_any_session(tmp_path, monkeypatch):
    fake = FakeRunTrial()
    plan = _plan(("R01",), arms=("A", "B"))
    original = runner._task_and_scorer_meta
    monkeypatch.setattr(
        runner,
        "_task_and_scorer_meta",
        lambda task: {**original(task), "task_sha256": "0" * 64},
    )
    executor = legacy_executor.make_legacy_trial_executor(_ctx(), run_trial=fake)
    spec = runner.build_trial_invocation_spec(plan["trials"][0], runner.StudyExecutionConfig())
    (tmp_path / "w").mkdir()
    out = executor(spec, 1, tmp_path / "w")["runner_record"]
    assert out["error_summary"]["primary_error"]["source_code"] == "task_or_scorer_hash_mismatch"
    assert fake.calls == []


# ------------------------------------------------------------ resume, retry, budget


def test_interruption_resume_retry_and_duplicates_through_the_ledger(tmp_path):
    plan = _plan(("R01",))
    ordered = [t["trial_id"] for t in sorted(plan["trials"], key=lambda t: t["execution_index"])]
    fake = FakeRunTrial(
        outcomes={ordered[2]: {"status": "error", "error_type": "RuntimeError", "score": None}},
        interrupt={ordered[1]},
    )
    executor = legacy_executor.make_legacy_trial_executor(_ctx(), run_trial=fake)
    first = legacy_executor.execute_study(
        plan, tmp_path, _ctx(), spend_ceiling=CEILING, executor=executor
    )
    assert first["interrupted"] is True and first["finalized_count"] == 1

    second = legacy_executor.execute_study(
        plan, tmp_path, _ctx(), spend_ceiling=CEILING, executor=executor
    )
    assert second["finalized_count"] == 3 and second["dataset_problems"] == []
    attempts = [c["output"].name for c in fake.calls]
    # Completed trial never replayed; interrupted trial resumed as attempt 2; the infrastructure
    # failure retried once (attempts 1 and 2) and then committed.
    assert attempts == [
        f"{ordered[0]}__att01",
        f"{ordered[1]}__att01",
        f"{ordered[1]}__att02",
        f"{ordered[2]}__att01",
        f"{ordered[2]}__att02",
    ]
    assert second["spend"]["reserve_charged_for_interrupted_attempts"] == [f"{ordered[1]}__att01"]

    path = tmp_path / "trial_records.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines + [lines[0]]) + "\n", encoding="utf-8")
    calls_before = len(fake.calls)
    third = legacy_executor.execute_study(
        plan, tmp_path, _ctx(), spend_ceiling=CEILING, executor=executor
    )
    assert len(fake.calls) == calls_before and third["finalized_count"] == 3
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_spend_ceiling_stops_before_the_next_session_and_binds_the_run(tmp_path):
    fake = FakeRunTrial()
    plan = _plan(("R01",))
    executor = legacy_executor.make_legacy_trial_executor(_ctx(), run_trial=fake)
    # 1000 in / 100 out at 2/8 USD per Mtok = 0.0028 USD per trial; reserve 0.01; ceiling 0.015.
    tight = spend_control.SpendCeiling(0.015, 2.0, 8.0, 0.01)
    res = legacy_executor.execute_study(
        plan, tmp_path, _ctx(), spend_ceiling=tight, executor=executor
    )
    assert [r["outcome_kind"] for r in res["records"]] == ["scored", "scored", "not_executed"]
    assert len(fake.calls) == 2 and res["stopped_reason"] == spend_control.STOP_CEILING_REACHED
    with pytest.raises(ValueError, match="differs"):
        legacy_executor.execute_study(
            plan, tmp_path, _ctx(), spend_ceiling=CEILING, executor=executor
        )


def test_a_real_context_requires_a_ceiling_and_study2_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="spend ceiling"):
        legacy_executor.execute_study(_plan(), tmp_path, _ctx(synthetic=False), spend_ceiling=None)
    with pytest.raises(legacy_executor.StudyUnsupported):
        legacy_executor.study_configuration("study2")
    with pytest.raises(legacy_executor.StudyUnsupported):
        legacy_executor.make_legacy_trial_executor(_ctx("study2"))
    with pytest.raises(legacy_executor.StudyUnsupported):
        legacy_executor.execute_study(_plan(), tmp_path, _ctx("study2"), spend_ceiling=CEILING)
    assert not any(tmp_path.iterdir())


def test_preflight_refuses_without_touching_docker_or_reporting_key_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear")
    monkeypatch.delenv("OPENAI_EXECUTOR_API_KEY", raising=False)

    def no_docker(*_a, **_k):
        raise AssertionError("docker must not run")

    monkeypatch.setattr(run_simple, "docker", no_docker)
    with pytest.raises(legacy_executor.LegacyRunnerUnavailable) as exc:
        legacy_executor.preflight(
            ["R01"],
            study=legacy_executor.STUDIES["study1"],
            effort="medium",
            timeout_seconds=900,
            need_mcp=True,
        )
    text = " ".join(exc.value.reasons)
    assert "OPENAI_EXECUTOR_API_KEY" in text and "sk-should-never-appear" not in text


def test_cli_execute_study_refuses_unsupported_unauthorized_and_unpinned(tmp_path, capsys):
    raw = tmp_path / "raw.json"
    assert (
        cli.main(["plan", "--tasks", "R01", "--reps", "1", "--seed", "3", "--out", str(raw)]) == 0
    )
    pinned = tmp_path / "pinned.json"
    assert (
        cli.main(
            ["plan", "--tasks", "R01", "--reps", "1", "--seed", "3", "--out", str(pinned), "--pin"]
        )
        == 0
    )
    ceiling = [
        "--max-spend-usd",
        "1",
        "--input-usd-per-mtok",
        "2",
        "--output-usd-per-mtok",
        "8",
        "--per-trial-reserve-usd",
        "0.05",
    ]
    out = ["--out-dir", str(tmp_path / "run")]
    assert cli.main(["execute-study", "--study", "study2", "--plan", str(pinned), *out]) == 2
    assert cli.main(["execute-study", "--study", "study1", "--plan", str(pinned), *out]) == 2
    assert (
        cli.main(["execute-study", "--study", "study1", "--plan", str(pinned), *out, *ceiling]) == 2
    )
    assert (
        cli.main(
            [
                "execute-study",
                "--study",
                "study1",
                "--plan",
                str(raw),
                *out,
                "--authorize-spend",
                *ceiling,
            ]
        )
        == 2
    )
    assert "not pinned" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()
