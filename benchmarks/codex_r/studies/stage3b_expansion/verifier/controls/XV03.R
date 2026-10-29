#### control: reference
# Trusted reference: dimension-based classification, tibble before data.frame.
object_kind <- function(x) {
  if (is.null(x)) return("NULL")
  if (is.function(x)) return("function")
  if (inherits(x, "tbl_df")) return("tibble")
  if (is.data.frame(x)) return("data.frame")
  if (is.factor(x)) return("factor")
  d <- dim(x)
  if (!is.null(d)) return(if (length(d) == 2L) "matrix" else "array")
  if (is.list(x) && !is.object(x)) return("list")
  if (is.atomic(x)) return("vector")
  "other"
}

#### control: alternate_inherits_based
# Alternate valid solution: uses inherits()/is.matrix() with explicit ordering.
object_kind <- function(x) {
  if (is.null(x)) "NULL"
  else if (is.function(x)) "function"
  else if (inherits(x, "tbl_df")) "tibble"
  else if (inherits(x, "data.frame")) "data.frame"
  else if (is.factor(x)) "factor"
  else if (is.matrix(x)) "matrix"
  else if (is.array(x)) "array"
  else if (typeof(x) == "list" && is.null(attr(x, "class"))) "list"
  else if (is.atomic(x)) "vector"
  else "other"
}

#### control: wrong_class_equals_matrix
# Plausible wrong strategy from R 3.x: class(x) == "matrix" has length 2 for matrices in R 4.x.
object_kind <- function(x) {
  if (is.null(x)) return("NULL")
  if (is.function(x)) return("function")
  if (inherits(x, "tbl_df")) return("tibble")
  if (is.data.frame(x)) return("data.frame")
  if (is.factor(x)) return("factor")
  if (class(x) == "matrix") return("matrix")
  if (is.array(x)) return("array")
  if (is.list(x) && !is.object(x)) return("list")
  if (is.atomic(x)) return("vector")
  "other"
}

#### control: wrong_array_before_matrix
# Plausible wrong strategy: inherits(x, "array") is TRUE for matrices, so matrices become arrays.
object_kind <- function(x) {
  if (is.null(x)) return("NULL")
  if (is.function(x)) return("function")
  if (inherits(x, "tbl_df")) return("tibble")
  if (is.data.frame(x)) return("data.frame")
  if (is.factor(x)) return("factor")
  if (inherits(x, "array")) return("array")
  if (is.list(x) && !is.object(x)) return("list")
  if (is.atomic(x)) return("vector")
  "other"
}

#### control: wrong_tibble_as_data_frame
# Plausible wrong strategy: a tibble is a data frame, so the tibble branch is never reached.
object_kind <- function(x) {
  if (is.null(x)) return("NULL")
  if (is.function(x)) return("function")
  if (is.data.frame(x)) return("data.frame")
  if (is.factor(x)) return("factor")
  d <- dim(x)
  if (!is.null(d)) return(if (length(d) == 2L) "matrix" else "array")
  if (is.list(x) && !is.object(x)) return("list")
  if (is.atomic(x)) return("vector")
  "other"
}

#### control: wrong_is_vector_for_atomic
# Plausible wrong strategy: is.vector() is FALSE for objects with attributes such as Dates and factors.
object_kind <- function(x) {
  if (is.null(x)) return("NULL")
  if (is.function(x)) return("function")
  if (inherits(x, "tbl_df")) return("tibble")
  if (is.data.frame(x)) return("data.frame")
  if (is.factor(x)) return("factor")
  d <- dim(x)
  if (!is.null(d)) return(if (length(d) == 2L) "matrix" else "array")
  if (is.list(x) && !is.object(x)) return("list")
  if (is.vector(x)) return("vector")
  "other"
}

#### control: wrong_data_frame_as_list
# Plausible wrong strategy: list test before the data frame test.
object_kind <- function(x) {
  if (is.null(x)) return("NULL")
  if (is.function(x)) return("function")
  if (is.list(x)) return("list")
  if (inherits(x, "tbl_df")) return("tibble")
  if (is.data.frame(x)) return("data.frame")
  if (is.factor(x)) return("factor")
  d <- dim(x)
  if (!is.null(d)) return(if (length(d) == 2L) "matrix" else "array")
  if (is.atomic(x)) return("vector")
  "other"
}

#### control: edge_errors_on_environments_and_formulas
# Boundary case: right except that environments and formulas error (expected: not fully correct).
# expect: fail
object_kind <- function(x) {
  if (is.null(x)) return("NULL")
  if (is.function(x)) return("function")
  if (inherits(x, "tbl_df")) return("tibble")
  if (is.data.frame(x)) return("data.frame")
  if (is.factor(x)) return("factor")
  d <- dim(x)
  if (!is.null(d)) return(if (length(d) == 2L) "matrix" else "array")
  if (is.list(x) && !is.object(x)) return("list")
  if (is.atomic(x)) return("vector")
  stop("unsupported object")
}

#### control: malformed_returns_class_vector
# Malformed submission: returns class(x), which has length 2 for matrices.
# expect: fail
object_kind <- function(x) class(x)

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
object_kind <- function(x) stop("todo")
