# Review of Seven Docker-Marked Offline Tests

**Review type:** static inspection only; no test, Docker command, image pull, or<br>
container/network operation was executed.
**R01-A status:** **NO-GO**.

## Scope and shared helpers

The seven tests are the six `@pytest.mark.docker` cases in
`tests/test_codex_docker_runtime.py` and one lifecycle case in
`tests/test_codex_managed_agents_lifecycle.py`. The tests use `tmp_path` or
`tmp_path_factory` for public synthetic workspaces. `prepared_r01_workspace`
copies only `TASK.md`, `renv.lock`, and `data/records.csv` to a new path outside
the repository (`benchmarks/codex_r/exploratory/docker_runtime.py:728-737`).

`_docker_runtime` and `_codex_runtime` require image ID environment variables,
Docker CLI, and a reachable daemon; they run `docker version` before returning
the runtime (`tests/test_codex_docker_runtime.py:80-115`). They do not pull an
image. `verify_engine_and_image` uses Docker inspect/version/info and runs
`sha256sum` in an image with `--network none` to validate the embedded lockfile
(`docker_runtime.py:374-439`).

The fixed candidate container policy is non-privileged, read-only rootfs,
capabilities dropped, no-new-privileges, resource limited, uid 65534, tmpfs
work areas, and a single `/candidate` bind mount. Its default network is
`none` (`docker_runtime.py:452-529`). This policy does not constrain the Docker
daemon itself or guarantee host firewall behavior. All claims below describe
the inspected test implementation, not verified live Docker compatibility.

## Per-test findings

### 1. `test_real_docker_denies_host_evaluator_secret_and_network_access`

**Classification: SAFE, conditional on the checked-in immutable R image and a
working Linux Docker engine.**

- **References:** test `tests/test_codex_docker_runtime.py:118-158`;
  helper/runtime `docker_runtime.py:45-78, 606-669, 728-737`;
  container policy `docker_runtime.py:452-529`.
- **Resources:** one disposable candidate probe container; no Docker network is
  created. Container uses `--network none`. It bind mounts only the synthetic
  public workspace at `/candidate`; test-only sentinel directories are on the
  host but are not mounted.
- **Network/API/inference:** the shell probe attempts curl checks for
  `example.com`, `model-proxy`, and the local MCP gateway after clearing proxy
  variables. The container has `--network none`; no credential is passed and
  no Managed Agents client exists. These are denial probes, not API or
  inference calls. A working Docker engine is still a host-level prerequisite.
- **Credentials/state/images:** only synthetic sentinel files are made. The
  probe inspects paths for credentials/oracles but does not read host
  credentials or historical state. Requires the pre-existing image named by
  `R_KNOWLEDGE_BENCH_IMAGE_ID` with the frozen R image digest and lockfile.
- **Cleanup:** after successful container creation, `finally` force-removes and
  verifies removal (`docker_runtime.py:624-640`). If container creation itself
  partially succeeds but returns an invalid ID, the cleanup block is not yet
  entered; ordinary Docker `create` failure semantics are assumed. Test temp
  workspace cleanup is pytest-managed. No explicit timeout wrapper covers the
  entire probe; individual Docker commands are bounded.
- **Independent WSL2 execution:** safe if Docker is already available and the
  image is already local; avoid configuring registry credentials or pulling
  images as part of this test.
- **Prerequisites/evidence:** Docker Linux daemon, local immutable R image ID,
  and writable isolated temp storage. Expected report says fixed-probe-only
  isolation, not agent isolation, with `launch_permitted: false` and verified
  container cleanup.

### 2. `test_real_docker_timeout_force_removes_container_and_child_process`

**Classification: SAFE, conditional on the checked-in immutable R image and
Linux Docker engine.**

- **References:** test `tests/test_codex_docker_runtime.py:160-168`;
  `SLEEP_SCRIPT` at `docker_runtime.py:79`; runtime
  `docker_runtime.py:672-725`; common create policy `452-529`.
- **Resources:** one disposable container, no bind mount after the fixed mount
  pair is removed, and `--network none`. It runs `sleep 60` as a child process.
- **Network/API/inference:** no network path, credentials, HTTP client, or
  Managed Agents operation. No inference.
- **Credentials/state/images:** no host credentials are passed or read. Uses
  local `R_KNOWLEDGE_BENCH_IMAGE_ID` image. No historical-state access.
- **Cleanup:** a `finally` block force-removes the container and verifies its
  absence. The wait deadline is caller-set but constrained to at most five
  seconds; child discovery polls for up to about four seconds, each Docker
  command has a bound (`docker_runtime.py:672-725`).
- **Independent WSL2 execution:** safe with the local pinned image and Docker
  daemon. It is suitable for isolated execution.
- **Prerequisites/evidence:** Docker Linux daemon and local image. Expected
  evidence identifies the synthetic timeout probe, observed child, force
  removal, zero sessions/requests, and `container_cgroup_force_removed`.

### 3. `test_frozen_image_digest_and_embedded_lockfile_are_verified`

**Classification: SAFE.**

- **References:** test `tests/test_codex_docker_runtime.py:171-178`;
  helper `80-96`; `verify_engine_and_image` at
  `docker_runtime.py:374-439`.
- **Resources:** no container or network is created. It queries Docker engine
  metadata and inspects the local image; it starts one short-lived `sha256sum`
  container with `--network none` to compare the embedded `renv.lock` digest.
- **Network/API/inference:** no external connection from the probe, no
  credentials, Managed Agents API, or inference. Docker daemon access is
  required.
- **Credentials/state/images:** no historical state or user credentials are
  read. Requires the locally present immutable R image specified by
  `R_KNOWLEDGE_BENCH_IMAGE_ID`; missing prerequisites cause a skip or error,
  not a pull.
- **Cleanup:** checksum container uses `docker run --rm`; no explicit named
  resources. Commands are bounded by the Docker runtime wrapper.
- **Independent WSL2 execution:** safe as a read/inspect plus network-disabled
  image check.
- **Prerequisites/evidence:** Docker Linux daemon and local image. Expected
  output contains engine versions/type, exact digest, image defaults, and
  embedded lockfile SHA-256.

### 4. `test_real_codex_exec_server_starts_in_offline_isolated_candidate`

**Classification: SAFE, conditional on a reviewed local Codex candidate image
and Linux Docker engine.**

- **References:** test `tests/test_codex_docker_runtime.py:180-198`;
  `CODEX_STARTUP_SCRIPT` at `docker_runtime.py:81-111`;
  `run_offline_executor_probe` at `docker_runtime.py:830-933`;
  create policy `452-529`.
- **Resources:** one disposable candidate container; no user-created Docker
  network, with `--network none`. It starts the real Codex `exec-server` bound
  to loopback inside the container. Workspace is the three public R01 input
  files only.
- **Network/API/inference:** startup script attempts `curl` checks to
  `example.com`, model proxy, and local MCP gateway before starting the server.
  The candidate has no network. It receives no `CODEX_API_KEY` and no
  application key. No session registration or inference is possible through
  this container under the configured policy. Docker engine access remains a
  host capability.
- **Credentials/state/images:** no host credential paths are mounted; no
  historical files are included. Requires `R_KNOWLEDGE_CODEX_IMAGE_ID`, the
  candidate image derived from the frozen R image, and the Codex binary/version
  under test. No image pull is performed.
- **Cleanup:** force-removal in `finally`, followed by removal verification.
  Startup/process inspection deadline is at most 15 seconds; Docker calls
  have individual bounds (`docker_runtime.py:830-933`). If create partially
  succeeds before an ID is accepted, cleanup is not established.
- **Independent WSL2 execution:** safe with the exact local reviewed image and
  no credential injection. Startup compatibility evidence is specific to that
  image and Docker version.
- **Prerequisites/evidence:** local Codex image, Linux Docker daemon, public
  workspace. Expected evidence confirms process observation and negative
  checks, while explicitly keeping agent isolation false and launch false.

### 5. `test_real_docker_restricted_egress_denies_bypass_without_upstream_requests`

**Classification: UNKNOWN for independent execution under a strict
no-external-connection requirement; the tested candidate is isolated, but the
test deliberately provisions an outbound-capable proxy sidecar.**

- **References:** test `tests/test_codex_docker_runtime.py:201-227`;
  `run_restricted_egress_probe` at `docker_runtime.py:1406-1552`;
  `RestrictedEgressNetwork` and cleanup at `docker_runtime.py:1140-1404`;
  proxy behavior `exploratory/egress_proxy.py:13-20, 57-113`;
  denial script `docker_runtime.py:119-151`.
- **Resources:** two Docker bridge networks (an outbound bridge and an
  internal isolated candidate-to-proxy network), an egress proxy container,
  and a disposable candidate container. It builds a local proxy image from a
  pinned, already-local Python base image (`runtime/egress.Dockerfile:1-10`).
  Candidate joins only the internal network; proxy joins both.
- **Network/API/inference:** the candidate script deliberately attempts direct
  requests to public IPs, the cloud metadata IP, arbitrary domains, a
  non-443 official host, and `host.docker.internal`; these should be denied.
  The proxy itself has an outbound bridge and its code can establish real TCP
  TLS tunnels to `api.openai.com:443` and
  `codex-cloud-environments.chatgpt.com:443` when requested. Current test
  inputs are denied host/IP/port cases, so the inspected path intends zero
  upstream requests, but the service is outbound-capable. The probe does not
  invoke a Managed Agents client or inference; no application or executor key
  is passed. Treat this as requiring explicit network-owner acceptance and
  isolation of the Docker daemon.
- **Credentials/state/images:** no real credential is read or supplied. Uses
  the local Codex candidate image ID and pinned Python base image; builds the
  proxy from repository source without `--pull`. Uses only public workspace
  inputs.
- **Cleanup:** candidate removal and topology cleanup are in `finally`; proxy
  container and both networks are removed and verified by helper
  (`docker_runtime.py:1381-1404, 1470-1516`). Cleanup failures are surfaced.
  A created Docker build image/tag is not removed by topology cleanup.
- **Independent WSL2 execution:** **not recommended independently** until the
  operator confirms that creating an outbound bridge is acceptable and the
  pinned proxy code/image are reviewed. This has more host/network impact than
  an offline candidate-only test.
- **Prerequisites/evidence:** local Codex image, local pinned Python base,
  Docker build and bridge-network permissions, and explicit network acceptance.
  Expected report claims denial observations and zero upstream HTTP requests;
  that is mocked-by-design policy behavior, not proof of live external firewall
  enforcement.

### 6. `test_real_codex_exec_server_uses_proxy_without_contacting_upstream`

**Classification: SAFE, conditional on the reviewed local Codex image and
Linux Docker engine.**

- **References:** test `tests/test_codex_docker_runtime.py:230-248`;
  `run_codex_proxy_transport_probe` at `docker_runtime.py:1555-1780`;
  fake sink `FAKE_CONNECT_SINK` at `docker_runtime.py:153-174`;
  candidate policy `452-529`.
- **Resources:** one isolated internal Docker network, one local Python fake
  CONNECT sink container, and one Codex candidate container. No outbound
  bridge is created. Both containers join only the internal isolated network.
- **Network/API/inference:** the real Codex binary is pointed at a synthetic
  `api.openai.com` registration URL and sends a CONNECT request to the local
  sink. The sink responds with synthetic HTTP 403; it never opens an upstream
  socket (`FAKE_CONNECT_SINK`, `153-174`). Candidate DNS is forced to localhost
  and the candidate network is internal. No TLS handshake, WebSocket
  registration, Managed Agents request, or inference occurs according to the
  inspected path.
- **Credentials/state/images:** application key absent; synthetic environment
  key only. The helper passes it using the child environment, not a real secret.
  Requires local Codex image and local pinned Python base image. Public
  workspace only; no historical state.
- **Cleanup:** `finally` removes and verifies candidate, sink, and internal
  network; failures are surfaced (`docker_runtime.py:1730-1778`).
- **Independent WSL2 execution:** safe if the Docker engine enforces internal
  isolated networks and both images are already local. No external bridge is
  present.
- **Prerequisites/evidence:** local Codex/Python images, Docker Linux engine,
  and temp workspace. Expected evidence is only proxy transport to the local
  sink, synthetic 403, zero contacted upstream hosts, no TLS/WebSocket/session,
  and cleanup verified.

### 7. `test_real_docker_synthetic_lifecycle_never_creates_a_trial_record`

**Classification: UNKNOWN; do not include in the smallest sequence.**

- **References:** test `tests/test_codex_managed_agents_lifecycle.py:530-650`;
  `RestrictedEgressNetwork` at `docker_runtime.py:1140-1404`;
  `run_codex_proxy_transport_probe` at `docker_runtime.py:1555-1780`;
  scoring `runner/bench.py:321-337` and Docker score command
  `runner/bench.py:166-223, 270-319`.
- **Resources:** starts a two-network restricted-egress topology and proxy
  container. Its fake runtime starts no actual Managed Agents executor; it
  instead runs the internal fake-proxy transport probe (which creates another
  internal network and two containers). The lifecycle then calls the real
  scorer, which starts an R scoring container with `--network none` and
  read-only mounts of oracle/config. The test's `run_one` call is synthetic and
  must not be confused with an operator execution.
- **Network/API/inference:** `FakeClient` is local and returns a synthetic
  session shape; it makes no API calls. No real inference is performed. The
  test nevertheless starts `RestrictedEgressNetwork`, whose proxy is attached
  to an outbound bridge and permits real TLS tunnels to two allowlisted public
  hosts. The fake runtime does not route the lifecycle client through that
  topology; its transport probe is confined to a separate internal network.
  This makes the outbound sidecar unnecessary for the fake flow and leaves an
  avoidable outbound-capable resource during the test. Thus external access is
  not shown to be invoked by this fixture, but its presence prevents a strong
  “no external connection possible” guarantee.
- **Credentials/state/images:** synthetic confirmation strings and synthetic
  key only; authorization/consumed lease state is created under `tmp_path`,
  not historical state. Requires both Codex and frozen R image IDs, Docker,
  pinned local Python image, and the benchmark scorer's R environment. The
  scorer executes the checked-in R oracle script in a container; no candidate
  user code from a live trial is involved.
- **Cleanup:** lifecycle tries executor stop (fake runtime), session delete
  (fake client), topology cleanup, and lease release. Proxy probe cleans its
  candidate/sink/network in `finally`; topology cleanup removes proxy/two
  networks. The scorer uses process/container cleanup in `runner/bench.py:270-319`.
  Cleanup may be incomplete after daemon failure, timeout, or abrupt process
  termination; verify Docker inventory and the temporary lease state before
  treating the run as clean.
- **Independent WSL2 execution:** not recommended as an isolated test until
  unnecessary outbound topology creation is removed or expressly approved.
  It directly exercises the lifecycle controller and scorer, creating
  synthetic authorization/lease state, so it is broader than a boundary unit
  test.
- **Prerequisites/evidence:** both immutable images, local Python base image,
  Docker build/bridge permissions, temp storage, and a functioning scorer.
  Expected evidence is a synthetic lifecycle audit only, false
  `launch_permitted`, synthetic scoring, zero upstream hosts, and cleanup
  assertions. It is not evidence of real API or live-session compatibility.

## Smallest safe Docker sequence

After an operator confirms the Linux Docker daemon is isolated and the required
immutable images are already local, the smallest sequence that obtains useful
Docker evidence without an outbound bridge is:

1. `test_frozen_image_digest_and_embedded_lockfile_are_verified` — read-only
   engine/image verification plus a network-disabled checksum container.
2. `test_real_docker_denies_host_evaluator_secret_and_network_access` — one
   no-network boundary probe with only public workspace input.
3. `test_real_docker_timeout_force_removes_container_and_child_process` — one
   no-network child-process timeout/forced-removal probe.

If Codex image startup evidence is separately required, add
`test_real_codex_exec_server_starts_in_offline_isolated_candidate`, then
`test_real_codex_exec_server_uses_proxy_without_contacting_upstream`. Keep the
restricted-egress test and synthetic lifecycle test out of the initial
sequence unless the outbound-capable proxy topology and its scope are
explicitly accepted. This review does not authorize execution.

## Limitations

This is source review only. Docker daemon enforcement, image contents, engine
version behavior, bridge firewalling, cleanup after host crash, and actual
WSL2 compatibility remain unverified. “No upstream requests” assertions are
test reports based on the probe’s inspected path; they are not live network
captures. No Docker tests were executed. R01-A remains **NO-GO**.
