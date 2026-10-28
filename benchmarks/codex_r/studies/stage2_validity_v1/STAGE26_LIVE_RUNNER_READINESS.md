# Stage 2.6: Live Runner Integration and Pilot Readiness Report

**Date**: October 28, 2026  
**Repository**: `https://github.com/menshikovs/R-Knowledge-MCP`  
**Base Branch**: `2.0`  
**Working Branch**: `feature/stage2-benchmark-validity`  
**Baseline Commit**: `08ef9e9e2711e1174ed6796b3e3e60bf0ad7ca58`  
**Final Readiness Outcome**: `PILOT INFRASTRUCTURE READY`

---

## 1. Executive Summary

Stage 2.6 establishes end-to-end live runner infrastructure capable of executing randomized three-arm ($A/B/C$) benchmark trials inside isolated Docker networks with deterministic network policy enforcement, zero host credential exposure, frozen scorer validation, automated resource cleanup, and telemetry projection.

All engineering requirements have been implemented and verified via automated test suites:
- **31 offline unit and policy tests** pass in sandbox mode ($1.7\text{ s}$).
- **9 live Docker end-to-end integration tests** pass against Docker Engine ($186.2\text{ s}$), verifying real container creation, network isolation, CONNECT forward-proxy allowlisting, cross-arm container denial, fault injection fail-closed behavior, and crash orphan sweeping.
- **Live smoke CLI execution** verifies 3 randomized trials (`D01` across Arms A, B, C), producing 100% valid schema-compliant trial records, clean network teardown, zero leftover containers or networks, and authentic scoring via `knowledge_pilot_v21`.
- **Legacy benchmark preservation**: `benchmarks/codex_r/run_simple.py` and existing historical datasets remain 100% unmodified.
- **Frozen evidence**: All 279 frozen benchmark files match their digests with 0 differences.

---

## 2. Architecture & Network Topology

### Topology Diagram

```
+----------------------------------------------------------------------------------------------------+
| HOST SYSTEM (Secure Environment, Python Runner)                                                    |
|                                                                                                    |
|  [TrialLedger / LiveTrialExecutor]                                                                 |
|         |                                                                                          |
|         v                                                                                          |
|  +-----------------------------------------------------+   +------------------------------------+  |
|  | DOCKER INTERNAL NETWORK: s26-int-<run_label>-<trial>|   | DOCKER UPSTREAM NETWORK:           |  |
|  | (--internal=true, no default gateway, no internet)  |   | s26-up-<run_label>-<trial>         |  |
|  |                                                     |   |                                    |  |
|  |  +-----------------------------------------------+  |   |  +------------------------------+  |  |
|  |  | Candidate Container (Agent)                   |  |   |  | Mock Model Server            |  |  |
|  |  | - Image: alpine:3.20                          |  |   |  | - Port: 8443                 |  |  |
|  |  | - User: 65534:65534 (nobody)                  |  |   |  | - Validates synthetic token  |  |  |
|  |  | - CapDrop: ALL                                |  |   |  | - Returns mock completions   |  |  |
|  |  | - ReadOnlyRootfs: true                        |  |   |  +--------------^---------------+  |  |
|  |  | - HTTPS_PROXY: http://egress-gateway:3128     |  |   |                 |                  |  |
|  |  | - HTTP_PROXY:  http://egress-gateway:3128     |  |   +-----------------|------------------+  |
|  |  +---------+-------------------+-----------------+  |                     |                     |
|  |            | (Arm B & C only)  | (All Arms)         |                     |                     |
|  |            |                   v                    |                     |                     |
|  |            |        +----------------------------+  |                     |                     |
|  |            |        | Egress Gateway (Gateway)   |  |                     |                     |
|  |            |        | - CONNECT-only proxy       +--+---------------------+                     |
|  |            |        | - Port 3128                |  |  (dual-homed to internal + upstream)      |
|  |            |        | - Whitelist table mapping: |  |                                           |
|  |            |        |   api.openai.com:443 ->    |  |                                           |
|  |            |        |   model-upstream:8443      |  |                                           |
|  |            |        +----------------------------+  |                                           |
|  |            v                                        |                                           |
|  |  +-----------------------------------------------+  |                                           |
|  |  | FastMCP Container                             |  |                                           |
|  |  | - Only present in Arms B and C                |  |                                           |
|  |  | - Port: 8000 (HTTP / SSE)                     |  |                                           |
|  |  | - In Arm A: CONTAINER NOT CREATED ON NETWORK  |  |                                           |
|  |  +-----------------------------------------------+  |                                           |
|  +-----------------------------------------------------+                                           |
+----------------------------------------------------------------------------------------------------+
```

### Isolation Guarantees

1. **Docker Internal Bridge (`--internal`)**:
   Docker creates a bridge network with no default gateway and no iptables MASQUERADE / NAT forwarding. Raw IP packets cannot leave the candidate container to reach public subnets (verified via direct canary probes to `1.1.1.1:443` and `8.8.8.8:53`).
2. **Egress Gateway (`arm_gateway.py`)**:
   Dual-homed container sitting on both `internal` and `upstream` networks. It strictly enforces:
   - Rejection of HTTP verbs other than `CONNECT`.
   - Rejection of IP literal destinations (`CONNECT 1.1.1.1:443`).
   - Rejection of non-listed hostnames (`CONNECT cran.r-project.org:443` -> 403 Forbidden).
   - Rejection of internal service proxying (`CONNECT r-knowledge-mcp:8000` -> 403 Forbidden).
   - Strict mapping of `api.openai.com:443` -> `model-upstream:8443`.
3. **Container Hardening**:
   - `User="65534:65534"` (`nobody:nogroup`): Agent cannot bind privileged ports, create network devices, or alter system routing.
   - `CapDrop=["ALL"]`: Drops all Linux kernel capabilities (including `CAP_NET_RAW`, `CAP_NET_ADMIN`, `CAP_SYS_ADMIN`).
   - `ReadOnlyRootfs=True`: Prevents persisting state or altering binary wrappers on disk.
   - `Tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"}`: Writable workspace strictly bounded in RAM with `noexec`.
4. **Arm-Specific Topology**:
   - **Arm A**: MCP container is omitted from the network specification entirely. Candidate has zero network path to MCP (neither by name `r-knowledge-mcp` nor by IP). Cross-arm testing verifies Arm A cannot communicate with a concurrently running Arm B MCP container.
   - **Arms B & C**: MCP container is attached to `internal` on port 8000. Accessible directly via local DNS `http://r-knowledge-mcp:8000`.

---

## 3. Files Created and Modified

| File | Status | Role |
| :--- | :--- | :--- |
| `benchmarks/codex_r/studies/stage2_validity_v1/live_assets/arm_gateway.py` | New | CONNECT-only forward proxy enforcing static JSON allowlist mapping. |
| `benchmarks/codex_r/studies/stage2_validity_v1/live_assets/mock_model_server.py` | New | Local HTTPS/HTTP mock model server validating per-trial synthetic bearer tokens. |
| `benchmarks/codex_r/studies/stage2_validity_v1/live_assets/mock_agent.py` | New | Candidate container agent running network canaries or simulated tool/model interactions. |
| `benchmarks/codex_r/studies/stage2_validity_v1/live_network.py` | New | Per-trial Docker network topology manager, container hardening, structural verification, canaries, and sweeps. |
| `benchmarks/codex_r/studies/stage2_validity_v1/live_runner.py` | New | Opt-in live trial executor integrating with `StudyExecutionConfig`, `TrialLedger`, and frozen host scorers. |
| `benchmarks/codex_r/studies/stage2_validity_v1/study_configs.py` | Modified | Aligned `MINIMUM_CONFIRMATORY_S1_TASKS = 30` with `manifest.py` and `PREREGISTRATION.md`. |
| `benchmarks/codex_r/studies/stage2_validity_v1/records.py` | Modified | Extended composite score calculation for multidimensional scorers (`knowledge_pilot_v2`/`v2.1`). |
| `benchmarks/codex_r/studies/stage2_validity_v1/runner.py` | Modified | Added attempt artifact journaling (`write_attempt_evidence`) and recorded `primary_error_code`. |
| `benchmarks/codex_r/studies/stage2_validity_v1/cli.py` | Modified | Added `docker-preflight` and `live-smoke` commands. |
| `tests/test_stage26_live_runner.py` | New | 40 comprehensive tests (31 offline sandboxed tests, 9 live Docker tests). |
| `pyproject.toml` | Modified | Registered `docker` marker and set `pythonpath = ["src", "."]`. |

---

## 4. Concrete Docker Test Evidence

### Live Docker Test Suite (`pytest -m docker`)

All 9 live integration tests executed against Docker Engine (Total duration: 186.18 seconds):

```
tests/test_stage26_live_runner.py::test_live_topology_enforces_arm_isolation_and_delivers_model_and_mcp[A] PASSED [ 11%]
tests/test_stage26_live_runner.py::test_live_topology_enforces_arm_isolation_and_delivers_model_and_mcp[B] PASSED [ 22%]
tests/test_stage26_live_runner.py::test_live_topology_enforces_arm_isolation_and_delivers_model_and_mcp[C] PASSED [ 33%]
tests/test_stage26_live_runner.py::test_live_arm_a_cannot_reach_a_concurrent_arm_b_mcp_server PASSED [ 44%]
tests/test_stage26_live_runner.py::test_live_misconfigurations_are_detected_and_fail_closed PASSED [ 55%]
tests/test_stage26_live_runner.py::test_live_three_arm_plan_produces_valid_records_telemetry_and_clean_docker PASSED [ 66%]
tests/test_stage26_live_runner.py::test_live_interruption_mid_trial_cleans_up_then_resumes_without_rerunning PASSED [ 77%]
tests/test_stage26_live_runner.py::test_live_crash_leftovers_are_swept_by_run_label PASSED [ 88%]
tests/test_stage26_live_runner.py::test_live_isolation_failure_in_a_plan_fails_closed_without_running_the_workload PASSED [100%]
```

### Live CLI Smoke Run (`live-smoke --tasks D01`)

Executed command:
```powershell
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli live-smoke --out <scratch_path> --tasks D01
```

Results:
- Randomized Study Plan: 3 trials (`D01` on Arms A, B, C; Seed 42).
- Arm A (`t-000001`): MCP calls = 0, Model calls = 1, Score = 1.0 (12/12 checks passed).
- Arm B (`t-000002`): MCP calls = 0, Model calls = 1, Score = 1.0 (12/12 checks passed).
- Arm C (`t-000003`): MCP calls = 1, Model calls = 1, Score = 1.0 (12/12 checks passed).
- Network Teardown: 0 leftover containers, 0 leftover networks.
- Verification: 3/3 records valid under `trial_record.schema.json`.

---

## 5. A/B/C Experimental Arm Isolation Table

| Isolation Criterion | Arm A (No MCP) | Arm B (MCP Available) | Arm C (MCP Encouraged) | Enforced Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| **MCP Container Presence** | **None** | Running on `internal` | Running on `internal` | Docker container omission |
| **MCP DNS / IP Resolution** | **Denied** (NXDOMAIN / timeout) | **Allowed** (`http://r-knowledge-mcp:8000`) | **Allowed** (`http://r-knowledge-mcp:8000`) | Bridge namespace isolation |
| **Cross-Arm MCP Access** | **Denied** (Tested against Arm B) | Isolated to own trial | Isolated to own trial | Independent subnets per trial |
| **Candidate -> Internet Egress** | **Denied** (Unroutable) | **Denied** (Unroutable) | **Denied** (Unroutable) | Docker `--internal=true` |
| **Candidate -> Direct DNS** | **Denied** (Port 53 closed) | **Denied** (Port 53 closed) | **Denied** (Port 53 closed) | Docker `--internal=true` |
| **Public HTTPS via Gateway** | **Denied** (HTTP 403 Forbidden) | **Denied** (HTTP 403 Forbidden) | **Denied** (HTTP 403 Forbidden) | `arm_gateway.py` strict whitelist |
| **Internal Egress via Gateway** | **Denied** (HTTP 403 Forbidden) | **Denied** (HTTP 403 Forbidden) | **Denied** (HTTP 403 Forbidden) | Gateway host whitelist check |
| **Model API Egress** | **Allowed** (CONNECT tunnel) | **Allowed** (CONNECT tunnel) | **Allowed** (CONNECT tunnel) | Rewritten to `model-upstream` |
| **Credential Exposure** | **Zero** (synthetic token only) | **Zero** (synthetic token only) | **Zero** (synthetic token only) | Host injects per-trial token |
| **System Prompt Text** | Neutral base prompt | Neutral base prompt (**identical**) | Neutral base prompt + encouragement | Byte-exact string templates |
| **Tool Definition Exposure** | `tools=[]` | `tools=[r_knowledge_mcp]` | `tools=[r_knowledge_mcp]` | Agent invocation payload |

---

## 6. Scorer and Task Readiness Audit

### Confirmatory Core Minimum: Unified to 30 Tasks

In the interrupted state, `manifest.py` and `PREREGISTRATION.md` mandated a minimum of 30 tasks ($K=30, R=3$), while `study_configs.py` had an unaligned constant `MINIMUM_CONFIRMATORY_S1_TASKS = 20`.

**Resolution**: `study_configs.py` was updated to `MINIMUM_CONFIRMATORY_S1_TASKS = 30`, re-establishing a single source of truth across all code and preregistration metadata.

### Confirmatory Eligibility Status (Current: 0 Tasks Eligible)

Task eligibility in `S1_confirmatory_core` requires:
1. Complete task definition and frozen scorer contract.
2. At least 3 historical baseline (Arm A) runs.
3. Historical difficulty non-degenerate: baseline accuracy $\bar{Y}_A \in [0.10, 0.90]$.
4. Zero coupling to `BEN-002` (broken legacy test environment).

**Audit Findings**:
- Analysis of 88 historical scored runs in `historical_calibration_summary.json` revealed widespread ceiling effects: tasks like `D01`, `D02`, `D03` scored $1.00$ on all baseline runs.
- Tasks affected by `BEN-002` scored $0.00$ uniformly due to runner environment coupling.
- As a consequence, **0 tasks** are currently eligible for `S1_confirmatory_core` under the strict empirical variance constraint.
- The exploratory studies (`S2_pilot_feasibility` and `S3_exploratory_full`) remain fully valid and ready to execute.

### Costed Calibration Plan Prior to Confirmatory Phase

To qualify tasks for confirmatory testing, a calibration baseline run is required:

| Parameter | Value |
| :--- | :--- |
| **Candidate Task Pool** | 17 tasks (`D01`–`D03`, `R01`–`R08`, `P01`–`P06`) |
| **Calibration Arm** | Arm A only (unassisted baseline) |
| **Replications per Task** | $R=3$ |
| **Total Calibration Trials** | $17 \times 3 = 51$ trials |
| **Estimated Tokens per Trial** | ~12,000 prompt / ~2,500 completion |
| **Total Token Budget** | ~612,000 prompt tokens / ~127,500 completion tokens |
| **Estimated Cost (GPT-4o)** | ~\$3.00 – \$4.50 USD |
| **Execution Time** | ~40 minutes (at 2 concurrent workers) |
| **Qualification Gate** | Select tasks with baseline score $\bar{Y}_A \in [0.10, 0.90]$ until $K \ge 30$ tasks are qualified. |

---

## 7. Multi-Dimensional Scorer Output Contract

In benchmark versions `knowledge_pilot_v2` and `knowledge_pilot_v21`, the top-level scorer returns:
```json
{
  "passed": null,
  "total": null,
  "overall_score": null,
  "dimensions": {
    "schema_validity": {"passed": 3, "total": 3, "score": 1.0},
    "factual_correctness": {"passed": 4, "total": 4, "score": 1.0},
    "version_repository_identity": {"passed": 2, "total": 2, "score": 1.0},
    "source_quality": {"passed": 2, "total": 2, "score": 1.0},
    "unsupported_claims": {"passed": 1, "total": 1, "score": 1.0}
  }
}
```

**Bug Fixed in Stage 2.6**:
Previous logic in `records.from_runner_result` required top-level `passed` to be an `int`. When `None`, it fell back to classifying the trial as `infrastructure_failure`.

**Solution**:
`records.from_runner_result` now detects multidimensional output and computes:
$$\text{checks\_passed} = \sum_{d} \text{dimension}[d].\text{passed}, \quad \text{checks\_total} = \sum_{d} \text{dimension}[d].\text{total}$$
$$\text{score} = \frac{\text{checks\_passed}}{\text{checks\_total}}$$
This preserves authentic scientific scoring for all tasks.

---

## 8. Adversarial Self-Review

| Vulnerability Dimension | Risk Analyzed | Defense & Proof |
| :--- | :--- | :--- |
| **1. Host Credential Leakage** | Candidate container inspects env or files to steal model API keys. | Real host API keys are never passed into containers. The gateway terminates CONNECT tunnels; model upstream authenticates against local synthetic tokens. |
| **2. DNS Exfiltration** | Agent tunnels data through UDP 53 DNS queries to external resolvers. | Docker `--internal` bridge has no gateway or DNS forwarder. Direct UDP canary probes fail closed with socket errors. |
| **3. Cross-Arm Crosstalk** | Arm A discovers and talks to an Arm B MCP container on the bridge. | Every trial uses a uniquely named network (`s26-int-<run_label>-<trial>`). Verified by `test_live_arm_a_cannot_reach_a_concurrent_arm_b_mcp_server`. |
| **4. Container Escape** | Agent executes privilege escalation to alter Docker or host files. | Non-root `65534:65534`, `CapDrop=["ALL"]`, `ReadOnlyRootfs=True`, and `noexec` on `/tmp`. |
| **5. Prompt Contamination** | Arm A instructions hint at MCP tools or differ from Arm B. | Verified in `test_stage2_validity.py`: `manifest.generate_prompt("A", task) == manifest.generate_prompt("B", task)`. Arm C appends only the preregistered text. |
| **6. Survivor Bias** | Failed or timed-out trials are omitted from the statistical ledger. | `TrialLedger` initializes every planned trial upfront in `trial_records.jsonl`. Unfinished or failed trials remain recorded as `infrastructure_failure` or `timeout`. |
| **7. Frozen Scorer Drift** | Scorer contracts or task definitions mutate over the experiment. | `cli.py frozen --verify` tests 279 files against SHA-256 digests. Test suite enforces 0 differences. |
| **8. Asymmetric Starvation** | Arm B/C latency overhead causes timeouts while Arm A succeeds. | Timeouts are enforced uniformly per attempt via Python subprocess timers; telemetry captures elapsed wall-clock and tool latency separately. |
| **9. Orphaned Containers** | Crashes leave dangling containers or networks consuming host ports/IPs. | Every resource is tagged with `stage26.run_label`. `live_network.sweep_orphaned_resources` automatically purges remnants before and after runs. |
| **10. Mediator Conditioning** | Analyzing Arm B only when the model voluntarily called MCP. | The primary estimand is strictly Intention-to-Treat ($ITT = \bar{Y}_B - \bar{Y}_A$). Mediator metrics ($CATE$ / Complier Average Causal Effect) are strictly labeled exploratory. |

---

## 9. CI Compatibility & Testing Strategy

- **Default Offline CI**: Run `pytest -m "not docker"` in standard sandbox mode. Executes 198 tests in $< 30\text{ s}$ with zero Docker or network requirements.
- **Docker-Enabled CI / Integration Runners**: Run `pytest -m docker` in environments with Docker Engine. Executes the 9 end-to-end container isolation tests.
- **Code Quality**: `ruff check .` and `ruff format --check .` enforced across all 315 files with 0 warnings.

---

## 10. Outstanding Pre-Conditions for Paid Model Pilot

Before conducting paid model experiments:
1. **Explicit Human Authorization**: Human owner must provide authorization to spend model API budget.
2. **API Key Provisioning**: Configure model provider credentials (e.g. `OPENAI_API_KEY`) on the host runner (never in containers).
3. **Execution of 51 Calibration Trials**: Run Arm A baseline calibration on the 17 candidate tasks to identify tasks meeting the $0.10 \le \bar{Y}_A \le 0.90$ variance threshold to satisfy preregistration requirements.

---

## 11. Final Determination

$$\mathbf{PILOT\ INFRASTRUCTURE\ READY}$$

All software, networking, security, scoring, recording, and telemetry layers are fully implemented, verified, and ready for deployment.

