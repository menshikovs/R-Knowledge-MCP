# XR01: Repair a legacy "top rows per group" helper

A team inherited this helper, written years ago. It no longer runs in the environment recorded in
`renv.lock` (a recent dplyr):

```r
top_by <- function(data, group, rank, n = 1L) {
  data %>%
    group_by_(group) %>%
    arrange_(paste0("desc(", rank, ")")) %>%
    filter_(paste0("row_number() <= ", n)) %>%
    ungroup()
}
```

Write `solution.R` defining `top_by(data, group, rank, n = 1L)` with the behaviour below. It must
run **without any warning or error** in the supplied environment and must not use deprecated or
removed functions. `group` and `rank` are **names** (single strings) of columns of `data`. Use only
packages installed in the supplied environment; do not install anything. A sample is in
`data/scores.csv` (columns `team`, `player`, `points`).

## Behaviour

- For each value of `group`, keep the `n` rows with the **largest** values of `rank`. If a group
  has fewer than `n` usable rows, keep all of them. Ties in `rank` are broken by the **original
  row order** (the earlier row wins).
- Rows with a missing `group` or a missing `rank` are ignored.
- Return a plain data frame with the same columns as `data` (same order, same types), with rows
  ordered by `group` (ascending) and then by `rank` (descending, ties in original order). Row
  names are `1, 2, ...`.
- `n` must be a single whole number of at least 1; otherwise stop with an error.
- Do not modify `data`.

The file will be sourced into a fresh R session and `top_by` called on data frames you have not
seen.
