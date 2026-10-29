# Hidden checks for XR05 (parameter-grid evaluation; purrr::cross()/invoke_map() are deprecated).
# Oracle: explicit mixed-radix index arithmetic, independent of expand.grid().

xr05_oracle <- function(params, f) {
  sizes <- vapply(params, length, 1L)
  total <- prod(sizes)
  cols <- lapply(seq_along(params), function(j) {
    stride <- if (j == 1L) 1L else prod(sizes[seq_len(j - 1L)])
    idx <- ((seq_len(total) - 1L) %/% stride) %% sizes[j] + 1L
    params[[j]][idx]
  })
  names(cols) <- names(params)
  res <- vapply(seq_len(total), function(r) {
    args <- lapply(cols, function(cl) cl[[r]])
    as.numeric(do.call(f, args))
  }, numeric(1))
  out <- as.data.frame(cols, stringsAsFactors = FALSE, optional = TRUE)
  names(out) <- names(params)
  out$result <- res
  out
}

xr05_p1 <- list(a = c(1, 2, 3), b = c(10, 20))
xr05_f1 <- function(a, b) a * 100 + b
xr05_p2 <- list(label = c("xx", "yyyy"), shift = c(0.5, -1, 2), scale = c(1, 10))
xr05_f2 <- function(scale, shift, label) nchar(label) * scale + shift
xr05_p3 <- list(only = c(4, 9, 16))
xr05_f3 <- function(only) sqrt(only)
xr05_p4 <- list(g = c("m", "f"), n = c(2L, 3L, 5L))
xr05_f4 <- function(n, g) n + if (g == "m") 0.5 else 0.25

local({
  o <- xr05_oracle(xr05_p1, xr05_f1)
  stopifnot(identical(o$a, c(1, 2, 3, 1, 2, 3)), identical(o$b, c(10, 10, 10, 20, 20, 20)))
  stopifnot(identical(o$result, c(110, 210, 310, 120, 220, 320)))
  e <- expand.grid(xr05_p2, stringsAsFactors = FALSE)
  o2 <- xr05_oracle(xr05_p2, xr05_f2)
  stopifnot(identical(as.character(e$label), o2$label), all.equal(e$shift, o2$shift), all.equal(e$scale, o2$scale))
  stopifnot(o2$result[1] == 2 * 1 + 0.5)
})

xr05_call <- function(p, f) call_wrapped("evaluate_grid", p, f, .prelude = lifecycle_prelude)

xr05_same <- function(got, want) {
  testthat::expect_true(is.data.frame(got))
  testthat::expect_identical(names(got), names(want))
  testthat::expect_identical(nrow(got), nrow(want))
  for (nm in setdiff(names(want), "result")) {
    testthat::expect_identical(unname(got[[nm]]), unname(want[[nm]]), info = nm)
  }
  expect_close(got$result, want$result, tol = 1e-9)
}

check("all_combinations_with_the_first_parameter_varying_fastest", {
  xr05_same(as.data.frame(value_of(xr05_call(xr05_p1, xr05_f1))), xr05_oracle(xr05_p1, xr05_f1))
})

check("arguments_are_matched_by_name_not_position", {
  xr05_same(as.data.frame(value_of(xr05_call(xr05_p2, xr05_f2))), xr05_oracle(xr05_p2, xr05_f2))
  xr05_same(as.data.frame(value_of(xr05_call(xr05_p4, xr05_f4))), xr05_oracle(xr05_p4, xr05_f4))
})

check("character_parameters_stay_character_and_integers_stay_integer", {
  got <- as.data.frame(value_of(xr05_call(xr05_p4, xr05_f4)))
  testthat::expect_true(is.character(got$g))
  testthat::expect_true(is.integer(got$n))
  testthat::expect_false(any(vapply(got, is.factor, logical(1))))
})

check("single_parameter_grid", {
  xr05_same(as.data.frame(value_of(xr05_call(xr05_p3, xr05_f3))), xr05_oracle(xr05_p3, xr05_f3))
})

check("columns_are_parameters_in_order_then_result", {
  got <- value_of(xr05_call(xr05_p2, xr05_f2))
  testthat::expect_identical(names(got), c("label", "shift", "scale", "result"))
  testthat::expect_true(is.numeric(got$result))
})

check("row_names_are_sequential_and_result_is_a_plain_data_frame", {
  got <- value_of(xr05_call(xr05_p1, xr05_f1))
  testthat::expect_identical(rownames(got), as.character(seq_len(nrow(got))))
  testthat::expect_false(inherits(got, "tbl_df"))
  testthat::expect_true(is.null(attr(got$result, "names")))
})

check("f_is_called_once_per_combination", {
  probe <- function() {
    n_calls <- 0L
    f <- function(a, b) { n_calls <<- n_calls + 1L; a + b }
    fn <- get("evaluate_grid", envir = globalenv(), mode = "function")
    out <- fn(list(a = 1:3, b = c(0.5, 1.5)), f)
    list(nrow = nrow(out), n_calls = n_calls)
  }
  environment(probe) <- globalenv()
  got <- value_of(call_candidate(probe))
  testthat::expect_identical(got$nrow, 6L)
  testthat::expect_identical(got$n_calls, 6L)
})

check("invalid_inputs_are_errors", {
  works <- xr05_call(xr05_p1, xr05_f1)
  expect_stops(xr05_call(list(1:3), xr05_f3), works = works)
  expect_stops(xr05_call(list(a = 1:3, a = 4:5), xr05_f1), works = works)
  expect_stops(xr05_call(list(), xr05_f1), works = works)
  expect_stops(xr05_call(list(a = numeric(0), b = 1), xr05_f1), works = works)
  expect_stops(xr05_call(xr05_p1, "sum"), works = works)
  expect_stops(xr05_call(xr05_p1, function(a, b) c(a, b)), works = works)
  expect_stops(xr05_call(xr05_p1, function(a, b) "text"), works = works)
})

check("runs_without_deprecation_or_other_warnings", {
  res <- xr05_call(xr05_p1, xr05_f1)
  value_of(res)
  expect_no_warnings(res)
})

check("params_are_not_modified", {
  p <- xr05_p2
  res <- xr05_call(p, xr05_f2)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], p)
})
