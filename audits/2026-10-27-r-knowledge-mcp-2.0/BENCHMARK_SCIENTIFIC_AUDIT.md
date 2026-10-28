# Benchmark scientific audit — `benchmarks/codex_r/`

Commit `4d2266c`. IDs refer to [`FINDINGS.md`](FINDINGS.md). No model API, credential, Docker benchmark image or R task execution was used. All numbers below are re-derived from saved artifacts or from reading code; nothing historical was modified.

## 1. What exists

| Component | Content | Assessment |
|---|---|---|
| Legacy pilot `tasks/R01–R12`, `oracle/` | 12 small base-R/tidyverse/SQL/Quarto tasks, 4 test groups each, hidden oracle, `selftest` | small, mostly saturated (§3.1) |
| Knowledge pilot B/C/D/E (16 tasks), `knowledge_pilot*.py`, `verifier/controls/` | package-selection (D), compatibility (E), data/stat tasks (B, C); versioned scorers legacy → v2 → v2.1 | D/E measure access to current facts; scorer contracts partly hidden (BEN-002) |
| Hard suite H01, H04, H10 of 10 specified | hidden verifier with independent oracle, `callr` sandbox, networkless scorer, trusted reference + deliberately wrong strategies (`verifier/controls/`) | **the best-designed part**; only 3/10 implemented; H04 is a documented substitute because `data.table` is absent from the image |
| Runner `run_simple.py` (3 733 lines), `runner/`, `exploratory/` | one session per attempt, disposable Docker workspace, Agents API executor, balanced order only for `b1-discovery` | A/B design issues (§4) |
| Telemetry `telemetry/` (schema 1.2), analytics `analytics/` (DuckDB, Streamlit) | per-call server telemetry, ordinal client/server correlation, derived DB | rich but cannot yet prove call identity (§6) |
| Reports `reports/` (52 files) | frozen audits P1-D, P1-E, B1 rescore, baseline root-cause audit | careful, candid, and mostly *negative* about causal claims |

Strengths worth stating: scorers have reference/mutant controls and offline self-tests; scoring runs after the agent and executor are destroyed, in a networkless container; scoring errors are `scoring_error`/missing, never successes (`manifest.json`, `knowledge_pilot.py:497-531`); historical records are versioned and re-scored read-only (B1 v2.1 rescore preserves the original checksum); every report says "exploratory". The problem is not carelessness; it is that the **design cannot answer the question it is being used for**.

## 2. Evidence base I used

The saved results (`benchmarks/codex_r/results/`, 20 MB, 30 run directories) are **git-ignored and absent from the audited commit** (BEN-005). I rebuilt the project's own DuckDB analytics from them with the project's importer (10.9 s, 91 trials, 25 runs with trials, 22 tasks, 30 run directories imported) and queried it (`evidence/benchmark/bench_stats.txt`, `bench_err.txt`, `bench_d01.txt`). I spot-checked the P1-E claims against the raw `results.json` of runs `20261027T092234Z-5d712f1d` and `…091937Z-29e767cb` (28 calls: 17 `get_function_docs`, 9 `list_package_functions`, 2 `get_package`; scores 3/4 and 1/4; 13 and 12 allowed tools): they match.

## 3. H1 — Validity of the tasks and scorers

### 3.1 Do the tasks measure R problem solving?
- **R01–R12, B, C, H** are legitimate but narrow. R01 ("`clean_records`") is a base-R function with four test groups; the oracle (`oracle/R01.R`) is readable and sound (typed empty output, first valid duplicate, no input mutation, schema rejection). These tasks are **at ceiling**: R01 is 1.0 in 7 of 7 scored trials in both arms; R02, B01–B03, C01–C05, H01, H04, E02, E03 are 1.0 in every scored trial of both arms.
- **No gradient**: with 4 groups per task and a capable model, the legacy suite cannot show improvement and can only show harm.
- **Public oracle/leakage.** The oracle tests, reference solutions and task statements are in the public repository; future models may have seen them. Hidden checks exist (the hard suite's verifier is not exported to the agent), but the repository itself is the leak.
- **D01–D03** ask the agent to *choose* a package for a described need and cite official sources, "using documentation versions published by 2026-10-25". Ground truth is a frozen snapshot of two packages (`termr 1.0.1`, `climenu 0.2.0`) plus feature/caveat IDs. The prompt names `termr` explicitly ("a candidate to assess"), a very new niche package that also features in this repository's own dogfooding report; nothing here shows a conflict of interest, but the explicit hint is an unnecessary steer.
- **E01/E04/E05** are 0/6, 0–1/5 in both arms (floor). The repository's own audit attributes this to a hidden JSON contract rather than to knowledge (BEN-002).

### 3.2 Ground-truth and scorer correctness
- Scorer false negatives (confirmed by reading `knowledge_pilot.py`): D-block exact URL membership; E-block exact-equality gates such as `packages["DESeq2"] == {"version": "1.50.2", "repository": "Bioconductor 3.22"}` and "every source must start with `https://bioconductor.org/`" although the task includes a CRAN package. P1-E documents a concrete D01 false negative (an official CRAN package index URL rejected).
- Scorer false positives: not observed; D/E answers are structured JSON compared with frozen constants, so they cannot be passed by fluent prose. The hard-suite verifier tests behaviour on real outputs with wrong-strategy controls, which is the right defence.
- Reference-solution errors: the E02 repair history shows the process works (the original 20-row fixture made DESeq2 fail on the *reference*, 0/5; the fixture was replaced and pinned) — but see CI-004: the pins validate only on one line-ending configuration.
- Task ambiguity: D01 allows "any valid package" yet the scorer accepts only candidates in `verifier/candidates.json` with their frozen URLs; an unlisted but correct package scores 0 on package/version.

### 3.3 Version drift and non-determinism
- D/E tasks are **time-pinned snapshots** (2026-10-25) while every MCP tool returns the *current* repository state; there is no as-of parameter. A CRAN or Bioconductor update after the snapshot turns a correct MCP answer into a scorer failure (BEN-002). The Bioconductor *release* has already moved on (`release` is now 3.23; the tasks pin 3.22).
- Model stochasticity is uncontrolled: D01 with MCP ranges 0.25–1.0 across eight replicates (§4).
- No confidence intervals, no seeds recorded for agent behaviour, runs spread across ten days (2026-10-24 … 10-27) on a live upstream.

## 4. H2 — Is the A/B comparison fair?

| Requirement | Finding | Evidence |
|---|---|---|
| Same model | **Yes**: all 91 trials `gpt-6-luna`, medium effort | analytics DB |
| Same task prompts | **Yes** within a task/suite; verified by prompt digests in `experiment.json` | `run_simple.py:700-727` |
| Equivalent environment apart from MCP | Mostly: same executor image, limits, workspace; the with-MCP arm adds an MCP container on the same bridge network | `run_simple.py:1750-1830,2491` |
| Uncontrolled external information | **Not controlled.** The per-trial Docker network is a normal bridge (no `--internal`, no proxy); "no browsing" is an instruction only; a control-arm agent can fetch CRAN directly and telemetry cannot see it (BEN-003) | `run_simple.py:2491`; P1-E §9 |
| Allowed tools apart from MCP | Same executor; but the MCP allow-list differs between conditions (13 vs 12 tools in the discovery pairs) | P1-D, P1-E |
| Consistent runtime configuration | **No across analyses**: 3 configurations, 7 scorer versions, `standard` and `diagnostic` instruction variants pooled | `evidence/benchmark/bench_err.txt` |
| Fair budgets | The manifest declares 30 000 tokens "enforced by the controller"; the simple runner states the limit is *not* enforced (`run_simple.py:67-74`) and records elapsed time only | `manifest.json:22` |
| Controlled order | **No** for standard runs: `for repetition: for task: for mode` makes arm A always first (`run_simple.py:3262-3275`); only `b1-discovery` has a hand-balanced order (lines 94-107) | code |
| Accurate token/latency accounting | **No tokens**: API usage observed in 1 of 91 trials, cost in 0 of 91. Server-side latency and byte counts are recorded per call | analytics DB |
| Correct attribution of MCP usage | Client/server events are matched by order only (`ordinal_unconfirmed`); 28 canonical calls in P1-E, one evidence event short; arguments/aliases not retained in historical runs | P1-E |
| No contamination between trials | Plausible (fresh session, fresh container, session deleted); cached upstream state is per-MCP-container, so not shared across trials. Upstream drift across days is shared | design |
| Differential attrition | 6 `without-mcp` trials ended `LEGACY_ERROR` (early development); 2 with-MCP trials interrupted; 6 with-MCP trials `unsupported_for_automatic_scoring` | `bench_err.txt` |

## 5. H3 — Do the benchmarks separate availability, discoverability, selection, success, correctness, use and benefit?

Partially, and better than most. The schema distinguishes `configured`, `allowed`, `listed` (server `tools/list` count), `called` (server telemetry), per-call `status`/`error_code`, `partial`, `version_mismatch`, `repeat_kind`, and has an explicit `observed_use` field with values such as `unknown_payload_unavailable`; and no report treats a call as evidence of benefit. What is missing:

| Layer | Observable today? |
|---|---|
| Availability (configured/allowed) | yes (session echo from schema 1.1 on) |
| Discoverability (agent saw the tool list) | **no**: remote tool discovery is "unknown" (P1-E §3); only the server's `tools/list` count |
| Selection | yes: first call, count, order |
| Successful invocation | yes (server status) |
| Retrieval correctness | **no**: responses and arguments not retained |
| Actual use of retrieved facts in the answer | **no**: P1-E "insufficient_observability"; 27 evidence events for 28 calls |
| Quality improvement | only through the scorer, with its hidden-contract issues |

What the D01 data do and do not say (exploratory, `bench_d01.txt`): the 12 scored D01 trials separate perfectly by *use*: all 6 trials that made MCP calls scored 3–4/4 (mean 0.875), all 6 that did not (4 without-MCP, 2 with-MCP-but-unused) scored 1–2/4 (mean 0.375). That is consistent with a large benefit **when the agent uses the tool for facts it otherwise cannot obtain in the sandbox**, which is exactly what D01 tests; but use was not randomised, the same agent chose to use it, the tasks are unlike most real R work, and the pooled arm comparison (0.375 vs 0.75, bootstrap interval 0.16–0.56 over n = 4 and 8 trials from different runs) is not an estimate to rely on.

## 6. H4 — Historical Function Discovery evidence (P1-D, P1-E)

What the frozen evidence **supports**:
1. In the P1-E enabled run, 28 canonical server calls occurred (17 `get_function_docs`, 9 `list_package_functions`, 2 `get_package`), with 12 docs successes, 2 `docs_not_found` and 3 `requested_version_unavailable`; all nine discovery calls returned without RPC error and were recorded `partial` (verified against `results.json`).
2. The answer's `termr 1.0.1` matches the frozen reference; the single failed check is the documentation URL (exact-membership scorer, BEN-002).
3. The earlier pair on the same task went the opposite way (enabled 2/4 with 0 MCP calls and a wrong package; disabled 4/4 with 15 calls): the two comparisons contradict each other and both are n = 1.
4. The `docs_not_found` events (59 across all runs, 56 in D01) are **agent guesses for APIs the agent did not know** (`new_app`, `select_input`, `choose_menu`, …) or hallucinations (`validate::violations`, which does not exist: I checked validate 1.1.7, the correct name is `violating`).

What it **cannot** support, and what I did not reconstruct:
- That discovery *caused* any score change (the disabled control made 0 MCP calls).
- Whether discovered aliases were later used in docs calls: arguments and returned aliases were not persisted; client/server correlation is ordinal; "no transition is verified" (P1-E §7).
- Why all nine discovery calls were `partial`. **New, from this audit:** partial is the *normal* status for real packages: `termr` 1.0.1 is partial because 44 of its Rd files contain roxygen-generated `\if{html}` blocks (KC-002), independent of any agent behaviour. The historical "9/9 partial" therefore carries no information about discovery quality.
- Package-version telemetry: the `version` projection defect (provider field `package_version` dropped) was fixed for future events; historical raw responses are absent, so no one can say what version the agent saw. Correctly not backfilled.

## 7. H5 — Statistical rigor and a confirmatory design

Current state: no pre-registration, no a-priori sample size, n = 1 in 26 of 42 cells, pooled configurations, no intervals, no multiplicity control, no inter-rater agreement (scoring is deterministic, so it does not need one; semantic adjudication of the `unsupported_for_automatic_scoring` D01/D03 answers would), no scorer calibration beyond reference/mutant controls, no variance analysis, no sensitivity analysis.

**Recommended confirmatory experiment** (to be frozen before any run; "exploratory" labels stay on everything else):
1. **Question:** does making the server available raise the probability that an R coding agent produces a correct artifact on tasks where installed-version facts, API existence or Bioconductor/R compatibility matter? (Not "does it get called".)
2. **Design:** paired, within-task, randomised order per pair with a recorded seed; arms differ only in MCP presence; same allow-list, instructions, network policy (egress through an allow-listed proxy that logs every request, so web fetches are visible), token budget enforced or removed, usage recorded.
3. **Tasks:** ≥ 30 tasks, each scored by a hidden behavioural verifier (hard-suite style), stratified by (a) installed ≠ latest version, (b) hallucination-prone API, (c) Bioconductor/R pairing, (d) control tasks where MCP is irrelevant (to bound the "tool-use tax": extra tokens/time/failures). Keep oracle tests private.
4. **Replication:** ≥ 3 independent sessions per task per arm; unit of analysis = task (cluster). Illustrative power: for a paired binary outcome with 30 % of pairs favouring MCP and 10 % favouring control (difference 20 points), McNemar needs ≈ 76 discordance-bearing task-runs at α = 0.05, 80 % power, so about 30 tasks × 3 repetitions is the right order of magnitude.
5. **Analysis (pre-specified):** paired difference in success rate with a task-clustered bootstrap 95 % interval; mixed-effects logistic model with random task and model-seed effects as sensitivity; effect size as absolute risk difference; strata reported separately; ITT accounting (failed/errored trials count as failures, with infrastructure errors reported separately and excluded only by a pre-declared rule); cost reported as tokens and wall-clock per *successful* task.
6. **Mechanism analysis (secondary, labelled exploratory):** adoption (first-call rate), retrieval correctness (arguments and returned version retained), use of retrieved facts (claim–evidence verification as in knowledge-pilot-v2.1), failure-mode stratification (hallucinated name vs wrong version vs misread compatibility).
7. **Scorer calibration:** run every scorer against reference, ≥ 3 wrong strategies *and* ≥ 5 independently written correct alternatives that differ in format/ordering/URL choice; require 0 false negatives before use.
8. **Reproducibility:** commit the evidence bundle with checksums (BEN-005), pin fixtures with line-ending rules (CI-004), version the scorer digest in every record.

## 8. Limits of this part of the audit
I did not run any trial, Docker benchmark image, R oracle task or scorer; I did not read all 31 918 lines of benchmark Python; the exploratory F09 connectivity harness, the managed-agents code and the R launcher application were only sampled; telemetry correlation logic was read through its reports, not re-implemented. The per-trial results exist only on the author's disk, so every statistic here is reproducible only by someone who has that directory (BEN-005).
