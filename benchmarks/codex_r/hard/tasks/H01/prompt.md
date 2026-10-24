# H01 — Dynamic weighted group summaries

Write `/candidate/solution.R` defining:

```r
dynamic_summary(data, groups, measure, weight)
```

Installed packages you may use include dplyr 1.2.1, rlang 1.3.0 and tibble 3.3.1
(see `renv.lock`). Do not install packages. Sourcing `solution.R` must only define
functions: no data loading, printing or global side effects.

## Arguments

- `data`: a data frame or tibble. It may already be grouped with `dplyr::group_by()`;
  any existing grouping is ignored.
- `groups`: a character vector of zero or more distinct column names.
- `measure`, `weight`: single column names (strings) of numeric (integer or double)
  columns.

Column names can be anything R allows, including names with spaces, punctuation,
non-ASCII letters, and names such as `.data`, `.env`, `data`, `groups`, `measure`
or `weight`. Names are always given as strings, never as symbols or expressions, and
must be treated literally. The result must not depend on variables that happen to
exist in the calling or global environment.

## Errors

- A name in `groups`, `measure` or `weight` that is not a column of `data`, a
  duplicated name in `groups`, or a non-numeric `measure`/`weight` column: signal an
  error whose class includes `"dynamic_summary_bad_column"` (for example with
  `rlang::abort(class = "dynamic_summary_bad_column")`).
- Any row whose `weight` is finite and negative (even if its `measure` is missing):
  signal an error whose class includes `"dynamic_summary_negative_weight"`.

## Result

An ungrouped tibble (class `tbl_df`, not `grouped_df`) with exactly these columns,
in this order:

1. the grouping columns, in the order given by `groups`, with their original names
   and types (factors stay factors with the same levels);
2. `weighted_mean` (double): `sum(w * x) / sum(w)` over the group's valid rows;
3. `n_valid` (integer): number of valid rows in the group;
4. `weight_sum` (double): `sum(w)` over the group's valid rows.

A row is *valid* when both its measure `x` and weight `w` are finite (not `NA`,
`NaN`, `Inf` or `-Inf`).

- There is one result row for every combination of grouping values that occurs in
  `data`, including combinations whose rows are all invalid. Combinations that do not
  occur (for example unused factor levels) do not appear.
- `NA` in a grouping column is an ordinary group value.
- If a group has no valid rows, or its valid weights sum to zero, `weighted_mean` is
  `NA_real_` (never `NaN`); `n_valid` and `weight_sum` are still reported (`0L`/`0`
  when there are no valid rows).
- `weight_sum` must be exact for integer weights whose sum exceeds the integer range.
- Rows are sorted by the grouping columns in `groups` order, ascending: character
  values in the C locale (byte order, as `dplyr::arrange(.locale = "C")`), factors by
  level order, `NA` last within each column.
- With `groups = character()`, always return exactly one row summarizing all of
  `data` (for zero input rows: `NA_real_`, `0L`, `0`).
- With at least one grouping column and zero input rows, return zero rows with the
  same columns and types.
- `data` itself must not be modified.

`data/sales.csv` is a small example (read it with
`read.csv("data/sales.csv", check.names = FALSE)`). Test your function locally with
installed R before finishing.
