# XV01: Several quantiles per group in a current tidyverse

A sales team wants the quartiles of a numeric measure within each group. A sample is in
`data/sales.csv` (columns `region`, `amount`; some amounts are missing). The analysis scripts run
under the package versions recorded in `renv.lock` (a recent dplyr), and **must run without any
warning or error** there.

Write `solution.R` defining `group_quantiles(data, group, value, probs = c(0.25, 0.5, 0.75))`.
`group` and `value` are the **names** (single strings) of the grouping column and of the numeric
column in `data`. Use only packages installed in the supplied environment; do not install anything.

## Return value

A plain data frame with exactly the columns, in this order: the grouping column (named as given in
`group`, same values as in `data`), `prob` (the requested probability, numeric) and `value`
(the sample quantile, numeric, R's default quantile definition, `type = 7`).

- One row per group and probability, ordered by group (ascending) and then by `prob` in the
  order given in `probs`.
- Missing values of `value` are ignored. A group with no non-missing value is omitted.
- Groups are character values; a missing group value is not a group and its rows are ignored.

## Rules

- `probs` must contain numbers in [0, 1] without missing values; otherwise stop with an error.
- Do not modify `data`.

The file will be sourced into a fresh R session and `group_quantiles` called on data frames you
have not seen.
