# Stage 2 Task Calibration and Catalogue Stratification

## 1. Executive Summary

The Stage 2 task catalogue ([`task_catalog.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/task_catalog.json)) indexes all **31 tasks** currently defined across the three executable benchmark suites in this repository:

- **`standard`** (`benchmarks/codex_r/run_simple.py::TASKS`): `R01–R12` (12 tasks)
- **`knowledge_pilot_v21`** (`benchmarks/codex_r/knowledge_pilot_v21.py::TASKS`): `B01–B03`, `C01–C05`, `D01–D03`, `E01–E05` (16 tasks)
- **`hard_v1`** (`benchmarks/codex_r/hard/suite.py::TASKS`): `H01`, `H04`, `H10` (3 tasks)

**No integrated ANOVA tasks exist in the executable suites.** Specifically, `H01` tests dense rank ties + weighted quantiles, `H04` tests rolling group median + MAD anomaly detection, and `H10` tests Rubin's rules for pooled multiple-imputation $t$-intervals (Barnard-Rubin degrees of freedom). While `H10` is the closest inferential statistics task in the suite, neither `H10` nor `R01–R12` implements analysis of variance (ANOVA). Stage 2 does not invent or claim ANOVA coverage.

## 2. Eight-Dimension Task Classification

Every task in `calibration.py::TASK_DIMENSIONS` is classified along 8 explicit ordinal dimensions:

1. `family`: Task family (`R_refactoring`, `B_bioconductor`, `C_compatibility`, `D_discovery`, `E_api_evolution`, `H_hard_algorithmic`).
2. `ecosystem`: Primary R package ecosystem (`tidyverse_core`, `bioconductor`, `cran_bioc_mixed`, `cran_survival`, `tidyverse_lifecycle`, `base_r_numeric`, `base_r_stats`).
3. `task_type`: Cognitive/operational demand (`code_refactor`, `workflow_audit`, `dependency_diagnosis`, `package_selection`, `deprecation_audit`, `numerical_implementation`, `statistical_inference`).
4. `expected_mcp_Surface`: Which R-Knowledge-MCP tool surface is structurally relevant (`package_docs`, `bioc_metadata_and_docs`, `version_and_dependencies`, `search_and_metadata`, `news_and_rd`, `none_algorithmic_baseline`, `none_statistical_formula`).
5. `verification_mode`: How the scorer grades the submission (`rscript_ behavioral_checks`, `structured_json_claim_scoring_v21`, `deterministic_hidden_holdout_tests`).
6. `oracle_independence`: Independence of the grading oracle from frozen MCP lookup tables (`high`, `medium`, `low_frozen_candidate_set`, `low_hidden_json_contract`).
7. `pretraining_Anchor_risk`: Likelihood that frontier LLM pretraining already memorizes the solution (`high`, `medium`, `low`).
8. `discrimination_tier_prior`: Prior expectation of task discrimination before empirical screening (`ceiling_prone`, `moderate`, `high`, `floor_or_contract_coupled`, `hard_tail`).

## 3. Arm-A-Only Screening Rule (Anti-Cherry-Picking Contract)

To prevent selecting tasks based on whether R-Knowledge-MCP happened to win or lose historically, `calibration.classify_task()` assigns tasks to strata using **Arm A (`without-mcp`) observations and structural audit flags only**. Arm B (`with-mcp`) scores are never consulted by the stratification rule.

The four mutually exclusive strata are:

1. **`Q_quarantined_or_smoke`**: Tasks with `unsupported_for_automatic_scoring` status in historical runs (`B01`, `B02`, `B03`, `E01`, `E02`, `E03` had 6 such records during early smoke runs) or documented `BEN-002` hidden JSON contract coupling (`E01`, `E04`, `E05`). **Count: 6 tasks** (`B01`, `B02`, `B03`, `E01`, `E02`, `E03`).
2. **`RC_recalibration_required`**:
   - Tasks flagged with `BEN-002` oracle/contract coupling not already in `Q` (`D01`, `D02`, `D03`, `E04`, `E05`), OR
   - Tasks with $n_A \ge 3$ scored Arm A runs where $\bar{Y}_A < 0.10$ (floor saturation) or $\bar{Y}_A > 0.90$ (ceiling saturation).
   - **Count: 8 tasks** (`C01`, `C02`, `C05`, `D01`, `D02`, `D03`, `E04`, `E05`).
3. **`S2_calibration_needed`**: Tasks without `BEN-002`/unsupported flags that have $n_A < 3$ scored Arm A observations (`R01–R12`, `C03`, `C04`, `H01`, `H04`, `H10`). These tasks require an Arm-A-only calibration pass ($n_A \ge 3$) before confirmatory eligibility can be decided. **Count: 17 tasks**.
4. **`S1_confirmatory_core`**: Tasks without `BEN-002`/unsupported flags that have $n_A \ge 3$ scored Arm A observations and $0.10 \le \bar{Y}_A \le 0.90$. **Count: 0 tasks**.

## 4. Complete 31-Task Calibration Table (Pre-Stage-2 Frozen History)

The table below reports the exact values from [`task_catalog.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/task_catalog.json) (computed over the 31 pre-Stage-2 run directories, 108 raw / 103 usable / 88 scored records):

| Task ID | Suite | Scorer | $n_A$ | $\bar{Y}_A$ | $\text{SD}_A$ | $n_B$ | $\bar{Y}_B$ | $\text{SD}_B$ | Flags | Stratum |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |
| `R01` | `standard` | `legacy` | 2 | 1.0000 | 0.0000 | 2 | 1.0000 | 0.0000 | `under_sampled_arm_a`, `ceiling_candidate` | `S2_calibration_needed` |
| `R02` | `standard` | `legacy` | 2 | 1.0000 | 0.0000 | 2 | 0.8750 | 0.1768 | `under_sampled_arm_a`, `ceiling_candidate` | `S2_calibration_needed` |
| `R03` | `standard` | `legacy` | 1 | 0.2500 | 0.0000 | 1 | 0.2500 | 0.0000 | `under_sampled_arm_a` | `S2_calibration_needed` |
| `R04` | `standard` | `legacy` | 2 | 1.0000 | 0.0000 | 1 | 1.0000 | 0.0000 | `under_sampled_arm_a`, `ceiling_candidate` | `S2_calibration_needed` |
| `R05` | `standard` | `legacy` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `R06` | `standard` | `legacy` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `R07` | `standard` | `legacy` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `R08` | `standard` | `legacy` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `R09` | `standard` | `legacy` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `R10` | `standard` | `legacy` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `R11` | `standard` | `legacy` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `R12` | `standard` | `legacy` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `B01` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 2 | 1.0000 | 0.0000 | 2 | 1.0000 | 0.0000 | `unsupported_auto_scoring_seen`, `under_sampled_arm_a`, `ceiling_candidate` | `Q_quarantined_or_smoke` |
| `B02` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 2 | 1.0000 | 0.0000 | 2 | 0.8333 | 0.2357 | `unsupported_auto_scoring_seen`, `under_sampled_arm_a`, `ceiling_candidate` | `Q_quarantined_or_smoke` |
| `B03` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 2 | 1.0000 | 0.0000 | 2 | 1.0000 | 0.0000 | `unsupported_auto_scoring_seen`, `under_sampled_arm_a`, `ceiling_candidate` | `Q_quarantined_or_smoke` |
| `C01` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 3 | 1.0000 | 0.0000 | 2 | 1.0000 | 0.0000 | `ceiling_candidate` | `RC_recalibration_required` |
| `C02` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 3 | 1.0000 | 0.0000 | 2 | 1.0000 | 0.0000 | `ceiling_candidate` | `RC_recalibration_required` |
| `C03` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 2 | 0.7222 | 0.3928 | 2 | 0.7222 | 0.3928 | `under_sampled_arm_a` | `S2_calibration_needed` |
| `C04` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 2 | 0.5833 | 0.5893 | 2 | 1.0000 | 0.0000 | `under_sampled_arm_a` | `S2_calibration_needed` |
| `C05` | `knowledge_pilot_v21` | `knowledge-pilot-v21` | 3 | 1.0000 | 0.0000 | 2 | 0.8750 | 0.1768 | `ceiling_candidate` | `RC_recalibration_required` |
| `D01` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 6 | 0.7083 | 0.3118 | 6 | 0.8583 | 0.1934 | `BEN-002_oracle_or_contract_coupled` | `RC_recalibration_required` |
| `D02` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 5 | 0.5000 | 0.5000 | 6 | 1.0000 | 0.0000 | `BEN-002_oracle_or_contract_coupled` | `RC_recalibration_required` |
| `D03` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 5 | 0.6500 | 0.3791 | 5 | 0.9000 | 0.2236 | `BEN-002_oracle_or_contract_coupled` | `RC_recalibration_required` |
| `E01` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 6 | 0.1333 | 0.2066 | 6 | 0.1333 | 0.2066 | `unsupported_auto_scoring_seen`, `BEN-002_oracle_or_contract_coupled` | `Q_quarantined_or_smoke` |
| `E02` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 2 | 1.0000 | 0.0000 | 2 | 1.0000 | 0.0000 | `unsupported_auto_scoring_seen`, `under_sampled_arm_a`, `ceiling_candidate` | `Q_quarantined_or_smoke` |
| `E03` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 2 | 1.0000 | 0.0000 | 2 | 1.0000 | 0.0000 | `unsupported_auto_scoring_seen`, `under_sampled_arm_a`, `ceiling_candidate` | `Q_quarantined_or_smoke` |
| `E04` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 4 | 0.0000 | 0.0000 | 4 | 0.0000 | 0.0000 | `floor_candidate`, `BEN-002_oracle_or_contract_coupled` | `RC_recalibration_required` |
| `E05` | `knowledge_pilot_v21` | `knowledge-pilot-v2.1` | 4 | 0.0000 | 0.0000 | 4 | 0.0000 | 0.0000 | `floor_candidate`, `BEN-002_oracle_or_contract_coupled` | `RC_recalibration_required` |
| `H01` | `hard_v1` | `hard-v1` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `H04` | `hard_v1` | `hard-v1` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |
| `H10` | `hard_v1` | `hard-v1` | 0 | — | — | 0 | — | — | `unexecuted`, `under_sampled_arm_a` | `S2_calibration_needed` |

*Note on post-cutoff directory `20261028T113222Z-e5a013f7`*: If `summarize_history(before_date="")` is run without the date cutoff, `R01` has $n_A = 3, \bar{Y}_A = 1.0$ and `R03` has 2 additional `error` records (`candidate_failure` on missing output file); the stratum counts (`S1: 0, S2: 17, RC: 8, Q: 6`) are unchanged.

## 5. Actionable Calibration Roadmap Before Confirmatory Execution

1. **Execute Arm-A-only calibration ($n_A \ge 3$) on `S2_calibration_needed` tasks**: Specifically `R03`, `R05–R12`, `C03`, `C04`, `H01`, `H04`, and `H10`. Any task whose Arm A mean falls in $[0.10, 0.90]$ automatically graduates to `S1_confirmatory_core`.
2. **Decouple `BEN-002` oracle contracts in a future `v2.2` scorer revision**:
   - For `D01–D03`, replace the short hardcoded `acceptable_packages` list with capability/evidence verification or an expanded, pre-audited ecosystem rubric.
   - For `E01`, `E04`, `E05`, explicitly state the required JSON output schema in the task prompt so scores measure R lifecycle knowledge rather than guessing unprompted key names.

