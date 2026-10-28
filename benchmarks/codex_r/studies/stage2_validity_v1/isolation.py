"""Stage 2.5 information-channel isolation and network policy verification.

Connects the Stage 2 arm capability specifications (`protocol.py`) with the
repository's CONNECT-only egress allow-list gateway (`exploratory/egress_proxy.py`)
to validate:

1. MCP network reachability in each arm (unreachable in Arm A; reachable in Arms B/C).
2. Permitted model endpoint access (`api.openai.com:443` and
   `codex-cloud-environments.chatgpt.com:443`) across all arms.
3. Unauthorized outbound traffic rejection (CRAN, Bioconductor, GitHub, arbitrary
   domains, IP literals, non-443 ports).
4. Detection of gateway/observer bypass or non-internal Docker bridge networks.
5. Behavior when the MCP server is unavailable in Arms B/C.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from benchmarks.codex_r.exploratory import egress_proxy
from benchmarks.codex_r.studies.stage2_validity_v1 import protocol

MCP_INTERNAL_AUTHORITY = "r-knowledge-mcp:8000"
MCP_INTERNAL_HOST = "r-knowledge-mcp"
MCP_INTERNAL_PORT = 8000
PROXY_INTERNAL_AUTHORITY = f"egress-proxy:{egress_proxy.PORT}"
REPO_ROOT = Path(__file__).resolve().parents[4]

FORBIDDEN_EXTERNAL_HOSTS: tuple[str, ...] = (
    "cloud.r-project.org",
    "cran.r-project.org",
    "bioconductor.org",
    "api.github.com",
    "github.com",
)

FORBIDDEN_EXTERNAL_AUTHORITIES: tuple[str, ...] = (
    "cloud.r-project.org:443",
    "cran.r-project.org:443",
    "bioconductor.org:443",
    "api.github.com:443",
    "github.com:443",
    "example.com:443",
    "93.184.216.34:443",
    "api.openai.com:444",
)


@dataclass(frozen=True)
class ArmNetworkPolicy:
    """Target container network topology and channel rules for one experimental arm."""

    arm: str
    policy_id: str
    docker_network_internal: bool
    egress_proxy_required: bool
    egress_proxy_authority: str
    mcp_container_attached: bool
    mcp_authority: str | None
    allowed_connect_hosts: tuple[str, ...]
    blocked_external_hosts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_connect_hosts"] = list(self.allowed_connect_hosts)
        data["blocked_external_hosts"] = list(self.blocked_external_hosts)
        return data


@dataclass(frozen=True)
class ConnectionAttemptResult:
    """Outcome of a single outbound or internal connection attempt from a trial container."""

    arm: str
    channel: str  # "mcp_internal" | "egress_proxy_connect" | "direct_unproxied"
    method: str
    authority: str
    permitted: bool
    reason_code: str
    violation_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def policy_for_arm(arm: str) -> ArmNetworkPolicy:
    """Return the required Stage 2.5 container network policy for ``arm``."""
    spec = protocol.ARMS[arm]
    return ArmNetworkPolicy(
        arm=spec.id,
        policy_id=f"stage25-internal-net-arm-{spec.id.lower()}-v1",
        docker_network_internal=True,
        egress_proxy_required=True,
        egress_proxy_authority=PROXY_INTERNAL_AUTHORITY,
        mcp_container_attached=spec.mcp_available,
        mcp_authority=MCP_INTERNAL_AUTHORITY if spec.mcp_available else None,
        allowed_connect_hosts=tuple(sorted(egress_proxy.ALLOWED_HOSTS)),
        blocked_external_hosts=FORBIDDEN_EXTERNAL_HOSTS,
    )


def evaluate_connection_attempt(
    arm: str,
    *,
    channel: str,
    method: str,
    authority: str,
    docker_network_internal: bool = True,
    mcp_server_healthy: bool = True,
) -> ConnectionAttemptResult:
    """Evaluate a connection attempt under the Stage 2.5 arm isolation rules.

    Parameters
    ----------
    arm:
        Experimental arm (``"A"``, ``"B"``, or ``"C"``).
    channel:
        ``"mcp_internal"`` for internal trial-network HTTP requests to the MCP
        container, ``"egress_proxy_connect"`` for HTTPS requests routed through
        the CONNECT egress gateway, or ``"direct_unproxied"`` for a direct
        socket connection bypassing the proxy.
    method:
        HTTP/tunnel method (e.g. ``"POST"`` for MCP streamable-http or ``"CONNECT"``
        for proxy tunnels).
    authority:
        ``host:port`` target string.
    docker_network_internal:
        Whether the Docker bridge network was created with ``--internal``.
    mcp_server_healthy:
        Whether the MCP container is running and accepting connections on port 8000.
    """
    policy = policy_for_arm(arm)

    if channel == "mcp_internal":
        if authority != MCP_INTERNAL_AUTHORITY:
            return ConnectionAttemptResult(
                arm=arm,
                channel=channel,
                method=method,
                authority=authority,
                permitted=False,
                reason_code="unknown_internal_service",
                violation_code=None,
            )
        if not policy.mcp_container_attached:
            # In Arm A, the MCP container is not started on the trial network.
            # If it were reachable, that would be a critical control-arm leak.
            return ConnectionAttemptResult(
                arm=arm,
                channel=channel,
                method=method,
                authority=authority,
                permitted=False,
                reason_code="mcp_not_attached_in_arm_a",
                violation_code=None,
            )
        if not mcp_server_healthy:
            return ConnectionAttemptResult(
                arm=arm,
                channel=channel,
                method=method,
                authority=authority,
                permitted=False,
                reason_code="mcp_server_unavailable",
                violation_code="treatment_arm_mcp_unavailable",
            )
        return ConnectionAttemptResult(
            arm=arm,
            channel=channel,
            method=method,
            authority=authority,
            permitted=True,
            reason_code="mcp_internal_allowed",
            violation_code=None,
        )

    if channel == "direct_unproxied":
        # On a properly configured `--internal` Docker network, direct outbound
        # connections to external hosts fail with network unreachable. If the
        # network was NOT `--internal`, direct traffic bypasses the proxy!
        if docker_network_internal:
            return ConnectionAttemptResult(
                arm=arm,
                channel=channel,
                method=method,
                authority=authority,
                permitted=False,
                reason_code="blocked_by_internal_docker_network",
                violation_code=None,
            )
        return ConnectionAttemptResult(
            arm=arm,
            channel=channel,
            method=method,
            authority=authority,
            permitted=True,
            reason_code="unrestricted_bridge_bypass",
            violation_code="egress_not_restricted",
        )

    if channel == "egress_proxy_connect":
        if method != "CONNECT":
            return ConnectionAttemptResult(
                arm=arm,
                channel=channel,
                method=method,
                authority=authority,
                permitted=False,
                reason_code="connect_only",
                violation_code=None,
            )
        try:
            host, _port = egress_proxy.parse_connect_authority(authority)
        except egress_proxy.ProxyError as exc:
            reason = str(exc)
            violation = (
                "forbidden_host_contacted"
                if any(
                    authority.lower().startswith(f"{forbidden}:")
                    for forbidden in policy.blocked_external_hosts
                )
                else None
            )
            return ConnectionAttemptResult(
                arm=arm,
                channel=channel,
                method=method,
                authority=authority,
                permitted=False,
                reason_code=reason,
                violation_code=violation,
            )
        return ConnectionAttemptResult(
            arm=arm,
            channel=channel,
            method=method,
            authority=f"{host}:443",
            permitted=True,
            reason_code="allowed_model_endpoint",
            violation_code=None,
        )

    raise ValueError(f"Unsupported channel: {channel!r}")


def run_synthetic_isolation_probes() -> dict[str, Any]:
    """Run deterministic offline isolation probes across Arms A, B, and C.

    Verifies the policy engine and `egress_proxy.parse_connect_authority`
    against:
    - MCP reachability in Arm A (denied) vs Arms B/C (permitted when healthy,
      flagged when MCP server is down).
    - Permitted model endpoints (`api.openai.com:443`,
      `codex-cloud-environments.chatgpt.com:443`) in all arms.
    - Denied external hosts (`cran.r-project.org:443`, `bioconductor.org:443`,
      `github.com:443`, IP literals, non-443 ports, non-CONNECT verbs).
    - Direct unproxied bypass on an `--internal` network (blocked) vs plain
      bridge network (leaked and flagged as `egress_not_restricted`).
    """
    arm_reports: dict[str, Any] = {}
    all_passed = True

    for arm in sorted(protocol.ARMS):
        policy = policy_for_arm(arm)
        attempts: list[ConnectionAttemptResult] = []

        # 1. MCP internal reachability (healthy server)
        mcp_attempt = evaluate_connection_attempt(
            arm,
            channel="mcp_internal",
            method="POST",
            authority=MCP_INTERNAL_AUTHORITY,
            docker_network_internal=True,
            mcp_server_healthy=True,
        )
        attempts.append(mcp_attempt)

        # 2. Allowed model endpoints via CONNECT proxy
        for host in sorted(egress_proxy.ALLOWED_HOSTS):
            attempts.append(
                evaluate_connection_attempt(
                    arm,
                    channel="egress_proxy_connect",
                    method="CONNECT",
                    authority=f"{host}:443",
                    docker_network_internal=True,
                )
            )

        # 3. Forbidden external authorities via CONNECT proxy
        for auth in FORBIDDEN_EXTERNAL_AUTHORITIES:
            attempts.append(
                evaluate_connection_attempt(
                    arm,
                    channel="egress_proxy_connect",
                    method="CONNECT",
                    authority=auth,
                    docker_network_internal=True,
                )
            )

        # 4. Non-CONNECT HTTP method to proxy
        attempts.append(
            evaluate_connection_attempt(
                arm,
                channel="egress_proxy_connect",
                method="GET",
                authority="api.openai.com:443",
                docker_network_internal=True,
            )
        )

        # 5. Direct unproxied socket attempt on `--internal` Docker network
        attempts.append(
            evaluate_connection_attempt(
                arm,
                channel="direct_unproxied",
                method="TCP",
                authority="cran.r-project.org:443",
                docker_network_internal=True,
            )
        )

        expected_mcp = arm in {"B", "C"}
        mcp_ok = mcp_attempt.permitted is expected_mcp
        model_ok = all(a.permitted for a in attempts if a.reason_code == "allowed_model_endpoint")
        denials_ok = all(
            not a.permitted
            for a in attempts
            if a.channel in {"egress_proxy_connect", "direct_unproxied"}
            and a.reason_code != "allowed_model_endpoint"
        )
        arm_ok = mcp_ok and model_ok and denials_ok
        all_passed = all_passed and arm_ok

        arm_reports[arm] = {
            "policy": policy.to_dict(),
            "mcp_reachable": mcp_attempt.permitted,
            "model_endpoints_permitted": model_ok,
            "unauthorized_egress_rejected": denials_ok,
            "invariants_satisfied": arm_ok,
            "attempts": [a.to_dict() for a in attempts],
        }

    # Fault-injection probes: MCP server down in Arm B & unproxied bridge network leak
    mcp_down_b = evaluate_connection_attempt(
        "B",
        channel="mcp_internal",
        method="POST",
        authority=MCP_INTERNAL_AUTHORITY,
        docker_network_internal=True,
        mcp_server_healthy=False,
    )
    bridge_bypass_a = evaluate_connection_attempt(
        "A",
        channel="direct_unproxied",
        method="TCP",
        authority="cran.r-project.org:443",
        docker_network_internal=False,
    )

    fault_probes_ok = (
        not mcp_down_b.permitted
        and mcp_down_b.violation_code == "treatment_arm_mcp_unavailable"
        and bridge_bypass_a.permitted
        and bridge_bypass_a.violation_code == "egress_not_restricted"
    )

    return {
        "synthetic_probe_suite": True,
        "live_docker_isolation_established": False,
        "all_policy_invariants_satisfied": all_passed and fault_probes_ok,
        "arms": arm_reports,
        "fault_injection_probes": {
            "mcp_unavailable_in_arm_b": mcp_down_b.to_dict(),
            "plain_bridge_bypass_in_arm_a": bridge_bypass_a.to_dict(),
        },
    }


def inspect_legacy_runner_isolation(runner_path: Path | None = None) -> dict[str, Any]:
    """Static audit of ``benchmarks/codex_r/run_simple.py`` network isolation.

    Returns verifiable code-level evidence showing whether ``run_simple.py``
    enforces an ``--internal`` Docker network and starts ``egress_proxy.py``.
    """
    path = runner_path or (REPO_ROOT / "benchmarks" / "codex_r" / "run_simple.py")
    text = path.read_text(encoding="utf-8")
    creates_plain_bridge = 'docker("network", "create", network)' in text
    uses_internal_flag = '"--internal"' in text or "'--internal'" in text
    wires_egress_proxy = "egress_proxy" in text
    arm_a_skips_mcp = 'if mode == "with-mcp":\n                start_mcp(' in text

    return {
        "runner_file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "arm_a_omits_mcp_container": arm_a_skips_mcp,
        "creates_plain_docker_bridge": creates_plain_bridge,
        "uses_docker_internal_network_flag": uses_internal_flag,
        "wires_egress_proxy_container": wires_egress_proxy,
        "live_egress_isolation_enforced": bool(
            arm_a_skips_mcp
            and uses_internal_flag
            and wires_egress_proxy
            and not creates_plain_bridge
        ),
        "blocker_summary": (
            "run_simple.py omits the MCP container in without-mcp mode, preventing Arm A "
            "from reaching R-Knowledge-MCP over the container network, but creates a plain "
            "Docker bridge network (`docker('network', 'create', network)`) without `--internal` "
            "or `egress_proxy.py`. Therefore, candidate R processes in any arm can reach live "
            "CRAN/Bioconductor/GitHub unless `--internal` + `egress_proxy` is wired into the "
            "live container runtime."
        ),
    }
