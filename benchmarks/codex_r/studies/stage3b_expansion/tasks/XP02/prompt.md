# XP02: Who depends on this package?

Before upgrading a package in a shared library, a maintainer wants to know which **installed**
packages declare a dependency on it. The answer must come from the installed packages' own
metadata (the library of the supplied environment, the versions recorded in `renv.lock`), not
from memory and not from the network. A sample is in `data/imports_sample.csv`.

Write `solution.R` defining `reverse_dependencies(pkg, types = c("Depends", "Imports", "LinkingTo"))`.
Use only base R and packages installed in the supplied environment; do not install anything and do
not access the network.

## Behaviour

- `pkg` is a single string naming an **installed** package; otherwise stop with an error. `types`
  is a non-empty subset of `"Depends"`, `"Imports"`, `"LinkingTo"`, `"Suggests"`, `"Enhances"`;
  otherwise stop with an error.
- Return the names of the installed packages (in any library of the environment, including the
  packages that ship with R) whose DESCRIPTION lists `pkg` in at least one of the fields in
  `types`. The match is on the **whole package name** (a package named `clipr` does not depend on
  `cli`); version constraints such as `(>= 1.2)` are ignored. Only **direct** declarations count
  (not dependencies of dependencies). `pkg` itself is never listed.
- The result is sorted in C-locale (byte) order, has no duplicates, and is `character(0)` when no
  installed package qualifies.

The file will be sourced into a fresh R session and `reverse_dependencies` called on packages and
field sets you have not seen.
