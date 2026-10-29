# XP01: Everything a package needs installed

Before building a minimal container, a team wants the full list of packages that must be present for
a given package to load. The container uses the package library of the supplied environment (the
versions recorded in `renv.lock`), so the answer must come from the **installed packages' own
metadata**, not from memory and not from the network. A sample of the metadata is in
`data/deps_sample.csv`.

Write `solution.R` defining `dependency_closure(pkg, types = c("Depends", "Imports", "LinkingTo"))`.
Use only base R and packages installed in the supplied environment; do not install anything and do
not access the network.

## Behaviour

- `pkg` is a single string naming an **installed** package; otherwise stop with an error. `types`
  is a non-empty subset of `"Depends"`, `"Imports"`, `"LinkingTo"`; otherwise stop with an error.
- Return a character vector of the names of all packages reachable from `pkg` through the
  dependency fields listed in `types`, **transitively** (the dependencies of the dependencies, and
  so on, following the same fields at every level), excluding `pkg` itself, `R`, and the packages
  that ship with R itself (those whose `Priority` is `base`). Version constraints in the fields,
  such as `(>= 1.2)`, are not part of the names.
- The result is sorted in C-locale (byte) order, has no duplicates, and is `character(0)` when
  there is nothing to report.

The file will be sourced into a fresh R session and `dependency_closure` called on packages and
field sets you have not seen.
