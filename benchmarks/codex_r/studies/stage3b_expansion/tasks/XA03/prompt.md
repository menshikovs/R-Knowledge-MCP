# XA03: Marginal-means ANOVA for an unbalanced two-factor experiment

A study assigned participants to one of several `treatment` conditions within one of several
`program` sites and recorded a numeric `score`. Every treatment-by-program combination ("cell")
has observations, but the cell sizes are unequal. A sample of the data is in `data/experiment.csv`
(columns `participant_id`, `treatment`, `program`, `score`).

The research questions are about **equal-weight marginal means**:

1. Do the treatments differ when each treatment's mean is the unweighted average of its cell means
   over the programs?
2. Do the programs differ when each program's mean is the unweighted average of its cell means
   over the treatments?
3. Is there a treatment-by-program interaction?

Write `solution.R` defining two functions. Use only R packages that are installed in the supplied
environment (see `renv.lock`); do not install anything.

## `type3_anova(data)`

`data` is a data frame with columns `treatment`, `program` and `score`. The columns `treatment`
and `program` may be character, factor or ordered factor; other columns may be present and must
be ignored. Return a data frame with these rows, in this order: `treatment`, `program`,
`treatment:program`, `Residuals`, and these numeric columns:

| column | meaning |
| --- | --- |
| `df` | degrees of freedom |
| `sum_sq` | sum of squares for the hypothesis in the question above |
| `mean_sq` | `sum_sq / df` |
| `f_value` | F statistic against the residual mean square of the full interaction model (`NA` for `Residuals`) |
| `p_value` | upper-tail p-value of that F statistic (`NA` for `Residuals`) |

Rules:

- Rows with a missing `score`, `treatment` or `program` are dropped before anything is computed.
- The result must not depend on the row order, on the order of factor levels, or on how factors
  are stored (character, factor or ordered).
- If any treatment-by-program cell has no observations after dropping missing rows, the
  marginal hypotheses are not estimable: stop with an error.
- A missing required column is an error.
- Do not modify `data`.

## `type1_order_dependent(data)`

Return a single `TRUE` or `FALSE`: does the sequential ("Type I") sum of squares of at least one
main effect change when the order in which the two factors enter the model is swapped? The same
input rules as above apply.

## Notes

Numerical comparisons use a relative tolerance of about 1e-6. Put all code in `solution.R`; the
file will be sourced into a fresh R session and the two functions will be called with data frames
you have not seen.
