# Independent P0-A/P0-B Verification

Review date: 2026-10-23. Repository state reviewed: `70a0d943f7fceb64e6db6c13327f3c2a49e3f094`, with P0-A ancestor `53cf4f2904084ea648f6fb92fc6383e8363c648b`. Review was read-only apart from this report. No authorization/run command, authenticated API, inference request, or Docker resource creation was invoked. **Final execution status remains NO-GO.**

## Scope and evidence limits

I read `R01A_ROOT_CAUSE_AUDIT.md`, `P0A_OFFLINE_REMEDIATION.md`, and `P0B_DEADLINE_DURABILITY.md`, then traced production adapter/client/runtime/controller and journal code plus their focused tests. The code-level verdicts below do not treat the remediation notes as proof.

I attempted the offline P0-A/P0-B pytest suites on this Windows checkout. Pytest started but reported test errors and then failed in its own `tmpdir` session cleanup with `PermissionError: [WinError 5] Access is denied` enumerating the selected `--basetemp` directory. Consequently **this review has no independently completed pytest pass count**. Test evidence below identifies the exact regression assertions present in source; it is not represented as a test run passing here. Docker, live service, WSL filesystem, and power-loss behavior were not exercised.

## Findings

### F01 — URL contract

**PASS (offline implementation review); live compatibility remains unverified.**

- **Implementation:** `executor_contract.py:23-88` owns URL parsing and returns the exact original string. The client calls the shared validator in `managed_agents.py:96-124`; production executor startup calls it before workspace/image/Docker work in `docker_runtime.py:962-970`, then puts the unchanged `remote_url` into `exec-server --remote` at `docker_runtime.py:980-987`. The validator restricts HTTPS, allowlisted host, port, path namespace, credentials, fragments, traversal, nested escapes, and unsafe characters. Client creation preserves the validated URL at `managed_agents.py:274-285`.
- **Test evidence:** `tests/test_codex_executor_contract_integration.py` exercises `CodexCandidateRuntime.start_managed_executor` and asserts allowed URLs reach the subprocess boundary unchanged and rejected variants perform no Docker command (`test_runtime_and_client_share_executor_url_contract`, around lines 149-220 and parameterized cases near 390). This review could not complete that test because of the pytest temp-directory failure.
- **Remaining uncertainty:** The subprocess runner is injected and the HTTP response/transport is synthetic. No real daemon argument behavior, pinned binary URL acceptance, or service compatibility is established.
- **Required remediation:** None indicated by the inspected shared policy path. Keep the separate live compatibility gate closed.

### F02 — Lifecycle truthfulness

**PASS (state bookkeeping and conservative uncertainty).**

- **Implementation:** `managed_agents.py:274-364` marks create attempted/uncertain before POST, captures successful response status before decoding, and clears uncertainty only after schema validation or verified cleanup. Task POST is marked attempted/uncertain immediately before the request at `managed_agents.py:366-403`; client at-most-once protection is per session. `lifecycle.py:355-400` refreshes client state before failure serialization; `lifecycle.py:444-457` records the create attempt/uncertainty before creation, and `lifecycle.py:500-503` records submission only after the client call returns. Process start and connected event are separately recorded in the intervening startup/stream flow.
- **Test evidence:** Integration tests cover transport failure after create attempt, successful creation followed by executor failure, and ambiguous task POST (`tests/test_codex_executor_contract_integration.py:415-442`). Durability tests cover late create/SSE/task and task no-retry paths (`tests/test_codex_lifecycle_durability.py:302-329`). They were not independently executed successfully in this environment.
- **Remaining uncertainty:** A blocked call already entered into the HTTP transport cannot be killed by Python; its eventual remote outcome stays unknown. A confirmed 2xx response whose body cannot be validated is correctly not treated as a cleanly absent session.
- **Required remediation:** None identified in the inspected transitions.

### F03 — Error diagnostics and serialization

**PASS for reviewed diagnostics paths; arbitrary provider/runtime behavior remains outside proof.**

- **Implementation:** Docker exceptions carry closed codes and structured observations; lifecycle projects them through `project_runtime_diagnostics` (`executor_contract.py:117-176`; `lifecycle.py:548-590`). General exception text and chains are not serialized. Primary failure and cleanup failure are stored separately (`lifecycle.py:585-590`, `609-669`). The adapter's audit writer redacts before private persistence (`adapter.py:77-90`, `lifecycle.py:226-240`).
- **Test evidence:** Integration cases inject nonzero, timeout, and cleanup failures, then inspect serialized audit output (`tests/test_codex_executor_contract_integration.py:329-390`). The focused tests include exception causes and captured output checks (`tests/test_codex_executor_contract_integration.py:375-390, 448-471`). Completion not independently verified because of pytest environment failure.
- **Remaining uncertainty:** Diagnostic safety depends on new fields continuing to pass through the projections. An unreviewed future serializer or log path could bypass them; no live Docker stderr/log path was exercised.
- **Required remediation:** None for the paths reviewed. Preserve closed-vocabulary projection as a boundary.

### F04 — Integration fidelity

**PASS (test design); test execution incomplete here.**

- **Implementation/test boundary:** `tests/test_codex_executor_contract_integration.py` calls the production `CodexCandidateRuntime.start_managed_executor` through the lifecycle fixture, with a constructor-injected command runner replacing subprocess operations and an `httpx.MockTransport` replacing HTTP. It does not replace the executor startup method. The test module denies socket access and rejects unexpected subprocess calls (`tests/test_codex_executor_contract_integration.py:55-153, 244-330`). The durability suite imports and reuses that production fixture (`tests/test_codex_lifecycle_durability.py:1-30`).
- **Test evidence:** Source inspection confirms the invoked method and boundaries. The pytest attempt did not complete, so no claim of green independent execution is made.
- **Remaining uncertainty:** Mock command output and HTTP behavior do not prove compatibility with the real Docker CLI, pinned executor binary, HTTP service, TLS, or WSS.
- **Required remediation:** None to integration wiring; obtain separately authorized live compatibility evidence before changing execution status.

### F05 — Deadlines and late work

**PASS for conservative offline control flow; INSUFFICIENT EVIDENCE for hard real-time and live external-operation guarantees.**

- **Implementation:** `lifecycle_safety.py:317-339, 341-420` uses monotonic deadlines, parent/child flows, sticky cancellation, and worker threads. A timed-out already-entered call sets `abandoned`; `lifecycle.py:221-224, 256-260, 670-679` prevents cleanup certification and lease release when work/evidence is uncertain. `lifecycle.py:518-524` checks the event iterator through the safety gate so a late event cannot be treated as a successful task outcome. HTTP child caps are applied in `managed_agents.py:160-187, 198-205`. Docker commands derive their timeout from remaining safety budget; candidate removal is serialized and verified in `docker_runtime.py:1110-1165`.
- **Test evidence:** Test scenarios exist for late headers, silent stream, delayed connection, late task, expired intent, cleanup race, and independent task budget (`tests/test_codex_lifecycle_durability.py:302-329, 536-568, 659-686`). They were not independently completed here.
- **Remaining uncertainty:** Python cannot terminate an uncooperative worker or an external side effect that has already started. A late completion may still affect the remote service or Docker after caller timeout; safety state becomes uncertain and blocks subsequent authorized actions, but does not undo that effect. Mocked header/read delays do not establish actual HTTPX/service timing. Docker daemon late-removal behavior is not proven. Deadlines are bounded caller waits, not a process-wide real-time guarantee.
- **Required remediation:** No offline logic defect established. Live daemon/client compatibility and operational worker-exit behavior remain required evidence, not presumed passes.

### F08 — Journal durability, ordering, and recovery

**PASS for fail-closed process-crash design; INSUFFICIENT EVIDENCE for power-loss durability.**

- **Implementation:** `lifecycle_safety.py:102-133` creates exclusive private files and fsyncs file/parent; `:136-212` creates an O_APPEND exclusive JSONL journal and fsyncs each complete record before advancing in-memory sequence/hash. `LifecycleSafety.effect` writes and fsyncs intent before invoking the effect (`:422-480`). Failed intent blocks non-cleanup actions; cleanup on evidence failure is allowed only as a destructive attempt and cannot certify clean state (`:428-441`; controller gates at `lifecycle.py:221-224, 670-679`). `inspect_journal` verifies exact fields, sequence, chain, intent/outcome pairing and reports partial tails, pending work, unknown remote state, and no recovery/replay (`lifecycle_safety.py:226-314`). Final audit persistence is journaled before lease release (`lifecycle.py:225-255`). Marker writes are separate exclusive operations with no rollback (`adapter.py` consumed-marker writer; see `tests/test_codex_lifecycle_durability.py:585-613`).
- **Test evidence:** The source test matrix covers injected short write/fsync failure, partial tails, marker interruption, cleanup race, audit persistence/release crash boundaries, and 15-operation child-process crash matrices (`tests/test_codex_lifecycle_durability.py:358-378, 426-521, 524-613, 616-757`). These are intended process-crash tests; this review could not independently execute them.
- **Required crash distinction:** A child-process crash after a completed `fsync` tests process interruption and read-back behavior. It does **not** simulate sudden power loss, controller/device cache loss, filesystem journal replay, or prove that file and directory `fsync` reached nonvolatile media. The code explicitly rejects live journaling on Windows and reports directory-fsync support; POSIX/WSL mount and storage semantics remain unverified.
- **Remaining uncertainty:** No power-loss experiment; no WSL/Linux live filesystem verification. Hash chains detect accidental truncation/mutation in the retained prefix but are not signatures and cannot detect deletion of a complete valid tail by a state-directory owner. On an incomplete tail the inspector preserves the valid prefix and sets `incomplete_tail`; it never authorizes replay. A crash after audit outcome and before lease-release outcome leaves the release state uncertain; missing release proof blocks cleanup verification.
- **Required remediation:** None established in code for the stipulated process-crash boundary. Do not describe this as power-loss durable until filesystem and storage guarantees are independently established.

### F10 — Confidentiality, including event structures

**FAIL (credential-shaped dictionary keys survive event sanitization).**

- **Implementation:** `ManagedAgentsClient._sanitize_event` recursively redacts sensitive *field names* and exact `_key` occurrences in string values (`managed_agents.py:541-566`). But the dictionary comprehension emits `str(k)` unchanged at line 559. Lifecycle's second sanitizer also preserves dictionary keys while redacting sensitive-name values (`executor_contract.py:91-115`).
- **Deterministic offline reproduction:** For an event object like `{"sk-synthetic-secret-value": "opaque"}`, `_sanitize_event` returns the same secret-bearing key because it is not a sensitive field name and the key itself is never passed through a sanitizer. The lifecycle pass also retains it. This uses only an in-memory synthetic object; no network or credentials are involved.
- **Test evidence:** Existing tests exercise nested sensitive fields, exact key values, and URL-shaped strings (`tests/test_codex_executor_contract_integration.py:393-410, 448-471`), but do not cover a credential value in an object key. The source assertion is direct; pytest execution was incomplete here.
- **Remaining uncertainty:** This proves a sanitizer coverage gap, not that a real service event contains secrets as keys. Arbitrary unknown secret values under ordinary keys also cannot be identified unless their values are supplied to the scrubber or match a reviewed detector. `adapter.py:77-90` has the same key-preservation pattern.
- **Required remediation:** Before any future run, sanitize dictionary keys as well as values (including keys at every nested level) using bounded replacement/validation, and add a regression asserting that credential-shaped and exact supplied-secret keys do not survive either the client sanitizer or persisted lifecycle audit. Keep exception text excluded.

## Required adversarial scenario dispositions

| Scenario | Review disposition |
|---|---|
| Late HTTP completion after caller timeout | Conservative state/lease retention is implemented (`LifecycleSafety.call`, `effect`); remote late side effect remains inherently uncertain. Offline regression exists; not independently executed. |
| Late Docker subprocess completion after cleanup begins | Caller remains bounded; cleanup/lease is not certified when a worker is abandoned. A real subprocess already inside the daemon can finish late; no live daemon evidence. |
| SSE event after deadline | Deadline gate around iterator advancement and sticky cancellation prevent accepting it as a valid later transition. Mock scenario exists; not independently executed. |
| Concurrent timeout and normal container removal | Runtime removal mutex/verification and injected race test exist (`docker_runtime.py:1110-1165`, durability test around 536-568); no live Docker concurrency evidence. |
| Journal fsync failure before task submission | Intent failure blocks the task effect (`lifecycle_safety.py:428-441`); explicit injected-fsync test exists at `tests/test_codex_lifecycle_durability.py:616-628`; not independently executed. |
| Crash after audit persistence before lease release | Audit and release are separate intent/outcome pairs; missing release evidence stays unverified; test exists at `tests/test_codex_lifecycle_durability.py:701-712`. |
| Partial journal tail inspection | Prefix is reported with `incomplete_tail=true`; no append/recovery/replay is exposed (`lifecycle_safety.py:247-314`); test at `tests/test_codex_lifecycle_durability.py:524-534`. |
| Failed second consumed-marker write | First marker remains and retry is blocked by existing marker; production consumption crash child and assertions at `tests/test_codex_lifecycle_durability.py:585-613`. |
| Cleanup verification without durable outcome | Controller checks pending/invalid/torn evidence and audit/release ordering; inspection itself hardcodes `cleanup_proven_by_inspection=false` (`lifecycle.py:211-224`, `lifecycle_safety.py:309-313`). |
| Unknown remote session classified deleted | No usable ID plus uncertain create remains `None`/unknown; `session_deleted_verified` only becomes true after confirmed deletion path (`lifecycle.py:639-683`, `managed_agents.py:328-355`). |
| Secret leakage in unexpected exception/event structures | Exception text is excluded by allowlist; event dictionary-key leakage is a confirmed F10 failure described above. |

## Overall determination

F01, F02, F03, and F04 pass the inspected offline implementation design. F05 and F08 pass only within the mocked/process-crash boundary; their live behavior and power-loss durability are not established. F10 fails for secrets in nested dictionary keys. Since the focused pytest run did not complete independently and a confidentiality defect remains, the P0-A/P0-B packages are **not independently cleared**. **Final execution status remains NO-GO.**
