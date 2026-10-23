# Single-trial Codex runtime integration

## Status: Codex executor is containerized and starts offline; paid execution remains blocked

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
API-account model access. Session creation and turn execution were never
called. Existing adapter `run-one` stays fail-closed; session lifecycle,
artifact sealing, scoring and balance checkpoint are not wired into an
end-to-end runner.

Authorization records now require and bind the immutable candidate image ID
and a fingerprint of the Codex Docker recipe/runtime policy, in addition to the
task inputs, workspace, model, reasoning, and controller version. This prevents
reusing a one-time authorization after changing the reviewed runtime. It does
not make the current blocked preflight pass or authorize a live trial.

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
choices, but does not document a supported proxy/path-policy interface.

Consequently this change does not invent a proxy setting, terminate TLS, or
allow unrestricted CONNECT. A TCP/TLS pass-through can constrain destination
hosts but cannot inspect encrypted HTTP paths. TLS termination would require
the candidate to trust an interception certificate and would violate the
normal certificate-validation boundary. The candidate is confined to the
internal isolated-gateway network; the only outbound path is the fixed-host
CONNECT proxy. Local Docker probes verify negative controls and a synthetic
CONNECT, not a live relay test.

The managed-session API methods are still only tested against synthetic
HTTPX responses. No session has been created, so the actual `remote_url`,
registered executor handshake, API key scope/revocation, model/account access,
or resolved session settings are not observed. The code does not claim that a
mock event stream proves executor protocol compatibility.

The implemented pieces are not wired into a full trial lifecycle: exclusive
lease/authorization consumption, executor connection, task submission and
cancellation, verified agent termination, allowlisted artifact handoff,
scorer execution, real usage/spending reconciliation, and the operator
checkpoint are not joined in an end-to-end runner. Offline probes are labeled
as tests and never produce trial records. The original scorer and strict
benchmark files remain untouched.

Condition A's generated Agents API configuration has zero MCP tools. Runtime
tool discovery is still unverified because it would require a real session.
Conditions B/C are intentionally rejected by the config builder: the existing
recording gateway is stdio-only and has no authenticated candidate-facing HTTP
route. Do not claim the 15/20 effective tool inventories have been verified.

## Rebuild and offline checks

The frozen R image is a local benchmark artifact, not a public registry image.
Docker BuildKit tried to pull its digest from Docker Hub, so use Docker
Desktop's legacy builder while this local-only base is in use:

```powershell
$env:DOCKER_BUILDKIT = "0"
docker build --no-cache `
  -f benchmarks/codex_r/runtime/candidate.Dockerfile `
  -t rkmcp-codex-runtime:codex-0.163.0 .
docker image inspect rkmcp-codex-runtime:codex-0.163.0 --format '{{.Id}}'
```

Prepare a fresh public R01 workspace outside the evaluator repository, then
run the actual binary startup/security check with the immutable local candidate
image ID:

```powershell
python benchmarks/codex_r/exploratory/adapter.py prepare `
  --task R01 --workspace C:\tmp\public-R01-A
python benchmarks/codex_r/exploratory/adapter.py codex-runtime-probe `
  --image sha256:LOCAL_CODEX_CANDIDATE_IMAGE_ID `
  --workspace C:\tmp\public-R01-A --timeout-seconds 5
```

The probe is explicitly an offline binary-startup record, not a trial. It does
not create an Agents session, use `CODEX_API_KEY`, access model endpoints or
claim effective tool discovery. `docker-runtime-probe` tests against the frozen
R image and the pinned Codex image are marked `docker` and require
`R_KNOWLEDGE_BENCH_IMAGE_ID` and `R_KNOWLEDGE_CODEX_IMAGE_ID` respectively.
No real API key is read by CI tests.

The task workspace created for the local test was removed after verification.
The original strict benchmark, score importer and oracle were not modified.

## Exact blockers before a real R01-A turn

- A path-aware endpoint broker and separately verified outbound WSS relay are
  not implemented. The CONNECT proxy enforces exact hosts and port 443 only;
  it cannot inspect TLS-encrypted API paths or dynamic signed relay targets.
  Live WSS through this proxy remains unverified.
- No documented restricted executor environment key was supplied to the
  container, and no Managed Agents session/environment was created.
- Account-level access to `gpt-6-luna` and the resolved live `medium` setting
  remain unverified; do not verify by creating a session during ordinary CI.
- The executor process is tested only as a local loopback service. Its remote
  registration and WebSocket lifecycle, 900-second agent cancellation, API
  session deletion and cleanup combination are not verified.
- Session deletion only removes the public API session; official lifecycle
  guidance says provider compute must be stopped separately. A future runner
  must verify Docker container termination independently before artifact export.
- Artifact export after termination, sealed scoring handoff, and the final
  balance/usage/correctness checkpoint are not wired to an agent turn.
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
