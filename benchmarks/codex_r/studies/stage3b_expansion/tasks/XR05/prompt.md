# XR05: Migrate a parameter-grid evaluator off deprecated purrr functions

A simulation harness evaluates a function over every combination of parameter values. The helper
was written with early purrr and now emits deprecation warnings in the environment recorded in
`renv.lock`:

```r
evaluate_grid <- function(params, f) {
  grid <- purrr::cross(params)
  results <- purrr::invoke_map(f, grid)
  data.frame(do.call(rbind, lapply(grid, unlist)), result = unlist(results))
}
```

Write `solution.R` defining `evaluate_grid(params, f)`. It must run **without any warning or
error** in the supplied environment and must not use deprecated functions. A sample call is
described in `data/grid.csv` (the parameter values used in the harness). Use only packages
installed in the supplied environment; do not install anything.

## Behaviour

- `params` is a non-empty **named list** of non-empty atomic vectors (numeric or character); the
  names are unique and non-blank. `f` is a function that is called once per combination with
  **named arguments** (`f(a = ..., b = ...)`, one scalar value per parameter) and returns a single
  number.
- Return a plain data frame with one column per parameter (in the order of `params`, **keeping
  each parameter's type**: character stays character, no factors) followed by the numeric column
  `result`, with one row per combination.
- Row order is that of `expand.grid()`: the **first parameter varies fastest**. Row names are
  `1, 2, ...`.
- Arguments are matched to `f` **by name**, whatever the order of the formals of `f`.
- If `params` is not a valid named list, `f` is not a function, or `f` returns something that is not
  a single number for some combination, stop with an error.
- Do not modify `params`.

The file will be sourced into a fresh R session and `evaluate_grid` called with lists and functions
you have not seen.
