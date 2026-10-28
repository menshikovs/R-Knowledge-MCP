"""Stage 2.6 live Docker topology for one A/B/C trial (no model credentials, no paid calls).

Per trial, a fresh set of Docker resources is created, probed, used and removed::

    internal net  (docker --internal: no gateway, no route, no external DNS)
      |- candidate / canary containers  (no other network, non-root, read-only, caps dropped)
      |- egress-gateway   --- upstream net --- model-upstream (local mock model endpoint)
      '- r-knowledge-mcp  (Arms B/C only)  --- mcp-egress net (the server's own fetches only)

* The candidate can only open connections to peers on the internal network. The only peers are
  the gateway (CONNECT allow-list) and, in Arms B/C, the MCP server. In Arm A no MCP container
  exists, and a canary proves that name, address and gateway paths to MCP all fail.
* The model endpoint is reachable only through the gateway, which tunnels the single allow-listed
  authority ``api.openai.com:443`` to a fixed upstream chosen by the policy, never by the client.
* Fail closed: an invalid gateway policy, a missing readiness signal, a structural mismatch or any
  canary probe that reaches something forbidden stops the trial before the workload runs.
* Everything is labelled so interrupted runs can be swept (`sweep_run`) and cleanup is verified.

Docker's ``--internal`` flag alone is not trusted: structure is inspected and behaviour is probed
from inside a container on the same network with the same hardening as the workload.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from benchmarks.codex_r.studies.stage2_validity_v1 import protocol

ROOT = Path(__file__).resolve().parents[4]
ASSETS = Path(__file__).with_name("live_assets")
PYTHON_IMAGE = "python:3.11-slim"
MCP_IMAGE = "cran-knowledge-mcp:shiny-quarto"
LABEL_RUN = "rkmcp.stage26.run"
LABEL_TOPOLOGY = "rkmcp.stage26.topology"

GATEWAY_ALIAS, GATEWAY_PORT = "egress-gateway", 3128
MODEL_ALIAS, MODEL_PORT = "model-upstream", 8443
MODEL_AUTHORITY = "api.openai.com:443"
MCP_ALIAS, MCP_PORT = "r-knowledge-mcp", 8000
# The only workload and model upstream this topology can run. Both are local mocks; there is no
# real-model executor or credential path (see calibration_pipeline.live_execution_blockers).
WORKLOAD_SCRIPT = "/opt/stage26/mock_agent.py"
MODEL_UPSTREAM_SCRIPT = "/opt/stage26/mock_model_server.py"
# Names that must never reach any container started by this module.
HOST_SECRET_NAMES = frozenset(
    {
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "RKMCP_GITHUB_TOKEN",
        "MOCK_MODEL_TOKEN",
    }
)
FAULTS = frozenset(
    {
        "gateway_policy_invalid",
        "candidate_on_upstream_network",
        "mcp_in_arm_a",
        "model_usage_partial",
    }
)


class DockerUnavailable(RuntimeError):
    """Docker is missing or not reachable; live evidence cannot be produced."""


class DockerError(RuntimeError):
    """A docker command failed (message carries a truncated stderr, never credentials)."""


class IsolationEnforcementError(RuntimeError):
    """Policy enforcement could not be established; the trial must not run (fail closed)."""


def docker(
    *args: str,
    check: bool = True,
    timeout: float = 60,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:
        raise DockerUnavailable("docker CLI not found") from exc
    if check and proc.returncode:
        raise DockerError(f"docker {args[0]} failed: {proc.stderr.strip()[:1500]}")
    return proc


def docker_status(images: tuple[str, ...] = (PYTHON_IMAGE, MCP_IMAGE)) -> dict[str, Any]:
    """Whether a Docker engine answers and the required local images exist (never pulls)."""
    try:
        proc = docker("version", "--format", "{{.Server.Version}}", check=False, timeout=30)
    except (DockerUnavailable, subprocess.TimeoutExpired) as exc:
        return {"available": False, "ready": False, "reason": str(exc)[:200]}
    if proc.returncode or not proc.stdout.strip():
        return {"available": False, "ready": False, "reason": proc.stderr.strip()[:300]}
    missing = [i for i in images if docker("image", "inspect", i, check=False).returncode]
    return {
        "available": True,
        "ready": not missing,
        "server_version": proc.stdout.strip(),
        "missing_images": missing,
        "reason": None if not missing else f"local image(s) missing: {', '.join(missing)}",
    }


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in HOST_SECRET_NAMES}
    env.update(extra or {})
    return env


def canary_probes(arm_id: str) -> list[dict[str, str]]:
    """Connection attempts that must behave identically (except MCP) in every arm."""
    mcp = "allowed" if protocol.ARMS[arm_id].mcp_available else "denied"
    rows: list[tuple[str, str, str, str]] = [
        ("gateway_reachable", "tcp", f"{GATEWAY_ALIAS}:{GATEWAY_PORT}", "allowed"),
        ("model_via_gateway", "proxy_connect", MODEL_AUTHORITY, "allowed"),
        ("mcp_direct", "tcp", f"{MCP_ALIAS}:{MCP_PORT}", mcp),
        ("direct_public_ip_443", "tcp", "1.1.1.1:443", "denied"),
        ("direct_public_ip_80", "tcp", "93.184.216.34:80", "denied"),
        ("direct_metadata_ip", "tcp", "169.254.169.254:80", "denied"),
        ("direct_docker_host_bridge", "tcp", "172.17.0.1:2375", "denied"),
        ("direct_host_alias", "tcp", "host.docker.internal:80", "denied"),
        ("direct_model_upstream", "tcp", f"{MODEL_ALIAS}:{MODEL_PORT}", "denied"),
        ("dns_example_com", "dns", "example.com", "denied"),
        ("dns_model_host", "dns", "api.openai.com", "denied"),
        ("dns_cran", "dns", "cran.r-project.org", "denied"),
        ("proxy_example_com", "proxy_connect", "example.com:443", "denied"),
        ("proxy_cran", "proxy_connect", "cran.r-project.org:443", "denied"),
        ("proxy_bioconductor", "proxy_connect", "bioconductor.org:443", "denied"),
        ("proxy_github", "proxy_connect", "github.com:443", "denied"),
        ("proxy_ip_literal", "proxy_connect", "1.1.1.1:443", "denied"),
        ("proxy_model_wrong_port", "proxy_connect", "api.openai.com:444", "denied"),
        ("proxy_model_upstream_name", "proxy_connect", f"{MODEL_ALIAS}:{MODEL_PORT}", "denied"),
        ("proxy_mcp_via_gateway", "proxy_connect", f"{MCP_ALIAS}:{MCP_PORT}", "denied"),
        ("proxy_metadata", "proxy_connect", "169.254.169.254:80", "denied"),
        ("proxy_localhost", "proxy_connect", "localhost:80", "denied"),
        (
            "proxy_userinfo_smuggling",
            "proxy_connect",
            "api.openai.com:443@example.com:443",
            "denied",
        ),
        ("proxy_plain_get", "proxy_get", "http://example.com/", "denied"),
    ]
    return [{"id": a, "kind": b, "target": c, "expect": d} for a, b, c, d in rows]


class TrialTopology:
    """Create, verify, use and tear down the Docker resources of exactly one trial attempt."""

    def __init__(
        self,
        arm: str,
        *,
        trial_id: str = "trial",
        run_label: str = "stage26",
        python_image: str = PYTHON_IMAGE,
        mcp_image: str = MCP_IMAGE,
        executor_token: str | None = None,
        fault: str | None = None,
    ) -> None:
        if arm not in protocol.ARMS:
            raise ValueError(f"unknown arm {arm!r}")
        if fault is not None and fault not in FAULTS:
            raise ValueError(f"unknown fault injection {fault!r}")
        self.arm_id = arm
        self.arm = protocol.ARMS[arm]
        self.trial_id = trial_id
        self.run_label = run_label
        self.python_image, self.mcp_image = python_image, mcp_image
        self.token = executor_token or secrets.token_hex(16)
        self.fault = fault
        self.topology_id = hashlib.sha256(
            f"{trial_id}|{secrets.token_hex(6)}".encode()
        ).hexdigest()[:10]
        prefix = f"rkmcp-s26-{self.topology_id}"
        self.net_int, self.net_up, self.net_mcp = f"{prefix}-int", f"{prefix}-up", f"{prefix}-mcp"
        self.c_model, self.c_gateway, self.c_mcp = (
            f"{prefix}-model",
            f"{prefix}-gw",
            f"{prefix}-mcp",
        )
        self.containers: list[str] = []
        self.networks: list[str] = []
        self.has_mcp = self.arm.mcp_available or fault == "mcp_in_arm_a"
        self._spec_dir = Path(tempfile.mkdtemp(prefix="rkmcp-s26-spec-"))

    # ------------------------------------------------------------------ helpers
    def _labels(self) -> list[str]:
        return [
            "--label",
            f"{LABEL_RUN}={self.run_label}",
            "--label",
            f"{LABEL_TOPOLOGY}={self.topology_id}",
        ]

    @staticmethod
    def _hardening(memory: str, pids: int) -> list[str]:
        return [
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--memory={memory}",
            f"--pids-limit={pids}",
            "--user=65534:65534",
            "--tmpfs",
            "/tmp:rw,nosuid,size=64m,mode=1777",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "HOME=/tmp",
        ]

    def _assets_mount(self) -> list[str]:
        return ["--mount", f"type=bind,source={ASSETS},target=/opt/stage26,readonly"]

    def _networks_of(self, container: str) -> set[str]:
        raw = docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", container).stdout
        return set(json.loads(raw))

    def _wait_ready(self, container: str, port: int) -> None:
        probe = (
            "import socket,time\n"
            "for _ in range(150):\n"
            " try:\n"
            f"  socket.create_connection(('127.0.0.1',{port}),.2).close(); break\n"
            " except OSError: time.sleep(.1)\n"
            "else: raise SystemExit(3)\n"
        )
        try:
            docker("exec", container, "python", "-c", probe, timeout=40)
        except (DockerError, subprocess.TimeoutExpired) as exc:
            logs = docker("logs", "--tail", "20", container, check=False)
            raise IsolationEnforcementError(
                f"{container} did not become ready: {(logs.stderr + logs.stdout)[-800:]}"
            ) from exc

    def _require_running(self, container: str, what: str) -> None:
        deadline = time.monotonic() + 1.5
        while True:
            state = json.loads(docker("inspect", "--format", "{{json .State}}", container).stdout)
            if not state.get("Running"):
                logs = docker("logs", "--tail", "20", container, check=False)
                raise IsolationEnforcementError(
                    f"{what} exited (code {state.get('ExitCode')}) instead of starting: "
                    f"{(logs.stderr + logs.stdout)[-600:]}"
                )
            if time.monotonic() >= deadline:
                return
            time.sleep(0.1)

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        labels = self._labels()
        for net, internal in ((self.net_int, True), (self.net_up, False)):
            args = ["network", "create", *(["--internal"] if internal else []), *labels, net]
            docker(*args)
            self.networks.append(net)
        if self.has_mcp:
            docker("network", "create", *labels, self.net_mcp)
            self.networks.append(self.net_mcp)

        token_env = _clean_env({"MOCK_MODEL_TOKEN": self.token})
        docker(
            "run",
            "--detach",
            "--pull=never",
            "--name",
            self.c_model,
            "--network",
            self.net_up,
            "--network-alias",
            MODEL_ALIAS,
            *self._hardening("128m", 64),
            "--env",
            "MOCK_MODEL_TOKEN",
            "--env",
            f"MOCK_MODEL_USAGE={'partial' if self.fault == 'model_usage_partial' else 'full'}",
            *self._assets_mount(),
            *labels,
            self.python_image,
            "python",
            MODEL_UPSTREAM_SCRIPT,
            env=token_env,
        )
        self.containers.append(self.c_model)

        policy = {"allow": {MODEL_AUTHORITY: f"{MODEL_ALIAS}:{MODEL_PORT}"}}
        policy_text = "{not json" if self.fault == "gateway_policy_invalid" else json.dumps(policy)
        docker(
            "run",
            "--detach",
            "--pull=never",
            "--name",
            self.c_gateway,
            "--network",
            self.net_int,
            "--network-alias",
            GATEWAY_ALIAS,
            *self._hardening("128m", 128),
            "--env",
            f"RKMCP_GATEWAY_POLICY={policy_text}",
            *self._assets_mount(),
            *labels,
            self.python_image,
            "python",
            "/opt/stage26/arm_gateway.py",
            env=_clean_env(),
        )
        self.containers.append(self.c_gateway)
        self._require_running(self.c_gateway, "egress gateway")
        docker("network", "connect", self.net_up, self.c_gateway)
        self._wait_ready(self.c_gateway, GATEWAY_PORT)
        self._wait_ready(self.c_model, MODEL_PORT)

        if self.has_mcp:
            self._start_mcp(labels)

    def _start_mcp(self, labels: list[str]) -> None:
        docker(
            "run",
            "--detach",
            "--pull=never",
            "--name",
            self.c_mcp,
            "--network",
            self.net_int,
            "--network-alias",
            MCP_ALIAS,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=512m",
            "--pids-limit=128",
            "--tmpfs",
            "/tmp:rw,nosuid,size=128m,mode=1777",
            "--mount",
            f"type=bind,source={ROOT / 'src'},target=/evaluated,readonly",
            "--env",
            "PYTHONPATH=/evaluated",
            "--env",
            "MCP_TOOLSET=consolidated",
            "--env",
            f"RKMCP_BENCH_RUN_ID={self.run_label}",
            "--env",
            f"RKMCP_BENCH_TRIAL_ID={self.topology_id}",
            *labels,
            "--entrypoint",
            "python",
            self.mcp_image,
            "-m",
            "cran_knowledge_mcp.server",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--allowed-host",
            f"{MCP_ALIAS}:{MCP_PORT}",
            env=_clean_env(),
        )
        self.containers.append(self.c_mcp)
        # The server's own documentation fetches use a separate, non-candidate network.
        docker("network", "connect", self.net_mcp, self.c_mcp)
        self._wait_ready(self.c_mcp, MCP_PORT)

    # -------------------------------------------------------------- verification
    def verify_enforcement(self) -> dict[str, Any]:
        """Structural evidence (docker inspect). Returns ``ok`` False with ``problems``."""
        problems: list[str] = []
        net = json.loads(docker("network", "inspect", self.net_int).stdout)[0]
        members = sorted(c["Name"] for c in (net.get("Containers") or {}).values())
        expected = sorted([self.c_gateway] + ([self.c_mcp] if self.arm.mcp_available else []))
        if net.get("Internal") is not True:
            problems.append("candidate network is not Docker-internal")
        if members != expected:
            problems.append(f"internal network members {members} != expected {expected}")
        nets = {
            "gateway": sorted(self._networks_of(self.c_gateway)),
            "model": sorted(self._networks_of(self.c_model)),
        }
        if nets["gateway"] != sorted([self.net_int, self.net_up]):
            problems.append(f"gateway networks unexpected: {nets['gateway']}")
        if nets["model"] != [self.net_up]:
            problems.append(f"model networks unexpected: {nets['model']}")
        if self.has_mcp:
            nets["mcp"] = sorted(self._networks_of(self.c_mcp))
            if nets["mcp"] != sorted([self.net_int, self.net_mcp]):
                problems.append(f"mcp networks unexpected: {nets['mcp']}")
        gateway_env = json.loads(
            docker("inspect", "--format", "{{json .Config.Env}}", self.c_gateway).stdout
        )
        leaked = sorted(
            e.split("=", 1)[0] for e in gateway_env if e.split("=", 1)[0] in HOST_SECRET_NAMES
        )
        if leaked:
            problems.append(f"credential variables reached the gateway: {leaked}")
        return {
            "ok": not problems,
            "problems": problems,
            "internal_flag": net.get("Internal"),
            "internal_network_members": members,
            "container_networks": nets,
        }

    def _run_agent(
        self,
        role: str,
        spec: dict[str, Any],
        *,
        workspace: Path | None,
        with_token: bool,
        timeout: float,
    ) -> dict[str, Any]:
        name = f"rkmcp-s26-{self.topology_id}-{role}"
        spec_dir = self._spec_dir / role
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        networks = [self.net_int] + (
            [self.net_up] if self.fault == "candidate_on_upstream_network" else []
        )
        proxy = f"http://{GATEWAY_ALIAS}:{GATEWAY_PORT}"
        args = [
            "create",
            "--pull=never",
            "--name",
            name,
            "--network",
            networks[0],
            *self._hardening("512m", 128),
            "--env",
            f"HTTPS_PROXY={proxy}",
            "--env",
            f"HTTP_PROXY={proxy}",
            "--mount",
            f"type=bind,source={spec_dir},target=/agent,readonly",
            *self._assets_mount(),
            *self._labels(),
        ]
        if with_token:
            args += ["--env", "CODEX_API_KEY"]
        if workspace is not None:
            args += ["--mount", f"type=bind,source={workspace},target=/candidate"]
            args += ["--workdir", "/candidate"]
        args += [self.python_image, "python", WORKLOAD_SCRIPT]
        docker(*args, env=_clean_env({"CODEX_API_KEY": self.token} if with_token else None))
        self.containers.append(name)
        for extra in networks[1:]:
            docker("network", "connect", extra, name)
        info = json.loads(docker("inspect", name).stdout)[0]
        host_cfg = info["HostConfig"]
        inspect = {
            "networks": sorted(info["NetworkSettings"]["Networks"]),
            "privileged": host_cfg.get("Privileged"),
            "cap_drop": host_cfg.get("CapDrop"),
            "read_only_rootfs": host_cfg.get("ReadonlyRootfs"),
            "user": info["Config"].get("User"),
            "env_names": sorted(e.split("=", 1)[0] for e in info["Config"].get("Env") or []),
            "network_mode": host_cfg.get("NetworkMode"),
        }
        timed_out = False
        try:
            proc = docker("start", "-a", name, check=False, timeout=timeout)
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            timed_out = True
            docker("kill", name, check=False)
            logs = docker("logs", name, check=False)
            stdout, stderr = logs.stdout, logs.stderr
        state = json.loads(docker("inspect", "--format", "{{json .State}}", name).stdout)
        report = None
        for line in stdout.splitlines():
            if line.startswith("STAGE26_REPORT "):
                report = json.loads(line[len("STAGE26_REPORT ") :])
        return {
            "role": role,
            "report": report,
            "exit_code": state.get("ExitCode"),
            "timed_out": timed_out,
            "inspect": inspect,
            "stderr_tail": stderr[-500:],
        }

    def run_canary(self, timeout: float = 120) -> dict[str, Any]:
        """Behavioural isolation probes from inside the candidate network (no credentials)."""
        result = self._run_agent(
            "canary",
            {"mode": "canary", "probes": canary_probes(self.arm_id)},
            workspace=None,
            with_token=False,
            timeout=timeout,
        )
        probes = (result["report"] or {}).get("probes", [])
        expected = {p["id"] for p in canary_probes(self.arm_id)}
        complete = {p["id"] for p in probes} == expected
        breaches = [
            p["id"] for p in probes if p["expect"] == "denied" and p["outcome"] == "allowed"
        ]
        failures = [
            p["id"] for p in probes if p["expect"] == "allowed" and p["outcome"] != "allowed"
        ]
        errors = [p["id"] for p in probes if p["outcome"] == "error"]
        result.update(
            probes=probes,
            complete=complete,
            breaches=breaches,
            availability_failures=failures,
            probe_errors=errors,
            ok=complete
            and not breaches
            and not failures
            and not errors
            and not result["timed_out"],
        )
        return result

    def run_workload(self, spec: dict[str, Any], workspace: Path, timeout: float) -> dict[str, Any]:
        return self._run_agent(
            "workload",
            {"mode": "workload", **spec},
            workspace=workspace,
            with_token=True,
            timeout=timeout,
        )

    # ------------------------------------------------------------------ evidence
    @staticmethod
    def _json_lines(text: str) -> list[dict[str, Any]]:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        return rows

    def collect_logs(self) -> dict[str, Any]:
        gw = docker("logs", self.c_gateway, check=False)
        model = docker("logs", self.c_model, check=False)
        gateway_events = self._json_lines(gw.stderr + gw.stdout)
        model_events = self._json_lines(model.stderr + model.stdout)
        mcp_events: list[dict[str, Any]] = []
        raw_mcp = ""
        if self.has_mcp:
            mcp = docker("logs", self.c_mcp, check=False)
            raw_mcp = mcp.stderr + mcp.stdout
            marker = "RKMCP_BENCH_TELEMETRY "
            for line in raw_mcp.splitlines():
                if marker in line:
                    try:
                        mcp_events.append(json.loads(line.split(marker, 1)[1]))
                    except ValueError:
                        continue
        return {
            "gateway_events": gateway_events,
            "model_events": model_events,
            "mcp_telemetry": mcp_events,
            "raw_text": gw.stderr + gw.stdout + model.stderr + model.stdout + raw_mcp,
        }

    def container_ip(self, container: str, network: str) -> str:
        raw = docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", container).stdout
        return json.loads(raw)[network]["IPAddress"]

    # ------------------------------------------------------------------- cleanup
    def teardown(self) -> dict[str, list[str]]:
        """Remove every resource of this topology and return anything that remains."""
        for name in reversed(self.containers):
            docker("rm", "--force", name, check=False, timeout=60)
        for name in reversed(self.networks):
            if docker("network", "rm", name, check=False).returncode:
                time.sleep(0.5)
                docker("network", "rm", name, check=False)
        self.containers, self.networks = [], []
        import shutil

        shutil.rmtree(self._spec_dir, ignore_errors=True)
        return list_resources(topology=self.topology_id)

    def __enter__(self) -> TrialTopology:
        try:
            self.start()
        except BaseException:
            self.teardown()
            raise
        return self

    def __exit__(self, *_exc: object) -> None:
        self.teardown()


def list_resources(*, topology: str | None = None, run: str | None = None) -> dict[str, list[str]]:
    flt = f"label={LABEL_TOPOLOGY}={topology}" if topology else f"label={LABEL_RUN}={run}"
    containers = docker(
        "ps", "--all", "--filter", flt, "--format", "{{.Names}}", check=False
    ).stdout.split()
    networks = docker(
        "network", "ls", "--filter", flt, "--format", "{{.Name}}", check=False
    ).stdout.split()
    return {"containers": sorted(containers), "networks": sorted(networks)}


def sweep_run(run_label: str) -> dict[str, list[str]]:
    """Remove leftovers of an interrupted run (same run label); returns what was removed."""
    found = list_resources(run=run_label)
    for name in found["containers"]:
        docker("rm", "--force", name, check=False)
    for name in found["networks"]:
        docker("network", "rm", name, check=False)
    return found
