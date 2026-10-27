"""Offline B1 MCP description and interface contract tests."""

import asyncio
import csv
import io
import json
from argparse import Namespace
from pathlib import Path

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from benchmarks.codex_r import run_simple
from benchmarks.codex_r.analytics.import_results import (
    _b1_records_match_manifest,
    _run_metadata,
    _trial_plan,
)
from cran_knowledge_mcp.mcp_discovery import (
    CONTROL_SERVER_DESCRIPTION,
    TREATMENT_SERVER_DESCRIPTION,
    server_description,
)
from cran_knowledge_mcp.server import create_server


@pytest.mark.parametrize("toolset", ["legacy", "consolidated"])
def test_server_description_reaches_mcp_client_without_changing_tools(monkeypatch, toolset):
    assert server_description() == CONTROL_SERVER_DESCRIPTION
    captured_initializations = []
    original_initialize = ClientSession.initialize

    async def capture_initialize(session):
        result = await original_initialize(session)
        captured_initializations.append(result)
        return result

    monkeypatch.setattr(ClientSession, "initialize", capture_initialize)

    async def inspect_variant(variant):
        async with create_connected_server_and_client_session(
            create_server(toolset=toolset, mcp_discovery_variant=variant)
        ) as session:
            tools = (await session.list_tools()).tools
        return captured_initializations[-1], [
            tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools
        ]

    control_init, control_tools = asyncio.run(inspect_variant("control"))
    treatment_init, treatment_tools = asyncio.run(inspect_variant("treatment"))

    assert control_init.instructions == CONTROL_SERVER_DESCRIPTION
    assert treatment_init.instructions == TREATMENT_SERVER_DESCRIPTION
    assert "optional" in treatment_init.instructions.lower()
    assert "must" not in treatment_init.instructions.lower()
    assert control_tools == treatment_tools


@pytest.mark.parametrize("task", ["C01", "D01", "D03"])
def test_b1_variants_have_identical_advertised_interfaces(task):
    control = run_simple.mcp_discovery_metadata(task, "control")
    treatment = run_simple.mcp_discovery_metadata(task, "treatment")

    assert control["variant"] == "control"
    assert treatment["variant"] == "treatment"
    assert control["server_description_sha256"] != treatment["server_description_sha256"]
    assert control["advertised_interface_sha256"] == treatment["advertised_interface_sha256"]
    assert control["advertised_toolset_sha256"] == treatment["advertised_toolset_sha256"]
    assert control["tool_schemas_sha256"] == treatment["tool_schemas_sha256"]
    assert (
        control["individual_tool_descriptions_sha256"]
        == treatment["individual_tool_descriptions_sha256"]
    )


def test_b1_changes_only_server_variant_and_keeps_agent_request_constant(monkeypatch):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "id": "b1-session",
                "agent": body["agent"],
                "environment": {
                    "type": "self_hosted",
                    "id": "b1-environment",
                    "remote_url": "https://api.openai.com/v1/agents/api",
                },
            },
        )

    for _ in ("control", "treatment"):
        client = run_simple.SimpleClient(
            "application-test-key",
            "executor-test-key",
            transport=httpx.MockTransport(respond),
        )
        try:
            client.create_simple_session("medium", True, run_simple.suite_for("D01")[2], "standard")
        finally:
            client.close()

    assert requests[0] == requests[1]
    assert requests[0]["agent"]["instructions"] == run_simple.STANDARD_INSTRUCTIONS

    docker_calls = []

    def fake_docker(*args, **kwargs):
        if args[0] == "run":
            docker_calls.append(args)
        return None

    monkeypatch.setattr(run_simple, "docker", fake_docker)
    for variant in ("control", "treatment"):
        run_simple.start_mcp(
            "b1-mcp",
            "b1-network",
            "existing-mcp-image",
            toolset="consolidated",
            run_id="b1-run",
            trial_id="b1-trial",
            mcp_discovery_variant=variant,
        )

    def without_variant(args):
        result = []
        index = 0
        while index < len(args):
            if args[index] == "--env" and args[index + 1].startswith(
                f"{run_simple.MCP_DISCOVERY_ENV}="
            ):
                index += 2
            else:
                result.append(args[index])
                index += 1
        return result

    control_args, treatment_args = docker_calls
    assert without_variant(control_args) == without_variant(treatment_args)
    assert f"{run_simple.MCP_DISCOVERY_ENV}=control" in control_args
    assert f"{run_simple.MCP_DISCOVERY_ENV}=treatment" in treatment_args


def test_b1_trial_ids_pair_on_task_and_repetition():
    tasks = ["D03", "D01", "C01"]
    legacy = run_simple.planned_trials(tasks, ["with-mcp"], 1)
    control = run_simple.planned_trials(tasks, ["with-mcp"], 2, mcp_discovery="control")
    treatment = run_simple.planned_trials(tasks, ["with-mcp"], 2, mcp_discovery="treatment")

    assert [item[3] for item in legacy] == ["D03-B-1", "D01-B-1", "C01-B-1"]
    assert [(task, mode, repetition) for task, mode, repetition, _ in control] == [
        (task, mode, repetition) for task, mode, repetition, _ in treatment
    ]
    assert all(trial_id.endswith("-discovery-control") for *_, trial_id in control)
    assert all(trial_id.endswith("-discovery-treatment") for *_, trial_id in treatment)


def test_b1_single_run_plan_has_six_balanced_condition_pairs():
    plan = run_simple.planned_b1_trials(["D03", "D01", "C01"], 2)
    assert len(plan) == 12
    assert [item["execution_order"] for item in plan] == list(range(1, 13))
    assert {item["condition"] for item in plan} == {"control", "treatment"}
    pairs = {}
    for item in plan:
        pairs.setdefault((item["task"], item["repetition"]), []).append(item["condition"])
    assert len(pairs) == 6
    assert all(sorted(value) == ["control", "treatment"] for value in pairs.values())
    first = [
        min(
            (item for item in plan if (item["task"], item["repetition"]) == key),
            key=lambda i: i["execution_order"],
        )
        for key in pairs
    ]
    assert sum(item["condition"] == "control" for item in first) == 3
    assert sum(item["condition"] == "treatment" for item in first) == 3


def test_b1_comparison_summary_handles_partial_and_refuses_incompatible_scores():
    plan = run_simple.planned_b1_trials(["D03", "D01", "C01"], 2)
    manifest = {"run_id": "b1-offline", "trial_plan": plan}
    control_plan = next(
        item
        for item in plan
        if item["task"] == "D03" and item["repetition"] == 1 and item["condition"] == "control"
    )
    treatment_plan = next(
        item
        for item in plan
        if item["task"] == "D03" and item["repetition"] == 1 and item["condition"] == "treatment"
    )
    records = [
        {
            "trial_id": control_plan["trial_id"],
            "condition": "control",
            "status": "scored",
            "scorer_identity": "knowledge-pilot-v2",
            "score": {"passed": 2, "total": 4},
            "mcp_usage": {"calls": 0, "tool_search_calls": 0},
        },
        {
            "trial_id": treatment_plan["trial_id"],
            "condition": "treatment",
            "status": "scored",
            "scorer_identity": "knowledge-pilot-v2",
            "score": {"passed": 3, "total": 4},
            "mcp_usage": {"calls": 1, "tool_search_calls": 1},
            "mcp_telemetry": {"calls": [{"status": "error", "error_codes": ["docs_not_found"]}]},
        },
    ]
    failed_plan = next(
        item
        for item in plan
        if item["task"] == "D03" and item["repetition"] == 2 and item["condition"] == "control"
    )
    records.append(
        {
            "trial_id": failed_plan["trial_id"],
            "condition": "control",
            "status": "error",
            "error_type": "ScorerFailure",
            "scorer_identity": "knowledge-pilot-v2",
            "mcp_usage": {"calls": 0},
        }
    )
    summary = run_simple.build_b1_comparison(records, manifest)
    pair = next(
        item for item in summary["pairs"] if item["task"] == "D03" and item["repetition"] == 1
    )
    assert summary["planned_pairs"] == 6
    assert summary["scored_pairs"] == 1
    assert pair["score_comparable"] is True
    assert pair["delta_checks"] == 1
    assert pair["treatment"]["docs_not_found"] == 1
    assert pair["control"]["mcp_calls"] == 0
    incomplete = next(
        item for item in summary["pairs"] if item["task"] == "D03" and item["repetition"] == 2
    )
    assert incomplete["score_comparable"] is False
    assert incomplete["delta_checks"] is None
    assert incomplete["control"]["status"] == "error"


def test_b1_resume_keeps_condition_order_and_rejects_condition_drift():
    plan = run_simple.planned_b1_trials(["D03", "D01", "C01"], 2)
    experiment = {"run_id": "b1-resume", "trial_plan": plan, "trial_count": 12}
    planned = plan[0]
    record = {
        "run_id": "b1-resume",
        "trial_id": planned["trial_id"],
        "task": planned["task"],
        "mode": planned["mode"],
        "repetition": planned["repetition"],
        "condition": planned["condition"],
        "execution_order": planned["execution_order"],
        "status": "scored",
    }
    records, completed = run_simple.merge_resume_records(
        experiment, [], {record["trial_id"]: record}, {record["trial_id"]}
    )
    assert [item["trial_id"] for item in records] == [planned["trial_id"]]
    assert completed == {planned["trial_id"]}
    with pytest.raises(ValueError, match="condition mismatch"):
        run_simple.merge_resume_records(
            experiment,
            [],
            {record["trial_id"]: {**record, "condition": "treatment"}},
            {record["trial_id"]},
        )


def test_b1_experiment_manifest_saves_variant_and_per_task_interface_digest(monkeypatch):
    monkeypatch.setattr(run_simple.telemetry_experiment, "build", lambda **kwargs: {})
    monkeypatch.setattr(run_simple, "experiment_package_pins", lambda *args: {})
    monkeypatch.setattr(
        run_simple.knowledge_pilot,
        "provenance",
        lambda *args: {"public_spec_sha256": "spec-digest", "public_inputs": {}},
    )
    args = Namespace(
        run_id="b1-test",
        effort="medium",
        instructions="standard",
        modes=["with-mcp"],
        repetitions=2,
        timeout=900,
        knowledge_pilot_scorer="legacy",
        executor_image="executor-image",
        scorer_image="scorer-image",
        mcp_image="mcp-image",
        mcp_discovery="treatment",
        runtime_versions=None,
    )

    manifest = run_simple.write_experiment_manifest(
        "unused-output",
        args,
        {"executor": "executor-id", "scorer": "scorer-id"},
        ["D01"],
        write=False,
    )

    expected = run_simple.mcp_discovery_metadata("D01", "treatment")
    assert manifest["mcp_discovery"] == {
        "variant": "treatment",
        "server_description_sha256": expected["server_description_sha256"],
        "advertised_interface_sha256_by_task": {"D01": expected["advertised_interface_sha256"]},
    }
    assert all(item["trial_id"].endswith("-discovery-treatment") for item in manifest["trial_plan"])


def test_b1_single_run_manifest_captures_both_conditions_and_task_scoring(monkeypatch):
    monkeypatch.setattr(run_simple.telemetry_experiment, "build", lambda **kwargs: {})
    monkeypatch.setattr(run_simple, "experiment_package_pins", lambda *args: {})
    monkeypatch.setattr(
        run_simple.knowledge_pilot,
        "provenance",
        lambda task, scorer: {
            "public_spec_sha256": f"spec-{task}-{scorer}",
            "public_inputs": {},
        },
    )
    args = Namespace(
        run_id="b1-single-run",
        effort="medium",
        instructions="standard",
        modes=["with-mcp"],
        repetitions=2,
        timeout=900,
        knowledge_pilot_scorer="knowledge-pilot-v2",
        executor_image="rkmcp-codex-runtime:codex-0.163.0-bioc",
        scorer_image="codex-r-benchmark:pilot-bioc",
        mcp_image="cran-knowledge-mcp:shiny-quarto",
        mcp_discovery=None,
        experiment="b1-discovery",
        runtime_versions=None,
    )
    manifest = run_simple.write_experiment_manifest(
        "unused-output",
        args,
        {"executor": "executor-id", "scorer": "scorer-id", "mcp": "mcp-id"},
        ["D03", "D01", "C01"],
        write=False,
    )
    assert manifest["experiment_id"] == "b1-discovery"
    assert manifest["configuration_id"] == "b1-task-scoped-scorers"
    assert manifest["task_scorers"] == {
        "D03": "knowledge-pilot-v2",
        "D01": "knowledge-pilot-v2",
        "C01": "legacy",
    }
    assert manifest["function_discovery_policy"] == "disabled"
    b1_tools = [
        "search_packages",
        "get_package",
        "get_function_docs",
        "check_package_version",
        "check_r_compatibility",
        "search_r_documentation",
        "get_r_documentation_section",
        "get_framework_docs",
        "get_r_workflow_guidance",
        "analyze_r_source",
        "analyze_r_project",
        "recommend_technology_stack",
    ]
    for task_tools in manifest["mcp_server"]["allowed_tools_by_task"].values():
        assert task_tools == b1_tools
        assert "list_package_functions" not in task_tools
    for task_id, mode_tools in manifest["mcp_server"]["agent_tools_by_task_mode"].items():
        assert mode_tools["with-mcp"] == manifest["mcp_server"]["allowed_tools_by_task"][task_id]
    assert set(manifest["mcp_discovery"]["conditions"]) == {"control", "treatment"}
    control = manifest["mcp_discovery"]["conditions"]["control"]
    treatment = manifest["mcp_discovery"]["conditions"]["treatment"]
    assert control["server_description_sha256"] != treatment["server_description_sha256"]
    for key in (
        "advertised_interface_sha256_by_task",
        "advertised_toolset_sha256_by_task",
        "tool_schemas_sha256_by_task",
        "individual_tool_descriptions_sha256_by_task",
    ):
        assert control[key] == treatment[key]
    assert len(manifest["trial_plan"]) == 12
    records = {}
    for item in manifest["trial_plan"]:
        condition = item["condition"]
        task = item["task"]
        digests = manifest["mcp_discovery"]["conditions"][condition]
        records[item["trial_id"]] = {
            "experiment_id": "b1-discovery",
            "experiment_version": manifest["experiment_version"],
            "condition": condition,
            "mcp_discovery_variant": condition,
            "scorer_identity": manifest["task_scorers"][task],
            "scorer_sha256": manifest["scorer_sha256_by_task"][task],
            "task_prompt_sha256": manifest["prompt_sha256_by_task"][task],
            "task_manifest_sha256": manifest["task_manifest_sha256"],
            "agent_instructions_sha256": manifest["agent_instructions_sha256"],
            "mcp_server_description_sha256": digests["server_description_sha256"],
            "mcp_advertised_interface_sha256": digests["advertised_interface_sha256_by_task"][task],
            "mcp_advertised_toolset_sha256": digests["advertised_toolset_sha256_by_task"][task],
            "mcp_tool_schemas_sha256": digests["tool_schemas_sha256_by_task"][task],
            "mcp_individual_tool_descriptions_sha256": digests[
                "individual_tool_descriptions_sha256_by_task"
            ][task],
        }
    normalized_plan = [
        {
            "planned_trial_id": item["trial_id"],
            "task_id": item["task"],
            "condition": item["condition"],
        }
        for item in manifest["trial_plan"]
    ]
    assert _b1_records_match_manifest(records, normalized_plan, manifest)
    first_treatment = next(
        item for item in manifest["trial_plan"] if item["condition"] == "treatment"
    )
    records[first_treatment["trial_id"]]["mcp_tool_schemas_sha256"] = "0" * 64
    assert not _b1_records_match_manifest(records, normalized_plan, manifest)
    records[first_treatment["trial_id"]]["mcp_tool_schemas_sha256"] = manifest["mcp_discovery"][
        "conditions"
    ]["treatment"]["tool_schemas_sha256_by_task"][first_treatment["task"]]
    manifest.update(
        created_at_utc="2026-10-25T10:00:00Z",
        model="gpt-6-luna",
        effort="medium",
        instructions="standard",
        tasks=["D03", "D01", "C01"],
        modes=["with-mcp"],
        repetitions=2,
        scorer_versions={"knowledge_pilot_scorer": "knowledge-pilot-v2"},
    )
    trial_rows = []
    for item in manifest["trial_plan"]:
        task = item["task"]
        scorer = manifest["task_scorers"][task]
        result = records[item["trial_id"]]
        configuration = (
            "consolidated-v2" if task != "C01" else run_simple.knowledge_pilot.configuration()["id"]
        )
        result.update(
            configuration_id=configuration,
            task=task,
            mode="with-mcp",
            repetition=item["repetition"],
            model="gpt-6-luna",
            effort="medium",
            instructions="standard",
            status="scored",
            completed_at="2026-10-25T10:01:00Z",
            score={"passed": 2, "total": 4, "scorer_version": scorer},
        )
        trial_rows.append(
            {
                "trial_id": item["trial_id"],
                "task_id": task,
                "mode": "with-mcp",
                "condition": item["condition"],
                "execution_order": item["execution_order"],
                "repetition": item["repetition"],
                "finalized": True,
                "passed": 2,
                "total": 4,
                "status": "scored",
                "interrupted": False,
                "scorer_version": scorer,
                "model": "gpt-6-luna",
                "effort": "medium",
                "instructions": "standard",
                "configuration": configuration,
            }
        )
    metadata = _run_metadata(
        manifest,
        records,
        _trial_plan(manifest)[0],
        "valid",
        "completed",
        trial_rows,
        [],
        False,
        None,
        {},
    )
    assert metadata["full_status"] == "full_comparable"
    assert metadata["conditions_json"] == '["control", "treatment"]'


def test_b1_digests_are_saved_in_results_json_and_csv(monkeypatch):
    metadata = run_simple.mcp_discovery_metadata("D01", "treatment")
    record = {
        "trial": "D01-B-1-discovery-treatment",
        "mcp_discovery_variant": metadata["variant"],
        "mcp_server_description_sha256": metadata["server_description_sha256"],
        "mcp_advertised_interface_sha256": metadata["advertised_interface_sha256"],
    }
    saved = {}
    original_write_text = Path.write_text
    original_open = Path.open

    def capture_write_text(path, data, *args, **kwargs):
        if path.name == "results.json":
            saved[path.name] = data
            return len(data)
        return original_write_text(path, data, *args, **kwargs)

    class CsvCapture(io.StringIO):
        def __init__(self, name):
            super().__init__(newline="")
            self.name = name

        def __exit__(self, exc_type, exc_value, traceback):
            saved[self.name] = self.getvalue()
            return super().__exit__(exc_type, exc_value, traceback)

    def capture_open(path, mode="r", *args, **kwargs):
        if path.suffix == ".csv" and mode == "w":
            return CsvCapture(path.name)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", capture_write_text)
    monkeypatch.setattr(Path, "open", capture_open)
    run_simple.save_results(Path("memory-results"), [record])

    saved_json = json.loads(saved["results.json"])[0]
    assert saved_json["mcp_discovery_variant"] == "treatment"
    with io.StringIO(saved["results.csv"]) as stream:
        row = next(csv.DictReader(stream))
    assert row["mcp_discovery_variant"] == "treatment"
    assert row["mcp_server_description_sha256"] == metadata["server_description_sha256"]
    assert row["mcp_advertised_interface_sha256"] == metadata["advertised_interface_sha256"]


def test_b1_save_results_writes_partial_comparison_and_condition_columns(monkeypatch):
    plan = run_simple.planned_b1_trials(["D03", "D01", "C01"], 2)
    manifest = {
        "run_id": "b1-save",
        "experiment_id": "b1-discovery",
        "experiment_version": "1.0",
        "trial_plan": plan,
    }
    first_pair = [item for item in plan if item["task"] == "D03" and item["repetition"] == 1]
    records = [
        {
            "run_id": "b1-save",
            "trial_id": item["trial_id"],
            "task": item["task"],
            "mode": item["mode"],
            "condition": item["condition"],
            "execution_order": item["execution_order"],
            "experiment_id": "b1-discovery",
            "experiment_version": "1.0",
            "scorer_identity": "knowledge-pilot-v2",
            "scorer_sha256": "a" * 64,
            "agent_instructions_sha256": "b" * 64,
            "task_prompt_sha256": "c" * 64,
            "task_manifest_sha256": "d" * 64,
            "status": "scored",
            "score": {"passed": 2 if item["condition"] == "control" else 3, "total": 4},
            "mcp_usage": {"calls": 0, "tool_search_calls": 0},
        }
        for item in first_pair
    ]
    saved = {}
    original_write_text = Path.write_text
    original_read_text = Path.read_text
    original_open = Path.open

    def capture_write_text(path, data, *args, **kwargs):
        if path.name in {"results.json", "b1_comparison.json"}:
            saved[path.name] = data
            return len(data)
        return original_write_text(path, data, *args, **kwargs)

    def capture_read_text(path, *args, **kwargs):
        if path.name == "experiment.json":
            return json.dumps(manifest)
        return original_read_text(path, *args, **kwargs)

    class CsvCapture(io.StringIO):
        def __init__(self, name):
            super().__init__(newline="")
            self.name = name

        def __exit__(self, exc_type, exc_value, traceback):
            saved[self.name] = self.getvalue()
            return super().__exit__(exc_type, exc_value, traceback)

    def capture_open(path, mode="r", *args, **kwargs):
        if path.suffix == ".csv" and mode == "w":
            return CsvCapture(path.name)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", capture_write_text)
    monkeypatch.setattr(Path, "read_text", capture_read_text)
    monkeypatch.setattr(Path, "open", capture_open)
    run_simple.save_results(Path("memory-b1-results"), records)

    summary = json.loads(saved["b1_comparison.json"])
    assert summary["planned_pairs"] == 6
    assert summary["scored_pairs"] == 1
    pair = next(item for item in summary["pairs"] if item["task"] == "D03")
    assert pair["delta_checks"] == 1
    with io.StringIO(saved["results.csv"]) as stream:
        rows = list(csv.DictReader(stream))
    assert {row["condition"] for row in rows} == {"control", "treatment"}
    assert all(row["scorer_identity"] == "knowledge-pilot-v2" for row in rows)
