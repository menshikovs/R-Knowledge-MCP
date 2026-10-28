"""End-to-end telemetry check before D02.

Real: the MCP server process in a Docker container (current ``src`` tree, real entry point,
real telemetry wrapper, real network isolation and ``docker logs`` collection), the runner
(``run_simple.main`` including run_trial, cleanup, scoring, CSV/JSONL export) and the D01
scorer. Replaced: the Managed Agents HTTP API (a deterministic fake that speaks the same
protocol through ``httpx.MockTransport``), the executor container, and CRAN (fixed fixtures
served by the container's HTTP transport). No request leaves the machine and no OpenAI API
is used.
"""

import csv
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from conftest import archive

from benchmarks.codex_r import run_simple as simple
from benchmarks.codex_r.runner import bench
from benchmarks.codex_r.telemetry import aggregate, errors, experiment, schema

# Built from the current checkout by the `mcp_image` fixture. A hand-built tag such as the
# runner's default (cran-knowledge-mcp:shiny-quarto) can predate the code under test.
MCP_IMAGE = "cran-knowledge-mcp:telemetry-test"
REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = Path(__file__).parent / "data" / "mcp_fixture_launcher.py"
KEYS = ("integration-app-key-0001", "integration-exec-key-0002")
REAL_CLIENT = simple.SimpleClient
REAL_DOCKER = simple.docker
D01_ANSWER = {
    "r_version": "4.5.2",
    "rationale": "climenu provides keyboard single and multiple selection with stable values.",
    "recommendations": [
        {
            "package": "climenu",
            "version": "0.2.0",
            "source_url": "https://cran.r-project.org/src/contrib/climenu_0.2.0.tar.gz",
            "documentation_url": "https://cran.r-project.org/web/packages/climenu/climenu.pdf",
            "feature_ids": ["keyboard_single_multi_select", "stable_return_values"],
            "caveat_ids": ["menu_focused"],
        }
    ],
}

# (tool, arguments) in the order the fake agent issues them.
CALLS = [
    ("get_package", {"package": "climenu"}),  # 1 ok, upstream fetches
    ("get_package", {"package": "climenu"}),  # 2 ok, identical, served from the cache
    ("get_function_docs", {"package": "climenu", "function": "menu"}),  # 3 ok
    ("get_function_docs", {"package": "climenu", "function": "Menu"}),  # 4 docs_not_found
    ("get_function_docs", {"package": "climenu", "function": "Menu"}),  # 5 identical after error
    ("get_package", {"package": "pkgpartial", "include": ["metadata", "vignettes"]}),  # 6 partial
    ("get_package", {"package": "MissingPkg"}),  # 7 nested package_not_found
    ("get_function_docs", {"package": "climenu", "function": "menu", "package_version": "7.7.7"}),
    ("get_package", {"package": "../bad"}),  # 9 invalid_input, no repository lookup
]
EXPECTED_KINDS = [
    "first",
    "identical",
    "first",
    "similar",
    "identical_after_error",
    "first",
    "first",
    "similar",
    "first",
]
FAILED_CALLS = {4, 5, 7, 8, 9}
PARTIAL_CALLS = {6}


def _desc(name, version):
    return f"Package: {name}\nVersion: {version}\nTitle: Synthetic {name}\nEncoding: UTF-8\n"


def write_fixtures(root):
    """CRAN stand-in: two packages; pkgpartial has no package page, so vignettes fail."""
    root.mkdir()
    rd = "".join(
        f"\\name{{{n}}}\n\\alias{{{n}}}\n\\title{{Synthetic {n}}}\n\\description{{Fixture.}}\n"
        for n in ("menu",)
    )
    files = {
        "packages.txt": (
            b"Package: climenu\nVersion: 0.2.0\nLicense: MIT\n\n"
            b"Package: pkgpartial\nVersion: 1.0\nLicense: MIT\n"
        ),
        "climenu.desc": _desc("climenu", "0.2.0").encode(),
        "pkgpartial.desc": _desc("pkgpartial", "1.0").encode(),
        "climenu.tgz": archive(
            {
                "climenu/DESCRIPTION": _desc("climenu", "0.2.0"),
                "climenu/man/menu.Rd": rd,
                "climenu/man/checkbox.Rd": rd.replace("menu", "checkbox"),
                "climenu/man/select.Rd": rd.replace("menu", "select"),
            }
        ),
    }
    for name, content in files.items():
        (root / name).write_bytes(content)
    routes = {
        "/src/contrib/PACKAGES": "packages.txt",
        "/web/packages/climenu/DESCRIPTION": "climenu.desc",
        "/web/packages/pkgpartial/DESCRIPTION": "pkgpartial.desc",
        "/src/contrib/climenu_0.2.0.tar.gz": "climenu.tgz",
    }
    (root / "routes.json").write_text(json.dumps(routes), encoding="utf-8")
    shutil.copy(LAUNCHER, root / "mcp_fixture_launcher.py")
    return root


class EventStream(httpx.SyncByteStream):
    """Server-sent events produced lazily, so MCP calls happen while the runner reads."""

    def __init__(self, events):
        self.events = events

    def __iter__(self):
        for event in self.events:
            yield f"data: {json.dumps(event)}\n\n".encode()


class Lab:
    """Fake Managed Agents API plus a driver that talks to the real MCP container."""

    def __init__(self, tmp_path, monkeypatch, *, ending="completed", deletion="confirmed"):
        self.ending, self.deletion = ending, deletion
        self.fixtures = write_fixtures(tmp_path / "fixtures")
        self.results = tmp_path / "results"
        self.workspace = None
        self.mcp_name = None
        self.created = {"containers": [], "networks": []}
        self.responses = []  # (tool, arguments, CallToolResult dict) as returned by the server
        self.interrupt_after = 4
        self.second_interrupt = False
        self.score_override = None
        for name in simple.KEY_NAMES:
            monkeypatch.setenv(name, KEYS[simple.KEY_NAMES.index(name)])
        monkeypatch.setattr(simple, "SimpleClient", self.client)
        monkeypatch.setattr(simple, "docker", self.docker)
        monkeypatch.setattr(simple, "start_executor", lambda *args: None)
        real_prepare = simple.knowledge_pilot.prepare
        monkeypatch.setattr(simple.knowledge_pilot, "prepare", self.prepare(real_prepare))
        real_score = simple.knowledge_pilot.score
        monkeypatch.setattr(
            simple.knowledge_pilot,
            "score",
            lambda *a, **k: self.score_override or real_score(*a, **k),
        )

    # -- runner seams ---
    def prepare(self, real):
        def prepare(task, destination, scorer_choice="legacy"):
            result = real(task, destination, scorer_choice)
            self.workspace = Path(destination)
            return result

        return prepare

    def client(self, *keys):
        return REAL_CLIENT(*keys, transport=httpx.MockTransport(self.respond))

    def docker(self, *args, **kwargs):
        args = list(args)
        if args[0] == "run" and "cran_knowledge_mcp.server" in args:
            self.mcp_name = args[args.index("--name") + 1]
            self.created["containers"].append(self.mcp_name)
            entry = args.index("--entrypoint")
            args[entry:entry] = [
                "--mount",
                f"type=bind,source={self.fixtures},target=/fixture,readonly",
            ]
            module = args.index("cran_knowledge_mcp.server")
            args[module - 1 : module + 1] = ["/fixture/mcp_fixture_launcher.py"]
        elif args[:2] == ["network", "create"]:
            self.created["networks"].append(args[2])
        if any(isinstance(a, str) and a.endswith("-exec") for a in args):
            if args[0] == "inspect":  # the executor container is not started in this test
                return subprocess.CompletedProcess(args, 0, '{"Running": true}', "")
            if args[0] in {"logs", "rm"}:
                return subprocess.CompletedProcess(args, 0, "", "")
        return REAL_DOCKER(*args, **kwargs)

    # -- fake Managed Agents API ---
    def respond(self, request):
        path = request.url.path
        if request.method == "POST" and path.endswith("/sessions"):
            return httpx.Response(
                201,
                json={
                    "id": "sess_integration",
                    "agent": json.loads(request.content)["agent"],
                    "environment": {
                        "type": "self_hosted",
                        "id": "env_integration",
                        "remote_url": "https://api.openai.com/v1/agents/api",
                    },
                },
            )
        if request.method == "GET" and path.endswith("/events"):
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=EventStream(self.agent_events()),
            )
        if request.method == "POST" and b"input.cancel" in request.content:
            if self.second_interrupt:
                os.kill(os.getpid(), signal.SIGINT)
            return httpx.Response(200, json={})
        if request.method == "DELETE":
            if self.deletion == "failed":
                return httpx.Response(403, json={"error": "denied"})
            return httpx.Response(200, json={"id": "sess_integration", "deleted": True})
        if request.method == "GET":
            return httpx.Response(200, json={"usage": None, "environment": {"status": "pending"}})
        return httpx.Response(200, json={})

    def agent_events(self):
        yield {"type": "agent.session.environment.connected"}
        yield {"type": "agent.session.turn.started"}
        self.rpc("tools/list", {})  # MCP discovery, as the real client does once
        for index, (tool, arguments) in enumerate(CALLS, start=1):
            if self.ending == "ctrl_c" and index > self.interrupt_after:
                raise KeyboardInterrupt()
            if self.ending == "turn_failed" and index > self.interrupt_after:
                yield {"type": "agent.session.turn.failed"}
                return
            item = {"id": f"exec_{index:02d}", "type": "mcp_call", "name": tool}
            yield {
                "type": "agent.session.turn.item.added",
                "item": {**item, "status": "in_progress", "payload_redacted": True},
            }
            result = self.rpc("tools/call", {"name": tool, "arguments": arguments})
            self.responses.append((tool, arguments, result))
            status = "failed" if result.get("isError") else "completed"
            yield {
                "type": "agent.session.turn.item.done",
                "item": {**item, "status": status, "payload_redacted": True},
            }
        (self.workspace / "answer.json").write_text(json.dumps(D01_ANSWER), encoding="utf-8")
        yield {"type": "agent.session.turn.completed"}

    def rpc(self, method, params):
        """One JSON-RPC request to the MCP server inside the container."""
        script = (
            "import sys, urllib.request\n"
            "request = urllib.request.Request('http://127.0.0.1:8000/mcp', "
            "data=sys.stdin.buffer.read(), headers={'Content-Type': 'application/json', "
            "'Accept': 'application/json, text/event-stream', "
            "'MCP-Protocol-Version': '2025-06-18', 'Host': 'r-knowledge-mcp:8000'})\n"
            "print(urllib.request.urlopen(request, timeout=60).read().decode())\n"
        )
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        completed = subprocess.run(
            ["docker", "exec", "-i", self.mcp_name, "python", "-c", script],
            input=body,
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        return json.loads(completed.stdout)["result"]

    # -- running and cleaning up ---
    def run(self):
        code = simple.main(
            [
                "--effort",
                "medium",
                "--tasks",
                "D01",
                "--modes",
                "with-mcp",
                "--results",
                str(self.results),
                "--mcp-image",
                MCP_IMAGE,
                "--timeout",
                "300",
            ]
        )
        (self.run_dir,) = [p for p in self.results.iterdir() if p.is_dir()]
        return code

    def remove_resources(self):
        for name in self.created["containers"]:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        for name in self.created["networks"]:
            subprocess.run(["docker", "network", "rm", name], capture_output=True, check=False)

    def exists(self, container):
        listed = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^{container}$", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return container in listed.stdout.split()

    # -- reading what the runner wrote ---
    @property
    def events(self):
        text = (self.run_dir / "telemetry.jsonl").read_text(encoding="utf-8")
        assert text.endswith("\n")
        return [json.loads(line) for line in text.splitlines()]

    @property
    def record(self):
        return json.loads((self.run_dir / "results.json").read_text(encoding="utf-8"))[0]


def _docker_ready():
    if sys.platform != "linux" or not shutil.which("docker"):
        return "Linux with a Docker CLI is required"
    for image in ("rkmcp-codex-runtime:codex-0.163.0", "codex-r-benchmark:pilot"):
        probe = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
        if probe.returncode:
            return f"image {image} is not available locally"
    return None


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(_docker_ready() is not None, reason=str(_docker_ready())),
]


@pytest.fixture(scope="module", autouse=True)
def mcp_image():
    """Build the MCP image from this checkout so the tests never run against a stale local tag."""
    subprocess.run(
        ["docker", "build", "-q", "-t", MCP_IMAGE, str(REPO_ROOT)],
        check=True,
        capture_output=True,
        timeout=900,
    )
    return MCP_IMAGE


@pytest.fixture
def lab(tmp_path, monkeypatch):
    holder = {}

    def make(**kwargs):
        holder["lab"] = Lab(tmp_path, monkeypatch, **kwargs)
        return holder["lab"]

    yield make
    if "lab" in holder:
        holder["lab"].remove_resources()


def tool_events(events, source):
    return [
        event
        for event in events
        if event["event_type"] in schema.TOOL_TERMINAL and event["source"] == source
    ]


def without_key(value, key):
    if isinstance(value, dict):
        return {k: without_key(v, key) for k, v in value.items() if k != key}
    if isinstance(value, list):
        return [without_key(item, key) for item in value]
    return value


def linear_percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


# ------------------------------------------------------------------------------------------
def test_full_chain_with_real_mcp_container(lab):
    scenario = lab()
    assert scenario.run() == 0
    events, record = scenario.events, scenario.record

    # chain and ordering of runner-observed stages ---
    kinds = [e["event_type"] for e in events]
    runner_order = [
        "benchmark.run.started",
        "benchmark.trial.started",
        "agent.session.created",
        "agent.turn.started",
        "agent.turn.completed",
        "cleanup.started",  # the runner releases resources before it exports and scores
        "artifact.export.completed",
        "scorer.started",
        "scorer.completed",
    ]
    positions = [kinds.index(name) for name in runner_order]
    assert positions == sorted(positions)
    assert kinds[-2:] == ["benchmark.trial.completed", "benchmark.run.completed"]
    assert "mcp.discovery.started" not in kinds  # not observable, never invented
    (discovery,) = [e for e in events if e["event_type"] == "mcp.discovery.completed"]
    assert discovery["observation"] == "server_audit_after_trial"
    assert discovery["list_tools_requests"] == 1  # the one tools/list the fake agent sent
    assert scenario.record["mcp_server_audit"]["list_tools_requests"] == 1

    # schema, ids, uniqueness ---
    assert schema.validate_stream(events) == []
    assert {e["schema_version"] for e in events} == {schema.SCHEMA_VERSION}
    assert schema.SCHEMA_VERSION == "1.2"
    run_id = scenario.run_dir.name
    assert {e["run_id"] for e in events} == {run_id}
    trial_events = [e for e in events if "trial_id" in e]
    assert {e["trial_id"] for e in trial_events} == {"D01-B-1"}
    assert len({e["trace_id"] for e in trial_events}) == 1
    client = [e for e in events if e["source"] == "agent_stream" and "call_id" in e]
    server = tool_events(events, "mcp_server")
    starts = [e for e in client if e["event_type"] == "mcp.tool.started"]
    assert len(starts) == len(CALLS) == len(server) == 9
    assert len({e["call_id"] for e in starts}) == 9
    assert len({e["call_id"] for e in server}) == 9
    assert {e["call_id"] for e in starts}.isdisjoint({e["call_id"] for e in server})
    assert not [
        e for e in events if e["source"] == "mcp_server" and e["event_type"].endswith("started")
    ]

    # client/server: only an unconfirmed ordinal link, never a shared id ---
    assert {e["correlation"] for e in server} == {"ordinal_unconfirmed"}
    assert [e["correlated_call_id"] for e in server] == [e["call_id"] for e in starts]
    assert all(e["clock"] == "server_process" for e in server)
    assert all(e["clock"] == "trial" for e in client)

    # outcomes: counts follow the observed calls ---
    for number, event in enumerate(server, start=1):
        assert event["is_error"] is (number in FAILED_CALLS)
        assert event["event_type"] == (
            "mcp.tool.failed" if number in FAILED_CALLS else "mcp.tool.completed"
        )
        assert event["partial"] is (
            True if number in PARTIAL_CALLS else None if number in FAILED_CALLS else False
        )
    client_done = [e for e in client if e["event_type"] in schema.TOOL_TERMINAL]
    assert [e["is_error"] for e in client_done] == [n in FAILED_CALLS for n in range(1, 10)]
    overall = record["mcp_metrics"]["overall"]
    assert (overall["mcp_calls_attempted"], overall["mcp_calls_succeeded"]) == (9, 3)
    assert (overall["mcp_calls_failed"], overall["mcp_calls_partial"]) == (5, 1)
    assert overall["mcp_calls_unresolved"] == 0
    by_tool = record["mcp_metrics"]["by_tool"]
    assert (
        by_tool["get_package"]["mcp_calls_attempted"],
        by_tool["get_package"]["mcp_calls_failed"],
    ) == (5, 2)
    assert (
        by_tool["get_function_docs"]["mcp_calls_attempted"],
        by_tool["get_function_docs"]["mcp_calls_failed"],
    ) == (4, 3)

    # error sources, categories ---
    assert server[6]["error_codes"] == ["package_not_found"]  # nested errors[].error.code
    assert scenario.responses[6][2]["structuredContent"].get("error") is None
    assert server[3]["error_codes"] == ["docs_not_found"]
    assert server[7]["error_codes"] == ["requested_version_unavailable"]
    assert server[8]["error_codes"] == ["invalid_input"]
    assert server[5]["partial"] is True and server[5]["verification_status"] == "partial"
    assert server[5]["error_codes"] == ["not_found"]  # the failed vignettes section, kept as is
    mcp_errors = {
        (e["reason_code"], e["category"], e["source_code"]): e["count"]
        for e in record["error_summary"]["mcp_errors"]
    }
    assert mcp_errors[("MCP_PROVIDER_ERROR", "not_found", "docs_not_found")] == 2
    assert mcp_errors[("MCP_PROVIDER_ERROR", "not_found", "package_not_found")] == 1
    assert (
        mcp_errors[("MCP_PROVIDER_ERROR", "version_mismatch", "requested_version_unavailable")] == 1
    )
    assert mcp_errors[("MCP_PROVIDER_ERROR", "invalid_request", "invalid_input")] == 1
    assert mcp_errors[("MCP_PARTIAL_RESULT", "partial_result", "verification_partial")] == 1
    assert overall["mcp_version_mismatch_count"] == 1
    assert record["error_summary"]["primary_error"] is None  # tool errors did not fail the trial

    # the improved docs_not_found really reaches the model-visible result ---
    hint = scenario.responses[3][2]["structuredContent"]["error"]
    assert hint["code"] == "docs_not_found" and hint["alias_count"] == 3
    assert hint["available_aliases"] == ["checkbox", "menu", "select"]

    # sizes: content and structuredContent are separate, the duplicate counts once ---
    for event, (_, _, result) in zip(server, scenario.responses, strict=True):
        text = result["content"][0]["text"]
        structured = json.dumps(
            result["structuredContent"], ensure_ascii=False, separators=(",", ":")
        )
        assert event["text_content_bytes"] == len(text.encode())
        assert event["structured_bytes"] == len(structured.encode())
        assert event["content_duplicates_structured"] is True
        assert event["useful_bytes"] == event["text_content_bytes"]
        assert event["result_bytes"] > event["text_content_bytes"] + event["structured_bytes"]
    assert overall["mcp_result_bytes_total"] == sum(e["result_bytes"] for e in server)
    assert overall["mcp_unique_payload_bytes_total"] == sum(e["useful_bytes"] for e in server)
    assert overall["mcp_unique_payload_bytes_total"] < overall["mcp_result_bytes_total"] * 0.6

    # latency percentiles come from the individual durations ---
    durations = [e["duration_ms"] for e in server]
    assert overall["mcp_latency_observations"] == 9
    assert overall["mcp_latency_p50_ms"] == linear_percentile(durations, 0.5)
    assert overall["mcp_latency_p95_ms"] == linear_percentile(durations, 0.95)

    # repeats are recognized without storing arguments ---
    assert [e["repeat_kind"] for e in server] == EXPECTED_KINDS
    assert (overall["mcp_repeated_identical_calls"], overall["mcp_repeated_after_error"]) == (2, 1)
    assert overall["mcp_similar_calls"] == 2
    fingerprints = [e["argument_fingerprint"] for e in server]
    assert fingerprints[0] == fingerprints[1] and fingerprints[3] == fingerprints[4]
    assert len(set(fingerprints)) == 7
    forbidden = ("Menu", "MissingPkg", "../bad", "7.7.7")
    for artifact in ("telemetry.jsonl", "results.json", "mcp_calls.csv", "mcp_metrics.csv"):
        text = (scenario.run_dir / artifact).read_text(encoding="utf-8")
        if artifact == "results.json":
            # The only deliberate copy of validated package/function/version names is the
            # discovery sidecar projection; every other field must stay free of arguments.
            text = json.dumps(without_key(json.loads(text), "discovery_request_projection"))
        assert not [marker for marker in forbidden if marker in text], artifact
        assert not [key for key in KEYS if key in text], artifact

    # cache: scope is repository HTTP lookups; the denominator is hits + upstream requests ---
    assert server[0]["cache_network_requests"] > 0 and server[0]["cache_hits"] == 0
    assert server[1]["cache_network_requests"] == 0 and server[1]["cache_hits"] > 0
    assert (server[8]["cache_hits"], server[8]["cache_network_requests"]) == (0, 0)
    hits = sum(e["cache_hits"] for e in server)
    lookups = hits + sum(e["cache_network_requests"] for e in server)
    assert overall["mcp_cache_lookups"] == lookups > hits > 0
    assert overall["mcp_cache_hit_rate"] == round(hits / lookups, 4)

    # unknown stays null ---
    assert record["usage"] is None and record["cost"] is None
    usage = record["mcp_metrics"]["api_usage"]
    assert usage["input_tokens"] is usage["total_tokens"] is usage["cost"] is None
    done = next(e for e in events if e["event_type"] == "benchmark.trial.completed")
    assert done["api_usage_status"] == "unavailable" and done["api_total_tokens"] is None
    assert overall["mcp_output_truncation_count"] == 0  # every call reported the flag
    assert all(e["source_count"] is not None for e in server)

    # scoring, cleanup, files ---
    assert record["score"]["passed"] == record["score"]["total"] == 4
    assert record["score"]["scorer_version"] == "d-recommendation-2"
    assert record["cleanup_completed"] is True and record["error_summary"]["cleanup_errors"] == []
    completed = {e["cleanup_operation"] for e in events if e["event_type"] == "cleanup.completed"}
    assert {"delete_session", "mcp_audit", "remove_mcp", "remove_network"} <= completed
    assert not scenario.exists(scenario.mcp_name)  # the real container is gone
    assert record["configuration_id"] == "consolidated-v1.1"

    # metrics computed from the JSONL alone equal those stored with the result ---
    rebuilt = aggregate.summarize_trial({"trial_id": "D01-B-1", "mode": "with-mcp"}, events)
    assert rebuilt["overall"] == overall and rebuilt["by_tool"] == by_tool
    with (scenario.run_dir / "mcp_metrics.csv").open(encoding="utf-8") as stream:
        rows = {row["tool"]: row for row in csv.DictReader(stream)}
    assert set(rows) == {"*", "get_function_docs", "get_package"}
    assert rows["*"]["mcp_calls_attempted"] == "9" and rows["*"]["mcp_calls_partial"] == "1"
    assert float(rows["*"]["mcp_cache_hit_rate"]) == overall["mcp_cache_hit_rate"]
    assert rows["*"]["metrics_source"] == "telemetry_jsonl"
    calls_csv = (scenario.run_dir / "mcp_calls.csv").read_text(encoding="utf-8").splitlines()
    assert len(calls_csv) == 1 + 9 and "package_not_found" in "\n".join(calls_csv)


def test_experiment_configuration_is_recorded_without_secrets(lab):
    scenario = lab()
    assert scenario.run() == 0
    experiment_record = json.loads(
        (scenario.run_dir / "experiment.json").read_text(encoding="utf-8")
    )
    repo = bench.REPO
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    assert experiment_record["repository"]["revision"] == head
    assert isinstance(experiment_record["repository"]["dirty"], bool)
    assert experiment_record["configuration_id"] == "consolidated-v1.1"
    server = experiment_record["mcp_server"]
    assert server["toolset"] == "consolidated" and server["registered_tool_count"] == 16
    assert set(server["allowed_tools"]) < set(server["registered_tools"])
    assert server["allowed_tool_count"] == len(server["allowed_tools"]) == 13
    assert "list_package_functions" in server["allowed_tools"]
    assert not set(server["allowed_tools"]) & {
        "build_r_prompt",
        "get_r_prompt_context",
        "validate_r_prompt",
    }
    assert server["package_version"] == "0.1.0"
    assert server["source_sha256"] == experiment.tree_sha256(repo / "src")
    image = subprocess.run(
        ["docker", "image", "inspect", MCP_IMAGE, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert experiment_record["images"]["mcp"] == image and image.startswith("sha256:")
    assert experiment_record["telemetry_schema_version"] == "1.2"
    assert experiment_record["scorer_versions"]["d_recommendation"] == "d-recommendation-2"
    assert (experiment_record["model"], experiment_record["effort"]) == ("gpt-6-luna", "medium")
    assert experiment_record["tasks"] == ["D01"] and experiment_record["modes"] == ["with-mcp"]
    assert experiment_record["environment"]["r_version"] == "4.5.2"
    assert len(experiment_record["environment"]["renv_lock_sha256"]) == 64
    text = json.dumps(experiment_record)
    assert not [key for key in KEYS if key in text]
    assert "OPENAI" not in text and "API_KEY" not in text.upper()


def test_scorer_failure_is_reported_as_scorer_infrastructure_with_mcp_data_intact(lab):
    scenario = lab()
    scenario.score_override = {
        "status": "scoring_error",
        "passed": None,
        "total": 4,
        "fully_correct": None,
        "reason": "exit_125",
        "failed_checks": None,
        "details": [],
        "environment": None,
        "artifacts": {},
    }
    assert scenario.run() == 1
    events, record = scenario.events, scenario.record
    assert schema.validate_stream(events) == []
    assert record["status"] == "scoring_error"
    primary = record["error_summary"]["primary_error"]
    assert (primary["reason_code"], primary["source_code"]) == ("SCORER_INFRA_ERROR", "exit_125")
    scored = next(e for e in events if e["event_type"] == "scorer.completed")
    assert scored["scorer_status"] == "scoring_error" and scored["passed"] is None
    assert record["mcp_metrics"]["overall"]["mcp_calls_attempted"] == 9
    assert len(tool_events(events, "mcp_server")) == 9
    # normal "not found" answers stay in mcp_errors and are not blamed for the scoring failure
    assert primary["category"] == "protocol" or primary["category"] == "infrastructure"
    assert record["error_summary"]["mcp_errors"]


def test_first_ctrl_c_runs_cleanup_and_leaves_valid_jsonl(lab):
    scenario = lab(ending="ctrl_c")
    scenario.interrupt_after = 4
    assert scenario.run() == 130
    events, record = scenario.events, scenario.record
    assert schema.validate_stream(events) == []
    assert record["status"] == "interrupted" and record["interrupted"] is True
    assert record["cleanup_completed"] is True and not scenario.exists(scenario.mcp_name)
    done = next(e for e in events if e["event_type"] == "benchmark.trial.completed")
    assert done["primary_error"]["reason_code"] == "INTERRUPTED" and done["interrupted"] is True
    kinds = [e["event_type"] for e in events]
    assert "scorer.started" not in kinds and "artifact.export.completed" not in kinds
    assert kinds[-1] == "benchmark.run.completed"
    assert (
        next(e for e in events if e["event_type"] == "benchmark.run.completed")["status"]
        == "interrupted"
    )
    # the container was still queried: the four calls made before Ctrl+C are all recorded
    assert len(tool_events(events, "mcp_server")) == 4
    assert record["mcp_metrics"]["overall"]["mcp_calls_attempted"] == 4
    assert "cleanup.completed" in kinds and "cleanup.failed" not in kinds


def test_second_ctrl_c_stops_cleanup_but_keeps_jsonl_valid_and_error_first(lab):
    scenario = lab(ending="ctrl_c")
    scenario.interrupt_after = 5  # calls 4 and 5 fail, so both outcomes appear
    scenario.second_interrupt = True
    assert scenario.run() == 130
    events, record = scenario.events, scenario.record
    assert schema.validate_stream(events) == []
    assert record["cleanup_forced"] is True and record["cleanup_completed"] is False
    done = next(e for e in events if e["event_type"] == "benchmark.trial.completed")
    assert done["primary_error"]["reason_code"] == "INTERRUPTED"
    failed = {e["cleanup_operation"]: e for e in events if e["event_type"] == "cleanup.failed"}
    assert failed["cancel_turn"]["cleanup_status"] == "unknown"
    # the server log was never collected, so only the client's own statuses are known
    summary = record["mcp_metrics"]
    assert summary["source"] == "agent_stream_only"
    overall = summary["overall"]
    assert (
        overall["mcp_calls_attempted"],
        overall["mcp_calls_succeeded"],
        overall["mcp_calls_failed"],
    ) == (5, 3, 2)
    assert overall["mcp_latency_observations"] == 0 and overall["mcp_latency_p50_ms"] is None
    assert overall["mcp_calls_partial"] is None and overall["mcp_cache_hit_rate"] is None
    assert not tool_events(events, "mcp_server")
    # a second interrupt skips optional cleanup, but local Docker removal still runs
    assert not scenario.exists(scenario.mcp_name)


def test_cleanup_error_does_not_replace_the_primary_error(lab):
    scenario = lab(ending="turn_failed", deletion="failed")
    scenario.interrupt_after = 4
    assert scenario.run() == 1
    events, record = scenario.events, scenario.record
    assert schema.validate_stream(events) == []
    done = next(e for e in events if e["event_type"] == "benchmark.trial.completed")
    assert done["primary_error"]["reason_code"] == "MODEL_GENERATION_ERROR"
    assert done["primary_error"]["source_code"] == "turn_failed"
    assert [e["reason_code"] for e in done["cleanup_errors"]] == ["CLEANUP_ERROR"]
    assert done["cleanup_errors"][0]["category"] == "delete_session"
    assert record["status"] == "error" and record["cleanup_completed"] is False
    failed = [e for e in events if e["event_type"] == "cleanup.failed"]
    assert [e["cleanup_operation"] for e in failed] == ["delete_session"]
    assert len(tool_events(events, "mcp_server")) == 4
    assert not errors.classify_cleanup({"cleanup_operations": {}})
    assert not scenario.exists(scenario.mcp_name)  # other cleanup steps still ran
