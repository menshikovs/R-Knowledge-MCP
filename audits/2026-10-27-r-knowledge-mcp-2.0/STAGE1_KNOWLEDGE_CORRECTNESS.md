# Stage 1 — Knowledge correctness (KC-002, KC-003, real-archive regressions, nightly contract)

Status: **implementation complete and verified locally; not committed, not pushed, no GitHub CI and no nightly run yet.**
Everything below is local evidence (Windows, WSL Ubuntu, uv Python matrix, live read-only requests to CRAN and
Bioconductor) unless it says "GitHub". Raw outputs and scripts: `stage1-evidence/`.

## 1. Baseline

| | |
|---|---|
| Branch | `feature/stage1-knowledge-correctness`, created from `origin/2.0` |
| Baseline SHA | `8e8ace0e85943a8bad3ecf60fe2b824f38315b54` (merge of PR #26: Stage 0, Context7 removal) |
| CI at baseline | GitHub Actions run 40668856490 on `8e8ace0`: success |
| Working tree at start | clean except the untracked local `audits/*.7z` |
| Environment | Python 3.14.4 (`.venv`), mcp 1.30.0, httpx 0.28.1, pydantic 2.14.1, ruff 0.17.1; R 4.5.2 (own scripts only); Docker 29.8.2 |
| Consolidated tools | 16 before and after; names, annotations and parameter lists unchanged (`tools/list` diff against `8e8ace0`: identical names, properties, required, `additionalProperties`, annotations, both toolsets) |

## 2. Code changes (9 modified files; new files listed below, outside `audits/`)

| File | Change |
|---|---|
| `src/cran_knowledge_mcp/parsers.py` | diagnostic class table (`info` / `incomplete` / `unestablished`); `useDynLib`/`import` options exempt from the literal check; `S3method(pkg::generic, class)`; Rd scanner by brace depth (`_rd_structure`, linear); `rd_coverage()` (`rd_index_record()` keeps its 4-tuple); escaped `\name{\%>\%}`; duplicate `\alias` no longer counted as non-literal; unknown top-level calls are `unestablished` |
| `src/cran_knowledge_mcp/function_discovery.py` | aggregates diagnostics (count + ≤3 examples), `completeness`, `diagnostics`/`diagnostics_count` in pages; `issues` keeps only limiting codes; unavailable topic names now also mark Rd `partial` |
| `src/cran_knowledge_mcp/http.py` | `version_match`, `version_resolution`, `unavailable_version_details`, `EQUIVALENCE_RULE` |
| `src/cran_knowledge_mcp/providers/base.py` | discovery uses `version_match` at both call sites (KC-003); `requested_package_version`, `version_resolution`, `completeness` in results; docs result carries `version_resolution` |
| `src/cran_knowledge_mcp/service.py` | versioned docs use the shared rule, structured unavailable details, resolution record on success and on `docs_not_found` |
| `src/cran_knowledge_mcp/upstream_contract.py`, `scripts/contract_upstream.py` | nightly runner (new) |
| `.github/workflows/upstream-contract.yml` (new), `tests.yml` | scheduled contract workflow; native job also runs the new discovery tests |
| `tests/…` | `test_discovery_status.py`, `test_version_contract.py`, `test_real_archives.py`, `test_stage1_e2e.py`, `test_upstream_contract.py`, `archive_corpus.py`, `fixtures/archives/` (9 archives, `MANIFEST.json`, `fetch.py`) |
| `docs/FUNCTION_DISCOVERY.md`, `docs/UPSTREAM_MONITORING.md`, `.gitattributes` | documentation; archives marked binary |

Rust is unchanged: only `scan_calls` and the search index are native; NAMESPACE/Rd semantics live in Python above
that adapter, so the two backends cannot diverge in status semantics (and parity is tested, §9).

## 3. KC-002 — root cause and evidence

**Root cause (confirmed in `parsers.py` before the change).** Three independent over-approximations:
1. every NAMESPACE argument had to be a literal, and `TRUE` is not: `useDynLib(pkg, .registration = TRUE)` was `namespace_nonliteral_arguments`;
2. `_rd_complete()` marked an Rd file incomplete if `\if`, `\ifelse`, `\Sexpr`, `\eval`, `\newcommand`… occurred **anywhere**, including roxygen's `\if{html}{\out{…}}` formatting blocks;
3. `\name{\%>\%}` (the pipe operator, in many roxygen packages) failed the literal-name regex although `\alias` already understood the same escape.
Beyond the audit, the real-data cross-check found two more things: `S3method(pkg::generic, class)` (delayed registration, e.g. `R6`, `modelimpact`) was reported as non-literal, and an arbitrary top-level call such as `eval(...)` was classed like an ordinary bad argument although it can declare anything.

**Semantics now (tested, documented in `docs/FUNCTION_DISCOVERY.md`).**

| completeness | `verification_status` | meaning |
|---|---|---|
| `complete` | verified | nothing unusual |
| `complete_with_diagnostics` | verified | only `info` observations that cannot change what is enumerated |
| `incomplete` | partial | known gap (`exportPattern`, non-literal arguments, unreadable Rd, non-literal alias/name) |
| `unestablished` | partial | cannot be determined statically (missing/conditional NAMESPACE, arbitrary calls, top-level `\Sexpr`/`\RdOpts`, `\if` bodies containing Rd structure, unbalanced braces) |
| fatal | error envelope | retrieval/size/format errors are not statuses (unchanged) |

Scoping decision, verified on R 4.5.2 (`stage1-evidence/rd_sexpr_experiment/`: two own Rd files and `tools:::prepare_Rd(stages = "build")`, output included): a **top-level**
`\Sexpr[results=rd,stage=build]` that returns an alias adds it to the Rd alias metadata; the same call **inside a
section** does not. So only top-level dynamic content (and `\if` bodies that contain `\alias`/`\name`/macros) makes
the alias set undeterminable; nested ones are `info`. Unknown diagnostic codes default to `incomplete`.

**Before/after on the audit's seeded 30-package sample** (exact versions re-fetched from CRAN/Archive, SHA-256 in
`stage1-evidence/archives30_manifest.json`; raw rows `kc002_before_after.json`). The baseline reproduces the audit
exactly (16 verified / 14 partial).

| | before | after |
|---|---|---|
| verified | 16 | 25 |
| partial | 14 | 5 |
| completeness | – | 18 complete, 7 complete_with_diagnostics, 5 incomplete |

| package | before (cause) | after | evidence |
|---|---|---|---|
| runner 0.4.6, ggnext 0.1.0, RBMRB 3.0.0, einops 0.2.1 | partial (`rd_literal_coverage_partial`) | verified, complete_with_diagnostics | only `\if{html}` formatting blocks (`rd_conditional_formatting`) |
| fabletools 0.8.0 | partial (`rd_literal_coverage_partial`) | verified, complete_with_diagnostics | `\if` formatting ×2 and `\Sexpr` inside sections ×2 |
| checkglobals 0.1.4, gamesGA 1.1.3.7 | partial (`namespace_nonliteral_arguments`) | verified, complete_with_diagnostics | `useDynLib(…, .registration = TRUE)` |
| tidyREDCap 2.1.0 | partial (`rd_literal_coverage_partial`) | verified, complete | `\name{\%>\%}` |
| modelimpact 1.1.0 | partial (`namespace_nonliteral_arguments`) | verified, complete | 10 × `S3method(ggplot2::autoplot, …)` now enumerated |
| Rcan 1.3.92, TSEtools 1.0.0, nptest 1.2, swCRTdesign 4.1, ggmr 0.1.1 | partial (`export_patterns_not_expanded`) | **partial, incomplete** (unchanged) | `exportPattern()` cannot be expanded statically: genuinely partial |

No percentage was targeted. **Independent check against R itself:** for all 30 packages (and the 9 fixtures) the
alias set, the explicit export set (`export`, `exportClasses`, `exportMethods`) and the S3-method set equal what R 4.5.2
parses with `tools::parse_Rd` / `parseNamespaceFile` (no package code is run; `r_crosscheck.R`,
`compare_with_r.py`; results `r_comparison_30.json`, `r_comparison_fixtures.json`: 0 differences). The reclassified
packages were therefore already enumerated correctly; only their label was wrong. Entity counts are identical before
and after for 29 of 30 packages; `modelimpact` gains its 10 `S3method(ggplot2::autoplot, …)` methods, and the pipe
topics are named `%>%` instead of their file name. Both runs use the same archive bytes; the "before" run is the code of
`8e8ace0`. Discovery time over the 30 archives: 0.47 s before, 0.45 s after.

## 4. KC-003 — root cause and evidence

**Root cause.** `providers/base.py` compared the requested and the repository version with `!=` on the strings
while `service.py` (docs) used `version_parts`. Real trigger: R prints `packageVersion("MASS")` as `7.3.66` while
DESCRIPTION says `7.3-66`. Verified on R 4.5.2 (`numeric_version`): `2.10-1 == 2.10.1 == 2.10-1.0 == 2.10-01` are all
TRUE, `1.0 == 1` is TRUE (although `compareVersion("1.0","1")` is 1), `1.10 == 1.1` is FALSE. The existing rule was
right; discovery simply did not use it. The live nightly-contract run (§7) passes the dot spelling of `MASS 7.3-66` to discovery; the documentation tool uses the same rule and is covered offline.

**Contract (`http.version_match` / `version_resolution`, tested).** Every successful answer carries
`requested_package_version`, the source's own `package_version` (the resolved spelling is never replaced) and
`version_resolution {requested, resolved, match, verified_for_requested_version, version_scope[, equivalence_rule]}`
with `match` ∈ `not_requested`, `identical`, `equivalent`.

| Situation | Behaviour |
|---|---|
| none requested | resolved current version, `match: not_requested` |
| exact / equivalent spelling | success, `identical` / `equivalent` (rule stated) |
| older version | `requested_version_unavailable`, `requested_relation: older_than_available`, `reason: historical_versions_not_supported`, `substituted: false`; no data returned, no archive fetched |
| nonexistent / newer | same code, `newer_than_available`, `not_in_repository_index` |
| other repository/release | package absent there → `package_not_found`; Bioconductor release is selected by `bioc_version`, scope `selected_bioconductor_release` |
| upstream failure | keeps its own code (`source_unavailable`, …), never a version error |
| malformed (`v2`, `2..10`, empty, NUL, full-width digits, >100 chars) | `invalid_input` before any fetch |

Not implemented (out of scope, documented): historical CRAN versions from `Archive/`; the audit lists that as a
roadmap item. Cache keys: archives are cached by artifact (URL + content), snapshot tokens bind version and digest;
`test_versions_do_not_leak_through_caches` flips a package from 1.0 to 2.0 with the HTTP cache disabled and checks
that 2.0 shows no 1.0 entity, 1.0 is refused, a 1.0 snapshot yields `source_identity_drift`, and 1.0 text is never
returned.

**Cross-tool consistency.** For the 7 CRAN fixtures and 1 Bioconductor fixture the chain
`search_packages → list_package_functions → get_function_docs` (first/middle/last alias) agrees on package,
repository, version, scope and archive provenance, and the documentation `archive_member` is among the alias's
`documentation_topics` (`test_stage1_e2e.py`).

## 5. Real-archive fixture inventory (`tests/fixtures/archives/`, 1.49 MB)

Each entry in `MANIFEST.json` has package, version, repository, original URL, SHA-256, size, retrieval date, licence
(from DESCRIPTION), reason and expected observable behaviour; `fetch.py` re-downloads from the pinned URL (fixed hosts,
no redirects, size cap) and refuses a digest mismatch. Archives are parsed in memory by the bounded parser, never
extracted or executed. Retrieved 2026-10-28.

| package | version | repository | bytes | SHA-256 | licence | completeness | covers |
|---|---|---|---|---|---|---|---|
| cluster | 2.1.8.3 | CRAN | 373042 | `e240bebe2aa85f9d9f674cd7addc3dc9023f9e4c3f462eca94e582e22a5ce2e9` | GPL (>= 2) | complete_with_diagnostics | mixed Rd encodings (KC-001), `useDynLib`, shared topics |
| R6 | 2.6.1 | CRAN | 64507 | `59c6eba8b1b912eb7e104f65053235604be853425ee67c152ac4e86a1f2073b4` | MIT + file LICENSE | complete_with_diagnostics | `S3method(utils::.DollarNames, R6)` |
| BiocGenerics | 0.58.1 | Bioconductor 3.23 | 57572 | `6911559f0b2b5a07081cd21b6738aa4c6048509b23425cc3ebafc0b4cb011a98` | Artistic-2.0 | complete | S4 `exportMethods`/`exportClasses`, Bioconductor metadata |
| checkglobals | 0.1.4 | CRAN | 35286 | `c36c18ab5ad857b3183feaa0fa2c73c26177f63666d819bf499259e53f69f957` | MIT + file LICENSE | complete_with_diagnostics | `useDynLib(.registration=TRUE)`, S3 methods |
| RBMRB | 3.0.0 | CRAN | 50986 | `37f16303396a3ba46651c1a5bbc1fc748578647d6b40dcfee297dfb0820b510e` | GPL-3 | complete_with_diagnostics | conditional Rd formatting |
| TSEtools | 1.0.0 | CRAN | 16531 | `e398afa2a3d7dd2f183d81236a7f33fd364b8c192b403b544d93d2cb958f0d01` | BSD_2_clause + file LICENSE | incomplete | `exportPattern()` (must stay partial) |
| einops | 0.2.1 | CRAN | 221807 | `fb49a16d64fb225c706cc84c628385d33ceb6c0a537b81ab2616bd3de7129e59` | MIT + file LICENSE | complete_with_diagnostics | escaped-percent topic, many methods |
| modelimpact | 1.1.0 | CRAN | 449408 | `d87564b7f8e13440fdb5789742a31694340b74520cd44cbb5f706665af02060c` | MIT + file LICENSE | complete | `S3method(ggplot2::…)` ×10, large export list |
| fabletools | 0.8.0 | CRAN | 216993 | `e96c553879d3bb214d735d4b934047639f710423c65ef3d8a1f027107c45610d` | GPL-3 | complete_with_diagnostics | 88 topics, nested `\Sexpr`/`\if` |

All are open-source licences permitting redistribution; the licence text is inside each archive. The Bioconductor
fixture comes from release 3.23 as served on 2026-10-28.

## 6. Mutation evidence (tests catch the original defects)

Re-introducing the old behaviour on the new code: strict string version compare in discovery → 5 of 52 version tests
fail; harmless constructs classed as limiting again → 18 of 100 status/archive tests fail. The nightly runner turns
red (`fail`) for a KC-002 or KC-003 regression and `inconclusive` for an outage (offline tests).

## 7. Nightly upstream contract

`.github/workflows/upstream-contract.yml` (daily 05:41 UTC and `workflow_dispatch`, read-only, no secrets, 25-minute
cap, separate from PR CI) runs `scripts/contract_upstream.py` over `cluster`, `R6`, `MASS`, `rpart` and
Bioconductor `BiocGenerics`. Structural invariants only (never exact lists): identity, snapshot/archive digests,
provenance hosts and times, completeness vs status, diagnostic classes, discovery/docs agreement, the version
contract including refusal of a historical version, CRAN checksum verification level, the `cluster` encoding case.
Outcomes `pass` / `fail` / `inconclusive` (upstream unavailable, rate limited, missing, or an archive that disagrees with the repository's own index; `invalid_source` and `source_too_large` come from this project's parsers and limits and are `fail`); exit 0/1/2;
only 1 fails the job, 2 raises a warning annotation. It records upstream versions, archive SHA-256 and check times in
`upstream-contract-results.json` (uploaded as an artifact, 30 days) and a job summary. HTTP uses the project's layer
(explicit timeout, one bounded retry, byte limits, no redirects, no caller URLs); the runner adds a 150 s per-package
deadline and a 100-page bound. Expected values are never rewritten automatically.

**Execution status.** Offline behaviour: 9 tests (pass, report schema and no-secret content, outage → inconclusive,
vanished package → inconclusive, corrupt archive → fail, KC-003 and KC-002 regressions → fail, exit codes, bounded layer). **Local live run**
against the real CRAN/Bioconductor on 2026-10-28: 5 of 5 `pass` (`stage1-evidence/live_contract_local_run.json`).
**The GitHub Actions workflow has not run**; do not treat it as verified until a `workflow_dispatch` (and then the
scheduled runs) succeed on the default branch.

## 8. Public API compatibility

* Tool names, count (16 consolidated; legacy 34), annotations, input parameters: unchanged (`tools/list` compared with `8e8ace0` for both toolsets: identical).
* Additive response fields: `coverage.completeness`, `diagnostics`, `diagnostics_count`, `completeness`,
  `requested_package_version`, `version_resolution`; method entries may carry `generic_package`; `requested_version_unavailable`
  details gain `requested_relation`, `reason`, `substituted`, `version_scope`.
* Behaviour changes to note: (1) many packages that were `partial` are now `verified` (25/30 vs 16/30 on the sample);
  consumers that read `verification_status` or `issues` as "anything unusual" should read `completeness`/`diagnostics`
  instead; (2) `issues` no longer lists harmless observations; (3) equivalent spellings of the current version are
  accepted by `list_package_functions` (previously `requested_version_unavailable`); (4) `S3method(pkg::generic, …)` and
  `\name{\%>\%}` produce entities that were missing or file-named; (5) a topic whose name is unusable now also marks Rd
  `partial`; (6) unknown top-level NAMESPACE calls are `unestablished` instead of `namespace_nonliteral_arguments`
  (status unchanged: partial).
* Benchmark: the frozen harness and results are untouched. Future benchmark runs will observe the new `issues` and
  `verification_status` semantics; that is a measurement change, not a harness change.

## 9. Test results (commands and counts)

All local; none of this is GitHub CI. Evidence logs in `stage1-evidence/` (user names replaced by `<user>`).

| Check | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | pass / pass (278 files), Windows, Ubuntu, Python 3.11, 3.12, 3.13, 3.14 |
| `pytest --collect-only -q` | 1 851 collected (Stage 0.5: 1 655), 0 errors |
| Windows 11, Python 3.14.4, Docker running, full `python -m pytest` | **1 708 passed, 143 skipped, 0 failed** (8 min 51 s); none of the 143 skips is in a Stage 1 test file (same POSIX/PTY/Linux-only/image-opt-in categories as Stage 0.5) |
| Ubuntu (WSL2), Python 3.14.4, R/termr/Docker, `BENCH_PYTHON` set, full `pytest` | **1 772 passed, 79 skipped, 0 failed** (8 min 18 s). Skips: PyO3 module not installed in that venv 55 (parity is run with the module installed, see the Rust row), private bundle 8, historical results 9, image opt-ins/pinned images 7 |
| Python 3.11 / 3.12 / 3.13 / 3.14 (uv venvs, `.[dev,analytics]`): install, ruff, full collection, 10 Stage 1 + Stage 0 + discovery files | each **303 passed, 31 skipped** (skips = PyO3 parity tests without the extension). The full suites were **not** rerun on 3.11-3.13 this stage |
| Python/Rust parity (Windows, built `maturin` extension, ABI 3, active: `{'native_accelerators': True}`) | `test_native_parity`, `test_function_discovery(_replay)`, `test_discovery_status`, `test_real_archives`, `test_stage1_e2e`, `test_version_contract`, `test_upstream_contract`: **304 passed, 0 skipped**. The real-archive parity test compares the whole `DiscoveryIndex` and several pages for all 9 archives with and without the native scanner |
| Rust | `cargo fmt --check`, `cargo clippy --release -- -D warnings`, `cargo test --offline` (4 tests): pass (Rust sources are unchanged in Stage 1) |
| New tests | `test_discovery_status` 63, `test_version_contract` 52, `test_real_archives` 44, `test_stage1_e2e` 29 (includes stdio subprocess, Streamable HTTP over ASGI, MCP session schema validation), `test_upstream_contract` 9 |
| MCP schema compatibility | `tools/list` of both toolsets compared with `8e8ace0`: identical (16 / 34 tools) |
| stdio / HTTP smoke | covered by `test_stage1_e2e` (offline, no network) and the existing `test_server` suites |
| Wheel | builds (50 files); installed in a clean 3.11 venv `r-knowledge-mcp --help` works and `upstream_contract` imports; no `tests/`, `benchmarks/`, `audits/`, archives |
| Docker | `docker build` OK, `--help` OK, 16 consolidated tools (the Dockerfile copies only `pyproject.toml`, `README.md`, `LICENSE`, `src`) |
| Live (read-only, local) | `scripts/contract_upstream.py` against real CRAN and Bioconductor: 5/5 pass |
| GitHub Actions | **not run** (nothing pushed) |

Commands: `python -m ruff check .`; `python -m ruff format --check .`; `python -m pytest --collect-only -q`;
`python -m pytest -rs`; for the 30-package study `stage1-evidence/fetch_archives.py`, `classify_archives.py`
(old and new source trees), `extract_for_r.py` + `r_crosscheck.R` + `compare_with_r.py`.

## 10. Security and performance regression findings

* Bounded archive reading, `dcf()` linearity, per-file Rd encoding, path safety and Stage 0 behaviour: the Stage 0
  regression suites pass unchanged (§9).
* **New finding fixed during Stage 1:** a first version of the Rd macro scanner re-scanned every `\if` body, giving
  1.13 s on a 288 KB nested-conditional file (≈ 128·n). Brace pairs are now computed in one pass and structural macros
  are located once (bisect): 0.074 s for the same input; all adversarial shapes (sequential, unclosed, nested, 2 MB of
  backslashes, 200 000 braces) run in ≤ 0.25 s. `test_rd_scanning_is_linear_on_adversarial_input` guards it.
* Discovery work still runs in `asyncio.to_thread`; no new network access, redirect, host or recursion; the nightly
  runner is bounded (5 packages, ≤ 100 pages, 150 s each) and read-only.
* The wheel (50 files) contains the new `upstream_contract` module and none of `tests/`, `benchmarks/`, `audits/` or
  the archives; Docker image builds and lists 16 consolidated tools.

## 11. Remaining limitations

* GitHub CI for these changes has not run; the nightly workflow has not run on GitHub.
* Only the current repository version is available (no CRAN `Archive/` history).
* `exportPattern()` and conditional NAMESPACE blocks remain partial by design; static analysis never proves callability.
* Delayed-registration generics are enumerated but not resolved against the other package; the `S3method` forms with
  non-identifier generics remain unsupported.
* The 30-package sample is the audit's; it is not a statistical estimate of CRAN as a whole.
* Real-archive tests cover 9 packages; larger corpora (S4-class-heavy Bioconductor packages such as `Matrix`) are only
  exercised by the nightly sample.
* The untracked local archive `audits/2026-10-27-r-knowledge-mcp-2.0.7z` is still not part of any commit.

## 12. Final review before integration

One significant issue was found and fixed before the commit: the nightly runner treated `invalid_source` and `source_too_large` as upstream outages, although both are raised by this project's own bounded parsers and limits (a parser regression or a package outgrowing a limit would have been reported as `inconclusive`). They are now failures; a new test feeds a corrupt archive and expects `fail`. New tests in total: 197 (196 listed above plus this one).
