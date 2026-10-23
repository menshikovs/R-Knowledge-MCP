"""Unit and real-container checks for the non-model Docker boundary."""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

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
    assert not any("CODEX_HOME" in argument for argument in args)
    assert args[args.index("--env") + 1] == "HOME=/tmp"


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
    docker_runtime.prepared_r01_workspace(workspace)
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
    docker_runtime.prepared_r01_workspace(workspace)
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
