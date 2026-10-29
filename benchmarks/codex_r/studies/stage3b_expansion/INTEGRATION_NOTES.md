# Stage 3B Integration Notes

## 1. Architectural Integration Overview

Stage 3B (`benchmarks/codex_r/studies/stage3b_expansion/`) is integrated as a modular suite alongside `hard` (`benchmarks/codex_r/hard/`) and `knowledge_pilot` (`benchmarks/codex_r/knowledge_pilot.py`), preserving all frozen historical artifacts and existing CLI contracts.

### Invariants Preserved
1. **Frozen Evidence Unchanged**: `benchmarks/codex_r/studies/stage2_validity_v1/frozen_evidence_digests.json` verifies 279 tracked files from baseline commit `08ef9e9e2711e1174ed6796b3e3e60bf0ad7ca58` with **0 differences**.
2. **Historical 31-Task Catalogue Unchanged**: `benchmarks/codex_r/studies/stage2_validity_v1/task_catalog.json` and `historical_calibration_summary.json` retain their exact 31 historical tasks (`R01`–`R12`, `H01`–`H10`, `B01`–`B03`, `C01`, `C03`, `C04`, `D01`–`D03`, `E01`–`E05`).
3. **Committed Stage 2 / 2.5 / 2.7 Reports Unchanged**: `experiment_manifest.json`, `PREREGISTRATION.md`, `calibration_schedule.json` (75 trials across the 25 non-quarantined historical tasks), `calibration_eligibility_report.json`, `pilot_specification.json`, and `readiness_gates_report.json` remain byte-identical to their generators.

---

## 2. Module-by-Module Integration Surface

### 2.1 `benchmarks/codex_r/run_simple.py`
- **Suite Dispatch (`suite_for`)**:
  - Recognizes any Stage 3B task via `stage3b.owns(task)` (`X[AGPVRM][0-9]{2}`) and routes it to `(stage3b, "consolidated", allowed_tools)` using the same consolidated MCP tool surface as `hard` and `knowledge_pilot`.
- **CLI Task Selection (`expand_tasks` and `--tasks`)**:
  - Accepts `--tasks stage3b-pool` (expanding to all 30 Stage 3B task IDs in canonical order) as well as any individual Stage 3B task ID (`XA01`..`XM04`).
- **Container Image Routing (`default_image_refs`)**:
  - Automatically selects `codex-r-benchmark:pilot-bioc` (scorer) and `rkmcp-codex-runtime:codex-0.163.0-bioc` (executor) when any scheduled Stage 3B task declares `"image": "bioc"` (`XM01`, `XM04`), and the standard base images (`codex-r-benchmark:pilot`, `rkmcp-codex-runtime:codex-0.163.0`) otherwise.
- **Experiment Manifest & Trial Records (`write_experiment_manifest`, `experiment_package_pins`, `run_trial`)**:
  - Records `stage3b_verifier_sha256`, per-task `spec` and `inputs` fixture digests, package version pins from `stage3b.manifest()["environment"]["pins"]`, `"suite": "r-knowledge-mcp-stage3b-v1"`, `fully_correct`, and `environment_versions`.

### 2.2 `benchmarks/codex_r/studies/stage2_validity_v1/manifest.py`
- **`task_files(task)`**:
  - For `task.startswith("X")`, delegates to `stage3b_expansion.build.task_files(task)`, returning `[prompt.md, task.json, *fixtures, verifier/<ID>.R]`.

### 2.3 `benchmarks/codex_r/studies/stage2_validity_v1/scorer_bindings.py`
- **`STAGE3B_SCORER = "stage3b-expansion-v1"`**:
  - `bind(task, "stage3b-expansion-v1")` binds any `X...` task to `ScorerBinding` over `stage3b_build.scorer_files()` (`suite.py`, `verifier/run.R`, `verifier/lib.R`, and `hard/verifier/harness.R`), with `label_executable=True` and `multidimensional=False`.

### 2.4 `benchmarks/codex_r/studies/stage2_validity_v1/runner.py`
- **`_task_and_scorer_meta(task)`**:
  - Resolves `X...` tasks using `scorer_bindings.STAGE3B_SCORER` so `build_trial_invocation_spec`, `pin_plan_identities`, and `execute_study_plan` compute and verify exact 64-hex `task_sha256` and `scorer_sha256` digests before every trial attempt.

### 2.5 `benchmarks/codex_r/studies/stage2_validity_v1/legacy_executor.py`
- **`scorer_isolation(task)` & `REFERENCE_MARKERS`**:
  - Verifies that zero Stage 3B task or verifier files lie inside the MCP container's `/evaluated` (`src/`) mount, and monitors non-MCP tool outputs for `"stage3b_expansion/verifier"` reference-access markers.

### 2.6 `benchmarks/codex_r/studies/stage2_validity_v1/calibration_pipeline.py`
- **`stage3b_calibration_candidate_tasks()` & `build_stage3b_calibration_schedule()`**:
  - Reads `stage3b_expansion/catalog.json` to build deterministic Arm-A calibration schedules (`study_id="stage3b_baseline_calibration"`) for all validated Stage 3B tasks (`pool.calibration_eligible == True`).
- **`validate_calibration_schedule()`**:
  - Validates Stage 3B calibration schedules against `stage3b_calibration_candidate_tasks()` and verifies that every trial's `task_sha256`, `scorer_sha256`, and `scorer_version` (`stage3b-expansion-v1`) match the files on disk.
- **`live_execution_blockers()` & `live_execution_limitations()`**:
  - Includes `stage3b.task_ids()` in the set of legacy-runner known tasks and maps them to `scorer_bindings.STAGE3B_SCORER`, confirming zero structural blockers (`live_execution_blockers(sched) == []`) for Stage 3B schedules.
