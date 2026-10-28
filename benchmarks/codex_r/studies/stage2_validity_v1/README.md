# Stage 2 — Benchmark Scientific Validity (`stage2_validity_v1`)

This directory contains the protocol, statistical analysis engine, historical calibration pipeline, synthetic validation suite, and research documentation for **Stage 2 — Benchmark Scientific Validity** of the R-Knowledge-MCP 2.0 benchmark (`stage2_validity_v1`).

## Milestone Status

| Milestone | Status | Summary |
| :--- | :--- | :--- |
| **INFRASTRUCTURE READY** | **ACHIEVED** | Three-arm protocol, blocked Latin-permutation randomization, JSON Schema v1.0 trial records, schema-1.2 telemetry projection, task-level statistical analysis engine, power simulation, frozen digest verification, and synthetic dry-run harness are implemented and tested. |
| **PILOT READY** | **NOT REACHED** | Blocked by (1) `benchmarks/codex_r/run_simple.py` lacking native 3-arm (`A`/`B`/`C`) plan ingestion and randomized execution order, and (2) unimplemented container egress proxy enforcement (`exploratory/egress_proxy.py` is not wired into `run_simple.py`, which uses a plain Docker bridge network). |
| **CONFIRMATORY EXPERIMENT READY** | **NOT REACHED** | Blocked by pilot readiness plus: (1) `0` tasks currently meet the Arm-A-only confirmatory discrimination criterion (`Stratum S1`: $n_A \ge 3$ and $0.10 \le \bar{Y}_A \le 0.90$), (2) preregistration commit hash is not yet frozen on git prior to data collection, and (3) paid model execution budget is not authorized. |
| **STAGE 3A EXECUTION** | **EXECUTION READY (not empirically verified)** | Real execution adapter on the existing runner (`run_simple.run_trial`) for arms A/B/C and live calibration, verified end to end with a mocked model API, real Docker, real MCP and real R scorers. Preregistration amendment **A1** (protocol 1.1.0, `PREREGISTRATION_AMENDMENT_A1.md`) replaces the network-topology rule with per-trial capability equivalence for new runs; originals unchanged, no retroactive eligibility. Calibration-authorized: **no**. Study 2 (web search): **unsupported**. Confirmatory-ready: **no** (at most 14 of 30). See `STAGE3A_REAL_EXECUTION.md`. |
| **EMPIRICAL EFFECT ESTABLISHED** | **NOT ESTABLISHED** | **No live model trials were executed in Stage 2.** Historical runs are observational/heterogeneous and synthetic dry runs use deterministic fake scores. No empirical claim about R-Knowledge-MCP effectiveness is made. |

## Directory Layout

### Python Modules

- [`protocol.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/protocol.py): Defines the three experimental arms (`A` disabled, `B` available/voluntary, `C` encouraged), byte-identical base instructions across `A` and `B`, encouragement suffix for `C`, capability/egress contracts, and `TrialSpec` validation.
- [`design.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/design.py): Deterministic seed derivation (`derive_seed`) and counterbalanced Latin-permutation block randomization (`generate_plan`, `verify_plan_balance`).
- [`records.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/records.py): Trial record construction, JSON Schema Draft 2020-12 validation against [`trial_record.schema.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/trial_record.schema.json), protocol violation detection (`check_trial_compliance`), and runner output conversion (`from_runner_result`).
- [`telemetry.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/telemetry.py): Projects schema-1.2 `telemetry.jsonl` streams into 7 distinct observability levels (`available`, `listed`, `attempted`, `completed`, `errored`, `delivered`, `result_use_proxy`), handles duplicate/interrupted/unstarted call events, and labels client-server correlation certainty (`confirmed_protocol_id`, `ordinal_unconfirmed`, `unmatched`).
- [`analysis.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/analysis.py): Preregistered intention-to-treat (ITT) statistical engine using task-level sign-flip inference (`task_level_sign_flip_test`), two-stage percentile bootstrap CIs (`paired_bootstrap_ci`), block-level sharp-null sensitivity test (`paired_randomization_test`), Holm step-down multiplicity adjustment (`holm_adjust`), Manski worst/best bounds (`manski_bounds`), and leave-one-task-out stability (`leave_one_task_out`).
- [`power.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/power.py): Monte Carlo power and Type I error simulator across grid sizes ($K \in \{12, 20, 30, 40\}$, $R \in \{2, 3, 5\}$, $\delta \in \{-0.20, -0.10, 0.0, 0.10, 0.20, 0.30\}$) plus explicit comparison of task-level vs block-level Type I error under heterogeneous task effects ($\tau = 0.10$).
- [`calibration.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/calibration.py): Read-only aggregation of historical `benchmarks/codex_r/results/*/results.json` files and 31-task catalogue stratification (`S1_confirmatory_core`, `S2_calibration_needed`, `RC_recalibration_required`, `Q_quarantined_or_smoke`).
- [`manifest.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/manifest.py): Builds [`experiment_manifest.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/experiment_manifest.json) and computes/verifies [`frozen_evidence_digests.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/frozen_evidence_digests.json).
- [`prereg.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/prereg.py): Renders [`PREREGISTRATION.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/PREREGISTRATION.md) directly from `experiment_manifest.json` so prose and machine contracts cannot drift.
- [`dryrun.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/dryrun.py): Executes 5 synthetic validation scenarios (`null`, `positive`, `negative_tool_tax`, `heavy_missingness`, `leaky_control`) end-to-end without model API calls.
- [`cli.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/cli.py): Deterministic CLI entry point for all Stage 2 operations.

### Frozen Artifacts & Synthetic Validation

- [`experiment_manifest.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/experiment_manifest.json): Machine-readable study manifest (`core_sha256: 4eaee4975f9b7f7cd94ed875ab1464e4b35dcb7f57c52f8a3a2a60c20fcf603e`).
- [`trial_record.schema.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/trial_record.schema.json): JSON Schema Draft 2020-12 contract for trial records.
- [`frozen_evidence_digests.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/frozen_evidence_digests.json): SHA-256 digests of 279 frozen evidence, task, oracle, and scorer files at baseline commit `08ef9e9e2711e1174ed6796b3e3e60bf0ad7ca58`.
- [`task_catalog.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/task_catalog.json): 31-task catalogue with 8-dimension profiles and Arm-A-only stratum classifications.
- [`historical_calibration_summary.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/historical_calibration_summary.json): Read-only summary of pre-Stage-2 historical runs.
- [`power_simulation.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/power_simulation.json): Monte Carlo power and Type I error simulation outputs.
- [`synthetic_validation/`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/synthetic_validation/SUMMARY.json): End-to-end synthetic dry-run plans, JSONL trial records, and analysis outputs (`synthetic_validation: true`).

### Research Documentation

1. [`METHODOLOGY_AUDIT.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/METHODOLOGY_AUDIT.md): Root-cause audit of historical benchmark runs and validity threats.
2. [`TASK_CALIBRATION.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/TASK_CALIBRATION.md): Task catalogue, 8-dimension classification, saturation analysis, and Arm-A-only screening.
3. [`SCORING_VALIDITY.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/SCORING_VALIDITY.md): Audit of scorer families (`legacy`, `knowledge-pilot-v2.1`, `hard-v1`) and `BEN-002` frozen-oracle coupling.
4. [`TELEMETRY_CONTRACT.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/TELEMETRY_CONTRACT.md): Seven-level tool-observability contract and client-server correlation rules.
5. [`EXPERIMENT_DESIGN.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/EXPERIMENT_DESIGN.md): Three-arm A/B/C design, counterbalanced randomization, runner integration audit, and blockers.
6. [`STATISTICAL_ANALYSIS_PLAN.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/STATISTICAL_ANALYSIS_PLAN.md): Formal SAP covering task-level sign-flip inference, block-level sensitivity, bootstrap CIs, Holm adjustment, and missing-data rules.
7. [`PREREGISTRATION.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/PREREGISTRATION.md): Auto-rendered preregistration locked to `experiment_manifest.json`.
8. [`POWER_AND_BUDGET.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/POWER_AND_BUDGET.md): Power simulation tables, Type I error verification under heterogeneity, and budget formulas.
9. [`REPRODUCIBILITY.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/REPRODUCIBILITY.md): Deterministic CLI regeneration and verification commands.
10. [`STAGE2_REPORT.md`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/STAGE2_REPORT.md): Comprehensive Stage 2 report and readiness assessment.
