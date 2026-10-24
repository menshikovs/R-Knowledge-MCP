# R01-A Final Offline Readiness Review

**Review date:** 2026-10-23<br>
**Decision:** **NO-GO** for any new R01-A authorization, session, task, or trial.<br>
**Review type:** Read-only source/evidence review. No Docker, Managed Agents API, inference, authorization, or trial command was run. The only intended working-tree addition is this report.

## Repository snapshot and scope

- **HEAD:** `1ffe96bad3727d89fc699f3f8f6a1460faa47c06`.
- **Working tree:** dirty. Modified tracked files: `.gitignore`, `pyproject.toml`, `benchmarks/codex_r/exploratory/docker_runtime.py`, `tests/test_codex_docker_runtime.py`, `tests/test_codex_executor_contract_integration.py`, and `tests/test_codex_managed_agents_lifecycle.py`. Existing untracked exploratory reports are present. This report is being added separately.
- **Diff against HEAD:** `docker_runtime.py` contains the shell failure-token correction, Docker wait/log diagnostics, and scoped synthetic workspace ACL; the two pytest configuration files route/cache-ignore pytest data in one directory; tests cover those edits and correct the F10 fixture collision and readiness-gate assertions. There is no working diff in `adapter.py`, `lifecycle.py`, `lifecycle_safety.py`, `managed_agents.py`, or `executor_contract.py`.
- **Historical evidence:** The tracked benchmark reports, manifest, configs, oracle, and runner have no working-tree diff. The four closed attempt identities, consumed authorizations, and unreconciled financial checkpoint remain as recorded by the root-cause and P0-B reports. External per-user state was not opened, so this review does not independently attest its bytes or current remote contents.

Review inputs included `R01A_ROOT_CAUSE_AUDIT.md`, `P0A_OFFLINE_REMEDIATION.md`, `P0B_DEADLINE_DURABILITY.md`, `P0AB_INDEPENDENT_VERIFICATION.md`, `F10_CONFIDENTIALITY_HOTFIX.md`, `OFFLINE_VERIFICATION_UNBLOCK.md`, `DOCKER_MARKED_TEST_REVIEW.md`, the current implementation/test diff, and the operator evidence listed below.

## Evidence ledger

### Operator-reported verification

The operator reports the following completed in Ubuntu WSL2:

- Selected offline regression suite: **252 passed, 7 deselected**.
- Frozen R image and embedded lockfile Docker test: **PASS**.
- Real Docker isolation boundary probe: **PASS**.
- Real Docker timeout and forced child-process cleanup: **PASS**.
- Real Codex exec-server offline startup: **PASS**.
- Real Codex-to-local-fake-proxy transport: **PASS**.
- Final Docker inventory: no remaining RKMCP containers or networks.

These are recorded as operator-observed results, not independently reproduced in this read-only review. The exact command transcript, Docker daemon/image identifiers, stdout/stderr, and cleanup inventory artifact were not supplied with this request. They therefore support the stated test outcomes, but do not establish that a live service or TLS/WSS registration works.

### Independently checked in the local tree

- The tested Docker boundary uses a disposable container with `--network none`, UID/GID `65534:65534`, read-only root, dropped capabilities, `no-new-privileges`, bounded resources, and the generated public workspace only (`docker_runtime.py:452-525`). `PROBE_SCRIPT` now calls the defined `fail` helper at the direct gateway check (`docker_runtime.py:25-90`).
- Docker wait now separates Docker CLI failure, invalid/missing status, and nonzero container exit. Failure logs join stdout and stderr, with a fixed no-output fallback (`docker_runtime.py:597-652`). The boundary probe always enters forced container removal and requires removal verification before returning success (`:653-659`).
- The candidate write grant is an explicit, nonrecursive `u:65534:rwx` ACL on the fresh workspace root only (`docker_runtime.py:751-776`). The test mocks `setfacl` command execution (`tests/test_codex_docker_runtime.py:94-125`); the operator-reported Docker boundary/startup results supply the separate observed non-root use evidence.
- The event sanitizer recursively sanitizes dictionary keys and values, imposes depth/node/output/text limits, rejects non-string keys/cycles and fails on sanitized-key collisions (`executor_contract.py:108-196`). The client delegates event sanitization to that implementation (`managed_agents.py:541-545`); `adapter.redact` delegates to it too (`adapter.py:69-92`).
- Audit writes call the redactor before the owner-private writer (`adapter.py:1031-1038`). Journal files are created exclusively with `0600`; live journals require non-Windows POSIX and directory fsync support (`lifecycle_safety.py:108-180`). The recent workspace ACL is separate from these locations and files. No writer/journal permission code changed in the working diff.
- Cleanup verification checks Docker inventory, a saved audit, and a matching complete journal with successful audit-persistence and lease-release outcomes (`adapter.py:1313-1394`). Journal inspection reports partial tails and pending work and hardcodes replay/recovery/cleanup certification false (`lifecycle_safety.py:237-314`).

## Finding disposition

| Finding | Status | Current assessment and evidence |
|---|---|---|
| **F01 — URL contract** | **PASS (offline); live PARTIAL** | Shared validator and unchanged URL flow are documented in the independent report and source at `executor_contract.py:23-105`, `managed_agents.py:96-124,274-285`, and `docker_runtime.py:962-987`. The operator's Docker tests do not exercise a real registration URL or service response. No TLS/WSS/account compatibility claim is made. |
| **F02 — Lifecycle truthfulness** | **PASS (offline); external outcome PARTIAL** | Create/task attempt and uncertainty flags, executor-start state, and cleanup transitions are kept separately (`managed_agents.py:274-403`, `lifecycle.py:444-524,639-690`). Tests and operator's 252-pass suite cover the synthetic paths. A remote effect already entered into HTTP transport cannot be canceled by a local timeout; that state remains unknown and retains the fail-closed gate. |
| **F03 — Error diagnostics** | **PASS for reviewed projections; PARTIAL for future/live paths** | Closed diagnostic projection and separated primary/cleanup failures are in `executor_contract.py:117-196` and `lifecycle.py:548-590,609-669`. The uncommitted Docker diagnostics fix now preserves container exit status and stderr for this fixed offline probe (`docker_runtime.py:597-652`). Probe output is test diagnostics, not a general-purpose safe exception serializer; arbitrary logs must not be promoted into live audit fields. |
| **F04 — Integration fidelity** | **PASS for offline test seam; live compatibility PARTIAL** | The production `CodexCandidateRuntime.start_managed_executor` remains the method under test; only injected command and HTTP transport boundaries are replaced (`tests/test_codex_executor_contract_integration.py:55-153,244-330`). Operator reports real offline Codex startup and local fake-proxy transport. The fake proxy returns synthetic rejection and does not establish TLS, WSS, registration, or successful service behavior. |
| **F05 — Deadline behavior** | **PARTIAL** | Monotonic phase budgets, sticky cancellation, and no-late-event acceptance are implemented and the offline suite is reported green (`lifecycle_safety.py:317-420`; `lifecycle.py:518-524`). The implementation bounds caller waits but cannot kill uncooperative Python threads or retract an already-entered HTTP/Docker side effect. Late completion can remain externally effective; real daemon race and power interruption are not proven by the reported tests. |
| **F06 — Spend provenance** | **FAIL as a readiness gate** | `adapter.py:1163-1185` and `pilot.py:425-468` still rely on operator-entered spend/checkpoint values rather than provider-confirmed usage/cost. The historical 1004/1004/1004 checkpoint is explicitly unreconciled in `R01A_ROOT_CAUSE_AUDIT.md:27-32,582-589` and P0-B: it must remain unreconciled. Provider spending for the four historical attempts remains unknown. Obtain dated provider-side usage/cost evidence and reconcile without editing the original record. |
| **F07 — Historical schema/provenance** | **PASS for inspected protections; PARTIAL for external artifact custody** | The P0-A report records explicit historical-shape fixtures, byte-bound authorization provenance, immutable evidence, and synthetic-result rejection. The current tracked reports/config/oracle/runner are unchanged. The broader operator suite is reported green, but this review did not inspect external state or independently rerun historical byte-binding tests. Keep synthetic records segregated; no migration or rewrite is authorized. |
| **F08 — Journal durability/cleanup certification** | **PARTIAL (process-crash model); FAIL for any power-loss claim** | Intent-before-side-effect, append/fsync records, hash chain, torn-tail inspection, marker conservatism, audit-before-release ordering, and lease retention are implemented (`lifecycle_safety.py:119-229,237-314,422-480`; `lifecycle.py:215-264`; `adapter.py:993-1019,1313-1394`). The operator reports the selected suite green, but these are process-crash/injected-failure checks. They do not simulate sudden power loss or storage-cache loss and cannot establish nonvolatile-media durability. Missing release outcome remains unverified even after audit persistence. |
| **F09 — Readiness gates vs. actual service** | **PARTIAL / unresolved live blocker** | Local gates, frozen-image checks, offline executor startup, and a local fake proxy have evidence. The fake proxy proves transport selection to a local sink only; it is not an OpenAI endpoint and does not prove TLS certificate validation, WSS relay registration, account/model access, key scope, returned settings, or successful executor connection. These remain unknown (`ADAPTER.md:90-115,553-580`). |
| **F10 — Confidentiality** | **PASS for covered synthetic event/audit paths; residual limitation** | The previous independent finding demonstrated unchanged credential-shaped dictionary keys. The fixed sanitizer now processes keys as well as values and rejects collision/limit/type failures (`executor_contract.py:108-196`). The fixture was split into independent secret cases without changing the dedicated collision test (`tests/test_codex_executor_contract_integration.py:481-590`). The earlier Windows run could not enter the actual audit-writer test; the operator's later 252-pass Ubuntu suite resolves that test-execution gap if that case was included. It does not prove detection of arbitrary unknown secrets lacking configured material or recognizable credential/URL patterns. |
| **F11 — Operating status/inspection clarity** | **PARTIAL** | Inspection now preserves uncertainty and does not certify cleanup solely from journal inspection (`lifecycle_safety.py:300-314`; `adapter.py:1313-1394`), and lifecycle failures carry a sanitized summary. However `ADAPTER.md:3` and `:557-565` retain broad “no live trial/session” status statements that conflict with the four historical attempts and should be date-scoped and reconciled against authoritative incident evidence before any future decision. This review intentionally did not rewrite historical docs. |

## Specific readiness questions

### F10 evidence reconciliation

The original independent report's F10 **FAIL** was a source-confirmed dictionary-key leak; the hotfix changed both sanitizer layers to use the shared bounded sanitizer. The fixture's earlier collisions were genuine sanitizer collisions produced by mixing independent secret-key cases; the test now puts those cases in separate dictionaries, while the dedicated collision-rejection test remains. The report's previous Windows setup error did not test saved audit behavior. The operator now reports the selected Ubuntu suite completed with 252 passes. Accordingly, F10 is no longer an outstanding confirmed defect for the tested paths, and the operator evidence covers the prior blocked regression only to the extent that test was in the selected command. This is not a blanket confidentiality proof.

### Private permissions and candidate ACL

The working diff does not change the private audit or journal writer. Source still uses exclusive owner-only files (`0600`) and owner-only state/journal directories (`0700` default), with directory fsync required for live journals. The `setfacl` change is restricted to a newly generated public R01 workspace root and grants only UID 65534 the directory access needed by the container. It is not recursive, does not touch the repository, and does not affect private audit/journal paths. The focused unit test verifies the exact ACL command but mocks its execution; the reported real Docker boundary and startup passes are the evidence for practical UID access.

### Docker cleanup and abnormal termination

The reported final inventory is a successful point-in-time observation: no RKMCP containers or networks remained after the listed tests. Code attempts forced removal in `finally`, verifies the target's absence, and surfaces cleanup failures (`docker_runtime.py:653-659,1150-1177,1421-1443`; topology teardown also tracks individual created resources). This does not guarantee cleanup after host power loss, kernel failure, Docker daemon outage, forced process termination before `finally`, or an uncooperative command already accepted by the daemon. Such interruptions leave cleanup uncertain; the journal/lease gates are designed not to certify or replay that state.

### Outbound-capable Docker tests

The restricted-egress test (`tests/test_codex_docker_runtime.py:201-227`) creates an outbound bridge for a proxy that can establish TLS tunnels to two allowlisted hosts (`docker_runtime.py:1180-1245`; see `DOCKER_MARKED_TEST_REVIEW.md` section 5). Before relying on this proxy for any future live attempt, the egress policy needs an accepted and evidenced integration test in an operator-approved Docker environment. Its successful run would test the constrained egress path and denial checks; it still would not prove TLS/WSS service compatibility. The synthetic lifecycle test (`tests/test_codex_managed_agents_lifecycle.py:530-650`) also creates that outbound-capable topology even though its fake client/runtime do not route live API traffic through it. It is **not necessary** for a future readiness decision in its present form and should stay excluded or be redesigned to use an internal-only topology. Neither test was represented in the operator's list of completed Docker tests.

## Remaining blockers and next actions

1. Keep all four attempt identities closed and consumed authorizations intact. Do not reset or replace markers.
2. Preserve the historical financial checkpoint as unreconciled. Obtain independent provider-side spending evidence for the four attempts; do not infer a charge from the 1004 balance checkpoint.
3. Preserve a sealed operator evidence bundle for the claimed WSL2 suite and Docker results: exact commands, commit/tree digest, image IDs/digests, tool/daemon versions, safe result summaries, timestamps, and final inventory. Do not export secrets, full daemon events, environment values, or raw process arguments.
4. For any later readiness review, resolve documented status ambiguity in F11 and establish account/key-scope and live registration evidence through a separately reviewed process. A local fake proxy is not that evidence.
5. Decide whether to run the restricted-egress test under explicit network-owner acceptance, or revise the evidence plan if a safer equivalent is selected. Do not run the synthetic lifecycle Docker test with an outbound-capable proxy in its current unnecessary configuration.
6. Keep process-crash/fsync test claims bounded to process-crash behavior. Establish filesystem/storage guarantees separately before claiming power-loss durability.

## Final determination

Offline code paths, F10 regression coverage, and the listed Docker boundary checks have substantially stronger evidence than the prior review. The report nevertheless leaves material spend, historical remote state, power-loss, and live TLS/WSS/account compatibility questions unresolved. No local Docker result establishes Managed Agents compatibility. **Final R01-A execution status: NO-GO. This report does not authorize another attempt.**
