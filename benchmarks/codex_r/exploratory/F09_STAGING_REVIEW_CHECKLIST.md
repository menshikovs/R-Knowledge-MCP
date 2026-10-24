# F09 Future Staging Connectivity Review Checklist

This checklist is for a separately approved, zero-task staging check. Completing
it does not authorize a run. R01-A remains **NO-GO** and its authorizations are
not applicable to this harness.

Live mode is unconditionally disabled. The current solo-operator workflow is
described in [F09_SOLO_OPERATOR_GUIDE.md](F09_SOLO_OPERATOR_GUIDE.md). It trusts
explicit local operator confirmation and dashboard attestation, not a local
environment-variable match or provider-authenticated credential verification.
Separate users, a privileged helper and an independent reviewer are not required
under this threat model. Same-user malicious processes are outside its protection.
Review the implementation and execution wiring separately before any live use.

After the lease-release marker and inspector changes, the operator reported
three focused lease tests passed and 49 full F09 synthetic tests passed under
Ubuntu WSL2. Those results predate the two subprocess-based lease regressions.
An earlier Windows Codex sandbox attempt was blocked by `PermissionError:
[WinError 5]` while pytest accessed its fresh temporary directory; it did not
verify those subprocess regressions.

### Operator verification (2026-10-23)

The operator subsequently verified the regressions under Ubuntu WSL2: both
cross-process lease tests passed (**2 passed**), and the full F09 synthetic
suite completed with **51 passed, 1 non-blocking pytest configuration warning,
0 failures**. The 49-test result above is earlier evidence, before those two
subprocess regressions.

These results do not verify live TLS/WSS. Live mode remains disabled pending
verified staging-project identity and credential scope. They also do not provide
a power-loss durability guarantee. R01-A remains **NO-GO**.

Unresolved late workers or release markers must retain the lease and require
operator reconciliation. A valid hash chain cannot detect truncation at a
complete-record boundary without an external trusted anchor.

## Approval and isolation

- [ ] After separate live review, record interactive solo-operator approval for
  the exact source/configuration, fresh F09 attempt, explicit amount and short
  expiration. Confirm billing responsibility and best-effort spending control.
  An edited JSON record or earlier synthetic approval is not a new decision.
- [ ] Use the existing dedicated staging project and restricted credentials. Do not use
  R01-A authorization markers or production credentials.
- [ ] In the OpenAI Platform dashboard, verify the project identity and that the
  application credential belongs to the approved project and has only the
  session permissions needed for this zero-task check. Do not grant
  `api.responses.write` for this check. Verify the separate environment
  credential is restricted to executor connection. Confirm both credentials
  align to the approved organization, project and user/service account. The
  local project-ID environment variable is not proof of any of these facts.
- [ ] Bind the approved project ID in the non-secret request and dashboard
  attestation without displaying credentials. Environment-variable equality is
  not authorization or proof of credential identity.
- [ ] Use a reviewed WSL2 Linux host, persistent native ext4/xfs/btrfs owner-only
  state directory outside the repository (not `/mnt/c` or `/tmp`),
  repository, exclusive staging lease, pinned source commit and recorded
  executable/image digests. Confirm no stale lease or unresolved prior journal
  exists; do not remove one without investigating its run evidence.
- [ ] Confirm a restricted-egress proxy policy permits only reviewed OpenAI
  API and executor gateway destinations. Confirm no arbitrary direct egress,
  redirects, ambient proxy settings, credential mounts or evaluator/oracle
  mounts are available to the executor.
- [ ] Explicitly select a positive integer spend limit in USD cents and confirm
  billing-owner responsibility interactively before preparing a session. The
  local approval reference is created only after confirmation; there is no default
  limit and rejects missing, null, boolean, fractional, zero, negative, string,
  or unapproved limits before transport. It never rounds or converts. The code
  binds the local record and source but cannot defend against a malicious
  process running as the operator. Spend control is best-effort, not a guaranteed
  billing ceiling. The earlier 200-cent proposal is not automatically approved.
- [ ] Verify the current official Agents API schema, including the exact
  `spend_control.limit` integer-USD-cent type and enforcement semantics, before
  any live use. This repository has no local schema copy. Do not assume the
  limit makes the session zero-cost; record any remaining provider charges and
  exposure.

## Non-secret operator staging attestation template

Complete this record for review only. Do not enter secret values, key prefixes,
fingerprints, or redacted key strings. Use provider resource IDs and dashboard
labels only.

```text
Staging organization ID: <organization_id>
Approved staging project ID: <project_id>

Application credential
  Resource ID or dashboard label: <application_key_id_or_label>
  Owner type and ID (user or service account): <owner_type_and_id>
  Dashboard confirms api.agents.read: <yes/no>
  Dashboard confirms api.agents.write: <yes/no>
  Dashboard confirms api.responses.write is absent: <yes/no>
  Other permissions reviewed and approved for this zero-task check: <yes/no; list permission names only>

Executor environment credential
  Dashboard label: <environment_key_label>
  Owner type and ID (user or service account): <owner_type_and_id>
  Dashboard confirms only environment connection is permitted and all other permissions are None: <yes/no>

Identity alignment
  Both credentials are in the approved organization: <yes/no>
  Both credentials are in the approved project: <yes/no>
  Both credentials have the intended matching owner: <yes/no>

Dashboard review date (UTC): <YYYY-MM-DD>
Operator name or organization ID: <operator>
Reviewer name or organization ID (may be the same operator): <reviewer>

Local manual approval reference (only after confirmation): <approval_reference>
Billing owner identity and acknowledgment: <billing_owner_and_acknowledgment>
Approved spend_control.limit (positive integer USD cents): <integer_cents>

Authorized scope: exactly one staging session; zero task input, task submission,
  Responses inference, or follow-up session.
Approval expiration time (UTC): <YYYY-MM-DDTHH:MM:SSZ>

Attestation limitation: this is a dashboard/operator attestation. It is not
provider-authenticated verification that the runtime-loaded credentials are
the listed credentials or that their effective permissions match this record.
Completing this record does not authorize a check or unlock live mode.
```

Retain the completed record with the separate approval evidence. Keep live mode
disabled unless a separately reviewed implementation and approval process
establish the required credential and project checks.

## Proposed staging budget status

Operator-selected proposal; this is not approval to create a session.

- Project: `rkmcp-staging`.
- Scope: one future zero-task connectivity session.
- Maximum `spend_control.limit`: `200` integer USD cents ($2.00).
- Inference and Responses API use: prohibited.
- Billing-owner acknowledgment: pending authenticated acknowledgment.
- Project and credential ownership: pending final operator attestation.
- Live mode: disabled.
- R01-A: **NO-GO**.

No approval reference, signature, reviewer confirmation, or expiration date has
been supplied or recorded.

## Pre-run review

- [ ] Review this harness and selected tests at the approved source hash. Verify
  no code path imports or calls `R01ALifecycleController.run_one`,
  `ManagedAgentsClient.send_and_stream`, task submission, or Responses APIs.
- [ ] Verify the session body contains only the approved agent, fixed
  self-hosted environment configuration and externally approved positive
  integer-USD-cent `spend_control.limit`, with no task/input/instructions/tools.
- [ ] Verify TLS certificate validation is enabled, the API host is fixed,
  redirects are disabled, ambient proxy variables are ignored, and executor
  remote URLs pass the shared validator unchanged.
- [ ] Verify application credentials remain outside the executor, environment
  key is injected only into the reviewed executor startup boundary, and logs
  contain neither credentials, raw URLs, IDs, raw events nor exception text.
- [ ] Confirm create, connect and cleanup deadlines; the independent cleanup
  budget; bounded SSE bytes/events; and the monitored terminal event types.
- [ ] Agree on the operator procedure for unknown session state, stale lease,
  uncertain executor termination, failed journal fsync, or failed deletion.
  All such states abort and remain held for manual investigation; no retry.

## Observe and abort

- [ ] Start one check only. Observe only the fixed session-created result,
  sanitized event projection, executor startup, and matching
  `agent.session.environment.connected` event before the monotonic deadline.
- [ ] Abort on timeout, malformed/unexpected event, mismatched IDs, terminal
  failure event, redirect, TLS/proxy error, durability error, unexpected
  resource, or any indication of task submission or inference.
- [ ] Never accept a late connected event. Never retry ambiguous session
  creation. A thread that outlives a deadline is uncertain, not successful.
- [ ] Do not infer physical executor cleanup from session deletion. Verify the
  executor process/container and its network topology separately through the
  approved operator inspection path.

## Closeout evidence

- [ ] Verify executor termination and topology removal independently.
- [ ] Verify session deletion response and provider-side session state. If
  either is uncertain, retain the lease and escalate; do not start another run.
- [ ] Verify private audit file, journal hash chain, intent/outcome pairing,
  pending/complete release markers, fsync results and lease-release record.
  Treat these as process-crash evidence, not proof against power loss or
  storage-controller failure. Never remove an unresolved marker without review.
- [ ] Confirm provider billing/usage records after the approved window; record
  actual evidence and uncertainty. No task/inference means inference was not
  observed, not necessarily that provider cost was zero.
- [ ] Preserve audit artifacts, source/image hashes, exact command, UTC times,
  sanitized service responses, cleanup inventory and billing evidence. Do not
  edit historical R01-A records or consumed markers.
- [ ] Require a new independent review before considering any later R01-A
  decision. This connectivity check alone cannot authorize R01-A execution.
