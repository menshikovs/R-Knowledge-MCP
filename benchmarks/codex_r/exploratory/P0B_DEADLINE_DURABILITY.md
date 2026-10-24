# P0-B: phase deadlines and crash-durable evidence

Status: **NO-GO for live R01-A execution**. Baseline:
`53cf4f2904084ea648f6fb92fc6383e8363c648b` (P0-A). Branch:
`fix/r01a-deadline-durability`.

This package addresses F05/F08 offline. It creates no new attempt identity,
authorization, recovery permission or launch procedure. All four historical
attempts remain closed. The root-cause audit and P0-A evidence are unchanged.
Production MCP, the strict benchmark, R01 inputs, scorer/oracle, Luna/medium
configuration, zero-MCP policy, reviewed URL policy and egress rules are unchanged.

## Ownership and transitions

`lifecycle_safety.py` owns monotonic clocks, sticky cancellation, bounded caller
waiting, durable writes and journal inspection. The production lifecycle owns
phase transitions; the existing HTTP client and injected Docker command boundary
inherit the same flow and remaining budget. No timing override or bypass is
exposed by the CLI. Python injection permits deterministic offline verification.

The forward path is preparation -> session creation -> SSE/startup -> executor
connection -> task. A transition must occur before the current deadline expires.
Task submission is a child budget within the task's 900 seconds. Each `next()`
on the actual SSE generator is watched independently of whether a line arrives.
Slow headers, stalled commands and silent streams therefore cannot indefinitely
block the controller's caller. Checks run again after an operation returns and
after intent fsync, before a task or another significant action can start.

Cancellation and teardown have a separate shared deadline. The existing runtime
still force-removes the candidate and verifies absence; its removal mutex prevents
normal cleanup and deadline cleanup racing into conflicting removal calls. A
subprocess timeout alone never certifies removal. Disposable version containers
now have owned names and explicit removal/absence checks on failed startup.

| Phase / owner | Maximum seconds | Accounting |
| --- | ---: | --- |
| Preparation / adapter and lifecycle | 60 | Context/auth validation, deferred image/workspace gates, lease, markers and topology share the original preparation budget. |
| Session creation / lifecycle | 30 | Exactly one create attempt; individual HTTP I/O has a 15-second child cap. |
| SSE initialization and startup / lifecycle | 45 | Starts before GET headers and executor startup; Docker commands inherit remaining time, normally capped at 20 seconds. |
| Executor connection / lifecycle | 60 | Starts after verified process startup; process readiness does not imply connection. |
| Task / lifecycle | 900 | Starts at observed connection, includes task submission; never a whole-controller lifetime claim. |
| Task POST / client | 15 | Child of the remaining task budget; uncertain POST is not retried. |
| Teardown / shared safety flow | 60 | Fresh once, never renewed per cleanup: cancellation <=10, removal <=20, deletion <=15, client close <=5, topology <=15, each clipped to remaining time. |
| Artifact export and scorer handoff / lifecycle | 120 | Separate postprocess flow after verified candidate termination/cleanup; scorer implementation unchanged. |
| Human checkpoint review / controller | 300 | Separate flow; timeout records unavailable usage/spending/balance and unreconciled stop. |
| Canonical audit and lease release / lifecycle | 60 | Separate evidence flow, shared by persistence and release. |

HTTP connect/write/pool limits also use remaining time. With lifecycle safety,
the SSE read timeout can span the task, while the controller watchdog enforces
the current shorter startup/connection deadline. The old stream-wide 900-second
clock is used only for standalone client calls without a lifecycle safety object;
it cannot shorten the separately budgeted controller task.

Python cannot forcibly kill a blocked thread. A timed-out caller sets sticky
cancellation; later gates reject additional work. An uncooperative already-entered
I/O operation can nevertheless finish later. This is recorded as
`unfinished_operations_uncertain`, prevents cleanup certification and retains the
lease. No claim is made that a timed-out POST was cancelled at the provider.
Daemon workers may retain the journal descriptor for late outcomes until process
exit. Hung host threads, storage calls and Docker daemon behavior require further
operational validation; this is not a hard process-wide real-time guarantee.

## Evidence schema and ordering

Each existing attempt gets a new exclusive owner-private journal beneath
`STATE/lifecycle-journals/`, using its fixed existing identity as the basename.
No writer API reopens, repairs or resumes a journal. Existing files block creation.
Production writes use append-only semantics (`O_APPEND`), one serialized write
per JSONL record, file fsync after every transition, and directory fsync for new
directory entries. Newly created consumed-marker directories are also synced.
Private JSON writes flush/fsync the file and its parent; partial files are retained,
never deleted as rollback. Trial and authorization markers remain exclusive and
separate, with no rollback if the second write fails.

The closed version-1 schema contains only:

| Field | Meaning |
| --- | --- |
| `schema_version`, `record_type`, `synthetic` | Version and explicit non-benchmark classification. |
| `attempt_id` | One of the four already established identities, never caller-defined new identities. |
| `seq`, `previous_sha256` | Strict increasing sequence and SHA-256 of the preceding exact LF-terminated record. |
| `operation`, `event`, `intent_seq` | Reviewed operation enum, intent/outcome, paired intent sequence. |
| `code`, `cleanup_code` | Closed safe primary/cleanup classifications; unknown text becomes `operation_failed`. |

Covered operations: authorization consumption, each consumed-marker write,
topology startup, session creation, version probe, executor creation/start, task
submission, cancellation, executor termination, session deletion, topology cleanup,
final audit persistence and lease release. The production controller/client/runtime
are instrumented; nested wrappers do not duplicate a single operation's intent.
No API key, executor key, nonce, remote URL, session response, argv, environment,
stderr or unrestricted exception text can be a journal field. P0-A's separate
sanitized HTTP/runtime diagnostics remain in the audit. Cleanup failure codes do
not replace the primary failure. A false cleanup result is explicitly unverified.

Intent is fsynced before an external create/start/task action. Failed evidence
blocks these actions. If storage fails after a candidate has started, narrowly
allowlisted destructive cleanup may still be attempted without durable evidence;
this exception never permits a new session/task and never certifies cleanup.

On POSIX, journal files are 0600 and the journal directory 0700; pre-existing
nonprivate journal directories are rejected. Native Windows synthetic tests are
supported, but live journaling is blocked there: this implementation cannot prove
owner-only ACLs or directory-fsync durability. Operational use needs the reviewed
POSIX/WSL filesystem and storage guarantees verified separately.

The canonical sanitized audit is an exclusive sibling `*.audit.json`. Its writer
must return after file and directory sync, followed by the journal's successful
`audit_persist` outcome, before lease release begins. Audit presence alone is not
proof of committed persistence. New cleanup verification additionally requires a
valid complete journal with successful audit and lease-release outcomes. Legacy
audits retain their existing read-only handling and are never migrated in place.

Sequence/hash checks detect torn records, invalid transitions and many accidental
edits; they are not signatures or tamper-proof storage. Complete-tail deletion or
a malicious state-directory owner is outside this evidence integrity guarantee.
Process-crash tests do **not** prove power-loss durability. File/directory fsync
ordering depends on filesystem, mount, kernel and physical persistence behavior;
no Windows or WSL power-loss experiment was performed.

## Read-only recovery truth table

The only new CLI operation is inspection, not repair or execution:

```bash
python benchmarks/codex_r/exploratory/adapter.py inspect-journal \
  --journal /private/existing-state/lifecycle-journals/EXISTING-ATTEMPT.jsonl
```

This command makes no Docker/API calls and never changes a file. Its bounded
output is explicitly not a benchmark result. It always reports provider session
state and spending as unknown, never authorizes recovery/replay and never alone
certifies cleanup. Missing/invalid input fails inspection rather than implying
that no attempt occurred.

| Durable evidence after interruption | Interpretation and permitted default action |
| --- | --- |
| Empty journal / crash before intent | No outcome established; preserve lock/markers/history; no automatic replay. |
| Create intent without outcome | Remote creation may have occurred; provider state unknown; no second create. |
| Task intent without outcome | Submission may have occurred; no resend or inference conclusion. |
| One consumed marker, other absent/partial | Consumed/uncertain transaction; existing trial marker or malformed auth marker blocks reuse. |
| Complete outcome, no final audit | Operation evidence exists; attempt did not disappear; no automatic recovery. |
| Torn final line / short write / failed fsync | Preserve bytes; inspect valid prefix and flag uncertainty; no append/resume/repair. |
| Missing removal/deletion/topology proof | Cleanup unverified, export blocked and owned lease retained. |
| Failed canonical audit serialization | Preserve partial audit; journal outcome is failure/missing; lease retained. |
| Audit written, audit outcome missing | File alone is insufficient; verification remains blocked. |
| Audit committed, lease-release outcome missing | Release/durability uncertain, even if lock already disappeared; markers/journal still prevent replay. |
| Foreign or stale lock | Never clear or adopt it automatically; preserve original bytes. |
| Fully completed journal | Evidence of local transitions, not independent provider inventory, spending proof or new execution permission. |

An operator would need a separately reviewed and explicitly authorized forensic
procedure for independent session inventory, owned Docker resource inspection,
spending reconciliation and any stale-lease action. None is performed or
automatically enabled here. No historical authorization or attempt is reopened.

## Failure injection and security regression evidence

Tests use the production controller, HTTPX client, runtime startup/policy methods,
marker writer and serializer. Only API transport, subprocess execution, clocks,
operator review and scoring dependencies are synthetic. The new module denies
network access and permits real subprocesses only for three fixed local Python
crash scripts. Child controller tests also explicitly deny real subprocess/network
calls. Synthetic fixed IDs/markers are confined to temporary private directories.
No live CLI authorization or launch command was invoked.

| Failure matrix | Offline assertion |
| --- | --- |
| Preparation, slow creation, startup, late SSE headers, delayed connection, silent stream | Phase-specific expiry; no new task; remote uncertainty retained. |
| Task POST timeout, missing terminal event, 900-second task expiry | At-most-once submission; unknown POST result; candidate removal remains required. |
| Startup+connection followed by a long task | 77 seconds before task plus 850 task seconds does not expire the task; independent budgets. |
| Deadline spent during intent fsync | No task POST after the deadline gate. |
| Cancellation/removal timeout, deletion/topology failure | Primary failure survives; missing cleanup proof cannot certify cleanup. |
| Cleanup/deadline race | Serialized verified removal; one injected remove call. |
| Human review timeout | Separate review expiry, null spending/usage, unreconciled ledger and stopped progression. |
| Crash around critical transitions | 15 operations x 4 boundaries x 2 matrices = 120 actual local Python crash children: journal primitive and production controller. Before/after each intent/outcome boundary; read-only inspection and no replay. |
| Crash between consumed-marker writes | One additional local Python child uses production consumption; first marker preserved, second absent, reuse rejected. |
| Short write, fsync failure, disk full, truncated record | Preserve partial evidence; no create/task after failed intent. |
| Disk full after executor startup | No task; destructive removal still attempted; no cleanup certification. |
| Failed/partial final audit, crash before serialization, stale foreign lease | Exclusive preserved evidence, no silent clearing or rewrite. |
| Confidentiality / strict import | Secret-shaped values rejected or projected to codes; persisted synthetic records and inspection reports rejected as real benchmark results. |
| P0-A URL/runtime/credential regressions | Shared URL allowlist, byte-preserving forwarding, primary/secondary safe diagnostics and unknown session states preserved. |

## Commands and exact local results

Run on Windows in the existing project virtualenv, with pytest temporary roots
outside the evaluator repository. These are the explicitly selected offline suites;
the existing egress unit tests use only loopback synthetic servers.

```powershell
ruff check .
ruff format --check .
$p0bTemp = Join-Path $env:TEMP 'r01a-p0b-final-complete'
& .\.venv\Scripts\python.exe -m pytest tests/test_codex_lifecycle_durability.py -q --basetemp $p0bTemp
$p0aTemp = Join-Path $env:TEMP 'r01a-p0b-p0a-final-complete'
& .\.venv\Scripts\python.exe -m pytest tests/test_codex_executor_contract_integration.py tests/test_codex_managed_agents.py tests/test_codex_managed_agents_lifecycle.py tests/test_codex_docker_runtime.py tests/test_codex_egress_proxy.py -m 'not docker' -q -rs --basetemp $p0aTemp
$p0aHistoryTemp = Join-Path $env:TEMP 'r01a-p0b-history-verified'
& .\.venv\Scripts\python.exe -m pytest tests/test_codex_single_trial_adapter.py -k 'final_continuation or redacted_third or lifecycle_audit_is_not_valid_strict_benchmark_result or live_controller_factory' -q -rs --basetemp $p0aHistoryTemp
```

- Ruff lint passed; format check passed, 128 Python files already formatted.
- P0-B: **152 passed in 29.04s**, no skips/deselections.
- P0-A selected suite: **96 passed, 1 skipped, 7 deselected in 3.35s**.
- Historical provenance/deferred factory: **34 passed, 28 deselected in 1.70s**.
- Total executed: **282 passed, 1 skipped**; 35 intentionally deselected.
- Full unrestricted pytest, real Docker/WSL tests, builds, OpenAI operations and
  remote CI were not run. They are outside this task's authorization, not passes.

Intermediate checks caught the controller retrying deletion after an already
reported unknown schema-validation cleanup; the fallback now applies only to
deadline failures with a validated usable ID. A separate-clock fixture initially
exceeded a Docker command's shorter cap; its corrected delays test the intended
phase boundary. Final results above include these corrections.

### Every skipped or deselected case

Skipped for absent Windows symlink privilege:
`tests/test_codex_managed_agents_lifecycle.py::test_artifact_workspace_rejects_symlinks`.

The seven `docker` cases were deliberately deselected:

```text
test_codex_managed_agents_lifecycle.py::test_real_docker_synthetic_lifecycle_never_creates_a_trial_record
test_codex_docker_runtime.py::test_real_docker_denies_host_evaluator_secret_and_network_access
test_codex_docker_runtime.py::test_real_docker_timeout_force_removes_container_and_child_process
test_codex_docker_runtime.py::test_frozen_image_digest_and_embedded_lockfile_are_verified
test_codex_docker_runtime.py::test_real_codex_exec_server_starts_in_offline_isolated_candidate
test_codex_docker_runtime.py::test_real_docker_restricted_egress_denies_bypass_without_upstream_requests
test_codex_docker_runtime.py::test_real_codex_exec_server_uses_proxy_without_contacting_upstream
```

The following 28 cases in `tests/test_codex_single_trial_adapter.py` were outside
the selected history/factory regression scope and not executed. They are not
claimed as passes or collectively classified as safe to run:

```text
test_jsonl_events_are_bounded_and_credentials_are_redacted
test_trial_context_binds_fixed_model_condition_tools_and_inputs
test_prepare_workspace_exports_only_public_r01_inputs
test_preflight_is_honest_and_never_ready_without_isolation_and_access
test_authorization_is_single_row_scoped_expiring_and_one_use
test_active_trial_lease_is_exclusive_and_retained_without_cleanup_proof
test_active_trial_lease_rejects_a_competing_process
test_attempt_two_consumption_accepts_only_its_own_verified_lease
test_cleanup_verification_rejects_foreign_or_stale_lock
test_offline_timeout_probe_terminates_its_synthetic_process_tree
test_run_one_stays_blocked_before_any_session_can_start
test_authorization_file_is_private_and_one_use_without_network
test_usage_extraction_uses_actual_managed_agents_turn_usage
test_run_one_delegates_only_the_scoped_r01a_context_to_lifecycle
test_run_one_rejects_authorization_replay_under_different_state_directory
test_consumed_trial_marker_prevents_a_second_authorization_in_fixed_state
test_attempt_two_requires_immutable_clean_attempt_one_and_has_separate_marker
test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup[audit_change0]
test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup[audit_change1]
test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup[audit_change2]
test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup[audit_change3]
test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup[audit_change4]
test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup[audit_change5]
test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup[audit_change6]
test_legacy_attempt_two_audit_rejects_reported_work_or_uncertain_cleanup[audit_change7]
test_attempt_two_rejects_missing_first_attempt_consumed_marker
test_recovery_is_append_only_bound_to_expired_attempt_two_provenance
test_attempt_two_is_blocked_without_verified_cleanup_or_prior_consumption
```

Opposite-filter `--collect-only` commands enumerated these exact omissions without
running fixtures. Collection counts are not additional executed test evidence.

## Changed files

- `lifecycle_safety.py`: phase accounting, durable private evidence and inspector.
- `lifecycle.py`: production phase ownership, bounded SSE/cleanup/review,
  evidence-first persistence/release and conservative worker uncertainty.
- `managed_agents.py`: inherited I/O budgets and journaled API operations,
  stable successful-create response evidence and unchanged at-most-once guards.
- `docker_runtime.py`: inherited command budgets, named version-probe cleanup,
  serialized verified removal and journaled candidate operations.
- `adapter.py`: durable private files/markers/lease metadata, deferred bounded
  runtime gates, fingerprint binding, journal-aware cleanup and read-only CLI.
- `tests/test_codex_lifecycle_durability.py`: new offline fault/crash matrix.
- `tests/test_codex_managed_agents_lifecycle.py`: stricter uncooperative-stream
  timeout expectation; uncertainty cannot release the lease.
- `tests/test_codex_single_trial_adapter.py`: deferred production factory gate
  regression with synthetic components.
- This document. No historical evidence or benchmark scoring file is changed.

## Mandatory final assessment

**Implemented and offline-tested:** independent phase budgets, bounded silent
stream/header/command waiting, sticky no-late-action checks, no POST retries,
mandatory cleanup attempts, durable ordered intents/outcomes, exclusive markers,
read-only uncertainty-preserving inspection, evidence-before-release ordering and
P0-A confidentiality/contract regression preservation.

**Requires separately permitted real Docker/WSL2 testing:** daemon-side late
creation/removal races, actual child-process/cgroup termination, pinned CLI and
inspection behavior, workspace UID/bind permissions, restricted topology cleanup,
WSL filesystem permissions, fsync/mount/persistence semantics and host-worker exit.

**Requires live verification and separate operator decision:** account/model
access, environment-key scope, registration and actual TLS/WSS through restricted
egress, usable provider response/event behavior and independent session inventory.
Mocked TLS/HTTP responses establish none of those properties.

**Still UNKNOWN:** exact fourth-attempt Docker cause, historical remote session
inventory, provider spending for unreconciled attempts, power-loss persistence and
outcomes of any uncooperative already-entered external operation. No historical
state was reset or reinterpreted. No paid operation, real Docker resource or live
authorization was created. **Final outcome remains NO-GO.**
