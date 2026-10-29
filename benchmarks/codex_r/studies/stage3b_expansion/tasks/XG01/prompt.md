# XG01: Daily mean scores on a complete calendar, with honest gaps

A monitoring programme records a numeric `score` for participants on calendar days; several
readings can fall on the same day and some scores are missing. A sample is in
`data/readings.csv` (columns `reading_id`, `day` as `YYYY-MM-DD`, `score`).

Write `solution.R` defining `plot_daily_means(data)`, which returns a **ggplot2** plot object (do
not print or save anything). `data` is a data frame with a `Date` column `day` and a numeric
column `score`. Use only packages installed in the supplied environment (see `renv.lock`).

## What the plot must show

- The mean `score` per calendar day, computed from that day's non-missing scores.
- A **line layer** that covers **every calendar day** from the earliest to the latest `day` in
  `data`, inclusive. On a day with no non-missing score the mean is missing (`NA`) and the line
  must be **broken** there: no interpolation across the gap and no zero filled in.
- A **point layer** that marks only the days that have a mean.
- A date axis for the horizontal axis. The axis titles are exactly `Day` (horizontal) and
  `Mean score` (vertical).

## Rules

- Rows with a missing `day` are ignored.
- A day that has readings but only missing scores has no mean (treat it like a day without
  readings).
- Do not modify `data`; the plot must not depend on row order.
- The plot is inspected through `ggplot2::ggplot_build()`; layer data, scales and labels are
  checked, and rendering is not required.

The file will be sourced into a fresh R session and `plot_daily_means` called on data frames you
have not seen.
