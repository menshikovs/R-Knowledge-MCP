# Stage 2 Final Report — Benchmark Scientific Validity (`stage2_validity_v1`)

## 1. Stage 1 vs Stage 2 Comparison

| Dimension | Stage 1 / Historical Benchmark Runs | Stage 2 (`stage2_validity_v1`) |
| :--- | :--- | :--- |
| **Experimental Arms** | 2 ad-hoc modes (`without-mcp`, `with-mcp`) with shifting prompt instructions across campaigns. | **3 preregistered arms**: Arm A (`without-mcp`), Arm B (`with-mcp` voluntary, byte-identical base prompt), Arm C (`with-mcp-encouraged`, standardized encouragement suffix). |
| **Primary Estimand** | Informal comparison of aggregate/subset win counts, often conditioned on whether MCP was called. | **Intention-to-Treat (ITT) task-weighted paired difference** $\hat{\Delta}_{BA} = \frac{1}{K}\sum_{t=1}^K \bar{D}_t$ on `primary_score` $\in [0, 1]$, never conditioned on tool usage. |
| **Randomization & Order** | Deterministic sequential execution (`without-mcp` then `with-mcp`). | **Counterbalanced Latin-permutation block randomization** (`blocked-latin-permutations-v1`) across `(task, repetition)` blocks with interleaved wave execution and fresh session isolation per trial. |
| **Statistical Inference** | Descriptive means or naive block-level sign-flipping (which inflates Type I error under task heterogeneity). | **Task-level sign-flip test** (`task_level_sign_flip_test`) on within-task mean differences + two-stage percentile bootstrap CI + Holm step-down adjustment on secondary contrasts (`C-B`, `C-A`, `B-A:fully_correct`). Block-level sign-flipping retained strictly as a sharp-null sensitivity output. |
| **Task Selection** | Post-hoc focus on `D01–D03` where `with-mcp` scored higher. | **Arm-A-only screening rule** (`classify_task`): tasks are stratified using only Arm A observations ($n_A \ge 3$, $0.10 \le \bar{Y}_A \le 0.90$) and structural audit flags. |
| **Failure & Missingness Handling** | Errored or unsupported runs dropped or rescored inconsistently. | Explicit status taxonomy (`scored`, `candidate_failure` $= 0.0$ in ITT, `infrastructure_failure` / `scoring_error` / `not_executed` $=$ explicit missingness) with Manski worst/best bounds and complete-case sensitivity. |
| **Telemetry & Mediator Model** | Binary or conflated tool counts; unconfirmed client/server pairing. | **7 distinct observability levels** (`available`, `listed`, `attempted`, `completed`, `errored`, `delivered`, `result_use_proxy`) + explicit correlation certainty (`confirmed_protocol_id`, `ordinal_unconfirmed`, `unmatched`). |
| **Evidence & Scorer Pinning** | Scorer rules (`v1` $\to$ `v2` $\to$ `v2.1`) changed across runs. | **279 frozen evidence, task, oracle, and scorer files** pinned by SHA-256 (`frozen_evidence_digests.json`) and verified per trial. |

---

## 2. Historical Benchmark Findings (Read-Only Audit)

From [`historical_calibration_summary.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/historical_calibration_summary.json) (pre-Stage-2 cutoff `before_date="20261028"` across 31 run directories; 32 directories total when including the 4-entry post-cutoff directory `20261028T113222Z-e5a013f7`):

- **Corpus size**: `108` raw entries, `103` entries with usable `task` and `mode` fields, and `88` entries with `status == "scored"` (`6` `error`, `2` `interrupted`, `1` `smoke_transport_observed`, `6` `unsupported_for_automatic_scoring`). Including `20261028T113222Z-e5a013f7`, there are `112` raw / `107` usable / `90` scored entries.
- **Ceiling and floor saturation**:
  - `11` tasks exhibit Arm A ceiling performance (`mean_a == 1.0`): `R01`, `R02`, `R04`, `B01`, `B02`, `B03`, `C01`, `C02`, `C05`, `E02`, `E03`.
  - `2` tasks exhibit complete floor saturation (`mean_a == 0.0` and `mean_b == 0.0`): `E04`, `E05`.
  - Almost all positive historical score variation between `with-mcp` and `without-mcp` is concentrated in `D01`, `D02`, and `D03`.
- **Observability gaps**: Only `1 / 103` historical trials (`0.97%`) recorded model token usage (`total_tokens`). Median trial wall-clock duration across 101 timed entries was `82.619s` (`p90 = 185.788s`).
- **Causal conclusion**: Historical runs are heterogeneous, confounded by scorer and prompt changes, and saturated on most tasks; they **cannot** support a causal claim about R-Knowledge-MCP effectiveness.

---

## 3. Task Catalogue and Stratification (`task_catalog.json`)

The executable repository contains **31 tasks**: `R01–R12` (12), `B01–B03` (3), `C01–C05` (5), `D01–D03` (3), `E01–E05` (5), and `H01, H04, H10` (3). **No integrated ANOVA tasks exist in the repository.** (`H10` tests Rubin's rules for pooled multiple-imputation $t$-intervals.)

Under the Arm-A-only screening rule (`calibration.classify_task`):

- **`S1_confirmatory_core` (0 tasks)**: None (`0` tasks currently have $n_A \ge 3$, $0.10 \le \bar{Y}_A \le 0.90$, and no `BEN-002`/unsupported flags).
- **`S2_calibration_needed` (17 tasks)**: `R01–R12`, `C03`, `C04`, `H01`, `H04`, `H10` (fewer than 3 scored Arm A runs).
- **`RC_recalibration_required` (8 tasks)**: `C01`, `C02`, `C05` (Arm A ceiling `1.0` with $n_A = 3$); `D01`, `D02`, `D03` (`BEN-002` frozen candidate list); `E04`, `E05` (`BEN-002` hidden JSON contract + floor `0.0`).
- **`Q_quarantined_or_smoke` (6 tasks)**: `B01`, `B02`, `B03`, `E01`, `E02`, `E03` (historical `unsupported_for_automatic_scoring` records and/or `BEN-002`).

---

## 4. Scoring Audit Findings (`SCORING_VALIDITY.md`)

- **`legacy` (`R01–R12`)** and **`hard-v1` (`H01, H04, H10`)** use behavioral R execution and holdout tests with high oracle independence.
- **`knowledge-pilot-v2.1` (`B01–E05`)** properly treats `unknown` claims as abstentions rather than `0.5` partial credit (fixing the `v2` distortion), but retains **`BEN-002` oracle coupling** in `D01–D03` (grading `recommended_package` by exact membership in a 3–5 package frozen list) and `E01, E04, E05` (grading unprompted JSON schema key names). All `BEN-002` tasks are excluded from `S1_confirmatory_core` until recalibrated.

---

## 5. Telemetry Contract (`TELEMETRY_CONTRACT.md`)

`telemetry.py` enforces 7 distinct levels:

1. `mcp_available` (capability wired)
2. `mcp_listed` (`mcp_tools_listed` observed)
3. `attempted` (client calls started, deduplicated by `call_id`, including unstarted terminal events so `0 <= completed + errored <= attempted` always holds)
4. `completed` (client calls finished with `status == "ok"`)
5. `errored` (client calls finished with error status)
6. `delivered` (server calls finished with `is_error == False` and `output_bytes > 0`)
7. `result_use_proxy` (explicitly labeled `"unverified_lexical_overlap"` or `"not_applicable"`, never treated as proof of causal tool use)

Client-server call correlation (`correlate_calls`) distinguishes `confirmed_protocol_id`, `ordinal_unconfirmed`, and `unmatched` (including protocol ID mismatches and clock-skew violations).

---

## 6. Three-Arm Experimental Design (`EXPERIMENT_DESIGN.md`)

- **Arm A (`without-mcp`)**, **Arm B (`with-mcp`)**, and **Arm C (`with-mcp-encouraged`)** share byte-identical `COMMON_BASE_INSTRUCTION` (`sha256: b39ef2bc61a7d84e7706d809ca9ca4fa8190d62196844028492e1ef20c1464b6`). Arm C appends only `ARM_C_ENCOURAGEMENT_SUFFIX` (`sha256: 00161e2625835f8c8f4369a1e38f8fc508d855df9ec23bf2c4a21614308dc08b`).
- **Primary comparison**: `B - A` (ITT effect of voluntary MCP availability).
- **Secondary comparisons**: `C - B` (encouragement effect), `C - A` (encouraged availability effect), and `B - A:fully_correct` (perfect-score binary indicator), adjusted via Holm step-down.

---

## 7. Final Statistical Analysis Method (`STATISTICAL_ANALYSIS_PLAN.md`)

- **Unit of inference**: The **task** ($t = 1, \dots, K_{\text{obs}}$), using within-task mean paired differences $\bar{D}_t = \frac{1}{R_t}\sum_{r=1}^{R_t} (Y_{t,r}(B) - Y_{t,r}(A))$ weighted equally across tasks.
- **Primary hypothesis test**: Two-sided **task-level sign-flip test** (`task_level_sign_flip_test`), exact ($2^K$) for $K \le 16$ and Monte Carlo ($19{,}999$ permutations with Phipson-Smyth $+1$ correction) for $K > 16$.
- **Why block-level sign-flipping was replaced**: Under heterogeneous task effects with zero mean ($\mathbb{E}[u_t] = 0, \operatorname{Var}(u_t) = \tau^2 > 0$), flipping signs independently across repetitions within a task cancels $u_t$ in the permutation distribution, shrinking the null variance by $1/R$ and inflating Type I error to **`0.0867`–`0.1033`** at $K = 40, R = 5$ (`power_simulation.json`). Task-level sign-flipping preserves the exact task-level variance structure and maintains nominal Type I error (**`0.0400`** at $K = 40, R = 5$).
- **Confidence interval**: Two-stage percentile bootstrap (`paired_bootstrap_ci`, $10{,}000$ resamples: tasks with replacement, then blocks within task with replacement).

---

## 8. Power Simulation and Budget (`POWER_AND_BUDGET.md`)

From [`power_simulation.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/power_simulation.json) (`seed=20261028`, `n_sim=300`, $\tau=0.10$, $\sigma_{\text{rep}}=0.15$, $25\%$ saturated tasks):

- **Type I error ($\delta = 0.0$)**: Ranges from `0.0333` to `0.0533` across all $(K, R)$ cells for the primary task-level sign-flip test.
- **Power at $K = 30, R = 3$ (270 total trials)**: `0.7667` for latent $\delta = +0.10$ (`0.7333` for $\delta = -0.10$) and `1.0000` for $\delta = +0.20$ (`0.9967` for $\delta = -0.20$), with 95% CI coverage `0.9667–0.9800` and median CI half-width `0.050`.
- **Power at $K = 40, R = 5$ (600 total trials)**: `0.9467` for latent $\delta = +0.10$ and `1.0000` for $\delta = +0.20$.
- **Wall-clock budget**: Based on historical median `82.619s` (`p90 = 185.788s`), a 51-session Arm-A calibration pass requires `1.17h` expected (`2.63h` p90), a 48-session 3-arm pilot requires `1.10h` (`2.48h` p90), and a 270-session confirmatory study ($K = 30, R = 3$) requires `6.20h` (`13.93h` p90).

---

## 9. Synthetic Dry-Run Validation (`synthetic_validation/SUMMARY.json`)

Five deterministic synthetic scenarios ($K = 12, R = 2$, 72 trials each, `synthetic_validation: true`) were executed and verified end-to-end:

| Scenario | Study Valid | Primary $\hat{\Delta}_{BA}$ | 95% Bootstrap CI | Task-Level $p$-value | Invalidating Violations | Verified Behavior |
| :--- | :--- | ---: | :--- | ---: | ---: | :--- |
| `null` | `True` | `-0.0083` | `[-0.1000, +0.0833]` | `0.8594` | `0` | Non-significant under zero effect ($\delta = 0$). |
| `positive` | `True` | `+0.2583` | `[+0.1583, +0.3583]` | `0.0010` | `0` | Detects positive B>A effect and C>B encouragement increment (`+0.0917`, $p_{\text{Holm}} = 0.0449$). |
| `negative_tool_tax` | `True` | `-0.2083` | `[-0.2750, -0.1417]` | `0.0005` | `0` | Detects negative regression / tool tax ($\hat{\Delta}_{BA} < 0$). |
| `heavy_missingness` | `True` | `+0.0917` | `[+0.0250, +0.1583]` | `0.0342` | `0` | Preserves 12 missing records explicitly and widens Manski bounds to `[-0.1500, +0.3500]`. |
| `leaky_control` | **`False`** | `+0.0500` | `[-0.0417, +0.1417]` | `0.3823` | **`1`** | Flags leaked MCP availability/calls on Arm A (`arm_a_mcp_available_leaked`, `arm_a_mcp_listed_leaked`, `arm_a_mcp_call_attempted`) and invalidates the study without schema crash. |

---

## 10. Stage 2.5 Runner Hardening and Remaining Live Blockers

See [`STAGE25_PILOT_READINESS.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/STAGE25_PILOT_READINESS.md) for the complete Stage 2.5 pilot-readiness report:

1. **Three-Arm Study Runner & Fault-Tolerant Ledger (`runner.py`)**: Implemented and verified offline with `TrialLedger` (`plan.json`, `run_config.json`, `trial_records.jsonl`, `ledger_journal.jsonl`, and atomic `staging/<trial_id>.staging.json` recovery across process interruptions, corrupt JSONL tails, duplicate detection, and linked infrastructure retries).
2. **Isolation Policy & Probe Suite (`isolation.py`, `isolation_probes_report.json`)**: Implemented and verified offline across all 3 arms; static audit of `benchmarks/codex_r/run_simple.py` confirms Arm A omits the MCP container (`line 2501`), while the Docker bridge network (`line 2497`) does not yet pass `--internal` or start `egress_proxy.py`.
3. **Separate Scorer-Calibration Suite (`scorer_calibration.py`, `scorer_calibration_report.json`)**: Exercised 16 candidate JSON probes across `D01`–`D03`, `E01`, `E04`, and `E05` and audited all 31 R/JSON verifiers without modifying any frozen files (`279 frozen files; 0 differences`).
4. **Executable Study Configurations (`study_configs.py`, `study_specifications.json`)**: Defined `smoke_mock` (12 trials, ready & verified offline), `pilot_real_spec` (60 trials, gated on live Docker `--internal` + spend authorization), and `confirmatory_spec` (target 270 trials, gated on $\ge 20$ `S1` tasks + frozen registration commit + spend authorization).

---

## 11. Final Milestone Determination

- **STAGE 2 INFRASTRUCTURE READY**: **ACHIEVED / YES** (all Stage 2 modules, schemas, digests, statistical tests, and synthetic dry runs are complete and verified).
- **STAGE 2.5 PARTIALLY COMPLETE**: **ACHIEVED / YES** (all offline Stage 2.5 runner, fault-tolerant ledger, isolation probe, scorer calibration, and study configuration components are complete and verified; live Docker `--internal` + `egress_proxy.py` wiring in `run_simple.py` and Arm-A calibration trials remain before live pilot execution).
- **PILOT READY**: **NOT REACHED / NO** (requires wiring `--internal` + `egress_proxy.py` and the Stage 2.5 3-arm adapter into live Docker execution in `run_simple.py`, plus human spend authorization).
- **CONFIRMATORY EXPERIMENT READY**: **NOT REACHED / NO** (requires Pilot Readiness + graduating $\ge 20$ tasks into `S1_confirmatory_core` + frozen git registration commit + budget approval).
- **EMPIRICAL EFFECT ESTABLISHED**: **NOT ESTABLISHED / NO** (no live model trials were executed in Stage 2 or Stage 2.5).
