# XP03: The oldest R that can run a package

A team must state the minimum R version for an application built on one installed package. A
package's own `Depends: R (>= x)` line is not enough: everything it needs must also run. The
answer must come from the installed packages' own metadata (the library of the supplied
environment, the versions recorded in `renv.lock`). A sample is in `data/r_requirements_sample.csv`.

Write `solution.R` defining `minimum_r_version(pkg)`. Use only base R and packages installed in the
supplied environment; do not install anything and do not access the network.

## Behaviour

- `pkg` is a single string naming an **installed** package; otherwise stop with an error.
- Consider `pkg` and every package reachable from it through `Depends`, `Imports` and `LinkingTo`
  (transitively; packages that ship with R itself, whose `Priority` is `base`, are not
  followed, and packages named but not installed are skipped).
- Each considered package may state a minimum R version in its `Depends` field as `R (>= x)`.
  Return the **highest** such `x`, comparing versions numerically component by component (`4.10`
  is newer than `4.9`), as a string with at least three numeric components separated by dots
  (`"4.1"` becomes `"4.1.0"`; a component separator `-` is treated as `.`).
- If no considered package states a minimum R version, return `NA_character_`.
- Only `>=` constraints in `Depends` count. Do not modify any state.

The file will be sourced into a fresh R session and `minimum_r_version` called on packages you have
not seen.
