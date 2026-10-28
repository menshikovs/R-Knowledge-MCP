# Stage 2.7: Independent Review, Integration and Pilot Calibration Preparation Report

**Date**: October 28, 2026  
**Repository**: `https://github.com/menshikovs/R-Knowledge-MCP`  
**Base Branch**: `2.0`  
**Working Branch**: `feature/stage2-benchmark-validity`  
**Baseline Commit**: `08ef9e9e2711e1174ed6796b3e3e60bf0ad7ca58`  
**Pull Request**: `https://github.com/menshikovs/R-Knowledge-MCP/pull/28` (#28)  
**Final Status**: `STAGE 2.7 READY FOR CALIBRATION`

---

## 1. Executive Summary

Stage 2.7 delivers an independent scientific and architectural review of the entire Stage 2–2.6 implementation, provides automated task eligibility pipelines and baseline difficulty evaluation procedures, prepares an Arm-A-only calibration schedule (51 planned trials) without consuming model API credits, establishes the 5 formal research readiness gates, and packages the complete research platform into a reviewed Pull Request targeting `2.0`.

No paid model API calls were executed. No empirical benefit claims are made based on mock data.

---

## 2. Independent Audit Findings & Methodology Review

### 2.1 Experimental Protocol & Arm Integrity
- **Arm A (`without-mcp`)**: MCP container is omitted from the Docker network specification; the candidate has no network route or hostname mapping to MCP.
- **Arm B (`with-mcp`)**: MCP container runs on the internal bridge network at `http://r-knowledge-mcp:8000/mcp`. System prompt is byte-identical to Arm A.
- **Arm C (`with-mcp-encouraged`)**: MCP container is accessible identically to Arm B; appends exactly the preregistered neutral encouragement sentence.
- **Causal Estimand**: The primary contrast is strictly Intention-to-Treat ($ITT = \bar{Y}_B - \bar{Y}_A$), evaluated at the task level with equal weights across tasks ($K_{\text{obs}}$). Tool usage is an observational post-treatment mediator and is never conditioned upon for primary or secondary causal contrasts.

### 2.2 Adversarial Network Security Review
- **Docker Internal Bridge (`--internal`)**: Drops default gateways and external routing; verifies direct IP connections (`1.1.1.1:443`, `8.8.8.8:53`) fail closed.
- **CONNECT-Only Egress Gateway (`arm_gateway.py`)**: Rejects non-CONNECT methods, IP literals, proxy loops, and all non-whitelisted destinations. Whitelists `api.openai.com:443` $\to$ `model-upstream:8443`.
- **Candidate Container Hardening**: Non-root UID `65534:65534` (`nobody`), `--read-only` rootfs, `CapDrop=["ALL"]`, `/tmp` tmpfs (`noexec,nosuid`).
- **Isolation Probes**: Verified across 9 live Docker tests ($186.2\text{ s}$), confirming Arm A cannot access concurrent Arm B MCP containers, and network faults fail closed before workload execution.

### 2.3 Statistical Methodology Review
- **Task-Level Sign-Flip Test**: Reduces each task to its within-task mean paired difference $\bar{D}_t$ and flips signs at the task level ($s_t \in \{-1, +1\}$), maintaining nominal Type I error ($\alpha = 0.05$) under task treatment heterogeneity ($\tau^2 > 0$).
- **Block-Level Sign-Flip Test**: Retained strictly as a sensitivity test (sharp null); proven to over-reject ($8.7\%\text{--}10.3\%$) under heterogeneous nulls when $R > 1$.
- **Inference Precision**: Exact enumeration used for $K \le 16$; Monte Carlo permutation with Phipson-Smyth $+1$ finite-sample correction ($N_{\text{perm}} = 19{,}999$) used for $K > 16$.
- **Two-Stage Percentile Bootstrap**: Resamples tasks with replacement, then blocks within task with replacement ($N_{\text{boot}} = 5{,}000$).
- **Multiplicity Control**: Secondary family (`C-B`, `C-A`, `B-A:fully_correct`) adjusted via Holm step-down.

### 2.4 Scorer Contracts and Dimension Aggregation
- For multidimensional scorers (`knowledge-pilot-v2` and `knowledge-pilot-v2.1` on tasks `D01`–`D03`, `E01`–`E05`), top-level `passed` and `total` are `null` in the canonical JSON output.
- `records.from_runner_result` aggregates `passed` and `total` across evaluated subdimensions (`schema_validity`, `factual_correctness`, `version_repository_identity`, `source_quality`, `unsupported_claims`), yielding normalized scores in $[0, 1]$ matching benchmark checks.
- Candidate failures (timeouts, exit code errors) receive $0.0$ in ITT analysis. Infrastructure failures, scoring errors, and missing outcomes receive `None` and are bounded via Manski sensitivity bounds.

---

## 3. Corrections and Hardening Applied

1. **Confirmatory Task Minimum Unified to 30**: Aligned `MINIMUM_CONFIRMATORY_S1_TASKS = 30` in `study_configs.py` with `manifest.py` and `PREREGISTRATION.md`.
2. **Multidimensional Scorer Contract Handling**: Resolved false `infrastructure_failure` classifications by aggregating dimension-level checks when top-level fields are `None`.
3. **Attempt Artifact Journaling**: Added raw attempt output preservation in `runner.py`'s `TrialLedger.write_attempt_evidence` to preserve crash/failure context.
4. **Baseline Difficulty Uncertainty Decision Rule**: Implemented uncertainty-aware classification in `calibration_pipeline.py` recognizing that $R=3$ repetitions yield wide confidence intervals, categorizing borderline tasks as `"inconclusive_sample_size_limited"`.
5. **Readiness Gates Verification**: Added formal evaluation of the 5 research readiness gates via CLI command `readiness-gates`.
6. **Cross-Version Floating-Point Canonicalization**: Canonicalized float precision to 10 decimal places in `dryrun.result_digest` to eliminate 1-ULP platform and Python version discrepancies (Python 3.11 vs 3.14) in floating-point summation during synthetic dry-run verification.

---

## 4. Stage 2.7 Calibration Plan & Task Eligibility

### 4.1 Reconstructed Task Catalogue (31 Tasks Total)

From [`calibration_eligibility_report.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/calibration_eligibility_report.json):
- **`S1_confirmatory_core` (0 tasks)**: 0 tasks currently qualify under the preregistered variance rule ($n_A \ge 3$, $0.10 \le \bar{Y}_A \le 0.90$, zero `BEN-002` coupling).
- **`S2_calibration_needed` (17 tasks)**: `R01`–`R12`, `C03`, `C04`, `H01`, `H04`, `H10`. Eligible for Arm-A baseline calibration.
- **`RC_recalibration_required` (8 tasks)**: `C01`, `C02`, `C05` (ceiling saturation); `D01`, `D02`, `D03` (`BEN-002` frozen candidate list); `E04`, `E05` (`BEN-002` unprompted schema key requirements).
- **`Q_quarantined_or_smoke` (6 tasks)**: `B01`, `B02`, `B03`, `E01`, `E02`, `E03` (historical unsupported or environment coupling).

### 4.2 Baseline Calibration Schedule (`calibration_schedule.json`)

- **Design**: Arm A only (baseline control).
- **Candidate Tasks**: 17 tasks from $S2$.
- **Repetitions**: $R = 3$ per task.
- **Total Planned Trials**: $17 \times 3 = 51$ trials.
- **Resource Estimates**:
  - Estimated prompt tokens: ~612,000 tokens.
  - Estimated completion tokens: ~127,500 tokens.
  - Estimated cost (GPT-4o rates): ~\$3.00 – \$4.50 USD.
  - Expected wall-clock runtime: ~1.2 hours.
- **Status**: `PREPARED_NOT_EXECUTED`. Zero real model API calls have been run.

### 4.3 Mathematical and Methodological Feasibility Analysis for Confirmatory Quota ($K \ge 30$)

A rigorous audit of the benchmark catalogue reveals fundamental mathematical and methodological blockers to reaching the preregistered confirmatory core threshold ($K \ge 30$ tasks in $S1$):

1. **Schedule Upper-Bound Blocker ($\max(|S1|) = 17 \ll 30$)**:
   - Current confirmatory core count: $|S1| = 0$.
   - The calibration schedule tests only the 17 $S2$ candidate tasks.
   - Even under a theoretical 100% pass rate where all 17 tasks exhibit non-degenerate baseline variance ($\bar{Y}_A \in [0.10, 0.90]$), the maximum possible yield is $0 + 17 = 17$ tasks.
   - This leaves a deterministic deficit of at least $13$ tasks ($43.3\%$ short of the required 30).
2. **Whole-Catalogue Blocker ($\text{Total Usable Non-Quarantined Tasks} = 25 < 30$)**:
   - Total benchmark tasks: $N = 31$.
   - 6 tasks ($B01$–$B03$, $E01$–$E03$) are quarantined ($Q$) due to historical verifier failures and schema issues.
   - Total non-quarantined tasks: $31 - 6 = 25$ tasks ($17\ S2 + 8\ RC$).
   - Even if all 8 $RC$ (recalibration/decoupling) tasks were fully repaired and added to the calibration pool, the entire usable task pool is $25 < 30$.
   - **Conclusion**: Reaching $K = 30$ confirmatory tasks from the existing 31-task catalogue is mathematically impossible. The benchmark must be expanded by at least $+5$ tasks (and realistically $+15$ to $+20$ tasks to absorb empirical attrition), or the minimum confirmatory threshold must be formally re-specified in the protocol.
3. **Statistical Attrition Reality (~50%–70% Yield)**:
   - Historical R-Knowledge-MCP evaluations indicate substantial saturation on either floor ($0.0$) or ceiling ($1.0$).
   - In realistic empirical calibration, only ~8 to 12 of the 17 $S2$ candidate tasks are expected to fall within $[0.10, 0.90]$.
4. **Sample-Size Uncertainty at $R = 3$**:
   - With $R = 3$ observations per task, the Wilson 95% confidence interval for a task with $1/3$ success is $[0.061, 0.792]$ (crosses the $0.10$ floor), and for $2/3$ is $[0.208, 0.939]$ (crosses the $0.90$ ceiling).
   - Tasks scoring $1/3$ or $2/3$ are flagged as `"inconclusive_sample_size_limited"`. Robust qualification requires $R \ge 5$ baseline repetitions per task.

---

## 5. Formal Research Readiness Gates

| Gate | Description | Status | Evidence & Blockers |
| :--- | :--- | :--- | :--- |
| **Gate 1** | Offline Research Infrastructure | **`PASS`** | 156 offline validity, artifact, runner, and calibration tests pass; 279 frozen evidence files verified with 0 differences. |
| **Gate 2** | Real Docker Experiment Infrastructure | **`PASS`** | 9 live Docker tests pass (186.2s); 3-trial live CLI smoke test passes on D01 with 12/12 checks and clean teardown. |
| **Gate 3** | Baseline Model Calibration Execution | **`BLOCKED`** | Awaiting explicit project owner spend authorization; no model API credits authorized. |
| **Gate 4** | Three-Arm Pilot Execution | **`BLOCKED`** | Awaiting completion of Gate 3 baseline calibration and human pilot spend authorization. |
| **Gate 5** | Confirmatory Experiment Eligibility | **`BLOCKED`** | Currently 0 tasks meet S1 confirmatory criteria; requires Gate 3 baseline data to qualify $\ge 30$ tasks. |

---

## 6. Offline Verification Summary

```
============================== 156 passed, 9 deselected in 28.50s ==============================
- tests/test_stage2_validity.py: 73 passed
- tests/test_stage2_artifacts.py: 41 passed
- tests/test_stage26_live_runner.py: 31 passed (offline)
- tests/test_stage27_calibration.py: 11 passed (eligibility, schedule validation, mock execution, CLI commands, blockers)
- tests/test_stage26_live_runner.py (live Docker): 9 passed (verified in Phase 4 / Stage 2.6)
- ruff check . & ruff format --check .: 318 files checked, 0 errors, all formatted
- cli.py frozen --verify: 279 frozen files, 0 differences
```

---

## 7. Execution Commands for Authorized Calibration (Future Phase)

The calibration execution adapter is fully implemented in `calibration_pipeline.py` and exposed via `cli.py`:

1. **Review Readiness Gates**:
   ```bash
   python -m benchmarks.codex_r.studies.stage2_validity_v1.cli readiness-gates
   ```

2. **Offline Mock Calibration Run (Zero Cost, No Network)**:
   ```bash
   python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration \
     --schedule benchmarks/codex_r/studies/stage2_validity_v1/calibration_schedule.json \
     --out-dir benchmarks/codex_r/studies/stage2_validity_v1/calibration_runs_mock \
     --mock
   ```

3. **Live 51-Trial Baseline Calibration (Arm A only, Requires Spend Authorization)**:
   ```bash
   # Requires OPENAI_API_KEY exported in host shell (never inside containers)
   export OPENAI_API_KEY="sk-..."

   python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration \
     --schedule benchmarks/codex_r/studies/stage2_validity_v1/calibration_schedule.json \
     --out-dir benchmarks/codex_r/studies/stage2_validity_v1/calibration_runs \
     --authorize-spend
   ```

4. **Evaluate Difficulty & Uncertainty on Calibration Results**:
   ```bash
   python -m benchmarks.codex_r.studies.stage2_validity_v1.cli evaluate-baseline \
     --records benchmarks/codex_r/studies/stage2_validity_v1/calibration_runs/trial_records.jsonl \
     --out benchmarks/codex_r/studies/stage2_validity_v1/baseline_difficulty_report.json
   ```

5. **Select Qualified Tasks for S1 Confirmatory Core**:
   Qualify tasks exhibiting empirical baseline difficulty $\bar{Y}_A \in [0.10, 0.90]$ and non-degenerate variance until $K \ge 30$ tasks are qualified (addressing catalogue expansion requirements).
