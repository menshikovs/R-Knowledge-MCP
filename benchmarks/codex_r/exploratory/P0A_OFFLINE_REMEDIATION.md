# P0-A: contract consistency and safe startup diagnostics

Status: **NO-GO for live R01-A execution**, regardless of the tests below.
Base: audit commit `c6ebfdd4abbbad0a47e4a3e089382ba227cbc4bf`, which adds the
audit to `8b3ef1c`. All four historical attempts remain closed. This package
does not create an attempt identity, recovery authorization or launch procedure.

## Root cause to code mapping

| Finding | Change | Offline evidence |
| --- | --- | --- |
| F01 | `executor_contract.py` owns the URL policy; both client parsing and actual executor startup invoke it. HTTPS, the same API host and port 443 remain mandatory. Exact input string is passed to Codex; trailing slash, subpaths and noncredential routing queries are allowed. Malformed/nested path escaping, traversal, credentials, fragments and unsafe characters are rejected. | Allowed strings traverse production startup unchanged; each rejected string yields zero Docker operations. |
| F02 | Lifecycle records creation intent before the call, then refreshes observed client flags before error reporting and cleanup. It distinguishes confirmed/uncertain creation, startup attempted/failed/process-started, connection observed, and unattempted/uncertain/submitted task states. Task POST attempts come from the client, not from a connection event. | HTTP 201 followed by startup failure retains one created session and zero submissions; a process-only start never claims connection; ambiguous mock creation/submission remains uncertain. |
| F03 | Docker exceptions carry reviewed codes, phase, optional observed CLI/container exit values, startup state and timeout class. Lifecycle reprojects through a closed vocabulary. No stderr, argv, Config.Env, URL, exception text/chain or Docker HTTP status is exported. Primary startup errors survive failed removal; cleanup failures remain separately classified and block export. | Inject nonzero CLI exit, unavailable executable, timeout, malformed inspect, exited container and cleanup nonzero/exception; persist through the real private writer. |
| F04 | A constructor-injected command runner replaces subprocess execution only. `CodexCandidateRuntime.start_managed_executor`, image/workspace validation, policy inspection, client parsing and lifecycle remain production methods. | Synthetic HTTPX 201 and SSE plus deterministic Docker CLI records; subprocess and socket access are explicitly denied by the new test fixture. |
| F10 | New diagnostic text fields use closed enums, observed numeric fields require exact integers, unobserved fields stay null. Lifecycle scrubs known executor-key values and URLs even inside ordinary nested event text; the real HTTP client already removes the application-key value. | Unconventional synthetic keys, signed URLs, stderr, nested events, exception causes and cleanup failures are checked in persisted files and captured stdout/stderr. |

The runtime configuration fingerprint includes the new shared module. Existing
authorization validation, one-use markers, exclusive leases, remote deletion,
candidate isolation, model/effort, zero-MCP policy and scorer are not relaxed.
No historical file is rewritten. No external dependency or runtime bypass flag
is introduced. The injection seam is a Python dependency, not a CLI switch.

## Changed files

- `executor_contract.py`: shared data-only validation, event confidentiality
  helper and closed diagnostic projection.
- `managed_agents.py`: shared policy and explicit task-error operation label.
- `docker_runtime.py`: shared policy, injected command boundary and safe
  startup/cleanup error metadata. Running process evidence remains distinct
  from executor registration or a connected session.
- `lifecycle.py`: timely flags, primary versus cleanup reporting and confidential
  event storage; successful deletion is reflected in remote-session state.
- `adapter.py`: bind shared policy bytes into the execution fingerprint.
- `tests/test_codex_executor_contract_integration.py`: entirely offline boundary
  matrix. Every persisted result is synthetic and never a benchmark outcome.
- `tests/test_codex_managed_agents_lifecycle.py`: correct the old HTTP-rejection
  fake to carry the production client's uncertainty flags; assert retained
  lease and unknown deletion instead of falsely certifying cleanup.
- This document. The original audit and strict benchmark files are unchanged.

## Verification boundaries and test selection

The five selected existing/new test modules were inspected for offline safety.
All real Docker tests in the existing modules are marked `docker` and excluded.
The new file additionally fails on any real subprocess or network connection.
Its API transport is always `httpx.MockTransport`; the topology and lease are
synthetic objects, and the scoring callback fails if reached in a pre-task test.
No authorization file or consumed marker is created by the new lifecycle matrix.
The adapter regression selection uses only isolated historical fixtures, mocked
cleanup and synthetic authorization data; it never invokes a live CLI command.

Commands (Windows project virtualenv; pytest temp roots outside the repository):

```powershell
ruff check .
ruff format --check .
$p0aTemp = Join-Path $env:TEMP 'rkmcp-p0a-offline-final'
& .\.venv\Scripts\python.exe -m pytest tests/test_codex_executor_contract_integration.py tests/test_codex_managed_agents.py tests/test_codex_managed_agents_lifecycle.py tests/test_codex_docker_runtime.py tests/test_codex_egress_proxy.py -m 'not docker' -q --basetemp $p0aTemp
$p0aHistoryTemp = Join-Path $env:TEMP 'rkmcp-p0a-history-tests'
& .\.venv\Scripts\python.exe -m pytest tests/test_codex_single_trial_adapter.py -k 'final_continuation or redacted_third or lifecycle_audit_is_not_valid_strict_benchmark_result' -q --basetemp $p0aHistoryTemp
```

Final local results:

- `ruff check .`: passed.
- `ruff format --check .`: passed (125 Python files already formatted).
- Production-boundary matrix and established mocked regressions: **96 passed,
  1 skipped, 7 deselected**. The new module contributes 29 passing cases.
- Selected historical provenance, consumed-marker and strict-result import
  regressions: **33 passed, 29 deselected**.

An intermediate run exposed the old fake HTTP-rejection client's missing
production uncertainty flags. Its fixture and cleanup expectation were corrected
to preserve the existing real client's fail-closed behavior; the final selected
suite is green. The Windows
symlink test skipped for missing creation privileges; Docker tests are
deliberately deselected, not silently treated as passing. Full unrestricted
pytest, Docker builds/probes and live CI execution are outside this task's
permitted validation. No authenticated OpenAI calls are made by these commands.

## Mandatory failure matrix

| Case | Expected assertion |
| --- | --- |
| HTTP 201, invalid URL | Schema failure; preserved successful HTTP response; deletion confirmed by mock; no Docker operation or task. |
| HTTP 201, permitted URL | Actual production startup under injected subprocess; unchanged URL; process started, registration not claimed; synthetic stream can fail before any task. |
| CLI nonzero | `cli_nonzero`, `start_container`, observed exit 125, no fabricated HTTP status. |
| Executable unavailable | `executable_unavailable`, `verify_image`, unknown exit/status fields null. |
| Command timeout | `command_timeout`, observed command deadline classification, no raw timeout command/stderr. |
| Unexpected inspection | `invalid_inspection`, `inspect_policy`, no raw inspect output. |
| Container exited before readiness | `executor_exited`, observed state exited and exit code 126. |
| Startup and cleanup failures | Primary code retained; separate `cleanup_unverified`; no export/scoring and aggregate cleanup false. |
| Successful creation, zero submissions | Creation count one, task count zero, inference false; no inference inferred from HTTP or process readiness. |
| Persisted startup failure | Actual `_private_json_write`, synthetic record type/flag, no secrets, rejected by strict result validator. |
| Uncertain create/task POST | No retry; uncertain outcome remains explicit; no invented session ID/deletion or inferred inference. |

## Remaining blockers

- F05 global monotonic deadline restructuring is not implemented. Existing
  startup/stream/task/cleanup timing limitations remain; test success does not
  certify a single 900-second end-to-end controller deadline.
- F08 durable append-only intent/outcome journaling and crash recovery are not
  implemented. Diagnostics survive ordinary caught failures, not arbitrary
  process/power loss. Existing markers and histories remain conservative and
  immutable; no replay or fifth attempt is permitted by this package.
- Real Docker daemon inspection formats, WSL bind/UID permissions, pinned CLI
  behavior and the restricted proxy's TLS/WSS path still require separately
  permitted non-model validation. Mocked subprocess output is not daemon proof.
- Account permissions, environment-key scope and live service compatibility are
  unverified. No new session or model operation was used to validate them.
- The exact fourth-attempt cause remains unknown without the missing safe
  historical evidence identified by the audit. No old checkpoint is reconciled
  or interpreted as a confirmed provider charge.

P0-A removes demonstrated contract/ordinary-failure diagnostic defects. It is
not a GO decision, new launch authorization or automatic next experiment.
