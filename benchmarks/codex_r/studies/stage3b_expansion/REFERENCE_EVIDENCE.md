# Stage 3B Reference Evidence and Runtime Provenance

## 1. Pinned Runtime and Container Images

All Stage 3B fixtures, reference solutions, and hidden-check oracles are grounded in the pinned R 4.5.2 / Bioconductor 3.22 container images and `configs/renv.lock`.

| Role | Image Tag | Immutable Image Digest (`sha256`) | R Version |
| :--- | :--- | :--- | :---: |
| **Base Scorer** | `codex-r-benchmark:pilot` | `sha256:467944b2623c0e7a6f9cbbf24022616911cd834dd2a2200bd39fbe295666eca5` | `4.5.2` |
| **Bioc Scorer** | `codex-r-benchmark:pilot-bioc` | `sha256:1ef3313dc96365e7dc1784369bb217121188a87e037630a8ec648447ddbf0cf4` | `4.5.2` |
| **Base Executor** | `rkmcp-codex-runtime:codex-0.163.0` | Verified identical package set to `codex-r-benchmark:pilot` | `4.5.2` |
| **Bioc Executor** | `rkmcp-codex-runtime:codex-0.163.0-bioc` | Verified identical package set to `codex-r-benchmark:pilot-bioc` | `4.5.2` |

### Package Version Pins Recorded by Scorer Preflight

| Package | Pinned Version | Source | Tasks Using Package |
| :--- | :---: | :--- | :--- |
| `Biobase` | `2.70.0` | Container pin (`build.PINS`) | `XP04` |
| `BiocVersion` | `3.22.0` | Container pin (`build.PINS`) | `XM01`, `XM04`, `XP04` |
| `DESeq2` | `1.50.2` | Container pin (`build.PINS`) | `XM01`, `XP04` |
| `SummarizedExperiment` | `1.40.0` | Container pin (`build.PINS`) | `XM01`, `XM04` |
| `cachem` | `1.1.0` | `configs/renv.lock` | `XM03` |
| `digest` | `0.6.39` | `configs/renv.lock` | `XM04` |
| `dplyr` | `1.2.1` | `configs/renv.lock` | `XR01`, `XV01`, `XV02` |
| `ggplot2` | `4.0.3` | `configs/renv.lock` | `XG01`, `XG02`, `XG03`, `XG04`, `XG05`, `XV04` |
| `nlme` | `3.1.168` | Container pin (`build.PINS`) | `XA06` |
| `purrr` | `1.2.2` | `configs/renv.lock` | `XR05` |
| `readr` | `2.2.0` | `configs/renv.lock` | `XV05` |
| `shiny` | `1.14.0` | `configs/renv.lock` | `XM03` |
| `stats` | `4.5.2` | Container pin (`build.PINS`) | `XA01`, `XA02`, `XA03`, `XA04`, `XA05`, `XA06`, `XG01`, `XG02`, `XG03`, `XG04`, `XG05`, `XM02`, `XR02`, `XR03`, `XV01` |
| `tibble` | `3.3.1` | `configs/renv.lock` | `XV03` |
| `tidyr` | `1.3.2` | `configs/renv.lock` | `XR04`, `XR05` |
| `tools` | `4.5.2` | Container pin (`build.PINS`) | `XP01`, `XP02`, `XP03` |
| `utils` | `4.5.2` | Container pin (`build.PINS`) | `XP01`, `XP02`, `XP03`, `XP04`, `XP05`, `XV05` |

---

## 2. Per-Task Oracle Grounding and Source Registry Traceability

| Task | Source Registry IDs (`expansion/registry-v1.json`) | Primary Target APIs / Functions | Load-Time Oracle Cross-Check in `verifier/<ID>.R` |
| :--- | :--- | :--- | :--- |
| `XA01` | `ANOVA-A03`, `ANOVA-A01`, `ANOVA-A02` | `stats` | Cross-checks `stats::oneway.test`, `stats::aov`, `stats::TukeyHSD`, and pairwise Welch t-tests against closed-form within/between SS and Satterthwaite df. |
| `XA02` | `ANOVA-A04` | `stats` | Cross-checks `stats::lm` Type I/II/III factorial contrast decompositions against cell-means and marginal-means algebra. |
| `XA03` | `ANOVA-A05`, `ANOVA-A12` | `stats` | Cross-checks `car::Anova(..., type = 3)` with `contr.sum` against projection-matrix (`drop1` / full-vs-reduced QR) sums of squares. |
| `XA04` | `ANOVA-A06` | `stats` | Cross-checks Greenhouse-Geisser epsilon from the orthonormalized within-subject covariance matrix eigenvalues against `stats::aov` stratum residuals. |
| `XA05` | `ANOVA-A08` | `stats` | Cross-checks ANCOVA slope-homogeneity F-test (`group:baseline`) and covariate-adjusted marginal means (`emmeans` / OLS design matrix). |
| `XA06` | `ANOVA-A13`, `ANOVA-A07` | `stats`, `nlme` | Cross-checks `emmeans::emmeans` and `emmeans::contrast(..., method = 'pairwise', adjust = 'tukey')` against explicit `ptukey` / `qtukey` studentized range formulas. |
| `XG01` | `GGP-T01`, `GGP-B03`, `GGP-E04` | `ggplot2`, `stats` | Inspects `ggplot2::ggplot_build` layer data, `stat_summary` group means/SEs, and aesthetic mappings. |
| `XG02` | `GGP-E05`, `GGP-E06`, `GGP-X03` | `ggplot2`, `stats` | Inspects `ggplot2::facet_wrap` panel layout tables, free-scale ranges, and strip label mappings. |
| `XG03` | `GGP-T04`, `GGP-B02` | `ggplot2`, `stats` | Inspects `ggplot2::after_stat(density)` histogram/density layer computations and bin geometry. |
| `XG04` | `GGP-E08`, `GGP-P01` | `ggplot2`, `stats` | Inspects `ggplot2::sec_axis` affine forward/inverse transformations and secondary break positions. |
| `XG05` | `GGP-E04`, `GGP-E07`, `GGP-N01` | `ggplot2`, `stats` | Inspects `ggplot2::position_dodge` and `position_jitterdodge` x-offset coordinates and group alignment. |
| `XM01` | `ECO-BIO03`, `ADDON-B10` | `DESeq2`, `SummarizedExperiment`, `BiocVersion` | Cross-checks `DESeq2::DESeq` / `DESeq2::results` interaction contrast, `metadata(res)$filterTheta`, and normal-prior posterior shrinkage (`beta * v0 / (se^2 + v0)`). |
| `XM02` | `ANOVA-A14`, `ANOVA-A15` | `stats` | Cross-checks baseline standardized mean differences (SMDs) and stratum-adjusted vs covariate-adjusted `stats::lm` treatment effect estimates (`vcov` SEs and t-intervals). |
| `XM03` | `ECO-SH01`, `ECO-SH03`, `ADDON-B08`, `ADDON-C03` | `shiny`, `cachem` | Probes `shiny::moduleServer`, `shiny::bindCache`, and `cachem::cache_mem` inside `shiny::testServer` across cohort filtering, unit scaling, and cache hit counters. |
| `XM04` | `ECO-BIO04`, `ADDON-C10`, `ADDON-B10` | `SummarizedExperiment`, `BiocVersion`, `digest` | Cross-checks gene-level `rowsum` count/TPM aggregation, TPM-weighted effective lengths (fallback to unweighted mean when gene TPM == 0), `SummarizedExperiment` metadata, and `digest::digest(..., algo = 'sha256')`. |
| `XP01` | `ECO-PK01`, `ECO-PK03` | `tools`, `utils` | Cross-checks installed `utils::installed.packages` / `packageDescription` fields (`License`, `NeedsCompilation`, `Priority`) in the pinned container library. |
| `XP02` | `ECO-PL02`, `ECO-GP03` | `tools`, `utils` | Cross-checks `getNamespaceExports` and S3 method registration tables (`__S3MethodsTable__.`) in the pinned container library. |
| `XP03` | `ECO-PK02`, `ECO-PL02` | `tools`, `utils` | Cross-checks `tools::package_dependencies` direct/reverse dependency graphs over installed `DESCRIPTION` metadata. |
| `XP04` | `ECO-SRC02`, `ECO-BIO01`, `ADDON-C09` | `utils`, `Biobase`, `DESeq2`, `BiocVersion` | Cross-checks recursive `Imports`/`Depends`/`LinkingTo` dependency closure and topological installation layer depths. |
| `XP05` | `ECO-PK02`, `ADDON-C06` | `utils` | Cross-checks `renv.lock` JSON package records against a supplied library manifest snapshot (`missing`, `extra`, `version_mismatch`, `clean`). |
| `XR01` | `HARD-H01`, `ADDON-B01` | `dplyr` | Cross-checks `tidyr::pivot_longer` / `tidyr::pivot_wider` migration against base R reshape/split-apply-combine reference tables. |
| `XR02` | `ADDON-C04` | `stats` | Verifies `data.table::copy()` isolation so caller `data.table` objects are never mutated in place by `:=` or `set*`. |
| `XR03` | `ADDON-B05`, `HARD-H10` | `stats` | Cross-checks `lubridate` DST-safe period vs duration arithmetic in `America/New_York` and `UTC`. |
| `XR04` | `HARD-H03` | `tidyr` | Cross-checks `dplyr::across()` + named list `.names` specifications against explicit column-wise aggregations. |
| `XR05` | `HARD-H09`, `ADDON-C07` | `purrr`, `tidyr` | Cross-checks `purrr::pmap` / `map_dbl` / `map_chr` type stability and verifies exact invocation count (`n_calls == 6L`) via a candidate-session counter. |
| `XV01` | `HARD-H01` | `dplyr`, `stats` | Cross-checks `dplyr` 1.2.0 `.by` + `reframe()` multi-row quantile summaries and ungrouped tibble return invariants. |
| `XV02` | `HARD-H04`, `ADDON-B04` | `dplyr` | Cross-checks `dplyr::join_by(segment, closest(order_date >= effective_date))` rolling as-of join against `base::findInterval`. |
| `XV03` | `ECO-V02` | `tibble` | Cross-checks R 4.x `inherits(x, 'matrix')` / `is.array(x)` / `tibble::is_tibble` type classification hierarchy. |
| `XV04` | `ECO-GP01`, `ADDON-C02`, `GGP-E08` | `ggplot2` | Cross-checks `ggplot2` 3.4+/4.0 `linewidth`, `after_stat(density)`, and `theme(legend.position = 'inside', legend.position.inside = ...)`. |
| `XV05` | `ADDON-C04`, `HARD-H03` | `readr`, `utils` | Cross-checks `readr::read_csv(I(text), col_types = ...)` literal-input parsing and `readr::problems()` cell-level audit counts without temporary files or warnings. |
