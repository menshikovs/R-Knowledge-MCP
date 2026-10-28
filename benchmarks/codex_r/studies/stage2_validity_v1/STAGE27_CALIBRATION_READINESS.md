# Stage 2.7: Independent Review, Integration and Pilot Calibration Preparation Report

**Date**: October 28, 2026 (pre-merge correction the same day)  
**Repository**: `https://github.com/menshikovs/R-Knowledge-MCP`  
**Base Branch**: `2.0`  
**Working Branch**: `feature/stage2-benchmark-validity`  
**Baseline Commit**: `08ef9e9e2711e1174ed6796b3e3e60bf0ad7ca58`  
**Pull Request**: `https://github.com/menshikovs/R-Knowledge-MCP/pull/28` (#28)  
**Final Status**: `MOCK-READY` · live executor `NOT READY` · calibration `NOT AUTHORIZED` · confirmatory `NOT READY`

> **Correction notice.** An earlier revision of this report declared `STAGE 2.7 READY FOR
> CALIBRATION` and documented an `execute-calibration --authorize-spend` command for a live
> 51-trial run. That command always raised `NotImplementedError`: no real-model executor exists.
> The earlier revision also mislabelled the S2 *control* stratum as "calibration needed", listed
> strata that contradict `task_catalog.json`, and quoted a cost estimate at another model's prices.
> Sections 4–8 replace those statements.

> **Superseded in part by Stage 3A (2026-10-28).** See
> [`STAGE3A_REAL_EXECUTION.md`](STAGE3A_REAL_EXECUTION.md). `execute-calibration --executor live`
> now runs on the existing benchmark runner (`run_simple.run_trial`) after authorization and a
> spend ceiling; it no longer exits 3 for the current schedule. The live executor status is
> `IMPLEMENTED_NOT_EMPIRICALLY_VERIFIED`. The live-executor statements and commands in §1, §6, §7
> and §9 below describe the Stage 2.7 state. The dimension aggregation described in §2.4 and §3
> item 2 was removed (see the corrections there). The calibration schedule's scorer digests were
> re-pinned to the scorers that actually execute.

| Status | Value | Meaning |
| :--- | :--- | :--- |
| **Mock-ready** | **YES** | Calibration schedules run end to end through the Stage 2 ledger with the in-process mock executor and through the real Docker topology with a local mock model. Every record is `synthetic: true`. |
| **Live-executor-ready** | **NO** | No real-model workload, upstream or credential path exists. All 25 scheduled tasks need the R scorer container, which the live runner does not run (§7). |
| **Calibration-authorized** | **NO** | No owner-approved spend ceiling exists. `--authorize-spend` alone is refused. |
| **Confirmatory-ready** | **NO** | 0 S1 tasks. At most 8 after calibration, and 14 if the Q scorers are also revised, against the preregistered 30 (§4.3). |

---

## 1. Executive Summary

Stage 2.7 delivers an independent scientific and architectural review of the Stage 2–2.6 implementation. It adds a task eligibility pipeline and a baseline difficulty evaluation, prepares an Arm-A-only calibration schedule (25 tasks × 3 = 75 planned trials, not executed), adds a fail-closed spend ceiling, defines the 5 research readiness gates, and keeps the real-model execution path explicitly unavailable.

No model API calls were executed. No empirical benefit claims are made based on mock data.

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
- ~~`records.from_runner_result` aggregates `passed` and `total` across evaluated subdimensions …~~ **Corrected in Stage 3A.** The canonical scorers deliberately report no `passed`/`total` and no overall score (`overall_score: null`), and they abstain (`fully_correct: null`) on unknown claims. Summing the dimensions invented an aggregate the scorer refuses to make, and could call an abstention "fully correct". The preregistered primary outcome (passed/total) is therefore *undefined* for these scorers. Such a trial is a missing outcome (`scoring_error`), and the scorer's own verdict is kept in `scorer_result`. Only D01 and D03 are scored by v2.1; the other knowledge-pilot tasks are scored by the knowledge-pilot `legacy` scorer (`scorer_bindings.py`).
- Candidate failures (timeouts, exit code errors) receive $0.0$ in ITT analysis. Infrastructure failures, scoring errors, and missing outcomes receive `None` and are bounded via Manski sensitivity bounds.

---

## 3. Corrections and Hardening Applied

1. **Confirmatory Task Minimum Unified to 30**: Aligned `MINIMUM_CONFIRMATORY_S1_TASKS = 30` in `study_configs.py` with `manifest.py` and `PREREGISTRATION.md`.
2. **Multidimensional Scorer Contract Handling**: Resolved false `infrastructure_failure` classifications ~~by aggregating dimension-level checks when top-level fields are `None`~~. *Stage 3A correction:* such results are now a missing primary outcome (`scoring_error`), with the canonical result preserved, rather than an invented sum (see §2.4).
3. **Attempt Artifact Journaling**: Added raw attempt output preservation in `runner.py`'s `TrialLedger.write_attempt_evidence` to preserve crash/failure context.
4. **Baseline Difficulty Uncertainty Decision Rule**: Implemented uncertainty-aware classification in `calibration_pipeline.py` recognizing that $R=3$ repetitions yield wide confidence intervals, categorizing borderline tasks as `"inconclusive_sample_size_limited"`.
5. **Readiness Gates Verification**: Added formal evaluation of the 5 research readiness gates via CLI command `readiness-gates`.
6. **Cross-Version Floating-Point Canonicalization**: Canonicalized float precision to 10 decimal places in `dryrun.result_digest` to eliminate 1-ULP platform and Python version discrepancies (Python 3.11 vs 3.14) in floating-point summation during synthetic dry-run verification.

---

## 4. Stage 2.7 Calibration Plan & Task Eligibility

### 4.1 Reconstructed Task Catalogue (31 Tasks Total)

Source: [`task_catalog.json`](task_catalog.json), which `calibration.build_catalog` reproduces exactly from history, and [`calibration_eligibility_report.json`](calibration_eligibility_report.json). The stratum meanings are the preregistered ones (`experiment_manifest.json` → `confirmatory_task_rule.strata`). S1 requires a **target task by its text** (`calibration.target_by_features`, classified before any trial) **and** an in-range Arm-A screen.

| Stratum | Preregistered meaning | Tasks | Count | Can become S1? |
| :--- | :--- | :--- | ---: | :--- |
| `S1` | target | none | 0 | — |
| `S2` | control (tool-use tax) | `R01–R10`, `R12`, `B01–B03`, `H01`, `H04`, `H10` | 17 | **Never.** Not a target by task text. |
| `RC` | recalibrate | `R11`, `C02–C05`, `E02`, `E03` (n_A < 3); `C01` (ceiling, n_A = 3) | 8 | Yes, if the Arm-A screen lands in [0.10, 0.90] |
| `Q` | quarantined | `D01–D03`, `E01`, `E04`, `E05` (BEN-002) | 6 | Only after scorer revision and revalidation |

### 4.2 Baseline Calibration Schedule (`calibration_schedule.json`, v1.1)

- **Selection rule**: every non-quarantined task (`CALIBRATION_STRATA = ("RC", "S2")`). RC tasks determine S1 membership. S2 controls get a baseline difficulty screen. Q stays excluded until its scorers are revised.
- **Design**: Arm A only, 3 repetitions, **25 tasks × 3 = 75 planned trials**. The 8 RC tasks are listed in `candidates_that_can_enter_s1`.
- **Change from v1.0**: v1.0 hard-coded 17 tasks (14 S2 controls plus RC `R11`, `C03`, `C04`). It omitted `B01–B03` and five RC tasks, and called the whole set "S2". That list is a strict subset of v1.1. Validation rejects v1.0 schedules (`schedule_version`). **This composition is a design choice for the project owner.** `build_calibration_schedule(tasks=...)` narrows it, for example to the 8 RC tasks only.
- **Resource planning estimates** (not caps): about 900,000 prompt and 187,500 completion tokens; about 1.7 h expected wall clock. **No cost estimate is given.** No price for `gpt-6-luna` is recorded in this repository, and the earlier "GPT-4o rates" figure has been withdrawn.
- **Status**: `PREPARED_NOT_EXECUTED`, `model_execution_authorized: false`.

### 4.3 Reconciling the Preregistered Minimum (30) With the Catalogue

Computed by `calibration_pipeline.confirmatory_feasibility()`. The threshold is read from the manifest and **is not modified**.

| Quantity | Value |
| :--- | ---: |
| Preregistered minimum confirmatory (S1) tasks | 30 |
| Catalogue tasks / quarantined / non-quarantined | 31 / 6 / 25 |
| Current S1 tasks | 0 |
| S2 controls (can never be S1) | 17 |
| Max S1 after calibration, best case (every RC task in range) | **8** |
| Max S1 if the 6 Q scorers are also revised (all are targets by text) | **14** |
| Shortfall after calibration, best case | 22 |
| Minimum **new target tasks** required, even in the best case | **16** |
| Reachable with the current catalogue | **No** |

The earlier claims ("max 17 after calibration", "+5 tasks suffices") counted S2 controls as confirmatory candidates. That contradicts the preregistered S1 definition. Realistic attrition makes the deficit larger. With R = 3, Wilson intervals for 1/3 and 2/3 cross the 0.10 / 0.90 bounds, so such tasks are reported as `inconclusive_sample_size_limited`.

**Resolution options (owner decision):** add new, independently specified target tasks, or amend the preregistration through a documented, dated protocol change made before any confirmatory data are seen. Lowering the threshold to pass Gate 5 is not an option this report takes.

---

## 5. Formal Research Readiness Gates

Generated by `cli readiness-gates` into [`readiness_gates_report.json`](readiness_gates_report.json). The report now separates `mock_infrastructure_ready` (true) from `live_calibration_ready` (false), and carries the four statuses above under `execution_readiness`.

| Gate | Description | Status | Evidence & Blockers |
| :--- | :--- | :--- | :--- |
| **Gate 1** | Offline Research Infrastructure | **`PASS`** | §6 |
| **Gate 2** | Docker Experiment Infrastructure (**mock model only**) | **`PASS`** | §6. Not evidence of a real-model executor. |
| **Gate 3** | Baseline Model Calibration Execution | **`BLOCKED`** | `no_real_model_workload`, `no_real_model_upstream_or_credential_path`, `scorer_container_not_integrated`, `spend_not_authorized` |
| **Gate 4** | Three-Arm Pilot Execution | **`BLOCKED`** | Gate 3, the same executor blockers, and budget approval. No pilot execution command exists. |
| **Gate 5** | Confirmatory Experiment Eligibility | **`BLOCKED`** | At most 14 of 30 reachable. At least 16 new target tasks needed (§4.3). |

---

## 6. Verification Evidence (pre-merge correction, Windows 11, Docker 29.8.2)

| Check | Result |
| :--- | :--- |
| `ruff check .` / `ruff format --check .` | All checks passed / 321 files already formatted |
| `pytest -m "not docker"` (full suite) | 1890 passed, 130 skipped, 0 failed |
| Stage 2 / 2.5 / 2.6 / 2.7 offline subset | 190 passed |
| `pytest tests/test_stage27_docker_calibration.py tests/test_stage26_live_runner.py -m docker` | 14 passed (268.7 s); 0 leftover containers, 0 leftover networks |
| `cli frozen --verify` | 279 frozen files; 0 differences |
| Manifest / generated-artifact consistency (10 checks: manifest, preregistration render, catalogue reproduction, study specs, eligibility, schedule and its validation, pilot spec, gates, single confirmatory minimum) | 10/10 equal |
| `execute-calibration --executor mock` on the 75-trial schedule with a ceiling | Runs end to end; all records `synthetic: true`; `evaluate-baseline` refuses them (exit 2) |
| `execute-calibration --executor docker-mock-model` on the real schedule | Refused before Docker is touched: none of the 25 tasks is host-scorable |
| `execute-calibration --executor live` | Exit 2 without `--authorize-spend` or without a full ceiling. Exit 3 `UNAVAILABLE` with both. **No files written, no network, no key read.** |

The Docker calibration tests run real topologies (internal network, CONNECT gateway, canary, fresh workspace, mock agent, mock model server, verified teardown). They use D01 because it is the only host-scorable task with a deterministic mock answer. They cover: usage billed against the ceiling and refusal when the ceiling is reached; partial usage telemetry charged at the full reserve; an infrastructure failure retried with linkage, while a candidate failure is not retried; a scorer digest change at execution time detected and stopping the run; and an interruption with its reserve charge, resume without re-running, and quarantine of a duplicated record line.

---

## 7. Live (Real-Model) Execution: Integration Blockers

`calibration_pipeline.live_execution_blockers()` computes these from the code that would run. `execute-calibration --executor live` prints them and exits 3.

1. **`no_real_model_workload`**: `live_network.TrialTopology` always runs `live_assets/mock_agent.py` in `python:3.11-slim`. No code path starts the agent runtime named in the schedule (`rkmcp-codex-runtime:codex-0.163.0`) inside the isolated topology, and that image is not present locally (only a `-bioc` variant is).
2. **`no_real_model_upstream_or_credential_path`**: the gateway tunnels `api.openai.com:443` only to `mock_model_server.py` on the private upstream network. `OPENAI_API_KEY` is in `HOST_SECRET_NAMES` and withheld from every container. A real run needs an upstream route plus credential injection **outside** the candidate container, for example at the gateway, so the key never enters the workload. Neither exists, and adding them requires a separate security review.
3. **`scorer_container_not_integrated`**: the live runner scores only on the host, with `knowledge-pilot-v2` (D01–D03, E01, E04, E05) and `knowledge-pilot-v2.1` (D01, D03 only). All 25 scheduled tasks use R verifiers (`legacy`, `hard-v1`, knowledge-pilot `.R`) that need the scorer container. Before this correction, the live runner also **crashed** with uncaught exceptions on such tasks. It now records `scorer_container_required` before creating any container.
4. **Spend is accounted, not metered.** The ceiling is enforced per attempt over *reported* usage (§8). A real integration must also confirm that the upstream reports usage for every request. Otherwise every trial is charged its full reserve.

---

## 8. Spend Control (`spend_control.py`)

`--authorize-spend` alone is refused. Live mode also requires `--max-spend-usd`, `--input-usd-per-mtok`, `--output-usd-per-mtok` and `--per-trial-reserve-usd`, all finite and > 0, with the reserve no larger than the ceiling. Prices come from the owner. None is assumed.

- **Before each attempt**: refuse if `spent + reserve > ceiling`. The run stops with `spend_ceiling_reached`, and the remaining trials are materialised as `not_executed`. If a retry is refused, the preceding infrastructure failure is committed rather than dropped.
- **After each attempt**: observed usage is priced. Unavailable or partial usage is charged the **full reserve**. Observed cost above the reserve stops the run (`per_trial_reserve_exceeded`), as does cumulative spend above the ceiling.
- **On resume**: the journal is replayed (`attempt_accounted`). Every started attempt without an accounting entry, meaning an interruption, is charged the full reserve. Resuming with a different ceiling or executor mode is rejected (`calibration_run.json`).
- **Stop conditions from the schedule**: 1 infrastructure retry, stop after 3 consecutive infrastructure failures, and stop once trials whose final attempt failed for infrastructure reasons exceed 20 % of the planned trials.
- **Limits**: this is accounting over reported tokens, not provider billing, and nothing can cut off a request mid-flight. The reserve must be chosen with the provider's own limits in mind.

### Synthetic vs. baseline evidence

`evaluate-baseline` / `evaluate_baseline_difficulty` refuse records unless every record declares `synthetic: false` and passes the Stage 2 record schema. The CLI also refuses a run directory whose `run_config.json` says `synthetic: true` or whose `calibration_run.json` says `baseline_evidence: false`, so editing the JSONL flag alone is not enough. `--allow-synthetic` exists for pipeline checks, and its report is labelled `synthetic_not_baseline_evidence`. These checks guard against accidental use, not deliberate tampering with every provenance file.

---

## 9. Commands

```bash
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli calibration-pipeline   # regenerate eligibility, schedule, pilot spec
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli readiness-gates        # four statuses + five gates

# Mock-ready: in-process, no network, synthetic records
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration \
  --executor mock --out-dir /tmp/cal-mock \
  --max-spend-usd 1 --input-usd-per-mtok 2 --output-usd-per-mtok 8 --per-trial-reserve-usd 0.05

# Mock-ready through real Docker isolation: only host-scorable schedules (see tests); the
# 75-trial schedule is refused because none of its tasks is host-scorable
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration --executor docker-mock-model

# Live: validates authorization and ceiling, then exits 3 (UNAVAILABLE). Nothing runs.
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration --executor live \
  --authorize-spend --max-spend-usd <USD> --input-usd-per-mtok <USD> \
  --output-usd-per-mtok <USD> --per-trial-reserve-usd <USD>

# Baseline evaluation refuses synthetic records (exit 2); --allow-synthetic labels the report
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli evaluate-baseline --records <run>/trial_records.jsonl
```

Exit codes of `execute-calibration`: 0 ok, 1 dataset problems, 2 refused input or blocked environment, 3 live execution unavailable. `--mock` remains as a deprecated alias for `--executor mock`.
