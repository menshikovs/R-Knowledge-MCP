# Executive summary — independent audit of R-Knowledge-MCP 2.0

| | |
|---|---|
| **Audited commit** | `4d2266c994849ac460514ac2ae6df8a6fc5c180e` (branch `2.0`; equals `origin/2.0`) |
| **Audit date** | 2026-10-27 |
| **Scope** | production server (`src/`), MCP interface in both toolsets, CRAN/Bioconductor/Function Discovery correctness (incl. real upstream data and R 4.5.2 ground truth), security, performance, tests/CI/packaging, the whole `benchmarks/codex_r/` programme, Prompt Intelligence, documentation |
| **Not done** | no model/paid API call, no credentials, no benchmark trial, no R task from the benchmark, no code changes (only files under `audits/`) |
| **Detail** | [FINDINGS.md](FINDINGS.md) (canonical register) · [ARCHITECTURE](ARCHITECTURE_AUDIT.md) · [MCP](MCP_PROTOCOL_AUDIT.md) · [KNOWLEDGE](KNOWLEDGE_CORRECTNESS_AUDIT.md) · [SECURITY](SECURITY_AUDIT.md) · [PERFORMANCE](PERFORMANCE_AUDIT.md) · [TESTING/CI](TESTING_CI_AUDIT.md) · [BENCHMARK](BENCHMARK_SCIENTIFIC_AUDIT.md) · [PROMPT INTELLIGENCE](PROMPT_INTELLIGENCE_AUDIT.md) · [AGENT USABILITY](AGENT_USABILITY_AUDIT.md) · [ROADMAP](ROADMAP.md) · [EVIDENCE_MANIFEST.json](EVIDENCE_MANIFEST.json) |

## 1. Overall assessment

R-Knowledge-MCP is a **carefully engineered, defensively designed, read-only knowledge server that works**: the stdio and Streamable-HTTP transports, protocol negotiation, fixed-route HTTP policy, bounded in-memory archive parsing, provenance envelopes, error semantics, Bioconductor release discovery and the optional Rust accelerator (identical output to Python on 10 real archives) all behaved correctly under test. I found no SSRF, path-traversal, command-execution, regex-DoS or credential-in-result issue, and `pip-audit` reports no known vulnerabilities in the runtime closure.

What is weaker is **verification and measurement, not construction**. The repository's CI is red at this exact commit (confirmed against the real GitHub Actions run); two correctness defects that appear only on *real* CRAN data escaped a mock-only test suite; and the benchmark programme — twice the size of the product — has not produced evidence that can show whether the server helps an agent. The project's own reports say this candidly ("exploratory", "no causal effect estimated"); the audit confirms it and shows why.

**Findings: 0 P0 · 3 P1 · 17 P2 · 16 P3 (36 total).** Confidence is "confirmed" for 33 (reproduced, evidence stored; for SEC-001 the defect is confirmed but exploitability depends on an unverified upstream precondition) and "possible" for 3 (SEC-008, SEC-009, KC-004: code reading or synthetic data only).

## 2. Readiness by audience

| Audience | Verdict | Why |
|---|---|---|
| **1. Local individual use** (stdio, own machine) | **Ready, with known defects** | Works end to end; read-only and bounded. Known gaps: some packages' docs fail (KC-001), discovery says "partial" for ~half of packages (KC-002), version-spelling mismatch (KC-003), two R-manual tools empty until a manual step (AGT-002) |
| **2. Public open-source adoption** | **Not yet** | CI red (CI-001…004); no tags/CHANGELOG/SECURITY.md/release workflow; docs drift (DOC-001); version `0.1.0` on a "2.0" branch; broken links to untracked files |
| **3. Remote authenticated hosting** | **Not ready** | No authentication, rate or idle limits (SEC-002; spec says MUST rate-limit); quadratic parser stalls the loop ≈ 1 min (SEC-001); URL/question logging (SEC-003); unpinned supply chain (SEC-007). The security document states several of these honestly |
| **4. Research benchmarking** | **Infrastructure strong; inference not yet valid** | Excellent isolation, controls and telemetry ideas; but no confirmatory design, saturated/floor tasks, scorer false negatives, uncontrolled egress, no token/cost data, evidence not in the repository (BEN-001…005, CI-004) |
| **5. Stable production deployment** | **Not ready** | Union of 2 and 3, plus no load test, observability or release automation |

## 3. Release blockers (for a public 2.0 tag)
1. **CI-001/002/003/004** — the test workflow cannot pass: bare `pytest` cannot import `benchmarks` (22–23 modules), `duckdb` is not installed by CI, 8 tests need a git-ignored manifest, frozen hash pins depend on line endings. After the first two one-line fixes a Linux run still fails 17 tests.
2. **KC-001** — `get_function_docs` fails for *every* function of a package when one Rd file declares its own encoding (real: CRAN `cluster`, shipped with R).
3. **BEN-005 / DOC-001** — reports cite evidence and documents that are not in the repository.

## 4. Principal risks
- **Knowledge quality:** `partial` carries little information (KC-002); the two function tools disagree about versions (KC-003) and encodings (KC-001) — the very relationship the Function Discovery feature exists to make reliable.
- **Availability:** one hostile or merely huge DESCRIPTION can block the event loop for about a minute (SEC-001); shared HTTP hosting has no limits (SEC-002).
- **Decision risk:** investing further in features (templates, analyzers, tools) while the benchmark cannot detect an effect (BEN-001, BEN-004).
- **Evidence integrity:** "frozen" inputs and results are not verifiable by a third party (BEN-005, CI-004).

## 5. Strengths (evidence-based, not a feature list)
- Defence in depth where it matters: fixed route allow-lists per repository, redirects and proxies off, bounded gzip/tar handling (hostile 1 MB archive expanding to 133 MB peaks at 164 MB and is rejected), no archive extraction to disk, no R/Rd/script execution, singleflight and cancellation correct (50 concurrent identical fetches → 1 upstream request).
- Honest provenance: every result carries source URL, actual check time (even for cached data), verification status; failures are explicit and never replaced by substitutes; `requested_version_unavailable` instead of silent substitution — exactly what `AGENTS.md` demands.
- Real-data accuracy: on version-matched packages, discovered exports and aliases equal R's own (`boot`, `codetools`), and on seven more (MASS, rpart, nnet, class, foreign, KernSmooth, nlme) the sets are identical despite differing versions; Bioconductor release/R mapping is dynamic and correct (release 3.23, devel 3.24 today); the server's `docs_not_found` suggestions corrected a hallucinated function name in the benchmark's own history (`validate::violations` → `violating`).
- Benchmark craftsmanship: hidden verifiers with reference/mutant controls, networkless scoring after the agent is destroyed, versioned scorers with read-only rescoring, and unusually candid reports.
- Measured: 84 % line+branch coverage of production code, Rust parity and CI `native`/`docker` jobs green.

## 6. Strategic view (Phase K, short)
The problem is real: agents hallucinate API names, misstate current versions and Bioconductor/R pairings, and cannot always browse. The server's **strongest** capabilities are (1) *does this function/alias exist in the current package*, (2) current version/metadata, (3) the R↔Bioconductor mapping, (4) verified provenance. Its **largest unrealised** value is **version-pinned documentation for an installed older version** — today only the current release is available (CRAN `Archive/` is unsupported) — which is the one thing neither model memory nor a quick web search replaces. Prompt Intelligence and the static analyzers have no evidence of value over a capable model; the first has an unvalidated classifier (70 % on an exploratory set) and a score that rewards keywords. The only observed benefit in the frozen data is use-conditional on D01 (all 6 trials that used MCP scored 3–4/4; all 6 that did not scored 1–2/4), where the no-browsing agent had no other source — suggestive, not generalisable. Cost is real: one trial returned ≈ 241 KB (≈ 27–60 k tokens), about the whole task budget.

## 7. Terminal summary items (also printed in the session)
1. Commit: `4d2266c994849ac460514ac2ae6df8a6fc5c180e`.
2. Overall: sound, honest, defensively built server; verification/measurement lag; not yet ready for public release or remote hosting.
3. By severity: P0 0, P1 3, P2 17, P3 16.
4. Five most important confirmed problems: **CI-001** (CI cannot collect tests), **KC-001** (mixed-encoding Rd breaks all docs for a package), **BEN-001** (no valid evidence of MCP effect), **KC-002** (discovery "partial" for ~half of packages for mostly harmless reasons), **SEC-001** (quadratic DESCRIPTION parse blocks the loop ≈ 1 min; exploitability depends on upstream).
5. Five highest-value improvements: (i) green CI in four small steps (Stage 0); (ii) per-file Rd decoding + meaningful partial status + version normalisation (KC-001/002/003); (iii) real-archive fixture suite and nightly real-data contract job; (iv) a confirmatory, pre-registered, calibrated benchmark with enforced egress and usage accounting; (v) version-aware docs via CRAN Archive/Bioconductor history plus usage-oriented descriptions and error-carried next steps.
6. Verification incomplete for: live GitHub/Context7 paths, R-manual refresh, third-party MCP clients, SDK 2.x, load under concurrent clients, whether CRAN would accept a hostile DESCRIPTION (SEC-001 exploitability), five R-dependent launcher tests, GitHub job logs, any model behaviour.
7. Next engineering milestone: **"Green and trustworthy 2.0-rc"** — Stage 0 of `ROADMAP.md` plus KC-002/KC-003 and the real-data fixture suite (≈ 2–3 weeks), ending with a green four-version CI and a nightly real-upstream contract check.
