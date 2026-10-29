# XP04: Where did each installed package come from?

An audit asks which of the installed packages are base R, CRAN or Bioconductor, and for Bioconductor
packages the release they were installed from. The answer must come from the installed packages'
own metadata (the library of the supplied environment, the versions recorded in `renv.lock`), not
from memory and not from the network. A sample is in `data/origin_sample.csv`.

Write `solution.R` defining `package_origin(pkgs)`. Use only base R and packages installed in the
supplied environment; do not install anything and do not access the network.

## Behaviour

- `pkgs` is a character vector of package names with no missing values and at least one element;
  otherwise stop with an error. Names may repeat and may refer to packages that are not installed.
- Return a plain data frame with one row per element of `pkgs`, **in the same order**, and exactly
  the character columns `package`, `version`, `origin`, `bioc_release`:
  - `version`: the installed version (`NA` if not installed).
  - `origin`, by the first rule that applies:
    1. `"not_installed"`: the package is not installed;
    2. `"base"`: the package ships with R (its `Priority` is `base`);
    3. `"bioconductor"`: its `Repository` field starts with `Bioconductor` (or, when there is no
       `Repository` field, it has a `biocViews` field);
    4. `"cran"`: its `Repository` field is `CRAN` or `RSPM` (a Posit Package Manager snapshot of
       CRAN);
    5. `"unknown"` otherwise.
  - `bioc_release`: for `"bioconductor"` packages with a `Repository` of the form
    `Bioconductor <release>`, the release text (for example `3.22`); `NA` in every other case.
- Packages that ship with R's *recommended* set are not "base"; their `Repository` field decides.

The file will be sourced into a fresh R session and `package_origin` called on package sets you have
not seen.
