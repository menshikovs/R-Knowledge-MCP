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
`codex-cloud-environments.chatgpt.com`. The current candidate uses
`network=none`, so it cannot register or connect. A plain hostname CONNECT
allowlist does not enforce the required API paths, and the relay URL is signed
and returned dynamically. This branch does not implement a TLS-terminating,
path-aware trusted proxy or a tested relay broker. Enabling a broad outbound
route would not meet the protocol's egress requirement. No environment key is
mounted, no application key is passed to Docker, and no API session was
created.

`managed_agents.py` contains the fixed R01-A/GPT-6 Luna/medium session request,
controller-side HTTPX calls for session creation, event submission/streaming,
cancellation and deletion, response/event byte limits, redirect rejection,
fixed official URL checks, idempotent task submission and event secret
redaction. Tests use `httpx.MockTransport` and synthetic values only. They do
not establish API-account model access. Session creation and turn execution
were never called. Existing adapter `run-one` stays fail-closed; the full
session lifecycle is not connected to artifact sealing, scoring, the balance
checkpoint, or the required egress broker.

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

- A trusted, path-aware endpoint broker and separately verified outbound WSS
  relay are not implemented. The candidate currently has no network.
- No documented restricted executor environment key was supplied to the
  container, and no Managed Agents session/environment was created.
- Account-level access to `gpt-6-luna` and the resolved live `medium` setting
  remain unverified; do not verify by creating a session during ordinary CI.
- The executor process is tested only as a local loopback service. Its remote
  registration and WebSocket lifecycle, 900-second agent cancellation, API
  session deletion and cleanup combination are not verified.
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
  documents `codex exec-server`, the registration and WebSocket hosts, and the
  restricted environment-key arrangement.
- [Sandbox security](https://developers.openai.com/api/docs/guides/agents-api/environments/security)
  says agent-generated code can read environment credentials and that the
  application API key must stay outside the environment.
- [MCP connections](https://developers.openai.com/api/docs/guides/agents-api/tools/mcp)
  documents environment-origin MCP connections and `allowed_tools`.
- [Session events](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)
  documents input, cancellation and event-stream behavior.
- [Codex 0.163.0 release](https://github.com/openai/codex/releases/tag/rust-v0.163.0)
  supplies the SHA-256-pinned Linux package used by the candidate Dockerfile.
