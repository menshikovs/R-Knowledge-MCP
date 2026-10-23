# R01-A F10 Confidentiality Hotfix

Base: `70a0d943f7fceb64e6db6c13327f3c2a49e3f094`  
Hotfix implementation commit: `0fca5165563fa120821016971e8baefc2cc0cfc0`.  
Final execution status: **NO-GO**. This change does not authorize or perform another live R01-A attempt.

## Root cause and fix

The client event sanitizer and audit redactors scrubbed secret-bearing *values* but copied dictionary keys unchanged. Credential material, signed URLs, or sensitive URL components used as keys could therefore reach lifecycle records, private audit files, and output.

`executor_contract.sanitize_reference_data` is now the common bounded recursive sanitizer. It sanitizes every string key and value, including dictionaries nested inside lists; removes exact configured secrets and common credential/token/signature patterns; redacts URLs in executor events/audits; preserves ordinary source URLs in general adapter/pilot output while removing sensitive components and URL userinfo. Sensitive field names still redact their associated values, while ordinary protocol keys such as `type` remain intact.

The sanitizer fails closed on transformed-key collisions, non-string object keys, cyclic/unsupported values, excessive nesting/node counts/text/output size, and invalid secret configuration. It never chooses one colliding value or falls back to raw input. The executor credential is passed from lifecycle context to the production client sanitizer, while the client always supplies its application key. Adapter serialization includes configured application and executor keys. `pilot.redact` now uses the same policy.

## Modified files

- `benchmarks/codex_r/exploratory/executor_contract.py` — shared bounded sanitizer, exact-secret/token/signature handling, collision rejection.
- `benchmarks/codex_r/exploratory/managed_agents.py` — production event sanitization delegates to the shared policy.
- `benchmarks/codex_r/exploratory/lifecycle.py` — supplies executor key material to the event sanitizer; audit serialization already uses the same policy with both keys.
- `benchmarks/codex_r/exploratory/adapter.py` — configured keys and nested keys are scrubbed in private writes, JSONL event parsing, CLI errors, and stdout/stderr output.
- `benchmarks/codex_r/exploratory/pilot.py` — synthetic event redaction delegates to shared policy.
- `tests/test_codex_executor_contract_integration.py` — adversarial offline regressions.

No benchmark/scorer/oracle data, model configuration, URL allowlist, deadline behavior, journal schema/semantics, historical evidence, or live execution protocol was changed.

## Regression matrix

| Case | Regression assertion |
|---|---|
| Top-level dictionary key | Exact synthetic application key does not survive client sanitization. |
| Nested dictionary key | Exact executor key does not survive nested sanitization. |
| List of dictionaries | Recursive key/value sanitization applies inside list elements. |
| Ordinary value string | Application key, executor key, and signed URL text are removed. |
| Signed URL key/value | URL with a `signature` component is scrubbed in both positions. |
| Saved lifecycle audit | Production lifecycle record and its durable audit contain no synthetic secret. |
| Private adapter writer | `_private_json_write` removes configured app/executor keys even from injected raw audit fields. |
| Captured stdout/stderr and inspection | Read-only journal inspection output and saved output contain no synthetic secret. |
| Collision | If sanitization maps distinct keys to the same string, sanitization raises `SanitizationError`/`ValueError`; it does not overwrite. |
| Protocol behavior | `type` fields remain unchanged; connected then completed SSE events still submit once and terminate normally. |
| Ordinary source URL | Nonsensitive source URL remains unchanged in general adapter output. |

## Independent verification results

### Test provenance and offline safety

The five executed tests use only synthetic event JSON and credentials. The event streaming regressions use `httpx.MockTransport`; JSONL parsing and strict benchmark validation are local pure-function checks. Their source contains no Docker calls, `subprocess` boundary, network socket, credential lookup, authorization flow, or live service dependency. The audit/inspection test uses a temporary local fixture and the production private writer/inspection path; it was attempted separately but pytest failed before entering the test body.

### Commands and exact results

Windows PowerShell, repository venv, all paths below relative to the repository:

```powershell
& .\.venv\Scripts\ruff.exe check . --exclude .review-tmp,.review-tmp2,.review-tmp3
& .\.venv\Scripts\ruff.exe format --check benchmarks/codex_r tests
& .\.venv\Scripts\python.exe -m pytest `
  tests/test_codex_executor_contract_integration.py::test_f10_preserves_protocol_type_and_terminal_event_handling `
  tests/test_codex_executor_contract_integration.py::test_f10_sanitization_key_collision_fails_closed `
  tests/test_codex_managed_agents.py::test_sse_subscription_precedes_submission_and_redacts_credentials `
  tests/test_codex_single_trial_adapter.py::test_jsonl_events_are_bounded_and_credentials_are_redacted `
  tests/test_codex_single_trial_adapter.py::test_lifecycle_audit_is_not_valid_strict_benchmark_result `
  -q -p no:cacheprovider
```

- Ruff check: **passed**. The three excluded `.review-tmp*` directories were already present from the preceding Windows verification attempt and deny directory access; none was deleted or repaired.
- Ruff format check: **passed**, 69 files already formatted.
- Selected filesystem-free pytest command: **5 passed, 0 failed, 0 skipped, 0 deselected**.
- Audit/private-writer/inspection test attempt:

```powershell
$fresh = Join-Path $env:TEMP ('r01a-f10-verify-' + [guid]::NewGuid().ToString('N'))
& .\.venv\Scripts\python.exe -m pytest `
  tests/test_codex_executor_contract_integration.py::test_f10_sanitizes_keys_values_audit_stdout_and_inspection `
  -q --basetemp $fresh -p no:cacheprovider
```

Result: **0 passed, 0 failed, 0 skipped, 1 setup error, 0 deselected**. `tmp_path` fixture setup raised `PermissionError: [WinError 5] Access is denied` while enumerating the newly created external temp root. The test body did not run; lifecycle audit serialization, private adapter writer, captured output, and inspection confidentiality therefore remain unverified by pytest in this environment.

The P0-B `test_read_only_recovery_and_synthetic_audit_cannot_import_as_real` regression is synthetic and denies network access, but requires `tmp_path`; it was not run because the same pytest temp-fixture failure prevents reaching its test body.

### Read-only environment diagnosis

- `wsl.exe --list --quiet` and `wsl.exe -l -v` both return `Wsl/EnumerateDistros/Service/E_ACCESSDENIED`. Ubuntu WSL2 could not be identified or invoked, so no Linux test run was possible.
- `%TEMP%` parent ACL inspection showed inherited Modify/Read/Write entries. A newly created control directory could be listed. The pytest basetemp roots themselves reject directory listing and `icacls` with Access Denied; their reported PowerShell mode is `d-----`. The prior `.review-tmp`, `.review-tmp2`, and `.review-tmp3` roots have the same read-only-inspection result.
- No pytest directory was deleted, repaired, chmodded, or otherwise changed during this verification. The denial appears specific to those pytest roots in the managed Windows environment; its originating ACL/security mechanism could not be established read-only.
- No Docker, authenticated API, authorization, inference, or external network activity was performed.

## Remaining confidentiality limitations

The sanitizer detects exact configured key material plus reviewed common token, bearer, signature, and sensitive-field patterns. It cannot identify an arbitrary unknown secret that has no credential-shaped marker and is absent from configured secret values. Unsupported values or key collisions fail closed, which can stop an audit from being written; the lifecycle retains its existing uncertainty/NO-GO behavior and does not serialize raw fallback data. General metadata URLs are retained unless they contain sensitive components or userinfo; executor event/audit URLs are fully redacted.

## Independent verification status

**PARTIAL.** Key sanitization, collision fail-closed behavior, event type preservation, terminal handling, existing SSE credential scrubbing, JSONL sanitization, and synthetic-result rejection passed offline. Saved lifecycle audit/private-writer/inspection output is not independently verified because the corresponding pytest test could not leave fixture setup. WSL verification was unavailable.

**Final execution status remains NO-GO.** Independent live compatibility, remote session state, and authorization remain outside this hotfix. Do not authorize another R01-A attempt.
