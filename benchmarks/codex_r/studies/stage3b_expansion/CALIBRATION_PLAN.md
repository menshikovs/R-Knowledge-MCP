# Stage 3B Baseline Calibration Plan

## 1. Purpose and Scope

All 30 Stage 3B tasks have passed offline real-R container verification (`validation_report.json`), making them **calibration-eligible** (`pool.calibration_eligible = true`). None of them is yet **confirmatory-eligible** (`pool.confirmatory_eligible = false`, `pool.stratum = null`).

Per the Stage 2 preregistration (`PREREGISTRATION.md` and `experiment_manifest.json`), a task may enter the confirmatory study only after an **Arm-A-only baseline calibration screen**:
1. Only **Arm A** (`without-mcp`, standard tool-neutral instructions) trials are executed during calibration.
2. Outcomes from Arms B or C (with MCP access) are **never** inspected or conditioned upon for task selection or stratum assignment.
3. Each task is run for $R = 3$ independent Arm-A repetitions in fresh containers and sessions.
4. Tasks whose empirical Arm-A mean score satisfies $\bar{S}_{t,A} \in [0.10, 0.90]$ are non-degenerate:
   - A `target_candidate` task with $\bar{S}_{t,A} \in [0.10, 0.90]$ enters **`S1` (`S1_target_confirmatory_core`)**.
   - A `control` task with $\bar{S}_{t,A} \in [0.10, 0.90]$ enters **`S2` (`S2_control_tool_use_tax`)** to measure tool-use overhead on tasks where MCP is not needed.
   - Tasks with $\bar{S}_{t,A} < 0.10$ (floor saturation) or $\bar{S}_{t,A} > 0.90$ (ceiling saturation) are excluded from the primary confirmatory estimand.

---

## 2. Deterministic Stage 3B Calibration Schedule

`calibration_pipeline.build_stage3b_calibration_schedule(seed=20261029)` generates the deterministic Arm-A calibration schedule for Stage 3B:

- **Study ID**: `stage3b_baseline_calibration`
- **Schedule Version**: `stage27-calibration-schedule-v1.1`
- **Candidate Tasks**: All 30 validated Stage 3B tasks (`XA01`–`XA06`, `XG01`–`XG05`, `XM01`–`XM04`, `XP01`–`XP05`, `XR01`–`XR05`, `XV01`–`XV05`)
- **Candidates Eligible to Enter `S1` (`target_candidate`)**: 12 tasks (`XA06`, `XM01`, `XM03`, `XM04`, `XP04`, `XR01`, `XR04`, `XR05`, `XV01`, `XV02`, `XV04`, `XV05`)
- **Control Candidates (`control`)**: 13 tasks (`XA01`–`XA05`, `XG01`–`XG03`, `XG05`, `XM02`, `XP01`, `XP02`, `XR03`)
- **Exploratory Candidates (`exploratory`)**: 5 tasks (`XG04`, `XP03`, `XP05`, `XR02`, `XV03`)
- **Arms**: `["A"]`
- **Repetitions per Task**: `3`
- **Total Planned Trials**: `90` (`30 tasks × 3 repetitions`)
- **Resource Planning Estimates** (`ESTIMATED_PROMPT_TOKENS_PER_TRIAL = 12,000`, `ESTIMATED_COMPLETION_TOKENS_PER_TRIAL = 2,500`, `ESTIMATED_SECONDS_PER_TRIAL = 82.6s`):
  - Estimated prompt tokens: `1,080,000`
  - Estimated completion tokens: `225,000`
  - Expected wall-clock duration: `2.07 hours` (timeout ceiling at 900s/trial: `22.5 hours`)

### Generating and Validating the Schedule Offline (Zero API Calls)

```bash
# Generate a Stage 3B calibration schedule JSON and run it through the mock executor:
python -c "
import json
from pathlib import Path
from benchmarks.codex_r.studies.stage2_validity_v1 import calibration_pipeline

sched = calibration_pipeline.build_stage3b_calibration_schedule(seed=20261029)
assert calibration_pipeline.validate_calibration_schedule(sched) == []
assert calibration_pipeline.live_execution_blockers(sched) == []
Path('stage3b_calibration_schedule.json').write_text(json.dumps(sched, indent=2) + '\n', encoding='utf-8')
"
```

---

## 3. Executing Calibration Once Authorized

### Step 1: Dry-Run Verification with Mock Executor (No API Spend)
```bash
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration \
  --schedule stage3b_calibration_schedule.json \
  --out-dir calibration_runs/stage3b_mock \
  --executor mock
```

### Step 2: Live Arm-A Execution (Requires Owner Spend Authorization on Linux / WSL2)
```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_EXECUTOR_API_KEY="sk-..."

python -m benchmarks.codex_r.studies.stage2_validity_v1.cli execute-calibration \
  --schedule stage3b_calibration_schedule.json \
  --out-dir calibration_runs/stage3b_live \
  --executor live \
  --authorize-spend \
  --max-spend-usd <OWNER_APPROVED_CEILING_USD> \
  --input-usd-per-mtok <INPUT_PRICE_PER_MTOK> \
  --output-usd-per-mtok <OUTPUT_PRICE_PER_MTOK> \
  --per-trial-reserve-usd <PER_TRIAL_RESERVE_USD>
```

### Step 3: Baseline Difficulty and Uncertainty Evaluation
```bash
python -m benchmarks.codex_r.studies.stage2_validity_v1.cli evaluate-baseline \
  --records calibration_runs/stage3b_live/trial_records.jsonl \
  --out calibration_runs/stage3b_live/baseline_difficulty_report.json
```

---

## 4. Combined Confirmatory Pool Accounting and Attrition Budget

| Pool Source | Total Tasks | Target Candidates (`RC` / `target_candidate`) | Quarantined Target Candidates (`Q`) | Controls (`S2` / `control`) | Exploratory |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Historical Catalogue (`task_catalog.json`)** | 31 | 8 | 6 | 17 | 0 |
| **Stage 3B Expansion (`catalog.json`)** | 30 | 12 | 0 | 13 | 5 |
| **Combined Pool** | **61** | **20** | **6** | **30** | **5** |

- **Current Confirmed `S1` Tasks**: `0` (no real-model calibration has been authorized).
- **Maximum Reachable `S1` Tasks After Calibrating Historical `RC` + Stage 3B `target_candidate`**: $8 + 12 = \mathbf{20}$ (across 19 independent clusters, since `XM01` and `XM04` share `"bioconductor-workflows"`).
- **Maximum Reachable `S1` Tasks If All 6 Quarantined (`Q`) Scorers Are Also Revised**: $20 + 6 = \mathbf{26}$.
- **Expected `S1` Yield Under 25%–35% Floor/Ceiling Attrition**:
  - Out of 20 unquarantined target candidates, a realistic 65%–75% in-range rate yields **$13\text{–}15$ `S1` tasks**.
- **Path to Confirmatory Execution**:
  1. Run Arm-A calibration on the 25 non-quarantined historical tasks + 30 Stage 3B tasks (or the 20 target candidates first to bound spend).
  2. Measure the empirical retention rate $\hat{\rho} = |\text{in-range target tasks}| / 20$.
  3. Either author a targeted **Stage 3C** batch of $(30 - |\text{S1}|) / \hat{\rho}$ additional `target_candidate` tasks, or execute a dated, pre-confirmatory preregistration amendment setting the confirmatory sample size to the empirically calibrated `S1` pool size (e.g., $N \in [15, 20]$ tasks with $R = 5$ repetitions per arm to preserve statistical power, as tabulated in `power_simulation.json`).

