# XR04: Repair a long-to-wide reshaping that fails on repeated measurements

This helper reshapes a long table of measurements into one row per `id` and one column per `key`.
It worked for years, but now fails on the data the lab produces (some `id`/`key` pairs were
measured more than once):

```r
wide_means <- function(data) {
  data %>%
    tidyr::spread(key, value)
}
```

Write `solution.R` defining `wide_means(data)` that returns the wide table **with repeated
measurements averaged**. It must run **without any warning or error** in the environment recorded in
`renv.lock`. A sample is in `data/long.csv` (columns `id`, `key`, `value`). Use only packages
installed in the supplied environment; do not install anything.

## Behaviour

- `data` has the columns `id` (integer or character), `key` (character) and `value` (numeric,
  possibly `NA`).
- Return a plain data frame: the first column is `id`, followed by one column per distinct `key`.
  The key columns are **sorted alphabetically** (C-locale order of the key text), and rows are
  **sorted by `id`** (numeric order for numeric ids, alphabetical for character ids). Column names
  are exactly the keys (they may contain spaces or start with digits).
- A cell is the **mean of the non-missing values** for that `id` and `key`. If an `id` has no value
  for a `key`, or only missing values, the cell is `NA`.
- An `id` that has only missing values still appears as a row. `id` keeps its type.
- Empty `data` (no rows) gives a data frame with only an `id` column and no rows.
- Do not modify `data`.

The file will be sourced into a fresh R session and `wide_means` called on data frames you have not
seen.
