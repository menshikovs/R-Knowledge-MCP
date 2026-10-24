import json
import subprocess
import sys
import threading
from argparse import Namespace

import httpx
import pytest

from benchmarks.codex_r import run_simple as simple


@pytest.mark.parametrize("effort", ["medium", "high"])
@pytest.mark.parametrize("with_mcp", [False, True])
def test_session_request_uses_selected_effort_without_spend_control(effort, with_mcp):
    def respond(request):
        assert request.headers["authorization"] == "Bearer application-test-key"
        body = json.loads(request.content)
        assert "spend_control" not in body
        assert body["agent"]["model"] == "gpt-6-luna"
        assert body["agent"]["reasoning"] == {"effort": effort}
        assert bool(body["agent"]["tools"]) is with_mcp
        assert "executor-test-key" not in request.content.decode()
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

    client = simple.SimpleClient(
        "application-test-key", "executor-test-key", transport=httpx.MockTransport(respond)
    )
    try:
        assert client.create_simple_session(effort, with_mcp)["session_id"] == "sess_test"
    finally:
        client.close()


def test_scrub_preserves_usage_and_redacts_both_secrets():
    value = {
        "usage": {"input_tokens": 123, "output_tokens_details": {"reasoning_tokens": 9}},
        "text": "first-key second-key https://api.openai.com/v1/agents/api/routing",
        "remote_url": "private",
    }
    result = simple.scrub(value, ("first-key", "second-key"))
    assert result["usage"] == value["usage"]
    assert result["text"] == "[REDACTED] [REDACTED] [REDACTED]"
    assert result["remote_url"] == "[REDACTED]"


def test_create_and_events_use_same_application_key_despite_executor_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "application-test-key")
    monkeypatch.setenv("OPENAI_EXECUTOR_API_KEY", "executor-test-key")
    observations = []

    def respond(request):
        observations.append(
            {
                "path": request.url.path,
                "uses_application_key": request.headers.get("authorization")
                == "Bearer application-test-key",
                "uses_executor_key": request.headers.get("authorization")
                == "Bearer executor-test-key",
            }
        )
        if request.url.path.endswith("/events"):
            assert "Idempotency-Key" in request.headers
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "id": "sess_test",
                "agent": json.loads(request.content)["agent"],
                "environment": {
                    "type": "self_hosted",
                    "id": "env_test",
                    "remote_url": "https://api.openai.com/v1/agents/api",
                },
            },
        )

    keys = tuple(simple.os.environ[name] for name in simple.KEY_NAMES)
    client = simple.SimpleClient(*keys, transport=httpx.MockTransport(respond))
    try:
        environment = client.create_simple_session("medium", False)
        # Even a CODEX_API_KEY or later host-environment changes must not
        # replace the application's existing HTTP Authorization header.
        monkeypatch.setenv("CODEX_API_KEY", keys[1])
        monkeypatch.setenv("OPENAI_API_KEY", "changed-after-session-creation")
        client.submit_task(environment["session_id"], "Complete R01")
        assert [item["path"] for item in observations] == [
            "/v1/agents/sessions",
            "/v1/agents/sessions/sess_test/events",
        ]
        assert all(item["uses_application_key"] for item in observations)
        assert not any(item["uses_executor_key"] for item in observations)
    finally:
        client.close()


def test_missing_keys_writes_actual_startup_error_without_starting_docker(tmp_path, monkeypatch):
    for name in simple.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)

    def unexpected(*args, **kwargs):
        pytest.fail("Missing credentials must not start Docker or contact an API")

    monkeypatch.setattr(simple, "docker", unexpected)
    assert simple.main(["--effort", "medium", "--results", str(tmp_path)]) == 1
    records = json.loads(next(tmp_path.glob("*/results.json")).read_text())
    assert records[0]["status"] == "startup_error"
    assert "OPENAI_EXECUTOR_API_KEY" in records[0]["error"]
    assert next(tmp_path.glob("*/results.csv")).is_file()


def test_http_error_keeps_reason_but_never_keys():
    client = simple.SimpleClient(
        "application-test-key",
        "executor-test-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403, json={"error": "model access denied application-test-key executor-test-key"}
            )
        ),
    )
    try:
        with pytest.raises(RuntimeError, match="HTTP 403:.*model access denied") as caught:
            client.create_simple_session("medium", False)
        assert "application-test-key" not in str(caught.value)
        assert "executor-test-key" not in str(caught.value)
    finally:
        client.close()


@pytest.mark.skipif(sys.platform != "linux", reason="Runner uses Linux SIGALRM")
@pytest.mark.parametrize("outcome", ["completed", "failed", "environment_failed"])
@pytest.mark.parametrize(
    ("task", "filename"), [("R01", "solution.R"), ("R02", "summarize_sales.R")]
)
def test_trial_deletes_session_and_executor_before_scoring(
    tmp_path, monkeypatch, outcome, task, filename
):
    effects = []
    executor_started = threading.Event()
    succeeds = outcome == "completed"

    def respond(request):
        path = request.url.path
        if path.endswith("/sessions"):
            return httpx.Response(
                200,
                json={
                    "id": "sess_test",
                    "agent": json.loads(request.content)["agent"],
                    "environment": {
                        "type": "self_hosted",
                        "id": "env_test",
                        "remote_url": "https://api.openai.com/v1/agents/api",
                    },
                },
            )
        if request.method == "DELETE":
            assert "logs_captured" in effects
            effects.append("deleted")
            return httpx.Response(200, json={"id": "sess_test", "deleted": True})
        if path.endswith("/events") and request.method == "GET":
            # Model delayed SSE headers: do not return any headers until Docker
            # started. This failed when startup lived in on_stream_ready.
            assert executor_started.wait(timeout=2), (
                "SSE headers waited, but executor never started"
            )
            if outcome == "environment_failed":
                events = [
                    {
                        "type": "agent.session.environment.failed",
                        "environment": {
                            "error": {
                                "code": "environment_connection_timeout",
                                "message": "Environment could not connect executor-test-key",
                            }
                        },
                    }
                ]
            else:
                events = [
                    {"type": "agent.session.environment.connected"},
                    {"type": f"agent.session.turn.{outcome}"},
                ]
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
            )
        return httpx.Response(200, json={"usage": {"input_tokens": 55, "output_tokens": 9}})

    original_client = simple.SimpleClient
    monkeypatch.setattr(
        simple,
        "SimpleClient",
        lambda *keys: original_client(*keys, transport=httpx.MockTransport(respond)),
    )

    def docker(*args, **kwargs):
        if args[0] == "rm":
            effects.append("container_removed")
            assert "logs_captured" in effects
        if args[0] == "inspect":
            return subprocess.CompletedProcess(
                args, 0, '{"Running": true, "Status": "running"}', ""
            )
        if args[0] == "logs":
            effects.append("logs_captured")
            return subprocess.CompletedProcess(
                args, 0, "application-test-key", "network: connection refused executor-test-key"
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    def start_executor(name, network, image, workspace, environment, key):
        effects.append("executor_started")
        workspace.joinpath(filename).write_text("# synthetic test artifact\n")
        executor_started.set()

    def score(*args):
        assert "deleted" in effects and effects.count("container_removed") == 2
        assert args[1] == tmp_path / f"{task}-A-1/artifacts"
        assert args[1].joinpath("solution.R").read_text() == "# synthetic test artifact\n"
        effects.append("score")
        return {"status": "scored", "passed": 4, "total": 4}

    monkeypatch.setattr(simple, "docker", docker)
    monkeypatch.setattr(simple, "start_executor", start_executor)
    monkeypatch.setattr(simple.bench, "score", score)
    result = simple.run_trial(
        Namespace(effort="high", timeout=30),
        task,
        "without-mcp",
        1,
        tmp_path,
        ("application-test-key", "executor-test-key"),
        {"executor": "test", "scorer": "test"},
    )
    assert result["session_deleted"] is True
    assert result["usage"]["input_tokens"] == 55
    assert result["status"] == ("scored" if succeeds else "error")
    assert ("score" in effects) is succeeds
    assert "connection refused" in result["executor_diagnostics"]["stderr"]
    serialized = (tmp_path / f"{task}-A-1/result.json").read_text()
    assert "application-test-key" not in serialized
    assert "executor-test-key" not in serialized
    if succeeds:
        assert result["artifact_sources"] == {"solution.R": filename}
    if outcome == "environment_failed":
        assert result["environment_error"]["code"] == "environment_connection_timeout"
        assert "environment_connection_timeout" in result["error"]


@pytest.mark.parametrize("status", ["connected", "pending"])
def test_stream_reconciles_connection_and_submits_task_once(status):
    submissions = []

    def respond(request):
        if request.method == "POST":
            submissions.append(json.loads(request.content))
            return httpx.Response(200, json={})
        if request.url.path.endswith("/events"):
            # For connected, no connection event is replayed by the server.
            events = (
                []
                if status == "connected"
                else [
                    {"type": "agent.session.environment.connected"},
                    {"type": "agent.session.environment.connected"},
                ]
            )
            events.append({"type": "agent.session.turn.completed"})
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
            )
        return httpx.Response(200, json={"environment": {"status": status}})

    client = simple.SimpleClient("app-test", "exec-test", transport=httpx.MockTransport(respond))
    try:
        events = list(client.send_and_stream("sess_test", "Complete R01"))
        assert events[-1]["type"] == "agent.session.turn.completed"
        assert len(submissions) == 1
    finally:
        client.close()


def test_executor_receives_only_its_key_and_exact_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "application-test-key")
    monkeypatch.setenv("OPENAI_EXECUTOR_API_KEY", "executor-test-key")
    calls = []
    environment = {
        "environment_id": "env_expected",
        "session_id": "sess_different",
        "remote_url": "https://api.openai.com/v1/agents/api/routing?route=unchanged",
    }

    def docker(*args, env=None, **kwargs):
        calls.append((args, env))
        if args[0] == "run":
            assert env["CODEX_API_KEY"] == "executor-test-key"
            assert all(name not in env for name in simple.KEY_NAMES)
            assert all("test-key" not in value for value in args)
            assert args[args.index("--remote") + 1] == environment["remote_url"]
            assert args[args.index("--environment-id") + 1] == "env_expected"
            assert args[args.index("--network") + 1] == "benchmark-net"
            assert args[-5:] == (
                "exec-server",
                "--remote",
                environment["remote_url"],
                "--environment-id",
                "env_expected",
            )
            return subprocess.CompletedProcess(args, 0, "container-id", "")
        if ".Config.Env" in args[2]:
            value = ["CODEX_API_KEY=executor-test-key"]
        elif ".NetworkSettings.Networks" in args[2]:
            value = {"benchmark-net": {}}
        else:
            value = {"Running": True}
        return subprocess.CompletedProcess(args, 0, json.dumps(value), "")

    monkeypatch.setattr(simple, "docker", docker)
    simple.start_executor(
        "executor-name", "benchmark-net", "image-id", tmp_path, environment, "executor-test-key"
    )
    assert len(calls) == 4


def test_executor_disables_log_compression_with_single_file(monkeypatch, tmp_path):
    captured = []

    def capture(*args, **kwargs):
        captured.extend(args)
        raise RuntimeError("Captured Docker invocation")

    monkeypatch.setattr(simple, "docker", capture)
    with pytest.raises(RuntimeError, match="Captured Docker invocation"):
        simple.start_executor(
            "executor-test",
            "network-test",
            "image-test",
            tmp_path,
            {"remote_url": "https://api.openai.com/v1/agents/api", "environment_id": "env_test"},
            "executor-test-key",
        )
    options = dict(
        arg.removeprefix("--log-opt=").split("=", 1)
        for arg in captured
        if arg.startswith("--log-opt=")
    )
    assert options == {"max-size": "1m", "max-file": "1", "compress": "false"}


def test_r02_seals_reviewed_filename_inside_root(tmp_path):
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    content = "# synthetic R02 candidate\nsummarize_sales <- function(data) data\n"
    (workspace / "summarize_sales.R").write_text(content)
    destination = tmp_path / "artifacts"
    sources = simple.seal_trial_artifacts("R02", workspace, destination)
    assert sources == {"solution.R": "summarize_sales.R"}
    assert (destination / "solution.R").read_text() == content
    assert (workspace / "summarize_sales.R").read_text() == content
    assert not (workspace / "solution.R").exists()
    assert (destination / "data/sales.csv").is_file()


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX symlink security regression")
@pytest.mark.parametrize("target", ["solution.R", "summarize_sales.R", "candidate", "parent"])
def test_r02_alias_never_bypasses_symlink_protection(tmp_path, target):
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "summarize_sales.R").write_text("# synthetic candidate")
    outside = tmp_path / "outside.R"
    outside.write_text("# must not be imported")
    if target == "parent":
        link = tmp_path / "linked-parent"
        link.symlink_to(tmp_path, target_is_directory=True)
        workspace = link / "candidate"
    elif target == "candidate":
        link = tmp_path / "linked-candidate"
        link.symlink_to(workspace, target_is_directory=True)
        workspace = link
    else:
        path = workspace / target
        path.unlink(missing_ok=True)
        path.symlink_to(outside)
    with pytest.raises(ValueError, match="[Ss]ymlink|regular"):
        simple.seal_trial_artifacts("R02", workspace, tmp_path / "artifacts")
    assert not (tmp_path / "artifacts").exists()


def test_missing_artifact_error_reports_the_exact_path_and_root(tmp_path):
    with pytest.raises(ValueError) as caught:
        simple.bench.safe_file(tmp_path, "solution.R")
    assert str(tmp_path / "solution.R") in str(caught.value)
    assert f"root: {tmp_path}" in str(caught.value)


def test_stream_failure_joins_executor_startup_before_returning():
    release_startup = threading.Event()
    startup_finished = threading.Event()

    def start():
        assert release_startup.wait(timeout=2)
        startup_finished.set()

    def respond(request):
        release_startup.set()
        return httpx.Response(503)

    client = simple.SimpleClient("app-test", "exec-test", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(RuntimeError, match="HTTP 503"):
            list(client.send_and_stream("sess_test", "Complete R01", executor_start=start))
        assert startup_finished.is_set(), "Cleanup must not race a late Docker startup"
    finally:
        client.close()
