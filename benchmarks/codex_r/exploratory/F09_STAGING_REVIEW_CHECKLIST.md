# F09 Future Staging Connectivity Review Checklist

This checklist is for a separately approved, zero-task staging check. Completing
it does not authorize a run. R01-A remains **NO-GO** and its authorizations are
not applicable to this harness.

Live mode is currently disabled: provider project identity and credential scope
cannot yet be verified by a reviewed implementation. Complete that implementation
and independent offline review before this checklist can be used for approval.
A local environment-variable match is insufficient.

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

- [ ] Obtain separate written approval naming the staging project, operator,
  exact time window, maximum duration, and abort owner.
- [ ] Use a dedicated staging project and newly issued credentials. Do not use
  R01-A authorization markers or production credentials.
- [ ] In the OpenAI Platform dashboard, verify the project identity and that the
  application credential belongs to the approved project and has only the
  session permissions needed for this zero-task check. Do not grant
  `api.responses.write` for this check. Verify the separate environment
  credential is restricted to executor connection. Confirm both credentials
  align to the approved organization, project and user/service account. The
  local project-ID environment variable is not proof of any of these facts.
- [ ] Set `RKMCP_CONNECTIVITY_STAGING_PROJECT_ID` to the approved project ID and
  independently verify the value without displaying credentials.
- [ ] Use a reviewed POSIX host, owner-only state directory outside the
  repository, exclusive staging lease, pinned source commit and recorded
  executable/image digests. Confirm no stale lease or unresolved prior journal
  exists; do not remove one without investigating its run evidence.
- [ ] Confirm a restricted-egress proxy policy permits only reviewed OpenAI
  API and executor gateway destinations. Confirm no arbitrary direct egress,
  redirects, ambient proxy settings, credential mounts or evaluator/oracle
  mounts are available to the executor.
- [ ] Obtain an externally approved positive integer spend limit in USD cents
  and written billing-owner acknowledgment before preparing a session. Supply
  the approval reference and acknowledgment to the harness; it has no default
  limit and rejects missing, null, boolean, fractional, zero, negative, string,
  or unapproved limits before transport. It never rounds or converts. The code
  checks the approval record's shape but does not authenticate the approver or
  reference.
- [ ] Verify the current official Agents API schema, including the exact
  `spend_control.limit` integer-USD-cent type and enforcement semantics, before
  any live use. This repository has no local schema copy. Do not assume the
  limit makes the session zero-cost; record any remaining provider charges and
  exposure.

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
