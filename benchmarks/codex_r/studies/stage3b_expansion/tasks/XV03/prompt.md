# XV03: Classifying objects the way R 4.x does

A data-validation helper must report what kind of object a user passed. A sample of objects and the
expected kind is in `data/examples.csv` (columns `construction`, `kind`). The helper runs under the
R version recorded in `renv.lock` (R 4.x), where some old idioms no longer behave as they did in
R 3.x.

Write `solution.R` defining `object_kind(x)`, which returns **one string** describing `x`:

| kind | when |
| --- | --- |
| `"NULL"` | `x` is `NULL` |
| `"function"` | `x` is a function (closure or primitive) |
| `"tibble"` | `x` is a tibble (class `tbl_df`) |
| `"data.frame"` | `x` is a data frame that is not a tibble |
| `"matrix"` | `x` has exactly two dimensions (any element type, including zero rows or columns) and is not a data frame |
| `"array"` | `x` is an array that is not a matrix (one dimension, or three or more) |
| `"factor"` | `x` is a factor |
| `"list"` | `x` is a plain list (not a data frame) |
| `"vector"` | anything else that is an atomic vector (including dates and other classed vectors) |
| `"other"` | everything else (environments, formulas, S4 objects, ...) |

The checks are exclusive and are applied in the order above (a tibble is a tibble, not a data
frame; a data frame is not a list). The function must never raise an error or a warning for any
input and must always return a single string. Use only base R and packages installed in the
supplied environment; do not install anything.

The file will be sourced into a fresh R session and `object_kind` called on objects you have not
seen.
