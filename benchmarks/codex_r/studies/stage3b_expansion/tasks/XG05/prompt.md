# XG05: Individual trajectories with a mean trajectory

Participants were scored repeatedly over several weeks. A sample is in `data/trajectories.csv`
(columns `subject`, `week`, `score`; one row per participant and week, in no particular order).

Write `solution.R` defining `plot_trajectories(data)`, which returns a **ggplot2** plot object (do
not print or save anything). `data` is a data frame with columns `subject` (character or numeric
identifier), `week` (integer) and `score` (numeric, sometimes missing). Use only packages
installed in the supplied environment (see `renv.lock`).

## What the plot must show

- **One thin line per participant** joining that participant's observed scores in order of
  `week` (earliest week first), whatever the order of the rows in `data`. Each participant is one
  line; lines of different participants are never connected.
- **One thick line** for the **mean score across participants at each week**, ignoring missing
  scores. A week where nobody has a score has no point on the mean line. The mean line's width is
  at least 1.5 times that of the participant lines.
- Axis titles exactly `Week` (horizontal) and `Score` (vertical).

## Rules

- Missing scores are not plotted. Participants with no non-missing score do not appear.
- Do not modify `data`; the plot must not depend on row order.
- The plot is inspected through `ggplot2::ggplot_build()` (groups, positions and values in the
  layer data, line widths, labels); rendering is not required.

The file will be sourced into a fresh R session and `plot_trajectories` called on data frames you
have not seen.
