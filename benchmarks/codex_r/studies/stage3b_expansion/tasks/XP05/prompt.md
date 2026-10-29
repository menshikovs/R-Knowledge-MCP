# XP05: Does the installed library satisfy these version requirements?

A deployment checklist lists package version requirements such as "dplyr >= 1.1.0". Before
deploying, the team wants to know which requirements the **installed** library satisfies. The
answer must come from the installed packages' own metadata (the library of the supplied
environment, the versions recorded in `renv.lock`), not from memory and not from the network. A
sample checklist is in `data/requirements_sample.csv`.

Write `solution.R` defining `check_requirements(req)`. Use only base R and packages installed in
the supplied environment; do not install anything and do not access the network.

## Behaviour

- `req` is a data frame with the character columns `package`, `op` and `version` (extra columns
  are ignored; zero rows are allowed). `op` is one of `>=`, `>`, `<=`, `<`, `==`, `!=`.
- Versions are compared **numerically, component by component**; components are separated by `.`
  or `-` (so `7.3-65` has components 7, 3, 65). `1.10.0` is newer than `1.9.0`. Tested requirements
  never differ from an installed version merely by extra trailing `.0` components (R's own
  comparison functions disagree about such pairs, so they are not used).
- Return a plain data frame with one row per row of `req`, in the same order, and the columns
  `package`, `op`, `required` (the requested version text), `installed` (the installed version
  text, `NA` if not installed) and `status`, all character: `"satisfied"`, `"unsatisfied"`, or
  `"not_installed"`.
- Stop with an error if `req` is not a data frame with the three columns, if any `op` is not one
  of the six operators, or if a `required` version is not a series of non-negative integers
  separated by `.` or `-` (for example `abc` or `1..2`). Missing values in these columns are
  errors too.

The file will be sourced into a fresh R session and `check_requirements` called on requirement
tables you have not seen.
