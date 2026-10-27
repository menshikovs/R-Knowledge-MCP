"""Offline protocol-boundary tests: real HTTPX parsing, synthetic streams/processes."""

import json
import signal
import socket
import subprocess
import sys
import threading

import httpx
import pytest

from benchmarks.codex_r import connection_diagnostics as diagnostics
from benchmarks.codex_r import probe_executor_connection as probe
from benchmarks.codex_r import run_simple as simple

KEYS = ("application-private-marker", "executor-private-marker")
PRIVATE = "unstructured-private-payload"
REMOTE = "https://api.openai.com/v1/agents/api/opaque-routing"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real Docker/process/network access is forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


class Events(httpx.SyncByteStream):
    def __init__(self, events, ending=None):
        self.events, self.ending = events, ending

    def __iter__(self):
        yield b": keepalive\n\n"
        for event in self.events:
            yield f"data: {json.dumps(event)}\n\n".encode()
        if self.ending is not None:
            raise self.ending


def client_fixture(
    tmp_path,
    *,
    events=(),
    snapshot=None,
    ending=None,
    stream_status=200,
    delayed_headers=False,
    cls=simple.SimpleClient,
):
    calls = []
    started = threading.Event()

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/sessions"):
            return httpx.Response(
                200,
                json={
                    "id": "sess_test",
                    "agent": json.loads(request.content)["agent"],
                    "environment": {"type": "self_hosted", "id": "env_test", "remote_url": REMOTE},
                },
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "sess_test", "deleted": True})
        if request.url.path.endswith("/events"):
            if request.method == "POST":
                return httpx.Response(200, json={})
            if delayed_headers:
                assert started.wait(2), "Executor startup must not wait on SSE headers"
            return httpx.Response(
                stream_status,
                headers={"content-type": "text/event-stream"},
                stream=Events(events, ending),
            )
        return httpx.Response(
            200,
            json=snapshot
            if snapshot is not None
            else {
                "id": "sess_test",
                "environment": {"type": "self_hosted", "id": "env_test"},
            },
        )

    client = cls(*KEYS, transport=httpx.MockTransport(respond))
    client.connection_journal = diagnostics.ConnectionJournal(tmp_path / "connection.jsonl")
    client.create_simple_session("medium", False)
    return client, calls, started


def journal(client):
    return client.connection_journal.rows


def test_connected_submits_once_with_delayed_headers(tmp_path):
    events = [{"type": "agent.session.environment.connected"}] * 2 + [
        {"type": "agent.session.turn.completed", "private": PRIVATE}
    ]
    client, calls, started = client_fixture(tmp_path, events=events, delayed_headers=True)
    try:
        list(client.send_and_stream("sess_test", PRIVATE, executor_start=started.set))
        assert client.executor_connected.is_set()
        assert calls.count(("POST", "/v1/agents/sessions/sess_test/events")) == 1
        phases = [r["phase"] for r in journal(client)]
        assert phases.index("sse_headers_received") < phases.index("sse_first_line")
        assert phases.index("environment_connected") < phases.index("task_submit_requested")
        assert (
            next(r for r in journal(client) if r["phase"] == "session_snapshot")[
                "environment_status_present"
            ]
            is False
        )
        text = client.connection_journal.path.read_text()
        assert all(
            secret not in text for secret in (*KEYS, PRIVATE, REMOTE, "sess_test", "env_test")
        )
    finally:
        client.close()


@pytest.mark.parametrize("connect_only", [False, True])
def test_long_pending_stream_times_out_without_submitting(tmp_path, connect_only):
    client, calls, _ = client_fixture(
        tmp_path,
        events=[{"type": "agent.session.environment.pending", "private": PRIVATE}],
        ending=httpx.ReadTimeout(PRIVATE),
    )
    try:
        with pytest.raises(httpx.ReadTimeout):
            list(client.send_and_stream("sess_test", PRIVATE, connect_only=connect_only))
        assert not any(method == "POST" and path.endswith("/events") for method, path in calls)
        assert journal(client)[-1]["outcome"] == "timeout"
        assert any(row.get("outcome") == "not_connected" for row in journal(client))
        assert PRIVATE not in client.connection_journal.path.read_text()
    finally:
        client.close()


@pytest.mark.parametrize("status", [401, 403, 409, 503])
def test_stream_rejection_has_safe_http_status_and_no_submission(tmp_path, status):
    client, calls, _ = client_fixture(tmp_path, stream_status=status)
    try:
        with pytest.raises(RuntimeError, match="HTTP"):
            list(client.send_and_stream("sess_test", PRIVATE))
        assert any(
            r.get("http_status") == status and r.get("outcome") == "connection_rejected"
            for r in journal(client)
        )
        assert journal(client)[-1]["outcome"] == "connection_rejected"
        assert not client.task_submission_attempted
    finally:
        client.close()


def test_registration_failure_event_retains_code_not_message(tmp_path):
    client, _, _ = client_fixture(
        tmp_path,
        events=[
            {
                "type": "agent.session.environment.failed",
                "environment": {"error": {"code": "authentication_error", "message": PRIVATE}},
            }
        ],
    )
    try:
        list(client.send_and_stream("sess_test", PRIVATE))
        row = next(r for r in journal(client) if r["phase"] == "environment_failed")
        assert (
            row["outcome"] == "connection_rejected" and row["error_code"] == "authentication_error"
        )
        assert not client.task_submission_attempted
        assert PRIVATE not in client.connection_journal.path.read_text()
    finally:
        client.close()


@pytest.mark.parametrize("field", ["session", "environment"])
def test_mismatched_binding_blocks_input(tmp_path, field):
    snapshot = {
        "id": "sess_other" if field == "session" else "sess_test",
        "environment": {"id": "env_other" if field == "environment" else "env_test"},
    }
    client, _, _ = client_fixture(tmp_path, snapshot=snapshot)
    try:
        with pytest.raises(RuntimeError, match="binding"):
            list(client.send_and_stream("sess_test", PRIVATE))
        assert journal(client)[-1]["outcome"] == "binding_mismatch"
        assert not client.task_submission_attempted
    finally:
        client.close()


def test_cancel_closes_stream_preserves_metadata_and_stops_startup(tmp_path):
    client, _, _ = client_fixture(tmp_path, ending=KeyboardInterrupt(PRIVATE))
    try:
        with pytest.raises(KeyboardInterrupt):
            list(client.send_and_stream("sess_test", PRIVATE))
        assert client.stopping.is_set() and not client.turn_active
        rows = [
            json.loads(line) for line in client.connection_journal.path.read_text().splitlines()
        ]
        assert rows[-1]["outcome"] == "cancelled"
        assert rows[-1]["exception_type"] == "KeyboardInterrupt"
        assert PRIVATE not in json.dumps(rows)
    finally:
        client.close()


def test_connect_only_requires_event_and_never_submits(tmp_path):
    client, calls, _ = client_fixture(
        tmp_path,
        cls=probe.ConnectionOnlyClient,
        events=[{"type": "agent.session.environment.connected"}],
        snapshot={"environment": {"status": "connected"}},
    )
    try:
        list(client.send_and_stream("sess_test", None, connect_only=True))
        assert client.executor_connected.is_set()
        assert any(row["phase"] == "sse_first_line" for row in journal(client))
        assert not any(method == "POST" and path.endswith("/events") for method, path in calls)
        with pytest.raises(RuntimeError, match="cannot submit"):
            client.submit_task("sess_test", PRIVATE)
    finally:
        client.close()


def test_absent_status_and_missed_event_are_unknown_not_connection_failure(tmp_path):
    client, _, _ = client_fixture(tmp_path, ending=httpx.ReadTimeout(PRIVATE))
    try:
        with pytest.raises(httpx.ReadTimeout):
            list(client.send_and_stream("sess_test", PRIVATE))
        assert not any(
            row.get("outcome") in {"not_connected", "connection_rejected"}
            for row in journal(client)
        )
        assert not client.task_submission_attempted
    finally:
        client.close()


def test_runtime_projects_registration_websocket_auth_and_ignores_payloads():
    text = f"""{PRIVATE} {REMOTE} {KEYS[0]}
INFO Noise executor registration completed noise_event="registration" noise_outcome="ok"
WARN Noise executor failed to connect to rendezvous error_kind="http" http_status=403 \
rejection_reason="invalid_signature" payload={PRIVATE}
"""
    result = diagnostics.runtime_evidence(text)
    assert result["registration_completed"] and not result["rendezvous_connected"]
    assert result["http_status"] == 403 and result["rejection_reason"] == "invalid_signature"
    assert result["outcome"] == "connection_rejected"
    assert PRIVATE not in json.dumps(result)
    assert (
        diagnostics.runtime_evidence(
            "environment registry authentication failed (401 Unauthorized)"
        )["outcome"]
        == "connection_rejected"
    )
    assert (
        diagnostics.runtime_evidence(
            'Noise executor failed to connect to rendezvous error_kind="tls"'
        )["error_kind"]
        == "tls"
    )


def test_process_exit_is_recorded_without_raw_docker_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        simple,
        "executor_diagnostics",
        lambda *a, **kw: {
            "running": False,
            "exit_code": 17,
            "stderr": PRIVATE + REMOTE,
            "stdout": KEYS[0],
        },
    )
    log = diagnostics.ConnectionJournal(tmp_path / "connection.jsonl")
    probe.observe_executor(log, "fake", KEYS)
    assert log.rows[-1]["outcome"] == "process_exited" and log.rows[-1]["exit_code"] == 17
    assert PRIVATE not in log.path.read_text()


def test_watchdog_does_not_invent_pending_from_absent_environment_status(tmp_path, monkeypatch):
    client, _, _ = client_fixture(tmp_path)
    labels = []
    progress = type("P", (), {"event": lambda self, label, **kw: labels.append(label)})()
    monkeypatch.setattr(simple, "executor_diagnostics", lambda *a, **kw: {"running": True})
    try:
        record = {}
        simple.watch_executor_connection(
            client, record, progress, "fake", "sess_test", KEYS, seconds=0
        )
        assert labels == ["executor connection unknown"]
        assert record["executor_connect_watchdog"]["api_environment_status"] is None
        assert journal(client)[-1]["outcome"] == "unknown"
        assert not client.task_submission_attempted
    finally:
        client.close()


def test_journal_measures_time_bounds_output_and_rejects_arbitrary_fields(tmp_path):
    ticks = iter([1, 2, 8, *range(9, 700)])
    log = diagnostics.ConnectionJournal(tmp_path / "connection.jsonl", clock=lambda: next(ticks))
    log.emit("sse_open_requested", code=PRIVATE, payload=PRIVATE, remote_url=REMOTE)
    log.emit("sse_headers_received", http_status=200)
    assert log.rows[-1]["elapsed_seconds"] == 7
    assert log.rows[-1]["since_previous_seconds"] == 6
    for _ in range(600):
        log.emit("connection_observation")
    assert len(log.rows) == 512 and len(log.path.read_text().splitlines()) == 512
    assert PRIVATE not in log.path.read_text() and REMOTE not in log.path.read_text()
    with pytest.raises(ValueError):
        log.emit(PRIVATE)


def test_probe_gate_requires_authorization_before_io(tmp_path):
    with pytest.raises(SystemExit) as exc:
        probe.main(["--output", str(tmp_path / "probe")])
    assert exc.value.code == 2
    assert not (tmp_path / "probe").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Probe uses Linux SIGALRM")
@pytest.mark.parametrize(
    "outcome", ["connected", "timeout", "cancelled", "failed", "exit", "delete_unconfirmed"]
)
def test_probe_one_session_no_input_and_cleanup_on_every_outcome(tmp_path, monkeypatch, outcome):
    events = (
        [{"type": "agent.session.environment.connected"}]
        if outcome in {"connected", "delete_unconfirmed"}
        else []
    )
    if outcome == "failed":
        events = [
            {
                "type": "agent.session.environment.failed",
                "environment": {"error": {"code": "authentication_error", "message": PRIVATE}},
            }
        ]
    ending = KeyboardInterrupt(PRIVATE) if outcome == "cancelled" else httpx.ReadTimeout(PRIVATE)
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    client, calls, _ = client_fixture(
        fixture, events=events, ending=ending, cls=probe.ConnectionOnlyClient
    )
    # The fixture creation above validates the response; measure only the actual probe creation.
    calls.clear()
    if outcome == "delete_unconfirmed":
        original_delete = client.delete_session

        def unconfirmed_delete(session_id):
            original_delete(session_id)
            return {"id": session_id, "deleted": False, "private": PRIVATE}

        client.delete_session = unconfirmed_delete
    docker_calls = []

    def docker(*args, **kwargs):
        docker_calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(simple, "docker", docker)
    monkeypatch.setattr(simple, "start_executor", lambda *a: None)
    monkeypatch.setattr(
        simple,
        "executor_diagnostics",
        lambda *a, **kw: {
            "running": outcome != "exit",
            "exit_code": 23 if outcome == "exit" else 0,
            "stderr": PRIVATE,
            "stdout": REMOTE,
        },
    )
    previous = signal.getsignal(signal.SIGALRM)
    result = probe.run_probe(
        tmp_path / "probe", KEYS, "fake-image", client_factory=lambda *a: client
    )
    assert signal.getsignal(signal.SIGALRM) == previous
    assert result == (0 if outcome == "connected" else 1)
    assert calls.count(("POST", "/v1/agents/sessions")) == 1
    assert calls.count(("DELETE", "/v1/agents/sessions/sess_test")) == 1
    assert not any(method == "POST" and path.endswith("/events") for method, path in calls)
    assert sum(args[0] == "rm" for args in docker_calls) == 1
    assert any(args[:2] == ("network", "rm") for args in docker_calls)
    text = (tmp_path / "probe/connection.jsonl").read_text()
    assert all(secret not in text for secret in (*KEYS, PRIVATE, REMOTE))
    assert any(
        row.get("operation") == "delete_session"
        and row.get("confirmed") is (outcome != "delete_unconfirmed")
        for row in client.connection_journal.rows
    )
    if outcome == "exit":
        assert any(row.get("outcome") == "process_exited" for row in client.connection_journal.rows)


def test_executor_launch_uses_reviewed_log_target_and_preserves_binding(monkeypatch, tmp_path):
    calls = []

    def docker(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "inspect":
            template = args[args.index("--format") + 1]
            value = (
                [f"CODEX_API_KEY={KEYS[1]}"]
                if "Config.Env" in template
                else {"net": {}}
                if "NetworkSettings" in template
                else {"Running": True}
            )
            return subprocess.CompletedProcess(args, 0, json.dumps(value), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(simple, "docker", docker)
    simple.start_executor(
        "exec",
        "net",
        "fake",
        tmp_path,
        {"environment_id": "env_bound", "remote_url": REMOTE},
        KEYS[1],
    )
    argv, options = calls[0]
    assert argv[argv.index("--remote") + 1] == REMOTE
    assert argv[argv.index("--environment-id") + 1] == "env_bound"
    assert f"RUST_LOG={diagnostics.RUNTIME_LOG_FILTER}" in argv
    assert "--user=65534:65534" in argv and "--read-only" in argv
    assert "--security-opt=no-new-privileges" in argv and "--cap-drop=ALL" in argv
    assert KEYS[1] not in " ".join(argv) and options["env"]["CODEX_API_KEY"] == KEYS[1]
