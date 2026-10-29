# XA05: Adjusting for a baseline covariate, but only if slopes are parallel

Participants were randomly assigned to a `treatment`; a numeric `baseline` measurement was taken
before treatment and a numeric `score` afterwards. A sample is in `data/trial.csv` (columns
`participant_id`, `treatment`, `baseline`, `score`). The analysis plan is fixed in advance:

1. **Slope homogeneity.** Compare the parallel-slopes model (`score` on `treatment` and
   `baseline`) with the separate-slopes model (adding the `treatment` x `baseline` interaction)
   by the F test for the interaction terms. Slopes are treated as homogeneous if p >= 0.05.
2. **Homogeneous slopes.** Use the parallel-slopes ANCOVA. Report the F test for `treatment`
   adjusted for `baseline` (the `treatment` term entered after `baseline`), and the **adjusted
   means**: each treatment's fitted mean at the overall mean of `baseline` (over all analysed
   participants).
3. **Heterogeneous slopes.** A single adjusted treatment effect does not exist. Use the
   separate-slopes model and report each treatment's fitted mean at three baseline values: the
   overall mean of `baseline` minus one sample standard deviation, the overall mean, and the
   overall mean plus one standard deviation.

Write `solution.R` defining `ancova_analysis(data)`. `data` has at least the columns `treatment`
(character or factor), `baseline` and `score` (numeric). Use only packages installed in the
supplied environment (see `renv.lock`); do not install anything.

## Return value

A list with exactly these elements:

| element | content |
| --- | --- |
| `slope_test` | list with numeric `f_value`, `df1`, `df2`, `p_value` of the homogeneity test |
| `slopes_homogeneous` | `TRUE` or `FALSE` |
| `model` | `"parallel"` or `"separate"` |
| `treatment_test` | for homogeneous slopes a list with `f_value`, `df1`, `df2`, `p_value`; otherwise `NULL` |
| `adjusted_means` | for homogeneous slopes a data frame with columns `treatment`, `adjusted_mean` (rows ordered by `sort()` of the labels); otherwise `NULL` |
| `conditional_means` | for heterogeneous slopes a data frame with columns `treatment`, `at` (`"minus_1sd"`, `"mean"`, `"plus_1sd"`), `baseline`, `fitted`, ordered by treatment then `at` as listed; otherwise `NULL` |

## Rules

- Rows with a missing `treatment`, `baseline` or `score` are dropped first.
- At least 2 treatment levels are required, every level needs at least 3 observations, and
  `baseline` must not be constant; otherwise stop with an error.
- Do not modify `data`; the result must not depend on row order.

Numerical comparisons use a relative tolerance of about 1e-6. The file will be sourced into a
fresh R session and `ancova_analysis` called on data frames you have not seen.
