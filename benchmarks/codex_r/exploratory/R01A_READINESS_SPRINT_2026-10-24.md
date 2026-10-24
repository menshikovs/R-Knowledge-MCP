# R01-A Readiness Sprint — 2026-10-24

**Decision: NO-GO.** This is a non-historical readiness report. No Docker
container, Managed Agents request, session, task, inference, authorization, or
benchmark was run or created during this sprint.

## Snapshot and scope

- Baseline HEAD: `d7ee3a32bde1f8345a5e847538cb054a6a6fb8b5`.
- The working tree was already dirty. Sprint-related files are listed below;
  unrelated `.gitignore`, F09 checklist, and composable-prompt changes were
  preserved. Three pre-existing pytest directories were inaccessible during
  status enumeration and were not opened or changed.
- Historical attempt evidence, consumed authorization state, the root-cause
  audit, prior readiness report, and financial checkpoint have no sprint diff.
- No commit was made. The filesystem-backed lifecycle regression below remains
  unverified in this Windows sandbox, so the changes are not represented as a
  fully verified release.

## Changes made

| File | Change |
|---|---|
| `managed_agents.py:57-101,205-231,300-320` | Requires an exact positive `int` USD-cent limit, places it at `spend_control.limit`, and validates every session-creation POST before transport. Boolean, float, string, null, zero, and negative values fail closed. |
| `adapter.py:92-139,241-258,410-520,1211-1298` | Binds the spend approval to an attempt, refuses all four closed historical attempt IDs, reports independent zero-task connectivity as unverified, and fixes the production live gate to false. The existing attempt allowlist still contains only the historical identities. |
| `lifecycle.py:26,40-75,312-342,461-507` | Requires the independently verified zero-task connectivity prerequisite before lease acquisition, authorization consumption, Docker topology, or session creation. Snapshots the four closed historical IDs separately from the mutable journal allowlist. The approved cap is forwarded to the client. |
| `docker_runtime.py:184-211,307-321,335-352,1109-1148` and `executor_contract.py:202-265` | Adds bounded classification of a few recognized Docker CLI error phrases into closed diagnostic codes. Raw stderr is not copied into diagnostics. Existing operation-phase, exit-code, timeout, and cleanup fields remain projected through the closed schema. |
| `tests/test_codex_managed_agents.py:57-130` | Covers valid payload construction, invalid limits before transport, and direct-route method-case variants. |
| `tests/test_codex_managed_agents_lifecycle.py:222-258,527-679` | Covers cap forwarding/validation, journal-ID distinction, and that the live connectivity gate prevents later operations. The forwarding integration test requires filesystem-backed pytest setup and was not run here. |
| `tests/test_codex_single_trial_adapter.py:69-197,1422-1554` | Covers approval binding, rejection of closed attempts, preflight status, and the production controller gate. |
| `tests/test_codex_docker_runtime.py:58-151` | Adds deterministic injected-command tests for safe Docker failure classification, container-create cleanup ordering, and raw synthetic stderr exclusion. |
| `ADAPTER.md:1-25` | Documents the separate session spend-control requirement, closed history, and NO-GO status. |

The official [Managed Agents session creation reference](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create)
documents `spend_control.limit` in USD cents and says omission or null creates
an unlimited session. Requiring a positive integer is the local fail-closed
policy; no provider request was made to test enforcement.

## Verification

Final checks run in the Windows Python environment:

- Ruff check: **PASS**, 9 selected Python files.
- Ruff format check: **PASS**, 9 selected Python files.
- Selected synthetic offline pytest command: **72 passed, 0 failed**, with one
  non-blocking `PytestConfigWarning` for the existing `cache_dir` option.
  The selection included the complete `test_codex_managed_agents.py`, selected
  lifecycle and adapter regressions, and injected Docker command tests only.
  It did not invoke Docker or external services.
- `git diff --check` on sprint source, test, and adapter documentation paths:
  **PASS**.
- Historical audit/readiness report path diff check: **no changes**.

The exact selected pytest command was:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_codex_managed_agents.py tests/test_codex_docker_runtime.py::test_docker_runtime_requires_an_immutable_image_id tests/test_codex_docker_runtime.py::test_executor_environment_strips_both_application_and_host_scoped_keys tests/test_codex_docker_runtime.py::test_boundary_probe_shell_failure_commands_are_defined_and_portable tests/test_codex_docker_runtime.py::test_docker_wait_classifies_cli_failure_and_container_exit_status tests/test_codex_docker_runtime.py::test_container_logs_include_stderr_for_failure_diagnostics tests/test_codex_docker_runtime.py::test_docker_cli_failure_diagnostics_are_classified_without_persisting_stderr tests/test_codex_docker_runtime.py::test_container_creation_classifies_image_failure_and_verifies_cleanup tests/test_codex_managed_agents_lifecycle.py::test_future_spend_approval_is_typed_and_bound_before_live_gates tests/test_codex_managed_agents_lifecycle.py::test_synthetic_journal_allowlist_entry_is_not_treated_as_closed_history tests/test_codex_managed_agents_lifecycle.py::test_live_session_path_blocks_without_independent_connectivity_evidence tests/test_codex_single_trial_adapter.py::test_preflight_is_honest_and_never_ready_without_isolation_and_access tests/test_codex_single_trial_adapter.py::test_session_spend_approval_is_positive_integer_and_attempt_bound tests/test_codex_single_trial_adapter.py::test_session_spend_approval_cannot_reopen_historical_attempt tests/test_codex_single_trial_adapter.py::test_authorization_issuer_rejects_budget_for_historical_attempt tests/test_codex_single_trial_adapter.py::test_live_controller_factory_uses_existing_components_and_keeps_keys_controller_side
```

An initial run had 69 passes and one test-fixture failure: its synthetic
workspace was relative while the production factory resolves it to an absolute
path. The fixture now uses a non-created path under the system temp root; the
next run passed 70 tests. Injected Docker diagnostics raised that to 71.
Inspection then found that a synthetic journal allowlist entry would be mistaken
for historical closure by spend validation. A fixed historical-ID snapshot and
focused regression cover that case; the final run passed 72 tests. The
filesystem-backed
`test_lifecycle_forwards_only_attempt_bound_spend_limit` was not run because
pytest temporary-directory access has failed in this Windows sandbox. Previous
attempts to use Ubuntu WSL from this environment were denied with
`E_ACCESSDENIED`; no claim of WSL execution is made here. Operator-reported
results (252 offline tests and 5 Docker tests) remain operator-reported and
were not repeated in this sprint.

For Ubuntu WSL2, the unverified filesystem-backed regression can be run with:

```bash
cd /mnt/c/programming_pj/cran-mcp
test_root=$(mktemp -d /tmp/r01a-sprint-XXXXXX)
chmod 700 "$test_root"
PYTHONDONTWRITEBYTECODE=1 .venv-wsl/bin/python -m pytest \
  tests/test_codex_managed_agents_lifecycle.py::test_lifecycle_forwards_only_attempt_bound_spend_limit \
  -q -p no:cacheprovider --basetemp="$test_root/pytest-tmp"
```

## Readiness findings

### Session spending and authorization

All production session-create HTTP POSTs through `ManagedAgentsClient` now
require the positive-integer limit before transport. The R01-A controller also
requires a matching attempt-bound approval. The F09 proposed 200-cent budget is
not used. No R01-A budget or new attempt identity was invented.

The current context builder still accepts only the four historical attempt IDs
(`adapter.py:248-258`), and spend approval rejects each of them. Thus no new
R01-A run can be authorized by the current flow. A separately designed future
attempt identity, approved finite limit, and distinct durable authorization are
still required.

The four historical outcomes remain recorded as:

| Attempt | Recorded outcome |
|---|---|
| `R01-A/attempt-1` | Session creation outcome unknown. |
| `R01-A/attempt-2` | Blocked by the local lock. |
| `R01-A/recovery-after-attempt-2` | Session created; returned URL was rejected. |
| `R01-A/final-continuation` | Session created; Docker executor startup failed before task submission. The exact Docker sub-operation remains unknown. |

### Enforced live preflight

`build_preflight` reports independent connectivity as unverified and
`launch_permitted: false` (`adapter.py:441-520`). The production controller
also supplies a fixed-false connectivity gate (`adapter.py:1211-1298`), while
`lifecycle.py:321-325` rejects live operation before authorization consumption,
lease acquisition, topology startup, or session creation. Synthetic tests
assert no such operations occur. Therefore the R01-A `run_one` path does not
currently permit a session-create operation.

### Docker diagnostics and the fourth attempt

The executor reports a bounded sub-operation and safe reason/exit/timeout
classification. The new classifier distinguishes recognized daemon-unavailable,
image-unavailable, and mount/workspace-failure messages without saving their raw
text. Unrecognized or changed Docker wording remains `cli_nonzero`.

This improves future evidence but does not identify the exact failure in the
fourth historical attempt. The prior five Docker tests are operator-reported
offline isolation/startup checks; they do not reproduce the historical Managed
Agents session response or prove executor registration, WSS, proxy compatibility,
or environment connection. The historical Docker cause remains unknown.

### Historical finance and durability

The recorded `1004 / 1004 / 1004` checkpoint remains **unreconciled**; it does
not establish a $10.04 charge or zero charges. Provider-side usage/cost evidence
is still needed for the four closed attempts. Do not alter the checkpoint.
The operator previously reported no charges in the provider billing view, but
that report is not independent usage/cost evidence and does not reconcile the
checkpoint.

Journal fsync and crash-recovery tests establish only their tested process-crash
and injected-failure behavior. They do not prove power-loss or storage-cache
durability. No current report upgrades those guarantees.

## Remaining blockers and next action

1. Independently establish staging project identity, credential ownership/scope,
   and actual zero-task TLS/WSS executor registration through a separately
   reviewed F09 procedure. F09 live mode remains disabled; local fake-proxy and
   offline Docker evidence are not service compatibility evidence.
2. Design a fresh R01-A attempt identity and distinct durable single-use
   authorization, with its own positive integer USD-cent spend approval. Do not
   reuse any historical identity, consumed authorization, or the F09 budget.
3. Obtain provider-side evidence to reconcile historical charges before making
   a new financial readiness decision.
4. Run the filesystem-backed spend-forwarding regression under Ubuntu WSL2 and
   review the changed files before considering a local commit.

**Next operator action:** complete the separately controlled zero-task staging
identity/credential verification and connectivity procedure; do not attempt
R01-A as part of that check.

**Final readiness: R01-A NO-GO.**
