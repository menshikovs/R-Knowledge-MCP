# XR03: Repair a legacy trailing moving average

This helper was written for a report years ago. It crashes or returns wrong results on inputs that
the report generator now produces:

```r
moving_average <- function(x, k) {
  out <- c()
  for (i in 1:(length(x) - k + 1)) {
    out[i] <- mean(x[i:(i + k - 1)])
  }
  out
}
```

Write `solution.R` defining `moving_average(x, k)` that fixes the problems and has the behaviour
below. A sample series is in `data/series.csv` (column `value`, with some missing values). Use only
base R and packages installed in the supplied environment; do not install anything.

## Behaviour

- `x` is a numeric vector (possibly empty, possibly containing `NA`); `k` is the window length.
- The result is a numeric vector of the **same length as `x`**. Element `i` is the mean of the
  **trailing** window `x[(i - k + 1):i]` (the current value and the `k - 1` before it).
- Element `i` is `NA` when the window is incomplete (`i < k`) **or** the window contains a missing
  value. Missing values are never skipped.
- If `k` is larger than `length(x)`, every element is `NA`. An empty `x` gives `numeric(0)`.
- `k` must be a single whole number of at least 1; `x` must be numeric (integer or double).
  Otherwise stop with an error.
- The result is a plain double vector with no names or other attributes. Do not modify `x`.

The file will be sourced into a fresh R session and `moving_average` called on vectors you have not
seen.
