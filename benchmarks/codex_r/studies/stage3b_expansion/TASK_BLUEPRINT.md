# Stage 3B Task Blueprint and Design Specification

## 1. Design Principles

Stage 3B tasks are engineered to eliminate the failure modes identified in the Stage 0–2 audits (specifically **BEN-002** oracle coupling and unprompted schema keys in `D01`–`D03`/`E01`/`E04`/`E05`, and **ceiling saturation** in `R01`–`R12`).

Every Stage 3B task obeys six architectural invariants:

1. **Single Behavioral Deliverable (`solution.R`)**:
   - The candidate writes a single UTF-8 R script `solution.R` defining one or more named functions specified in `TASK.md`.
   - Unlike JSON-schema tasks where a missing key causes an all-or-nothing schema failure, `solution.R` functions are invoked directly by the verifier on multiple public and withheld inputs.
2. **Strict Public/Private Separation**:
   - **Public workspace (`suite.prepare`)**: Exports only `TASK.md` (from `tasks/<ID>/prompt.md`), `renv.lock`, and declared fixture files under `data/`.
   - **Private repository files**: `tasks/<ID>/task.json` (dimensions, MCP relevance, source specs), `verifier/<ID>.R` (hidden checks and withheld datasets), and `verifier/controls/<ID>.R` (reference, alternate, and negative controls) are never mounted into the candidate container or MCP server.
3. **Explicit Output Contracts in `TASK.md`**:
   - Every required return type, list element name, data.frame column name, column type, sorting rule, tie-breaking rule, and error condition is stated explicitly in `prompt.md`.
   - Hidden checks never test undocumented field names or unstated conventions.
4. **Independent Load-Time Oracles**:
   - Every `verifier/<ID>.R` computes expected values using an independent mathematical or algorithmic formulation and verifies agreement at load time via `stopifnot(...)` before registering checks.
5. **Closed-World Determinism**:
   - Package discovery (`XP01`–`XP05`) and workflow (`XM01`–`XM04`) tasks operate strictly over the local library (`lib.loc`) or supplied fixture files in the pinned container image (`R 4.5.2`, `Bioconductor 3.22`), never live CRAN/Bioconductor metadata.
6. **Pre-Data Dimension Rating and Derived Classification**:
   - Each task is rated on the five Stage 2 ordinal dimensions (`0` to `3`) from the prompt and target API surface alone.
   - `build.derived_classification(task)` deterministically computes whether the task is `target_candidate`, `control`, or `exploratory`.

---

## 2. Task Directory and File Layout

```text
benchmarks/codex_r/studies/stage3b_expansion/
├── __init__.py
├── build.py                  # Deterministic generator/checker for manifest.json & catalog.json
├── suite.py                  # Runner interface: prepare, seal_artifacts, docker_command, score
├── selftest.py               # Offline real-R container validation gate
├── manifest.json             # Runner manifest (30 tasks, environment pins, protocol limits)
├── catalog.json              # Research catalogue (hashes, derived classifications, pool status)
├── validation_report.json    # Complete selftest evidence (30 tasks, 323 checks, 0 API calls)
├── tools/
│   ├── make_fixtures.py      # Reproducible container-backed fixture generator
│   └── fixtures/             # Per-task deterministic R scripts generating tasks/<ID>/fixture/*
├── tasks/
│   └── <ID>/
│       ├── prompt.md         # Public task specification (exported as TASK.md)
│       ├── task.json         # Authoring metadata, Stage 2 dimensions, source_specs, risks
│       └── fixture/          # Deterministic CSV/RDS/text fixtures (exported under data/)
└── verifier/
    ├── run.R                 # Container entrypoint delegating to hard/verifier/harness.R
    ├── lib.R                 # Shared assertion and callr helper library
    ├── <ID>.R                # Task-specific hidden checks and independent load-time oracle
    └── controls/
        └── <ID>.R            # Reference, alternate_*, wrong_*, edge_*, malformed_* controls
```

---

## 3. Six Task Families

### Family 1: `XA01`–`XA06` — ANOVA and Statistical Inference (`anova_statistical_inference`)
- **Focus**: Classical vs Welch one-way ANOVA with Brown-Forsythe screening (`XA01`), two-way factorial interaction vs main-effects routing (`XA02`), unbalanced Type III sums of squares via orthogonal polynomial/helmert contrasts (`XA03`), repeated-measures Greenhouse-Geisser sphericity correction (`XA04`), ANCOVA homogeneity-of-slopes and adjusted marginal means (`XA05`), and `emmeans` pairwise contrasts with custom `infer` / `adjust` contracts (`XA06`).
- **Role**: Primarily `control` (`XA01`–`XA05` use base `stats` linear algebra/formulas well represented in pretraining) plus one `target_candidate` (`XA06`, which depends on `emmeans` 2.0.1 summary/contrast structure).

### Family 2: `XG01`–`XG05` — `ggplot2` 4.0.2 Visualization Construction (`ggplot2_visualization`)
- **Focus**: Multi-layer summary overlays (`XG01`), faceted scales/labellers (`XG02`), `after_stat` density/histogram transformations (`XG03`), secondary axis affine transformations (`XG04`), and dodge/jitter position alignment (`XG05`).
- **Role**: Four `control` tasks (`XG01`–`XG03`, `XG05`) and one `exploratory` task (`XG04`) inspecting built `ggplot_build()` layer data and grob/panel structures without rendering fragile raster pixels.

### Family 3: `XV01`–`XV05` — Version-Sensitive Tidyverse APIs (`version_sensitive_api`)
- **Focus**: `dplyr` 1.2.0 `.by` + `reframe()` (`XV01`), `dplyr::join_by()` rolling/inequality overlap joins (`XV02`), R 4.x `matrix`/`array` inheritance and `vctrs`/S3 dispatch (`XV03`), `ggplot2` 3.4+/4.0 `linewidth`, `after_stat()`, and `legend.position.inside` (`XV04`), and `readr` 2.2.0 literal input `I()` + `problems()` auditing (`XV05`).
- **Role**: Four `target_candidate` tasks (`XV01`, `XV02`, `XV04`, `XV05`) where post-cutoff/recent API deprecations and argument contracts make MCP documentation lookup directly beneficial, plus one `exploratory` task (`XV03`).

### Family 4: `XR01`–`XR05` — Code Repair and Deprecation Migration (`code_repair_migration`)
- **Focus**: Migrating legacy `tidyr::gather`/`spread` pipelines (`XR01`), fixing broken `data.table` reference semantics (`:=` mutation of caller tables in `XR02`), repairing `lubridate` DST/timezone arithmetic (`XR03`), replacing deprecated `dplyr::across()` / `summarize_at()` patterns (`XR04`), and refactoring `purrr` type-unstable `map_*` / `pmap` pipelines (`XR05`).
- **Role**: Three `target_candidate` tasks (`XR01`, `XR04`, `XR05`), one `control` (`XR03`), and one `exploratory` (`XR02`).

### Family 5: `XP01`–`XP05` — Closed-World Package Discovery & Metadata (`package_discovery`)
- **Focus**: Querying installed package `DESCRIPTION`, `NAMESPACE`, reverse dependencies, S3/S4 exports, and `renv.lock` drift strictly within the container's local library (`lib.loc`) or supplied lockfile fixtures.
- **Role**: Two `control` tasks (`XP01`, `XP02`), two `exploratory` tasks (`XP03`, `XP05`), and one `target_candidate` (`XP04`, combining `tools::package_dependencies` recursive resolution with topological installation ordering).

### Family 6: `XM01`–`XM04` — Multi-Step End-to-End Workflows (`multi_step_workflow`)
- **Focus**:
  - `XM01` (`bioc`, `target_candidate`): `DESeq2` 1.50.2 interaction model fitting, empirical `filterTheta` extraction from `metadata(res)$filterNumRej`, and closed-form normal-prior log2 fold-change shrinkage.
  - `XM02` (`base`, `control`): Stratified clinical-trial randomization balance audit (standardized mean differences) and ANCOVA sensitivity comparison across baseline covariates.
  - `XM03` (`base`, `target_candidate`): `shiny` 1.13.0 + `cachem` 1.1.0 reactive module server (`moduleServer`, `reactiveVal`, `bindCache`) tested deterministically via `shiny::testServer()`.
  - `XM04` (`bioc`, `target_candidate`): Transcript-to-gene `SummarizedExperiment` 1.40.0 aggregation (counts, abundance, abundances-weighted effective lengths), `rowData`/`colData`/`metadata` assembly with `BiocVersion` 3.22.0, and deterministic `digest` 0.6.39 audit hashing.

---

## 4. Deterministic Classification Rule

In `build.py`, a task's classification is computed by `derived_classification(task)`:

```python
def derived_classification(task: dict) -> str:
    entry = {
        "dimensions": task["dimensions"],
        "expected_mcp_usefulness": task["expected_mcp_usefulness"],
    }
    if calibration.target_by_features(entry):
        return "target_candidate"
    d = task["dimensions"]
    low_need = max(d["version_sensitivity"], d["documentation_dependence"]) <= 1 and (
        d["package_api_verification_need"] <= 1
    )
    if task["expected_mcp_usefulness"] in ("none", "low") and low_need:
        return "control"
    return "exploratory"
```

`build.py` asserts `task["mcp_relevance"]["classification"] == derived_classification(task)` on every build, preventing hand-edited classification drift.

