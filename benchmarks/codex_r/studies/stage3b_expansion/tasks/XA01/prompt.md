# XA01: Choosing between classical and Welch one-way ANOVA

Several independent groups of participants were measured on a numeric `score`; group sizes and
spreads may differ. A sample is in `data/experiment.csv` (columns `participant_id`, `group`,
`score`). The analysis plan is fixed in advance:

1. Test equality of variances with the **Brown-Forsythe** test: the ordinary one-way ANOVA F test
   applied to the absolute deviations of each observation from the **median** of its own group.
   Variances are treated as equal if that test's p-value is at least 0.05.
2. If variances are equal, use the classical (pooled-variance) one-way ANOVA and Tukey-Kramer
   all-pairwise comparisons. Otherwise use Welch's one-way ANOVA (unequal variances) and all
   pairwise Welch t-tests (no pooled variance, Satterthwaite degrees of freedom) with Holm
   adjustment over all pairs.

Write `solution.R` defining `compare_groups(data)`. `data` is a data frame with at least the
columns `group` (character) and `score` (numeric). Use only packages installed in the supplied
environment (see `renv.lock`); do not install anything.

## Return value

A list with exactly these elements:

| element | content |
| --- | --- |
| `variance_test` | list with numeric `statistic`, `df1`, `df2`, `p_value` of the Brown-Forsythe test |
| `method` | `"classical"` or `"welch"` |
| `omnibus` | list with numeric `statistic`, `df1`, `df2`, `p_value` of the F test for the chosen method |
| `pairwise` | data frame with columns `group1`, `group2`, `diff`, `p_adjusted` (below) |

`pairwise` has one row per pair of groups. Groups are ordered by `sort()` on their labels; the
pairs are (1,2), (1,3), ..., (2,3), ... in that order, with `group1` before `group2` in that
ordering. `diff` is `mean(group2) - mean(group1)`. `p_adjusted` is the Tukey-Kramer adjusted
p-value (classical branch) or the Holm-adjusted Welch p-value (Welch branch).

## Rules

- Rows with a missing `group` or `score` are dropped first.
- At least three groups are required, and every group needs at least two observations; otherwise
  stop with an error.
- Do not modify `data`; the result must not depend on row order.

Numerical comparisons use a relative tolerance of about 1e-6. The file will be sourced into a
fresh R session and `compare_groups` called on data frames you have not seen.
