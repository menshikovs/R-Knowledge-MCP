"""Explicitly authorized, one-session connection probe; never submits model input.

Run --help offline. Running with --allow-session-create requires separate user
authorization; the flag is an operator gate, not a claim that sessions are free.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from benchmarks.codex_r import run_simple as simple
from benchmarks.codex_r.connection_diagnostics import (
    ConnectionJournal,
    failure_outcome,
    runtime_evidence,
)


class ConnectionOnlyClient(simple.SimpleClient):
    def submit_task(self, *args, **kwargs):
        raise RuntimeError("Connection probe cannot submit input")


def observe_executor(journal, name, keys):
    observed = simple.executor_diagnostics(name, keys, timeout=5)
    facts = runtime_evidence(observed.get("stdout", "") + observed.get("stderr", ""))
    outcome = facts.pop("outcome", "unknown")
    if observed.get("running") is False:
        outcome = "process_exited"
    journal.emit(
        "connection_observation",
        outcome=outcome,
        running=observed.get("running"),
        exit_code=observed.get("exit_code"),
        **facts,
    )


def run_probe(output, keys, image, *, seconds=60, client_factory=ConnectionOnlyClient):
    """One creation, no retries, bounded wait, independent cleanup attempts."""
    output.mkdir(parents=True, exist_ok=False)
    journal = ConnectionJournal(output / "connection.jsonl")
    client = client_factory(*keys)
    client.connection_journal = journal
    suffix = uuid.uuid4().hex[:16]
    network, executor = (f"rkmcp-connect-{suffix}-{part}" for part in ("net", "exec"))
    stop = threading.Event()
    monitor = None
    temporary = tempfile.TemporaryDirectory(prefix="rkmcp-connect-")
    previous = signal.signal(signal.SIGALRM, simple.deadline_expired)
    succeeded = False
    cleanup_ok = True
    creation_attempted = False
    try:
        signal.alarm(seconds)
        workspace = Path(temporary.name) / "candidate"
        workspace.mkdir(mode=0o777)
        workspace.chmod(0o777)
        Path(temporary.name).chmod(0o755)
        simple.docker("network", "create", network)
        creation_attempted = True
        environment = client.create_simple_session("medium", False)

        def launch():
            nonlocal monitor
            journal.emit("executor_start_requested")
            try:
                simple.start_executor(executor, network, image, workspace, environment, keys[1])
            finally:
                if client.stopping.is_set():
                    simple.docker("rm", "--force", executor, check=False, timeout=10)
            if client.stopping.is_set():
                return
            journal.emit("executor_started")

            def sample():
                while not stop.is_set():
                    try:
                        observe_executor(journal, executor, keys)
                    except Exception as exc:
                        journal.emit("connection_observation", outcome="unknown", exception=exc)
                    if stop.wait(2):
                        break

            monitor = threading.Thread(target=sample, daemon=True)
            monitor.start()

        for _ in client.send_and_stream(
            environment["session_id"],
            None,
            deadline_seconds=seconds,
            executor_start=launch,
            connect_only=True,
        ):
            pass  # Never persist event bodies, even if the server unexpectedly supplies them.
        succeeded = client.executor_connected.is_set()
    except (Exception, KeyboardInterrupt) as exc:
        journal.emit("wait_finished", outcome=failure_outcome(exc), exception=exc)
    finally:
        signal.alarm(0)
        stop.set()
        client.stopping.set()
        if monitor is not None:
            monitor.join(timeout=11)
        journal.emit("cleanup_started")

        def delete_session():
            if client.session_id_for_cleanup:
                result = client.delete_session(client.session_id_for_cleanup)
                if (
                    result.get("deleted") is not True
                    or result.get("id") != client.session_id_for_cleanup
                ):
                    raise RuntimeError("Session deletion not confirmed")
            elif creation_attempted and (
                client._last_response_status is None or 200 <= client._last_response_status < 300
            ):
                raise RuntimeError("Session creation outcome unknown")

        def remove(*args):
            result = simple.docker(*args, check=False, timeout=10)
            if result.returncode and not any(
                marker in result.stderr for marker in ("No such container", "not found")
            ):
                raise RuntimeError("Local cleanup not confirmed")

        # Keep the workspace until startup has settled and container removal was attempted.
        client.cleanup_timeout = 10
        for name, operation in (
            ("startup_wait", client.wait_for_startup),
            ("capture_executor", lambda: observe_executor(journal, executor, keys)),
            ("delete_session", delete_session),
            ("remove_executor", lambda: remove("rm", "--force", executor)),
            ("remove_network", lambda: remove("network", "rm", network)),
            ("close_client", client.close),
            ("remove_workspace", temporary.cleanup),
        ):
            signal.alarm(12)
            try:
                operation()
                journal.emit("cleanup_finished", operation=name, confirmed=True)
            except (Exception, KeyboardInterrupt) as exc:
                cleanup_ok = False
                journal.emit(
                    "cleanup_finished",
                    operation=name,
                    confirmed=False,
                    outcome=failure_outcome(exc),
                    exception=exc,
                )
            finally:
                signal.alarm(0)
        journal.emit("cleanup_finished", outcome="unknown" if not cleanup_ok else None)
        signal.signal(signal.SIGALRM, previous)
    return 0 if succeeded and cleanup_ok and not journal.write_failed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-session-create", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executor-image", default="rkmcp-codex-runtime:codex-0.163.0-bioc")
    parser.add_argument(
        "--seconds", type=int, choices=range(10, 121), default=60, metavar="10..120"
    )
    args = parser.parse_args(argv)
    if not args.allow_session_create:
        parser.error("Separate user authorization and --allow-session-create are required")
    if sys.platform != "linux":
        parser.error("Use Ubuntu WSL2 or Linux")
    keys = tuple(os.environ.get(name, "") for name in simple.KEY_NAMES)
    if not all(key.strip() for key in keys):
        parser.error("Both application and restricted executor credentials are required")
    return run_probe(args.output, keys, simple.image_id(args.executor_image), seconds=args.seconds)


if __name__ == "__main__":
    raise SystemExit(main())
