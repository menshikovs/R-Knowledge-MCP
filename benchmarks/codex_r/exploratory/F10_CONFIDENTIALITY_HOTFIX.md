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

## Verification results

- `ruff check . --exclude .review-tmp,.review-tmp2,.review-tmp3` — **passed**. The exclusions are inaccessible leftover pytest temp directories from the prior Windows review attempt.
- `ruff format --check benchmarks/codex_r tests` — **passed**, 69 files already formatted.
- Filesystem-free selected pytest cases — **2 passed**: `test_f10_preserves_protocol_type_and_terminal_event_handling` and `test_f10_sanitization_key_collision_fails_closed`.
- The lifecycle/private-writer/inspection pytest case was attempted with a fresh unique `--basetemp` under `%TEMP%`, outside the repository. Pytest failed during `tmp_path` fixture setup with `PermissionError: [WinError 5] Access is denied` on that root. It did not execute; this is an environment failure, not a test pass. The regression is present in source but persistence and inspection assertions remain unverified by execution here.
- No Docker, authenticated API, authorization, inference, or external network activity was performed.

## Remaining confidentiality limitations

The sanitizer detects exact configured key material plus reviewed common token, bearer, signature, and sensitive-field patterns. It cannot identify an arbitrary unknown secret that has no credential-shaped marker and is absent from configured secret values. Unsupported values or key collisions fail closed, which can stop an audit from being written; the lifecycle retains its existing uncertainty/NO-GO behavior and does not serialize raw fallback data. General metadata URLs are retained unless they contain sensitive components or userinfo; executor event/audit URLs are fully redacted.

**Final execution status remains NO-GO.** Independent live compatibility, remote session state, and authorization remain outside this hotfix.
