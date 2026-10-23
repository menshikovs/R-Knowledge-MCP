# Offline Verification Unblock Report

**Repository baseline:** `1ffe96bad3727d89fc699f3f8f6a1460faa47c06`<br>
**Verification date:** 2026-10-23<br>
**Final execution status:** **NO-GO**

## Summary

The pytest blocker is reproducible and is caused by Windows handling of
owner-only (`0o700`) directories created by the installed pytest/Python
combination. The standard pytest `tmp_path` fixture cannot enumerate its fresh
temporary directory. A separate synthetic test fixture using mode `0o755` got
past that issue, but the lifecycle audit then failed when the journal code
created its intentionally owner-only journal directory/file. This is an
environment compatibility limitation; no production code was changed.

The `%TEMP%` parent permits creating and modifying children, but its inherited
ACL grants access to multiple principals. Therefore it is not an owner-private
alternative suitable for claiming private journal verification. No ACL or
security settings were changed. WSL2 was also unavailable: both distribution
enumeration commands returned `Wsl/EnumerateDistros/Service/E_ACCESSDENIED`.

## Diagnosis and safe corrective action

Read-only inspection of the installed pytest implementation showed
`TempPathFactory.getbasetemp`/`mktemp` create directories with mode `0o700`
(`.venv/Lib/site-packages/_pytest/tmpdir.py`, lines 139-159). In the same
`%TEMP%` parent, a synthetic `os.mkdir(..., 0o700)` directory immediately
failed on enumeration with `PermissionError: [WinError 5]`; `icacls` on that
child also returned Access Denied. Synthetic children created with `0o755`
and `0o777` could be listed and passed a file write/read/delete probe.

The repository's lifecycle journal independently requires owner-only directory
and file creation (`benchmarks/codex_r/exploratory/lifecycle_safety.py:108,
165`). A temporary test-only fixture override used a unique directory under
`%TEMP%` and mode `0o755` for the test directory. The test then reached
`Journal.__init__` and failed opening its journal file with `PermissionError`.
The fixture teardown also received Access Denied while traversing the resulting
journal directory. This proves the failure is not limited to pytest fixture
setup or test isolation. The diagnostics do not establish that security
software is responsible; subprocess inheritance is not implicated by these
direct filesystem reproductions.

`C:\\tmp` was also checked read-only for ACLs, but a normal child-directory
creation was denied in this sandbox. No inaccessible existing pytest
directories (`.review-tmp`, `.review-tmp2`, `.review-tmp3`, or earlier roots)
were deleted, repaired, or permission-adjusted.

**Safe next step:** have the platform owner restore the current user's normal
access to the registered Ubuntu WSL2 distribution, then use a fresh private
Linux temporary directory outside the repository and historical R01-A state.
Alternatively, run on a supported Linux host with owner-only directory/file
semantics. Do not loosen journal permissions or alter Windows ACL/security
configuration to force this verification. After access is restored, rerun the
blocked tests and selected P0-A/P0-B offline regressions.

## Test commands and results

All selected tests use local synthetic fixtures and do not make API requests,
invoke inference, or create Docker resources. No authorization or execution
commands were used.

### Tmp-independent F10/P0-A regressions

Command:

```powershell
.venv\Scripts\python.exe -m pytest `
  tests/test_codex_executor_contract_integration.py::test_f10_preserves_protocol_type_and_terminal_event_handling `
  tests/test_codex_executor_contract_integration.py::test_f10_sanitization_key_collision_fails_closed `
  tests/test_codex_managed_agents.py::test_sse_subscription_precedes_submission_and_redacts_credentials `
  tests/test_codex_single_trial_adapter.py::test_jsonl_events_are_bounded_and_credentials_are_redacted `
  tests/test_codex_single_trial_adapter.py::test_lifecycle_audit_is_not_valid_strict_benchmark_result `
  -q -p no:cacheprovider
```

Result: **5 passed, 0 failed, 0 skipped, 0 deselected** (`5 passed in 0.08s`).
These cover protocol event preservation/terminal handling, collision rejection,
SSE credential redaction, bounded/redacted JSONL events, and strict benchmark
rejection of a synthetic lifecycle audit.

### Lifecycle audit, private writer, and inspection test

The previously blocked test is
`tests/test_codex_executor_contract_integration.py::test_f10_sanitizes_keys_values_audit_stdout_and_inspection`.
With standard pytest `tmp_path`, fixture setup fails while accessing the fresh
pytest temp directory (`PermissionError: [WinError 5]`). A test-only plugin
override created a unique synthetic test directory with mode `0o755`; the
selected test then failed in `lifecycle_safety.py:165` when opening
`lifecycle-journals/R01-A-attempt-1.jsonl` with `PermissionError: [Errno 13]`.
The plugin teardown produced one additional Access Denied error while walking
that journal directory.

Result for the override run: **0 passed, 1 failed, 1 error**, exit status 1.
This is an environment failure, not a passing confidentiality regression.
Its diagnostic directory was preserved after access was denied; no cleanup or
permission changes were attempted.

### WSL2

Read-only commands `wsl.exe --list --quiet` and `wsl.exe -l -v` both returned
`Wsl/EnumerateDistros/Service/E_ACCESSDENIED`. No WSL configuration or system
settings were changed.

### Selected suites not completed

The lifecycle audit/private-writer/inspection regression remains unverified on
this host. The broader selected P0-A/P0-B suites were not run because they
include filesystem/journal cases subject to the same owner-only Windows
failure. The five tests above are the offline-safe subset that completed; they
do not constitute full P0-A/P0-B verification.

## F10 verification status

**Partial; not independently complete on this host.** The tmp-independent
sanitizer, protocol, collision, event-redaction, and synthetic-record
rejection tests pass. The test covering sanitized saved audits, captured
stdout/stderr, and read-only inspection output did not complete because the
private journal writer cannot create its owner-only journal file under this
Windows environment. Live compatibility was not tested. No test evidence here
establishes power-loss durability.

## Remaining NO-GO blockers

- Restore safe access to the registered WSL2 Linux distribution or provide a
  supported Linux environment with working owner-only temporary filesystem
  semantics.
- Re-run the blocked F10 lifecycle audit/private-writer/inspection test and
  selected offline P0-A/P0-B suites there.
- Keep final execution status **NO-GO**; this report does not authorize or
  perform another R01-A attempt.

No production source, historical records, consumed markers, ACLs, or security
configuration were modified. This report is not committed because the
workspace grants read-only access to `.git`; no elevated operation was
requested or attempted.
