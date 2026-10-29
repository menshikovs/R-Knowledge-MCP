# XA04: Repeated-measures ANOVA with a sphericity correction

Every participant was measured on the same ordered occasions, giving long-format data with
columns `subject`, `time` and `score`. A sample is in `data/measurements.csv`. The analysis plan
is fixed in advance:

1. Test the within-subject effect of `time` with the one-factor repeated-measures ANOVA. The error
   term is the `time` x `subject` interaction; the measurements of one participant are not
   independent.
2. Estimate the Greenhouse-Geisser epsilon from the sample covariance matrix of the occasions.
3. If that epsilon is below 0.75, the **primary** p-value is the Greenhouse-Geisser-corrected one
   (both degrees of freedom multiplied by epsilon, F unchanged); otherwise it is the uncorrected
   p-value.

Write `solution.R` defining `rm_anova(data)`. `data` is a data frame in long format with at least
the columns `subject` (any type), `time` (character, factor or integer) and `score` (numeric).
Use only packages installed in the supplied environment (see `renv.lock`); do not install
anything.

## Return value

A list with exactly these elements:

| element | content |
| --- | --- |
| `n_subjects`, `n_levels` | integers: complete subjects used, number of occasions |
| `ss_time`, `ss_error` | sum of squares of `time` and of its error term (`time` x `subject`) |
| `df1`, `df2`, `f_value`, `p_value` | the uncorrected test |
| `epsilon_gg` | the Greenhouse-Geisser epsilon |
| `p_gg` | the Greenhouse-Geisser-corrected p-value |
| `correction` | `"greenhouse_geisser"` if `epsilon_gg < 0.75`, otherwise `"none"` |
| `p_primary` | `p_gg` if `correction` is `"greenhouse_geisser"`, otherwise `p_value` |

## Rules

- Occasions are the sorted unique values of `time` (as character strings, `sort()` order).
- Subjects that do not have a non-missing `score` at **every** occasion are dropped entirely
  (listwise by subject). Each remaining subject must have exactly one value per occasion.
- At least 3 occasions and at least 4 complete subjects are required; otherwise stop with an
  error. A subject with more than one row at the same occasion is an error.
- Do not modify `data`; the result must not depend on row order.

Numerical comparisons use a relative tolerance of about 1e-6. The file will be sourced into a
fresh R session and `rm_anova` called on data frames you have not seen.
