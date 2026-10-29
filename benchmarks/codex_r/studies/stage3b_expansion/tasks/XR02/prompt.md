# XR02: Repair a legacy paired-difference analysis

A clinic measured the same participants `before` and `after` a programme. This analysis helper was
written for an old R version and now fails in the R version recorded in `renv.lock`:

```r
paired_difference <- function(data) {
  long <- stack(data[c("before", "after")])
  tt <- t.test(values ~ ind, data = long, paired = TRUE)
  list(n = nrow(data), mean_difference = unname(tt$estimate),
       p_value = tt$p.value)
}
```

Write `solution.R` defining `paired_difference(data)` that performs the intended analysis and runs
**without any warning or error** in the supplied environment. A sample is in `data/clinic.csv`
(columns `id`, `before`, `after`; some measurements are missing). Use only packages installed in the
supplied environment; do not install anything.

## Behaviour

The analysis is a **paired** two-sided t-test of the within-participant differences
`d = after - before`, using only participants with **both** measurements. Return a list with
exactly these elements (all numeric unless stated, no names on the values):

| element | content |
| --- | --- |
| `n` | integer: number of participants with both measurements |
| `mean_difference` | mean of `d` (so a positive value means `after` is larger) |
| `sd_difference` | sample standard deviation of `d` |
| `statistic` | the paired t statistic |
| `df` | degrees of freedom |
| `p_value` | two-sided p-value |
| `conf_low`, `conf_high` | 95% confidence interval for the mean difference |

## Rules

- Fewer than two complete pairs, or differences that are all identical (zero variance), are
  errors: stop with an error.
- Do not modify `data`.

The file will be sourced into a fresh R session and `paired_difference` called on data frames you
have not seen.
