"""Unit and real-container checks for the non-model Docker boundary."""

import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/codex_r"
spec = importlib.util.spec_from_file_location(
    "codex_r_docker_runtime", ROOT / "exploratory/docker_runtime.py"
)
docker_runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docker_runtime)


def test_docker_runtime_requires_an_immutable_image_id():
    with pytest.raises(docker_runtime.DockerRuntimeError, match="immutable sha256"):
        docker_runtime.DockerCandidateRuntime("codex-r-benchmark:pilot")


def test_executor_environment_strips_both_application_and_host_scoped_keys():
    environment = docker_runtime._executor_child_environment(
        {
            "OPENAI_API_KEY": "synthetic-app-secret",
            "OPENAI_EXECUTOR_API_KEY": "synthetic-host-restricted-secret",
            "CODEX_API_KEY": "stale-key",
            "PATH": "/usr/bin",
            "LANG": "C.UTF-8",
        },
        "synthetic-container-restricted-key",
    )
    assert environment == {
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "CODEX_API_KEY": "synthetic-container-restricted-key",
    }


def test_fixed_r01_probe_configuration_has_no_host_capability_mounts(tmp_path):
    runtime = docker_runtime.DockerCandidateRuntime("sha256:" + "a" * 64, docker="docker")
    args = runtime._create_args(
        "rkmcp-probe-R01-A-0123456789abcdef",
        tmp_path,
        ["/bin/sh", "-c", docker_runtime.PROBE_SCRIPT],
    )
    assert "--network" in args and args[args.index("--network") + 1] == "none"
    assert "--read-only" in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges:true" in args
    assert args[args.index("--user") + 1] == "65534:65534"
    assert args.count("--mount") == 1
    assert args[args.index("--mount") + 1].endswith("target=/candidate")
    assert "docker.sock" not in args[args.index("--mount") + 1]
    assert "CODEX_HOME=/tmp" in args
    assert args[args.index("--env") + 1] == "HOME=/tmp"


def test_boundary_probe_shell_failure_commands_are_defined_and_portable():
    assert "fail direct_gateway_bypass_reachable" in docker_runtime.PROBE_SCRIPT
    assert "fail_direct_gateway_bypass_reachable" not in docker_runtime.PROBE_SCRIPT
    # Proxy variables are explicitly empty in _create_args, so env -u is not
    # needed and would unnecessarily depend on non-POSIX env extensions.
    assert "env -u " not in docker_runtime.PROBE_SCRIPT


def test_docker_wait_classifies_cli_failure_and_container_exit_status():
    def completed(returncode, stdout=b"", stderr=b""):
        return subprocess.CompletedProcess(["docker", "wait"], returncode, stdout, stderr)

    assert docker_runtime.DockerCandidateRuntime._docker_wait_exit_code(completed(0, b"0\n")) == 0
    assert docker_runtime.DockerCandidateRuntime._docker_wait_exit_code(completed(0, b"20\n")) == 20
    with pytest.raises(docker_runtime.DockerRuntimeError) as cli_error:
        docker_runtime.DockerCandidateRuntime._docker_wait_exit_code(
            completed(125, stderr=b"daemon unavailable")
        )
    assert cli_error.value.diagnostics["docker_cli_exit_code"] == 125
    with pytest.raises(docker_runtime.DockerRuntimeError, match="valid container exit status"):
        docker_runtime.DockerCandidateRuntime._docker_wait_exit_code(completed(0))


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            b"Cannot connect to the Docker daemon: synthetic-private-detail",
            "docker_daemon_unavailable",
        ),
        (b"No such image: synthetic-image-label", "image_unavailable"),
        (
            b"invalid mount config: permission denied at synthetic-path",
            "mount_or_workspace_failure",
        ),
        (b"unrecognized synthetic Docker failure", "cli_nonzero"),
    ],
)
def test_docker_cli_failure_diagnostics_are_classified_without_persisting_stderr(stderr, expected):
    argv = ["docker", "info"]
    runtime = docker_runtime.DockerCandidateRuntime(
        "sha256:" + "a" * 64,
        docker="docker",
        command_runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            argv, 125, b"", stderr
        ),
    )

    with pytest.raises(docker_runtime.DockerRuntimeError) as caught:
        runtime._docker("info")

    assert caught.value.diagnostics["reason_code"] == expected
    assert caught.value.diagnostics["docker_cli_exit_code"] == 125
    assert "synthetic-private-detail" not in repr(caught.value.diagnostics)
    assert "synthetic-path" not in repr(caught.value.diagnostics)


def test_container_creation_classifies_image_failure_and_verifies_cleanup():
    calls = []

    def command_runner(argv, *, timeout, env):
        calls.append(argv[1])
        if argv[1] == "create":
            return subprocess.CompletedProcess(
                argv, 125, b"", b"No such image: synthetic-private-image-label"
            )
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    runtime = docker_runtime.DockerCandidateRuntime(
        "sha256:" + "a" * 64, docker="docker", command_runner=command_runner
    )
    with pytest.raises(docker_runtime.DockerRuntimeError) as caught:
        runtime._create_container("rkmcp-probe-R01-A-0123456789abcdef", ["docker", "create"])

    assert caught.value.diagnostics["reason_code"] == "image_unavailable"
    assert caught.value.diagnostics["docker_cli_exit_code"] == 125
    assert "synthetic-private-image-label" not in repr(caught.value.diagnostics)
    assert calls == ["create", "rm", "ps"]


def test_container_logs_include_stderr_for_failure_diagnostics():
    def command_runner(argv, *, timeout, env):
        assert argv[1:3] == ["logs", "a" * 64]
        return subprocess.CompletedProcess(argv, 0, b"", b"probe failed: public_fixture_missing\n")

    runtime = docker_runtime.DockerCandidateRuntime(
        "sha256:" + "a" * 64, docker="docker", command_runner=command_runner
    )
    assert runtime._logs("a" * 64) == "probe failed: public_fixture_missing\n"


def test_prepared_candidate_workspace_grants_only_directory_acl_to_executor_uid(monkeypatch):
    commands = []
    monkeypatch.setattr(docker_runtime, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(docker_runtime.shutil, "which", lambda name: "/usr/bin/setfacl")

    def fake_run(argv, *, timeout):
        commands.append((argv, timeout))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(docker_runtime, "_bounded_run", fake_run)
    temp_root = Path(tempfile.gettempdir()) / f"synthetic-r01-public-{uuid4().hex}"
    temp_root.mkdir(mode=0o755)
    try:
        destination = temp_root / "workspace"
        report = docker_runtime.prepared_r01_workspace(destination, candidate_writable=True)

        assert sorted(report["files"]) == ["TASK.md", "data/records.csv", "renv.lock"]
        assert len(commands) == 1
        argv, timeout = commands[0]
        assert argv == [
            "/usr/bin/setfacl",
            "-m",
            "u:65534:rwx",
            "--",
            str(destination.resolve()),
        ]
        assert "-R" not in argv and timeout == 10
        assert (destination / "TASK.md").is_file()
        assert (destination / "data/records.csv").is_file()
        assert (destination / "renv.lock").is_file()
    finally:
        shutil.rmtree(temp_root)


def test_f09_acl_reader_uses_numeric_ids_and_matches_ubuntu_grant_acl(monkeypatch):
    calls = []
    monkeypatch.setattr(docker_runtime.shutil, "which", lambda name: "/usr/bin/getfacl")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        # getfacl without -n may print the local account name for UID 65534.
        output = (
            b"user::rwx\nuser:65534:rwx\ngroup::---\nmask::rwx\nother::---\n"
            if "n" in argv[1]
            else b"user::rwx\nuser:nobody:rwx\ngroup::---\nmask::rwx\nother::---\n"
        )
        return subprocess.CompletedProcess(argv, 0, output, b"")

    monkeypatch.setattr(docker_runtime.subprocess, "run", fake_run)
    acl = docker_runtime._read_f09_workspace_acl(Path("synthetic-workspace"), {}, timeout=2)

    assert calls[0][1] == "-cpn"
    assert docker_runtime._has_reviewed_f09_workspace_acl(acl)
    assert not docker_runtime._has_reviewed_f09_workspace_acl(
        "user::rwx\nuser:nobody:rwx\ngroup::---\nmask::rwx\nother::---\n"
    )


def test_f09_revoked_acl_accepts_only_harmless_empty_mask():
    assert docker_runtime._has_private_revoked_f09_workspace_acl(
        "user::rwx\ngroup::---\nmask::---\nother::---\n"
    )
    assert docker_runtime._has_private_revoked_f09_workspace_acl(
        "user::rwx\ngroup::---\nother::---\n"
    )
    assert not docker_runtime._has_private_revoked_f09_workspace_acl(
        "user::rwx\nuser:65534:rwx\ngroup::---\nmask::rwx\nother::---\n"
    )
    assert not docker_runtime._has_private_revoked_f09_workspace_acl(
        "user::rwx\ngroup::---\ngroup:65534:rwx\nmask::rwx\nother::---\n"
    )
    assert not docker_runtime._has_private_revoked_f09_workspace_acl(
        "user::rwx\ngroup::---\nmask::rwx\nother::---\n"
    )


@pytest.mark.skipif(
    os.name != "posix" or not shutil.which("getfacl") or not shutil.which("setfacl"),
    reason="real F09 ACL integration requires Linux getfacl/setfacl",
)
def test_f09_workspace_acl_grant_and_revoke_on_native_tmp_filesystem(tmp_path):
    workspace_root = tmp_path.resolve()
    if not workspace_root.is_relative_to(Path("/tmp")):
        pytest.skip("run with --basetemp under native Linux /tmp")
    workspace = workspace_root / "f09-acl-workspace"
    workspace.mkdir(mode=0o700)
    runtime = docker_runtime.F09ConnectivityRuntime(
        "sha256:" + "a" * 64,
        workspace_root,
    )

    assert workspace.stat().st_mode & 0o777 == 0o700
    runtime.grant_workspace_access(workspace)
    assert workspace.stat().st_mode & 0o777 == 0o770
    assert docker_runtime._has_reviewed_f09_workspace_acl(
        docker_runtime._read_f09_workspace_acl(workspace, {})
    )

    assert runtime.revoke_workspace_access(workspace, timeout=5)
    assert not workspace.exists()


def test_restricted_executor_uses_private_proxy_and_fail_closed_dns(tmp_path):
    runtime = docker_runtime.CodexCandidateRuntime("sha256:" + "a" * 64, docker="docker")
    proxy_url = "http://172.20.0.2:3128"
    args = runtime._create_args(
        "rkmcp-probe-R01-A-0123456789abcdef",
        tmp_path,
        ["/bin/sh", "-c", docker_runtime.EGRESS_PROBE_SCRIPT],
        network_mode="rkmcp-candidate-R01-A-0123456789ab",
        proxy_enabled=True,
        proxy_url=proxy_url,
        deny_dns=True,
    )
    assert args[args.index("--network") + 1] == "rkmcp-candidate-R01-A-0123456789ab"
    assert args[args.index("--dns") + 1] == "127.0.0.1"
    assert args.count("--mount") == 1
    assert f"HTTPS_PROXY={proxy_url}" in args
    assert "CODEX_API_KEY" not in args


def _docker_runtime():
    image_id = os.environ.get("R_KNOWLEDGE_BENCH_IMAGE_ID")
    if not image_id:
        pytest.skip("Set R_KNOWLEDGE_BENCH_IMAGE_ID to run real Docker integration tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")
    available = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if available.returncode:
        pytest.skip("Docker daemon is unavailable")
    return docker_runtime.DockerCandidateRuntime(image_id)


def _codex_runtime():
    image_id = os.environ.get("R_KNOWLEDGE_CODEX_IMAGE_ID")
    if not image_id:
        pytest.skip("Set R_KNOWLEDGE_CODEX_IMAGE_ID to test the pinned Codex image")
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")
    available = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if available.returncode:
        pytest.skip("Docker daemon is unavailable")
    return docker_runtime.CodexCandidateRuntime(image_id)


@pytest.mark.docker
def test_real_docker_denies_host_evaluator_secret_and_network_access(tmp_path):
    runtime = _docker_runtime()
    # These are synthetic sentinels; no real user credentials are inspected.
    (tmp_path / "host-test-secret").mkdir()
    (tmp_path / "host-test-secret" / "private-marker").write_text("synthetic\n")
    (tmp_path / "other-trial").mkdir()
    (tmp_path / "other-trial" / "private-marker").write_text("synthetic\n")
    workspace = tmp_path / "candidate-R01-A"
    docker_runtime.prepared_r01_workspace(workspace, candidate_writable=True)
    report = runtime.run_boundary_probe(workspace)

    assert report["record_type"] == "docker_candidate_boundary_probe_not_agent_trial"
    assert report["isolation_verified_for_fixed_probe_only"] is True
    assert report["agent_isolation_verified"] is False
    assert report["launch_permitted"] is False
    assert report["container_cleanup_verified"] is True
    assert report["policy"]["network_mode"] == "none"
    assert report["policy"]["read_only_rootfs"] is True
    assert report["policy"]["user"] == "65534:65534"
    assert report["policy"]["memory_swap_bytes"] == report["policy"]["memory_bytes"]
    assert report["policy"]["privileged"] is False
    assert report["policy"]["bind_mounts"][0]["destination"] == "/candidate"
    assert report["negative_checks"] == {
        "oracle_paths_absent": True,
        "repository_mount_absent": True,
        "home_and_credential_mounts_absent": True,
        "credential_environment_absent": True,
        "docker_socket_absent": True,
        "other_trial_mount_absent": True,
        "arbitrary_internet_denied": True,
        "model_proxy_unavailable_in_A": True,
        "direct_gateway_bypass_denied": True,
        "mcp_tools_exposed": 0,
        "effective_codex_tools_verified": False,
        "condition_a_tools_verified": False,
    }
    assert sorted(
        path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file()
    ) == ["TASK.md", "data/records.csv", "renv.lock"]


@pytest.mark.docker
def test_real_docker_timeout_force_removes_container_and_child_process(tmp_path):
    runtime = _docker_runtime()
    report = runtime.run_timeout_probe(timeout_seconds=1)
    assert report["record_type"] == "docker_process_tree_timeout_probe_not_trial"
    assert report["child_process_created"] is True
    assert report["container_removed"] is True
    assert report["status"] == "container_cgroup_force_removed"
    assert report["model_requests"] == report["sessions_created"] == 0


@pytest.mark.docker
def test_frozen_image_digest_and_embedded_lockfile_are_verified():
    report = _docker_runtime().verify_engine_and_image()
    assert report["image_id"] == os.environ["R_KNOWLEDGE_BENCH_IMAGE_ID"]
    assert report["renv_lock_sha256"]
    assert report["server_version"]
    assert report["os_type"] == "linux"


@pytest.mark.docker
def test_real_codex_exec_server_starts_in_offline_isolated_candidate(tmp_path_factory):
    runtime = _codex_runtime()
    workspace = tmp_path_factory.getbasetemp() / "public-candidate-R01-A"
    docker_runtime.prepared_r01_workspace(workspace, candidate_writable=True)
    report = runtime.run_offline_executor_probe(workspace, timeout_seconds=5)

    assert report["record_type"] == "codex_exec_server_offline_startup_probe_not_trial"
    assert report["image"]["codex_version"] == "0.163.0"
    assert report["image"]["rootfs_layers_preserve_base"] is True
    assert report["codex_exec_server_process_observed"] is True
    assert report["negative_checks_passed"] is True
    assert report["application_key_in_container"] is False
    assert report["restricted_environment_key_present"] is False
    assert report["network_mode"] == "none"
    assert report["mcp_tools_exposed"] == 0
    assert report["effective_agent_tools_verified"] is False
    assert report["container_cleanup_verified"] is True
    assert report["launch_permitted"] is False


@pytest.mark.docker
def test_real_docker_restricted_egress_denies_bypass_without_upstream_requests(
    tmp_path_factory,
):
    image_id = os.environ.get("R_KNOWLEDGE_CODEX_IMAGE_ID")
    if not image_id:
        pytest.skip("Set R_KNOWLEDGE_CODEX_IMAGE_ID to test the restricted executor boundary")
    workspace = tmp_path_factory.getbasetemp() / "public-egress-candidate-R01-A"
    docker_runtime.prepared_r01_workspace(workspace)
    report = docker_runtime.run_restricted_egress_probe(image_id, workspace)
    assert report["record_type"] == "offline_restricted_egress_test_not_real_trial"
    assert report["status"] == "offline_policy_checks_passed_upstream_not_contacted"
    assert report["negative_checks"] == {
        "direct_public_ip_denied": True,
        "cloud_metadata_ip_denied": True,
        "arbitrary_domain_denied_by_proxy": True,
        "IP_literal_proxy_target_denied": True,
        "non_443_proxy_target_denied": True,
        "unrestricted_dns_denied": True,
        "host_docker_service_denied": True,
        "docker_socket_unavailable": True,
        "candidate_has_only_internal_network": True,
    }
    assert report["candidate_container_removed"] is True
    assert report["egress_proxy_and_networks_removed"] is True
    assert report["sessions_created"] == report["inference_requests"] == 0
    assert report["launch_permitted"] is False


@pytest.mark.docker
def test_real_codex_exec_server_uses_proxy_without_contacting_upstream(tmp_path_factory):
    image_id = os.environ.get("R_KNOWLEDGE_CODEX_IMAGE_ID")
    if not image_id:
        pytest.skip("Set R_KNOWLEDGE_CODEX_IMAGE_ID to test Codex proxy transport")
    workspace = tmp_path_factory.getbasetemp() / "public-proxy-candidate-R01-A"
    docker_runtime.prepared_r01_workspace(workspace)
    report = docker_runtime.run_codex_proxy_transport_probe(image_id, workspace)
    assert report["record_type"] == "offline_codex_proxy_transport_test_not_real_registration"
    assert report["codex_https_proxy_connect_observed"] is True
    assert report["observed_target"] == "api.openai.com:443"
    assert report["upstream_hosts_contacted"] == []
    assert report["tls_handshake_performed"] is False
    assert report["websocket_registration_verified"] is False
    assert report["sessions_created"] == report["inference_requests"] == 0
    assert report["launch_permitted"] is False
    assert report["candidate_container_removed"] is True
    assert report["local_proxy_container_removed"] is True
    assert report["isolated_network_removed"] is True
