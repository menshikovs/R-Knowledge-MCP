# XG03: Heatmap of within-group proportions with percent labels

Each respondent belongs to a `group` and reports the `region` where they live. A sample is in
`data/respondents.csv` (columns `respondent_id`, `group`, `region`).

Write `solution.R` defining `plot_proportion_heatmap(data)`, which returns a **ggplot2** plot
object (do not print or save anything). `data` is a data frame with columns `group` and `region`
(character or factor). Use only packages installed in the supplied environment (see
`renv.lock`).

## What the plot must show

- A **tile** for **every** combination of `group` and `region`, including combinations with no
  respondents. The horizontal axis is `region` and the vertical axis is `group`.
- The **fill** of a tile is the **proportion of that group's respondents who live in that
  region**. Within each group the proportions over all regions add up to 1 (this is a share of the
  group, not of the region and not of all respondents). The fill uses a continuous colour scale.
- A **text label** on every tile with that same share as a percentage with exactly one decimal
  and a percent sign, for example `23.5%`; an empty combination reads `0.0%`.
- Axis titles exactly `Region` (horizontal) and `Group` (vertical).
- Axis order: factor levels if the column is a factor (only levels that occur after the rows
  below are removed), otherwise `sort()` order.

## Rules

- Rows with a missing `group` or `region` are ignored.
- Do not modify `data`; the plot must not depend on row order.
- The plot is inspected through `ggplot2::ggplot_build()` and the layers' mapped values; rendering
  is not required.

The file will be sourced into a fresh R session and `plot_proportion_heatmap` called on data
frames you have not seen.
