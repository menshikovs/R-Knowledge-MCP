"""Stage 2 study machinery: arms, randomization, records, telemetry, analysis, dry run, power.

Everything here is offline and deterministic. No model, container, R process or network is used.
"""

import json
import math

import jsonschema
import pytest

from benchmarks.codex_r.studies.stage2_validity_v1 import (
    analysis,
    cli,
    design,
    dryrun,
    power,
    protocol,
    records,
    telemetry,
)
from benchmarks.codex_r.telemetry import schema as event_schema

EXPECTED = dryrun.EXPECTED


# ----------------------------------------------------------------- arms / fairness


def test_arms_differ_only_by_mcp_access_and_one_encouragement_sentence():
    base = "Tool-neutral base."
    a, b, c = (protocol.ARMS[k].instructions(base) for k in "ABC")
    assert a == b == base  # byte-identical: no hidden prompt difference between A and B
    assert c == base + protocol.ENCOURAGEMENT and c != b
    assert [protocol.ARMS[k].mcp_available for k in "ABC"] == [False, True, True]
    assert "must" not in protocol.ENCOURAGEMENT and "always" not in protocol.ENCOURAGEMENT
    assert "do not call them when they cannot help" in protocol.ENCOURAGEMENT  # no forced call


def test_real_base_instruction_is_tool_neutral():
    text = protocol.base_instructions()
    assert (
        "R-Knowledge-MCP" not in text and "Documentation tools, if connected, are optional" in text
    )


def evidence_for(arm, **faults):
    return dryrun.MockEnvironment(arm, **faults).evidence()


@pytest.mark.parametrize("arm", ["A", "B", "C"])
def test_correctly_configured_arms_have_no_violations(arm):
    env = dryrun.MockEnvironment(arm)
    if arm != "A":
        env.call("search_packages")
    assert protocol.capability_violations(arm, env.evidence(), EXPECTED) == []


@pytest.mark.parametrize(
    ("arm", "faults", "code", "invalidating"),
    [
        ("A", {"flip_mcp": True}, "arm_a_mcp_reachable", True),
        ("B", {"flip_mcp": True}, "treatment_not_delivered", True),
        ("A", {"open_network": True}, "egress_not_restricted", True),
        ("B", {"no_egress_log": True}, "egress_unverified", True),
        ("A", {"leak_web": True}, "egress_unexpected_destination", True),
    ],
)
def test_misconfigured_sandboxes_are_protocol_violations(arm, faults, code, invalidating):
    found = {
        v.code: v
        for v in protocol.capability_violations(arm, evidence_for(arm, **faults), EXPECTED)
    }
    assert code in found and found[code].invalidating is invalidating


def test_arm_a_cannot_reach_the_mcp_and_a_call_is_recorded_as_a_violation():
    env = dryrun.MockEnvironment("A")
    with pytest.raises(dryrun.ToolUnavailable):
        env.call("get_function_docs")
    leaky = dryrun.MockEnvironment("A", flip_mcp=True)
    leaky.call("get_function_docs")
    codes = {v.code for v in protocol.capability_violations("A", leaky.evidence(), EXPECTED)}
    assert {"arm_a_mcp_reachable", "arm_a_mcp_called"} <= codes
    assert dryrun.MockEnvironment("B").visible_tools() == list(dryrun.TOOLS)


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("instructions_sha256", "0" * 64, "instructions_mismatch"),
        ("model", "other-model", "model_mismatch"),
        ("effort", "high", "effort_mismatch"),
        ("scorer_version", "other-scorer", "scorer_version_mismatch"),
        ("allowed_tools", None, "tool_allowlist_unrecorded"),
    ],
)
def test_recorded_evidence_must_match_the_arm_and_study_constants(key, value, code):
    evidence = {**evidence_for("B"), key: value}
    assert code in {v.code for v in protocol.capability_violations("B", evidence, EXPECTED)}


def test_partial_toolset_is_reported_but_not_invalidating():
    evidence = {**evidence_for("B"), "allowed_tools": list(dryrun.TOOLS[:2])}
    (violation,) = protocol.capability_violations("B", evidence, EXPECTED)
    assert violation.code == "toolset_differs" and violation.invalidating is False


def test_arm_c_instructions_in_arm_b_are_detected():
    evidence = {
        **evidence_for("B"),
        "instructions_sha256": protocol.sha256_text(
            protocol.ARMS["C"].instructions(dryrun.DRYRUN_BASE)
        ),
    }
    assert "instructions_mismatch" in {
        v.code for v in protocol.capability_violations("B", evidence, EXPECTED)
    }


# ------------------------------------------------------------ randomization


TASKS = [f"T{i:02d}" for i in range(1, 9)]


def make_plan(reps=6, seed=5, tasks=TASKS):
    return design.build_plan(tasks, ("A", "B", "C"), reps, seed, "t")


def test_plan_is_valid_deterministic_and_seed_sensitive():
    plan = make_plan()
    assert design.verify_plan(plan) == []
    assert make_plan()["plan_sha256"] == plan["plan_sha256"]
    assert make_plan(seed=6)["plan_sha256"] != plan["plan_sha256"]
    assert plan["seed"] == 5 and plan["algorithm"] == design.ALGORITHM
    assert all(t["fresh_context"] and isinstance(t["trial_seed"], int) for t in plan["trials"])


def test_same_tasks_in_every_arm_and_blocks_are_contiguous_pairs():
    plan = make_plan()
    per_arm = {
        arm: sorted((t["task"], t["repetition"]) for t in plan["trials"] if t["arm"] == arm)
        for arm in "ABC"
    }
    assert per_arm["A"] == per_arm["B"] == per_arm["C"]
    assert len(plan["trials"]) == len(TASKS) * 3 * 6


def test_arm_order_is_exactly_balanced_when_repetitions_fill_the_cycles():
    plan = make_plan(reps=6)
    for task in TASKS:
        positions = {arm: [] for arm in "ABC"}
        for t in plan["trials"]:
            if t["task"] == task:
                positions[t["arm"]].append(t["position_in_block"])
        for arm in "ABC":
            assert sorted(positions[arm]) == [1, 1, 2, 2, 3, 3]  # each position twice per arm
    total = design.position_balance(plan)
    assert all(set(cell.values()) == {16} for cell in total.values())


def test_arm_order_is_within_one_of_balanced_for_other_repetition_counts():
    plan = make_plan(reps=3)
    for cell in design.position_balance(plan).values():
        assert max(cell.values()) - min(cell.values()) <= len(TASKS)


def test_blocks_are_shuffled_so_task_and_repetition_are_not_ordered_in_time():
    plan = make_plan()
    order = [b["block_id"] for b in sorted(plan["blocks"], key=lambda b: b["block_index"])]
    assert order != sorted(order)
    first_of_task = [min(b["block_index"] for b in plan["blocks"] if b["task"] == t) for t in TASKS]
    assert first_of_task != sorted(first_of_task)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["trials"].append(dict(p["trials"][0])),
        lambda p: p["trials"].pop(),
        lambda p: p["trials"][0].update(arm="B" if p["trials"][0]["arm"] != "B" else "C"),
        lambda p: p["trials"][0].update(fresh_context=False),
        lambda p: p.update(seed=999),
    ],
)
def test_tampered_or_incomplete_plans_are_rejected(mutate):
    plan = make_plan(reps=2)
    mutate(plan)
    assert design.verify_plan(plan)


def test_invalid_design_requests_are_rejected():
    with pytest.raises(ValueError):
        design.build_plan(["T1", "T1"], ("A", "B"), 1, 1, "t")
    with pytest.raises(ValueError):
        design.build_plan(["T1"], ("A",), 1, 1, "t")
    with pytest.raises(ValueError):
        design.build_plan(["T1"], ("A", "B"), 0, 1, "t")


# --------------------------------------------------------------- records


def good_record(**changes):
    record = {
        "trial_id": "T01-r1-A",
        "block_id": "T01-r1",
        "task": "T01",
        "arm": "A",
        "repetition": 1,
        "execution_index": 1,
        "model": "m",
        "effort": "medium",
        "scorer_version": "s",
        "outcome_kind": "scored",
        "score": 0.6,
        "checks_passed": 3,
        "checks_total": 5,
        "mcp": {
            "available": False,
            "listed": False,
            "attempted": 0,
            "completed": 0,
            "errored": 0,
            "correlation": "not_applicable",
        },
        "usage": {"status": "unavailable"},
        "violations": [],
    }
    record.update(changes)
    return record


def test_valid_record_passes_python_and_json_schema():
    record = good_record()
    assert records.validate_record(record) == []
    jsonschema.validate(record, records.schema())


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome_kind": "made-up"},
        {"score": 1.5},
        {"score": 0.7},  # not passed / total
        {"outcome_kind": "candidate_failure", "score": 0.4},
        {"outcome_kind": "infrastructure_failure", "score": 0.0},
        {"arm": "D"},
        {"usage": {"status": "observed"}},
        {"violations": None},
        {"mcp": {"available": False}},
        {"checks_total": 0},
    ],
)
def test_inconsistent_records_are_rejected(changes):
    assert records.validate_record(good_record(**changes))


def test_mcp_counters_must_be_consistent():
    mcp = {**good_record()["mcp"], "attempted": 1, "completed": 1, "errored": 1}
    assert records.validate_record(good_record(mcp=mcp))


def test_dataset_needs_exactly_one_record_per_planned_trial():
    ids = ["T01-r1-A", "T01-r1-B"]
    a, b = good_record(), good_record(trial_id="T01-r1-B", arm="B")
    assert records.validate_dataset([a, b], ids) == []
    assert any("no record" in p for p in records.validate_dataset([a], ids))
    assert any("duplicate" in p for p in records.validate_dataset([a, a, b], ids))
    assert any(
        "not in the plan" in p
        for p in records.validate_dataset([a, b, good_record(trial_id="X")], ids)
    )


def test_missing_data_rules_are_the_preregistered_ones():
    value = lambda **c: records.analysis_value(good_record(**c))  # noqa: E731
    assert value() == (0.6, "scored")
    assert value(outcome_kind="candidate_failure", score=0.0) == (0.0, "candidate_failure_as_zero")
    for kind in ("infrastructure_failure", "scoring_error", "not_executed"):
        assert value(outcome_kind=kind, score=None) == (None, kind)
    violation = {"code": "arm_a_mcp_called", "detail": "", "invalidating": True}
    assert value(violations=[violation]) == (None, "invalidating_protocol_violation")
    mild = {"code": "toolset_differs", "detail": "", "invalidating": False}
    assert value(violations=[mild])[0] == 0.6


# -------------------------------------------------------------- telemetry


def trace(behaviour, available=True, seed=3):
    events = dryrun.synthetic_tool_events("run", "trial", behaviour, design.seeded(seed, "t"))
    return events, telemetry.summarize_trace(events, available=available)


@pytest.mark.parametrize(
    "behaviour", ["none", "uses_ok", "uses_errors", "interrupted", "partial_trace", "mismatch"]
)
def test_synthetic_events_conform_to_the_benchmark_event_schema(behaviour):
    events, _ = trace(behaviour)
    for event in events:
        assert event_schema.validate_event(event) == [], event


def test_availability_listing_attempt_and_completion_are_separate_levels():
    _, none = trace("none")
    assert (none["available"], none["listed"], none["attempted"], none["completed"]) == (
        True,
        None,
        0,
        0,
    )
    _, absent = trace("none", available=False)
    assert absent["available"] is False and absent["listed"] is False
    _, ok = trace("uses_ok")
    assert (ok["listed"], ok["attempted"], ok["completed"], ok["errored"], ok["delivered"]) == (
        True,
        2,
        2,
        0,
        2,
    )
    assert ok["correlation"] == "ordinal_unconfirmed" and ok["delivered_confirmed"] is None
    assert ok["time_to_first_call_ms"] == 1000.0 and ok["server_latency_ms_mean"] == 12.5


def test_errors_and_interrupted_calls_are_not_successes():
    _, errors = trace("uses_errors")
    assert (errors["attempted"], errors["completed"], errors["errored"], errors["delivered"]) == (
        2,
        1,
        1,
        1,
    )
    assert errors["error_codes"] == {"docs_not_found": 1}
    _, interrupted = trace("interrupted")
    assert (interrupted["attempted"], interrupted["completed"], interrupted["never_completed"]) == (
        2,
        1,
        1,
    )


def test_missing_or_disagreeing_server_trace_is_never_reported_as_confirmed():
    _, partial = trace("partial_trace")
    assert partial["server_calls"] == 0 and partial["listed"] is None
    assert partial["correlation"] == "unmatched" and partial["client_server_count_mismatch"] is True
    _, mismatch = trace("mismatch")
    assert mismatch["correlation"] == "unmatched"


def test_protocol_id_correlation_requires_matching_ids_tools_and_counts():
    events, _ = trace("uses_ok")
    client = [
        e
        for e in events
        if e["event_type"] == "mcp.tool.completed" and e["source"] == telemetry.CLIENT
    ]
    server = [
        {**e, "protocol_call_id": str(i + 1)}
        for i, e in enumerate(
            x for x in events if x["source"] == telemetry.SERVER and "call_id" in x
        )
    ]
    for call in server:
        call["server_protocol_call_id"] = call["protocol_call_id"]
    proxy = [{"jsonrpc_id": str(i + 1), "tool": c["tool"]} for i, c in enumerate(server)]
    status, links = telemetry.correlate_calls(client, server, proxy)
    assert status == "confirmed_protocol_id" and all(
        link["status"] == "confirmed" for link in links
    )
    wrong_tool = [{**proxy[0], "tool": "other"}, proxy[1]]
    assert telemetry.correlate_calls(client, server, wrong_tool)[0] == "unmatched"
    assert telemetry.correlate_calls(client, server, proxy[:1])[0] == "unmatched"
    assert telemetry.correlate_calls([], [], None)[0] == "not_applicable"


def test_result_use_proxy_is_labelled_a_proxy_and_ignores_prompt_restatement():
    prompt = "Choose a terminal user interface package for a command line tool"
    results = ["Package termr: reactive terminal applications; widgets, layouts, themes"]
    used = telemetry.result_use_proxy(
        results, prompt, "I recommend termr with its widgets and layouts"
    )
    unused = telemetry.result_use_proxy(
        results, prompt, "I recommend a package for a command line tool"
    )
    assert used["kind"] == unused["kind"] == "proxy"
    assert used["share"] > unused["share"] == 0.0
    assert telemetry.result_use_proxy([], prompt, "anything")["share"] is None


# ----------------------------------------------------------------- analysis


def rec(task, rep, arm, score, **changes):
    total = 10
    fields = {
        "trial_id": f"{task}-r{rep}-{arm}",
        "block_id": f"{task}-r{rep}",
        "task": task,
        "arm": arm,
        "repetition": rep,
        "score": score,
        "checks_passed": None if score is None else round(score * total),
        "checks_total": None if score is None else total,
        **changes,
    }
    return good_record(**fields)


def test_estimate_is_the_mean_of_task_means_not_of_trials():
    data = []
    for rep in range(1, 7):  # task T1: six blocks, effect 0.5
        data += [rec("T1", rep, "A", 0.0), rec("T1", rep, "B", 0.5)]
    data += [rec("T2", 1, "A", 0.5), rec("T2", 1, "B", 0.5)]  # task T2: one block, effect 0
    result = analysis.estimate(data, "B", "A", seed=1, n_perm=999, n_boot=200)
    assert result["estimate"] == pytest.approx(0.25)  # weighting blocks would give 3.0 / 7
    assert result["n_tasks"] == 2 and result["ledger"]["blocks_analysed"] == 7


def test_exact_sign_flip_p_value_matches_hand_enumeration():
    diffs = {"T1": [0.2], "T2": [0.1], "T3": [0.3]}
    result = analysis.sign_flip_p(diffs, seed=1)
    assert result["method"] == "exact" and result["n_permutations"] == 8
    assert result["p"] == pytest.approx(2 / 8)  # only all-plus and all-minus are as extreme


def test_monte_carlo_p_is_reproducible_and_bounded_below():
    diffs = {f"T{i}": [0.2, 0.1, 0.3] for i in range(20)}
    first = analysis.sign_flip_p(diffs, seed=4, n_perm=999)
    assert first == analysis.sign_flip_p(diffs, seed=4, n_perm=999)
    assert first["method"] == "monte_carlo" and first["p"] >= 1 / 1000
    assert first["unit"] == "task" and first["n_units"] == 20


def test_repetitions_cannot_substitute_for_tasks_in_the_primary_test():
    """Three tasks with 30 identical positive repetitions each: the task-level test cannot get
    below 2/8, the block-level (sharp null) test can. Repetitions are not independent samples."""
    diffs = {f"T{i}": [0.2] * 30 for i in range(3)}
    task = analysis.sign_flip_p(diffs, seed=1, unit="task")
    block = analysis.sign_flip_p(diffs, seed=1, n_perm=999, unit="block")
    assert task["p"] == pytest.approx(0.25) and task["method"] == "exact"
    assert block["p"] < 0.01 and block["n_units"] == 90
    data = [
        rec(t, r, a, s)
        for t in ("T1", "T2", "T3")
        for r in range(1, 31)
        for a, s in (("A", 0.2), ("B", 0.4))
    ]
    result = analysis.estimate(data, "B", "A", seed=1, n_perm=999, n_boot=100)
    assert result["p_value"] == pytest.approx(0.25)  # the reported p-value is the task-level one
    assert result["test_block_level_sharp_null"]["p"] < 0.01


def test_bootstrap_interval_is_reproducible_and_brackets_a_clear_effect():
    diffs = {f"T{i}": [0.3 + 0.01 * i] for i in range(12)}
    ci = analysis.bootstrap_ci(diffs, seed=2, n_boot=400)
    assert ci == analysis.bootstrap_ci(diffs, seed=2, n_boot=400)
    assert ci["low"] <= analysis.statistic(diffs) <= ci["high"] and ci["low"] > 0.2


def test_failures_missing_values_and_violations_follow_the_ledger_rules():
    base = [rec("T1", 1, "A", 0.2), rec("T1", 1, "B", 0.6)]
    data = base + [
        rec("T2", 1, "A", 0.5),
        rec(
            "T2",
            1,
            "B",
            0.0,
            outcome_kind="candidate_failure",
            checks_passed=None,
            checks_total=None,
        ),
        rec("T3", 1, "A", 0.5),
        rec("T3", 1, "B", None, outcome_kind="infrastructure_failure"),
        rec("T4", 1, "A", 0.5),
        rec("T4", 1, "B", 0.9, violations=[{"code": "x", "detail": "", "invalidating": True}]),
    ]
    diffs, ledger = analysis.block_differences(data, "B", "A")
    assert diffs == {
        "T1": pytest.approx([0.4]),
        "T2": [-0.5],
    }  # failure counts as 0; others dropped
    assert ledger["dropped"] == {"infrastructure_failure": 1, "invalidating_protocol_violation": 1}
    assert ledger["blocks_planned"] == 4 and ledger["blocks_analysed"] == 2
    sensitivity = analysis.sensitivity(data, seed=1)
    assert (
        sensitivity["missing_worst_case_for_treatment"]
        < sensitivity["missing_best_case_for_treatment"]
    )
    assert sensitivity["include_protocol_violation_trials"] != sensitivity["primary_point_estimate"]


def test_holm_correction_is_monotone_and_keeps_missing_values():
    adjusted = analysis.holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": None})
    assert adjusted["a"] == pytest.approx(0.03) and adjusted["c"] == pytest.approx(0.06)
    assert adjusted["b"] == pytest.approx(0.06) and adjusted["d"] is None


def test_use_conditioned_comparison_is_labelled_descriptive_and_confounded():
    data = [
        rec("T1", 1, "B", 0.9, mcp={**good_record()["mcp"], "attempted": 2}),
        rec("T2", 1, "B", 0.1),
    ]
    result = analysis.descriptive_by_use(data)
    assert "confounded" in result["label"] and result["used"]["n"] == result["not_used"]["n"] == 1


def test_primary_analysis_never_conditions_on_tool_use():
    # Same scores, different tool use: the assigned-arm estimate cannot change.
    data = [rec("T1", r, a, s) for r in (1, 2) for a, s in (("A", 0.2), ("B", 0.6))]
    used = [{**d, "mcp": {**d["mcp"], "attempted": 3}} if d["arm"] == "B" else d for d in data]
    one = analysis.estimate(data, "B", "A", seed=1, n_perm=99, n_boot=50)["estimate"]
    two = analysis.estimate(used, "B", "A", seed=1, n_perm=99, n_boot=50)["estimate"]
    assert one == two


# ----------------------------------------------------------------- dry run


def test_dry_run_is_reproducible_from_preserved_inputs(tmp_path):
    first = dryrun.run_scenario(tmp_path / "a", "positive", 10, 3, 9)
    second = dryrun.run_scenario(tmp_path / "b", "positive", 10, 3, 9)
    assert first["digest"] == second["digest"]
    plan, recs = dryrun.read_inputs(tmp_path / "a")
    assert dryrun.result_digest(dryrun.analyse(plan, recs, 9)) == first["digest"]
    assert cli.main(["reanalyze", str(tmp_path / "a"), "--seed", "9"]) == 0


def test_no_trial_is_silently_dropped_and_failures_are_kept_in_the_record(tmp_path):
    out = dryrun.run_scenario(tmp_path, "heavy_missingness", 12, 3, 4)
    result = out["result"]
    assert result["n_records"] == result["n_trials_planned"] == 12 * 3 * 3
    assert sum(result["outcome_kinds"].values()) == result["n_records"]
    assert result["outcome_kinds"]["infrastructure_failure"] > 10
    ledger = result["analysis"]["primary"]["ledger"]
    assert ledger["blocks_analysed"] + sum(ledger["dropped"].values()) == ledger["blocks_planned"]


def test_leaky_control_is_detected_and_excluded_from_the_primary_analysis(tmp_path):
    result = dryrun.run_scenario(tmp_path, "leaky_control", 12, 3, 4)["result"]
    assert result["violation_codes"]["arm_a_mcp_reachable"] > 0
    ledger = result["analysis"]["primary"]["ledger"]
    assert ledger["dropped"]["invalidating_protocol_violation"] > 0
    assert result["analysis"]["sensitivity"]["include_protocol_violation_trials"] is not None


def test_scenarios_recover_their_known_truth(tmp_path):
    results = {
        n: dryrun.run_scenario(tmp_path / n, n, 30, 3, 20261028)["result"] for n in dryrun.SCENARIOS
    }
    primary = {n: r["analysis"]["primary"] for n, r in results.items()}
    assert primary["null"]["ci"]["low"] < 0 < primary["null"]["ci"]["high"]
    assert primary["positive"]["estimate"] > 0.08 and primary["positive"]["p_value"] < 0.05
    assert (
        primary["negative_tool_tax"]["estimate"] < -0.08
        and primary["negative_tool_tax"]["p_value"] < 0.05
    )
    # a harmful or null effect is reported as such; the analysis has no built-in direction
    assert results["positive"]["analysis"]["primary_decision"] == "reject_null_at_alpha"
    assert results["null"]["analysis"]["primary_decision"] == "do_not_reject_null"


def test_dry_run_records_validate_against_the_json_schema(tmp_path):
    _, recs = dryrun.generate("leaky_control", 6, 2, 3)
    for record in recs:
        jsonschema.validate(record, records.schema())
        assert records.validate_record(record) == []


def test_corrupt_inputs_fail_loudly(tmp_path):
    plan, recs = dryrun.generate("null", 4, 2, 1)
    with pytest.raises(ValueError, match="no record"):
        dryrun.analyse(plan, recs[:-1], 1)
    broken = [{**recs[0], "outcome_kind": "bogus"}, *recs[1:]]
    with pytest.raises(ValueError, match="outcome_kind"):
        dryrun.analyse(plan, broken, 1)


# ------------------------------------------------------------------- power


def test_power_simulation_is_deterministic_and_has_sensible_extremes():
    a = power.Assumptions()
    cell = power.power_cell(30, 3, 0.30, a, n_sim=40, n_perm=199, seed=1)
    assert cell == power.power_cell(30, 3, 0.30, a, n_sim=40, n_perm=199, seed=1)
    assert cell["rejection_rate"] > 0.6
    null = power.power_cell(10, 3, 0.0, a, n_sim=80, n_perm=199, seed=1)
    assert null["rejection_rate"] <= 0.15  # nominal 0.05; loose bound for 80 simulations
    assert abs(null["mean_estimate"]) < 0.05


def test_resource_arithmetic_uses_only_supplied_measurements():
    out = power.resources(30, 3, 3, 0.10, {"median_seconds": 100.0, "p90_seconds": 200.0})
    assert out["planned_trials"] == 270 and out["trials_with_retry_allowance"] == 297
    assert out["sequential_hours_median"] == round(297 * 100 / 3600, 1)
    assert "price" in out["cost_total_formula"] and not any(
        "usd" in str(v).lower() for v in out.values()
    )
    assert math.isclose(power._sigmoid(power._logit(0.3)), 0.3)


def test_cli_plan_writes_a_verified_pilot_plan(tmp_path):
    out = tmp_path / "plan.json"
    assert cli.main(["plan", "--design", "pilot", "--seed", "12345", "--out", str(out)]) == 0
    plan = json.loads(out.read_text(encoding="utf-8"))
    assert design.verify_plan(plan) == [] and len(plan["trials"]) == 10 * 3 * 3


def test_negative_effect_is_detected_by_estimate_and_power_simulation():
    data = [
        rec(f"T{i:02d}", r, arm, 0.7 if arm == "A" else 0.3)
        for i in range(1, 13)
        for r in (1, 2, 3)
        for arm in ("A", "B")
    ]
    res = analysis.estimate(data, "B", "A", seed=11, n_perm=999, n_boot=400)
    assert res["estimate"] == pytest.approx(-0.4)
    assert res["ci"]["high"] < -0.2 and res["p_value"] < 0.01
    a = power.Assumptions()
    neg_cell = power.power_cell(30, 3, -0.20, a, n_sim=40, n_perm=199, seed=7)
    assert neg_cell["diluted_effect"] == pytest.approx(-0.15)
    assert neg_cell["mean_estimate"] < -0.08 and neg_cell["rejection_rate"] > 0.6


def test_heterogeneous_zero_mean_task_effects_preserve_task_level_type_i_error():
    # Half the tasks have a true +0.4 effect, half have -0.4; population average is 0.
    # Across 10 repetitions per task, block-level sign-flipping treats repetitions as
    # independent and severely over-rejects, whereas task-level sign-flipping stays nominal.
    a = power.Assumptions(saturated=0.0, tau=0.20, rep_sd=0.2)
    cmp = power.type_i_comparison(24, 6, a, n_sim=80, n_perm=199, seed=42)
    assert cmp["type_i_task_level"] <= 0.12
    assert cmp["type_i_block_level"] > cmp["type_i_task_level"]


def test_saturated_tasks_dilute_point_estimate_without_breaking_inference():
    data = []
    # 6 saturated ceiling tasks (both arms score 1.0) and 6 active tasks (+0.4 effect)
    for i in range(1, 7):
        for r in (1, 2):
            data += [rec(f"S{i}", r, "A", 1.0), rec(f"S{i}", r, "B", 1.0)]
            data += [rec(f"A{i}", r, "A", 0.4), rec(f"A{i}", r, "B", 0.8)]
    res = analysis.estimate(data, "B", "A", seed=5, n_perm=999, n_boot=400)
    assert res["n_tasks"] == 12
    assert res["estimate"] == pytest.approx(0.2)
    assert res["ci"]["low"] > 0.0 and res["p_value"] < 0.05


def test_complete_and_incomplete_paired_blocks_weight_tasks_equally():
    # T1 has 1 complete block (+0.4) and 2 incomplete blocks (missing B);
    # T2 has 3 complete blocks (0.0). Task-level mean must still be (0.4 + 0.0) / 2 = 0.2.
    data = [
        rec("T1", 1, "A", 0.2),
        rec("T1", 1, "B", 0.6),
        rec("T1", 2, "A", 0.2),
        rec("T1", 2, "B", None, outcome_kind="infrastructure_failure"),
        rec("T1", 3, "A", 0.2),
        rec("T1", 3, "B", None, outcome_kind="not_executed"),
    ]
    for r in (1, 2, 3):
        data += [rec("T2", r, "A", 0.5), rec("T2", r, "B", 0.5)]
    res = analysis.estimate(data, "B", "A", seed=3, n_perm=499, n_boot=200)
    assert res["n_tasks"] == 2
    assert res["estimate"] == pytest.approx(0.2)
    assert res["ledger"]["blocks_planned"] == 6 and res["ledger"]["blocks_analysed"] == 4
    assert res["ledger"]["dropped"] == {"infrastructure_failure": 1, "not_executed": 1}


def test_small_task_counts_use_exact_enumeration_with_known_resolution_floor():
    # With K=4 tasks and identical positive effects, exact two-sided p is 2 / 2^4 = 0.125 > 0.05.
    diffs = {f"T{i}": [0.5, 0.5, 0.5] for i in range(4)}
    res = analysis.sign_flip_p(diffs, seed=1, unit="task")
    assert res["method"] == "exact" and res["n_permutations"] == 16
    assert res["p"] == pytest.approx(2 / 16)


def test_preregistered_analysis_returns_complete_primary_secondary_and_holm_outputs():
    data = []
    for i in range(1, 9):
        for r in (1, 2):
            data += [
                rec(f"T{i}", r, "A", 0.2),
                rec(f"T{i}", r, "B", 0.8),
                rec(f"T{i}", r, "C", 1.0),
            ]
    out = analysis.run_preregistered_analysis(data, seed=19, n_perm=499, n_boot=200)
    assert out["primary"]["contrast"] == "B-A"
    assert out["primary"]["estimate"] == pytest.approx(0.6)
    assert set(out["secondary"]) == {"C-B", "C-A", "B-A:fully_correct"}
    assert all("p_holm" in v and v["p_holm"] is not None for v in out["secondary"].values())
    assert out["secondary"]["B-A:fully_correct"]["estimate"] == pytest.approx(0.0)
    assert out["secondary"]["C-A"]["estimate"] == pytest.approx(0.8)
    assert out["primary_decision"] == "reject_null_at_alpha"


def test_control_arm_record_with_leaked_mcp_validates_and_records_violation():
    leaked = good_record(
        arm="A",
        mcp={
            "available": True,
            "listed": True,
            "attempted": 2,
            "completed": 2,
            "errored": 0,
            "correlation": "ordinal_unconfirmed",
        },
        violations=[
            {"code": "arm_a_mcp_reachable", "detail": "leaked container", "invalidating": True},
            {"code": "arm_a_mcp_called", "detail": "2 calls", "invalidating": True},
        ],
    )
    assert records.validate_record(leaked) == []
    jsonschema.validate(leaked, records.schema())
    assert records.analysis_value(leaked, exclude_invalidating=True) == (
        None,
        "invalidating_protocol_violation",
    )
    assert records.analysis_value(leaked, exclude_invalidating=False) == (0.6, "scored")


def test_telemetry_handles_duplicated_and_unstarted_terminal_events():
    events = [
        dryrun._event(
            "mcp.tool.started",
            "run",
            "trial",
            100.0,
            telemetry.CLIENT,
            call_id="client-call-0001",
            tool="get_package",
        ),
        # Duplicate start for same call_id
        dryrun._event(
            "mcp.tool.started",
            "run",
            "trial",
            100.0,
            telemetry.CLIENT,
            call_id="client-call-0001",
            tool="get_package",
        ),
        dryrun._event(
            "mcp.tool.completed",
            "run",
            "trial",
            120.0,
            telemetry.CLIENT,
            call_id="client-call-0001",
            tool="get_package",
            is_error=False,
        ),
        # Duplicate completion for same call_id
        dryrun._event(
            "mcp.tool.completed",
            "run",
            "trial",
            120.0,
            telemetry.CLIENT,
            call_id="client-call-0001",
            tool="get_package",
            is_error=False,
        ),
        # Interrupted second call
        dryrun._event(
            "mcp.tool.started",
            "run",
            "trial",
            200.0,
            telemetry.CLIENT,
            call_id="client-call-0002",
            tool="search_packages",
        ),
        # Third call with terminal event only (no start event streamed)
        dryrun._event(
            "mcp.tool.failed",
            "run",
            "trial",
            300.0,
            telemetry.CLIENT,
            call_id="client-call-0003",
            tool="get_function_docs",
            is_error=True,
        ),
    ]
    summary = telemetry.summarize_trace(events, available=True)
    assert summary["attempted"] == 3
    assert summary["completed"] == 1
    assert summary["errored"] == 1
    assert summary["never_completed"] == 1
    rec_obj = good_record(arm="B", mcp={k: v for k, v in summary.items() if k != "links"})
    assert records.validate_record(rec_obj) == []
    jsonschema.validate(rec_obj, records.schema())


def test_from_runner_result_maps_outcomes_and_flags_plain_bridge_network():
    plan = design.build_plan(["D01"], ("A", "B", "C"), 1, 7, "s")
    trials_by_arm = {t["arm"]: t for t in plan["trials"]}
    runner_b = {
        "trial_id": "D01-B-1",
        "task": "D01",
        "mode": "with-mcp",
        "repetition": 1,
        "model": EXPECTED["model"],
        "effort": EXPECTED["effort"],
        "instructions": "standard",
        "scorer_identity": EXPECTED["scorer_version"],
        "status": "scored",
        "score": {"passed": 3, "total": 4},
        "allowed_tools": list(EXPECTED["mcp_tools"]),
        "mcp_server_audit": {"list_tools_requests": 1, "call_tool_requests": 2},
        "usage_status": "observed",
        "usage": {"input_tokens": 1200, "output_tokens": 250},
    }
    events, _ = trace("uses_ok")
    stage2_b = records.from_runner_result(trials_by_arm["B"], runner_b, events, EXPECTED)
    assert records.validate_record(stage2_b) == []
    jsonschema.validate(stage2_b, records.schema())
    assert stage2_b["outcome_kind"] == "scored" and stage2_b["score"] == pytest.approx(0.75)
    assert stage2_b["synthetic"] is False
    codes_b = {v["code"] for v in stage2_b["violations"]}
    # Because run_simple.py uses a plain bridge network without an egress proxy, both are flagged.
    assert {"egress_not_restricted", "egress_unverified"} <= codes_b

    # Scorer abstention (unsupported_for_automatic_scoring) maps to scoring_error (missing), not 0.
    runner_unsupported = {
        **runner_b,
        "status": "unsupported_for_automatic_scoring",
        "score": None,
        "error_summary": {
            "primary_error": {
                "origin": "candidate",
                "category": "r_runtime",
                "reason_code": "R_RUNTIME_ERROR",
                "source_code": "unsupported_for_automatic_scoring",
            }
        },
    }
    stage2_unsup = records.from_runner_result(
        trials_by_arm["B"], runner_unsupported, events, EXPECTED
    )
    assert stage2_unsup["outcome_kind"] == "scoring_error" and stage2_unsup["score"] is None
    assert records.validate_record(stage2_unsup) == []

    # Candidate error maps to candidate_failure with score 0.0.
    runner_cand_err = {
        **runner_b,
        "status": "error",
        "score": None,
        "error_summary": {
            "primary_error": {
                "origin": "candidate",
                "category": "artifact",
                "reason_code": "ARTIFACT_INVALID",
                "source_code": "valueerror",
            }
        },
    }
    stage2_cand = records.from_runner_result(trials_by_arm["B"], runner_cand_err, events, EXPECTED)
    assert stage2_cand["outcome_kind"] == "candidate_failure" and stage2_cand["score"] == 0.0
    assert records.validate_record(stage2_cand) == []


# ------------------------------------------------ Stage 2.5 runner, isolation & scorer calibration


def test_stage25_isolation_policy_and_connection_probes():
    from benchmarks.codex_r.studies.stage2_validity_v1 import isolation

    probes = isolation.run_synthetic_isolation_probes()
    assert probes["synthetic_probe_suite"] is True
    assert probes["live_docker_isolation_established"] is False
    assert probes["all_policy_invariants_satisfied"] is True
    assert probes["arms"]["A"]["mcp_reachable"] is False
    assert probes["arms"]["B"]["mcp_reachable"] is True
    assert probes["arms"]["C"]["mcp_reachable"] is True

    # Verify legacy runner static audit accurately reports the plain Docker bridge blocker.
    legacy = isolation.inspect_legacy_runner_isolation()
    assert legacy["arm_a_omits_mcp_container"] is True
    assert legacy["creates_plain_docker_bridge"] is True
    assert legacy["uses_docker_internal_network_flag"] is False
    assert legacy["live_egress_isolation_enforced"] is False


def test_stage25_runner_executes_three_arm_plan_and_preserves_invariants(tmp_path):
    from benchmarks.codex_r.studies.stage2_validity_v1 import runner, study_configs

    out_dir = tmp_path / "smoke_run"
    result = study_configs.run_smoke_mock_study(out_dir, seed=20261028)
    assert result["dataset_problems"] == []
    assert result["finalized_count"] == 12
    assert result["planned_count"] == 12
    assert result["interrupted"] is False
    assert {r["arm"] for r in result["records"]} == {"A", "B", "C"}
    assert all(r["outcome_kind"] == "scored" for r in result["records"])
    assert all(r["violations"] == [] for r in result["records"])

    # Re-running on the same directory is a no-op (completed valid trials are never repeated).
    plan = json.loads((out_dir / "plan.json").read_text(encoding="utf-8"))
    cfg = runner.StudyExecutionConfig(
        stage="smoke_mock",
        timeout_seconds=60,
        max_infra_retries=1,
        stop_on_invalidating_violation=True,
        synthetic=True,
    )

    def _fail_if_called(spec, attempt_idx, ws):
        raise AssertionError(f"Completed trial {spec['trial_id']} must not be re-executed")

    resumed = runner.execute_study_plan(plan, cfg, out_dir, _fail_if_called)
    assert resumed["dataset_problems"] == []
    assert resumed["finalized_count"] == 12


def test_stage25_ledger_resume_after_interruption_during_execution_and_after_scoring(tmp_path):
    from benchmarks.codex_r.studies.stage2_validity_v1 import runner

    plan = design.build_plan(
        ["R03", "C03"], ("A", "B", "C"), 1, seed=99, study_id=protocol.STUDY_ID
    )
    cfg = runner.StudyExecutionConfig(stage="fault_test", max_infra_retries=0, synthetic=True)
    ordered = sorted(plan["trials"], key=lambda t: t["execution_index"])
    second_tid = ordered[1]["trial_id"]
    third_tid = ordered[2]["trial_id"]

    # 1. Interrupt during model execution of the 2nd trial:
    run_dir = tmp_path / "interrupt_exec"
    exec_1 = runner.make_mock_trial_executor(interrupt_on={(second_tid, 1)})
    res_1 = runner.execute_study_plan(plan, cfg, run_dir, exec_1)
    assert res_1["interrupted"] is True
    assert res_1["finalized_count"] == 1
    by_id_1 = {r["trial_id"]: r for r in res_1["records"]}
    assert by_id_1[ordered[0]["trial_id"]]["outcome_kind"] == "scored"
    assert by_id_1[second_tid]["outcome_kind"] == "not_executed"

    # Resume with max_infra_retries=0: the interrupted trial exhausted its 1 attempt and
    # becomes an explicit `not_executed` record in the ledger while remaining trials complete.
    exec_2 = runner.make_mock_trial_executor()
    res_2 = runner.execute_study_plan(plan, cfg, run_dir, exec_2)
    assert res_2["interrupted"] is False
    assert res_2["dataset_problems"] == []
    by_id_2 = {r["trial_id"]: r for r in res_2["records"]}
    assert by_id_2[second_tid]["outcome_kind"] == "not_executed"
    assert by_id_2[third_tid]["outcome_kind"] == "scored"

    # 2. Interrupt AFTER scoring of the 3rd trial but BEFORE final persistence:
    run_dir_post = tmp_path / "interrupt_post_score"

    def _interrupt_before_commit(tid: str, attempt_idx: int) -> None:
        if tid == third_tid and attempt_idx == 1:
            raise runner.InterruptionSimulated("Power loss after scoring before JSONL append")

    res_post_1 = runner.execute_study_plan(
        plan,
        cfg,
        run_dir_post,
        runner.make_mock_trial_executor(),
        before_commit_hook=_interrupt_before_commit,
    )
    assert res_post_1["interrupted"] is True
    assert res_post_1["finalized_count"] == 2

    # On resume, `third_tid` is recovered directly from `.staging.json` WITHOUT calling executor!
    called_trials: list[str] = []
    base_exec = runner.make_mock_trial_executor()

    def _tracking_exec(spec, attempt_idx, ws):
        called_trials.append(spec["trial_id"])
        return base_exec(spec, attempt_idx, ws)

    res_post_2 = runner.execute_study_plan(plan, cfg, run_dir_post, _tracking_exec)
    assert res_post_2["dataset_problems"] == []
    assert res_post_2["finalized_count"] == 6
    assert third_tid not in called_trials
    assert all(r["outcome_kind"] == "scored" for r in res_post_2["records"])


def test_stage25_ledger_recovers_corrupt_jsonl_tail_and_deduplicates_records(tmp_path):
    from benchmarks.codex_r.studies.stage2_validity_v1 import runner

    plan = design.build_plan(["R03"], ("A", "B", "C"), 1, seed=7, study_id=protocol.STUDY_ID)
    cfg = runner.StudyExecutionConfig(stage="corrupt_test", synthetic=True)
    run_dir = tmp_path / "corrupt_ledger"
    res = runner.execute_study_plan(plan, cfg, run_dir, runner.make_mock_trial_executor())
    assert res["finalized_count"] == 3

    # Inject a duplicate of the first record and a truncated/corrupt JSON tail line
    rec_path = run_dir / "trial_records.jsonl"
    lines = rec_path.read_text(encoding="utf-8").splitlines()
    corrupted_content = "\n".join([lines[0], lines[0], lines[1], '{"trial_id": "truncated'])
    rec_path.write_text(corrupted_content, encoding="utf-8")

    # Recovery must quarantine the corrupt tail, deduplicate lines[0], and run the 3rd trial
    res_recovered = runner.execute_study_plan(plan, cfg, run_dir, runner.make_mock_trial_executor())
    assert res_recovered["dataset_problems"] == []
    assert res_recovered["finalized_count"] == 3
    ledger = runner.TrialLedger(run_dir)
    events = {e["event"] for e in ledger.journal_events()}
    assert "corrupt_jsonl_line_quarantined" in events
    assert "duplicate_trial_record_detected" in events


def test_stage25_infra_retry_links_attempts_and_never_retries_candidate_failure(tmp_path):
    from benchmarks.codex_r.studies.stage2_validity_v1 import runner

    plan = design.build_plan(["R03"], ("A", "B", "C"), 1, seed=123, study_id=protocol.STUDY_ID)
    cfg = runner.StudyExecutionConfig(stage="retry_test", max_infra_retries=1, synthetic=True)
    ordered = sorted(plan["trials"], key=lambda t: t["execution_index"])
    t_infra = ordered[0]["trial_id"]
    t_cand = ordered[1]["trial_id"]

    executor = runner.make_mock_trial_executor(
        fail_trial_attempts={
            (t_infra, 1): "infrastructure_failure",
            (t_cand, 1): "candidate_failure",
        }
    )
    run_dir = tmp_path / "retry_run"
    res = runner.execute_study_plan(plan, cfg, run_dir, executor)
    assert res["dataset_problems"] == []
    by_id = {r["trial_id"]: r for r in res["records"]}
    # `t_infra` succeeded on attempt 2 after attempt 1 failed with infrastructure_failure
    assert by_id[t_infra]["outcome_kind"] == "scored"
    # `t_cand` was NOT retried and remained candidate_failure with ITT score 0.0
    assert by_id[t_cand]["outcome_kind"] == "candidate_failure"
    assert by_id[t_cand]["score"] == 0.0

    ledger = runner.TrialLedger(run_dir)
    infra_starts = [
        e
        for e in ledger.journal_events()
        if e.get("trial_id") == t_infra and e.get("event") == "trial_attempt_started"
    ]
    cand_starts = [
        e
        for e in ledger.journal_events()
        if e.get("trial_id") == t_cand and e.get("event") == "trial_attempt_started"
    ]
    assert len(infra_starts) == 2
    assert infra_starts[1]["retry_of_attempt_id"] == f"{t_infra}__att01"
    assert len(cand_starts) == 1


def test_stage25_task_and_scorer_hash_mismatch_detected(tmp_path):
    from benchmarks.codex_r.studies.stage2_validity_v1 import runner

    plan = design.build_plan(["R03"], ("A", "B", "C"), 1, seed=55, study_id=protocol.STUDY_ID)
    cfg = runner.StudyExecutionConfig(
        stage="tamper_test", stop_on_invalidating_violation=True, synthetic=True
    )
    base_exec = runner.make_mock_trial_executor()

    def _tampered_exec(spec, attempt_idx, ws):
        out = base_exec(spec, attempt_idx, ws)
        if spec["execution_index"] == 1:
            out["runner_record"]["task_sha256"] = "0" * 64
            out["runner_record"]["scorer_sha256"] = "f" * 64
        return out

    res = runner.execute_study_plan(plan, cfg, tmp_path / "tamper", _tampered_exec)
    first_rec = res["records"][0]
    codes = {v["code"] for v in first_rec["violations"]}
    assert {"task_hash_mismatch", "scorer_hash_mismatch"} <= codes
    # Because stop_on_invalidating_violation=True, remaining trials were not executed
    assert res["stopped_reason"] is not None
    assert res["records"][1]["outcome_kind"] == "not_executed"


def test_stage25_scorer_calibration_suite_validates_gold_alternatives_and_ben002():
    from benchmarks.codex_r.studies.stage2_validity_v1 import scorer_calibration

    report = scorer_calibration.run_scorer_calibration_suite()
    assert report["frozen_scorers_modified"] is False
    assert report["all_probes_matched_expected_behavior"] is True
    assert report["all_verifier_check_counts_consistent"] is True
    assert report["quarantined_tasks_due_to_scorer_limitations"] == [
        "D01",
        "D02",
        "D03",
        "E01",
        "E04",
        "E05",
    ]
