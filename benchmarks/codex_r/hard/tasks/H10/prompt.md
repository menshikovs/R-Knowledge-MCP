# H10 — Pooling multiple-imputation estimates (Rubin's rules)

Write `/candidate/solution.R` defining:

```r
pool_estimates(estimates, std_errors, conf_level = 0.95,
               method = c("rubin1987", "barnard_rubin1999"), complete_df = NULL)
```

Use base R only (no packages are needed; mice is not installed). Sourcing
`solution.R` must only define functions.

`estimates` and `std_errors` hold one scalar parameter estimate and its standard
error from each of `m` completed (imputed) data sets.

## Method

Pool with Rubin's rules: the pooled estimate is the mean of the estimates; the
within-imputation variance is the mean of the squared standard errors; the
between-imputation variance is the sample variance of the estimates; the total
variance is within + (1 + 1/m) × between. Report:

- `riv`: relative increase in variance, (1 + 1/m) × between / within;
- `lambda`: proportion of total variance due to missingness, (1 + 1/m) × between / total;
- `df`: for `method = "rubin1987"`, Rubin's (1987) large-sample degrees of freedom;
  for `"barnard_rubin1999"`, the Barnard & Rubin (1999) small-sample degrees of
  freedom with complete-data degrees of freedom `complete_df`;
- `fmi`: fraction of missing information, `(riv + 2 / (df + 3)) / (riv + 1)`;
- a two-sided `conf_level` confidence interval `estimate ± q × std_error`, where `q`
  is the Student t quantile with `df` degrees of freedom and `std_error` is the
  square root of the total variance.

Use the exact formulas, with no clamping or other adjustments, and these limits:

- Between-imputation variance 0 (all estimates equal) with positive within variance:
  `riv = lambda = 0`; `"rubin1987"` gives `df = Inf`; `"barnard_rubin1999"` gives
  its observed-data degrees of freedom.
- Total variance 0 (all standard errors 0 and all estimates equal): `std_error = 0`,
  both interval bounds equal the estimate, `riv = lambda = fmi = 0`, and `df` as in the
  previous rule.
- Within variance 0 but between variance positive: `riv = Inf`, `lambda = 1`,
  `fmi = 1`; `"rubin1987"` gives `df = m - 1`; `"barnard_rubin1999"` gives `df = 0`
  and both interval bounds `NA_real_`.

## Result

A named list with exactly these elements, in this order:
`estimate`, `std_error`, `df`, `ci_lower`, `ci_upper`, `within_var`, `between_var`,
`total_var`, `riv`, `lambda`, `fmi` (all single doubles), `m` (integer), `method`
(the chosen method string) and `conf_level` (double).

## Numerical accuracy

`estimate`, `std_error`, `df`, the interval bounds, `riv`, `lambda` and `fmi` must
have a relative error of at most 1e-10 whenever their exact values are finite
doubles — including when estimates are close to the largest double or when standard
errors are so small or large (for example 1e-170 or 1e+200) that the variances
themselves underflow or overflow. `within_var`, `between_var` and `total_var` may be
`0` or `Inf` when their exact values are not representable, and must otherwise meet
the same accuracy.

## Errors

Signal an error whose class includes `"pool_input_error"` (for example with
`stop(structure(class = c("pool_input_error", "error", "condition"),
list(message = "...", call = NULL)))`) when: the inputs are not numeric vectors of
the same length `m >= 2`; any estimate or standard error is not finite; any standard
error is negative; `conf_level` is not a single number strictly between 0 and 1;
`method` is not one of the two methods; `complete_df` is not a single finite
positive number for `"barnard_rubin1999"`, or is not `NULL` for `"rubin1987"`.
Inputs must not be modified and no warnings may be emitted.

`data/imputations.csv` contains an example with `m = 5`. Test your function locally
with installed R before finishing.
