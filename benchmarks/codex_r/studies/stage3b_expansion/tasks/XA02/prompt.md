# XA02: Two-way factorial analysis that respects the interaction

A balanced experiment crossed two factors: `treatment` and `site`. Every treatment-by-site cell
has the same number (at least 2) of participants, each measured once on a numeric `score`. A
sample is in `data/experiment.csv` (columns `participant_id`, `treatment`, `site`, `score`).

The analysis plan is fixed in advance:

1. Fit the full factorial model (both main effects and their interaction) and report its ANOVA
   table.
2. The interaction is "significant" if its p-value is below 0.05.
3. If the interaction is significant, main effects are **not** interpreted on their own. Report
   the **simple effects of `treatment` within each `site`**: for every site, the F test that the
   treatment cell means differ at that site, using the **residual mean square of the full
   factorial model** (not a separate error term estimated from that site alone).
4. Otherwise report the main effects and no simple effects.

Write `solution.R` defining `factorial_analysis(data)`. `data` has at least the columns
`treatment`, `site` (character or factor) and `score` (numeric). Use only packages installed in
the supplied environment (see `renv.lock`); do not install anything.

## Return value

A list with exactly these elements:

| element | content |
| --- | --- |
| `anova` | data frame with rows `treatment`, `site`, `treatment:site`, `Residuals` (in this order) and numeric columns `df`, `sum_sq`, `mean_sq`, `f_value`, `p_value` (`NA` for `Residuals`) |
| `cell_means` | data frame with columns `treatment`, `site`, `mean`, `n`: one row per cell, ordered by `treatment` then `site` (labels sorted with `sort()`) |
| `interaction_significant` | `TRUE` or `FALSE` |
| `report_level` | `"simple_effects"` if the interaction is significant, otherwise `"main_effects"` |
| `simple_effects` | `NULL` unless the interaction is significant; otherwise a data frame with one row per site (ordered by `sort()` of the site labels) and columns `site`, `df1`, `df2`, `sum_sq`, `f_value`, `p_value` |

## Rules

- Rows with a missing `treatment`, `site` or `score` are dropped first. After that the design
  must still be balanced with at least 2 observations per cell and at least 2 levels of each
  factor; otherwise stop with an error (sums of squares would not be uniquely defined).
- Do not modify `data`; the result must not depend on row order.

Numerical comparisons use a relative tolerance of about 1e-6. The file will be sourced into a
fresh R session and `factorial_analysis` called on data frames you have not seen.
