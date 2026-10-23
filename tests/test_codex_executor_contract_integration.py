"""Offline production-boundary tests. No daemon, sockets, keys or sessions are used."""

import importlib.util
import json
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/codex_r"


def load(name):
    spec = importlib.util.spec_from_file_location(
        "p0a_" + name, ROOT / "exploratory" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_module = load("docker_runtime")
managed = load("managed_agents")
lifecycle = load("lifecycle")
adapter = load("adapter")
IMAGE = "sha256:" + "a" * 64
CID = "b" * 64
APP_KEY = "unconventional.APPLICATION.material"
ENV_KEY = "unconventional.EXECUTOR.material"
SIGNED_URL = "https://api.openai.com/private?signature=unconventional.SIGNED.material"
SECRET_TEXT = f"{APP_KEY} {ENV_KEY} {SIGNED_URL}"
NETWORK = "rkmcp-candidate-R01-A-synthetic"


@pytest.fixture(autouse=True)
def no_real_io(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("Real network or subprocess access is prohibited in P0-A tests")

    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "public"
    (path / "data").mkdir(parents=True)
    (path / "TASK.md").write_text("Synthetic R01 input; never execute live.\n")
    (path / "renv.lock").write_text("{}\n")
    (path / "data/records.csv").write_text("x\n1\n")
    return path


class FakeDocker:
    """Deterministic CLI results with the production inspect field shapes."""

    def __init__(self, workspace, *, failure=None, cleanup_failure=False):
        self.workspace = workspace
        self.failure = failure
        self.cleanup_failure = cleanup_failure
        self.calls = []
        self.removed = False

    def __call__(self, argv, *, timeout=20, env=None):
        self.calls.append(argv)
        command = argv[1:]

        def result(text="", status=0):
            return subprocess.CompletedProcess(argv, status, text.encode(), SECRET_TEXT.encode())

        if self.failure == "unavailable" and command[:2] == ["image", "inspect"]:
            raise FileNotFoundError(SECRET_TEXT)
        if command[:2] == ["image", "inspect"]:
            if command[-1] == runtime_module.FROZEN_R_IMAGE_ID:
                return result(json.dumps(["base-layer"]))
            return result(IMAGE + '|65534:65534|/candidate|["/opt/codex/bin/codex"]|["base-layer"]')
        if command[0] == "run":
            assert "--version" in command and "--network" in command
            return result("codex-cli " + runtime_module.CODEX_VERSION)
        if command[0] == "create":
            assert env["CODEX_API_KEY"] == ENV_KEY
            assert "OPENAI_API_KEY" not in env
            return result(CID)
        if command[0] == "inspect":
            template = command[command.index("--format") + 1]
            if "HostConfig" in template:
                if self.failure == "inspection":
                    return result(SECRET_TEXT)
                protocol = runtime_module.pilot.bench.manifest()["protocol"]
                host = {
                    "NetworkMode": NETWORK,
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PidsLimit": protocol["pids"],
                    "Memory": protocol["memory_mb"] * 1024**2,
                    "MemorySwap": protocol["memory_mb"] * 1024**2,
                    "NanoCpus": int(protocol["cpus"] * 1_000_000_000),
                    "Privileged": False,
                    "Tmpfs": {"/tmp": "rw", "/work": "rw"},
                }
                mounts = [
                    {
                        "Type": "bind",
                        "Destination": "/candidate",
                        "RW": True,
                        "Source": str(self.workspace),
                    }
                ]
                return result(
                    "|".join(
                        [json.dumps(host), json.dumps("65534:65534"), json.dumps(mounts), "created"]
                    )
                )
            if "NetworkSettings" in template:
                return result(json.dumps({NETWORK: {"IPAddress": "172.20.0.3"}}))
            if "Config.Env" in template:
                return result(
                    json.dumps(["CODEX_API_KEY=" + ENV_KEY, "HTTPS_PROXY=http://172.20.0.2:3128"])
                )
            if "State.Status" in template:
                return result("exited|126")
        if command[0] == "start":
            if self.failure == "nonzero":
                return result(status=125)
            if self.failure == "timeout":
                raise subprocess.TimeoutExpired(argv, timeout, stderr=SECRET_TEXT)
            return result(CID)
        if command[0] == "top":
            return result("" if self.failure == "exit" else "65534 exec-server")
        if command[0] == "rm":
            if self.cleanup_failure == "exception":
                raise OSError(SECRET_TEXT) from RuntimeError(SECRET_TEXT)
            if self.cleanup_failure:
                return result(status=1)
            self.removed = True
            return result(CID)
        if command[0] == "ps":
            return result(CID if self.cleanup_failure else "")
        raise AssertionError("Unexpected synthetic Docker operation")


def runtime(workspace, **kwargs):
    docker = FakeDocker(workspace, **kwargs)
    instance = runtime_module.CodexCandidateRuntime(
        IMAGE, docker="synthetic-docker", command_runner=docker
    )
    return instance, docker


def start(instance, workspace, url):
    return instance.start_managed_executor(
        workspace,
        environment_id="synthetic_env",
        remote_url=url,
        environment_key=ENV_KEY,
        topology=SimpleNamespace(started=True, internal_network=NETWORK),
        proxy_ip="172.20.0.2",
    )


ACCEPTED = [
    "https://api.openai.com/v1/agents/api",
    "https://api.openai.com:443/v1/agents/api/",
    "https://api.openai.com/v1/agents/api/connect/session",
    "https://api.openai.com/v1/agents/api?route=opaque-server-routing-value",
]
REJECTED = [
    "http://api.openai.com/v1/agents/api",
    "https://evil.example/v1/agents/api",
    "https://api.openai.com:444/v1/agents/api",
    "https://user:pass@api.openai.com/v1/agents/api",
    "https://api.openai.com/v1/agents/api#",
    "https://api.openai.com/v1/agents/api?token=x",
    "https://api.openai.com/v1/agents/api/%2e%2e/private",
    "https://api.openai.com/v1/agents/api/%252e%252e/private",
    "https://api.openai.com/v1/agents/api/%FF",
    "https://api.openai.com/v1/agents/api?route=%zz",
    "https://api.openai.com/v1/agents/api?route=%0a",
    "https://api.openai.com/v1/agents/api\n",
    "https://api.openai.com/v1/agents/api/../private",
]


def session_record(url):
    return {
        "id": "synthetic_session",
        "agent": {"model": "gpt-6-luna", "reasoning": {"effort": "medium"}, "tools": []},
        "environment": {"id": "synthetic_env", "type": "self_hosted", "remote_url": url},
    }


@pytest.mark.parametrize("url", ACCEPTED)
def test_shared_policy_traverses_actual_executor_startup_unchanged(workspace, url):
    checked = managed.validate_environment_record(session_record(url))
    assert checked["remote_url"] is url
    instance, docker = runtime(workspace)
    started = start(instance, workspace, checked["remote_url"])
    create = next(call for call in docker.calls if call[1] == "create")
    assert create[create.index("--remote") + 1] == url
    assert started["executor_registered"] is False
    assert instance.stop_managed_executor(started["container_id"])
    assert docker.removed


@pytest.mark.parametrize("url", REJECTED)
def test_both_url_boundaries_reject_before_any_docker_operation(workspace, url):
    with pytest.raises(managed.ManagedAgentsError):
        managed.validate_environment_record(session_record(url))
    instance, docker = runtime(workspace)
    with pytest.raises(runtime_module.DockerRuntimeError) as caught:
        start(instance, workspace, url)
    assert caught.value.diagnostics["reason_code"] == "remote_url_rejected"
    assert docker.calls == []


class Lease:
    def __enter__(self):
        return self

    def mark_cleanup_verified(self):
        self.clean = True

    def __exit__(self, *_args):
        pass


class Ledger:
    active_trial_id = None

    def authorize_one(self, *_args, **_kwargs):
        self.active_trial_id = "R01-A"

    def checkpoint(self, *_args, **_kwargs):
        self.active_trial_id = None
        return {"synthetic": True, "reconciled": False}


def run_synthetic(
    workspace,
    *,
    url=ACCEPTED[2],
    failure=None,
    cleanup_failure=False,
    create_transport_failure=False,
    task_transport_failure=False,
):
    routes = []

    def handler(request):
        routes.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/sessions"):
            if create_transport_failure:
                raise httpx.ConnectError(SECRET_TEXT, request=request)
            return httpx.Response(201, json=session_record(url))
        if request.method == "GET":
            # A connected event is used only by the synthetic task-POST failure test.
            event = {
                "type": "agent.session.environment.connected"
                if task_transport_failure
                else "agent.session.environment.failed",
                APP_KEY: "top-level key secret",
                "details": {
                    ENV_KEY: "nested key secret",
                    "nested": [
                        SECRET_TEXT,
                        {SIGNED_URL: "signed URL key secret", "ordinary": SECRET_TEXT},
                    ],
                },
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=("data: " + json.dumps(event) + "\n\n").encode(),
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "synthetic_session", "deleted": True})
        event_type = json.loads(request.content)["events"][0]["type"]
        if event_type == "agent.session.input.message":
            assert task_transport_failure  # MockTransport never transmits this request.
            raise httpx.WriteError(SECRET_TEXT, request=request)
        assert event_type == "agent.session.input.cancel"
        return httpx.Response(200, json={})

    client = managed.ManagedAgentsClient(APP_KEY, transport=httpx.MockTransport(handler))
    client.synthetic = True
    instance, docker = runtime(workspace, failure=failure, cleanup_failure=cleanup_failure)
    topology = SimpleNamespace(started=True, internal_network=NETWORK)
    topology.start = lambda: {"proxy_internal_ip": "172.20.0.2"}
    topology.cleanup = lambda: True
    control = lifecycle.R01ALifecycleController(
        client=client,
        runtime=instance,
        topology=topology,
        ledger=Ledger(),
        authorize=lambda *_: None,
        consume_authorization=lambda *_args, **_kwargs: None,
        lease_factory=lambda *_: Lease(),
        score=lambda *_: pytest.fail("No pre-task scoring"),
        frozen_r_image_id=runtime_module.FROZEN_R_IMAGE_ID,
        environment_key=ENV_KEY,
        estimated_spend_cents=100,
        checkpoint_review=lambda *_: None,
        current_live_gates=lambda: {},
        synthetic_mode=True,
    )
    context = {
        "trial_id": "R01-A",
        "condition": "A",
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "expected_tools": [],
        "workspace": str(workspace),
    }
    try:
        record = control.run_one(
            context=context,
            authorization={"synthetic": True},
            state_directory=workspace.parent / "synthetic-state",
        )
    except lifecycle.LifecycleError as exc:
        record = exc.audit_record
    return record, docker, routes


@pytest.mark.parametrize(
    ("failure", "code", "phase"),
    [
        ("nonzero", "cli_nonzero", "start_container"),
        ("unavailable", "executable_unavailable", "verify_image"),
        ("timeout", "command_timeout", "start_container"),
        ("inspection", "invalid_inspection", "inspect_policy"),
        ("exit", "executor_exited", "verify_process"),
    ],
)
def test_http201_actual_runtime_failure_is_temporally_correct_and_private(
    workspace, tmp_path, capsys, failure, code, phase
):
    record, docker, routes = run_synthetic(workspace, failure=failure)
    assert record["failure"]["operation"] == "start_executor"
    assert record["failure"]["reason_code"] == code
    assert record["failure"]["sub_operation"] == phase
    assert record["failure"]["docker_http_status"] is None
    assert record["failure"]["docker_cli_exit_code"] == (125 if failure == "nonzero" else None)
    assert record["failure"]["container_exit_code"] == (126 if failure == "exit" else None)
    assert record["failure"]["timeout_classification"] == (
        "docker_command_deadline" if failure == "timeout" else None
    )
    assert record["session_creation_http_status"] == 201
    assert record["session_created"] and record["sessions_created_count"] == 1
    assert record["session_creation_outcome"] == "confirmed"
    assert record["executor_startup_attempted"] and record["executor_startup_failed"]
    assert not record["inference_submitted"] and record["task_submissions_attempted_count"] == 0
    assert record["task_submission_outcome"] == "not_attempted"
    assert record["cleanup_verified"] and record["session_deleted_verified"]
    assert routes.count(("POST", "/v1/agents/sessions")) == 1
    assert "before session creation" not in json.dumps(record)
    if failure != "unavailable":
        assert docker.removed
    target = tmp_path / "synthetic-audit.json"
    adapter._private_json_write(target, record)
    serialized = target.read_text()
    assert json.loads(serialized)["synthetic"] is True
    assert "not_benchmark_result" in serialized
    assert json.loads(serialized)["launch_permitted"] is False
    with pytest.raises(ValueError, match="Result fields differ"):
        runtime_module.pilot.bench.validate_record(json.loads(serialized), {})
    captured = capsys.readouterr()
    for forbidden in (APP_KEY, ENV_KEY, SIGNED_URL, "unconventional.SIGNED.material", ACCEPTED[2]):
        assert forbidden not in serialized + captured.out + captured.err


@pytest.mark.parametrize("cleanup_failure", [True, "exception"])
def test_primary_error_survives_cleanup_failure_and_blocks_export(
    workspace, tmp_path, capsys, cleanup_failure
):
    record, _, _ = run_synthetic(workspace, failure="nonzero", cleanup_failure=cleanup_failure)
    assert record["failure"]["reason_code"] == "cli_nonzero"
    assert record["failure"]["docker_cli_exit_code"] == 125
    assert record["failure"]["secondary_cleanup_failure"] == "cleanup_unverified"
    assert record["primary_failure_classification"] == "docker_runtime"
    assert not record["cleanup_verified"] and not record["container_termination_verified"]
    assert record["artifact_hashes"] == {} and record["scoring"] is None
    assert record["session_deleted_verified"]
    assert "container_removal_unverified" in record["cleanup_failures"]
    target = tmp_path / "synthetic-cleanup-failure.json"
    adapter._private_json_write(target, record)
    captured = capsys.readouterr()
    for secret in (APP_KEY, ENV_KEY, SIGNED_URL):
        assert secret not in target.read_text() + captured.out + captured.err


@pytest.mark.parametrize("url", [ACCEPTED[3], REJECTED[0]])
def test_http201_pre_task_boundary_and_real_serialization(workspace, tmp_path, capsys, url):
    record, docker, _ = run_synthetic(workspace, url=url)
    assert record["session_created"] and record["session_creation_http_status"] == 201
    assert record["task_submissions_attempted_count"] == 0
    assert not record["executor_connection_observed"] and not record["inference_submitted"]
    if url in ACCEPTED:
        assert record["executor_process_started"] and not record["executor_startup_failed"]
        assert record["failure"]["operation"] == "await_executor_connection"
        assert record["events"]  # nested output was scrubbed by the real client/controller
    else:
        assert docker.calls == []
        assert record["failure"]["category"] == "response_schema_validation"
    target = tmp_path / "synthetic-result.json"
    adapter._private_json_write(target, record)
    captured = capsys.readouterr()
    text = target.read_text() + captured.out + captured.err
    for forbidden in (APP_KEY, ENV_KEY, SIGNED_URL, "unconventional.SIGNED.material"):
        assert forbidden not in text


def test_uncertain_creation_never_becomes_a_confirmed_creation_or_executor_attempt(
    workspace, tmp_path, capsys
):
    record, docker, routes = run_synthetic(workspace, create_transport_failure=True)
    assert record["session_creation_attempted"]
    assert record["session_creation_outcome"] == "uncertain"
    assert record["session_creation_uncertain"] and not record["session_created"]
    assert record["sessions_created_count"] == 0
    assert record["session_creation_http_status"] is None
    assert not record["executor_startup_attempted"] and docker.calls == []
    assert record["task_submission_outcome"] == "not_attempted"
    assert record["task_submissions_attempted_count"] == 0
    assert record["session_deleted_verified"] is None and not record["cleanup_verified"]
    assert len(routes) == 1  # No retry, cancel or guessed deletion.
    target = tmp_path / "synthetic-unknown-session.json"
    adapter._private_json_write(target, record)
    captured = capsys.readouterr()
    for secret in (APP_KEY, ENV_KEY, SIGNED_URL):
        assert secret not in target.read_text() + captured.out + captured.err


def test_mocked_task_post_uncertainty_is_counted_once_without_retry(workspace):
    record, _, routes = run_synthetic(workspace, task_transport_failure=True)
    assert record["session_creation_outcome"] == "confirmed"
    assert record["executor_process_started"] and record["executor_connection_observed"]
    assert record["task_submission_outcome"] == "uncertain"
    assert record["task_submission_uncertain"] and record["task_submission_attempted"]
    assert record["task_submissions_attempted_count"] == 1 and not record["inference_submitted"]
    assert record["failure"]["operation"] == "submit_task"
    # One failed mock submission plus one cancellation, no automatic resubmission.
    assert routes.count(("POST", "/v1/agents/sessions/synthetic_session/events")) == 2
    assert record["cleanup_verified"]


def test_unreviewed_diagnostic_values_and_exception_context_are_never_persisted(tmp_path, capsys):
    error = runtime_module.DockerRuntimeError(
        SECRET_TEXT,
        code=SECRET_TEXT,
        sub_operation=SECRET_TEXT,
        exception_category={"nested": SECRET_TEXT},
        docker_cli_exit_code=SECRET_TEXT,
        container_exit_code=SECRET_TEXT,
        container_startup_state=SECRET_TEXT,
        secondary_cleanup_failure=SECRET_TEXT,
    )
    error.__cause__ = RuntimeError(SECRET_TEXT)
    record = {
        "synthetic": True,
        "record_type": "synthetic_diagnostics_not_benchmark_result",
        "failure": error.diagnostics,
    }
    target = tmp_path / "synthetic-closed-vocabulary.json"
    adapter._private_json_write(target, record)
    captured = capsys.readouterr()
    text = target.read_text() + captured.out + captured.err
    for secret in (APP_KEY, ENV_KEY, SIGNED_URL):
        assert secret not in text
    assert record["failure"]["docker_cli_exit_code"] is None
    assert record["failure"]["container_exit_code"] is None
    assert record["failure"]["sub_operation"] is None


def test_f10_sanitizes_keys_values_audit_stdout_and_inspection(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", APP_KEY)
    monkeypatch.setenv("OPENAI_EXECUTOR_API_KEY", ENV_KEY)
    workspace = tmp_path / "workspace"
    (workspace / "data").mkdir(parents=True)
    (workspace / "TASK.md").write_text("synthetic only\n")
    (workspace / "renv.lock").write_text("{}\n")
    (workspace / "data/records.csv").write_text("x\n1\n")
    record, _, _ = run_synthetic(workspace)
    serialized_record = json.dumps(record, ensure_ascii=False)
    for secret in (APP_KEY, ENV_KEY, SIGNED_URL, "unconventional.SIGNED.material"):
        assert secret not in serialized_record
    assert record["events"][0]["type"] == "agent.session.environment.failed"
    assert record["events"][0]["details"]["nested"][0] == "[REDACTED] [REDACTED] [REDACTED]"

    client = managed.ManagedAgentsClient(APP_KEY, transport=httpx.MockTransport(lambda _req: None))
    client._additional_sanitization_secrets = (ENV_KEY,)
    raw = {
        APP_KEY: "top-level",
        "nested": [{ENV_KEY: f"value {APP_KEY} {SIGNED_URL}"}],
        SIGNED_URL: "signed-url-key-value",
        "type": "agent.session.turn.completed",
    }
    for sanitizer in (
        lambda value: client._sanitize_event(value),
        lambda value: managed.contract.sanitize_reference_data(value, secrets=(APP_KEY, ENV_KEY)),
        lambda value: adapter.redact(value, secrets=(APP_KEY, ENV_KEY)),
    ):
        clean = sanitizer(raw)
        clean_text = json.dumps(clean, ensure_ascii=False)
        for secret in (APP_KEY, ENV_KEY, SIGNED_URL, "unconventional.SIGNED.material"):
            assert secret not in clean_text
        assert clean["type"] == "agent.session.turn.completed"
    assert adapter.redact({"source_url": "https://example.test/docs"}) == {
        "source_url": "https://example.test/docs"
    }

    target = tmp_path / "private-audit.json"
    record["synthetic_probe"] = {APP_KEY: "configured app key", ENV_KEY: "configured executor key"}
    adapter._private_json_write(target, record)
    journal_path = tmp_path / "synthetic-state/lifecycle-journals/R01-A-attempt-1.jsonl"
    assert journal_path.is_file()
    lifecycle_audit = journal_path.with_suffix(".audit.json")
    assert lifecycle_audit.is_file()
    for secret in (APP_KEY, ENV_KEY, SIGNED_URL, "unconventional.SIGNED.material"):
        assert secret not in lifecycle_audit.read_text()
    capsys.readouterr()
    assert adapter.main(["inspect-journal", "--journal", str(journal_path)]) == 0
    captured = capsys.readouterr()
    combined = target.read_text() + lifecycle_audit.read_text() + captured.out + captured.err
    for secret in (APP_KEY, ENV_KEY, SIGNED_URL, "unconventional.SIGNED.material"):
        assert secret not in combined


def test_f10_preserves_protocol_type_and_terminal_event_handling():
    observed = []

    def handler(request):
        if request.method == "GET":
            events = [
                {"type": "agent.session.environment.connected", APP_KEY: "synthetic"},
                {
                    "type": "agent.session.turn.completed",
                    "nested": [{ENV_KEY: SIGNED_URL}],
                },
            ]
            payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=payload.encode(),
            )
        return httpx.Response(200, json={})

    client = managed.ManagedAgentsClient(APP_KEY, transport=httpx.MockTransport(handler))
    client._additional_sanitization_secrets = (ENV_KEY,)
    events = list(
        client.send_and_stream(
            "synthetic_session",
            "synthetic task",
            on_stream_ready=lambda: None,
            on_environment_connected=lambda: observed.append("connected"),
            on_task_submitted=lambda: observed.append("submitted"),
        )
    )
    assert [event["type"] for event in events] == [
        "agent.session.environment.connected",
        "agent.session.turn.completed",
    ]
    assert observed == ["connected", "submitted"]
    assert SIGNED_URL not in json.dumps(events)


def test_f10_sanitization_key_collision_fails_closed():
    client = managed.ManagedAgentsClient(APP_KEY, transport=httpx.MockTransport(lambda _req: None))
    with pytest.raises(ValueError, match="duplicate object key"):
        client._sanitize_event({APP_KEY: "secret", "[REDACTED]": "ordinary"})
    with pytest.raises(ValueError, match="duplicate object key"):
        adapter.redact({SIGNED_URL: "secret", "[REDACTED]": "ordinary"}, secrets=(SIGNED_URL,))
