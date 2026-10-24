# Managed Agents Connection Readiness and R01-A Launch Preparation

- Review date: 2026-10-24
- Repository: R-Knowledge-MCP
- HEAD: b24691c5a258d8599598c6070576070a4fb45434
- Branch: fix/r01a-deadline-durability

**Decision: NOT READY - code blocker.** F09 live mode remains intentionally unreachable because no reviewed trust path exists for staging project/credential identity or one-time authorization. R01-A remains **NO-GO**. This report is not authorization to create a session, submit a task, run inference, or launch the benchmark.

## Evidence and scope

This review inspected the relevant source, tests, existing readiness reports, and official OpenAI documentation. It did not access credential values, private credential files, historical private state, or authorization markers. No Docker, network probe, authenticated request, session, inference, task, authorization, or benchmark was run.

The working tree was already dirty: the F09 staging checklist was modified, and R01-A sprint/testing reports plus docs/reviews were untracked. These pre-existing changes were left untouched. Git status also reported nine inaccessible pytest directories; they were not opened or changed.

| Evidence | Status |
|---|---|
| Current source and test structure | Inspected at the stated HEAD. Source inspection is not a live compatibility test. |
| R01-A offline suite, 145 passed / 1 deselected | Operator-reported in the request; not independently rerun here. |
| F09 synthetic suite, 102 passed | Operator-reported in the request. The existing checklist records an earlier 51-pass result from 2026-10-23; the 102 result was not independently verified in this environment. |
| Five offline Docker checks | Earlier operator-reported evidence only; not run during this review. They do not prove OpenAI TLS/WSS registration. |
| Focused test, live R01-A gate | 1 passed, 1 existing pytest configuration warning; command and scope below. |
| Filesystem-backed F09 selection | Did not complete: pytest raised WinError 5 while enumerating a fresh basetemp directory. No valid aggregate result is claimed. |
| WSL availability | Read-only WSL enumeration returned E_ACCESSDENIED. No WSL test run is claimed. |

## A. Implemented controls

### R01-A live execution

- The lifecycle module defines LIVE_ZERO_TASK_CONNECTIVITY_VERIFIED as false and rejects a non-synthetic run before lease acquisition, authorization consumption, topology startup, or session creation: lifecycle.py:26, 312-345. The adapter's production controller also reports independent connectivity as false: adapter.py:1211-1298.
- Attempt-bound spend approval is required before the live gates, but the current adapter supports only the four closed attempt identities; all are marked historical and cannot be reused: adapter.py:61-70, 241-255, 588-607. The approval does not create a new attempt or authorization.
- ManagedAgentsClient validates a positive exact integer USD-cent cap before every session-create POST and includes it in the request: managed_agents.py:57-101, 205-231, 300-321. This is local validation; it does not establish provider-side enforcement or authorize a run.

### F09 zero-task harness

- The supported client surface is limited to session creation, SSE observation, and deletion. Its route allowlist permits only POST /v1/agents/sessions, GET for that session's event stream, and DELETE for that session: connectivity_harness.py:1115-1130.
- Session creation requires exactly agent, environment, and spend_control; the body contains no input, task, or event field. Agent tools must be empty. Spend approval is shape-checked as a positive integer plus reference and billing acknowledgment, but those fields have no trusted issuer here: connectivity_harness.py:306-318, 1131-1157, 1188-1225.
- The harness does not expose task submission or Responses methods. Its audit schema records zero task submissions and Responses calls; the synthetic test asserts no-input creation and the POST/GET/DELETE sequence: connectivity_harness.py:1434-1457; test_codex_connectivity_harness.py:304-319, 750-766. This establishes isolation of the supported harness path, not a process sandbox against arbitrary code using Python private attributes.
- The response's remote URL is checked by the shared executor URL contract and passed to the executor unchanged. The production Docker runtime validates the same contract before starting exec-server: connectivity_harness.py:1233-1239; docker_runtime.py:1031-1040, 1045-1062.
- The F09 control-plane HTTP client pins its API origin, verifies TLS, rejects redirects, and ignores ambient proxy settings. The source has no live transport injection: connectivity_harness.py:1069-1113. These are local client settings; they do not prove live TLS or WebSocket behavior.
- The restricted egress proxy permits CONNECT only to api.openai.com and codex-cloud-environments.chatgpt.com on port 443: egress_proxy.py:17, 30-51. Its TLS passthrough cannot inspect encrypted paths. The local fake-proxy probe is not an OpenAI endpoint test: docker_runtime.py:1623 onward.

### Durable evidence and cleanup

- The F09 journal writes intent before an operation, checks complete writes, fsyncs records, hash-chains them, and marks itself failed after an uncertain write: connectivity_harness.py:708-803. Audit persistence checks for a short write, fsyncs the file and directory, and occurs before lease release: connectivity_harness.py:1512-1533, 1939-1970.
- The lease uses a persistent cross-process gate and pending/complete release markers; unresolved markers block acquisition: connectivity_harness.py:641-705. Tests cover process-level and injected failures, but not power loss or storage hardware that falsely acknowledges flushes. The hash chain cannot detect truncation at a complete-record boundary without an external trusted anchor: F09_STAGING_REVIEW_CHECKLIST.md:27-33.
- The harness verifies local executor/topology cleanup and a matching session-deletion response before recording its cleanup state. However, OpenAI's delete confirmation means the session is removed from the public API; physical cleanup may continue asynchronously. Therefore cleanup_verified must not be read as proof of provider-side physical resource termination. See connectivity_harness.py:1905-1938 and the [Delete session reference](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/delete).

## B. Current Managed Agents contract and compatibility gaps

The current official [Create an agent session reference](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create) documents POST /agents/sessions, optional initial input for self-hosted non-streaming execution, and spend_control.limit in USD cents. Omission or null creates an unlimited session. Its response describes the configured limit and best-effort consumption; the reference does not establish that the amount is an absolute provider billing ceiling.

The official [self-hosted sandbox guide](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted) documents this flow:

1. The application creates a self-hosted session and receives its session ID and environment details.
2. The application opens the session event stream.
3. The self-hosted executor registers using an environment ID and restricted environment key, then connects outbound over WebSocket.
4. The app observes environment connection events. The guide says the environment needs both a connection and user input to start agent work; it does not guarantee that an input-free session or executor registration has zero cost.
5. The application stops its compute and deletes the session.

The documented outbound destinations are HTTPS api.openai.com for environment registration and WSS codex-cloud-environments.chatgpt.com for commands/results. The application key needs api.agents.read and api.agents.write for session operations; api.responses.write is required for model inference. A separate environment key should belong to the same organization, project, and session-owning user or service account, with other permissions set to None. The application key must remain outside the executor. These documented requirements are not verified for any runtime-loaded key in this repository.

The harness's expected API paths are POST /v1/agents/sessions, GET /v1/agents/sessions/{id}/events, and DELETE /v1/agents/sessions/{id}: connectivity_harness.py:1115-1128, 1246-1370. The official [stream-events method reference](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/subresources/events/methods/stream) and current Python SDK use the GET path without a query string and send `Accept: text/event-stream`; the events guide's raw `curl` example includes `?stream=true`. The harness now follows the method-reference/SDK route and retains the SSE Accept header. No live request was made to test service compatibility. The shared URL policy and fixed host allowlist agree with the documented executor hosts. No live request, TLS handshake, WSS upgrade, executor registration, connected event, or provider cleanup was observed. The synthetic proxy and mocked HTTP responses establish only local behavior.

The API's delete response confirms public session removal, not physical cleanup. The local harness cannot independently observe when provider-side cleanup finishes. This is an explicit limit of the evidence, not a reason to claim cleanup failed.

## C. Staging identity, authorization, and spending

The existing F09 checklist is explicit that live mode is disabled pending project and credential-scope verification; it also says its local project-ID environment variable is not proof of identity. Its proposed rkmcp-staging budget of 200 cents is not an approval, and billing-owner acknowledgment plus project/credential ownership attestation are pending: F09_STAGING_REVIEW_CHECKLIST.md:7-10, 35-69, 121-135.

The implementation independently enforces that block:

- Live StagingAgentsClient construction rejects injected transports, requires local project confirmation, and then rejects live mode because a reviewed provider identity/scope verifier is unavailable: connectivity_harness.py:1085-1096.
- require_trusted_staging_authorization always raises staging_authorization_issuer_unavailable after checking claim shape: connectivity_harness.py:289-303. The offline capability store is explicitly synthetic and does not establish an OS-separated trusted issuer: connectivity_harness.py:811 onward, 827-959.
- Thus a completed dashboard attestation or a self-declared JSON approval cannot unlock live mode. No trustworthy issuer, provider credential verifier, or live authorization-consumption path is configured.

The current official API reference says the session limit is optional, uses USD cents, and omission/null means unlimited; response consumption is described as best effort. Do not state that the proposed $2.00 is a hard maximum or that an input-free connection has zero cost. Obtain an explicit billing-owner approval and provider clarification of the charge/exposure semantics before any later authorization review.

### Historical R01-A finance

The four closed identities and recorded outcomes are:

| Historical identity | Repository evidence | Cost conclusion |
|---|---|---|
| R01-A/attempt-1 | Creation outcome unknown; no confirmed task or inference in the audit. | Provider session state and cost remain unknown. |
| R01-A/attempt-2 | Local lease conflict stopped execution before session creation. | No session or inference was observed for this attempt; do not convert that into a reconciled provider-cost claim. |
| R01-A/recovery-after-attempt-2 | HTTP 201 was recorded, then the returned URL failed local validation; a later inventory was operator-reported. | A session was created; no task/inference was observed; cost is unreconciled. |
| R01-A/final-continuation | One session was created; executor startup failed before a connection or task submission; exact Docker sub-operation is unknown. | No inference was observed; cost remains unreconciled. |

Sources: R01A_ROOT_CAUSE_AUDIT.md:94-101 and R01A_READINESS_SPRINT_2026-10-24.md:101-108. “No inference observed” is not evidence of zero provider charges.

The stored 1004 / 1004 / 1004 checkpoint is not a provider receipt. The root-cause record says spending was operator-entered and the ledger rejects the arithmetic 1004 - 1004 != 1004 and missing usage: R01A_ROOT_CAUSE_AUDIT.md:27-30. The ledger fields are opening_balance_cents, reported_spend_cents, and remaining_balance_cents, and it requires usage and reconciliation evidence: pilot.py:433-478. The values remain unreconciled; do not infer a $10.04 charge or zero charges.

Read-only reconciliation should be performed by an organization owner or authorized billing reviewer: match historical session IDs/request timestamps and project to provider session records and the organization Costs data, with a date range that includes the attempts in UTC. The official [Costs API reference](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs) supports time filtering and grouping/filtering by project, user, API key, API source, and line item, but returns time-bucketed aggregates rather than per-attempt proof. Reconcile those exports with available session usage/audit records and invoices. Preserve the original checkpoint and separately record any new reconciliation evidence. No billing endpoint was called here.

## D. Previous executor startup failure

The fourth historical attempt reached session creation but failed in Docker executor startup before a connected event; its exact failing Docker sub-operation is not established: R01A_ROOT_CAUSE_AUDIT.md:100-101, 135-176. Newer diagnostics classify recognized Docker failure classes but cannot reconstruct the old failure or recover removed logs.

The smallest offline diagnostic selection is the injected production-method integration coverage:
- tests/test_codex_executor_contract_integration.py::test_http201_actual_runtime_failure_is_temporally_correct_and_private
- tests/test_codex_executor_contract_integration.py::test_primary_error_survives_cleanup_failure_and_blocks_export
- tests/test_codex_executor_contract_integration.py::test_shared_policy_traverses_actual_executor_startup_unchanged

These use production executor logic with synthetic HTTP and injected subprocess boundaries. They can check phase classification and cleanup evidence, not the historical cause or real remote registration. Docker-marked tests were not run in this review.

## E. Minimal future zero-task protocol

Every live step below is **NOT EXECUTED**. It requires a later, separate authorization and review; none is authorized by this report.

1. Review an exact immutable source commit, executable/image digests, the F09 code and zero-task test evidence.
2. Obtain a non-secret Platform attestation: organization/project IDs; application and environment key resource labels/IDs; their owners; application Agents read/write scope with Responses permission absent for the zero-task check; environment connection-only scope; and matching organization, project, and session owner. Never record key values, prefixes, hashes, or fingerprints.
3. Obtain billing-owner acknowledgment, an explicit positive-integer USD-cent limit, a short expiration and one-session/zero-task scope. Resolve whether the provider limit is a hard cap or only a configured limit with best-effort consumption. The present 200-cent proposal is pending and is not authorization.
4. Implement and independently review the missing trusted issuer and provider identity/scope boundary. The current live client and authorization validator reject before transport; do not bypass them with an environment variable or synthetic claims.
5. On a reviewed POSIX host and protected native Linux filesystem, verify no unresolved F09 lease marker exists. Durably consume a new F09-only one-time capability before the network step. Do not use R01-A authorization or state.
6. Under a separately approved run, create one self-hosted session with no input, no task/event fields, empty tools, and the approved spend_control.limit. Validate the returned identity and remote URL. Open the event stream, start the reviewed executor with only the restricted environment key, and accept only the matching connected event before the bounded deadline.
7. Submit no task and call no Responses API. On success or any failure, stop the executor, clean topology under the shared deadline, delete the known session, require the matching deletion confirmation, persist sanitized audit/outcomes durably, and retain the lease on any uncertainty. Then inspect provider records for billed use.

A deleted response confirms removal from the public API; it does not prove provider-side physical cleanup is finished. Journal fsync and process-restart tests do not guarantee power-loss durability.

## F. Stop conditions

Stop without retry for missing, expired, reused, mismatched, malformed, or unauthenticated approval; unverified project/key ownership or scope; missing/unclear spend approval; ambiguous session creation; invalid session identity/URL; TLS/proxy/WSS or executor startup failure; late/mismatched/failed connection event; any task or inference path; cleanup, journal, audit, fsync, or lease uncertainty; or a remaining Docker resource. Preserve uncertain state for operator reconciliation.

## Verification run here

The following single gate test completed:

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'; .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_codex_managed_agents_lifecycle.py::test_live_session_path_blocks_without_independent_connectivity_evidence
~~~

Result: **1 passed, 1 non-blocking PytestConfigWarning** (unknown existing cache_dir option). It verifies the live controller's fixed-false gate in this environment.

A focused selection covering the following tests was attempted using a newly created %TEMP% basetemp:

- test_public_surface_cannot_submit_tasks_or_responses_and_create_has_no_input
- test_missing_or_invalid_spend_control_fails_before_transport
- test_late_connected_event_is_not_accepted
- test_ambiguous_create_timeout_is_not_retried_and_retains_lease
- test_saved_audit_redacts_credentials_ids_remote_url_and_exception_text
- test_fixed_route_client_rejects_task_and_responses_paths_before_transport
- test_live_session_path_blocks_without_independent_connectivity_evidence

A filesystem write/read/delete probe succeeded, but pytest did not complete: it emitted setup/test errors and then failed in its session-finish hook while scanning the basetemp with PermissionError: [WinError 5] Access is denied. No aggregate test count or pass is claimed for that selection. Read-only wsl.exe --list --quiet returned Wsl/EnumerateDistros/Service/E_ACCESSDENIED, so Ubuntu WSL2 tests were unavailable to this review.

The selected F09 tests use synthetic IDs/secrets and mocked HTTPX transport; the selected executor diagnostic tests use injected subprocess boundaries. No live API, Docker, credential, session, or inference behavior was exercised.

## Shortest next action

Have the staging project owner and billing owner complete the existing non-secret F09 attestation with project/key resource labels, owners and permission scopes, a genuine billing acknowledgment, approved integer limit, expiration, and explicit zero-task scope. Record that this dashboard evidence does not verify runtime-loaded key identity and that live mode remains disabled. That review evidence can specify the missing verifier/issuer work; it does not authorize a connectivity attempt.

**R01-A remains NO-GO. F09 live connectivity remains disabled.**

