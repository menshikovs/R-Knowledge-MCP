# Single-trial execution adapter status

## Status: real execution intentionally blocked

`adapter.py` is a readiness and offline lifecycle harness, not a secure Codex
launcher. It prepares one assigned trial context, validates a short-lived
single-row authorization record, maintains an exclusive cross-process lease,
parses bounded/redacted JSONL, and exercises a synthetic timeout path. It never
starts Codex, authenticates, requests a model, or writes benchmark results.
`run-one` always fails closed while the secure backend gate is unverified.

The host Codex CLI is not a safe substitute: it uses the operator's host
authentication context and the available interface does not establish that all
agent filesystem operations stay inside the candidate workspace. Docker is not
available in the current development environment. No separately audited
isolated Codex agent runtime, trusted credential broker, model-only egress
policy, or route from that runtime to the recording MCP gateway is provisioned.
The benchmark's R image and tool inventory declarations are not evidence that
an agent actually ran with those controls. Account access to `gpt-6-luna` with
the required tools is also unverified; verifying it with a real turn would be a
paid request and has not been authorized.

These are implementation blockers, not configuration fields that can be set to
`true`. Until an external execution backend can provide independently
inspectable evidence for every gate, no paid trial can run. A future backend
must demonstrate, before enabling `run-one`:

- Disposable agent/container isolation and enforced denial of evaluator/oracle
  paths, including a negative access probe.
- A model credential broker that does not expose the credential to candidate
  code, plus enforced network policy allowing only the model endpoint and the
  trusted recording gateway when required.
- The actual agent's effective tool inventory (A=0, B=15, C=20), gateway
  allowlist/audit, frozen R image identity, and verified account/model access.
- Process-tree termination, workspace export and cleanup evidence, with a
  fail-closed recovery path that retains the exclusive lease if cleanup is
  uncertain.
- An explicit fresh authorization bound to one trial row and a checkpoint
  before any next row. Existing balance checkpoints remain best-effort; delayed
  accounting can exceed displayed prepaid credits.

## Offline use

From the repository root:

```sh
python benchmarks/codex_r/exploratory/adapter.py preflight --trial R01-A
python benchmarks/codex_r/exploratory/adapter.py prepare --task R01 \
  --workspace /absolute/path/outside/repository/candidate-R01
python benchmarks/codex_r/exploratory/adapter.py dry-run
```

The trial ID must be one of the nine rows in `pilot.py`. `preflight` writes a
machine-readable report and exits with status 2 while gates are blocked.
`prepare` exports only reviewed public task material and explicitly reports
`boundary_verified: false`; it is not container isolation. `dry-run` launches
only a fixed local sleep probe to test timeout cleanup, never Codex. A Windows
sandbox that denies child-process creation can verify root-process timeout but
cannot verify descendant cleanup; the report records that limitation and the
focused test skips only its descendant assertion.

Authorization record helpers exist to test exact-row scope, expiry, and replay
protection, but creating such a record does not grant this adapter execution
capability. Do not treat it as permission to bypass the blocked preflight.
There is no usable command to launch even one real trial at this stage.

The original strict 72-trial benchmark, its manifests, schemas, score path, and
security requirements are unchanged. Exploratory pilot data remains separate.
