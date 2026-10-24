# R-Knowledge-MCP Change Impact, Architecture and Security Review

**Review date:** 2026-10-24
**Current branch:** `fix/r01a-deadline-durability`
**HEAD:** `1bdbf6c4cffefd5985e826973e7e4f8639931990`
**Decision:** **NO-GO for R01-A execution and live F09 connectivity.**

## 1. Executive summary

The current tree integrates the R01-A spend-control changes, a fail-closed F09 zero-task harness and synthetic authorization store, an actual MCP technology-stack recommendation tool, and an official R documentation retrieval provider. The server routes the new tools through the existing service boundary. The repository has meaningful offline coverage, but current Windows verification is incomplete and no live OpenAI registration or TLS/WSS compatibility is established.

This review found **0 P0, 1 P1 readiness blocker, 3 P2 findings, and 2 P3 findings**. The P1 is a readiness status, not a newly discovered code defect: remote executor registration, provider credential identity/scope, and historical spend remain unverified. The P2s are a secret-pattern gap, a false-positive package-role matcher, and synchronous local manual-index loading on async request paths. Lower-priority issues concern build-time dependency labeling and formatting/test-environment reliability.

The review did not run Docker, access credentials, call OpenAI, create sessions, submit tasks, consume authorizations, or alter historical evidence. Synthetic reproductions used only fabricated strings. R01-A remains **NO-GO**.

## 2. Repository state and comparison baseline

`git status --short` showed 32 modified tracked files, 8 untracked source/test/documentation files, no staged changes, and no tracked deletions or renames. The one file added by this review is this report. `git diff --check` passed; Git emitted CRLF normalization warnings. `git status` also warned that several pre-existing pytest/review temporary directories are unreadable. They were left untouched and were not included in the review scope.

The exact baseline is ambiguous because no starting commit was specified. I used HEAD as the comparison point for the current uncommitted diff. The relevant R01-A/F09 baseline `715cfa1e460db21cdd92b7789810afe27e5e469d` is an ancestor of HEAD. The intervening commits add the F09 harness and spend policy, fail-closed authorization claims/store, and technology-stack tool. Conclusions about the working tree include both committed changes through HEAD and current uncommitted edits; they should not be read as an approval of any pending commit.

| Component | Relevant files | Change purpose and dependencies | Verification status |
|---|---|---|---|
| R01-A benchmark | `benchmarks/codex_r/exploratory/{adapter,managed_agents,lifecycle,docker_runtime,executor_contract}.py`; corresponding `tests/test_codex_*.py`; `R01A_READINESS_SPRINT_2026-10-24.md` | Attempt-bound spend approval and session payload; lifecycle readiness gate; Docker probe diagnostics and offline regressions. Depends on durable authorization/journal and cleanup code. | Source reviewed. Prior 72-test result is documented as a local operator run; not independently repeated here. Live gate remains false. |
| F09 connectivity | `benchmarks/codex_r/exploratory/connectivity_harness.py`; `F09_STAGING_REVIEW_CHECKLIST.md`; `F09_CONNECTIVITY_HARNESS_IMPLEMENTATION.md`; `tests/test_codex_connectivity_harness.py` | Separate zero-task state machine, fixed-route HTTP client, synthetic authorization store, lease/journal/cleanup protocol. | Source reviewed. Prior Ubuntu result of 102 tests is operator-reported in the sprint context, not independently verified in this turn. Live mode is deliberately blocked. |
| MCP stack tool | `src/cran_knowledge_mcp/technology_recommendation.py`; `service.py`; `server.py`; `tests/test_technology_recommendation.py`; `tests/test_server.py`; `docs/TECHNOLOGY_STACK_RECOMMENDATION.md` | Deterministic package-role recommendations grounded in current provider metadata; registered as `recommend_technology_stack`. Uses existing package and R documentation services. | 11 focused recommendation tests passed; MCP discovery/invocation included in the 27-test offline selection below. Two source-level issues reproduced. |
| Official R manuals | `src/cran_knowledge_mcp/providers/r_documentation.py`; `service.py`; `server.py`; `docs/R_DOCUMENTATION.md`; three `tests/test_r_documentation*.py` modules | Fixed-source R manual index, bounded parsing/search, citation and retrieval provenance, explicit refresh command. | 27 recommendation/manual/MCP tests passed with one Windows-only stdio subprocess test deselected. No live manual download performed. |
| Prompt Intelligence | `src/cran_knowledge_mcp/prompt_intelligence/{composer.py,composition/composer.py,composition/constraints.py,intent.py,native_prompts.py,service.py}`; prompt tests and docs | Client-neutral English generated instructions while retaining supplied text; structured package/documentation context and quality heuristics. | Source and tests inspected. Existing heuristic credential filter shares the limitation in P2-1. |
| Test/configuration support | `pyproject.toml`, `.gitignore`, `tests/conftest.py`, `tests/test_codex_offline_tripwire.py`, Docker and egress tests | Central pytest cache path and scoped offline guard; injected command/transport tests. | Ruff check passed. Broad selected pytest run was blocked by Windows filesystem permission errors. Seven Docker-marked tests were excluded and not run. |

## 3. Architecture assessment

The primary package boundaries remain recognizable: MCP registration is in `server.py`, service orchestration is in `service.py`, package providers remain behind their provider interfaces, and the manual index is isolated in `providers/r_documentation.py`. The new server handlers delegate rather than duplicating provider logic (`server.py:304-332,620-641`; `service.py:420-426,995-1226`). No circular import was found in the reviewed paths. The `KnowledgeService` now owns a sizeable recommendation workflow as well as manual retrieval (`service.py:995-1439`); this remains understandable but is a future extraction candidate if more recommendation workflows are added.

The benchmark package remains separate from the production MCP package. F09 uses a dedicated harness rather than `R01ALifecycleController.run_one`, which is appropriate for keeping zero-task connectivity separate from benchmark execution. The synthetic F09 authorization store is explicitly a model, not a trusted issuer (`connectivity_harness.py:825-829,937-966`); its role labels do not establish distinct OS identities or a trusted issuer.

## 4. MCP protocol and tool compatibility

The new tools are registered with FastMCP and have bounded typed arguments. `recommend_technology_stack` is an actual MCP tool at `server.py:620-641`, not just a helper. Manual search and section retrieval are registered at `server.py:304-332`. In-process MCP tests inspect names/schemas and invoke tools (`tests/test_server.py:15-37,90-101,141-153`; `tests/test_r_documentation_mcp.py:45-76`). Error-aware dispatch converts application and internal failures through the existing result envelope (`server.py:61-68`).

The test `test_stdio_subprocess_initialize_and_error` is the only observed transport-level failure in this focused set. On Windows it fails during named-pipe creation with `PermissionError: [WinError 5]`, before the MCP subprocess can be validated. This is an environment-specific verification gap, not evidence of an MCP protocol defect. Stdio operation under the target Linux environment still needs the operator/CI result.

The project continues to declare `mcp>=1.30,<2` and Python `>=3.11` (`pyproject.toml:10-15`), matching the FastMCP SDK boundary in the repository instructions.

## 5. Prompt Intelligence

Generated headings and boilerplate are English and the prompt composition path retains caller-supplied objective/context rather than translating it. Prompt package facts are grounded through service/provider calls; retrieved manual passages are labeled untrusted and include fixed-source citations (`service.py:1259-1267,1420`; `providers/r_documentation.py:533-597`; `docs/R_DOCUMENTATION.md:88-102`). External enhancement remains an explicit optional path, not a default LLM dependency.

The prompt quality and input filters are deterministic heuristics, not comprehensive secret detectors (`prompt_intelligence/quality.py:5-11,157`; `prompt_intelligence/service.py:1365-1377`). They should not be represented as proof that arbitrary caller text is secret-free. The concrete shared gap is captured as P2-1.

## 6. Technology-stack recommendation findings

The recommendation endpoint validates bounded text/list sizes, retains the caller's text, and labels package results with metadata/source/check-time evidence (`technology_recommendation.py:303-380`; `service.py:1332-1439`). Package candidates originate from templates but are emitted only after package metadata and role evidence checks; the output explicitly calls the architecture and trade-offs heuristics and does not claim an installed environment or solved dependency graph (`service.py:1150-1205,1390-1427`). No LLM call, package installation, project-file read, deployment, or execution is needed.

**P2-2 — Substring role matching can falsely verify package fit.** `metadata_supports_role` searches each role signal as an unbounded substring (`technology_recommendation.py:424-431`). A deterministic synthetic call returned `True` for `readr`, role `data ingestion`, title `Database tools`, and description `Maintains database connections`: the signal `data` is contained at the beginning of `database`. This can cause a candidate package to be labeled metadata-matched and recommended despite unrelated metadata. Match token/phrase boundaries or use package-specific evidence, with regression cases for `data` versus `database`.

**P2-1 — Credential detection misses common authorization-header forms.** The stack validator recognizes a short token-prefix list and labels such as `api_key`, `access_token`, `password`, `secret`, and `credential` (`technology_recommendation.py:297-314`). It accepts the synthetic input `Authorization: Bearer synthetic-token-value`; the same limited pattern family is used by prompt validation (`quality.py:5-11`; `prompt_intelligence/service.py:1371-1377`). Since recommendation output preserves input at `service.py:1432-1438`, a caller can accidentally receive and retain a credential-like string in tool output and conversation history. The synthetic probe was not written to any file. Expand detection for authorization/bearer and other credential forms, add safe rejection tests, and avoid echoing rejected sensitive content. No evidence indicates an actual key is present in the repository.

**P3-1 — `LinkingTo` shares the generic “required” bucket.** Direct package metadata places `Depends`, `Imports`, and `LinkingTo` together under `dependencies.required` (`service.py:1172-1185,1389-1398`). `LinkingTo` is specifically relevant to package compilation, while the response does not distinguish build-time from runtime requirements. Clarify the field scope and output label; do not describe this metadata as a complete install graph.

## 7. Official CRAN documentation integration

The provider uses a fixed registry of six reviewed HTTPS URLs, bounds source/index/section/result sizes, disables redirects, and uses `trust_env=False` in its explicit refresh command (`providers/r_documentation.py:22-29,778-809,906-910`; `docs/R_DOCUMENTATION.md:18-36`). MCP inputs select registered manual IDs and opaque section IDs, not arbitrary hosts or file paths (`server.py:304-332`; provider validation at `r_documentation.py:326-400,490-501,633-678`). Search/retrieval is local-only; refresh is a separately invoked command. The provider reports source URL, retrieval/check times, content hash and version status, and marks returned material untrusted.

The index is not bundled in the reviewed tree. Therefore this review verifies implementation and synthetic fixtures, not that an operator has populated the index, that its six pages are current, or that live source content has been licensed/reviewed. Missing indexes are a documented unavailable state, not a verified retrieval (`docs/R_DOCUMENTATION.md:26-50,88-102`).

**P2-3 — Synchronous index loading and search execute inside async service calls.** The async service methods call synchronous `search`/`get_section` directly (`service.py:420-426`), and the first provider load does `stat`, `read_text`, JSON parsing and full schema validation in the request call (`r_documentation.py:458-488`). The file and section counts have explicit caps (`MAX_INDEX_BYTES` 64 MiB and at most 15,000 sections; `r_documentation.py:22-26,326-400`), which bounds work but can still pause the event loop during cold load and each search scans the local index. Consider moving cold I/O/parse and scoring off-loop or loading/validating the index at controlled startup. The stat-then-read sequence also leaves a local file replacement race; the input path is operator-configured, not MCP-controlled, so this is a local integrity/resource limitation rather than a remote path traversal.

## 8. R01-A readiness and financial controls

The session client validates a positive integer spend limit and includes it in `spend_control.limit` (`managed_agents.py:57-97,221-225,300-311`). Adapter approval checks reject the four historical attempt IDs and bind a new approval to the supplied future attempt (`adapter.py:63-127,922-928`). The lifecycle refuses live execution before session creation unless independent zero-task connectivity evidence is set; the constant is currently `False` (`lifecycle.py:26,330-336`). Thus this review found no path that makes a live run ready merely because the spend-control payload exists.

Readiness remains **NO-GO**. No real Managed Agents TLS/WSS registration is evidenced, no new R01-A authorization is approved or consumed, and the historical financial checkpoint remains unreconciled. The report's documented offline and Docker counts are operator-reported evidence, not new executions in this review. No new attempt was run. The four historical attempts, consumed authorizations, and source financial record were not modified.

The R01-A spend approval is a local typed confirmation object, not provider-authenticated identity/scope evidence. Its presence supplies a finite limit to the request; it does not reconcile previous usage or prove remote credential permissions. Obtain provider-side account/usage evidence and independent remote connectivity evidence before any separately authorized R01-A decision.

## 9. F09 staging isolation

The harness rejects injected transports in live mode, requires `MockTransport` for synthetic clients, disables environment proxy inheritance, checks HTTPS/fixed routes, and validates the finite spend payload (`connectivity_harness.py:1074-1096,1135-1185,1207-1221`). The harness accepts only its concrete reviewed client boundary and still rejects live construction because project/credential scope is unavailable (`connectivity_harness.py:1093-1096,1423-1428`). The authorization store labels itself synthetic-only and refuses to act as a trusted issuer (`connectivity_harness.py:825-829,937-966`).

The lease and journal implementation durably records intents/outcomes, retains unresolved-release markers, and makes inspection read-only and conservative (`connectivity_harness.py:631-680,1940-1960,2062-2167`). Documentation explicitly limits claims to process-level ordering and says power-loss/storage-controller durability is unproven (`F09_CONNECTIVITY_HARNESS_IMPLEMENTATION.md:205-219,243-251`).

F09 is not ready for a real connectivity check: no provider-verified project/key identity relationship exists; the issuer/runtime OS-account boundary is not verified; live TLS/WSS has not been tested; and process-crash evidence is not a power-loss guarantee. The previous 102-test result is recorded as operator-reported synthetic evidence only.

## 10. Security and trust boundaries

Positive controls observed: fixed URL/route registries, redirect rejection, TLS verification defaults, disabled implicit proxies in reviewed transports, bounded responses, sanitized diagnostics, synthetic-only HTTP tests, no task/Responses API on the F09 client, and a hard false live gate for both R01-A connectivity readiness and F09 verified credential scope. The full F09 run path requires a connected event before completion, then attempts executor stop and session deletion under a shared cleanup budget; uncertain effects retain the lease and do not certify cleanup (`connectivity_harness.py:1544-1672,1775-1816,1855-1958`).

The test offline guard is useful but is not an OS sandbox: `tests/conftest.py:84-105,137-204` patches sockets and known subprocess entry points within selected test processes. It does not prove behavior of an arbitrary descendant process outside the patched boundary. Tests involving subprocesses need explicit child guards and should continue to be limited to synthetic commands.

No repository credential file, environment secret, provider account, or private user state was opened. The only credential-shaped text used during this review was fabricated for the in-memory validator reproduction.

## 11. Test coverage and evidence quality

The suite covers MCP discovery/invocation, fixed-source manual parsing and citations, recommendation metadata matching, F09 synthetic lifecycle/journal/capability-store behavior, and injected Docker command behavior. `tests/test_codex_docker_runtime.py` contains both injected offline tests and seven Docker-marked tests; the marked tests were excluded. `tests/test_r_documentation*.py` use synthetic HTML and `httpx.MockTransport`. Prior reported Docker and Ubuntu/WSL2 runs remain operator claims here; no Docker daemon or WSL distribution was accessed.

The current broad Windows selection did not complete cleanly. It displayed many test errors and two failures, then pytest shutdown failed with `PermissionError: [WinError 5]` while enumerating its `--basetemp`. Exact aggregate counts were not emitted, so no pass/fail total is claimed. A focused run of the recommendation/manual/MCP modules produced 27 passed, 1 deselected, 1 warning when excluding the Windows stdio subprocess test. Including that test produced 27 passed, 1 failed: `test_stdio_subprocess_initialize_and_error`, failing at Windows named-pipe creation. The broader failure is consistent with the separately observed inaccessible pytest temp root; it does not prove all reported test errors share that cause.

## 12. Performance, platform and maintainability

Manual index parsing/search is bounded but synchronous on the async request path (P2-3). The deterministic recommendation logic uses short local provider calls; no uncontrolled expansion or execution is present. The code is Python-specific and currently has no Rust boundary/schema specification; a future Rust port should follow stable JSON schemas and provider contracts after behavior settles, not duplicate business rules prematurely.

The Windows environment used Python 3.14.4 and the repository `.venv`; WSL enumeration returned `E_ACCESSDENIED`. No dependency installation or security-setting change was attempted. A fresh OS-temp directory was used for pytest. The stdio test failed on Windows named-pipe permission, while the other focused tests passed. The seven Docker-marked tests were not run by design.

`ruff check .` passed with warnings about the pre-existing unreadable review/pytest directories. `ruff format --check` did not pass: it reports `connectivity_harness.py` would be reformatted at the current working-tree lines 232, 242, 244, 275, 867, 881, 922, and 1003; no formatter was run to avoid editing an existing file. The selected pytest invocation disabled the cache provider and emitted one non-blocking `PytestConfigWarning` that `cache_dir` is unknown when that plugin is disabled.

## 13. Documentation accuracy

The official manual documentation correctly separates indexing from MCP retrieval and describes limits/untrusted source material. The recommendation response states that architecture suggestions are heuristics, package metadata is current repository metadata, no compatibility claim is made without a target R version, and dependency data is not a transitive graph. F09 documentation distinguishes synthetic results from live compatibility and process-crash ordering from power-loss durability. R01-A remains NO-GO in the readiness sprint report.

Counts such as 72 R01-A selected tests, 102 F09 synthetic tests, and earlier Docker passes are documented as operator-observed; they were not independently reproduced by this Windows session. The review report does not promote those counts to independently verified facts.

## 14. Integration conflicts and dependencies

The stack tool and official manuals are coupled through `KnowledgeService` and server registration: the tool adds local manual citations when available, and its tests depend on mock package providers plus mocked manual results (`service.py:1259-1267`; `tests/test_technology_recommendation.py:337-361`). These should ship/test together. The server tool additions also require a `prompts/list`/`prompts/get` transport check for standard prompts when that workstream changes prompts; the current selected run did not validate every transport.

F09's $2 limit and synthetic authorization claims are separate from R01-A approval/accounting. Do not reuse F09 spend approval as R01-A authorization. The shared pytest configuration changes and current unreadable temp directories also affect any attempt to reproduce tests on Windows; they are not feature code dependencies.

## 15. Prioritized remediation roadmap

| Priority | Finding | Component | Evidence | Recommended action |
|---|---|---|---|---|
| P1 readiness | No independent live service, credential-scope, or historical spend reconciliation evidence; execution gates remain closed. | R01-A and F09 | `lifecycle.py:26,330-336`; `connectivity_harness.py:1093-1096`; readiness reports | Keep NO-GO. Obtain provider-side spend/ownership evidence and a separately reviewed zero-task connectivity result before a new authorization decision. |
| P2-1 | Bearer authorization text passes input secret filters and is echoed in preserved input fields. | Stack tool / Prompt Intelligence | `technology_recommendation.py:297-314`; `service.py:1432-1438`; `quality.py:5-11` | Extend the detector, reject before copying, and add synthetic header/token regression cases. |
| P2-2 | Substring role match treats “database” as evidence for the “data” role. | Stack tool | `technology_recommendation.py:424-431`; reproduced with synthetic metadata | Match whole tokens/phrases or package-specific evidence; add positive and negative tests. |
| P2-3 | Up to 64 MiB of local JSON is synchronously read/parsed/scanned inside an async service call; stat/read is not an atomic bounded read. | Official manual provider | `r_documentation.py:458-490`; `service.py:420-426` | Read at most limit+1 bytes from an opened descriptor, validate the same file object, and move cold parsing/search off the event loop if latency testing warrants it. |
| P3-1 | Build-time `LinkingTo` is grouped with runtime required fields. | Stack tool | `service.py:1172-1185,1389-1398` | Label runtime versus build-time fields explicitly. |
| P3-2 | Formatter check is not clean; Windows stdio/pytest temp verification is unavailable. | F09/tests | `ruff format --check`; test outcomes in §11-12 | Apply formatting in a separate authorized change and rerun the documented suite in Ubuntu WSL2 with a fresh Linux temp directory. |

Recommended order: address the two stack-tool correctness/privacy issues first; clarify dependency metadata; harden/offload manual index reads if latency goals require it; then run Ruff format and the focused/full offline suites in Ubuntu. Keep all live gates closed until provider and spend evidence is separately reviewed.

## 16. Verification commands and actual results

| Command/action | Result |
|---|---|
| `git status --short --untracked-files=normal`; `git log --oneline -25`; `git diff --stat`; `git diff --cached --stat`; `git diff --check` | Read-only inspection. No staged changes. 32 modified tracked files and 8 untracked files before this report. `git diff --check` passed; CRLF warnings only. |
| `python -m ruff check .` (repository `.venv`) | **PASS**, all checks passed; warnings for unreadable pre-existing temp directories. |
| `ruff format --check` on changed Python and related new Python files | **FAIL**, `connectivity_harness.py` would be reformatted; no files modified. |
| Focused: `tests/test_technology_recommendation.py` | **11 passed, 1 warning** (`cache_dir` unknown with cache plugin disabled). |
| Focused offline MCP/manual selection: `tests/test_technology_recommendation.py tests/test_server.py tests/test_r_documentation.py tests/test_r_documentation_mcp.py tests/test_r_documentation_prompt.py -m 'not docker' -k 'not test_stdio_subprocess_initialize_and_error' -q -p no:cacheprovider` | **27 passed, 1 deselected, 1 warning**. Synthetic/manual and in-process MCP paths only. |
| Same focused selection including `test_stdio_subprocess_initialize_and_error` | **27 passed, 1 failed, 1 warning**. Failure: Windows named-pipe `PermissionError: [WinError 5]` before server startup. |
| Cross-workstream offline selection (21 named test modules, `-m 'not docker' -q -p no:cacheprovider`, fresh OS-temp base) | **INCOMPLETE/FAILED ENVIRONMENT RUN**. Many errors and two failures were displayed; pytest shutdown then raised `PermissionError: [WinError 5]` enumerating the temp base, so aggregate counts were unavailable. No pass claim is made. |
| Docker, Managed Agents API, inference, authorization, WSL2 | **NOT RUN** by restriction; WSL enumeration was inaccessible. |

The focused passing command was run with the repository `.venv` Python, `PYTHONDONTWRITEBYTECODE=1`, and a fresh unique temporary base outside the repository. The broad-selection run likewise used a fresh OS-temp base and disabled pytest cache writes. No package was installed.

## 17. Explicit limitations and unknowns

- No live OpenAI TLS/WSS registration, credential identity/scope validation, session creation, task submission, inference, or billing query was performed.
- No Docker container or network was created. Historical operator-reported Docker passes and image IDs were not independently checked in this review.
- The provider manual index is not bundled; current upstream document versions and licensing were not verified by a live refresh.
- Provider-side cost for the four historical R01-A attempts remains unknown from this review; no zero-charge or fixed-charge inference is made.
- Prior Ubuntu/WSL2 test counts remain operator-reported and distinct from the current Windows runs.
- A process crash/orderly filesystem fsync is not proof of power-loss durability or storage-device guarantees.
- Existing unreadable pytest/review directories were not inspected or changed.

## 18. Final recommendation

**R01-A execution: NO-GO. F09 live connectivity: NO-GO.** Keep both gates closed. The next development action is to fix and test the stack-tool secret filter and package-role matching, then rerun focused offline tests and the Ubuntu WSL2 selection. Separately, the next readiness action for R01-A is provider-side historical spend reconciliation; it must not be conflated with the F09 $2 staging limit.
