# Stage 2 Scoring Validity and Oracle Independence Audit

## 1. Frozen Scorer Implementations Audited

In accordance with Stage 2 non-negotiable rules, all existing scorer implementations were audited in read-only mode and pinned by SHA-256 digest in [`frozen_evidence_digests.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/frozen_evidence_digests.json):

| Scorer Name | Source File | SHA-256 Digest | Applicable Tasks |
| :--- | :--- | :--- | :--- |
| `legacy` | [`benchmarks/codex_r/run_simple.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/run_simple.py) | `157e3933720d420fd51a3ff2f81b39dd7477a860f28b92e1530be7d2fc3c6812` | `R01–R12` |
| `knowledge-pilot-v2.1` | [`benchmarks/codex_r/knowledge_pilot_v21.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/knowledge_pilot_v21.py) | `c7d419fb933d3a9660ce602da0044b6d85dd56ca7278c498114dc54e2c2635bd` | `B01–B03`, `C01–C05`, `D01–D03`, `E01–E05` |
| `hard-v1` | [`benchmarks/codex_r/hard/suite.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/hard/suite.py) | `1bf84083e2b206933fa97b84342670dfed6167b249e0109ebcc44c545b1ac236` | `H01`, `H04`, `H10` |

## 2. Scorer Family Evaluation

### 2.1 `legacy` Behavioral Scorer (`R01–R12`)

- **Mechanism**: Executes deterministic R verification scripts (`Rscript -e ...`) inside the container workspace and checks functional postconditions (e.g., output CSV/RDS values, absence of deprecated function calls in AST/source, test pass/fail counts), returning `score` (`0..4`) and `max_score` (`4`), normalized in Stage 2 to `primary_score = score / max_score` $\in [0, 1]$.
- **Strengths**: High oracle independence (`oracle_independence = "high"`). Any valid R implementation that satisfies the behavioral postconditions and constraints receives credit.
- **Limitations**: Several tasks (`R01`, `R02`, `R04`) are too easy for frontier models (`mean_a = 1.0`), producing ceiling saturation. In addition, if the candidate fails to write the target file (`R03` in `20261028T113222Z-e5a013f7`), `run_simple.py` records `status = "error"` (`candidate_artifact_missing`), which Stage 2 maps via `records.from_runner_result()` to `status = "candidate_failure"` with `primary_score = 0.0`.

### 2.2 `knowledge-pilot-v2.1` Structured JSON Scorer (`B01–E05`)

- **Mechanism**: Grades a structured JSON response against frozen evidence snapshots in `benchmarks/codex_r/evidence/b1_frozen_20261026/`.
- **Claim Evidence Semantics (`v2` vs `v2.1`)**:
  - In `knowledge-pilot-v2`, claims whose ground-truth verification status in the frozen evidence was `unknown` were awarded `0.5` partial credit, artificially penalizing or rewarding confident claims depending on task composition.
  - In `knowledge-pilot-v2.1` (`score_claim_v21`), each claim is evaluated against frozen evidence states (`supported`, `contradicted`, `unknown`). Claims marked `unknown` by the candidate are treated as explicit **abstentions** (excluded from the precision denominator rather than given arbitrary partial credit), while `contradicted` claims receive `0.0` and incur an explicit contradiction count.
- **Confirmed Defect `BEN-002` (Oracle and Contract Coupling)**:
  1. **Discovery Tasks (`D01–D03`) — Frozen Candidate List**:
     - `D01` (`acceptable_packages`: `["survminer", "ggsurvfit", "survival"]`), `D02` (`["DESeq2", "edgeR", "limma"]`), and `D03` (`["SingleCellExperiment", "Seurat", "SeuratObject", "SpatialExperiment", "SummarizedExperiment"]`) grade `recommended_package` by exact membership in `acceptable_packages`.
     - Because R-Knowledge-MCP searches the same CRAN/Bioconductor metadata used to construct those lists, MCP-assisted trials are more likely to name the exact canonical package string, whereas a baseline trial naming an alternative valid package (or a synonym/extension package) receives `0.0` on the recommendation component.
  2. **API Evolution Tasks (`E01`, `E04`, `E05`) — Unprompted JSON Schema Equality**:
     - The task prompts ask the agent to write a JSON file summarizing deprecation/lifecycle status, but do not specify the exact JSON key names or allowed enum strings expected by the scorer (e.g., `E04` and `E05` score `0.0` across all 8 historical Arm A and Arm B runs because candidates emit human-reasonable JSON keys that do not match the scorer's hardcoded key names).
- **Stage 2 Disposition**: All `BEN-002`-affected tasks (`D01–D03`, `E01`, `E04`, `E05`) are quarantined from `S1_confirmatory_core` (`D01–D03`, `E04`, `E05` in `RC_recalibration_required`; `E01–E03` in `Q_quarantined_or_smoke`). They cannot enter a confirmatory headline estimate until their prompts and rubrics are recalibrated and re-screened on Arm A.

### 2.3 `hard-v1` Deterministic Holdout Scorer (`H01`, `H04`, `H10`)

- **Mechanism**: Evaluates candidate R functions (`solution.R`) against visible contract checks plus deterministic hidden holdout test cases (`benchmarks/codex_r/hard/tasks/H*/holdout_tests.R`), checking numerical accuracy, edge-case handling (ties, `NA`s, zero-variance windows, Barnard-Rubin df clamping), and forbidden package imports.
- **Strengths**: Highest oracle independence (`oracle_independence = "high"`) and zero coupling to MCP documentation text.
- **Limitations**: Currently `unexecuted` (`n_A = 0`) in historical `results.json` archives; requires Arm-A calibration runs (`Stratum S2_calibration_needed`).

## 3. Scorer Integrity and Hash Verification

To guarantee that no scorer or evidence snapshot changes silently between preregistration and analysis:

1. Every planned trial in `design.generate_plan()` and every observed record in `records.build_trial_record()` pins `task_sha256` and `scorer_sha256`.
2. `records.check_trial_compliance()` compares the observed `task_sha256` and `scorer_sha256` against the planned hashes and adds `"task_hash_mismatch"` or `"scorer_hash_mismatch"` to `protocol.capability_violations`, setting `protocol.compliant = False` if either drifts.
3. `manifest.verify_frozen_evidence()` verifies all 279 files in `frozen_evidence_digests.json` against baseline commit `08ef9e9e2711e1174ed6796b3e3e60bf0ad7ca58`.
