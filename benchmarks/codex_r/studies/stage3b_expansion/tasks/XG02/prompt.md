# XG02: Mean outcome per group as a bar chart

Participants belong to a `group` and have a numeric outcome `y` that is sometimes missing. A
sample is in `data/outcomes.csv` (columns `participant_id`, `group`, `y`).

Write `solution.R` defining `plot_group_means(data)`, which returns a **ggplot2** plot object (do
not print or save anything). `data` is a data frame with columns `group` (character or factor)
and `y` (numeric). Use only packages installed in the supplied environment (see `renv.lock`).

## What the plot must show

- One **bar** per group whose height is the mean of that group's non-missing `y` values, starting
  at zero.
- Bars in the order of the factor levels of `group` if it is a factor, otherwise in `sort()`
  order of the group labels.
- Groups that have **no** non-missing `y` value must not appear at all: no bar and no empty slot
  on the horizontal axis. Rows with a missing `group` are ignored.
- Axis titles exactly `Group` (horizontal) and `Mean y` (vertical).

## Rules

- Do not modify `data`; the plot must not depend on row order.
- The plot is inspected through `ggplot2::ggplot_build()` (layer data, scales, labels);
  rendering is not required.

The file will be sourced into a fresh R session and `plot_group_means` called on data frames you
have not seen.
