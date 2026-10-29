# Hidden checks for XR01 (migration off defunct dplyr underscore verbs).
# Oracle: base-R ordering and per-group truncation.

xr01_oracle <- function(data, group, rank, n) {
  d <- data
  d$.i <- seq_len(nrow(d))
  d <- d[!is.na(d[[group]]) & !is.na(d[[rank]]), , drop = FALSE]
  d <- d[order(as.character(d[[group]]), -d[[rank]], d$.i), , drop = FALSE]
  keep <- ave(d$.i, as.character(d[[group]]), FUN = seq_along) <= n
  d <- d[keep, setdiff(names(d), ".i"), drop = FALSE]
  rownames(d) <- NULL
  d
}

xr01_data <- function(seed, n, groups, ties = TRUE) {
  with_seed(seed, {
    d <- data.frame(
      g = sample(groups, n, replace = TRUE),
      pts = sample(c(1:9, NA), n, replace = TRUE),
      who = sprintf("w%02d", seq_len(n)),
      flag = sample(c(TRUE, FALSE), n, replace = TRUE),
      stringsAsFactors = FALSE
    )
    d$g[c(4, 11)] <- NA
    d
  })
}

xr01_a <- xr01_data(891L, 50L, c("b", "a", "c"))
xr01_b <- xr01_data(892L, 14L, c("x", "y", "z", "w"))
xr01_num <- data.frame(k = c(2, 1, 2, 1, 2), v = c(0.5, 0.5, 1.5, 0.25, 1.5), tag = letters[1:5])

local({
  stopifnot(anyNA(xr01_a$pts), anyNA(xr01_a$g))
  # Ties must exist within the top rows of some group, otherwise the tie rule is untested.
  o <- xr01_oracle(xr01_a, "g", "pts", 3L)
  stopifnot(any(duplicated(o[c("g", "pts")])))
})

xr01_call <- function(d, g, r, ...) call_wrapped("top_by", d, g, r, ..., .prelude = lifecycle_prelude)

check("top_n_rows_per_group_match_the_oracle", {
  for (n in c(1L, 2L, 3L)) {
    got <- value_of(xr01_call(xr01_a, "g", "pts", n))
    want <- xr01_oracle(xr01_a, "g", "pts", n)
    testthat::expect_identical(as.data.frame(got), want)
  }
})

check("default_n_is_one", {
  got <- value_of(xr01_call(xr01_a, "g", "pts"))
  testthat::expect_identical(as.data.frame(got), xr01_oracle(xr01_a, "g", "pts", 1L))
})

check("ties_are_broken_by_original_row_order", {
  got <- value_of(xr01_call(xr01_num, "k", "v", 2L))
  want <- xr01_oracle(xr01_num, "k", "v", 2L)
  testthat::expect_identical(as.character(got$tag), as.character(want$tag))
  testthat::expect_identical(as.character(got$tag), c("b", "d", "c", "e"))
})

check("groups_smaller_than_n_keep_all_their_usable_rows", {
  got <- value_of(xr01_call(xr01_b, "g", "pts", 5L))
  testthat::expect_identical(as.data.frame(got), xr01_oracle(xr01_b, "g", "pts", 5L))
})

check("rows_with_missing_group_or_rank_are_ignored", {
  got <- value_of(xr01_call(xr01_a, "g", "pts", 100L))
  testthat::expect_false(anyNA(got$g))
  testthat::expect_false(anyNA(got$pts))
  testthat::expect_identical(nrow(got), sum(!is.na(xr01_a$g) & !is.na(xr01_a$pts)))
})

check("columns_order_and_types_are_preserved", {
  got <- value_of(xr01_call(xr01_a, "g", "pts", 2L))
  testthat::expect_identical(names(got), names(xr01_a))
  testthat::expect_identical(vapply(got, typeof, ""), vapply(xr01_a, typeof, ""))
  testthat::expect_false(inherits(got, "grouped_df"))
})

check("column_names_are_taken_from_the_arguments_even_when_they_clash_with_other_names", {
  d <- data.frame(group = c("u", "u", "v"), rank = c(3, 9, 4), n = c(1L, 2L, 3L))
  got <- value_of(xr01_call(d, "group", "rank", 1L))
  testthat::expect_identical(got$n, c(2L, 3L))
})

check("numeric_group_columns_work", {
  got <- value_of(xr01_call(xr01_num, "k", "v", 1L))
  testthat::expect_identical(as.data.frame(got), xr01_oracle(xr01_num, "k", "v", 1L))
})

check("invalid_n_is_an_error", {
  works <- xr01_call(xr01_a, "g", "pts")
  expect_stops(xr01_call(xr01_a, "g", "pts", 0L), works = works)
  expect_stops(xr01_call(xr01_a, "g", "pts", 1.5), works = works)
  expect_stops(xr01_call(xr01_a, "g", "pts", c(1L, 2L)), works = works)
  expect_stops(xr01_call(xr01_a, "g", "pts", NA_integer_), works = works)
})

check("runs_without_warnings_under_strict_lifecycle_settings", {
  res <- xr01_call(xr01_a, "g", "pts", 2L)
  value_of(res)
  expect_no_warnings(res)
})

check("input_is_not_modified", {
  d <- xr01_a
  res <- xr01_call(d, "g", "pts", 2L)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})
