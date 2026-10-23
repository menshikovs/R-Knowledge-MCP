# Single-trial Codex runtime integration

## Status: one-trial lifecycle is wired; no live trial has been run

The primary interface selected for a future real turn is the documented
OpenAI Managed Agents API with a self-hosted Docker executor. GPT-6 Luna
supports Responses tool use and `medium` reasoning. The Agents API session
configuration supports a self-hosted environment, reasoning settings, and MCP
tool allowlists. The executor environment key is distinct from the application
API key; official guidance states that the restricted environment key is
readable inside its environment, so the application key must stay on the
controller.

The local R01-A Codex candidate image is built from the unchanged frozen R
image, pinned at
`sha256:467944b2623c0e7a6f9cbbf24022616911cd834dd2a2200bd39fbe295666eca5`.
It adds the official Codex CLI 0.163.0 Linux x86_64 package from the OpenAI
Codex release and verifies the release archive SHA-256 before extraction. The
observed local candidate image ID is
`sha256:ea7eaa089df6671c5eb7dc913fb752909dff5344aafe5f8c4974aa97e2365074`.
The Docker probe verifies that the frozen R image's root filesystem layers are
an unchanged prefix of the candidate image layers. The original image and the
strict 72-trial benchmark remain unchanged.

The real `codex exec-server` 0.163.0 process was observed running inside that
candidate image in a Linux Docker Desktop container. The fixed probe mounted
only the public R01 workspace, used UID 65534, read-only root, no-new-privileges,
all capabilities dropped, 2 CPU / 2 GiB / 256 PID limits, `/tmp` and `/work`
tmpfs, and Docker `network=none`. It verified the expected oracle, repository,
host-home credential, Docker socket, and other-trial paths were absent, the
application API key was absent, arbitrary internet was unreachable, MCP count
was zero, and the container was removed. This establishes the boundary for
this fixed offline executor probe; it does not prove a registered agent session
has the same effective filesystem or tools.

The self-hosted Agents API needs outbound environment registration through
`api.openai.com` and a registered WebSocket relay on
`codex-cloud-environments.chatgpt.com`. A real Codex 0.163.0 `exec-server`
was run in an internal Docker network against a local fake proxy: it issued
`CONNECT api.openai.com:443`, received a synthetic 403, and made no upstream
connection. A Docker candidate probe also confirmed that direct public IP,
metadata IP, arbitrary-domain, and non-443 proxy access are denied. These
checks verify transport selection and denial behavior only; they do not verify
TLS, WSS, registration, or account/model access.

`egress_proxy.py` accepts CONNECT only for the exact documented hosts
`api.openai.com:443` and `codex-cloud-environments.chatgpt.com:443`. It
resolves names on the proxy side, rejects private/non-global DNS answers, and
does not intercept TLS or rewrite `remote_url`. The candidate has no DNS route
and joins only Docker's internal isolated-gateway network. The proxy alone
joins that network and a normal outbound bridge. This enforces host and port,
not encrypted HTTP paths; dynamic signed relay target validation and live WSS
compatibility remain unverified.

`managed_agents.py` contains the fixed R01-A/GPT-6 Luna/medium session request,
controller-side HTTPX calls for session creation, event submission/streaming,
cancellation and deletion, response/event byte limits, redirect rejection,
fixed official URL checks, idempotent task submission and event secret
redaction. The SSE client subscribes using the documented
`/v1/agents/sessions/{id}/events?stream=true` route before submitting input.
Tests use `httpx.MockTransport` and synthetic values only. They do not establish
API-account model access. Session creation and inference were never called.
The live CLI is single-trial only. It does not support an automatic or batch
launch command.

`adapter.py run-one` now invokes the production `R01ALifecycleController` and
the existing Managed Agents client, Docker executor, fixed-host egress proxy,
scorer, and balance ledger. It accepts only R01-A / Condition A, permits one
session and one task submission, has no retry or batch mode, and enforces the
900-second deadline. A short-lived authorization binds the exact public
workspace, immutable Codex image ID, runtime fingerprint, fixed per-user WSL
state directory, balance snapshot, model, reasoning and zero-tool configuration.
The consumed-trial marker is persistent: do not delete the state directory or
marker to try again. Synthetic lifecycle records cannot be imported as real
benchmark outcomes.

The `authorize-one` command does not contact OpenAI or inspect credentials. It
requires explicit typed authorization for exactly one paid attempt and a
separate operator attestation that the executor key is restricted. The API
cannot independently prove the key's permissions. Official guidance says the
executor key is readable by agent code, so this remains a material limitation;
the application API key stays controller-side and is filtered out of the
candidate process environment. The real launch checks Docker images, public
workspace contents, model/reasoning/tools returned by session creation, and
executor connection before submitting the one task. A prerequisite that needs
session creation is attempted only within this authorized single-trial path.

## Relay and lifecycle investigation for this task

The current official self-hosted executor guide documents an application
request to `https://api.openai.com` and an outbound WebSocket to
`wss://codex-cloud-environments.chatgpt.com`. It says to pass the returned
`session.environment.remote_url` unchanged to `codex exec-server --remote` and
provides the separate environment key as `CODEX_API_KEY`. It explicitly warns
that agent-generated code can read that environment key. The official guide
does not specify a local forward-proxy interface, a path-aware proxy protocol,
a TLS interception CA workflow, or signed relay URL matching rules. The
installed pinned CLI's `exec-server --help` lists `--remote` and transport
choices, but does not document a path-policy interface. The offline integration
starts the production restricted topology and runs Codex against a separate
local fake CONNECT sink. It deliberately does not connect that Codex process
to the outbound sidecar, so the test cannot establish live registration.

Consequently this change does not invent a proxy setting, terminate TLS, or
allow unrestricted CONNECT. A TCP/TLS pass-through can constrain destination
hosts but cannot inspect encrypted HTTP paths. TLS termination would require
the candidate to trust an interception certificate and would violate the
normal certificate-validation boundary. The candidate is confined to the
internal isolated-gateway network; the only outbound path is the fixed-host
CONNECT proxy. Local Docker probes verify negative controls and a synthetic
CONNECT, not a live relay test.

The managed-session API methods are still only tested against synthetic
HTTPX responses. No live session has been created, so the actual `remote_url`,
registered executor handshake, API key scope/revocation, model/account access,
or resolved session settings are not observed. The code does not claim that a
mock event stream proves executor protocol compatibility. The manually
authorized `run-one` path verifies the returned settings and executor
connection before its sole task submission.

`lifecycle.py` now joins the existing authorization validator/consumer,
cross-process `SingleTrialLease`, balance ledger, Managed Agents client,
restricted Docker topology, executor, artifact sealer, and isolated R scorer
for exactly one R01-A attempt. The controller records ordered lifecycle states,
uses dependency injection for its API client, cancels on failed streams, and
keeps the lease until verified termination, session deletion, network cleanup,
scoring, and the mandatory spending checkpoint have completed. A watchdog
starts immediately before task submission and force-removes the container at
the configured deadline (no more than 900 seconds); cleanup verifies removal
again. It rejects additional files, links, special files, and over-limit workspaces before
artifact sealing. If cleanup cannot be verified, it retains the lock and does
not export artifacts. A missing or unreconciled operator checkpoint stops the
ledger; the client-side ledger is not a provider spending limit.

The same controller has a synthetic mode that accepts only an explicitly
synthetic injected client and returns a distinct
`synthetic_r01a_lifecycle_audit_not_benchmark_result` record. The Docker
integration test uses the pinned Codex binary and local synthetic CONNECT 403,
synthetic control-plane events, the existing restricted topology setup, the
allowlisted artifact export, and the real frozen-image scorer. No OpenAI host
is contacted; the resulting score is synthetic test evidence and cannot be
imported as a benchmark result. The normal controller still requires explicit
fresh authorization and every live verification gate to be true. No live
session, model request, or inference was started in this change.

Condition A's generated Agents API configuration has zero MCP tools. Runtime
tool discovery is still unverified because it would require a real session.
Conditions B/C are intentionally rejected by the config builder: the existing
recording gateway is stdio-only and has no authenticated candidate-facing HTTP
route. Do not claim the 15/20 effective tool inventories have been verified.

## Rebuild and offline checks

The frozen R image is a local benchmark artifact, not a public registry image.
Docker BuildKit tried to pull its digest from Docker Hub, so use Docker
Desktop's legacy builder while this local-only base is in use:

```bash
DOCKER_BUILDKIT=0 docker build --no-cache \
  -f benchmarks/codex_r/runtime/candidate.Dockerfile \
  -t rkmcp-codex-runtime:codex-0.163.0 .
docker image inspect rkmcp-codex-runtime:codex-0.163.0 --format '{{.Id}}'
```

Prepare a fresh public R01 workspace outside the evaluator repository, then
run the actual binary startup/security check with the immutable local candidate
image ID:

```bash
python benchmarks/codex_r/exploratory/adapter.py prepare \
  --task R01 --workspace "$HOME/.cache/rkmcp/public-R01-A"
python benchmarks/codex_r/exploratory/adapter.py codex-runtime-probe \
  --image "$(docker image inspect rkmcp-codex-runtime:codex-0.163.0 --format '{{.Id}}')" \
  --workspace "$HOME/.cache/rkmcp/public-R01-A" --timeout-seconds 5
```

The probe is explicitly an offline binary-startup record, not a trial. It does
not create an Agents session, use `CODEX_API_KEY`, access model endpoints or
claim effective tool discovery. `docker-runtime-probe` tests against the frozen
R image and the pinned Codex image are marked `docker` and require
`R_KNOWLEDGE_BENCH_IMAGE_ID` and `R_KNOWLEDGE_CODEX_IMAGE_ID` respectively.
No real API key is read by CI tests.

The task workspace created for the local test was removed after verification.
The original strict benchmark, score importer and oracle were not modified.

## One manually authorized WSL2 launch

These commands describe exactly one R01-A attempt. Run them from the Linux
distribution integrated with the existing Docker Desktop. The checkout path
below is the WSL mount of this workspace; adjust only if you keep a separate
Linux-side checkout. Do not run the
authorization or launch command unless you intend to incur possible charges.
The displayed prepaid balance may be stale and delayed accounting can cause
charges to exceed it; the client-side ledger is not a hard spend limit. The
documented executor key is readable by agent-generated code. Use a separate,
narrowly scoped key and revoke it after the attempt. Never put either key in
command arguments or files.

```bash
set -euo pipefail
cd /mnt/c/programming_pj/cran-mcp
if [[ ! -x .venv-wsl/bin/python ]]; then python3 -m venv .venv-wsl; fi
source .venv-wsl/bin/activate
python -m pip install -e '.[dev]'
ADAPTER=benchmarks/codex_r/exploratory/adapter.py
STATE="$HOME/.local/state/r-knowledge-mcp/r01a"
WORKSPACE="$HOME/.cache/rkmcp/public-R01-A"
IMAGE="$(docker image inspect rkmcp-codex-runtime:codex-0.163.0 --format '{{.Id}}')"

# Prepare only when absent; the command refuses to overwrite an existing tree.
if [[ ! -e "$WORKSPACE" ]]; then
  python "$ADAPTER" prepare --task R01 --workspace "$WORKSPACE"
fi

# Keys are entered without echo. The controller filters the application key
# from the candidate process. The executor key is visible to candidate code.
read -rsp 'Controller OpenAI API key: ' OPENAI_API_KEY; echo
export OPENAI_API_KEY
read -rsp 'Restricted executor CODEX_API_KEY: ' OPENAI_EXECUTOR_API_KEY; echo
export OPENAI_EXECUTOR_API_KEY

# Replace these placeholders with a fresh operator dashboard observation and
# a conservative reserve. The estimate is informational and non-binding.
BALANCE_CENTS=1000
RESERVE_CENTS=300
ESTIMATE_CENTS=150
BALANCE_CHECKED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "$STATE"
python "$ADAPTER" authorize-one --trial R01-A \
  --workspace "$WORKSPACE" --image "$IMAGE" \
  --available-balance-cents "$BALANCE_CENTS" \
  --reserve-cents "$RESERVE_CENTS" \
  --estimated-spend-cents "$ESTIMATE_CENTS" \
  --balance-source operator_dashboard \
  --balance-checked-at "$BALANCE_CHECKED_AT" \
  --confirm 'AUTHORIZE ONE PAID TRIAL R01-A' \
  --confirm-restricted-key-scope 'CONFIRM RESTRICTED EXECUTOR KEY SCOPE R01-A' \
  --authorization-output "$STATE/authorization.json"

# Sole launch command: at most one session and one task, no retries or batches.
# Keep this terminal attached for the mandatory post-trial review checkpoint.
python "$ADAPTER" run-one --trial R01-A \
  --workspace "$WORKSPACE" --image "$IMAGE" \
  --authorization "$STATE/authorization.json" \
  --result "$STATE/r01a-result.json"
unset OPENAI_API_KEY OPENAI_EXECUTOR_API_KEY
```

The balance and estimate above are examples and must be replaced with current
operator observations. `authorize-one` itself makes no OpenAI call and reads no
credential. It writes a five-minute, one-use authorization bound to the exact
workspace, image digest, runtime fingerprint, model, reasoning, balance data,
and fixed WSL state directory. A persistent marker prevents another R01-A
launch. Do not delete or replace the state directory to retry.

To cancel from a second WSL terminal while the foreground launch is active, run
the verified cancellation command below; pressing Ctrl+C in the launch
terminal is also supported. Cleanup failure blocks artifact export:

```bash
cd /mnt/c/programming_pj/cran-mcp
source .venv-wsl/bin/activate
python benchmarks/codex_r/exploratory/adapter.py cancel-one
```

After the launch process exits, check Docker/session cleanup and inspect its
saved audit:

```bash
cd /mnt/c/programming_pj/cran-mcp
source .venv-wsl/bin/activate
STATE="$HOME/.local/state/r-knowledge-mcp/r01a"
python benchmarks/codex_r/exploratory/adapter.py verify-cleanup \
  --result "$STATE/r01a-result.json"
python benchmarks/codex_r/exploratory/adapter.py inspect-result \
  --result "$STATE/r01a-result.json"
sed -n '1,240p' "$STATE/r01a-result.json"
```

The run stops for review of usage, provider-reported spend, independent score,
and a newly checked balance. Missing usage or unreconciled spend stops the
ledger. No later trial is authorized automatically. Cleanup verification does
not establish billing reconciliation.

## Exact blockers before a real R01-A turn

- A path-aware endpoint broker and separately verified outbound WSS relay are
  not implemented. The CONNECT proxy enforces exact hosts and port 443 only;
  it cannot inspect TLS-encrypted API paths or dynamic signed relay targets.
  Live WSS through this proxy remains unverified.
- No live Managed Agents session/environment has been created. The launch path
  passes the documented executor key only as `CODEX_API_KEY` to the executor;
  the permissions depend on the operator-supplied key and attestation.
- Account-level access to `gpt-6-luna` and the resolved live `medium` setting
  remain unverified; do not verify by creating a session during ordinary CI.
- The executor process is tested against a synthetic local CONNECT sink only.
  Remote registration, actual TLS/WSS lifecycle, account access, and observed
  effective model settings remain unverified. The live `send_and_stream`
  cancellation and 900-second path is covered with synthetic API tests, not a
  real service session.
- Session deletion only removes the public API session; official lifecycle
  guidance says provider compute must be stopped separately. A future runner
  must verify Docker container termination independently before artifact export.
- The lifecycle controller now wires verified termination, artifact export,
  scorer handoff, and the balance/usage/correctness checkpoint. It has been
  exercised offline with synthetic responses; live end-to-end behavior is
  unverified.
- A's zero-MCP configuration is deterministic but has not been observed in an
  actual Codex agent session. B/C candidate gateway networking and effective
  15/20 tool inventories remain future work.

The operator's prepaid balance and disabled automatic top-ups do not create a
hard spend cap. Before a future paid trial, require a current operator-confirmed
balance, reserve, one-row authorization, and review after that trial. Never
automatically start the next row. The existing strict 72-trial benchmark
remains separate and unchanged.

## Reviewed official documentation

- [GPT-6 Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna)
  documents Responses tools, MCP, and `reasoning.effort: medium` support.
- [Self-hosted sandboxes](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted)
  documents the two outbound hosts, the unchanged `remote_url`,
  `codex exec-server --remote`, and the restricted environment-key arrangement.
- [Sandbox security](https://developers.openai.com/api/docs/guides/agents-api/environments/security)
  says agent-generated code can read environment credentials and that the
  application API key must stay outside the environment.
- [MCP connections](https://developers.openai.com/api/docs/guides/agents-api/tools/mcp)
  documents environment-origin MCP connections and `allowed_tools`.
- [Session events](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)
  documents the `?stream=true` SSE route, input ordering, cancellation and
  event-stream behavior.
- [Sandbox lifecycle](https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle)
  states that session deletion does not stop provider compute and describes
  connection, reconnection, and cleanup ownership.
- [Codex 0.163.0 release](https://github.com/openai/codex/releases/tag/rust-v0.163.0)
  supplies the SHA-256-pinned Linux package used by the candidate Dockerfile.
