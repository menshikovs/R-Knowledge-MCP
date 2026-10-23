# F09 Zero-Task Connectivity Harness

Status: **implemented for offline synthetic verification only**. R01-A remains
**NO-GO**. This implementation is not approval for a live staging check.

## Changed files

- `benchmarks/codex_r/exploratory/connectivity_harness.py` - isolated client,
  journal, lease, state machine and injected executor boundary.
- `tests/test_codex_connectivity_harness.py` — synthetic-only regression tests.
- `benchmarks/codex_r/exploratory/F09_STAGING_REVIEW_CHECKLIST.md` — separate
  checklist for a future, separately authorized staging check.

## Safety boundary

The client has fixed HTTPS routes for session creation, event streaming and
session deletion. The creation schema accepts only a reviewed agent
configuration, a self-hosted environment with `/workspace`, and a required
externally approved finite `spend_control.limit`; there is no task input,
task-submission method, Responses API method, R01-A controller, or
authorization-consumption path. Synthetic clients require `httpx.MockTransport`.
The control-plane client pins the API origin, verifies TLS, ignores ambient
proxy variables, and refuses redirects. An executor is injected; the narrow
Docker adapter delegates only to the existing runtime start/stop boundary and
does not itself launch Docker.

The spend limit has no production default. A caller must supply a positive
integer number of USD cents with an external approval reference and
billing-owner acknowledgment; missing, null, boolean, fractional, non-positive,
string, or otherwise invalid values are rejected before transport without
rounding or conversion. These fields are structural evidence only and do not
authenticate the approval. The request uses `spend_control.limit`, but this
repository contains no official API schema copy. Its USD-cent units and
enforcement semantics must be checked against the official schema before any
live use. Live mode remains disabled.

The state machine records create intent before the request, treats ambiguous
creation as unknown without retry, rejects connection events after a monotonic
deadline, and uses a separate bounded cleanup budget. Journal appends are
hash-chained, private, append-only and fsynced. A final bounded audit is
persisted before lease-release authorization. The release authorization is
durably recorded before unlinking the lease, so interruption can leave a stale
lease that blocks future checks rather than permit an unrecorded clean release.
Unverified executor termination, uncertain session creation/deletion, or
durability errors retain the lease. Audit output contains categorical states,
failure codes, timestamps and hashes of IDs; it does not contain credentials,
raw event objects, remote URLs or exception text.

## Verification

Ruff was run on the two Python files:

```text
ruff check benchmarks/codex_r/exploratory/connectivity_harness.py tests/test_codex_connectivity_harness.py
All checks passed!

ruff format --check benchmarks/codex_r/exploratory/connectivity_harness.py tests/test_codex_connectivity_harness.py
2 files already formatted
```

Selected tests that do not require filesystem fixtures completed under Windows
Python 3.14.4 with `httpx` supplied from the installed Python 3.10 user-site
directory through `PYTHONPATH`:

```text
python -m pytest -p no:tmpdir -p no:cacheprovider \
  tests/test_codex_connectivity_harness.py::test_fixed_https_proxy_and_redirect_contract \
  tests/test_codex_connectivity_harness.py::test_agent_configuration_rejects_input_tools_and_unreviewed_fields \
  tests/test_codex_connectivity_harness.py::test_malformed_and_truncated_sse_fail_without_exposing_payload \
  tests/test_codex_connectivity_harness.py::test_blocked_boundary_is_bounded_even_if_injected_clock_stalls -q
5 passed, 1 PytestConfigWarning (unknown `cache_dir` option), 0 failed
```

The complete module was also attempted with:

```text
python -m pytest -p no:cacheprovider --tb=short tests/test_codex_connectivity_harness.py -q
5 passed, 20 setup errors, 1 PytestConfigWarning
```

All 20 errors occurred before test bodies ran: pytest could not access the
user-specific `%TEMP%\pytest-of-<user>` directory (`PermissionError:
[WinError 5] Access is denied`). Filesystem-backed lease/journal/audit
integration tests, including the fsync failure and release-order regressions,
therefore remain unverified. WSL2 startup/enumeration also returned
`Wsl/Service/CreateInstance/E_ACCESSDENIED`. No Docker, network, Managed Agents
API, credentials, inference, or historical state were used.

## Remaining limitations and unresolved risks

- Mocked HTTP behavior does not prove live endpoint schemas, event ordering,
  authentication scope, TLS/WSS registration compatibility, or provider
  behavior. The harness is not yet live-compatible evidence.
- Synthetic tests do not establish filesystem durability on the eventual live
  host. `fsync` and directory `fsync` are requested, but this is not a power-loss
  guarantee; storage/controller caches and filesystem behavior remain outside
  the evidence. No power-loss test was run.
- Process-crash behavior is reasoned from intent/outcome ordering and retained
  lease behavior; this task did not perform kill-at-each-boundary crash tests.
- A timed-out daemon thread cannot be forcibly cancelled. Late create and
  executor results receive bounded cleanup attempts under the shared cleanup
  deadline. If a worker or cleanup does not settle, the lease remains held and
  operator reconciliation is required; no result is treated as a clean outcome.
- The existing executor runtime/topology must independently enforce restricted
  egress, secret isolation, bounded startup/termination and verifiable resource
  cleanup. This harness does not prove those live properties.
- Provider cost for a session without task input is not established as zero.
- Windows is explicitly unsupported for live journal durability in this
  implementation; live use requires a reviewed POSIX host and private external
  state directory.

**Decision:** offline implementation work only; no staging or R01-A GO decision.


## P0 remediation follow-up

Live readiness remains NO-GO. Live clients now reject injected transports and
remain completely disabled because no reviewed provider identity/credential-scope
verifier is implemented. Matching a local project string is never sufficient.
This is a fail-closed gate, not evidence that project binding has been established.
The live harness also requires the reviewed Docker adapter.

Worker abandonment is synchronized with eventual completion; late results are
disposed once without certifying cleanup. Both real and injected monotonic clocks
are checked. Expired workers do not invoke their callbacks. The Docker adapter
checks the deadline again after topology startup before starting an executor.
An already running opaque callback cannot be forcibly cancelled; its internal
external effects remain uncertain and the lease remains held.

SSE is parsed from bounded chunks, with total, line and event byte limits checked
before buffering additional bytes. Cleanup shares one absolute budget (real and
injected clocks); topology cleanup is attempted after executor-stop exceptions
while budget remains. Exhaustion never authorizes additional cleanup work or a
clean lease release. Final audit writes reject short return counts. Private
file/directory modes and journal ordering are preserved.

`inspect_staging_journal` is read-only and bounded. It checks chain/sequence,
record types and intent/outcome references, reports pending intents and corruption,
and never certifies resource cleanup or authorizes recovery. It does not reset locks.
A hash chain is not a signature or protection against an owner rewriting evidence.

Current checks:

- `ruff check` and `ruff format --check` on both Python files: PASS.
- Selected filesystem-independent cases: 16 passed, 23 deselected, one cache_dir warning.
- At that stage, the complete module: 16 passed, 23 fixture setup errors, one
  cache_dir warning.
- The setup errors are Windows WinError 5 accessing the pytest user temp root;
  they do not establish production defects. Linux filesystem integration remains
  unverified after those changes. The operator was asked to run the suite in
  Ubuntu; the operator subsequently reported 45 synthetic tests passed before
  the lease-release durability changes in this update.

Operator command (offline only, from the repository using its Linux Python environment):

```sh
python -m pytest -p no:cacheprovider --basetemp="$(mktemp -d /tmp/f09-p0-XXXXXX)" tests/test_codex_connectivity_harness.py -q
```

Exact test functions requiring Linux filesystem verification (the SSE function
expands to five cases):

- `test_public_surface_cannot_submit_tasks_or_responses_and_create_has_no_input`
- `test_nested_environment_connected_event_is_projected_and_accepted`
- `test_sse_states_are_fail_closed_and_always_delete_known_session`
- `test_late_connected_event_is_not_accepted`
- `test_duplicate_pending_events_do_not_repeat_executor_start`
- `test_duplicate_connected_event_does_not_repeat_any_side_effect`
- `test_ambiguous_create_timeout_is_not_retried_and_retains_lease`
- `test_create_rejection_is_distinct_from_ambiguous_creation`
- `test_unverified_executor_stop_or_session_delete_prevents_clean_release`
- `test_unverified_session_deletion_prevents_clean_release`
- `test_failed_journal_intent_blocks_session_creation_and_keeps_lease`
- `test_saved_audit_redacts_credentials_ids_remote_url_and_exception_text`
- `test_fixed_route_client_rejects_task_and_responses_paths_before_transport`
- `test_lease_release_is_authorized_by_a_durable_journal_outcome`
- `test_journal_fsync_failure_blocks_session_creation_and_retains_lease`
- `test_release_failure_keeps_durable_audit_and_retains_lease`
- `test_shared_cleanup_budget_blocks_delete_after_exhaustion`
- `test_short_audit_write_retains_lease`
- `test_journal_inspector_rejects_partial_tail_and_reports_pending`


## Follow-up - second independent review findings

The harness constructor now accepts synthetic test doubles only with a synthetic
journal and lease. Live mode requires the exact `StagingAgentsClient` type and a
module capability token. No constructor path currently issues that token: live
client creation still fails closed until provider project identity and credential
scope have an independently reviewed verifier. An arbitrary object marked
`synthetic=False` cannot enter the harness.

A create call that returns after its deadline is never retried. A late, fully
validated response is identified by hashes in the journal, then deletion is
attempted only within the same absolute cleanup deadline used by the run. The
delete result must be explicitly confirmed before it is recorded as successful.
Late executor results likewise receive a durable stop intent/outcome pair and
their cleanup uses the original cleanup deadline. If the callback, identity,
journal or cleanup remains uncertain at deadline, the lease stays held and the
run requires operator reconciliation. Unresolved workers retain their journal
and client handles until they can append a bounded outcome; they do not release
the lease.

The read-only journal inspector now checks exact record keys and types, consistent
synthetic mode, operation uniqueness, resource-hash pairing, intent/outcome
references, and audit-before-release ordering. It never certifies cleanup or
authorizes recovery. A hash chain cannot detect truncation at a valid record
boundary without a trusted external sequence/hash anchor; journal contents are
also not signed against an owner who can rewrite the file.

Lease release uses a persistent process-shared `lease.gate` and paired private
release markers. Under the gate, release durably writes a `pending` marker before
unlinking `active.lock`, fsyncs the lease directory after unlink, then durably
writes a matching `complete` marker. Acquisition holds the same gate and refuses
to proceed if any marker is corrupt or lacks its matching completion marker.
Markers are retained; an unresolved release requires operator reconciliation and
is never repaired by recreating the lock. This covers process interruption and
concurrent acquisition races when the filesystem honors the requested syncs. It
does not establish power-loss or storage-controller guarantees. The read-only
journal inspector reports the marker state but never authorizes recovery. The
marker scan is bounded at 10,000 release attempts; exceeding the bound fails
closed and requires operator review.

Verification for this follow-up:

- `ruff check` and `ruff format --check` on the harness and test module: PASS.
- Filesystem-independent pytest selection: 13 passed, 31 deselected; one warning
  that `cache_dir` is unknown when the cache plugin is disabled.
- After the lease-release marker and inspector changes, the operator reported
  three focused lease tests passed and 49 full F09 tests passed under Ubuntu
  WSL2. Those results predate the two subprocess regressions added in this
  update.
- An earlier Windows Codex sandbox attempt could not access fresh `--basetemp`
  directories and ended with `PermissionError: [WinError 5]` in `pytest.tmpdir`
  setup/session cleanup. That environment failure did not verify the new
  subprocess regressions.

### Operator verification (2026-10-23)

The operator subsequently ran the tests directly under Ubuntu WSL2:

- Cross-process lease regressions: **2 passed**.
- Full F09 synthetic suite: **51 passed**, one non-blocking pytest configuration
  warning, **0 failures**.

These completed Ubuntu results supersede the earlier Windows sandbox test
blocker for this offline suite. The earlier 49-test result predates the new
subprocess regressions and is retained as historical evidence. This remains
synthetic evidence only: live TLS/WSS has not been verified, live mode stays
disabled pending project identity and credential-scope verification, and no
power-loss durability guarantee is established. R01-A remains **NO-GO**.

Run the complete synthetic module directly in Ubuntu WSL2:

```sh
python -m pytest -p no:cacheprovider --basetemp="$(mktemp -d /tmp/f09-p0-XXXXXX)" tests/test_codex_connectivity_harness.py -q
```

The two new subprocess lease regressions can also be selected directly:

```sh
python -m pytest -p no:cacheprovider --basetemp="$(mktemp -d /tmp/f09-lease-process-XXXXXX)" \
  tests/test_codex_connectivity_harness.py::test_independent_processes_cannot_hold_the_same_lease \
  tests/test_codex_connectivity_harness.py::test_fresh_process_rejects_lease_after_process_exits_mid_release -q
```

The subprocess regressions and complete suite have now been run by the operator
under Ubuntu WSL2 as recorded in the dated verification update above. This does
not establish live TLS/WSS compatibility or power-loss durability; live mode
remains disabled pending project identity and credential-scope verification.

No Docker, network, provider API, session, task, inference or authorization
operation is part of this command. R01-A and staging connectivity remain NO-GO.
