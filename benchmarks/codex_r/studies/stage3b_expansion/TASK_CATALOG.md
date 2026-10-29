# Stage 3B Task Catalogue (`stage3b-catalog-v1.0`)

## 1. Summary Table of All 30 Stage 3B Tasks

| Task | Title | Category | Image | Packages | Checks | Controls | Classification | Usefulness | Dimensions (`R/V/D/RC/CG/SR/DB/API`) | Cluster | Shared With |
| :--- | :--- | :--- | :---: | :--- | :---: | :---: | :--- | :---: | :---: | :--- | :--- |
| `XA01` | Brown-Forsythe screening, then classical or Welch one-way ANOVA with matching follow-ups | `anova_statistical_inference` | `base` | `stats` | 13 | 8 | `control` | `low` | `2/0/1/2/2/3/0/1` | `anova-independent-groups` | — |
| `XA02` | Balanced two-way factorial ANOVA with interaction-aware simple-effects reporting | `anova_statistical_inference` | `base` | `stats` | 13 | 8 | `control` | `none` | `2/0/1/2/2/3/0/0` | `anova-factorial` | — |
| `XA03` | Equal-weight marginal (Type III) tests in an unbalanced two-factor design | `anova_statistical_inference` | `base` | `stats` | 13 | 9 | `control` | `none` | `2/0/1/3/2/3/1/1` | `anova-sums-of-squares` | — |
| `XA04` | One-factor repeated-measures ANOVA with a Greenhouse-Geisser sphericity rule | `anova_statistical_inference` | `base` | `stats` | 13 | 9 | `control` | `low` | `3/0/1/3/2/3/0/1` | `anova-dependent-data` | — |
| `XA05` | ANCOVA with a slope-homogeneity decision rule and covariate-adjusted means | `anova_statistical_inference` | `base` | `stats` | 12 | 8 | `control` | `none` | `2/0/1/3/2/3/0/0` | `anova-covariate-adjustment` | — |
| `XA06` | Treatment-by-time interaction with missing visits: random-intercept model and ML likelihood-ratio test | `anova_statistical_inference` | `base` | `stats`, `nlme` | 13 | 8 | `target_candidate` | `plausible` | `3/0/2/3/2/3/0/2` | `anova-dependent-data` | `XA04` |
| `XG01` | Daily mean time series on a complete calendar with a broken line at gaps | `ggplot2_visualization` | `base` | `ggplot2`, `stats` | 11 | 9 | `control` | `low` | `2/1/1/2/2/0/1/1` | `ggplot2-missing-data` | `XG02` |
| `XG02` | Group-mean bars with correct NA handling, level order and no empty axis slot | `ggplot2_visualization` | `base` | `ggplot2`, `stats` | 11 | 9 | `control` | `low` | `2/1/1/2/1/0/1/1` | `ggplot2-missing-data` | `XG01` |
| `XG03` | Within-group proportion heatmap with complete grid and exact percent labels | `ggplot2_visualization` | `base` | `ggplot2`, `stats` | 12 | 9 | `control` | `none` | `2/0/1/2/2/1/0/0` | `ggplot2-aggregation` | — |
| `XG04` | Zoom with the coordinate system so the regression line still uses all observations | `ggplot2_visualization` | `base` | `ggplot2`, `stats` | 11 | 9 | `exploratory` | `low` | `2/1/2/2/1/1/1/1` | `ggplot2-scales-and-coords` | — |
| `XG05` | Per-participant trajectories with a mean trajectory: grouping, ordering and missing scores | `ggplot2_visualization` | `base` | `ggplot2`, `stats` | 11 | 9 | `control` | `none` | `2/0/1/2/2/0/1/0` | `ggplot2-grouping` | — |
| `XM01` | DESeq2 differential expression with a batch covariate, contrast direction, alpha-matched filtering and name-based sample alignment | `multi_step_workflow` | `bioc` | `DESeq2`, `SummarizedExperiment`, `BiocVersion` | 10 | 10 | `target_candidate` | `high` | `3/2/3/3/3/3/2/3` | `bioconductor-workflows` | `XM04` |
| `XM02` | Multi-site treatment investigation with column-selective missingness screening, post-treatment exclusion, interaction gate and site-specific vs pooled contrasts | `multi_step_workflow` | `base` | `stats` | 9 | 7 | `control` | `low` | `2/0/1/3/3/3/1/0` | `multi-step-statistical-investigation` | — |
| `XM03` | Shiny moduleServer workflow with session-scoped bindCache/bindEvent pipeline, reactiveVal audit counters and headless testServer replay | `multi_step_workflow` | `base` | `shiny`, `cachem` | 8 | 7 | `target_candidate` | `high` | `3/2/3/2/3/1/2/3` | `shiny-reactive-workflows` | — |
| `XM04` | Transcript-to-gene SummarizedExperiment workflow with sequence MD5 provenance verification, abundance-weighted effective length and sample metadata alignment | `multi_step_workflow` | `bioc` | `SummarizedExperiment`, `BiocVersion`, `digest` | 9 | 7 | `target_candidate` | `high` | `3/1/3/3/3/2/2/3` | `bioconductor-workflows` | `XM01` |
| `XP01` | Transitive hard-dependency closure of an installed package from its own metadata | `package_discovery` | `base` | `tools`, `utils` | 8 | 9 | `control` | `low` | `2/1/1/2/2/0/1/1` | `installed-package-metadata` | `XP02`, `XP03`, `XP04`, `XP05` |
| `XP02` | Direct reverse dependencies among installed packages (whole-name matching) | `package_discovery` | `base` | `tools`, `utils` | 10 | 9 | `control` | `low` | `2/1/1/2/2/0/1/1` | `installed-package-metadata` | `XP01`, `XP03`, `XP04`, `XP05` |
| `XP03` | Minimum R version required by a package and everything it needs (numeric version comparison) | `package_discovery` | `base` | `tools`, `utils` | 8 | 9 | `exploratory` | `low` | `2/2/1/3/2/0/1/1` | `installed-package-metadata` | `XP01`, `XP02`, `XP04`, `XP05` |
| `XP04` | Base, CRAN or Bioconductor? Repository identity of installed packages, including RSPM snapshots | `package_discovery` | `bioc` | `utils`, `Biobase`, `DESeq2`, `BiocVersion` | 11 | 10 | `target_candidate` | `plausible` | `2/2/2/2/1/0/1/2` | `installed-package-metadata` | `XP01`, `XP02`, `XP03`, `XP05` |
| `XP05` | Check version requirements against the installed library with numeric version semantics | `package_discovery` | `base` | `utils` | 9 | 8 | `exploratory` | `low` | `2/2/1/2/2/0/1/1` | `installed-package-metadata` | `XP01`, `XP02`, `XP03`, `XP04` |
| `XR01` | Migrate a legacy helper off dplyr's defunct underscore verbs (string-based column selection) | `code_repair_migration` | `base` | `dplyr` | 11 | 10 | `target_candidate` | `plausible` | `2/3/2/2/2/0/3/2` | `dplyr-se-migration` | — |
| `XR02` | Repair a paired t-test written with the formula interface (paired = TRUE is an error since R 4.4) | `code_repair_migration` | `base` | `stats` | 10 | 10 | `exploratory` | `low` | `3/3/1/2/1/3/2/0` | `base-r-api-change` | — |
| `XR03` | Repair a legacy moving average: short and empty inputs, missing values and attributes | `code_repair_migration` | `base` | `stats` | 12 | 10 | `control` | `none` | `2/0/0/2/1/1/3/0` | `base-r-numeric-repair` | — |
| `XR04` | Repair a long-to-wide reshape that errors on repeated measurements (spread() duplicates) | `code_repair_migration` | `base` | `tidyr` | 10 | 10 | `target_candidate` | `plausible` | `2/2/2/2/2/0/2/2` | `tidyr-reshaping` | — |
| `XR05` | Migrate a parameter-grid evaluator off deprecated purrr cross() and invoke_map() | `code_repair_migration` | `base` | `purrr`, `tidyr` | 10 | 10 | `target_candidate` | `plausible` | `3/3/2/2/2/0/2/2` | `purrr-deprecations` | — |
| `XV01` | Multiple quantiles per group: summarise() no longer returns several rows in a current dplyr | `version_sensitive_api` | `base` | `dplyr`, `stats` | 10 | 9 | `target_candidate` | `plausible` | `2/3/2/1/1/1/1/2` | `dplyr-multirow-summaries` | — |
| `XV02` | Price in force on the order date: rolling join without future leakage or many-to-many notices | `version_sensitive_api` | `base` | `dplyr` | 10 | 10 | `target_candidate` | `plausible` | `3/2/2/2/2/0/1/2` | `as-of-joins` | — |
| `XV03` | Classifying objects in R 4.x: matrix class vectors, tibbles and classed atomic vectors | `version_sensitive_api` | `base` | `tibble` | 11 | 10 | `exploratory` | `low` | `3/2/1/2/1/0/2/0` | `base-r-object-semantics` | — |
| `XV04` | Density histograms with a legend inside: deprecated ggplot2 spellings fail under the pinned version | `version_sensitive_api` | `base` | `ggplot2` | 12 | 10 | `target_candidate` | `plausible` | `2/3/2/1/2/1/1/2` | `ggplot2-deprecations` | — |
| `XV05` | Parsing CSV held in a string: literal data needs I() in readr 2.2, and type guessing loses identifiers | `version_sensitive_api` | `base` | `readr`, `utils` | 12 | 9 | `target_candidate` | `plausible` | `2/3/2/2/2/0/1/2` | `readr-ingestion` | — |

Dimension abbreviations: `R` = `r_knowledge_depth`, `V` = `version_sensitivity`, `D` = `documentation_dependence`, `RC` = `reasoning_complexity`, `CG` = `code_generation_complexity`, `SR` = `statistical_reasoning`, `DB` = `debugging_difficulty`, `API` = `package_api_verification_need`.

---

## 2. Per-Task Catalogue Profiles and Content Digests

### `XA01` — Brown-Forsythe screening, then classical or Welch one-way ANOVA with matching follow-ups
- **Category**: `anova_statistical_inference` (`base` image)
- **Packages**: `stats`
- **Source Registry Specs**: `ANOVA-A03`, `ANOVA-A01`, `ANOVA-A02`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: The decision rule and every formula are given in the prompt; the work is implementation of base-R statistics. MCP package documentation does not change the answer.
- **Independence**: cluster `anova-independent-groups` (`shared_with = none`)
- **Fixtures**: `fixture/experiment.csv`
- **Scorer Checks (13) & Controls (8)**: `reference`, `alternate_closed_form`, `wrong_levene_mean_centered`, `wrong_always_classical`, `wrong_welch_with_pooled_tukey`, `edge_accepts_two_groups`, `malformed_returns_vector`, `malformed_incomplete_stub`
- **Task SHA-256**: `da0d0d8154f6237dd45df3169be5072376c74b6188abca507bfaabe9634cbcd5`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XA02` — Balanced two-way factorial ANOVA with interaction-aware simple-effects reporting
- **Category**: `anova_statistical_inference` (`base` image)
- **Packages**: `stats`
- **Source Registry Specs**: `ANOVA-A04`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = none`)
- **MCP Rationale**: Pure factorial-design reasoning with an explicit reporting rule; nothing depends on a package, version or documentation fact beyond base R.
- **Independence**: cluster `anova-factorial` (`shared_with = none`)
- **Fixtures**: `fixture/experiment.csv`
- **Scorer Checks (13) & Controls (8)**: `reference`, `alternate_closed_form`, `wrong_per_site_anova`, `wrong_ignores_interaction`, `wrong_always_reports_simple_effects`, `edge_accepts_unbalanced_data`, `malformed_missing_elements`, `malformed_incomplete_stub`
- **Task SHA-256**: `cc06b96406df947fd4f8248d53e920b0b7e26d6725bd993a93943832102fe80f`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XA03` — Equal-weight marginal (Type III) tests in an unbalanced two-factor design
- **Category**: `anova_statistical_inference` (`base` image)
- **Packages**: `stats`
- **Source Registry Specs**: `ANOVA-A05`, `ANOVA-A12`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = none`)
- **MCP Rationale**: The task is statistical reasoning about hypotheses and contrast coding. The decisive facts (how contr.sum, drop1 scope and sequential SS behave) are in base R documentation that is also installed locally; no package version or ecosystem fact changes the answer.
- **Independence**: cluster `anova-sums-of-squares` (`shared_with = none`)
- **Fixtures**: `fixture/experiment.csv`
- **Scorer Checks (13) & Controls (9)**: `reference`, `alternate_model_comparison`, `alternate_cell_means`, `wrong_type1_sequential`, `wrong_type2`, `wrong_treatment_contrasts`, `edge_ignores_missing_scores`, `malformed_incomplete_missing_function`, `malformed_returns_list`
- **Task SHA-256**: `9d040538c7f554653bcd04699b82622ce3d5cedfa48678b7da95366db600bf61`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XA04` — One-factor repeated-measures ANOVA with a Greenhouse-Geisser sphericity rule
- **Category**: `anova_statistical_inference` (`base` image)
- **Packages**: `stats`
- **Source Registry Specs**: `ANOVA-A06`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: The statistics are specified in the prompt; the only ecosystem fact is that the usual convenience packages (ez, afex, rstatix) are not installed, which the supplied lockfile shows directly.
- **Independence**: cluster `anova-dependent-data` (`shared_with = none`)
- **Fixtures**: `fixture/measurements.csv`
- **Scorer Checks (13) & Controls (9)**: `reference`, `alternate_matrix_formulas`, `wrong_independent_oneway`, `wrong_no_df_adjustment`, `wrong_huynh_feldt`, `wrong_always_corrects`, `edge_keeps_incomplete_subjects`, `malformed_wrong_names`, `malformed_incomplete_stub`
- **Task SHA-256**: `d4cc2480e94aa38609f5155c958a3abc6ccbb55d10d68d1fa040936b96f00e54`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XA05` — ANCOVA with a slope-homogeneity decision rule and covariate-adjusted means
- **Category**: `anova_statistical_inference` (`base` image)
- **Packages**: `stats`
- **Source Registry Specs**: `ANOVA-A08`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = none`)
- **MCP Rationale**: Model specification and covariate reasoning in base R; no package or version fact is needed.
- **Independence**: cluster `anova-covariate-adjustment` (`shared_with = none`)
- **Fixtures**: `fixture/trial.csv`
- **Scorer Checks (12) & Controls (8)**: `reference`, `alternate_matrix_algebra`, `wrong_sequential_unadjusted`, `wrong_skips_slope_test`, `wrong_means_at_zero_baseline`, `edge_accepts_tiny_groups`, `malformed_flat_output`, `malformed_incomplete_stub`
- **Task SHA-256**: `e18b4938169900a44acc2b86b8a3643d3545ff39d6b92db3993281dd275300ef`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XA06` — Treatment-by-time interaction with missing visits: random-intercept model and ML likelihood-ratio test
- **Category**: `anova_statistical_inference` (`base` image)
- **Packages**: `stats`, `nlme`
- **Source Registry Specs**: `ANOVA-A13`, `ANOVA-A07`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: The standard answer in the wild uses lme4::lmer, which is not installed. Choosing nlme::lme and its ML/REML and VarCorr conventions is an API-availability and documentation question that package metadata and function documentation can inform (check_package_version, get_function_docs). It is not decisive: the lockfile and library(nlme) are available locally.
- **Independence**: cluster `anova-dependent-data` (`shared_with = `XA04``)
- **Fixtures**: `fixture/visits.csv`
- **Scorer Checks (13) & Controls (8)**: `reference`, `alternate_gls_compound_symmetry`, `wrong_complete_case_anova`, `wrong_reml_comparison`, `wrong_ignores_clustering`, `edge_does_not_check_arm_membership`, `malformed_missing_lrt`, `malformed_incomplete_stub`
- **Task SHA-256**: `e13155af3a2c12630561c39ed70177085a6a795f30c41a46ed8e6f2ffc87488a`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XG01` — Daily mean time series on a complete calendar with a broken line at gaps
- **Category**: `ggplot2_visualization` (`base` image)
- **Packages**: `ggplot2`, `stats`
- **Source Registry Specs**: `GGP-T01`, `GGP-B03`, `GGP-E04`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: The failure modes concern how ggplot2 treats NA in lines and how to build a complete calendar; they are semantic traps solvable from basic ggplot2 knowledge and local help. Nothing depends on a version-specific fact.
- **Independence**: cluster `ggplot2-missing-data` (`shared_with = `XG02``)
- **Fixtures**: `fixture/readings.csv`
- **Scorer Checks (11) & Controls (9)**: `reference`, `alternate_dplyr_complete`, `wrong_observed_days_only`, `wrong_gaps_filled_with_zero`, `wrong_na_rm_bridges_gaps`, `wrong_median_instead_of_mean`, `edge_default_axis_titles`, `malformed_returns_data_frame`, `malformed_incomplete_stub`
- **Task SHA-256**: `5b5b23feed933ba0d5e561748c3a2d1ce6d6c35f031e73846aa3fa0609b7af8e`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XG02` — Group-mean bars with correct NA handling, level order and no empty axis slot
- **Category**: `ggplot2_visualization` (`base` image)
- **Packages**: `ggplot2`, `stats`
- **Source Registry Specs**: `GGP-E05`, `GGP-E06`, `GGP-X03`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: Stat/geom semantics and scale training are core ggplot2 knowledge available from local help; the answer does not depend on a version or an external fact.
- **Independence**: cluster `ggplot2-missing-data` (`shared_with = `XG01``)
- **Fixtures**: `fixture/outcomes.csv`
- **Scorer Checks (11) & Controls (9)**: `reference`, `alternate_stat_summary_after_filter`, `wrong_count_bars`, `wrong_mean_without_na_rm`, `wrong_alphabetical_order_for_factors`, `wrong_keeps_empty_group_slot`, `edge_default_axis_titles`, `malformed_returns_means_table`, `malformed_incomplete_stub`
- **Task SHA-256**: `7110f95745f0482a602b14435486755f528f2ffb1f258817d4e10b9a9a5487a1`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XG03` — Within-group proportion heatmap with complete grid and exact percent labels
- **Category**: `ggplot2_visualization` (`base` image)
- **Packages**: `ggplot2`, `stats`
- **Source Registry Specs**: `GGP-T04`, `GGP-B02`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = none`)
- **MCP Rationale**: Normalisation margin and a complete grid are data-wrangling semantics; no package, version or documentation fact is decisive.
- **Independence**: cluster `ggplot2-aggregation` (`shared_with = none`)
- **Fixtures**: `fixture/respondents.csv`
- **Scorer Checks (12) & Controls (9)**: `reference`, `alternate_dplyr_complete`, `wrong_share_of_region`, `wrong_share_of_all_respondents`, `wrong_drops_empty_combinations`, `wrong_label_without_decimal`, `edge_default_axis_titles`, `malformed_returns_table`, `malformed_incomplete_stub`
- **Task SHA-256**: `457e5d92a0361dad30ada6fac1ffa96f317af7da8153fecf2c1538575a2f2013`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XG04` — Zoom with the coordinate system so the regression line still uses all observations
- **Category**: `ggplot2_visualization` (`base` image)
- **Packages**: `ggplot2`, `stats`
- **Source Registry Specs**: `GGP-E08`, `GGP-P01`
- **Derived MCP Classification**: `exploratory` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: The distinction between scale limits and coord_cartesian() is documented in the ggplot2 help and is the heart of the task, so documentation matters more than for the other plotting tasks; but the help pages are installed locally and the behaviour is long-stable, so MCP offers no unique information.
- **Independence**: cluster `ggplot2-scales-and-coords` (`shared_with = none`)
- **Fixtures**: `fixture/measurements.csv`
- **Scorer Checks (11) & Controls (9)**: `reference`, `alternate_abline_from_lm`, `wrong_scale_limits_drop_points`, `wrong_fit_on_window_subset`, `wrong_default_loess_smoother`, `wrong_zoom_by_filtering_rows`, `edge_no_window_validation`, `malformed_returns_coefficients`, `malformed_incomplete_stub`
- **Task SHA-256**: `cd29e9193a71f1e12642511599db15c6c61d9df9162182eaf0ccc0b10edd9f65`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XG05` — Per-participant trajectories with a mean trajectory: grouping, ordering and missing scores
- **Category**: `ggplot2_visualization` (`base` image)
- **Packages**: `ggplot2`, `stats`
- **Source Registry Specs**: `GGP-E04`, `GGP-E07`, `GGP-N01`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = none`)
- **MCP Rationale**: Grouping and drawing order are core ggplot2 semantics; the answer does not rest on a package fact or version.
- **Independence**: cluster `ggplot2-grouping` (`shared_with = none`)
- **Fixtures**: `fixture/trajectories.csv`
- **Scorer Checks (11) & Controls (9)**: `reference`, `alternate_stat_summary_mean_line`, `wrong_no_group_aesthetic`, `wrong_path_in_row_order`, `wrong_mean_with_missing_as_zero`, `wrong_mean_line_same_width`, `edge_default_axis_titles`, `malformed_returns_means_table`, `malformed_incomplete_stub`
- **Task SHA-256**: `ee186e62f98686ee73dbc9b1c7dd7fa05c2baf85269d5c37cff6e94091808a8d`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XM01` — DESeq2 differential expression with a batch covariate, contrast direction, alpha-matched filtering and name-based sample alignment
- **Category**: `multi_step_workflow` (`bioc` image)
- **Packages**: `DESeq2`, `SummarizedExperiment`, `BiocVersion`
- **Source Registry Specs**: `ECO-BIO03`, `ADDON-B10`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = high`)
- **MCP Rationale**: A Bioconductor-package workflow whose correctness depends on API details of the installed DESeq2 (results() arguments, factor levels, alpha semantics). Package documentation and the Bioconductor release context are where MCP is designed to help. The installed help pages are available locally, so the information is recoverable without MCP; the multi-step structure makes it a good test of whether an agent consults documentation unprompted.
- **Independence**: cluster `bioconductor-workflows` (`shared_with = `XM04``)
- **Fixtures**: `fixture/counts.csv`, `fixture/coldata.csv`
- **Scorer Checks (10) & Controls (10)**: `reference`, `alternate_coefficient_name_and_relevel`, `wrong_default_alphabetical_reference`, `wrong_no_batch_covariate`, `wrong_alpha_only_in_the_final_filter`, `wrong_sample_names_overwritten`, `wrong_sorted_by_fold_change`, `edge_no_input_validation`, `malformed_returns_deseq_results`, `malformed_incomplete_stub`
- **Task SHA-256**: `520a4a43b8143f28b0e008291274c350199c217bc0d02323e401ee81bbff0257`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XM02` — Multi-site treatment investigation with column-selective missingness screening, post-treatment exclusion, interaction gate and site-specific vs pooled contrasts
- **Category**: `multi_step_workflow` (`base` image)
- **Packages**: `stats`
- **Source Registry Specs**: `ANOVA-A14`, `ANOVA-A15`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: The workflow relies on base R linear-model projection, contrast extraction and statistical study-design hygiene rather than external package APIs or version-sensitive functions. It serves as a multi-step statistical workflow control for measuring tool-use overhead on complex reasoning tasks.
- **Independence**: cluster `multi-step-statistical-investigation` (`shared_with = none`)
- **Fixtures**: `fixture/study.csv`
- **Scorer Checks (9) & Controls (7)**: `reference`, `alternate_vcov_linear_combinations`, `wrong_na_omit_all_columns`, `wrong_separate_within_site_regressions`, `wrong_always_reports_pooled_effect`, `edge_no_input_validation`, `malformed_returns_lm_object`
- **Task SHA-256**: `3baa35f90c3c33554e0feef3d6e8196a9fd88def369648baf5833bc2ce7e9ef1`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XM03` — Shiny moduleServer workflow with session-scoped bindCache/bindEvent pipeline, reactiveVal audit counters and headless testServer replay
- **Category**: `multi_step_workflow` (`base` image)
- **Packages**: `shiny`, `cachem`
- **Source Registry Specs**: `ECO-SH01`, `ECO-SH03`, `ADDON-B08`, `ADDON-C03`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = high`)
- **MCP Rationale**: Correctness depends on specific Shiny API contracts: bindCache() must precede bindEvent(), cache = 'session' vs default 'app' scoping, reactiveVal() setter syntax, and shiny::testServer() session$setInputs / session$returned semantics. R-Knowledge-MCP exposes both package function docs and reviewed Shiny framework documentation.
- **Independence**: cluster `shiny-reactive-workflows` (`shared_with = none`)
- **Fixtures**: `fixture/cohorts.csv`
- **Scorer Checks (8) & Controls (7)**: `reference`, `alternate_explicit_session_cache_object`, `wrong_app_scoped_cache`, `wrong_incomplete_cache_key`, `wrong_no_bind_event_eager_reactive`, `edge_no_input_validation`, `malformed_missing_replay_function`
- **Task SHA-256**: `13c99b1940894e82c3571e2df43064d66c22b0f26fbd8f60acc51c5338516dcb`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XM04` — Transcript-to-gene SummarizedExperiment workflow with sequence MD5 provenance verification, abundance-weighted effective length and sample metadata alignment
- **Category**: `multi_step_workflow` (`bioc` image)
- **Packages**: `SummarizedExperiment`, `BiocVersion`, `digest`
- **Source Registry Specs**: `ECO-BIO04`, `ADDON-C10`, `ADDON-B10`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = high`)
- **MCP Rationale**: Constructing a valid SummarizedExperiment with multiple named assays, aligned rowData/colData S4 DataFrames, metadata(), and digest::digest(serialize = FALSE) requires exact Bioconductor and CRAN API conventions that R-Knowledge-MCP surfaces via get_function_docs and search_r_documentation.
- **Independence**: cluster `bioconductor-workflows` (`shared_with = `XM01``)
- **Fixtures**: `fixture/tx_counts.csv`, `fixture/tx_tpm.csv`, `fixture/tx_efflen.csv`, `fixture/coldata.csv`, `fixture/tx_manifest.csv`
- **Scorer Checks (9) & Controls (7)**: `reference`, `alternate_split_by_gene_loop`, `wrong_unweighted_effective_length`, `wrong_no_zero_tpm_fallback`, `wrong_manifest_md5_uses_full_manifest`, `edge_no_checksum_or_input_validation`, `malformed_returns_plain_list`
- **Task SHA-256**: `ed5739a0820619314e6bbac0085f667d71b174bfe5dfbd41c7da0f5ee28d6b64`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XP01` — Transitive hard-dependency closure of an installed package from its own metadata
- **Category**: `package_discovery` (`base` image)
- **Packages**: `tools`, `utils`
- **Source Registry Specs**: `ECO-PK01`, `ECO-PK03`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: The question is closed-world: the scorer evaluates dependency metadata of the pinned installed library, which an MCP package-metadata tool does not see (it describes CRAN/Bioconductor, not this container's library). It therefore tests whether an agent over-uses MCP for a question the local library answers authoritatively; any MCP use is overhead or at best a cross-check.
- **Independence**: cluster `installed-package-metadata` (`shared_with = `XP02`, `XP03`, `XP04`, `XP05``)
- **Fixtures**: `fixture/deps_sample.csv`
- **Scorer Checks (8) & Controls (9)**: `reference`, `alternate_tools_package_dependencies`, `wrong_direct_dependencies_only`, `wrong_base_packages_included`, `wrong_suggests_always_included`, `wrong_locale_sort_and_default_types_ignored`, `edge_no_argument_validation`, `malformed_returns_data_frame`, `malformed_incomplete_stub`
- **Task SHA-256**: `e077c0196cad489b18faa6b00951ad6a3b2fa6c6a13bf6e51158c4f9cf2bdac7`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XP02` — Direct reverse dependencies among installed packages (whole-name matching)
- **Category**: `package_discovery` (`base` image)
- **Packages**: `tools`, `utils`
- **Source Registry Specs**: `ECO-PL02`, `ECO-GP03`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: Closed-world question answered authoritatively by the pinned installed library; MCP describes CRAN/Bioconductor, not this library, so any use is overhead or a cross-check. Included to measure unprompted tool use when the tool is not needed.
- **Independence**: cluster `installed-package-metadata` (`shared_with = `XP01`, `XP03`, `XP04`, `XP05``)
- **Fixtures**: `fixture/imports_sample.csv`
- **Scorer Checks (10) & Controls (9)**: `reference`, `alternate_manual_scan`, `wrong_substring_matching`, `wrong_recursive_dependencies`, `wrong_ignores_linkingto_and_types`, `wrong_only_user_library_searched`, `edge_no_argument_validation`, `malformed_returns_list`, `malformed_incomplete_stub`
- **Task SHA-256**: `26c2d502dff113991ab70ca1273cd389cecef33a3066120104bfb26ad195ef61`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XP03` — Minimum R version required by a package and everything it needs (numeric version comparison)
- **Category**: `package_discovery` (`base` image)
- **Packages**: `tools`, `utils`
- **Source Registry Specs**: `ECO-PK02`, `ECO-PL02`
- **Derived MCP Classification**: `exploratory` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: Version-requirement reasoning over a dependency closure is exactly what a package-metadata service could help with in the open world, but the scorer fixes the evidence to the pinned installed library, so MCP can at most cross-check metadata for packages whose installed and CRAN versions agree. Marked exploratory because the closed-world reduction removes the information advantage.
- **Independence**: cluster `installed-package-metadata` (`shared_with = `XP01`, `XP02`, `XP04`, `XP05``)
- **Fixtures**: `fixture/r_requirements_sample.csv`
- **Scorer Checks (8) & Controls (9)**: `reference`, `alternate_tools_package_dependencies`, `wrong_own_requirement_only`, `wrong_lexical_comparison`, `wrong_base_packages_followed`, `wrong_no_normalisation`, `edge_no_argument_validation`, `malformed_returns_numeric_version`, `malformed_incomplete_stub`
- **Task SHA-256**: `e7be3129e26884472df1fc6bc61bc12bf9bde0f67fb8ad2f2e7b994cdba00727`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XP04` — Base, CRAN or Bioconductor? Repository identity of installed packages, including RSPM snapshots
- **Category**: `package_discovery` (`bioc` image)
- **Packages**: `utils`, `Biobase`, `DESeq2`, `BiocVersion`
- **Source Registry Specs**: `ECO-SRC02`, `ECO-BIO01`, `ADDON-C09`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: Distinguishing CRAN from Bioconductor and mapping a Bioconductor release is the kind of repository-identity reasoning an R package-knowledge service exists for. The scorer, however, fixes the evidence to installed DESCRIPTION metadata, so MCP can only corroborate the repository of a package name; the decisive facts (the RSPM value, the Priority rule) are stated in the prompt. Classified target_candidate by the dimension rule and expected to show modest benefit at most.
- **Independence**: cluster `installed-package-metadata` (`shared_with = `XP01`, `XP02`, `XP03`, `XP05``)
- **Fixtures**: `fixture/origin_sample.csv`
- **Scorer Checks (11) & Controls (10)**: `reference`, `alternate_packagedescription`, `wrong_repository_field_used_as_origin`, `wrong_recommended_treated_as_base`, `wrong_rspm_not_cran`, `wrong_unique_rows_and_sorted`, `wrong_missing_release_text`, `edge_no_argument_validation`, `malformed_returns_named_vector`, `malformed_incomplete_stub`
- **Task SHA-256**: `1eacd571de1999ebfedbe3a81b7980a8e2d605cad4953bb1f38ad4e2638afb18`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XP05` — Check version requirements against the installed library with numeric version semantics
- **Category**: `package_discovery` (`base` image)
- **Packages**: `utils`
- **Source Registry Specs**: `ECO-PK02`, `ADDON-C06`
- **Derived MCP Classification**: `exploratory` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: Version-requirement checking is central to package compatibility reasoning, but here the semantics are fully specified in the prompt and the installed versions are local metadata, so MCP adds little; an agent that calls MCP for installed versions would be using the wrong evidence source (CRAN current versus the installed library). Exploratory to observe unprompted use and any confusion of the two sources.
- **Independence**: cluster `installed-package-metadata` (`shared_with = `XP01`, `XP02`, `XP03`, `XP04``)
- **Fixtures**: `fixture/requirements_sample.csv`
- **Scorer Checks (9) & Controls (8)**: `reference`, `alternate_compareversion`, `wrong_textual_comparison`, `wrong_hyphen_not_a_separator`, `wrong_not_installed_is_an_error`, `edge_no_input_validation`, `malformed_returns_logical`, `malformed_incomplete_stub`
- **Task SHA-256**: `ea2d662810c8b133cbf1be2fd8f1efbcb940a6abcecec3cda9a030b5f368ab4a`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XR01` — Migrate a legacy helper off dplyr's defunct underscore verbs (string-based column selection)
- **Category**: `code_repair_migration` (`base` image)
- **Packages**: `dplyr`
- **Source Registry Specs**: `HARD-H01`, `ADDON-B01`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: The migration path from removed standard-evaluation verbs to the .data pronoun is a version-specific fact; function documentation for the installed dplyr and its programming vignette state it. The defunct-function error message itself names the replacements, and base R is a complete fallback.
- **Independence**: cluster `dplyr-se-migration` (`shared_with = none`)
- **Fixtures**: `fixture/scores.csv`
- **Scorer Checks (11) & Controls (10)**: `reference`, `alternate_base_r`, `wrong_underscore_verbs_unchanged`, `wrong_top_n_keeps_ties`, `wrong_ascending_order`, `wrong_keeps_missing_groups`, `wrong_data_masking_name_clash`, `edge_no_n_validation`, `malformed_returns_vector`, `malformed_incomplete_stub`
- **Task SHA-256**: `0ffeec29e2d169452609211f1b3ab52f357f495f4170d58edf93c3c080a0016d`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XR02` — Repair a paired t-test written with the formula interface (paired = TRUE is an error since R 4.4)
- **Category**: `code_repair_migration` (`base` image)
- **Packages**: `stats`
- **Source Registry Specs**: `ADDON-C04`
- **Derived MCP Classification**: `exploratory` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: The failure is a base-R behaviour change documented in R's NEWS and in ?t.test; the error message states the problem. The statistical content (pairwise deletion, sign convention, df) matters more than any package fact, so MCP offers little beyond local help pages.
- **Independence**: cluster `base-r-api-change` (`shared_with = none`)
- **Fixtures**: `fixture/clinic.csv`
- **Scorer Checks (10) & Controls (10)**: `reference`, `alternate_manual_formulas`, `wrong_legacy_formula_paired`, `wrong_unpaired_welch`, `wrong_sign_before_minus_after`, `wrong_independent_na_removal`, `wrong_ninety_percent_interval`, `edge_names_left_on_values`, `malformed_returns_htest`, `malformed_incomplete_stub`
- **Task SHA-256**: `a058d21de56622b23f3e0e30973aae2d9ecde910ef558e05417e5ebc8894a475`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XR03` — Repair a legacy moving average: short and empty inputs, missing values and attributes
- **Category**: `code_repair_migration` (`base` image)
- **Packages**: `stats`
- **Source Registry Specs**: `ADDON-B05`, `HARD-H10`
- **Derived MCP Classification**: `control` (`expected_mcp_usefulness = none`)
- **MCP Rationale**: A pure base-R logic repair; no package, version or documentation fact is needed. It controls for general coding ability when MCP access is available.
- **Independence**: cluster `base-r-numeric-repair` (`shared_with = none`)
- **Fixtures**: `fixture/series.csv`
- **Scorer Checks (12) & Controls (10)**: `reference`, `alternate_stats_filter`, `wrong_legacy_code_unchanged`, `wrong_leading_values_dropped`, `wrong_skips_missing_values`, `wrong_cumsum_propagates_missing`, `wrong_centered_window`, `edge_keeps_names`, `malformed_returns_scalar`, `malformed_incomplete_stub`
- **Task SHA-256**: `220a536640af3a5c9a3228b4366a8e48449bb6751bb3bd991f782dd704700120`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XR04` — Repair a long-to-wide reshape that errors on repeated measurements (spread() duplicates)
- **Category**: `code_repair_migration` (`base` image)
- **Packages**: `tidyr`
- **Source Registry Specs**: `HARD-H03`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: The superseded spread()/gather() verbs and the pivot_wider(values_fn =) replacement are tidyr-version-specific; documentation for the installed tidyr states the duplicate-handling behaviour. Base R remains a complete fallback, and the runtime error and warning both name values_fn.
- **Independence**: cluster `tidyr-reshaping` (`shared_with = none`)
- **Fixtures**: `fixture/long.csv`
- **Scorer Checks (10) & Controls (10)**: `reference`, `alternate_tidyr_pivot_wider`, `wrong_legacy_spread_unchanged`, `wrong_pivot_wider_list_columns`, `wrong_sum_instead_of_mean`, `wrong_missing_values_poison_the_mean`, `wrong_columns_in_order_of_appearance`, `edge_drops_ids_with_only_missing_values`, `malformed_returns_matrix`, `malformed_incomplete_stub`
- **Task SHA-256**: `6ff99c6e47fe37946174c2a4f4f8ff34d1788d99b26f28b8ef6231b1fb0045ba`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XR05` — Migrate a parameter-grid evaluator off deprecated purrr cross() and invoke_map()
- **Category**: `code_repair_migration` (`base` image)
- **Packages**: `purrr`, `tidyr`
- **Source Registry Specs**: `HARD-H09`, `ADDON-C07`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: Which purrr functions are deprecated, and what replaces them with what semantics, is package-version knowledge that pre-1.0 training data contradicts. The deprecation warnings themselves name the replacements, and base R expand.grid()/do.call() is a complete fallback.
- **Independence**: cluster `purrr-deprecations` (`shared_with = none`)
- **Fixtures**: `fixture/grid.csv`
- **Scorer Checks (10) & Controls (10)**: `reference`, `alternate_purrr_pmap`, `wrong_legacy_purrr_unchanged`, `wrong_last_parameter_varies_fastest`, `wrong_factors_from_expand_grid`, `wrong_positional_arguments`, `wrong_no_input_validation`, `edge_returns_tibble`, `malformed_returns_vector`, `malformed_incomplete_stub`
- **Task SHA-256**: `46e1bf1eee1fab56ccb7c71306d2b11a51a90139f8b12f8b488d8d0f6b0093f1`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XV01` — Multiple quantiles per group: summarise() no longer returns several rows in a current dplyr
- **Category**: `version_sensitive_api` (`base` image)
- **Packages**: `dplyr`, `stats`
- **Source Registry Specs**: `HARD-H01`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: The failing idiom is exactly what older material teaches, and the replacement (reframe) and its argument conventions are version-specific facts about the installed dplyr. MCP could supply the current function signature and guidance, but the error message in the pinned dplyr itself names reframe(), and base R is an equally valid route, so the information is recoverable without MCP.
- **Independence**: cluster `dplyr-multirow-summaries` (`shared_with = none`)
- **Fixtures**: `fixture/sales.csv`
- **Scorer Checks (10) & Controls (9)**: `reference`, `alternate_base_r_split`, `wrong_summarise_multirow`, `wrong_quantile_type_6`, `wrong_ignores_probs_argument`, `wrong_keeps_empty_group_as_na`, `edge_no_probs_validation`, `malformed_returns_list`, `malformed_incomplete_stub`
- **Task SHA-256**: `0c39c48acab87a714e438918beb466a28fbd26dd9e4b6aa91ba11691f88333b9`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XV02` — Price in force on the order date: rolling join without future leakage or many-to-many notices
- **Category**: `version_sensitive_api` (`base` image)
- **Packages**: `dplyr`
- **Source Registry Specs**: `HARD-H04`, `ADDON-B04`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: join_by() with closest() and the relationship checks are version-gated dplyr features that older training material lacks; MCP could confirm the signature and the first version that offers it. A base-R solution is a complete fallback, so MCP is helpful but not necessary.
- **Independence**: cluster `as-of-joins` (`shared_with = none`)
- **Fixtures**: `fixture/orders.csv`, `fixture/prices.csv`
- **Scorer Checks (10) & Controls (10)**: `reference`, `alternate_base_r_findinterval`, `wrong_filter_after_join_warns_and_duplicates`, `wrong_strict_inequality`, `wrong_uses_next_price`, `wrong_drops_unmatched_orders`, `wrong_output_sorted_by_date`, `edge_extra_helper_column`, `malformed_returns_vector`, `malformed_incomplete_stub`
- **Task SHA-256**: `7ff464b59f12bf9545d16b256f00ceba9c552fba8a0f45b29f0c5b54c28e6c04`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XV03` — Classifying objects in R 4.x: matrix class vectors, tibbles and classed atomic vectors
- **Category**: `version_sensitive_api` (`base` image)
- **Packages**: `tibble`
- **Source Registry Specs**: `ECO-V02`
- **Derived MCP Classification**: `exploratory` (`expected_mcp_usefulness = low`)
- **MCP Rationale**: The decisive facts concern base R semantics that changed in R 4.0/4.2; they are discoverable by running code and are in the installed base documentation. No package metadata is involved, so MCP is of limited use, but version-specific NEWS knowledge could matter.
- **Independence**: cluster `base-r-object-semantics` (`shared_with = none`)
- **Fixtures**: `fixture/examples.csv`
- **Scorer Checks (11) & Controls (10)**: `reference`, `alternate_inherits_based`, `wrong_class_equals_matrix`, `wrong_array_before_matrix`, `wrong_tibble_as_data_frame`, `wrong_is_vector_for_atomic`, `wrong_data_frame_as_list`, `edge_errors_on_environments_and_formulas`, `malformed_returns_class_vector`, `malformed_incomplete_stub`
- **Task SHA-256**: `849dd91d06d856bf4d97ec6613bb6ae546f31bb11c7683ac6186f1fd6207f9eb`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XV04` — Density histograms with a legend inside: deprecated ggplot2 spellings fail under the pinned version
- **Category**: `version_sensitive_api` (`base` image)
- **Packages**: `ggplot2`
- **Source Registry Specs**: `ECO-GP01`, `ADDON-C02`, `GGP-E08`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: Three separate API changes are version-gated and the correct modern spelling requires knowing the installed ggplot2's interface (legend.position.inside, after_stat, linewidth). Documentation retrieval is directly useful; the deprecated forms still run, so the failure is only visible through warnings, which an agent that executes code may or may not read.
- **Independence**: cluster `ggplot2-deprecations` (`shared_with = none`)
- **Fixtures**: `fixture/measurements.csv`
- **Scorer Checks (12) & Controls (10)**: `reference`, `alternate_explicit_density_mapping`, `wrong_dot_dot_notation`, `alternate_numeric_legend_position`, `wrong_size_for_line_width`, `wrong_counts_and_stacked`, `wrong_legend_outside_on_the_right`, `edge_bins_not_validated`, `malformed_returns_density_list`, `malformed_incomplete_stub`
- **Task SHA-256**: `fb0db4713295cb7e894fe75c6f5527268857ddbd69dcf3002190788a98917738`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`

### `XV05` — Parsing CSV held in a string: literal data needs I() in readr 2.2, and type guessing loses identifiers
- **Category**: `version_sensitive_api` (`base` image)
- **Packages**: `readr`, `utils`
- **Source Registry Specs**: `ADDON-C04`, `HARD-H03`
- **Derived MCP Classification**: `target_candidate` (`expected_mcp_usefulness = plausible`)
- **MCP Rationale**: The literal-data change is a very recent readr release note that most training material predates; knowing the installed readr's behaviour requires version-specific documentation. The warning text itself shows the fix, and base R read.csv(text=) avoids the issue altogether.
- **Independence**: cluster `readr-ingestion` (`shared_with = none`)
- **Fixtures**: `fixture/events.csv`
- **Scorer Checks (12) & Controls (9)**: `reference`, `alternate_base_r_read_csv`, `wrong_literal_data_without_I`, `wrong_guessed_user_type`, `wrong_problem_count_includes_missing`, `wrong_local_timezone`, `edge_header_only_drops_types`, `malformed_returns_data_frame_only`, `malformed_incomplete_stub`
- **Task SHA-256**: `ed8cc52833720f3b7197cb11cd6d280017d4cf0507a6ff5e02d3197a1d5fe386`
- **Scorer SHA-256**: `e59baca13f76581b542e510b4a5e4ab9da60c65900fe00bee8954c46a046bcd7`
- **Pool Status**: `pool = stage3b-candidate-pool-v1`, `stratum = null`, `calibration_eligible = true`, `confirmatory_eligible = false`
