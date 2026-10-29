# XA06: Treatment-by-time interaction when some visits are missing

Participants were randomised to a `treatment` and measured on a numeric `score` at several visits
(`time`). Some participants missed some visits. A sample is in `data/visits.csv` (columns `id`,
`treatment`, `time`, `score`; one row per attended visit). The analysis plan is fixed in advance:

1. Analyse **all available observations**; do not discard participants who missed a visit.
2. Model the repeated measures of each participant with a **random intercept** per `id`, with
   `treatment` and `time` as categorical fixed effects (`time` is a factor, not a numeric trend).
3. Test the `treatment` x `time` interaction by a **likelihood-ratio test** between the model with
   `treatment * time` and the model with `treatment + time`. Both models must be fitted by
   **maximum likelihood** (not REML), because their fixed-effects structures differ. The test
   statistic is twice the difference of the maximised log-likelihoods, compared with a
   chi-square distribution whose degrees of freedom are the difference in the number of
   fixed-effect parameters.

Write `solution.R` defining `longitudinal_test(data)`. `data` has at least the columns `id` (any
type), `treatment`, `time` (character, factor or integer) and `score` (numeric). Use only packages
installed in the supplied environment (see `renv.lock`); do not install anything.

## Return value

A list with exactly these elements:

| element | content |
| --- | --- |
| `n_subjects`, `n_observations` | integers: participants and rows used after dropping missing values |
| `lrt` | list with numeric `statistic`, `df`, `p_value` |
| `significant` | `TRUE` if `lrt$p_value < 0.05` |
| `random_intercept_sd` | ML estimate of the standard deviation of the random intercepts in the full model |
| `residual_sd` | ML estimate of the residual standard deviation in the full model |

## Rules

- Rows with a missing `id`, `treatment`, `time` or `score` are dropped first.
- Each `id` must belong to exactly one `treatment`; otherwise stop with an error. At least 2
  treatment levels and 2 time levels are required; otherwise stop with an error.
- Do not modify `data`; the result must not depend on row order.

Likelihood-based quantities are compared with a relative tolerance of about 1e-4. The file will
be sourced into a fresh R session and `longitudinal_test` called on data frames you have not
seen.
