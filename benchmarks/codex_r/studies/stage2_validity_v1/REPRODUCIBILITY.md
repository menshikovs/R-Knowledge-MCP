# Stage 2 Reproducibility and Verification Guide

All Stage 2 artifacts, schemas, digests, power simulations, and synthetic dry-run outputs are deterministically reproducible offline without network access or model API calls.

## 1. Environment Setup

Use the repository virtual environment (Python 3.11+ with `mcp>=1.30,<2`, `httpx`, `jsonschema`, `pytest`, `ruff`):

```powershell
.\.venv\Scripts\python.exe --version
```

## 2. Deterministic CLI Commands (`stage2_validity_v1.cli`)

### 2.1 Summarize Historical Results and Regenerate Task Catalogue

Reads local `benchmarks/codex_r/results/*/results.json` in read-only mode (defaulting to the pre-Stage-2 cutoff `before_date="20261028"`) and writes `historical_calibration_summary.json` and `task_catalog.json`:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.codex_r.studies.stage2_validity_v1.cli summarize-history
```

### 2.2 Regenerate Study Manifest and Preregistration

Builds `experiment_manifest.json` (`core_sha256: 4eaee4975f9b7f7cd94ed875ab1464e4b35dcb7f57c52f8a3a2a60c20fcf603e`) and renders `PREREGISTRATION.md` directly from the manifest:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.codex_r.studies.stage2_validity_v1.cli manifest
.\.venv\Scripts\python.exe -m benchmarks.codex_r.studies.stage2_validity_v1.cli prereg
```

### 2.3 Verify Frozen Evidence and Scorer SHA-256 Digests

Verifies all 279 frozen evidence, task, oracle, and scorer files against `frozen_evidence_digests.json` and exits non-zero if any file drifted:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.codex_r.studies.stage2_validity_v1.cli frozen --verify
```

### 2.4 Regenerate Power and Type I Error Simulation

Runs the deterministic Monte Carlo power grid (`seed=20261028`, `n_sim=300`) and task-level vs block-level Type I error comparison, writing `power_simulation.json`:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.codex_r.studies.stage2_validity_v1.cli power --seed 20261028 --n-sim 300
```

### 2.5 Execute End-to-End Synthetic Dry-Run Scenarios

Generates randomized plans, JSONL trial records, and preregistered analysis reports for all 5 synthetic scenarios (`null`, `positive`, `negative_tool_tax`, `heavy_missingness`, `leaky_control`) under `synthetic_validation/`:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.codex_r.studies.stage2_validity_v1.cli dryrun
```

### 2.6 Re-Run Analysis on Any Trial Record JSONL

Recomputes `analysis.json` from a `plan.json` and `trial_records.jsonl` file:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.codex_r.studies.stage2_validity_v1.cli reanalyze `
  --plan benchmarks/codex_r/studies/stage2_validity_v1/synthetic_validation/positive/plan.json `
  --records benchmarks/codex_r/studies/stage2_validity_v1/synthetic_validation/positive/trial_records.jsonl `
  --seed 20261028
```

## 3. Seed Derivation Contract

Randomization and permutation seeds are derived deterministically via `design.derive_seed(registration_commit, study_id, stage)`:

```python
digest = hashlib.sha256(f"{registration_commit}|{study_id}|{stage}".encode("utf-8")).hexdigest()
seed = int(digest[:16], 16) % (2**31 - 1)
```

For synthetic validation and pre-registration simulations before a git registration commit is frozen, `SYNTHETIC_DEFAULT_SEED = 20261028` (`registration_commit = "UNREGISTERED_SYNTHETIC_VALIDATION"`).

## 4. Automated Test and Lint Verification

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest tests/test_stage2_validity.py tests/test_stage2_artifacts.py -v
```
