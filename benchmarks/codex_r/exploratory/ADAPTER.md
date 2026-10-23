# Single-trial execution adapter status

## Status: offline Docker boundary verified; agent execution blocked

`adapter.py` and `docker_runtime.py` prepare a readiness report and run fixed
security probes against the frozen R image. The Docker probe has been executed
against Docker Desktop's Linux engine and verifies the actual container
configuration and negative paths. It does not install or start Codex,
authenticate, request a model, or write benchmark results. It records isolation
only for the fixed probe, never for an agent. `run-one` always fails closed.

The host Codex CLI is not a safe substitute: it uses the operator's host
authentication context and does not prove that agent filesystem operations
stay inside the candidate workspace. The tested candidate container has no
network, no Codex binary, no model proxy, and no MCP gateway. Consequently the
probe can prove that arbitrary internet and model-proxy access are denied, but
it cannot establish model connectivity or actual Codex tool discovery. The
R01-A execution gate remains blocked. Account access to `gpt-6-luna` is also
unverified; checking it with a real turn would be a paid request and is not part
of this task.

The frozen image is pinned by local image ID at probe time. It carries the
reviewed `renv.lock` byte-for-byte and starts as UID 65534. The disposable
container uses only the exact public R01 workspace bind mount, an internal
`none` network, a read-only root, dropped capabilities, no-new-privileges,
fixed CPU/memory/PID limits, and bounded tmpfs mounts. The fixed probe checks
that expected oracle/repository/home/socket/other-trial paths and credential
environment variables are absent, direct internet is unreachable, and the
R01-A model-proxy route is unavailable. It removes its container and verifies
that Docker no longer lists it. A separate timeout probe starts a child process
inside a no-network container and force-removes the whole container after the
short test deadline.

These checks are not agent isolation evidence: the existing frozen image does
not include Codex. These are blockers, not fields that can be set to `true`.
Before enabling an actual model run, a follow-up implementation must provide:

- Disposable agent/container isolation and enforced denial of evaluator/oracle
  paths, including a negative access probe.
- A trusted Responses-API reverse proxy on a separate uplink network, with the
  real API key available only to that proxy. The candidate network must be an
  internal Docker bridge with no default route; the proxy must accept only the
  selected model/API path and must never operate as a general HTTP or CONNECT
  proxy. The candidate must receive no upstream key. Official Codex docs
  describe this trusted-proxy pattern for self-hosted sandboxes and warn that
  credentials injected into the agent environment are readable by generated
  code.
- A Codex-enabled candidate image and configuration bound to
  `gpt-6-luna`/`medium`, with the proxy URL but no credentials. Its effective
  MCP tool list must be read from a real agent session before timing.
- The actual agent's effective tool inventory (A=0, B=15, C=20), gateway
  allowlist/audit, frozen R image identity, and verified account/model access.
  For B/C, a trusted gateway container must join the internal candidate network
  while the production MCP service remains on a separate upstream network; the
  candidate must have no route to that service.
- Process-tree termination, workspace export and cleanup evidence, with a
  fail-closed recovery path that retains the exclusive lease if cleanup is
  uncertain.
- An explicit fresh authorization bound to one trial row and a checkpoint
  before any next row. Existing balance checkpoints remain best-effort; delayed
  accounting can exceed displayed prepaid credits.

## Offline use

From the repository root, with Docker Desktop's WSL2 integration enabled for
Ubuntu and the existing frozen image available locally:

```sh
python benchmarks/codex_r/exploratory/adapter.py preflight --trial R01-A
python benchmarks/codex_r/exploratory/adapter.py prepare --task R01 \
  --workspace /absolute/path/outside/repository/candidate-R01
python benchmarks/codex_r/exploratory/adapter.py dry-run
```

Create an exact public R01 workspace outside the evaluator repository, then use
the image's immutable local ID (not its mutable tag) for the real Docker probes:

```sh
IMAGE_ID=$(docker image inspect codex-r-benchmark:pilot --format '{{.Id}}')
python benchmarks/codex_r/exploratory/adapter.py prepare --task R01 \
  --workspace /absolute/outside/repository/candidate-R01-A
python benchmarks/codex_r/exploratory/adapter.py docker-isolation --trial R01-A \
  --image "$IMAGE_ID" --workspace /absolute/outside/repository/candidate-R01-A
python benchmarks/codex_r/exploratory/adapter.py docker-timeout-probe \
  --image "$IMAGE_ID" --timeout-seconds 1
```

Real container-only tests are marked `docker`; set
`R_KNOWLEDGE_BENCH_IMAGE_ID` to the immutable image ID and run
`pytest -m docker`. They make no model requests. Ordinary tests can run without
Docker and skip only those integration checks.

The trial ID must be one of the nine rows in `pilot.py`. `preflight` writes a
machine-readable report and exits with status 2 while gates are blocked.
`prepare` exports only reviewed public task material and explicitly reports
`boundary_verified: false`; it is not container isolation. `dry-run` launches
only a fixed local sleep probe to test timeout cleanup, never Codex. A Windows
sandbox that denies child-process creation can verify root-process timeout but
cannot verify descendant cleanup; the report records that limitation and the
focused test skips only its descendant assertion.

Authorization record helpers and the balance-aware ledger still test exact-row
scope, expiry, replay protection, and post-trial checkpoints. Creating an
authorization record does not grant this adapter execution capability. Do not
treat it as permission to bypass the blocked preflight. There is no usable
command to launch even one real trial at this stage.

The original strict 72-trial benchmark, its manifests, schemas, score path, and
security requirements are unchanged. Exploratory pilot data remains separate.

## Reviewed Codex credential documentation

- [OpenAI sandbox security](https://developers.openai.com/api/docs/guides/agents-api/environments/security)
  says agent-generated code can read its environment credentials and recommends
  keeping the application key outside a self-hosted environment behind a trusted
  proxy/server.
- [Codex authentication](https://learn.chatgpt.com/docs/auth) and
  [advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
  document custom model providers and compatible Responses API gateways. This
  branch does not yet implement that gateway or configure a live model route.
