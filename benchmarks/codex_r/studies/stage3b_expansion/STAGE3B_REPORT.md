# Stage 3B Benchmark Expansion — Scientific and Engineering Report

## 1. Executive Summary

Stage 3B delivers a self-contained, offline-validated **30-task R benchmark expansion** (`r-knowledge-mcp-stage3b-v1`, pool `stage3b-candidate-pool-v1`) under `benchmarks/codex_r/studies/stage3b_expansion/`.

Every task in Stage 3B is:
1. **Grounded in the pinned R 4.5.2 / Bioconductor 3.22 runtime** (`configs/renv.lock` and verified container pins), with zero external network dependencies.
2. **Evaluated by a deterministic behavioral R verifier** (`verifier/<ID>.R`) executing candidate functions in an isolated `callr` subprocess inside a networkless (`--network none`), read-only, non-root Docker container (`codex-r-benchmark:pilot` or `codex-r-benchmark:pilot-bioc`).
3. **Cross-checked at load time by an independent mathematical/algorithmic oracle** (`stopifnot(...)` before any check is registered) so oracle bugs fail closed as `scoring_error` rather than mis-scoring candidates.
4. **Validated offline against an adversarial control suite** (`verifier/controls/<ID>.R` plus synthetic `reference_repeat`, `empty`, `syntax_error`, and `forged_result` probes) in the real R scorer containers (`validation_report.json`: **30/30 tasks passed gate, 323 behavioral checks, 0 API calls**).
5. **Integrated with the Stage 2 / Stage 2.7 / Stage 3A experimental platform and legacy runner** (`run_simple.py`, `manifest.py`, `scorer_bindings.py`, `runner.py`, `legacy_executor.py`, and `calibration_pipeline.py`) without modifying any frozen benchmark evidence (`frozen_evidence_digests.json`: 279 files, 0 differences) or the historical 31-task `task_catalog.json`.

| Status Dimension | Stage 3B Status | Evidence |
| :--- | :--- | :--- |
| **30-Task Authoring & Fixtures** | **COMPLETE** | `tasks/X{A,G,V,R,P,M}*/{prompt.md,task.json,fixture/*}` |
| **Real-R Container Scorer Gate** | **PASS (30 / 30)** | `validation_report.json` (`gate: "passed"`, `api_calls: 0`) |
| **Manifest & Catalogue Sync** | **PASS** | `python -m benchmarks.codex_r.studies.stage3b_expansion.build --check` |
| **Frozen Evidence Integrity** | **PASS (279 / 279)** | `python -m benchmarks.codex_r.studies.stage2_validity_v1.cli frozen --verify` |
| **Arm-A Model Calibration** | **PREPARED / NOT EXECUTED** | Requires owner budget authorization (`0` paid model calls run) |
| **Confirmatory (`S1`) Promotion** | **NOT PROMOTED (`stratum: null`)** | Requires empirical Arm-A calibration mean in `[0.10, 0.90]` |

---

## 2. Family and Classification Distribution

Stage 3B spans six task families (`XA`, `XG`, `XV`, `XR`, `XP`, `XM`). Each task's MCP relevance classification (`target_candidate`, `control`, or `exploratory`) is **deterministically derived** from its pre-assigned Stage 2 ordinal dimension ratings (`version_sensitivity`, `documentation_dependence`, `package_api_verification_need`, `statistical_Domain_reasoning`, `code_synthesis_complexity`) and `expected_mcp_usefulness` via `calibration.target_by_features`, never from model outcomes:

- **`target_candidate`**: `expected_mcp_usefulness` in `{"plausible", "high"}` **and** `max(version_sensitivity, documentation_dependence, package_api_verification_need) >= 2`.
- **`control`**: `expected_mcp_usefulness` in `{"none", "low"}` **and** `max(version_sensitivity, documentation_dependence, package_api_verification_need) <= 1`.
- **`exploratory`**: Intermediate tasks that neither qualify as confirmatory targets nor satisfy the strict low-documentation control bound.

| Family Prefix | Category | Total Tasks | `target_candidate` | `control` | `exploratory` | Task IDs |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **`XA`** | `anova_statistical_inference` | 6 | 1 (`XA06`) | 5 (`XA01`–`XA05`) | 0 | `XA01`–`XA06` |
| **`XG`** | `ggplot2_visualization` | 5 | 0 | 4 (`XG01`–`XG03`, `XG05`) | 1 (`XG04`) | `XG01`–`XG05` |
| **`XV`** | `version_sensitive_api` | 5 | 4 (`XV01`, `XV02`, `XV04`, `XV05`) | 0 | 1 (`XV03`) | `XV01`–`XV05` |
| **`XR`** | `code_repair_migration` | 5 | 3 (`XR01`, `XR04`, `XR05`) | 1 (`XR03`) | 1 (`XR02`) | `XR01`–`XR05` |
| **`XP`** | `package_discovery` | 5 | 1 (`XP04`) | 2 (`XP01`, `XP02`) | 2 (`XP03`, `XP05`) | `XP01`–`XP05` |
| **`XM`** | `multi_step_workflow` | 4 | 3 (`XM01`, `XM03`, `XM04`) | 1 (`XM02`) | 0 | `XM01`–`XM04` |
| **Total** | **All 6 Families** | **30** | **12** | **13** | **5** | **23 clusters** |

### Independence Structure
Across the 30 tasks, there are **23 distinct independence clusters** (`independence.cluster`): 19 singleton clusters plus `anova-dependent-data` (`XA04`, `XA06`), `ggplot2-missing-data` (`XG01`, `XG02`), `installed-package-metadata` (`XP01`–`XP05`), and `bioconductor-workflows` (`XM01`, `XM04`). Crucially, among the **12 `target_candidate` tasks**, there are **11 distinct independence clusters** (only `XM01` and `XM04` share `"bioconductor-workflows"`).

---

## 3. Confirmatory Pool Feasibility Analysis

In Stage 2.7, auditing the historical 31-task catalogue (`R01`–`R12`, `H01`–`H10`, `B01`–`B03`, `C01`, `C03`, `C04`, `D01`–`D03`, `E01`–`E05`) established a mathematical blocker to the preregistered 30-task confirmatory (`S1`) core:
- Historical catalogue: `0` `S1`, `17` `S2` controls (which can never enter `S1`), `8` `RC` target candidates, and `6` `Q` quarantined target candidates (requiring BEN-002 scorer revision).
- Even under 100% calibration retention, the historical catalogue could yield at most **8 `S1` tasks** (or **14** if all 6 `Q` scorers were revised).

With the Stage 3B expansion (`30` tasks: `12` `target_candidate`, `13` `control`, `5` `exploratory`):
- **Combined Benchmark Pool**: $31 + 30 = 61$ tasks ($55$ non-quarantined calibration-ready tasks).
- **Target Candidates Eligible for `S1` via Arm-A Calibration**:
  - Historical `RC` tasks: **8** (`C01`, `C03`, `C04`, `E02`, `E03`, `H04`, `H07`, `H09`)
  - Stage 3B `target_candidate` tasks: **12** (`XA06`, `XM01`, `XM03`, `XM04`, `XP04`, `XR01`, `XR04`, `XR05`, `XV01`, `XV02`, `XV04`, `XV05`)
  - **Best-Case `S1` Pool (without `Q` scorer revision)**: $8 + 12 = \mathbf{20}$ tasks (19 independent clusters).
  - **Best-Case `S1` Pool (if all 6 `Q` scorers are also revised)**: $20 + 6 = \mathbf{26}$ tasks.
- **Control (`S2`) Pool for Tool-Use Tax Estimation**:
  - Historical `S2` controls: **17**
  - Stage 3B `control` tasks: **13** (`XA01`–`XA05`, `XG01`–`XG03`, `XG05`, `XM02`, `XP01`, `XP02`, `XR03`)
  - **Combined Control Pool**: $17 + 13 = \mathbf{30}$ tasks.

> [!IMPORTANT]
> **Methodological Conclusion on Confirmatory Sample Size**:
> Stage 3B increases the maximum reachable `S1` target pool from **8** to **20** (or **26** with `Q` scorer revisions) and expands the `S2` control pool to **30** tasks. Because Stage 3B followed the pre-committed task-family blueprint (`6 XA`, `5 XG`, `5 XV`, `5 XR`, `5 XP`, `4 XM`) and classified MCP relevance strictly from task dimensions rather than inflating ratings to force tasks into `target_candidate`, **18 of the 30 tasks are legitimately classified as `control` (13) or `exploratory` (5)**. Consequently, reaching the preregistered 30-task `S1` confirmatory minimum still requires either (a) a Stage 3C target-focused task batch ($\ge 10$ additional `target_candidate` tasks, or more accounting for Arm-A floor/ceiling attrition) or (b) a dated, pre-data preregistration amendment adjusting `confirmatory_task_rule.minimum_tasks`.

---

## 4. Offline Scorer Validation Summary

All 30 verifiers were executed against their control suites inside the pinned scorer containers via `python -m benchmarks.codex_r.studies.stage3b_expansion.selftest`:

- **Total Tasks Validated**: 30 / 30 (`gate: "passed"`)
- **Total Behavioral Checks**: 323 (mean 10.77 checks/task; range 8–13)
- **Total Container Control Runs**: 353 (including `reference`, `reference_repeat`, 34 `alternate_*` implementations, 98 `wrong_*` strategies, 31 `edge_*` boundary probes, and 60 `malformed_*` / synthetic probes)
- **Repeatability**: 30 / 30 `reference` and `reference_repeat` runs achieved 100% check pass rates with zero nondeterminism.
- **False Negatives on Valid Alternatives**: 0 / 34 (`100%` of `alternate_*` solutions scored `fully_correct: true`).
- **False Positives on Wrong/Malformed Controls**: 0 (`100%` of `wrong_*`, `malformed_*`, `empty`, and `syntax_error` controls were rejected).
- **Output Forgery Immunity**: 30 / 30 `forged_result` controls confirmed that candidate stdout printing `BENCH_RESULT=...` cannot inflate scores or override harness output.

---

## 5. Remaining Blockers Before Live Calibration

1. **Owner Spend Authorization**: Live Arm-A calibration (`90` trials for the 30 Stage 3B tasks at $R=3$) requires explicit owner budget approval and CLI flags (`--executor live --authorize-spend --max-spend-usd ...`).
2. **Linux / WSL2 Host for `run_simple.py`**: The legacy live runner uses `signal.SIGALRM` and must be launched from Linux or Ubuntu WSL2 with `OPENAI_API_KEY` and `OPENAI_EXECUTOR_API_KEY` set in the environment.
3. **Empirical Arm-A Screening**: Until real Arm-A calibration records are collected and evaluated with `evaluate-baseline`, all 30 Stage 3B tasks remain in `stage3b-candidate-pool-v1` with `stratum: null` and `confirmatory_eligible: false`.
