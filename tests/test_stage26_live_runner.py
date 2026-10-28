"""Stage 2.6: live Docker isolation, A/B/C execution adapter, recovery and fail-closed behaviour.

Offline tests (no Docker, no network) cover policy parsing, probe design, record mapping, retry
classification and fail-closed refusal. The ``docker``-marked tests build real containers and
networks with a local mock model; they skip with an explicit reason when Docker or the local
images are unavailable and never substitute synthetic evidence for live evidence.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from benchmarks.codex_r.studies.stage2_validity_v1 import (
    design,
    live_network,
    live_runner,
    manifest,
    protocol,
    records,
    runner,
    study_configs,
)

GATEWAY_PATH = live_network.ASSETS / "arm_gateway.py"
SENTINEL = "sk-stage26-host-sentinel-0123456789"


def _load_gateway():
    spec = importlib.util.spec_from_file_location("arm_gateway_under_test", GATEWAY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ offline: gateway policy


@pytest.mark.parametrize(
    "raw",
    [None, "", "{not json", "[]", '{"allow": {}}', '{"allow": {"1.2.3.4:443": "a:1"}}'],
)
def test_gateway_refuses_to_start_without_a_valid_policy(raw):
    gateway = _load_gateway()
    with pytest.raises(gateway.PolicyError):
        gateway.load_policy(raw)


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("GET http://example.com/ HTTP/1.1", "connect_only"),
        ("CONNECT example.com:443 HTTP/1.1", "authority_not_allowed"),
        ("CONNECT api.openai.com:444 HTTP/1.1", "authority_not_allowed"),
        ("CONNECT 1.1.1.1:443 HTTP/1.1", "ip_literal_denied"),
        ("CONNECT model-upstream:8443 HTTP/1.1", "authority_not_allowed"),
        ("CONNECT r-knowledge-mcp:8000 HTTP/1.1", "authority_not_allowed"),
        ("CONNECT api.openai.com:443@evil.test:443 HTTP/1.1", "invalid_authority"),
        ("CONNECT api.openai.com HTTP/1.1", "invalid_authority"),
        ("CONNECT api.openai.com:443", "malformed_request"),
    ],
)
def test_gateway_denies_everything_outside_the_exact_allow_list(line, reason):
    gateway = _load_gateway()
    policy = gateway.load_policy(
        json.dumps({"allow": {"api.openai.com:443": "model-upstream:8443"}})
    )
    with pytest.raises(gateway.Denied, match=reason):
        gateway.decide(line, policy)


def test_gateway_maps_the_allowed_authority_to_a_fixed_upstream_not_the_client_choice():
    gateway = _load_gateway()
    policy = gateway.load_policy(
        json.dumps({"allow": {"API.OpenAI.com.:443": "model-upstream:8443"}})
    )
    authority, upstream = gateway.decide("CONNECT api.openai.com:443 HTTP/1.1", policy)
    assert authority == "api.openai.com:443" and upstream == ("model-upstream", 8443)


# ------------------------------------------------------------------ offline: probe design


def test_canary_probes_differ_between_arms_only_in_mcp_reachability():
    a, b, c = (live_network.canary_probes(x) for x in "ABC")
    assert b == c
    assert [p["id"] for p in a] == [p["id"] for p in b]
    assert len({p["id"] for p in a}) == len(a)
    differing = [x["id"] for x, y in zip(a, b, strict=True) if x != y]
    assert differing == ["mcp_direct"]
    assert next(p for p in a if p["id"] == "mcp_direct")["expect"] == "denied"
    assert next(p for p in b if p["id"] == "mcp_direct")["expect"] == "allowed"
    # MCP must never be reachable through the model gateway, in any arm.
    for probes in (a, b, c):
        assert next(p for p in probes if p["id"] == "proxy_mcp_via_gateway")["expect"] == "denied"


def test_canary_covers_dns_direct_ip_metadata_and_gateway_bypass_paths():
    ids = {p["id"] for p in live_network.canary_probes("A")}
    for needed in (
        "direct_public_ip_443",
        "direct_metadata_ip",
        "direct_docker_host_bridge",
        "direct_model_upstream",
        "dns_example_com",
        "proxy_ip_literal",
        "proxy_userinfo_smuggling",
        "proxy_plain_get",
        "model_via_gateway",
    ):
        assert needed in ids


# ------------------------------------------------------------------ offline: fail closed


def test_docker_status_reports_unavailable_instead_of_raising(monkeypatch):
    def boom(*_a, **_k):
        raise live_network.DockerUnavailable("docker CLI not found")

    monkeypatch.setattr(live_network, "docker", boom)
    status = live_network.docker_status()
    assert status["available"] is False and status["ready"] is False and status["reason"]


def test_live_study_refuses_to_run_and_writes_nothing_when_docker_is_not_ready(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        live_network,
        "docker_status",
        lambda *_a, **_k: {"available": False, "ready": False, "reason": "no engine"},
    )
    plan = design.build_plan(["D01"], ("A", "B", "C"), 1, seed=1, study_id=protocol.STUDY_ID)
    with pytest.raises(live_network.DockerUnavailable, match="no engine"):
        live_runner.execute_live_study(plan, runner.StudyExecutionConfig(), tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_unknown_fault_or_arm_is_rejected():
    with pytest.raises(ValueError):
        live_network.TrialTopology("D")
    with pytest.raises(ValueError):
        live_network.TrialTopology("A", fault="nope")


def _spec(arm="B", task="D01", **changes):
    plan = design.build_plan([task], ("A", "B", "C"), 1, seed=5, study_id=protocol.STUDY_ID)
    planned = next(t for t in plan["trials"] if t["arm"] == arm)
    spec = runner.build_trial_invocation_spec(planned, runner.StudyExecutionConfig())
    spec.update(changes)
    return planned, spec


def test_hash_mismatch_is_detected_before_any_container_is_created(monkeypatch, tmp_path):
    def forbidden(*_a, **_k):
        raise AssertionError("no container may be created for a hash mismatch")

    monkeypatch.setattr(live_network, "TrialTopology", forbidden)
    planned, spec = _spec(task_sha256="0" * 64)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out = live_runner.make_docker_trial_executor()(spec, 1, workspace)
    record = out["runner_record"]
    assert record["error_summary"]["primary_error"]["source_code"] == "task_or_scorer_hash_mismatch"
    stage2 = records.from_runner_result(
        planned,
        record,
        out["telemetry_events"],
        runner.StudyExecutionConfig().expected_contract(spec["scorer_version"]),
    )
    assert stage2["outcome_kind"] == "infrastructure_failure" and stage2["score"] is None


def test_non_empty_workspace_is_rejected_so_sessions_cannot_share_state(monkeypatch, tmp_path):
    monkeypatch.setattr(live_network, "TrialTopology", lambda *a, **k: 1 / 0)
    _planned, spec = _spec()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "left_over.txt").write_text("previous trial", encoding="utf-8")
    out = live_runner.make_docker_trial_executor()(spec, 1, workspace)
    assert out["runner_record"]["error_summary"]["primary_error"]["source_code"] == (
        "workspace_not_fresh"
    )


# ------------------------------------------------------------- offline: classification


def _expected(spec):
    return runner.StudyExecutionConfig().expected_contract(spec["scorer_version"])


def test_isolation_failure_is_an_infrastructure_failure_with_an_invalidating_violation():
    planned, spec = _spec("A")
    record = live_runner._error_record(
        spec, origin="runner", category="isolation", code="isolation_enforcement_failed", live={}
    )
    stage2 = records.from_runner_result(planned, record, [], _expected(spec))
    assert stage2["outcome_kind"] == "infrastructure_failure"
    assert stage2["score"] is None
    codes = {v["code"]: v["invalidating"] for v in stage2["violations"]}
    assert codes.get("egress_not_restricted") is True


def test_candidate_timeout_is_scored_zero_and_never_an_infrastructure_retry():
    planned, spec = _spec("B")
    record = live_runner._error_record(
        spec,
        origin="candidate",
        category="timeout",
        code="candidate_timeout",
        live={},
        network_internal=True,
        egress=[protocol.MODEL_ENDPOINT, protocol.MCP_ENDPOINT],
    )
    stage2 = records.from_runner_result(planned, record, [], _expected(spec))
    assert stage2["outcome_kind"] == "candidate_failure" and stage2["score"] == 0.0


def test_events_projection_yields_a_consistent_telemetry_summary():
    report = {
        "mcp": {
            "ok": True,
            "calls": [{"call_id": "client-call-1", "tool": "validate_r_prompt", "is_error": False}],
        }
    }
    server = [
        {
            "protocol_call_id": "3",
            "tool_name": "validate_r_prompt",
            "status": "ok",
            "response_bytes": 10,
        }
    ]
    from benchmarks.codex_r.studies.stage2_validity_v1 import telemetry

    summary = telemetry.summarize_trace(
        live_runner._events(report, server, listed=True), available=True
    )
    assert (summary["listed"], summary["attempted"], summary["completed"]) == (True, 1, 1)
    assert summary["delivered"] == 1 and summary["correlation"] == "ordinal_unconfirmed"
    assert summary["client_server_count_mismatch"] is False


def test_egress_projection_flags_breaches_and_unreadable_logs():
    allowed = {"event": "connect", "result": "allowed", "authority": live_network.MODEL_AUTHORITY}
    denied = {"event": "connect", "result": "denied", "authority": "example.com:443"}
    canary = {"probes": [], "breaches": []}
    assert live_runner._egress([allowed, denied], canary, None) == [protocol.MODEL_ENDPOINT]
    assert live_runner._egress([], canary, None) is None
    assert "breach:mcp_direct" in live_runner._egress(
        [allowed], {"probes": [], "breaches": ["mcp_direct"]}, None
    )


def test_arm_instructions_and_tool_surface_in_the_live_spec():
    specs = {arm: _spec(arm)[1] for arm in "ABC"}
    assert specs["A"]["instructions"] == specs["B"]["instructions"]
    assert specs["A"]["instructions_sha256"] == specs["B"]["instructions_sha256"]
    assert specs["C"]["instructions"] == specs["B"]["instructions"] + protocol.ENCOURAGEMENT
    assert specs["A"]["allowed_tools"] == [] and specs["A"]["mcp_container_started"] is False
    assert specs["B"]["allowed_tools"] == specs["C"]["allowed_tools"] != []
    assert len({s["session_isolation_id"] for s in specs.values()}) == 3


def test_confirmatory_minimum_has_one_source_of_truth_in_the_manifest():
    declared = manifest.build_manifest()["confirmatory_task_rule"]["minimum_tasks"]
    assert study_configs.MINIMUM_CONFIRMATORY_S1_TASKS == declared
    specs = study_configs.build_study_specifications()
    assert specs["minimum_confirmatory_s1_tasks"] == declared
    assert specs["current_eligible_s1_task_count"] == 0 and specs["confirmatory_ready"] is False


def test_legacy_runner_is_untouched_and_still_reports_its_plain_bridge():
    from benchmarks.codex_r.studies.stage2_validity_v1 import isolation

    audit = isolation.inspect_legacy_runner_isolation()
    assert audit["creates_plain_docker_bridge"] is True
    assert audit["live_egress_isolation_enforced"] is False


# ------------------------------------------------------------------------ live Docker

_STATUS = None


def _status():
    global _STATUS
    if _STATUS is None:
        _STATUS = live_network.docker_status()
    return _STATUS


@pytest.fixture
def live(monkeypatch):
    status = _status()
    if not status["ready"]:
        pytest.skip(f"live Docker verification unavailable: {status['reason']}")
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    monkeypatch.setenv("GITHUB_TOKEN", SENTINEL)
    return status


def _workload_spec(arm, call=True):
    return {
        "instructions": "x",
        "mcp_expected": arm != "A",
        "call_tool": call and arm != "A",
        "tool_call": live_runner.MOCK_TOOL_CALL,
        "answer": {"ok": True},
    }


@pytest.mark.docker
@pytest.mark.parametrize("arm", ["A", "B", "C"])
def test_live_topology_enforces_arm_isolation_and_delivers_model_and_mcp(live, arm, tmp_path):
    expected_tools = list(manifest.mcp_tool_surface()["tools"])
    topo = live_network.TrialTopology(arm, trial_id=f"t-{arm}", run_label=f"s26t-{os.getpid()}")
    try:
        topo.start()
        enforcement = topo.verify_enforcement()
        assert enforcement["ok"], enforcement["problems"]
        assert enforcement["internal_flag"] is True
        canary = topo.run_canary()
        assert canary["complete"] and canary["ok"], (canary["breaches"], canary["probe_errors"])
        by_id = {p["id"]: p for p in canary["probes"]}
        assert by_id["mcp_direct"]["outcome"] == ("allowed" if arm != "A" else "denied")
        assert by_id["model_via_gateway"]["outcome"] == "allowed"
        for probe_id in (
            "direct_public_ip_443",
            "dns_example_com",
            "proxy_cran",
            "proxy_mcp_via_gateway",
        ):
            assert by_id[probe_id]["outcome"] == "denied", probe_id
        hardening = canary["inspect"]
        assert hardening["networks"] == [topo.net_int]
        assert hardening["privileged"] is False and hardening["cap_drop"] == ["ALL"]
        assert hardening["read_only_rootfs"] is True and hardening["user"] == "65534:65534"
        assert not set(hardening["env_names"]) & live_network.HOST_SECRET_NAMES

        workspace = tmp_path / "ws"
        workspace.mkdir()
        result = topo.run_workload(_workload_spec(arm), workspace, 120)
        report = result["report"]
        assert result["exit_code"] == 0 and "agent_error" not in report, report
        assert report["workspace_entries_at_start"] == []
        assert report["model"]["ok"] is True and report["model"]["usage"]["output_tokens"] == 42
        assert (workspace / "answer.json").is_file()
        if arm == "A":
            assert "mcp" not in report
        else:
            assert report["mcp"]["tools"] == expected_tools
            assert report["mcp"]["calls"][0]["is_error"] is False
        # The candidate holds only the per-trial synthetic key; host secrets never arrive.
        assert set(report["env_names"]) & live_network.HOST_SECRET_NAMES == {"CODEX_API_KEY"}
        assert result["inspect"]["networks"] == [topo.net_int]

        logs = topo.collect_logs()
        assert all(r["auth_ok"] for r in logs["model_events"] if r.get("event") == "model_request")
        denied = [e for e in logs["gateway_events"] if e.get("result") == "denied"]
        assert len(denied) >= 10
        allowed = {e["authority"] for e in logs["gateway_events"] if e.get("result") == "allowed"}
        assert allowed == {live_network.MODEL_AUTHORITY}
        assert (len(logs["mcp_telemetry"]) == 1) is (arm != "A")
        assert SENTINEL not in logs["raw_text"] and topo.token not in logs["raw_text"]
    finally:
        leftovers = topo.teardown()
    assert leftovers == {"containers": [], "networks": []}


@pytest.mark.docker
def test_live_arm_a_cannot_reach_a_concurrent_arm_b_mcp_server(live, tmp_path):
    label = f"s26x-{os.getpid()}"
    topo_b = live_network.TrialTopology("B", trial_id="x-B", run_label=label)
    topo_a = live_network.TrialTopology("A", trial_id="x-A", run_label=label)
    try:
        topo_b.start()
        topo_a.start()
        mcp_ip = topo_b.container_ip(topo_b.c_mcp, topo_b.net_int)
        gw_ip = topo_b.container_ip(topo_b.c_gateway, topo_b.net_int)
        probes = [
            {"id": "b_mcp_ip", "kind": "tcp", "target": f"{mcp_ip}:8000", "expect": "denied"},
            {
                "id": "b_mcp_name",
                "kind": "tcp",
                "target": f"{topo_b.c_mcp}:8000",
                "expect": "denied",
            },
            {"id": "b_gateway_ip", "kind": "tcp", "target": f"{gw_ip}:3128", "expect": "denied"},
            {
                "id": "own_mcp_alias",
                "kind": "tcp",
                "target": "r-knowledge-mcp:8000",
                "expect": "denied",
            },
        ]
        result = topo_a._run_agent(
            "cross",
            {"mode": "canary", "probes": probes},
            workspace=None,
            with_token=False,
            timeout=90,
        )
        outcomes = {p["id"]: p["outcome"] for p in result["report"]["probes"]}
        assert outcomes == dict.fromkeys(
            ("b_mcp_ip", "b_mcp_name", "b_gateway_ip", "own_mcp_alias"), "denied"
        )
    finally:
        left = [topo_a.teardown(), topo_b.teardown()]
    assert all(x == {"containers": [], "networks": []} for x in left)


@pytest.mark.docker
def test_live_misconfigurations_are_detected_and_fail_closed(live):
    label = f"s26f-{os.getpid()}"
    # 1. Invalid gateway policy: the gateway refuses to start, so the topology cannot start.
    broken = live_network.TrialTopology(
        "B", trial_id="f1", run_label=label, fault="gateway_policy_invalid"
    )
    with pytest.raises(live_network.IsolationEnforcementError, match="policy_unparseable|exited"):
        with broken:
            pytest.fail("topology must not start with an invalid gateway policy")
    assert live_network.list_resources(topology=broken.topology_id) == {
        "containers": [],
        "networks": [],
    }
    # 2. Candidate also attached to the upstream network: structure may look plausible, but the
    #    behavioural canary reaches the model upstream directly and reports a breach.
    leaky = live_network.TrialTopology(
        "A", trial_id="f2", run_label=label, fault="candidate_on_upstream_network"
    )
    # 3. An MCP container started in Arm A is a control-arm leak.
    mcp_leak = live_network.TrialTopology("A", trial_id="f3", run_label=label, fault="mcp_in_arm_a")
    try:
        leaky.start()
        canary = leaky.run_canary()
        assert canary["ok"] is False and "direct_model_upstream" in canary["breaches"]
        mcp_leak.start()
        assert mcp_leak.verify_enforcement()["ok"] is False
        leak_canary = mcp_leak.run_canary()
        assert leak_canary["ok"] is False and "mcp_direct" in leak_canary["breaches"]
    finally:
        assert leaky.teardown() == {"containers": [], "networks": []}
        assert mcp_leak.teardown() == {"containers": [], "networks": []}


class _Capture:
    def __init__(self, inner):
        self.inner, self.outputs = inner, []

    def __call__(self, spec, attempt_index, workspace_dir):
        out = self.inner(spec, attempt_index, workspace_dir)
        self.outputs.append((spec, attempt_index, out))
        return out


def _config(**changes):
    values = {
        "stage": "live_smoke_mock_model",
        "timeout_seconds": 120,
        "max_infra_retries": 0,
        "stop_on_invalidating_violation": False,
        "synthetic": True,
    }
    values.update(changes)
    return runner.StudyExecutionConfig(**values)


@pytest.mark.docker
def test_live_three_arm_plan_produces_valid_records_telemetry_and_clean_docker(live, tmp_path):
    plan = design.build_plan(["D01"], ("A", "B", "C"), 1, seed=20261028, study_id=protocol.STUDY_ID)
    label = f"s26p-{os.getpid()}"
    settings = live_runner.LiveExecutorSettings(run_label=label)
    capture = _Capture(live_runner.make_docker_trial_executor(settings))
    result = live_runner.execute_live_study(
        plan, _config(), tmp_path / "run", settings, executor=capture
    )
    assert result["dataset_problems"] == [] and result["finalized_count"] == 3
    by_arm = {r["arm"]: r for r in result["records"]}
    assert all(r["outcome_kind"] == "scored" and r["score"] == 1.0 for r in by_arm.values())
    assert all(r["violations"] == [] and r["synthetic"] is True for r in by_arm.values())
    assert by_arm["A"]["mcp"]["available"] is False and by_arm["A"]["mcp"]["attempted"] == 0
    assert by_arm["C"]["mcp"]["attempted"] == 1 == by_arm["C"]["mcp"]["delivered"]
    assert by_arm["B"]["mcp"]["listed"] is True and by_arm["B"]["mcp"]["available"] is True
    assert result["resource_cleanup"]["remaining_after"] == {"containers": [], "networks": []}

    evidence = {s["arm"]: o["runner_record"] for s, _i, o in capture.outputs}
    shas = {arm: rec["agent_instructions_sha256"] for arm, rec in evidence.items()}
    assert shas["A"] == shas["B"] != shas["C"]  # measured inside the candidate, not just planned
    assert evidence["A"]["allowed_tools"] == []
    assert evidence["B"]["allowed_tools"] == evidence["C"]["allowed_tools"]
    for rec in evidence.values():
        live_evidence = rec["live_evidence"]
        assert live_evidence["enforcement"]["ok"] is True
        assert live_evidence["canary"]["ok"] is True
        assert live_evidence["host_secret_names_in_candidate"] == []
        assert live_evidence["cleanup_leftovers"] == {"containers": [], "networks": []}
    # Fresh session per trial: three distinct topologies and isolation ids.
    assert len({r["live_evidence"]["topology_id"] for r in evidence.values()}) == 3
    # The persisted ledger holds exactly one valid record per planned trial.
    lines = (tmp_path / "run" / "trial_records.jsonl").read_text(encoding="utf-8").splitlines()
    assert (
        len(lines) == 3
        and records.validate_dataset(
            [json.loads(x) for x in lines], [t["trial_id"] for t in plan["trials"]]
        )
        == []
    )


@pytest.mark.docker
def test_live_interruption_mid_trial_cleans_up_then_resumes_without_rerunning(live, tmp_path):
    plan = design.build_plan(["D01"], ("A", "B", "C"), 1, seed=77, study_id=protocol.STUDY_ID)
    ordered = sorted(plan["trials"], key=lambda t: t["execution_index"])
    second = ordered[1]["trial_id"]
    label = f"s26i-{os.getpid()}"
    settings = live_runner.LiveExecutorSettings(run_label=label)
    run_dir = tmp_path / "run"
    cfg = _config(max_infra_retries=1)

    first = live_runner.execute_live_study(
        plan,
        cfg,
        run_dir,
        settings,
        executor=live_runner.make_docker_trial_executor(
            settings, interrupt_before_workload={(second, 1)}
        ),
    )
    assert first["interrupted"] is True and first["finalized_count"] == 1
    # Containers/networks of the interrupted attempt were removed by the executor's finally block.
    assert live_network.list_resources(run=label) == {"containers": [], "networks": []}

    capture = _Capture(live_runner.make_docker_trial_executor(settings))
    resumed = live_runner.execute_live_study(plan, cfg, run_dir, settings, executor=capture)
    assert resumed["dataset_problems"] == [] and resumed["finalized_count"] == 3
    rerun = {(s["trial_id"], i) for s, i, _o in capture.outputs}
    assert (ordered[0]["trial_id"], 1) not in rerun  # completed trial never re-executed
    assert (second, 2) in rerun  # interrupted trial is a linked, bounded retry
    journal = runner.TrialLedger(run_dir).journal_events()
    link = next(
        e for e in journal if e["event"] == "trial_attempt_started" and e["attempt_index"] == 2
    )
    assert link["retry_of_attempt_id"] == f"{second}__att01"
    assert all(r["outcome_kind"] == "scored" for r in resumed["records"])


@pytest.mark.docker
def test_live_crash_leftovers_are_swept_by_run_label(live):
    label = f"s26c-{os.getpid()}"
    crashed = live_network.TrialTopology("B", trial_id="crash", run_label=label)
    crashed.start()  # simulate a killed process: no teardown
    assert live_network.list_resources(run=label)["containers"]
    swept = live_network.sweep_run(label)
    assert swept["containers"] and swept["networks"]
    assert live_network.list_resources(run=label) == {"containers": [], "networks": []}
    crashed.containers, crashed.networks = [], []


@pytest.mark.docker
def test_live_isolation_failure_in_a_plan_fails_closed_without_running_the_workload(live, tmp_path):
    plan = design.build_plan(["D01"], ("A", "B", "C"), 1, seed=3, study_id=protocol.STUDY_ID)
    ordered = sorted(plan["trials"], key=lambda t: t["execution_index"])
    broken = ordered[0]["trial_id"]
    label = f"s26g-{os.getpid()}"
    settings = live_runner.LiveExecutorSettings(run_label=label)
    capture = _Capture(
        live_runner.make_docker_trial_executor(
            settings, topology_faults={(broken, 1): "gateway_policy_invalid"}
        )
    )
    result = live_runner.execute_live_study(
        plan, _config(), tmp_path / "run", settings, executor=capture
    )
    by_id = {r["trial_id"]: r for r in result["records"]}
    failed = by_id[broken]
    assert failed["outcome_kind"] == "infrastructure_failure" and failed["score"] is None
    assert any(
        v["code"] == "egress_not_restricted" and v["invalidating"] for v in failed["violations"]
    )
    record = next(o for s, _i, o in capture.outputs if s["trial_id"] == broken)["runner_record"]
    assert "workload_seconds" not in record["live_evidence"]  # workload never started
    assert all(r["outcome_kind"] == "scored" for t, r in by_id.items() if t != broken)
    assert result["resource_cleanup"]["remaining_after"] == {"containers": [], "networks": []}


def test_module_paths_are_inside_the_repository():
    assert Path(live_network.ROOT, "benchmarks", "codex_r", "run_simple.py").is_file()
