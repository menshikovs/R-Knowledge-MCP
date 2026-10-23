"""Docker-backed, no-network candidate boundary probes for the exploratory pilot.

This module can run fixed security probes in the frozen R image. It does not
install Codex, supply credentials, connect a model proxy, or launch an agent.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
_PILOT_SPEC = importlib.util.spec_from_file_location(
    "codex_r_docker_pilot", ROOT / "exploratory" / "pilot.py"
)
if _PILOT_SPEC is None or _PILOT_SPEC.loader is None:
    raise RuntimeError("Exploratory pilot module could not be loaded")
pilot = importlib.util.module_from_spec(_PILOT_SPEC)
_PILOT_SPEC.loader.exec_module(pilot)
MAX_OUTPUT_BYTES = 1 << 20
CONTAINER_NAME = re.compile(r"^rkmcp-probe-R01-A-[a-f0-9]{16}$")
IMAGE_ID = re.compile(r"^sha256:[a-f0-9]{64}$")
PROBE_SCRIPT = r"""set -eu
fail() { echo "probe failed: $1" >&2; exit 20; }
[ "$(id -u)" = 65534 ] || fail unprivileged_uid
[ -r /candidate/TASK.md ] || fail public_task_missing
[ -r /candidate/renv.lock ] || fail public_lock_missing
[ -r /candidate/data/records.csv ] || fail public_fixture_missing
[ -w /candidate ] || fail candidate_workspace_not_writable
for p in \
  /oracle/R01.R \
  /repo/benchmarks/codex_r/oracle/R01.R \
  /mnt/c/programming_pj/cran-mcp \
  /root/.codex/auth.json \
  /tmp/.codex/auth.json \
  /var/run/docker.sock \
  /other-trial/private-marker \
  /host-test-secret/private-marker; do
  [ ! -e "$p" ] || fail "unexpected_path:$p"
done
if env | cut -d= -f1 | grep -E \
  '^(OPENAI_API_KEY|CODEX_API_KEY|AZURE_OPENAI_API_KEY)$' >/dev/null; then
  fail credential_environment_present
fi
[ -x "$(command -v curl)" ] || fail curl_unavailable_for_egress_probe
if env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  curl --noproxy '*' --connect-timeout 2 --max-time 3 -fsS \
  https://example.com/ >/dev/null 2>&1; then
  fail arbitrary_internet_reachable
fi
if env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS \
  http://model-proxy:8080/v1/responses >/dev/null 2>&1; then
  fail model_proxy_reachable_in_offline_condition_A
fi
if env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS \
  http://cran-knowledge-mcp:8000/mcp >/dev/null 2>&1; then
  fail_direct_gateway_bypass_reachable
fi
printf '%s\n' 'docker boundary probe passed'
"""
SLEEP_SCRIPT = 'sleep 60 & child=$!; echo child_started; wait "$child"'


class DockerRuntimeError(RuntimeError):
    """Docker daemon, image, workspace, or policy verification failed."""


class DockerCommandTimeout(DockerRuntimeError):
    """A local Docker CLI operation exceeded its own deadline."""


def _load_controller():
    spec = importlib.util.spec_from_file_location(
        "codex_r_docker_controller", ROOT / "runner" / "controller.py"
    )
    if spec is None or spec.loader is None:
        raise DockerRuntimeError("Benchmark controller could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bounded_run(argv: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DockerCommandTimeout("Docker command exceeded its local deadline") from exc
    except OSError as exc:
        raise DockerRuntimeError("Docker command failed or timed out") from exc
    if len(result.stdout) + len(result.stderr) > MAX_OUTPUT_BYTES:
        raise DockerRuntimeError("Docker command output exceeded its byte limit")
    return result


class DockerCandidateRuntime:
    """Create and audit one disposable networkless R01-A candidate container."""

    def __init__(self, image_id: str, docker: str | None = None):
        if not IMAGE_ID.fullmatch(image_id):
            raise DockerRuntimeError("Use the immutable sha256 image ID, not a tag")
        self.docker = docker or shutil.which("docker")
        if not self.docker:
            raise DockerRuntimeError("Docker CLI was not found")
        self.image_id = image_id

    def _docker(self, *args: str, timeout: int = 20) -> subprocess.CompletedProcess:
        result = _bounded_run([self.docker, *args], timeout=timeout)
        if result.returncode != 0:
            raise DockerRuntimeError("Docker daemon rejected a required operation")
        return result

    def _assert_removed(self, container_id: str) -> None:
        result = self._docker(
            "ps", "--all", "--filter", f"id={container_id}", "--format", "{{.ID}}"
        )
        if result.stdout.strip():
            raise DockerRuntimeError("Disposable container still exists after cleanup")

    def _assert_name_absent(self, name: str) -> None:
        result = self._docker("ps", "--all", "--filter", f"name=^/{name}$", "--format", "{{.ID}}")
        if result.stdout.strip():
            raise DockerRuntimeError("Disposable container still exists after cleanup")

    def _create_container(self, name: str, argv: list[str]) -> str:
        try:
            result = _bounded_run(argv)
        except DockerRuntimeError:
            try:
                _bounded_run([self.docker, "rm", "--force", name], timeout=20)
                self._assert_name_absent(name)
            except DockerRuntimeError as cleanup_error:
                raise DockerRuntimeError(
                    "Container creation timed out and cleanup could not be verified"
                ) from cleanup_error
            raise
        if result.returncode != 0:
            self._assert_name_absent(name)
            raise DockerRuntimeError("Docker failed to create the candidate probe container")
        container_id = result.stdout.decode("utf-8", "replace").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            _bounded_run([self.docker, "rm", "--force", name], timeout=20)
            self._assert_name_absent(name)
            raise DockerRuntimeError("Docker returned an invalid container identifier")
        return container_id

    def verify_engine_and_image(self) -> dict:
        version = (
            self._docker("version", "--format", "{{.Client.Version}}|{{.Server.Version}}")
            .stdout.decode("utf-8", "replace")
            .strip()
        )
        client_version, separator, server_version = version.partition("|")
        if not separator or not client_version or not server_version:
            raise DockerRuntimeError("Docker client and server are not both available")
        info = self._docker("info", "--format", "{{.OSType}}|{{.Architecture}}")
        os_type, separator, architecture = (
            info.stdout.decode("utf-8", "replace").strip().partition("|")
        )
        if not separator or os_type != "linux":
            raise DockerRuntimeError("Docker Desktop must provide a Linux container engine")
        image = (
            self._docker(
                "image",
                "inspect",
                "--format",
                "{{.Id}}|{{.Config.User}}|{{.Config.WorkingDir}}",
                self.image_id,
            )
            .stdout.decode("utf-8", "replace")
            .strip()
        )
        image_digest, separator, identity = image.partition("|")
        image_user, separator, workdir = identity.partition("|")
        if image_digest != self.image_id or not separator:
            raise DockerRuntimeError("Local image ID does not match the requested digest")
        if image_user != "65534:65534" or workdir != "/candidate":
            raise DockerRuntimeError("Frozen image user or work directory differs from protocol")
        lock_hash = hashlib.sha256((ROOT / "configs" / "renv.lock").read_bytes()).hexdigest()
        remote_hash = (
            self._docker(
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "sha256sum",
                self.image_id,
                "/config/renv.lock",
            )
            .stdout.decode("utf-8", "replace")
            .split()[0]
        )
        if remote_hash != lock_hash:
            raise DockerRuntimeError(
                "Frozen image lockfile does not match the reviewed benchmark lock"
            )
        return {
            "client_version": client_version,
            "server_version": server_version,
            "os_type": os_type,
            "architecture": architecture,
            "image_id": image_digest,
            "image_user": image_user,
            "image_workdir": workdir,
            "renv_lock_sha256": remote_hash,
            "verified_at": datetime.now(UTC).isoformat(),
        }

    def _validate_workspace(self, workspace: Path) -> dict:
        controller = _load_controller()
        try:
            report = controller.validate_public_workspace(workspace, "R01")
        except (OSError, ValueError) as exc:
            raise DockerRuntimeError("Workspace is not the exact public R01 input set") from exc
        if report["files"] != ["TASK.md", "data/records.csv", "renv.lock"]:
            raise DockerRuntimeError("R01 workspace file inventory differs from protocol")
        resolved = Path(workspace).resolve(strict=True)
        if resolved.is_relative_to(REPO.resolve()):
            raise DockerRuntimeError("Candidate workspace must be outside the evaluator repository")
        if any(ch in str(resolved) for ch in (",", "\n", "\r")):
            raise DockerRuntimeError("Workspace path cannot be represented safely in a bind mount")
        return {"path": str(resolved), "files": report["files"]}

    def _create_args(self, name: str, workspace: Path, command: list[str]) -> list[str]:
        protocol = pilot.bench.manifest()["protocol"]
        return [
            self.docker,
            "create",
            "--name",
            name,
            "--init",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--cpus",
            str(protocol["cpus"]),
            "--memory",
            f"{protocol['memory_mb']}m",
            "--memory-swap",
            f"{protocol['memory_mb']}m",
            "--pids-limit",
            str(protocol["pids"]),
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "--tmpfs",
            "/work:rw,nosuid,nodev,size=256m,mode=1777",
            "--workdir",
            "/candidate",
            "--env",
            "HOME=/tmp",
            "--env",
            "TZ=UTC",
            "--env",
            "LC_ALL=C.UTF-8",
            "--env",
            "HTTP_PROXY=",
            "--env",
            "HTTPS_PROXY=",
            "--env",
            "ALL_PROXY=",
            "--env",
            "http_proxy=",
            "--env",
            "https_proxy=",
            "--env",
            "all_proxy=",
            "--mount",
            f"type=bind,source={workspace},target=/candidate",
            self.image_id,
            *command,
        ]

    def _inspect_policy(self, container_id: str, workspace: Path) -> dict:
        template = "{{json .HostConfig}}|{{json .Config.User}}|{{json .Mounts}}|{{.State.Status}}"
        raw = (
            self._docker("inspect", "--format", template, container_id)
            .stdout.decode("utf-8", "replace")
            .strip()
        )
        parts = raw.split("|", 3)
        if len(parts) != 4:
            raise DockerRuntimeError("Docker inspect returned an incomplete policy record")
        host = json.loads(parts[0])
        user = json.loads(parts[1])
        mounts = json.loads(parts[2])
        state = parts[3]
        binds = [mount for mount in mounts if mount.get("Type") == "bind"]
        actual_mounts = {(mount.get("Type"), mount.get("Destination")) for mount in mounts}
        expected_mounts = {("bind", "/candidate")}
        if len(binds) != 1 or binds[0].get("Destination") != "/candidate" or not binds[0].get("RW"):
            raise DockerRuntimeError("Container has an unexpected bind mount set")
        if actual_mounts != expected_mounts:
            raise DockerRuntimeError(
                f"Container mount types/targets differ from policy: {sorted(actual_mounts)}"
            )
        if str(binds[0].get("Source", "")).casefold() != str(workspace).casefold():
            raise DockerRuntimeError(
                "Candidate bind source differs from the assigned public workspace"
            )
        cap_drop = {str(item).upper() for item in host.get("CapDrop", [])}
        security_opt = {str(item).lower() for item in host.get("SecurityOpt", [])}
        tmpfs = host.get("Tmpfs", {})
        limits = pilot.bench.manifest()["protocol"]
        if (
            host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or "ALL" not in cap_drop
            or "no-new-privileges:true" not in security_opt
            or host.get("PidsLimit") != limits["pids"]
            or host.get("Memory") != limits["memory_mb"] * 1024 * 1024
            or host.get("MemorySwap") != limits["memory_mb"] * 1024 * 1024
            or host.get("NanoCpus") != int(limits["cpus"] * 1_000_000_000)
            or host.get("Privileged") is not False
            or user != "65534:65534"
            or set(tmpfs) != {"/tmp", "/work"}
            or state != "created"
        ):
            raise DockerRuntimeError("Container security settings differ from the required policy")
        return {
            "network_mode": host["NetworkMode"],
            "read_only_rootfs": host["ReadonlyRootfs"],
            "cap_drop": sorted(cap_drop),
            "no_new_privileges": True,
            "user": user,
            "pids_limit": host["PidsLimit"],
            "memory_bytes": host["Memory"],
            "memory_swap_bytes": host["MemorySwap"],
            "nano_cpus": host["NanoCpus"],
            "privileged": host["Privileged"],
            "bind_mounts": [
                {
                    "source": binds[0]["Source"],
                    "destination": binds[0]["Destination"],
                    "read_write": binds[0]["RW"],
                }
            ],
            "tmpfs_mounts": sorted(tmpfs),
        }

    def _logs(self, container_id: str) -> str:
        output = self._docker("logs", container_id).stdout
        if len(output) > MAX_OUTPUT_BYTES:
            raise DockerRuntimeError("Container probe logs exceeded their byte limit")
        return output.decode("utf-8", "replace")

    def run_boundary_probe(self, workspace: Path, *, trial_id: str = "R01-A") -> dict:
        """Run a fixed no-inference security probe and always remove its container."""
        if trial_id != "R01-A":
            raise DockerRuntimeError("This Docker runtime currently supports only trial R01-A")
        workspace_info = self._validate_workspace(Path(workspace))
        engine = self.verify_engine_and_image()
        name = f"rkmcp-probe-R01-A-{uuid.uuid4().hex[:16]}"
        if not CONTAINER_NAME.fullmatch(name):
            raise DockerRuntimeError("Internal disposable container name is invalid")
        workspace_path = Path(workspace_info["path"])
        create = self._create_args(name, workspace_path, ["/bin/sh", "-c", PROBE_SCRIPT])
        container_id = self._create_container(name, create)
        policy = None
        cleanup_verified = False
        try:
            policy = self._inspect_policy(container_id, workspace_path)
            self._docker("start", container_id)
            wait = _bounded_run([self.docker, "wait", container_id], timeout=10)
            if wait.returncode != 0 or wait.stdout.strip() != b"0":
                logs = self._logs(container_id)
                raise DockerRuntimeError("Docker security probe failed: " + logs[-1000:])
            logs = self._logs(container_id)
            if "docker boundary probe passed" not in logs:
                raise DockerRuntimeError("Docker probe did not emit its success record")
        finally:
            removed = _bounded_run([self.docker, "rm", "--force", container_id], timeout=20)
            if removed.returncode == 0:
                self._assert_removed(container_id)
                cleanup_verified = True
        if not cleanup_verified:
            raise DockerRuntimeError("Disposable Docker container cleanup could not be verified")
        return {
            "schema_version": 1,
            "record_type": "docker_candidate_boundary_probe_not_agent_trial",
            "checked_at": datetime.now(UTC).isoformat(),
            "trial_id": trial_id,
            "condition": "A",
            "model": pilot.MODEL,
            "reasoning_effort": pilot.REASONING_EFFORT,
            "sessions_created": 0,
            "inference_requests": 0,
            "docker": engine,
            "workspace": workspace_info,
            "policy": policy,
            "negative_checks": {
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
            },
            "container_cleanup_verified": cleanup_verified,
            "isolation_verified_for_fixed_probe_only": True,
            "agent_isolation_verified": False,
            "model_connectivity_ready": False,
            "launch_permitted": False,
            "status": "offline_boundary_verified_agent_execution_blocked",
        }

    def run_timeout_probe(self, *, timeout_seconds: float = 1.0) -> dict:
        """Verify forced container cleanup after a process and child exceed a deadline."""
        if not 0 < timeout_seconds <= 5:
            raise DockerRuntimeError("Offline timeout test must be between 0 and 5 seconds")
        name = f"rkmcp-probe-R01-A-{uuid.uuid4().hex[:16]}"
        create = self._create_args(name, Path("/unused"), ["/bin/sh", "-c", SLEEP_SCRIPT])
        # The timeout probe has no bind mount; remove that exact pair from its
        # fixed command rather than accepting a caller-provided command or path.
        mount_index = create.index("--mount")
        del create[mount_index : mount_index + 2]
        container_id = self._create_container(name, create)
        started = datetime.now(UTC)
        timed_out = False
        child_observed = False
        failure = None
        try:
            self._docker("start", container_id)
            for _ in range(40):
                top = _bounded_run([self.docker, "top", container_id], timeout=5)
                if top.returncode != 0:
                    break
                if re.search(rb"\bsleep\b", top.stdout):
                    child_observed = True
                    break
                time.sleep(0.1)
            if not child_observed:
                failure = "Timeout probe did not observe its child process"
            else:
                try:
                    _bounded_run([self.docker, "wait", container_id], timeout=timeout_seconds)
                except DockerCommandTimeout:
                    timed_out = True
                if not timed_out and failure is None:
                    failure = "Timeout fixture exited before its deadline"
        finally:
            _bounded_run([self.docker, "rm", "--force", container_id], timeout=20)
            self._assert_removed(container_id)
        if failure:
            raise DockerRuntimeError(failure)
        if not timed_out:
            raise DockerRuntimeError("Timeout fixture exited before its deadline")
        return {
            "record_type": "docker_process_tree_timeout_probe_not_trial",
            "synthetic": True,
            "trial_id": "R01-A",
            "child_process_created": True,
            "timeout_seconds": timeout_seconds,
            "container_removed": True,
            "started_at": started.isoformat(),
            "checked_at": datetime.now(UTC).isoformat(),
            "model_requests": 0,
            "sessions_created": 0,
            "status": "container_cgroup_force_removed",
        }


def prepared_r01_workspace(destination: Path) -> dict:
    """Export exactly R01's public files to a fresh path outside the repository."""
    destination = Path(destination)
    if destination.exists() or destination.resolve().is_relative_to(REPO.resolve()):
        raise DockerRuntimeError("Choose a new workspace outside the evaluator repository")
    pilot.bench.prepare("R01", destination)
    controller = _load_controller()
    report = controller.validate_public_workspace(destination, "R01")
    return {"path": str(destination.resolve()), "files": report["files"]}
