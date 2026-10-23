"""Docker-backed, no-network candidate boundary probes for the exploratory pilot.

This module can run fixed security probes in the frozen R image. It does not
install Codex, supply credentials, connect a model proxy, or launch an agent.
"""

from __future__ import annotations

import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import shutil
import subprocess
import threading
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
_CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "r01_runtime_executor_contract", Path(__file__).with_name("executor_contract.py")
)
if _CONTRACT_SPEC is None or _CONTRACT_SPEC.loader is None:
    raise RuntimeError("Executor contract is unavailable")
contract = importlib.util.module_from_spec(_CONTRACT_SPEC)
_CONTRACT_SPEC.loader.exec_module(contract)
MAX_OUTPUT_BYTES = 1 << 20
CONTAINER_NAME = re.compile(r"^rkmcp-probe-R01-A-[a-f0-9]{16}$")
IMAGE_ID = re.compile(r"^sha256:[a-f0-9]{64}$")
AGENT_IMAGE_ID = re.compile(r"^sha256:[a-f0-9]{64}$")
CODEX_VERSION = "0.163.0"
FROZEN_R_IMAGE_ID = "sha256:467944b2623c0e7a6f9cbbf24022616911cd834dd2a2200bd39fbe295666eca5"
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
if curl --noproxy '*' --connect-timeout 2 --max-time 3 -fsS \
  https://example.com/ >/dev/null 2>&1; then
  fail arbitrary_internet_reachable
fi
if curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS \
  http://model-proxy:8080/v1/responses >/dev/null 2>&1; then
  fail model_proxy_reachable_in_offline_condition_A
fi
if curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS \
  http://cran-knowledge-mcp:8000/mcp >/dev/null 2>&1; then
  fail direct_gateway_bypass_reachable
fi
printf '%s\n' 'docker boundary probe passed'
"""
SLEEP_SCRIPT = 'sleep 60 & child=$!; echo child_started; wait "$child"'
CODEX_STARTUP_SCRIPT = r"""set -eu
[ "$(id -u)" = 65534 ]
[ -r /candidate/TASK.md ]
[ -r /candidate/renv.lock ]
[ -r /candidate/data/records.csv ]
[ -w /candidate ]
for p in /oracle/R01.R /repo/benchmarks/codex_r/oracle/R01.R \
  /mnt/c/programming_pj/cran-mcp /root/.codex/auth.json \
  /mnt/c/Users/User001/.codex/auth.json /tmp/.codex/auth.json \
  /var/run/docker.sock \
  /other-trial/private-marker /host-test-secret/private-marker; do
  [ ! -e "$p" ] || { echo "unexpected path: $p" >&2; exit 21; }
done
if env | cut -d= -f1 | grep -E \
  '^(OPENAI_API_KEY|CODEX_API_KEY|AZURE_OPENAI_API_KEY)$' >/dev/null; then
  echo 'application credential reached candidate' >&2
  exit 22
fi
if curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS \
  https://example.com/ >/dev/null 2>&1; then
  echo 'unapproved internet reachable' >&2
  exit 23
fi
for url in http://model-proxy:8080/v1/responses http://cran-knowledge-mcp:8000/mcp; do
  if curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS \
    "$url" >/dev/null 2>&1; then
    echo "unexpected network route reachable: $url" >&2
    exit 24
  fi
done
exec /opt/codex/bin/codex exec-server --listen ws://127.0.0.1:3788
"""

EGRESS_PROBE_SCRIPT = r"""set -eu
fail() { echo "egress probe failed: $1" >&2; exit 31; }
[ "$(id -u)" = 65534 ] || fail wrong_uid
[ -r /candidate/TASK.md ] || fail public_workspace_missing
[ ! -e /var/run/docker.sock ] || fail docker_socket_visible
if env | grep -E '^(OPENAI_API_KEY|AZURE_OPENAI_API_KEY)=' >/dev/null; then
  fail application_key_visible
fi
[ -n "$EGRESS_PROXY_URL" ] && [ "$HTTPS_PROXY" = "$EGRESS_PROXY_URL" ] \
  || fail proxy_not_configured
command -v getent >/dev/null 2>&1 || fail dns_probe_unavailable
if getent hosts example.com >/dev/null 2>&1; then
  fail unrestricted_dns_resolved
fi
for url in https://example.com/ https://93.184.216.34/ https://169.254.169.254/; do
  if env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
    curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS "$url" >/dev/null 2>&1; then
    fail "direct_egress_reachable:$url"
  fi
done
for url in https://example.com/ https://93.184.216.34/ https://api.openai.com:444/; do
  if curl --connect-timeout 2 --max-time 3 -fsS "$url" >/dev/null 2>&1; then
    fail "proxy_allowed_unapproved_request:$url"
  fi
done
if env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  timeout 2 bash -c '</dev/tcp/host.docker.internal/2375' 2>/dev/null; then
  fail host_docker_api_reachable
fi
printf '%s\n' 'restricted egress denial checks passed'
"""

FAKE_CONNECT_SINK = r"""import socketserver

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(2049)
        if len(line) > 2048:
            return
        request_line = line.decode("ascii", "replace").strip()
        if request_line.startswith("CONNECT "):
            print(request_line, flush=True)
        total = len(line)
        while line not in (b"\r\n", b"\n", b"") and total < 16384:
            line = self.rfile.readline(2049)
            total += len(line)
        self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

Server(("0.0.0.0", 3128), Handler).serve_forever()
"""


class DockerRuntimeError(RuntimeError):
    """Docker daemon, image, workspace, or policy verification failed."""

    def __init__(self, message, *, code="runtime_policy_rejected", **observed):
        super().__init__(message)
        self.diagnostics = contract.project_runtime_diagnostics({"reason_code": code, **observed})


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


def _bounded_run(
    argv: list[str], *, timeout: int = 20, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise DockerCommandTimeout(
            "Docker command exceeded its local deadline",
            code="command_timeout",
            exception_category="timeout",
            timeout_classification="docker_command_deadline",
        ) from exc
    except OSError as exc:
        raise DockerRuntimeError(
            "Docker command failed",
            code="executable_unavailable"
            if isinstance(exc, FileNotFoundError)
            else "command_os_error",
            exception_category="subprocess",
        ) from exc
    if len(result.stdout) + len(result.stderr) > MAX_OUTPUT_BYTES:
        raise DockerRuntimeError(
            "Docker command output exceeded its byte limit", code="output_limit"
        )
    return result


def _executor_child_environment(
    host_environment: dict[str, str], environment_key: str
) -> dict[str, str]:
    """Forward only non-secret host settings plus the documented scoped executor key."""
    if not isinstance(environment_key, str) or not environment_key:
        raise DockerRuntimeError("Restricted executor environment key is unavailable")
    safe = {
        key: value
        for key, value in host_environment.items()
        if key.upper()
        not in {
            "OPENAI_API_KEY",
            "OPENAI_EXECUTOR_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "CODEX_API_KEY",
        }
        and not re.search(r"(?i)(TOKEN|SECRET|PASSWORD|CREDENTIAL)", key)
    }
    safe["CODEX_API_KEY"] = environment_key
    return safe


class DockerCandidateRuntime:
    """Create and audit one disposable networkless R01-A candidate container."""

    def __init__(self, image_id: str, docker: str | None = None, *, command_runner=None):
        if not IMAGE_ID.fullmatch(image_id):
            raise DockerRuntimeError("Use the immutable sha256 image ID, not a tag")
        self.docker = docker or shutil.which("docker")
        if not self.docker:
            raise DockerRuntimeError("Docker CLI was not found")
        self.image_id = image_id
        self._command_runner = command_runner or _bounded_run
        self._termination_lock = threading.Lock()
        self._verified_removed = set()

    def _run_command(self, argv, *, timeout=20, env=None):
        """Inject only subprocess execution; validation and startup stay production code."""
        try:
            safety = getattr(self, "safety", None)
            if safety is not None:
                timeout = safety.timeout(timeout)
            effects = {
                "create": "executor_create",
                "start": "executor_start",
                "rm": "executor_terminate",
                "run": "image_version_probe",
            }
            operation = effects.get(argv[1])

            def command():
                def invoke():
                    return self._command_runner(argv, timeout=timeout, env=env)

                return safety.io(invoke, cap=timeout) if safety is not None else invoke()

            result = (
                safety.effect(operation, command) if safety is not None and operation else command()
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerCommandTimeout(
                "Docker command exceeded its local deadline",
                code="command_timeout",
                exception_category="timeout",
                timeout_classification="docker_command_deadline",
            ) from exc
        except OSError as exc:
            raise DockerRuntimeError(
                "Docker command failed",
                code="executable_unavailable"
                if isinstance(exc, FileNotFoundError)
                else "command_os_error",
                exception_category="subprocess",
            ) from exc
        if len(result.stdout) + len(result.stderr) > MAX_OUTPUT_BYTES:
            raise DockerRuntimeError("Docker output limit exceeded", code="output_limit")
        return result

    def _docker(
        self,
        *args: str,
        timeout: int = 20,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        result = self._run_command([self.docker, *args], timeout=timeout, env=env)
        if result.returncode != 0:
            raise DockerRuntimeError(
                "Docker daemon rejected a required operation",
                code="cli_nonzero",
                docker_cli_exit_code=result.returncode,
                exception_category="subprocess",
            )
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

    def _create_container(
        self, name: str, argv: list[str], *, env: dict[str, str] | None = None
    ) -> str:
        try:
            result = self._run_command(argv, env=env)
            if result.returncode != 0:
                raise DockerRuntimeError(
                    "Docker failed to create the candidate probe container",
                    code="cli_nonzero",
                    docker_cli_exit_code=result.returncode,
                    exception_category="subprocess",
                )
            container_id = result.stdout.decode("utf-8", "replace").strip()
            if not re.fullmatch(r"[a-f0-9]{64}", container_id):
                raise DockerRuntimeError(
                    "Docker returned an invalid container identifier", code="invalid_container_id"
                )
            return container_id
        except Exception as primary:

            def cleanup():
                self._run_command([self.docker, "rm", "--force", name], timeout=20)
                self._assert_name_absent(name)

            try:
                safety = getattr(self, "safety", None)
                if safety is not None:
                    safety.cleanup("executor_terminate", cleanup, cap=20)
                else:
                    cleanup()
            except Exception:
                primary.cleanup_unverified = True
                if isinstance(getattr(primary, "diagnostics", None), dict):
                    primary.diagnostics["secondary_cleanup_failure"] = "cleanup_unverified"
            raise

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

    def _create_args(
        self,
        name: str,
        workspace: Path,
        command: list[str],
        *,
        network_mode: str = "none",
        proxy_enabled: bool = False,
        proxy_url: str | None = None,
        deny_dns: bool = False,
        environment_key: bool = False,
    ) -> list[str]:
        protocol = pilot.bench.manifest()["protocol"]
        args = [
            self.docker,
            "create",
            "--name",
            name,
            "--init",
            "--network",
            network_mode,
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
            "CODEX_HOME=/tmp",
            "--env",
            "TZ=UTC",
            "--env",
            "LC_ALL=C.UTF-8",
            "--mount",
            f"type=bind,source={workspace},target=/candidate",
        ]
        if deny_dns:
            args.extend(["--dns", "127.0.0.1"])
        if proxy_enabled and (
            not isinstance(proxy_url, str)
            or not re.fullmatch(r"http://(?:\d{1,3}\.){3}\d{1,3}:3128", proxy_url)
        ):
            raise DockerRuntimeError("Restricted proxy URL must use its private Docker IP")
        proxy_url = proxy_url if proxy_enabled else ""
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            args.extend(["--env", f"{name}={proxy_url}"])
        if proxy_enabled:
            args.extend(["--env", f"EGRESS_PROXY_URL={proxy_url}"])
        if environment_key:
            # Docker reads the key from the controller's environment. It never
            # appears in this process's command line or in a generated log.
            args.extend(["--env", "CODEX_API_KEY"])
        args.extend([self.image_id, *command])
        return args

    def _inspect_policy(
        self, container_id: str, workspace: Path, *, expected_network: str = "none"
    ) -> dict:
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
            host.get("NetworkMode") != expected_network
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
        result = self._docker("logs", container_id)
        output = result.stdout + result.stderr
        if len(output) > MAX_OUTPUT_BYTES:
            raise DockerRuntimeError("Container probe logs exceeded their byte limit")
        return output.decode("utf-8", "replace")

    @staticmethod
    def _docker_wait_exit_code(result: subprocess.CompletedProcess) -> int:
        if result.returncode != 0:
            raise DockerRuntimeError(
                "Docker wait command failed",
                code="cli_nonzero",
                docker_cli_exit_code=result.returncode,
                exception_category="subprocess",
            )
        output = result.stdout.strip()
        if not re.fullmatch(rb"[0-9]+", output):
            raise DockerRuntimeError(
                "Docker wait returned no valid container exit status",
                code="invalid_inspection",
                exception_category="subprocess",
            )
        return int(output)

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
            exit_code = self._docker_wait_exit_code(wait)
            if exit_code != 0:
                logs = self._logs(container_id)
                detail = logs[-1000:] or "container emitted no log output"
                raise DockerRuntimeError(
                    f"Docker security probe exited with status {exit_code}: {detail}",
                    code="cli_nonzero",
                    container_exit_code=exit_code,
                    exception_category="subprocess",
                )
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


def _grant_candidate_directory_access(workspace: Path) -> None:
    """Grant UID 65534 access to this one generated workspace directory."""
    if os.name != "posix":
        raise DockerRuntimeError("Candidate workspace ACLs require a POSIX host")
    setfacl = shutil.which("setfacl")
    if not setfacl:
        raise DockerRuntimeError("POSIX setfacl is required for the candidate workspace")
    result = _bounded_run(
        [setfacl, "-m", "u:65534:rwx", "--", str(Path(workspace).resolve(strict=True))],
        timeout=10,
    )
    if result.returncode != 0:
        raise DockerRuntimeError("Could not grant the candidate UID workspace-directory access")


def prepared_r01_workspace(destination: Path, *, candidate_writable: bool = False) -> dict:
    """Export exactly R01's public files to a fresh path outside the repository."""
    destination = Path(destination)
    if destination.exists() or destination.resolve().is_relative_to(REPO.resolve()):
        raise DockerRuntimeError("Choose a new workspace outside the evaluator repository")
    pilot.bench.prepare("R01", destination)
    if candidate_writable:
        _grant_candidate_directory_access(destination)
    controller = _load_controller()
    report = controller.validate_public_workspace(destination, "R01")
    return {"path": str(destination.resolve()), "files": report["files"]}


class CodexCandidateRuntime(DockerCandidateRuntime):
    """Run the pinned Codex self-hosted executor in an offline R01-A boundary.

    This proves actual binary startup and container isolation only. It does not
    register a Managed Agents environment or create a model session.
    """

    def __init__(self, image_id: str, docker: str | None = None, *, command_runner=None):
        if not AGENT_IMAGE_ID.fullmatch(image_id):
            raise DockerRuntimeError("Use the immutable Codex candidate image ID")
        super().__init__(image_id, docker, command_runner=command_runner)

    def verify_candidate_image(self) -> dict:
        inspected = (
            self._docker(
                "image",
                "inspect",
                "--format",
                "{{.Id}}|{{.Config.User}}|{{.Config.WorkingDir}}|"
                "{{json .Config.Entrypoint}}|{{json .RootFS.Layers}}",
                self.image_id,
            )
            .stdout.decode("utf-8", "replace")
            .strip()
        )
        image_id, user, workdir, entrypoint, rootfs = inspected.split("|", 4)
        if image_id != self.image_id or user != "65534:65534" or workdir != "/candidate":
            raise DockerRuntimeError("Codex candidate image identity or defaults are invalid")
        if json.loads(entrypoint) != ["/opt/codex/bin/codex"]:
            raise DockerRuntimeError("Codex candidate entrypoint differs from the pinned binary")
        base_layers = json.loads(
            self._docker(
                "image",
                "inspect",
                "--format",
                "{{json .RootFS.Layers}}",
                FROZEN_R_IMAGE_ID,
            ).stdout
        )
        candidate_layers = json.loads(rootfs)
        if candidate_layers[: len(base_layers)] != base_layers:
            raise DockerRuntimeError("Candidate image does not preserve the frozen R image layers")
        version_name = f"rkmcp-version-R01-A-{uuid.uuid4().hex[:16]}"
        try:
            version = (
                self._docker(
                    "run",
                    "--rm",
                    "--name",
                    version_name,
                    "--network",
                    "none",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
                    "--user",
                    "65534:65534",
                    self.image_id,
                    "--version",
                )
                .stdout.decode("utf-8", "replace")
                .strip()
            )
        except BaseException:

            def remove_version_probe():
                self._run_command([self.docker, "rm", "--force", version_name], timeout=20)
                self._assert_name_absent(version_name)

            safety = getattr(self, "safety", None)
            try:
                if safety:
                    safety.cleanup("executor_terminate", remove_version_probe, cap=20)
                else:
                    remove_version_probe()
            except Exception:
                if safety:
                    safety.evidence_failed = True
            raise
        if version != f"codex-cli {CODEX_VERSION}":
            raise DockerRuntimeError("Codex version differs from the pinned release")
        return {
            "image_id": image_id,
            "base_frozen_r_image_id": FROZEN_R_IMAGE_ID,
            "codex_version": CODEX_VERSION,
            "user": user,
            "workdir": workdir,
            "rootfs_layers_preserve_base": True,
            "version_command": version,
        }

    def run_offline_executor_probe(self, workspace: Path, *, timeout_seconds: float = 5) -> dict:
        """Start the real Codex exec-server, test boundary, then kill and verify cleanup."""
        if not 0 < timeout_seconds <= 15:
            raise DockerRuntimeError("Offline Codex startup probe must be at most 15 seconds")
        workspace_info = self._validate_workspace(Path(workspace))
        image = self.verify_candidate_image()
        name = f"rkmcp-probe-R01-A-{uuid.uuid4().hex[:16]}"
        workspace_path = Path(workspace_info["path"])
        create = self._create_args(name, workspace_path, ["-c", CODEX_STARTUP_SCRIPT])
        image_index = create.index(self.image_id)
        create[image_index:image_index] = ["--interactive", "--entrypoint", "/bin/sh"]
        container_id = self._create_container(name, create)
        policy = None
        process_observed = False
        negative_checks_passed = False
        cleanup_verified = False
        failure = None
        try:
            policy = self._inspect_policy(container_id, workspace_path)
            self._docker("start", container_id)
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                top = _bounded_run([self.docker, "top", container_id], timeout=5)
                if top.returncode != 0:
                    failure = "Codex executor exited before process inspection"
                    log_result = _bounded_run([self.docker, "logs", container_id], timeout=5)
                    details = log_result.stdout + log_result.stderr
                    state_result = self._docker(
                        "inspect",
                        "--format",
                        "{{.State.Status}}|{{.State.ExitCode}}|{{.State.Error}}",
                        container_id,
                    )
                    failure += ": " + details.decode("utf-8", "replace")[-1000:]
                    failure += " [" + state_result.stdout.decode("utf-8", "replace").strip() + "]"
                    break
                processes = top.stdout.decode("utf-8", "replace")
                if "codex" in processes and "exec-server" in processes:
                    process_observed = True
                    break
                state = (
                    self._docker("inspect", "--format", "{{.State.Status}}", container_id)
                    .stdout.decode("ascii", "replace")
                    .strip()
                )
                if state != "running":
                    failure = "Codex executor exited before process inspection"
                    log_result = _bounded_run([self.docker, "logs", container_id], timeout=5)
                    details = log_result.stdout + log_result.stderr
                    failure += ": " + details.decode("utf-8", "replace")[-1000:]
                    break
                time.sleep(0.1)
            if not process_observed and failure is None:
                failure = "Codex exec-server did not remain running inside the candidate container"
            if process_observed:
                logs = self._logs(container_id)
                if "application credential reached candidate" in logs:
                    failure = "Application credential reached candidate container"
                elif any(
                    marker in logs
                    for marker in (
                        "unexpected path:",
                        "unapproved internet reachable",
                        "unexpected network route reachable:",
                    )
                ):
                    failure = "Codex candidate boundary negative check failed"
                else:
                    negative_checks_passed = True
        finally:
            removed = _bounded_run([self.docker, "rm", "--force", container_id], timeout=20)
            if removed.returncode == 0:
                self._assert_removed(container_id)
                cleanup_verified = True
        if not cleanup_verified:
            raise DockerRuntimeError("Codex candidate container cleanup could not be verified")
        if failure:
            raise DockerRuntimeError(failure)
        return {
            "schema_version": 1,
            "record_type": "codex_exec_server_offline_startup_probe_not_trial",
            "checked_at": datetime.now(UTC).isoformat(),
            "trial_id": "R01-A",
            "model": pilot.MODEL,
            "reasoning_effort": pilot.REASONING_EFFORT,
            "sessions_created": 0,
            "inference_requests": 0,
            "image": image,
            "workspace": workspace_info,
            "policy": policy,
            "codex_exec_server_process_observed": process_observed,
            "candidate_secrets_exposed": [],
            "application_key_in_container": False,
            "restricted_environment_key_present": False,
            "negative_checks_passed": negative_checks_passed,
            "network_mode": "none",
            "mcp_tools_exposed": 0,
            "effective_agent_tools_verified": False,
            "container_cleanup_verified": cleanup_verified,
            "agent_isolation_verified": False,
            "model_connectivity_ready": False,
            "launch_permitted": False,
            "status": "real_codex_binary_started_offline_agent_execution_blocked",
        }

    def start_managed_executor(
        self,
        workspace: Path,
        *,
        environment_id: str,
        remote_url: str,
        environment_key: str,
        topology: RestrictedEgressNetwork,
        proxy_ip: str,
    ) -> dict:
        """Start one remote executor with only the restricted environment key.

        The caller must already have created an authorized session and must
        keep the application API key outside Docker. This method does not
        create sessions, submit work, or infer connection success from process
        startup.
        """
        container_id = None
        phase = "validate_topology"
        try:
            if not topology.started or topology.internal_network == "none":
                raise DockerRuntimeError("A verified restricted egress topology is required")
            phase = "validate_environment"
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", environment_id):
                raise DockerRuntimeError("Managed Agents environment identity is invalid")
            if not environment_key or not isinstance(environment_key, str):
                raise DockerRuntimeError("A documented restricted environment key is required")
            phase = "validate_remote_url"
            try:
                contract.validate_executor_remote_url(remote_url)
            except contract.ExecutorURLValidationError as exc:
                raise DockerRuntimeError(
                    "Executor remote URL failed reviewed policy",
                    code="remote_url_rejected",
                    exception_category="validation",
                ) from exc
            phase = "validate_workspace"
            workspace_info = self._validate_workspace(Path(workspace))
            phase = "verify_image"
            image = self.verify_candidate_image()
            phase = "build_container_args"
            proxy_url = f"http://{ipaddress.ip_address(proxy_ip)}:3128"
            name = f"rkmcp-probe-R01-A-{uuid.uuid4().hex[:16]}"
            argv = self._create_args(
                name,
                Path(workspace_info["path"]),
                [
                    "exec-server",
                    "--remote",
                    remote_url,
                    "--environment-id",
                    environment_id,
                ],
                network_mode=topology.internal_network,
                proxy_enabled=True,
                proxy_url=proxy_url,
                deny_dns=True,
                environment_key=True,
            )
            safe_env = _executor_child_environment(os.environ, environment_key)
            phase = "create_container"
            container_id = self._create_container(name, argv, env=safe_env)
            phase = "inspect_policy"
            self._inspect_policy(
                container_id,
                Path(workspace_info["path"]),
                expected_network=topology.internal_network,
            )
            phase = "inspect_network"
            networks = json.loads(
                self._docker(
                    "inspect", "--format", "{{json .NetworkSettings.Networks}}", container_id
                ).stdout
            )
            phase = "inspect_environment"
            env = json.loads(
                self._docker("inspect", "--format", "{{json .Config.Env}}", container_id).stdout
            )
            if (
                set(networks) != {topology.internal_network}
                or f"HTTPS_PROXY={proxy_url}" not in env
                or f"CODEX_API_KEY={environment_key}" not in env
                or any(
                    value.split("=", 1)[0]
                    in {"OPENAI_API_KEY", "OPENAI_EXECUTOR_API_KEY", "AZURE_OPENAI_API_KEY"}
                    for value in env
                )
            ):
                raise DockerRuntimeError("Executor credential or network policy did not verify")
            phase = "start_container"
            self._docker("start", container_id)
            phase = "verify_process"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                top = self._docker("top", container_id, timeout=5)
                if "exec-server" in top.stdout.decode("utf-8", "replace"):
                    return {
                        "record_type": "managed_executor_process_started_not_connection_verified",
                        "container_id": container_id,
                        "candidate_image_id": image["image_id"],
                        "environment_id": environment_id,
                        "remote_url_redacted": True,
                        "application_key_absent": True,
                        "restricted_environment_key_in_candidate": True,
                        "environment_key_is_readable_to_agent_code": True,
                        "network_mode": topology.internal_network,
                        "egress_proxy_ip": proxy_ip,
                        "mcp_tools_requested": 0,
                        "executor_registered": False,
                        "status": "process_running_live_connection_unverified",
                    }
                state = (
                    self._docker(
                        "inspect", "--format", "{{.State.Status}}|{{.State.ExitCode}}", container_id
                    )
                    .stdout.decode("ascii", "replace")
                    .strip()
                )
                state_parts = state.split("|", 1)
                state_name = state_parts[0]
                exit_code = None
                if len(state_parts) == 2 and re.fullmatch(r"-?\d{1,10}", state_parts[1]):
                    exit_code = int(state_parts[1])
                if state_name != "running":
                    raise DockerRuntimeError(
                        "Codex executor exited before process verification",
                        code="executor_exited",
                        container_startup_state=state_name,
                        container_exit_code=exit_code,
                    )
                time.sleep(0.1)
            raise DockerRuntimeError(
                "Codex executor process did not remain running", code="executor_not_running"
            )
        except BaseException as exc:
            if (
                isinstance(exc, DockerRuntimeError)
                or getattr(exc, "diagnostics", {}).get("category") == "deadline_expired"
            ):
                failure = exc
                if (
                    phase.startswith("inspect_")
                    and failure.diagnostics.get("reason_code") == "runtime_policy_rejected"
                ):
                    failure.diagnostics["reason_code"] = "invalid_inspection"
            else:
                failure = DockerRuntimeError(
                    "Executor startup failed",
                    code="invalid_inspection"
                    if phase.startswith("inspect_")
                    else "runtime_policy_rejected",
                    exception_category="validation" if isinstance(exc, ValueError) else "runtime",
                )
            failure.diagnostics["sub_operation"] = phase
            if container_id:
                try:
                    safety = getattr(self, "safety", None)
                    if safety is not None:
                        removed = safety.cleanup(
                            "executor_terminate",
                            lambda: self.stop_managed_executor(container_id),
                            cap=20,
                        )
                    else:
                        removed = self.stop_managed_executor(container_id)
                except Exception:
                    removed = False
                if not removed:
                    failure.container_id = container_id
                    failure.cleanup_unverified = True
                    failure.diagnostics["secondary_cleanup_failure"] = "cleanup_unverified"
            if failure is exc:
                raise
            raise failure from exc

    def stop_managed_executor(self, container_id: str) -> bool:
        safety = getattr(self, "safety", None)
        wait_seconds = safety.timeout(20) if safety else 20
        if not self._termination_lock.acquire(timeout=wait_seconds):
            return False
        try:
            if container_id in self._verified_removed:
                return True
            removed = self._stop_managed_executor(container_id)
            if removed:
                self._verified_removed.add(container_id)
            return removed
        finally:
            self._termination_lock.release()

    def _stop_managed_executor(self, container_id: str) -> bool:
        """Force-stop every process in the executor cgroup and verify removal."""
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise DockerRuntimeError("Executor container identity is invalid")
        removed = self._run_command([self.docker, "rm", "--force", container_id], timeout=20)
        if removed.returncode == 0:
            self._assert_removed(container_id)
            return True
        listed = self._run_command(
            [self.docker, "ps", "--all", "--filter", f"id={container_id}", "--format", "{{.ID}}"],
            timeout=5,
        )
        return listed.returncode == 0 and not listed.stdout.strip()


class RestrictedEgressNetwork:
    """A two-network Docker topology with a fixed-host CONNECT-only gateway.

    The candidate joins only an internal isolated-gateway network. The gateway
    also joins a separate outbound bridge and permits TLS tunnels only to the
    documented Agents API and executor relay destinations.
    """

    NAME = re.compile(r"^rkmcp-(?:candidate|egress)-R01-A-[a-f0-9]{12}$")
    PYTHON_BASE_ID = "sha256:cce12316475d7d56d605f76e1d811d0dc4e7227f2d4afd29951521264f504ff8"

    def __init__(self, docker: str | None = None):
        self.docker = docker or shutil.which("docker")
        if not self.docker:
            raise DockerRuntimeError("Docker CLI was not found")
        suffix = uuid.uuid4().hex[:12]
        self.internal_network = f"rkmcp-candidate-R01-A-{suffix}"
        self.egress_network = f"rkmcp-egress-R01-A-{suffix}"
        self.proxy_container = f"rkmcp-egress-R01-A-{suffix}"
        self.proxy_image = f"rkmcp-egress-proxy:{suffix}"
        self.proxy_image_id: str | None = None
        self.started = False
        self._created_networks: list[str] = []
        self._created_container = False

    def _run(self, *args: str, timeout: int = 20) -> subprocess.CompletedProcess:
        safety = getattr(self, "safety", None)
        result = _bounded_run(
            [self.docker, *args], timeout=safety.timeout(timeout) if safety else timeout
        )
        if result.returncode != 0:
            raise DockerRuntimeError("Docker rejected the restricted egress topology")
        return result

    def start(self) -> dict:
        """Build and start the reviewed proxy; fail closed on any policy mismatch."""
        if self.started:
            raise DockerRuntimeError("Restricted egress topology is already active")
        try:
            return self._start_topology()
        except BaseException:
            self.cleanup()
            raise

    def _start_topology(self) -> dict:
        base = (
            self._run("image", "inspect", "--format", "{{.Id}}", self.PYTHON_BASE_ID)
            .stdout.decode("ascii", "replace")
            .strip()
        )
        if base != self.PYTHON_BASE_ID:
            raise DockerRuntimeError("Pinned egress proxy Python image is unavailable")
        build = _bounded_run(
            [
                self.docker,
                "build",
                "--pull=false",
                "--tag",
                self.proxy_image,
                "--file",
                str(ROOT / "runtime" / "egress.Dockerfile"),
                str(REPO),
            ],
            timeout=self.safety.timeout(120) if getattr(self, "safety", None) else 120,
        )
        if build.returncode != 0:
            raise DockerRuntimeError("Could not build the restricted egress proxy image")
        self.proxy_image_id = (
            self._run("image", "inspect", "--format", "{{.Id}}", self.proxy_image)
            .stdout.decode("ascii", "replace")
            .strip()
        )
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", self.proxy_image_id):
            raise DockerRuntimeError("Egress proxy image did not resolve to an immutable digest")
        self._create_network(self.egress_network, internal=False)
        self._create_network(self.internal_network, internal=True)
        proxy_id = (
            self._run(
                "create",
                "--name",
                self.proxy_container,
                "--network",
                self.egress_network,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--cpus",
                "0.5",
                "--memory",
                "128m",
                "--memory-swap",
                "128m",
                "--pids-limit",
                "16",
                "--user",
                "65534:65534",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
                self.proxy_image_id,
            )
            .stdout.decode("ascii", "replace")
            .strip()
        )
        if not re.fullmatch(r"[a-f0-9]{64}", proxy_id):
            raise DockerRuntimeError("Docker returned an invalid egress proxy container ID")
        self._created_container = True
        self._run(
            "network",
            "connect",
            "--alias",
            "rkmcp-egress",
            self.internal_network,
            proxy_id,
        )
        self._run("start", proxy_id)
        self._wait_proxy()
        self._verify_proxy_topology()
        proxy_ip = (
            self._run(
                "inspect",
                "--format",
                '{{(index .NetworkSettings.Networks "' + self.internal_network + '").IPAddress}}',
                self.proxy_container,
            )
            .stdout.decode("ascii", "replace")
            .strip()
        )
        try:
            parsed_ip = ipaddress.ip_address(proxy_ip)
        except ValueError as exc:
            raise DockerRuntimeError("Restricted proxy has no valid internal IPv4 address") from exc
        if not parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_link_local:
            raise DockerRuntimeError(
                "Restricted proxy address is outside its private Docker subnet"
            )
        self.started = True
        return {
            "internal_network": self.internal_network,
            "outbound_network": self.egress_network,
            "proxy_container_id": proxy_id,
            "proxy_image_id": self.proxy_image_id,
            "proxy_internal_ip": proxy_ip,
            "allowed_destinations": [
                "api.openai.com:443",
                "codex-cloud-environments.chatgpt.com:443",
            ],
            "tls_interception": False,
            "remote_url_rewritten": False,
            "network_isolation": "docker_internal_isolated_gateway",
            "status": "restricted_gateway_started_not_upstream_connection_verified",
        }

    def _create_network(self, name: str, *, internal: bool) -> None:
        if not self.NAME.fullmatch(name):
            raise DockerRuntimeError("Generated Docker network name is invalid")
        args = [self.docker, "network", "create", "--driver", "bridge"]
        if internal:
            args.extend(
                [
                    "--internal",
                    "--opt",
                    "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                ]
            )
        args.append(name)
        result = _bounded_run(args)
        if result.returncode != 0:
            raise DockerRuntimeError("Docker could not create the isolated egress networks")
        self._created_networks.append(name)
        inspect = (
            self._run(
                "network",
                "inspect",
                "--format",
                "{{.Internal}}|{{json .Options}}",
                name,
            )
            .stdout.decode("utf-8", "replace")
            .strip()
        )
        internal_flag, _, raw_options = inspect.partition("|")
        options = json.loads(raw_options)
        if internal:
            if (
                internal_flag != "true"
                or options.get("com.docker.network.bridge.gateway_mode_ipv4") != "isolated"
            ):
                raise DockerRuntimeError("Candidate network is not an isolated internal bridge")
        elif internal_flag != "false":
            raise DockerRuntimeError("Egress proxy network must have outbound bridge access")

    def _wait_proxy(self) -> None:
        deadline = time.monotonic() + 5
        last_error = None
        while time.monotonic() < deadline:
            try:
                self._run(
                    "exec",
                    self.proxy_container,
                    "python",
                    "-c",
                    "import socket; s=socket.create_connection(('127.0.0.1',3128),1); s.close()",
                    timeout=3,
                )
                return
            except DockerRuntimeError as exc:
                last_error = exc
                time.sleep(0.1)
        raise DockerRuntimeError("Restricted egress proxy did not become ready") from last_error

    def _verify_proxy_topology(self) -> None:
        raw = (
            self._run(
                "inspect",
                "--format",
                "{{json .HostConfig}}|{{json .Mounts}}|{{json .NetworkSettings.Networks}}"
                "|{{.Config.Image}}",
                self.proxy_container,
            )
            .stdout.decode("utf-8", "replace")
            .strip()
        )
        parts = raw.split("|", 3)
        if len(parts) != 4:
            raise DockerRuntimeError("Docker returned incomplete egress proxy policy evidence")
        host, mounts, networks = json.loads(parts[0]), json.loads(parts[1]), json.loads(parts[2])
        if (
            set(networks) != {self.egress_network, self.internal_network}
            or mounts
            or host.get("Privileged") is not False
            or host.get("ReadonlyRootfs") is not True
            or {str(cap).upper() for cap in host.get("CapDrop", [])} != {"ALL"}
            or "no-new-privileges:true"
            not in {str(option).lower() for option in host.get("SecurityOpt", [])}
            or host.get("PidsLimit") != 16
            or host.get("Memory") != 128 * 1024 * 1024
        ):
            raise DockerRuntimeError("Egress proxy container settings violate the fixed policy")

    def cleanup(self) -> bool:
        """Remove the sidecar and both networks; false means the lease must remain held."""
        success = True
        if self._created_container:
            stopped = _bounded_run(
                [self.docker, "rm", "--force", self.proxy_container],
                timeout=self.safety.timeout(20) if getattr(self, "safety", None) else 20,
            )
            success = stopped.returncode == 0 and success
            if stopped.returncode == 0:
                self._created_container = False
        for name in reversed(self._created_networks):
            removed = _bounded_run(
                [self.docker, "network", "rm", name],
                timeout=self.safety.timeout(20) if getattr(self, "safety", None) else 20,
            )
            success = removed.returncode == 0 and success
            if removed.returncode == 0:
                self._created_networks.remove(name)
        if self._created_container or self._created_networks:
            success = False
        self.started = False
        return success


def run_restricted_egress_probe(image_id: str, workspace: Path, docker: str | None = None) -> dict:
    """Exercise the real Docker topology without contacting an upstream service."""
    runtime = CodexCandidateRuntime(image_id, docker)
    workspace_info = runtime._validate_workspace(Path(workspace))
    image = runtime.verify_candidate_image()
    topology = RestrictedEgressNetwork(runtime.docker)
    candidate_name = f"rkmcp-probe-R01-A-{uuid.uuid4().hex[:16]}"
    if not CONTAINER_NAME.fullmatch(candidate_name):
        raise DockerRuntimeError("Generated candidate probe name is invalid")
    candidate_id = None
    candidate_removed = False
    gateway_removed = False
    container_policy = None
    proxy_policy_evidence = None
    try:
        gateway = topology.start()
        proxy_url = f"http://{gateway['proxy_internal_ip']}:3128"
        argv = runtime._create_args(
            candidate_name,
            Path(workspace_info["path"]),
            ["-c", EGRESS_PROBE_SCRIPT],
            network_mode=topology.internal_network,
            proxy_enabled=True,
            proxy_url=proxy_url,
            deny_dns=True,
        )
        image_index = argv.index(runtime.image_id)
        argv[image_index:image_index] = ["--entrypoint", "/bin/sh"]
        candidate_id = runtime._create_container(candidate_name, argv)
        container_policy = runtime._inspect_policy(
            candidate_id,
            Path(workspace_info["path"]),
            expected_network=topology.internal_network,
        )
        attached = json.loads(
            runtime._docker(
                "inspect", "--format", "{{json .NetworkSettings.Networks}}", candidate_id
            ).stdout
        )
        if set(attached) != {topology.internal_network}:
            raise DockerRuntimeError("Candidate joined an unexpected Docker network")
        env = json.loads(
            runtime._docker("inspect", "--format", "{{json .Config.Env}}", candidate_id).stdout
        )
        if (
            not all(
                f"{name}={proxy_url}" in env for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
            )
            or f"EGRESS_PROXY_URL={proxy_url}" not in env
            or "CODEX_API_KEY" in env
            or any(value.startswith("OPENAI_API_KEY=") for value in env)
        ):
            raise DockerRuntimeError(
                "Candidate proxy or credential environment differs from policy"
            )
        dns = json.loads(
            runtime._docker("inspect", "--format", "{{json .HostConfig.Dns}}", candidate_id).stdout
        )
        if dns != ["127.0.0.1"]:
            raise DockerRuntimeError("Candidate DNS is not fail-closed")
        runtime._docker("start", candidate_id)
        wait = _bounded_run([runtime.docker, "wait", candidate_id], timeout=25)
        if wait.returncode != 0 or wait.stdout.strip() != b"0":
            log_result = _bounded_run([runtime.docker, "logs", candidate_id], timeout=5)
            logs = (log_result.stdout + log_result.stderr).decode("utf-8", "replace")
            state = _bounded_run(
                [
                    runtime.docker,
                    "inspect",
                    "--format",
                    "{{.State.Status}}|{{.State.ExitCode}}|{{.State.Error}}",
                    candidate_id,
                ],
                timeout=5,
            )
            raise DockerRuntimeError(
                "Restricted egress probe failed inside the candidate: "
                + state.stdout.decode("utf-8", "replace").strip()
                + " logs="
                + logs[-1000:]
            )
        logs = runtime._logs(candidate_id)
        if "restricted egress denial checks passed" not in logs:
            raise DockerRuntimeError("Candidate egress denial checks did not pass")
        proxy_logs = _bounded_run([runtime.docker, "logs", topology.proxy_container], timeout=5)
        if proxy_logs.returncode != 0:
            raise DockerRuntimeError("Could not inspect restricted egress proxy test evidence")
        proxy_text = (proxy_logs.stdout + proxy_logs.stderr).decode("utf-8", "replace")
        expected_denials = ("host_denied", "ip_literal_denied", "port_denied")
        if not all(reason in proxy_text for reason in expected_denials):
            raise DockerRuntimeError("Proxy did not record every unapproved destination denial")
        proxy_policy_evidence = {
            "host_denied_observed": True,
            "ip_literal_denied_observed": True,
            "non_https_port_denied_observed": True,
            "tls_interception": False,
            "upstream_http_requests": 0,
        }
    finally:
        if candidate_id is not None:
            removed = _bounded_run([runtime.docker, "rm", "--force", candidate_id], timeout=20)
            if removed.returncode == 0:
                runtime._assert_removed(candidate_id)
                candidate_removed = True
        gateway_removed = topology.cleanup()
    if not candidate_removed or not gateway_removed:
        raise DockerRuntimeError("Candidate or restricted egress resources were not fully cleaned")
    return {
        "schema_version": 1,
        "record_type": "offline_restricted_egress_test_not_real_trial",
        "checked_at": datetime.now(UTC).isoformat(),
        "trial_id": "R01-A",
        "condition": "A",
        "image": image,
        "workspace": workspace_info,
        "network_policy": {
            "candidate_network": "Docker internal isolated gateway",
            "candidate_dns": "127.0.0.1; external resolution denied",
            "proxy": "CONNECT only; exact official host allowlist; TCP TLS passthrough",
            "allowed_hosts": ["api.openai.com", "codex-cloud-environments.chatgpt.com"],
            "remote_url_rewritten": False,
            "application_key_in_candidate": False,
            "candidate_environment_key_present": False,
        },
        "candidate_policy": container_policy,
        "proxy_policy_evidence": proxy_policy_evidence,
        "negative_checks": {
            "direct_public_ip_denied": True,
            "cloud_metadata_ip_denied": True,
            "arbitrary_domain_denied_by_proxy": True,
            "IP_literal_proxy_target_denied": True,
            "non_443_proxy_target_denied": True,
            "unrestricted_dns_denied": True,
            "host_docker_service_denied": True,
            "docker_socket_unavailable": True,
            "candidate_has_only_internal_network": True,
        },
        "candidate_container_removed": candidate_removed,
        "egress_proxy_and_networks_removed": gateway_removed,
        "sessions_created": 0,
        "inference_requests": 0,
        "paid_calls_made": 0,
        "launch_permitted": False,
        "upstream_connectivity_verified": False,
        "status": "offline_policy_checks_passed_upstream_not_contacted",
    }


def run_codex_proxy_transport_probe(
    image_id: str, workspace: Path, docker: str | None = None
) -> dict:
    """Prove Codex exec-server uses HTTPS_PROXY without any upstream route."""
    runtime = CodexCandidateRuntime(image_id, docker)
    workspace_info = runtime._validate_workspace(Path(workspace))
    image = runtime.verify_candidate_image()
    suffix = uuid.uuid4().hex[:12]
    network = f"rkmcp-candidate-R01-A-{suffix}"
    server_name = f"rkmcp-proxy-sink-R01-A-{suffix}"
    candidate_name = f"rkmcp-probe-R01-A-{uuid.uuid4().hex[:16]}"
    if not RestrictedEgressNetwork.NAME.fullmatch(network) or not CONTAINER_NAME.fullmatch(
        candidate_name
    ):
        raise DockerRuntimeError("Generated proxy probe resources have invalid names")
    created_network = False
    server_id = None
    candidate_id = None
    server_removed = candidate_removed = False
    try:
        network_result = _bounded_run(
            [
                runtime.docker,
                "network",
                "create",
                "--driver",
                "bridge",
                "--internal",
                "--opt",
                "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                network,
            ]
        )
        if network_result.returncode != 0:
            raise DockerRuntimeError("Could not create the isolated proxy-transport test network")
        created_network = True
        network_info = (
            runtime._docker(
                "network", "inspect", "--format", "{{.Internal}}|{{json .Options}}", network
            )
            .stdout.decode("utf-8", "replace")
            .strip()
        )
        internal, _, options_json = network_info.partition("|")
        if (
            internal != "true"
            or json.loads(options_json).get("com.docker.network.bridge.gateway_mode_ipv4")
            != "isolated"
        ):
            raise DockerRuntimeError("Proxy test network is not isolated from host and internet")
        base_id = (
            runtime._docker(
                "image", "inspect", "--format", "{{.Id}}", RestrictedEgressNetwork.PYTHON_BASE_ID
            )
            .stdout.decode("ascii", "replace")
            .strip()
        )
        if base_id != RestrictedEgressNetwork.PYTHON_BASE_ID:
            raise DockerRuntimeError("Pinned local Python image for proxy sink is unavailable")
        server_id = (
            runtime._docker(
                "create",
                "--name",
                server_name,
                "--network",
                network,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--memory",
                "64m",
                "--pids-limit",
                "16",
                "--user",
                "65534:65534",
                "--entrypoint",
                "python",
                RestrictedEgressNetwork.PYTHON_BASE_ID,
                "-u",
                "-c",
                FAKE_CONNECT_SINK,
            )
            .stdout.decode("ascii", "replace")
            .strip()
        )
        if not re.fullmatch(r"[a-f0-9]{64}", server_id):
            raise DockerRuntimeError("Docker returned an invalid local proxy sink ID")
        runtime._docker("start", server_id)
        deadline = time.monotonic() + 5
        server_ip = ""
        while time.monotonic() < deadline:
            server_ip = (
                runtime._docker(
                    "inspect",
                    "--format",
                    '{{(index .NetworkSettings.Networks "' + network + '").IPAddress}}',
                    server_id,
                )
                .stdout.decode("ascii", "replace")
                .strip()
            )
            if server_ip:
                break
            time.sleep(0.1)
        if not ipaddress.ip_address(server_ip).is_private:
            raise DockerRuntimeError("Local proxy sink lacks a private address")
        sink_ready = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            ready = _bounded_run(
                [
                    runtime.docker,
                    "exec",
                    server_id,
                    "python",
                    "-c",
                    "import socket; s=socket.create_connection(('127.0.0.1',3128),1); s.close()",
                ],
                timeout=3,
            )
            if ready.returncode == 0:
                sink_ready = True
                break
            time.sleep(0.1)
        if not sink_ready:
            raise DockerRuntimeError("Local fake proxy sink did not become ready")
        proxy_url = f"http://{server_ip}:3128"
        argv = runtime._create_args(
            candidate_name,
            Path(workspace_info["path"]),
            [
                "exec-server",
                "--remote",
                "https://api.openai.com/v1/agents/api",
                "--environment-id",
                "synthetic_env_for_proxy_probe",
            ],
            network_mode=network,
            proxy_enabled=True,
            proxy_url=proxy_url,
            deny_dns=True,
            environment_key=True,
        )
        safe_env = _executor_child_environment(os.environ, "synthetic_environment_key_never_logged")
        candidate_id = runtime._create_container(candidate_name, argv, env=safe_env)
        runtime._docker("start", candidate_id)
        deadline = time.monotonic() + 10
        sink_logs = ""
        while time.monotonic() < deadline:
            sink_logs = runtime._logs(server_id)
            if "CONNECT api.openai.com:443" in sink_logs:
                break
            state = (
                runtime._docker("inspect", "--format", "{{.State.Status}}", candidate_id)
                .stdout.decode("ascii", "replace")
                .strip()
            )
            if state != "running":
                break
            time.sleep(0.1)
        if "CONNECT api.openai.com:443" not in sink_logs:
            candidate_logs = (
                _bounded_run([runtime.docker, "logs", candidate_id], timeout=5)
                if candidate_id
                else None
            )
            candidate_state = (
                _bounded_run(
                    [
                        runtime.docker,
                        "inspect",
                        "--format",
                        "{{.State.Status}}|{{.State.ExitCode}}",
                        candidate_id,
                    ],
                    timeout=5,
                )
                if candidate_id
                else None
            )
            candidate_state_text = (
                candidate_state.stdout.decode("utf-8", "replace").strip()
                if candidate_state
                else "none"
            )
            candidate_log_text = (
                (candidate_logs.stdout + candidate_logs.stderr).decode("utf-8", "replace")[-500:]
                if candidate_logs
                else ""
            )
            raise DockerRuntimeError(
                "Codex exec-server did not use HTTPS_PROXY for the fake registration endpoint; "
                f"sink={sink_logs[-500:]}; "
                f"candidate_state={candidate_state_text}; "
                f"candidate_logs={candidate_log_text}"
            )
    finally:
        if candidate_id is not None:
            removed = _bounded_run([runtime.docker, "rm", "--force", candidate_id], timeout=20)
            if removed.returncode == 0:
                runtime._assert_removed(candidate_id)
                candidate_removed = True
        if server_id is not None:
            removed = _bounded_run([runtime.docker, "rm", "--force", server_id], timeout=20)
            server_removed = removed.returncode == 0
            if server_removed:
                runtime._assert_removed(server_id)
        network_removed = not created_network
        if created_network:
            removed = _bounded_run([runtime.docker, "network", "rm", network], timeout=20)
            network_removed = removed.returncode == 0
    if not candidate_removed or not server_removed or not network_removed:
        raise DockerRuntimeError("Proxy transport probe resources were not fully cleaned")
    return {
        "record_type": "offline_codex_proxy_transport_test_not_real_registration",
        "checked_at": datetime.now(UTC).isoformat(),
        "candidate_image": image,
        "workspace": workspace_info,
        "codex_https_proxy_connect_observed": True,
        "observed_target": "api.openai.com:443",
        "test_proxy_response": "synthetic_http_403",
        "upstream_hosts_contacted": [],
        "application_key_absent": True,
        "synthetic_environment_key_used": True,
        "tls_handshake_performed": False,
        "websocket_registration_verified": False,
        "candidate_container_removed": candidate_removed,
        "local_proxy_container_removed": server_removed,
        "isolated_network_removed": network_removed,
        "sessions_created": 0,
        "inference_requests": 0,
        "paid_calls_made": 0,
        "launch_permitted": False,
        "status": "https_proxy_transport_confirmed_wss_and_registration_unverified",
    }
