# XG04: Zoom into a region without changing the fitted line

A calibration experiment recorded pairs `x`, `y`. A sample is in `data/measurements.csv`
(columns `sample_id`, `x`, `y`). A colleague wants a close-up of a region of the plot, **but the
regression line must still describe all of the data**.

Write `solution.R` defining `plot_zoomed_fit(data, xlim)`, which returns a **ggplot2** plot object
(do not print or save anything). `data` is a data frame with numeric columns `x` and `y`; `xlim`
is a numeric vector of length 2 (the horizontal zoom window). Use only packages installed in the
supplied environment (see `renv.lock`).

## What the plot must show

- A **point layer** with every row whose `x` and `y` are both finite, **including rows outside
  the zoom window**. Zooming must not remove observations.
- A **line layer** with the ordinary least-squares line of `y` on `x` (`lm`), fitted to **all**
  rows with finite `x` and `y`, not only to the rows inside the window.
- The visible horizontal range is the zoom window `xlim` (plus ggplot2's default expansion).

## Rules

- `xlim` must be two finite numbers with `xlim[1] < xlim[2]`; otherwise stop with an error.
- Rows with a missing or infinite `x` or `y` are ignored.
- Do not modify `data`.
- The plot is inspected through `ggplot2::ggplot_build()` (layer data, coordinate limits, panel
  range); rendering is not required.

The file will be sourced into a fresh R session and `plot_zoomed_fit` called on data frames and
windows you have not seen.
