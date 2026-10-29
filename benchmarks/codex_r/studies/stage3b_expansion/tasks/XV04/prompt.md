# XV04: Overlaid density histograms with a legend inside the panel

A lab compares the distribution of a measurement between groups. A sample is in
`data/measurements.csv` (columns `value`, `group`). The plotting scripts run under the package
versions recorded in `renv.lock` (a recent ggplot2) and **must run without any deprecation
warning** there, including when the plot is built.

Write `solution.R` defining `plot_density_histogram(data, bins = 10L)`, which returns a **ggplot2**
plot object (do not print or save anything). `data` is a data frame with a numeric column `value`
and a column `group`. Use only packages installed in the supplied environment; do not install
anything.

## What the plot must show

- A **histogram layer** with `bins` bins per group, drawn on the **density** scale (the area of
  each group's bars sums to 1), so that groups of different sizes are comparable. The groups are
  **overlaid** (not stacked); the bars are filled by `group`.
- A **density-curve layer** (one curve per group, same `group` colouring) whose line width is at
  least 0.8.
- The vertical axis title is exactly `Density`.
- The **legend is placed inside the plotting area, in its upper right part** (both coordinates of
  the inside position at least 0.5), not outside it.

## Rules

- `bins` must be a single whole number of at least 2; otherwise stop with an error.
- Rows with a missing `value` or `group` are ignored. Do not modify `data`.
- The plot is inspected through `ggplot2::ggplot_build()` and the plot's theme; rendering is not
  required.

The file will be sourced into a fresh R session and `plot_density_histogram` called on data frames
you have not seen.
