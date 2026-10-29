# XM02: Multi-site treatment investigation with a baseline covariate and a post-treatment variable

A multi-site study evaluates a treatment (`arm`) across several clinical sites (`site`). A sample
table is in `data/study.csv` with the columns `subject_id`, `arm`, `site`, `baseline`,
`post_adherence`, and `outcome`.

- `baseline` was measured **before** treatment assignment and is a valid pre-treatment covariate.
- `post_adherence` was measured **after** treatment assignment; it is a post-treatment variable
  (and is frequently missing even when `outcome` was recorded). Conditioning on or filtering rows by
  a post-treatment variable biases the estimated treatment effect, so `post_adherence` must be
  **ignored completely** (neither used to drop rows nor included in any regression model).

Write `solution.R` defining
`investigate_study(records, active_arm, control_arm, alpha = 0.05)` using only packages installed in
the supplied environment (`stats`); do not install anything.

## Step 1: Data screening

1. Keep only rows where `arm`, `site`, `baseline`, and `outcome` are all non-missing (`!is.na()`).
   Rows whose only missing value is in `post_adherence` (or any other extra column) **must be
   retained**.
2. Among the retained rows, verify that:
   - `subject_id` has no missing values and no duplicates,
   - `active_arm` and `control_arm` are distinct strings and the retained `arm` values consist
     **only** of those two arms,
   - there are at least 2 distinct sites, and every `(site, arm)` cell has at least 2 retained
     observations,
   - `baseline` is not constant (`sd(baseline) > 0`), and `alpha` is strictly between `0` and `1`.
   If any check fails, stop with an error.

## Step 2: Treatment-by-site interaction test

Fit two ordinary least-squares linear models on the retained rows:

- **Additive model:** `outcome ~ baseline + site + arm`
- **Interaction model:** `outcome ~ baseline + site * arm`

Here `site` and `arm` are categorical factors (with `control_arm` as the reference level of `arm`),
and `baseline` enters as a single linear numeric covariate. Compare the two models with the
extra-sum-of-squares F test for the `site:arm` interaction terms (`f_value`, numerator degrees of
freedom `df1`, residual degrees of freedom `df2`, and p-value `p_value`). Set
`interaction_present = (p_value < alpha)`.

## Step 3: Site-specific and pooled treatment contrasts

1. **Site-specific effects (`site_effects`):** From the **interaction model**
   (`outcome ~ baseline + site * arm`), compute the baseline-adjusted treatment effect
   (`active_arm` minus `control_arm`) within each site, using that model's pooled residual standard
   error and residual degrees of freedom `df2`. Return a plain data frame with one row per site,
   ordered by `sort(unique(site))`, and exact columns:
   `site` (character), `n_control` (integer), `n_active` (integer), `estimate`, `se`, `p_value`
   (two-sided t-test p-value using `df2`). Row names are `1, 2, ...`.
2. **Pooled main effect (`pooled_effect`):**
   - If `interaction_present` is `FALSE`, return a list with numeric scalars
     `estimate`, `se`, `df`, `p_value`, `ci_low`, `ci_high` giving the baseline- and site-adjusted
     `active_arm` minus `control_arm` contrast from the **additive model**
     (`outcome ~ baseline + site + arm`), where `ci_low` and `ci_high` form the two-sided
     `(1 - alpha)` t confidence interval.
   - If `interaction_present` is `TRUE`, a single site-pooled main effect is not scientifically
     appropriate; set `pooled_effect = NULL`.

## Return value

A named list with exact elements in this order:
`n_used` (integer), `n_dropped` (integer), `interaction_test` (list with `f_value`, `df1`, `df2`,
`p_value`), `interaction_present` (logical scalar), `site_effects` (data frame), and
`pooled_effect` (list or `NULL`).

Do not modify `records`; the result must not depend on input row order.

