"""Prove the shared R01-A offline guard blocks live actions safely."""

import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("r01a_offline_guard")


def test_external_dns_and_socket_connections_are_blocked_before_io():
    with pytest.raises(AssertionError, match="blocked external network"):
        socket.getaddrinfo("api.openai.com", 443)
    with pytest.raises(AssertionError, match="blocked external network"):
        socket.gethostbyname("api.openai.com")

    fake_socket = SimpleNamespace(family=socket.AF_INET)
    with pytest.raises(AssertionError, match="blocked external network"):
        socket.socket.connect(fake_socket, ("198.51.100.42", 443))
    with pytest.raises(AssertionError, match="blocked external network"):
        socket.socket.connect_ex(fake_socket, ("198.51.100.42", 443))
    with pytest.raises(AssertionError, match="blocked external network"):
        socket.socket.sendto(fake_socket, b"synthetic", ("198.51.100.42", 53))
    with pytest.raises(AssertionError, match="blocked external network"):
        socket.socket.bind(fake_socket, ("0.0.0.0", 8080))


def test_live_commands_are_rejected_before_process_creation(monkeypatch):
    attempted_launches = []

    def forbidden_launcher(*args, **kwargs):
        attempted_launches.append((args, kwargs))
        raise RuntimeError("synthetic launcher sentinel")

    monkeypatch.setattr(subprocess, "Popen", forbidden_launcher)
    with pytest.raises(AssertionError, match="blocked a live or external command"):
        subprocess.run(["docker", "version"], check=False)
    with pytest.raises(AssertionError, match="blocked a live or external command"):
        subprocess.run([sys.executable, "adapter.py", "authorize-one"], check=False)
    assert attempted_launches == []


def test_popen_guard_blocks_benchmark_command_without_starting_it():
    # If the guard is broken, this harmless Python child only executes ``pass``.
    try:
        process = subprocess.Popen([sys.executable, "-c", "pass", "run-one"])
    except AssertionError as exc:
        assert "blocked a live or external command" in str(exc)
    else:
        process.wait(timeout=5)
        pytest.fail("Popen accepted a live benchmark subcommand")


def test_synthetic_python_child_process_remains_available():
    result = subprocess.run(
        [sys.executable, "-c", "print('synthetic offline child')"],
        capture_output=True,
        check=True,
        text=True,
        timeout=5,
    )
    assert result.stdout.strip() == "synthetic offline child"
