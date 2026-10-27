"""Offline Ctrl+C, cleanup and progress checks for the simple runner."""

import csv
import json
import os
import signal
import subprocess
import sys
import threading
from argparse import Namespace

import httpx
import pytest

from benchmarks.codex_r import run_simple as simple

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Runner uses POSIX signals")
KEYS = ("application-private-marker", "executor-private-marker")
REAL_CLIENT = simple.SimpleClient


class EventStream(httpx.SyncByteStream):
    def __init__(self, events, interrupt):
        self.events, self.interrupt = events, interrupt

    def __iter__(self):
        for event in self.events:
            yield f"data: {json.dumps(event)}\n\n".encode()
        if self.interrupt:
            raise KeyboardInterrupt()


def trial(tmp_path, monkeypatch, *, phase="completed", deletion="confirmed", cleanup=None):
    calls, docker_calls, clients = [], [], []

    def respond(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "POST" and path.endswith("/sessions"):
            if phase == "creation_unknown":
                raise httpx.ReadTimeout("creation acknowledgement unknown " + KEYS[0])
            if phase == "creation_missing_id":
                return httpx.Response(201, json={"id": None})
            return httpx.Response(
                201,
                json={
                    "id": "sess_interrupt",
                    "agent": json.loads(request.content)["agent"],
                    "environment": {
                        "type": "self_hosted",
                        "id": "env_interrupt",
                        "remote_url": "https://api.openai.com/v1/agents/api",
                    },
                },
            )
        if request.method == "GET" and path.endswith("/events"):
            events = []
            if phase != "waiting_executor":
                events += [
                    {"type": "agent.session.environment.connected"},
                    {"type": "agent.session.turn.started"},
                ]
            if phase in {"completed", "ordinary_error"}:
                events.append(
                    {
                        "type": "agent.session.turn."
                        + ("completed" if phase == "completed" else "failed")
                    }
                )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=EventStream(events, phase in {"waiting_executor", "during_turn"}),
            )
        # Cleanup requests use a separate, bounded HTTP timeout.
        in_cleanup = bool(clients and clients[-1].cleanup_timeout is not None)
        if in_cleanup and (
            request.method == "DELETE"
            or request.method == "GET"
            or (request.method == "POST" and b"input.cancel" in request.content)
        ):
            assert set(request.extensions["timeout"].values()) == {simple.CLEANUP_TIMEOUT_SECONDS}
        if request.method == "POST" and b"input.cancel" in request.content:
            if cleanup == "second_interrupt":
                os.kill(os.getpid(), signal.SIGINT)
            if cleanup == "cancel_unsupported":
                return httpx.Response(405, json={"error": "not supported"})
            return httpx.Response(200, json={})
        if request.method == "DELETE":
            if deletion == "timeout":
                raise httpx.ReadTimeout("private transport text " + KEYS[0])
            if deletion == "failed":
                return httpx.Response(403, json={"error": "Bearer secret-auth-marker " + KEYS[1]})
            if deletion == "unknown":
                return httpx.Response(200, json={"id": "sess_interrupt", "deleted": False})
            if deletion == "mismatched":
                return httpx.Response(200, json={"id": "other_session", "deleted": True})
            return httpx.Response(200, json={"id": "sess_interrupt", "deleted": True})
        if request.method == "GET":
            if in_cleanup and cleanup == "first_interrupt_during_cleanup":
                os.kill(os.getpid(), signal.SIGINT)
            if in_cleanup and cleanup == "interrupt_usage":
                raise KeyboardInterrupt()
            if in_cleanup and cleanup == "double_interrupt_usage":
                os.kill(os.getpid(), signal.SIGINT)
                os.kill(os.getpid(), signal.SIGINT)
            return httpx.Response(200, json={"usage": None, "environment": {"status": "pending"}})
        return httpx.Response(200, json={})

    def client(*keys):
        value = REAL_CLIENT(*keys, transport=httpx.MockTransport(respond))
        clients.append(value)
        if phase == "after_session":
            create = value.create_simple_session

            def interrupted_create(*args, **kwargs):
                create(*args, **kwargs)
                raise KeyboardInterrupt()

            value.create_simple_session = interrupted_create
        return value

    def prepare(task, destination, _scorer_choice="legacy"):
        if phase == "before_session":
            raise KeyboardInterrupt()
        destination.mkdir()
        (destination / "TASK.md").write_text("private task body marker")
        (destination / "answer.json").write_text("{}")

    def docker(*args, **kwargs):
        docker_calls.append(args)
        if args[0] == "inspect":
            return subprocess.CompletedProcess(args, 0, '{"Running": true}', "")
        if args[0] == "logs":
            return subprocess.CompletedProcess(args, 0, KEYS[0], KEYS[1])
        if cleanup == "remove_error" and args[:2] == ("rm", "--force"):
            return subprocess.CompletedProcess(args, 1, "", "private error " + KEYS[0])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(simple, "SimpleClient", client)
    monkeypatch.setattr(simple, "docker", docker)
    monkeypatch.setattr(simple, "start_executor", lambda *args: None)
    monkeypatch.setattr(simple, "start_mcp", lambda *args: None)
    monkeypatch.setattr(simple.knowledge_pilot, "prepare", prepare)

    def score(_task, _artifacts, _image, *, scorer_version):
        assert scorer_version == "legacy"
        return {
            "status": "scored",
            "passed": 4,
            "total": 4,
            "fully_correct": True,
        }

    monkeypatch.setattr(
        simple.knowledge_pilot,
        "score",
        score,
    )
    previous = signal.getsignal(signal.SIGINT)
    result = simple.run_trial(
        Namespace(effort="medium", timeout=900),
        "D01",
        "with-mcp",
        1,
        tmp_path,
        KEYS,
        {"executor": "test", "mcp": "test", "scorer": "test"},
    )
    assert signal.getsignal(signal.SIGINT) == previous
    return result, calls, docker_calls


@pytest.mark.parametrize(
    "phase",
    [
        "before_session",
        "after_session",
        "waiting_executor",
        "during_turn",
    ],
)
def test_interrupt_at_each_stage_cleans_up_and_never_scores(tmp_path, monkeypatch, phase):
    result, calls, docker_calls = trial(tmp_path, monkeypatch, phase=phase)
    assert result["status"] == "interrupted" and result["interrupted"]
    assert result["error_type"] == "KeyboardInterrupt"
    assert result["score"] is None and result["cleanup_completed"]
    assert result["session_deleted"] is (None if phase == "before_session" else True)
    cancel = [
        index
        for index, (method, path) in enumerate(calls)
        if method == "POST" and path.endswith("/events")
    ]
    deletes = [index for index, (method, _) in enumerate(calls) if method == "DELETE"]
    if phase == "during_turn":
        assert len(cancel) == 2 and cancel[-1] < deletes[0]
        assert result["cleanup_operations"]["cancel_turn"]["status"] == "requested"
    else:
        assert not cancel
    assert sum(args[0] == "rm" for args in docker_calls) == 2
    assert any(args[:2] == ("network", "rm") for args in docker_calls)
    saved = json.loads((tmp_path / "D01-B-1/result.json").read_text())
    assert saved == result


@pytest.mark.parametrize(
    ("deletion", "status", "diagnostic"),
    [
        ("failed", "failed", "http_403"),
        ("unknown", "unknown", "deletion_not_confirmed"),
        ("mismatched", "unknown", "deletion_not_confirmed"),
        ("timeout", "unknown", "timeout"),
    ],
)
def test_delete_requires_confirmation_and_keeps_primary_error(
    tmp_path, monkeypatch, deletion, status, diagnostic, capsys
):
    result, _, docker_calls = trial(
        tmp_path, monkeypatch, phase="ordinary_error", deletion=deletion
    )
    assert result["session_deleted"] is None
    assert result["error"].startswith("RuntimeError: Agent did not complete")
    assert result["error_type"] == "RuntimeError"
    assert not result["cleanup_completed"]
    operation = result["cleanup_operations"]["delete_session"]
    assert operation["status"] == status and operation["diagnostic"] == diagnostic
    assert sum(args[0] == "rm" for args in docker_calls) == 2
    output = capsys.readouterr().out
    assert "session deleted" not in output
    assert all(
        secret not in output + json.dumps(result) for secret in (*KEYS, "secret-auth-marker")
    )


def test_second_ctrl_c_aborts_cleanup_without_new_input(tmp_path, monkeypatch):
    result, calls, docker_calls = trial(
        tmp_path, monkeypatch, phase="during_turn", cleanup="second_interrupt"
    )
    assert result["cleanup_forced"] and result["interrupted"]
    assert result["session_deleted"] is None and not result["cleanup_completed"]
    # Regression: a second Ctrl+C used to leave the executor, MCP container and network behind.
    operations = result["cleanup_operations"]
    assert all(
        operations[name]["status"] == "confirmed"
        for name in ("remove_executor", "remove_mcp", "remove_network")
    )
    assert sum(args[0] == "rm" for args in docker_calls) == 2
    assert any(args[:2] == ("network", "rm") for args in docker_calls)
    assert result["cleanup_operations"]["cancel_turn"]["status"] == "unknown"
    assert result["cleanup_operations"]["delete_session"]["diagnostic"] == "second_interrupt"
    assert sum(method == "POST" and path.endswith("/sessions") for method, path in calls) == 1
    assert sum(method == "POST" and path.endswith("/events") for method, path in calls) == 2


def test_first_ctrl_c_during_cleanup_still_deletes(tmp_path, monkeypatch):
    result, _, _ = trial(tmp_path, monkeypatch, cleanup="first_interrupt_during_cleanup")
    assert result["interrupted"] and not result["cleanup_forced"]
    assert result["session_deleted"] is True and result["cleanup_completed"]
    assert result["score"] is None


def test_interrupted_usage_capture_still_deletes_and_keeps_primary_error(tmp_path, monkeypatch):
    result, _, _ = trial(tmp_path, monkeypatch, phase="ordinary_error", cleanup="interrupt_usage")
    assert result["error"].startswith("RuntimeError: Agent did not complete")
    assert result["session_deleted"] is True and result["cleanup_completed"]
    assert result["cleanup_operations"]["collect_usage"]["status"] == "unknown"


def test_double_interrupt_during_cleanup_preserves_original_failure(tmp_path, monkeypatch):
    result, _, _ = trial(
        tmp_path, monkeypatch, phase="ordinary_error", cleanup="double_interrupt_usage"
    )
    assert result["cleanup_forced"] and result["interrupted"]
    assert result["error"].startswith("RuntimeError: Agent did not complete")
    assert result["error_type"] == "RuntimeError" and result["session_deleted"] is None


@pytest.mark.parametrize("phase", ["creation_unknown", "creation_missing_id"])
def test_unknown_creation_never_starts_executor_or_guesses_session_id(tmp_path, monkeypatch, phase):
    result, calls, _ = trial(tmp_path, monkeypatch, phase=phase)
    assert result["session_creation_unknown"] and not result["cleanup_completed"]
    assert result["session_deleted"] is None
    assert "session_id" not in result and "executor_started_at" not in result
    assert calls == [("POST", "/v1/agents/sessions")]


@pytest.mark.parametrize("phase", ["completed", "during_turn"])
def test_interrupt_during_local_workspace_cleanup_is_saved(tmp_path, monkeypatch, phase):
    temporary_directory = simple.tempfile.TemporaryDirectory

    def temporary(*args, **kwargs):
        directory = temporary_directory(*args, **kwargs)

        def interrupt():
            raise KeyboardInterrupt()

        directory.cleanup = interrupt
        return directory

    monkeypatch.setattr(simple.tempfile, "TemporaryDirectory", temporary)
    result, _, _ = trial(tmp_path, monkeypatch, phase=phase)
    assert result["status"] == "interrupted" and result["error_type"] == "KeyboardInterrupt"
    assert result["session_deleted"] is True and not result["cleanup_completed"]
    assert result["cleanup_forced"] is (phase == "during_turn")
    if phase == "completed":
        assert result["error"] == "KeyboardInterrupt: interrupted by Ctrl+C"
        assert result["cleanup_errors"] == ["remove_workspace: interrupted"]
        assert result["error_summary"]["primary_error"]["reason_code"] == "INTERRUPTED"
        assert [error["reason_code"] for error in result["error_summary"]["cleanup_errors"]] == [
            "CLEANUP_ERROR"
        ]
    assert json.loads((tmp_path / "D01-B-1/result.json").read_text()) == result


def test_unsupported_cancel_still_attempts_delete(tmp_path, monkeypatch):
    result, _, _ = trial(tmp_path, monkeypatch, phase="during_turn", cleanup="cancel_unsupported")
    assert result["session_deleted"] is True and result["cleanup_completed"]
    assert result["cleanup_operations"]["cancel_turn"]["http_status"] == 405
    assert result["error_type"] == "KeyboardInterrupt"


def test_docker_cleanup_failure_does_not_replace_primary_error(tmp_path, monkeypatch):
    result, _, _ = trial(tmp_path, monkeypatch, phase="ordinary_error", cleanup="remove_error")
    assert result["error"].startswith("RuntimeError: Agent did not complete")
    assert result["session_deleted"] is True and not result["cleanup_completed"]
    assert result["cleanup_operations"]["remove_executor"]["diagnostic"] == "docker_exit_1"
    assert result["cleanup_operations"]["remove_network"]["status"] == "confirmed"


def test_progress_order_and_csv_remain_safe(tmp_path, monkeypatch, capsys):
    result, _, _ = trial(tmp_path, monkeypatch)
    labels = [item["event"] for item in result["progress_events"]]
    assert labels == [
        "session created",
        "Docker executor started",
        "executor connected",
        "turn started",
        "turn completed",
        "session deleted",
        "scoring started",
        "scoring completed",
        "cleanup completed",
    ]
    output = capsys.readouterr().out
    assert all(label in output for label in labels)
    assert all(secret not in output for secret in (*KEYS, "private task body marker"))
    simple.save_results(tmp_path, [result])
    with (tmp_path / "results.csv").open() as stream:
        row = next(csv.DictReader(stream))
    assert row["session_deleted"] == "True" and row["cleanup_completed"] == "True"
    assert json.loads(row["cleanup_operations"])["delete_session"]["status"] == "confirmed"


def test_heartbeat_reports_stage_without_waiting_for_sse(monkeypatch):
    observed, lines = threading.Event(), []

    def capture(message, **kwargs):
        lines.append(message)
        if "waiting:" in message:
            observed.set()

    monkeypatch.setattr("builtins.print", capture)
    progress = simple.Progress("D01-B-1", {}, interval=0.01)
    progress.set_stage("waiting for executor")
    progress.start()
    try:
        assert observed.wait(timeout=1)
    finally:
        progress.close()
    assert "waiting for executor" in lines[0] and "s]" in lines[0]
    assert not progress.thread.is_alive()


def test_cleanup_has_a_wall_clock_deadline(monkeypatch):
    monkeypatch.setattr(simple, "CLEANUP_TIMEOUT_SECONDS", 1)
    record = {"cleanup_operations": {}, "cleanup_errors": []}
    simple.cleanup_operation(
        record, "delete_session", threading.Event().wait, simple.RunInterrupts()
    )
    assert record["cleanup_operations"]["delete_session"]["diagnostic"] == "timeout"
    assert record["cleanup_operations"]["delete_session"]["duration_seconds"] < 3


def test_double_sigint_exits_process_with_a_blocked_startup_thread():
    script = r"""
import signal, threading
import httpx
from benchmarks.codex_r import run_simple as simple

interrupts = simple.RunInterrupts()
signal.signal(signal.SIGINT, interrupts.handle)
startup_entered = threading.Event()
def start():
    startup_entered.set()
    threading.Event().wait()
def respond(request):
    assert startup_entered.wait(timeout=1)
    signal.raise_signal(signal.SIGINT)
client = simple.SimpleClient("local-app", "local-executor", transport=httpx.MockTransport(respond))
try:
    list(client.send_and_stream("sess_local", "local fixture", executor_start=start))
except KeyboardInterrupt as exc:
    interrupts.note(exc)
assert client.startup_thread.daemon and client.startup_thread.is_alive()
interrupts.in_cleanup = True
record = {"cleanup_operations": {}, "cleanup_errors": []}
def stop_again():
    signal.raise_signal(signal.SIGINT)
    client.wait_for_startup()
simple.cleanup_operation(record, "startup_wait", stop_again, interrupts)
assert interrupts.forced
assert record["cleanup_operations"]["startup_wait"]["status"] == "unknown"
client.close()
print("double-interrupt-exit")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=simple.bench.REPO,
        timeout=5,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "double-interrupt-exit"


def test_ctrl_c_before_any_trial_saves_interrupted_startup(tmp_path, monkeypatch):
    for name, key in zip(simple.KEY_NAMES, KEYS, strict=True):
        monkeypatch.setenv(name, key)
    monkeypatch.setattr(simple.shutil, "which", lambda _: "docker")

    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(simple, "image_id", interrupt)
    assert simple.main(["--effort", "medium", "--tasks", "D01", "--results", str(tmp_path)]) == 130
    record = json.loads(next(tmp_path.glob("*/results.json")).read_text())[0]
    assert record["status"] == "interrupted" and record["error"] == "KeyboardInterrupt"


@pytest.mark.parametrize(
    ("first", "expected_calls", "exit_code"),
    [
        ("ordinary", 2, 1),
        ("interrupted", 1, 130),
        ("cleanup_incomplete", 1, 1),
    ],
)
def test_main_continues_only_after_an_ordinary_task_error(
    tmp_path, monkeypatch, first, expected_calls, exit_code
):
    for name, key in zip(simple.KEY_NAMES, KEYS, strict=True):
        monkeypatch.setenv(name, key)
    monkeypatch.setattr(simple.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(simple, "image_id", lambda _: "test")
    calls = []

    def run(
        args,
        task,
        mode,
        repetition,
        output,
        keys,
        images,
        *,
        condition=None,
        execution_order=None,
        planned_trial_id=None,
    ):
        calls.append(task)
        # Standard plans carry no B1 condition or execution order.
        assert condition is None and execution_order is None
        assert planned_trial_id == f"{task}-A-{repetition}"
        failed = len(calls) == 1
        return {
            "trial": task,
            "status": "error" if failed else "scored",
            "score": None,
            "error": "test failure" if failed else None,
            "interrupted": failed and first == "interrupted",
            "cleanup_completed": not (failed and first == "cleanup_incomplete"),
        }

    monkeypatch.setattr(simple, "run_trial", run)
    code = simple.main(
        [
            "--effort",
            "medium",
            "--tasks",
            "D01",
            "D02",
            "--modes",
            "without-mcp",
            "--results",
            str(tmp_path),
        ]
    )
    assert code == exit_code and len(calls) == expected_calls
    records = json.loads(next(tmp_path.glob("*/results.json")).read_text())
    assert len(records) == expected_calls


def watchdog_client(environment_status):
    def respond(request):
        assert request.method == "GET" and request.url.path == "/v1/agents/sessions/sess_w"
        return httpx.Response(
            200, json={"environment": {"status": environment_status, "error": KEYS[0]}}
        )

    return REAL_CLIENT(*KEYS, transport=httpx.MockTransport(respond))


@pytest.mark.parametrize(("status", "missed"), [("pending", False), ("connected", True)])
def test_connect_watchdog_records_readonly_evidence_without_aborting(monkeypatch, status, missed):
    monkeypatch.setattr(
        simple,
        "docker",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, '{"Status": "running", "Running": true}', KEYS[1]
        ),
    )
    record, labels = {}, []
    progress = type("P", (), {"event": lambda self, label, **kw: labels.append(label)})()
    client = watchdog_client(status)
    simple.watch_executor_connection(
        client, record, progress, "executor", "sess_w", KEYS, seconds=0.01
    )
    evidence = record["executor_connect_watchdog"]
    assert evidence["api_environment_status"] == status
    assert evidence["sse_event_possibly_missed"] is missed
    assert evidence["executor"]["running"] is True
    assert labels == ["executor not connected"]
    assert KEYS[0] not in json.dumps(record) and KEYS[1] not in json.dumps(record)
    client.close()


def test_connect_watchdog_is_silent_when_executor_connects(monkeypatch):
    record, labels = {}, []
    progress = type("P", (), {"event": lambda self, label, **kw: labels.append(label)})()
    client = watchdog_client("connected")
    client.executor_connected.set()
    simple.watch_executor_connection(
        client, record, progress, "executor", "sess_w", KEYS, seconds=0.01
    )
    assert record == {} and labels == []
    client.close()
