# Prioritised remediation roadmap

Commit `4d2266c`. Finding IDs are defined in [`FINDINGS.md`](FINDINGS.md). Effort is engineer-time for someone who knows the codebase (S ≤ 1 day, M ≈ 2–5 days, L > 1 week). Order within a stage is priority order. Nothing here is implemented by this audit.

Guiding rule used for ordering: *restore the ability to verify first; fix what returns wrong or missing knowledge second; make measurement trustworthy third; only then reshape code or surface.*

## Stage 0 — Immediate blockers (≈ 1 week)

| # | Task | Fixes | Expected impact | Effort | Prerequisites | Risk | Success measured by |
|---|---|---|---|---|---|---|---|
| 0.1 | `pythonpath = ["src", "."]` in `[tool.pytest.ini_options]`; add a `pytest --collect-only -q` step | CI-001 | CI can run tests at all (22–23 modules uncollectable today) | S | — | none | `pytest --collect-only` reports 0 errors on Py 3.11–3.14 |
| 0.2 | Install `.[dev,analytics]` in CI (or guard the `duckdb`/`streamlit` imports with `importorskip`) | CI-002 | removes the next collection error | S | 0.1 | CI time +1–2 min | 0 collection errors with CI's exact install command |
| 0.3 | Commit a public `SOURCE_MANIFEST.json` or `skipif` the 8 registry tests when absent | CI-003 | removes 8 deterministic failures | S | decision on what may be public | leaks private answer-key sources if committed carelessly | clean-clone run has 0 failures from this module |
| 0.4 | `.gitattributes` (`benchmarks/** -text`), re-pin the six CRLF-hashed files from `git show HEAD:` bytes, fix stale assertions (telemetry schema `1.1`→`1.2`; `environment_error` type) | CI-004, TST-002 | frozen inputs verifiable on Linux; Docker-enabled runs stop failing | S–M | 0.1–0.3 | re-pinning changes frozen digests: record old→new in a report, do not edit historical results | Linux CI green incl. the pin test; `git ls-files --eol` shows no `w/crlf` under `benchmarks/` |
| 0.5 | Decode Rd per file (`\encoding{}`; skip-and-report undecodable) in `_alias_index`; regression test from a latin1 Rd | KC-001 | restores docs for `cluster` and any mixed-encoding package; aligns discovery and docs | S | — | low; alias sets can grow | `get_function_docs("cluster","agnes")` succeeds against the real package in the nightly smoke |
| 0.6 | Make `dcf()` linear and run DESCRIPTION parsing in a thread | SEC-001 | removes the only multi-second event-loop stall | S | — | none | 700 000-line field parses < 1 s; unit test |

Exit criterion for Stage 0: the `Tests` workflow is green on Python 3.11, 3.12, 3.13, 3.14, `docker` and `native` jobs unchanged-green, and the Linux full run has no failures except tests that explicitly require R/termr/Docker images (those must `skip`, not fail, when the resource is missing).

## Stage 1 — Correctness and reliability (≈ 2–3 weeks)

| # | Task | Fixes | Impact | Effort | Prereq | Risk | Success |
|---|---|---|---|---|---|---|---|
| 1.1 | Meaningful discovery status: exempt `useDynLib` arguments, scope the macro check to `\name`/`\alias`, report *which* entries are unverifiable | KC-002 | "partial" regains information (47 % of sampled packages today) | S–M | 0.5 | changes an observable status | re-run the seeded 30-package sample: `partial` only where `exportPattern`/conditional NAMESPACE/real non-literals remain; 0 harmless causes |
| 1.2 | Version equality via `version_parts` in discovery; accept R-printed spellings everywhere | KC-003 | no false `requested_version_unavailable` | S | — | none | parametrised test over four spellings for both tools |
| 1.3 | Recorded real-data fixtures: `tests/data/` with 6–8 real source tarballs (cluster, MASS, termr-like R6, compiled `useDynLib`, `exportPattern`, Bioconductor S4) + SHA-256; plus Hypothesis tests for `version_parts`, `dcf`, `aliases`, snapshot paging | TST-001 | catches what mocks hid (KC-001/002) | M | 0.x | repo size (+ ~5 MB) | the two defects above are caught by the fixture suite when reverted |
| 1.4 | Real output schemas: shared envelope model + per-tool payload types; validate `structuredContent` against `outputSchema` in tests | MCP-001, MCP-004 | typed clients, machine-checkable contract | M | — | clients begin validating | schema-conformance test passes for every tool and error path |
| 1.5 | `ambiguous_docs` returns the candidate archive members; keep protocol nits explicit (unknown tool, missing resource) | KC (gap §3.4), MCP-002 | agents can resolve ambiguity | S | — | none | unit test |
| 1.6 | Resolve hard limits to partial results (> 4 000 NAMESPACE directives, > 10 000 entries) | KC-004 | no total failure on very large packages | S | — | none | synthetic large-package test returns `partial` with counts |
| 1.7 | Nightly *real-upstream contract* job: the 15 packages of this audit (versions pinned by SHA of the tarball for the offline part; live for the nightly), assert structural invariants not exact lists | TST-001 | detects upstream drift | M | 1.3 | flaky if asserting too much | stable for 14 consecutive nights |
| 1.8 | Thread-safety review of the parsed-source LRU (lock or copy-on-read); memoise `releases.catalog()`; compare `Release` by value | SEC-008, PERF-001 | removes a latent race and 12 ms/call | S | — | low | concurrency test with eviction under `to_thread` |

## Stage 2 — Benchmark validity (≈ 4–8 weeks; the longest pole)

| # | Task | Fixes | Impact | Effort | Prereq | Risk | Success |
|---|---|---|---|---|---|---|---|
| 2.1 | Commit a redacted, checksummed evidence bundle (or release asset) for every report-cited run; make links resolve; add a CI link check | BEN-005, DOC-001 | third parties can verify the audits | S | decide redaction | leaking secrets: run the existing redaction scan | `linkcheck` reports 0 broken; a fresh clone reproduces report counts from the bundle |
| 2.2 | Scorer calibration: every scorer gets reference + ≥ 3 wrong strategies + ≥ 5 independent correct alternatives (other URL, ordering, key format); replace exact-membership/hidden-schema gates (publish schemas/enums in the task text); accept official URLs by host+pattern verified against package identity | BEN-002 | removes false negatives (E01 0/6 at a correct fix; D01 URL) | M–L | 2.1 | rescoring changes numbers: version scorers, never rewrite history | 0 false negatives on the alternative set; scorer digest in every record |
| 2.3 | As-of semantics: snapshot date as an explicit task parameter, tasks written against *current* facts with an auto-refreshed key (or MCP-side as-of via archives) | BEN-002 | removes version-drift failures | M | 3.x (archive support) optional | complexity | tasks pass when the live repository changes by a patch release |
| 2.4 | Runner design: seeded randomised/counterbalanced order, one configuration per analysis, ITT accounting, enforced egress (internal network + logging allow-list proxy) or recorded network use, token budget enforced *or* removed, usage/cost recorded | BEN-003 | comparable arms, visible external information | M–L | — | cost; requires proxy | every trial record has order seed, egress log, usage; analysis refuses to pool across configuration ids |
| 2.5 | Task suite v2: ≥ 30 tasks with hidden behavioural verifiers, strata (installed≠latest, hallucination-prone API, Bioconductor/R pairing, MCP-irrelevant controls); keep oracles private; finish H-suite (7 of 10 missing) | BEN-004 | non-saturated, discriminating | L | 2.2 | authoring cost | pilot: no task at floor/ceiling for both arms; control tasks show no MCP-induced regression |
| 2.6 | Observability for causal attribution: retain bounded request arguments and returned aliases/versions per call with provable call ids; verification of claim↔evidence (v2.1 style) for all D/E tasks | BEN-001 | can link discovery → docs → answer | M | 2.4 | privacy: redact | ≥ 95 % of calls with client/server identity confirmed |
| 2.7 | **Confirmatory experiment** per `BENCHMARK_SCIENTIFIC_AUDIT.md` §7 (pre-registered; ≥ 30 tasks × 3 sessions × 2 arms) | BEN-001 | first valid estimate of the MCP effect with an interval | L (compute budget) | 2.1–2.6 | spend; requires approval | pre-registration frozen before first run; report with task-clustered 95 % intervals |

## Stage 3 — Architecture and performance (≈ 3–4 weeks, parallelisable after Stage 1)

| # | Task | Fixes | Impact | Effort | Prereq | Risk | Success |
|---|---|---|---|---|---|---|---|
| 3.1 | Neutral `rlex` module for the R tokenizer; point `parsers.py`, `visualization_analysis.py` and `native.py` at it | ARCH-002 | restores the "parsers are data-only" rule | S | — | low | import-graph test: `parsers` imports no analyzer |
| 3.2 | Move benchmark telemetry out of the production request path (emit only when run/trial ids are set) | ARCH-001 (A4) | smaller production surface | S–M | benchmark parser test | benchmark depends on the line | production logs contain no `RKMCP_BENCH_TELEMETRY` unless enabled |
| 3.3 | Extract legacy entry points to `legacy_service.py`; extract workspace/framework/recommendation methods | ARCH-001 (A1, A2) | shrinks `KnowledgeService` ≈ 40 %; makes legacy deletable | M | Stage 1 tests | regression in legacy conditions | full MCP contract suite + legacy benchmark smoke unchanged |
| 3.4 | Type-check providers/discovery/parsers (pyright basic) with typed envelopes | ARCH-001 | refactor safety | M | 1.4 | noise | type check in CI, 0 errors in the three packages |
| 3.5 | Single payload copy and deduplicated `sources` in compact mode; report model-visible bytes | MCP-003, PERF | ≈ 50 % fewer context bytes per call | S–M | 1.4 | clients that read only `structuredContent` | bytes per call −40 %+ on the P1-E replay set |
| 3.6 | Shared-deployment load test and concurrency limits (only if remote hosting is pursued) | SEC-002, PERF | knowing the ceiling | M | 5.1 | — | documented RPS/latency at N concurrent clients |

## Stage 4 — Agent usability (≈ 3–6 weeks; depends on Stage 2 for validation)

| # | Task | Fixes | Impact | Effort | Prereq | Risk | Success |
|---|---|---|---|---|---|---|---|
| 4.1 | Description template + usage-oriented default server instructions (U1) | AGT-001 | clearer selection | S | — | none | rubric ≥ 5/6 for every tool; then the U1 experiment |
| 4.2 | Error-carried next steps (`suggested_tool`) (U2) | AGT-001 | fewer guess loops | S | 1.2 | none | replay of historical misses |
| 4.3 | R-manual index: console script, hint in description, hide tools until indexed (AGT-002) | AGT-002 | no dead tools | S | — | none | fresh-install tool list contains only working tools |
| 4.4 | Core-8 default surface behind a flag (U3) | AGT-001 | smaller choice set | S | 4.1 | breaks benchmark comparability: keep `legacy`/`consolidated` | selection-accuracy study |
| 4.5 | **Version-aware docs**: CRAN `Archive/` + Bioconductor historical via a new provider route with exact-version provenance and a size/rate policy (U4) | KC (§4), ROADMAP item already planned | the one capability not replaceable by web search | L | 1.x, security review of a new fixed route | policy: `AGENTS.md` forbids silent substitution — satisfied by exact-version routes | stratum (a) tasks: success with vs without |
| 4.6 | Prompt Intelligence evaluation (4 arms, hidden verifiers) before any new templates; rename the score | PI-001 | evidence-based keep/trim decision | L | 2.5 | spend | decision rule in `PROMPT_INTELLIGENCE_AUDIT.md` §5 |
| 4.7 | `summary` line per result and `installed_version` argument (U4/U7) | usability | faster claims | S–M | 1.4 | — | tokens-to-first-correct-claim |

## Stage 5 — Production readiness (only if remote or shared hosting is a goal; ≈ 4–6 weeks)

| # | Task | Fixes | Impact | Effort | Prereq | Risk | Success |
|---|---|---|---|---|---|---|---|
| 5.1 | Authentication + rate/concurrency limits + idle limits for SSE at a reverse proxy or in-app middleware; deployment guide with TLS | SEC-002 | meets the MCP "SHOULD authenticate / MUST rate limit" bar | M | — | operational | pen-test checklist: unauthenticated GET/POST rejected; limits enforced under load test |
| 5.2 | Logging hardening: silence `httpx` URL logs, unify/replace Context7 redaction, per-field untrusted markers (SEC-003/004/006) | SEC-003/004/006 | privacy, injection hygiene | S–M | — | — | tests from `probe_logs`/`probe_secrets`; envelopes carry `content_trust` |
| 5.3 | Supply chain: lock file with hashes, base image by digest, actions pinned by SHA, SBOM + provenance, HEALTHCHECK, `pip-audit` in CI | SEC-007 | reproducible, auditable builds | M | — | upgrade friction | `pip-audit` clean in CI; image digest recorded |
| 5.4 | Release process: version `2.0.0` consistent across `pyproject`, User-Agent, docs; `CHANGELOG`, `SECURITY.md`, tags, release workflow (no publishing to PyPI without approval) | DOC-001 | traceable releases | S–M | Stage 0 | — | tagged release builds wheel + image from CI |
| 5.5 | Observability: structured metrics (call counts, latency, cache hit/miss, upstream errors) without arguments; `/healthz` for HTTP | operability | M | — | — | dashboards from logs only |
| 5.6 | MCP SDK 2 migration in a separate reviewed change (keep stdio/HTTP, re-examine the per-request lifespan workaround, legacy clients) | maintenance | stay on a supported SDK | M–L | Stage 1 contract tests | protocol regressions | all transports pass the conformance matrix in `MCP_PROTOCOL_AUDIT.md` §3 |
| 5.7 | Documentation drift sweep and a CI doc-consistency check (tool counts, env vars, links) | DOC-001 | trust in docs | S | — | — | CI fails on a mismatched tool count |

## What not to do
- Do not expand templates, tools or analyzers before the Stage 2 experiment exists; the surface is already larger than the evidence for it.
- Do not "fix" the benchmark by changing scorers *in place*; add versioned scorers and re-score read-only, as the project already does.
- Do not split `server.py`'s registration or `providers/r_documentation.py` for size alone (`ARCHITECTURE_AUDIT.md` §4).
