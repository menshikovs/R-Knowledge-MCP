# Hidden behavioral checks for H01 (dynamic weighted group summaries).

# Independent base-R oracle: no dplyr, rlang or vctrs, no data masks.
h01_key <- function(column) {
  if (is.factor(column)) return(ifelse(is.na(column), "\001", paste0("f", as.integer(column))))
  if (inherits(column, "Date")) column <- unclass(column)
  if (is.numeric(column)) return(ifelse(is.na(column), "\001", sprintf("n%.17g", column)))
  ifelse(is.na(column), "\001", paste0("s", enc2utf8(as.character(column))))
}

h01_oracle <- function(data, groups, measure, weight) {
  df <- as.data.frame(data, stringsAsFactors = FALSE, optional = TRUE)
  x <- df[[measure]]
  w <- df[[weight]]
  valid <- is.finite(x) & is.finite(w)
  if (length(groups)) {
    key <- do.call(paste, c(lapply(df[groups], h01_key), sep = "\r"))
    first <- !duplicated(key)
    keys <- df[first, groups, drop = FALSE]
    gid <- match(key, key[first])
  } else {
    keys <- data.frame(row.names = 1L)
    gid <- rep.int(1L, nrow(df))
  }
  stats <- lapply(seq_len(nrow(keys)), function(g) {
    rows <- which(gid == g & valid)
    ws <- sum(as.double(w[rows]))
    c(mean = if (ws > 0) sum(as.double(w[rows]) * as.double(x[rows])) / ws else NA_real_,
      n = length(rows), ws = ws)
  })
  out <- keys
  out[["weighted_mean"]] <- vapply(stats, `[[`, numeric(1), "mean")
  out[["n_valid"]] <- as.integer(vapply(stats, `[[`, numeric(1), "n"))
  out[["weight_sum"]] <- vapply(stats, `[[`, numeric(1), "ws")
  if (length(groups) && nrow(out) > 1L) {
    ord <- do.call(order, c(unname(as.list(keys)), list(na.last = TRUE, method = "radix")))
    out <- out[ord, , drop = FALSE]
  }
  rownames(out) <- NULL
  out
}

expect_summary <- function(result, expected) {
  testthat::expect_s3_class(result, "tbl_df")
  testthat::expect_false(inherits(result, "grouped_df"))
  testthat::expect_identical(names(result), names(expected))
  testthat::expect_identical(nrow(result), nrow(expected))
  for (column in setdiff(names(expected), c("weighted_mean", "n_valid", "weight_sum"))) {
    testthat::expect_identical(result[[column]], expected[[column]], info = column)
  }
  testthat::expect_type(result$weighted_mean, "double")
  testthat::expect_identical(is.na(result$weighted_mean), is.na(expected$weighted_mean))
  testthat::expect_false(any(is.nan(result$weighted_mean)))
  testthat::expect_equal(result$weighted_mean, expected$weighted_mean, tolerance = 1e-12)
  testthat::expect_identical(result$n_valid, expected$n_valid)
  testthat::expect_type(result$weight_sum, "double")
  testthat::expect_equal(result$weight_sum, expected$weight_sum, tolerance = 1e-12)
}

h01_basic <- function() {
  tibble::tibble(
    `store id` = c("S2", "S1", "S1", "S2", "S3", "S1", "S3", "s1", "S2"),
    `région` = c("Sud", "Nord", "Nord", NA, "Île", "Nord", "Île", "Nord", "Sud"),
    `sales (€)` = c(8, 10.5, NA, 4, 5, 9, Inf, 2, NaN),
    weight = c(1, 2, 1, 3, 1, 1.5, 2, 0.5, 4)
  )
}

h01_case <- function(data, groups, measure = "sales (€)", weight = "weight") {
  result <- call_candidate("dynamic_summary", data, groups, measure, weight)
  expect_no_candidate_warnings(result)
  expect_summary(value_of(result), h01_oracle(data, groups, measure, weight))
  result
}

check("two_non_syntactic_groups_match_oracle", {
  h01_case(h01_basic(), c("store id", "région"))
})

check("grouping_order_follows_argument_order", {
  h01_case(h01_basic(), c("région", "store id"))
})

check("c_locale_order_with_na_last", {
  data <- tibble::tibble(k = c("b", "B", "a", "é", "z", NA, "Z", "_"), v = 1:8, w = rep(1, 8))
  result <- value_of(call_candidate("dynamic_summary", data, "k", "v", "w"))
  testthat::expect_identical(result$k, c("B", "Z", "_", "a", "b", "z", "é", NA))
})

check("non_finite_measure_and_weight_rows_are_invalid", {
  data <- tibble::tibble(
    g = c("a", "a", "a", "a", "a", "b", "b"),
    x = c(1, NA, NaN, Inf, -Inf, 2, 3),
    w = c(2, 1, 1, 1, 1, Inf, 1)
  )
  result <- h01_case(data, "g", "x", "w")
  testthat::expect_identical(value_of(result)$n_valid, c(1L, 1L))
})

check("all_invalid_group_is_reported_with_na_mean", {
  data <- tibble::tibble(g = c("keep", "lost", "lost"), x = c(1, NA, Inf), w = c(1, 2, 3))
  result <- value_of(call_candidate("dynamic_summary", data, "g", "x", "w"))
  testthat::expect_identical(result$g, c("keep", "lost"))
  testthat::expect_identical(result$n_valid, c(1L, 0L))
  testthat::expect_identical(result$weight_sum, c(1, 0))
  testthat::expect_true(is.na(result$weighted_mean[2]) && !is.nan(result$weighted_mean[2]))
})

check("zero_weight_sum_gives_na_not_nan", {
  data <- tibble::tibble(g = c("z", "z", "y"), x = c(5, 7, 1), w = c(0, 0, 2))
  result <- value_of(call_candidate("dynamic_summary", data, "g", "x", "w"))
  testthat::expect_identical(result$g, c("y", "z"))
  testthat::expect_identical(result$n_valid, c(1L, 2L))
  testthat::expect_identical(result$weight_sum, c(2, 0))
  testthat::expect_true(is.na(result$weighted_mean[2]) && !is.nan(result$weighted_mean[2]))
})

check("negative_weight_is_rejected_even_without_measure", {
  data <- tibble::tibble(g = c("a", "b"), x = c(1, NA), w = c(1, -0.5))
  expect_candidate_error(
    call_candidate("dynamic_summary", data, "g", "x", "w"), "dynamic_summary_negative_weight"
  )
  finite_only <- tibble::tibble(g = c("a", "b"), x = c(1, 2), w = c(1, -Inf))
  h01_case(finite_only, "g", "x", "w")
})

check("bad_columns_signal_classed_errors", {
  data <- tibble::tibble(g = "a", x = 1, w = 1, label = "text")
  for (arguments in list(
    list(c("g", "missing"), "x", "w"),
    list(c("g", "g"), "x", "w"),
    list("g", "label", "w"),
    list("g", "x", "nope")
  )) {
    expect_candidate_error(
      do.call(call_candidate, c(list("dynamic_summary", data), arguments)),
      "dynamic_summary_bad_column"
    )
  }
})

check("special_column_names_are_literal", {
  data <- tibble::tibble(
    `.data` = c("p", "q", "p", "q", "p"),
    `.env` = c(1L, 1L, 2L, 2L, 1L),
    measure = c(1, 2, 3, 4, 5),
    weight = c(10, 20, 30, 40, 50),
    data = c(9, 9, 9, 9, 9),
    groups = c("x", "x", "y", "y", "x")
  )
  h01_case(data, c(".data", ".env"), measure = "weight", weight = "measure")
  h01_case(data, c("groups", "data"), measure = "measure", weight = "weight")
})

check("global_variables_do_not_leak_into_columns", {
  for (name in c("x", "w", "weight", "measure", "g")) {
    call_candidate("assign", name, -99, envir = globalenv())
  }
  data <- tibble::tibble(g = c("a", "a", "b"), x = c(1, 2, 3), w = c(1, 3, 1))
  h01_case(data, "g", "x", "w")
})

check("existing_grouping_is_ignored", {
  data <- dplyr::group_by(h01_basic(), weight)
  result <- h01_case(data, "store id")
  testthat::expect_false(inherits(value_of(result), "grouped_df"))
})

check("zero_grouping_columns_return_one_row", {
  h01_case(h01_basic(), character())
  empty <- h01_basic()[0, ]
  result <- value_of(call_candidate("dynamic_summary", empty, character(), "sales (€)", "weight"))
  testthat::expect_identical(names(result), c("weighted_mean", "n_valid", "weight_sum"))
  testthat::expect_identical(nrow(result), 1L)
  testthat::expect_identical(result$n_valid, 0L)
  testthat::expect_identical(result$weight_sum, 0)
  testthat::expect_true(is.na(result$weighted_mean) && !is.nan(result$weighted_mean))
})

check("empty_input_keeps_columns_and_types", {
  empty <- tibble::tibble(
    f = factor(character(), levels = c("b", "a")),
    d = as.Date(character()),
    x = double(),
    w = integer()
  )
  result <- value_of(call_candidate("dynamic_summary", empty, c("f", "d"), "x", "w"))
  testthat::expect_identical(nrow(result), 0L)
  testthat::expect_identical(names(result), c("f", "d", "weighted_mean", "n_valid", "weight_sum"))
  testthat::expect_identical(levels(result$f), c("b", "a"))
  testthat::expect_s3_class(result$d, "Date")
  testthat::expect_type(result$weighted_mean, "double")
  testthat::expect_type(result$n_valid, "integer")
  testthat::expect_type(result$weight_sum, "double")
})

check("factor_groups_sort_by_levels_and_omit_unused", {
  data <- tibble::tibble(
    f = factor(c("lo", "hi", "mid", "hi", NA), levels = c("mid", "hi", "lo", "unused")),
    x = c(1, 2, 3, 4, 5),
    w = c(1, 1, 1, 1, 1)
  )
  result <- h01_case(data, "f", "x", "w")
  testthat::expect_identical(as.character(value_of(result)$f), c("mid", "hi", "lo", NA))
})

check("date_logical_and_integer_keys_keep_types", {
  data <- tibble::tibble(
    day = as.Date(c("2026-01-02", "2025-12-31", "2026-01-02", NA)),
    flag = c(TRUE, FALSE, TRUE, NA),
    n = c(2L, 1L, 2L, 1L),
    x = c(1, 2, 3, 4),
    w = c(1, 2, 3, 4)
  )
  h01_case(data, c("day", "flag", "n"), "x", "w")
})

check("row_permutation_does_not_change_result", {
  data <- h01_basic()
  shuffled <- data[c(5, 3, 8, 1, 9, 7, 2, 6, 4), ]
  first <- value_of(call_candidate("dynamic_summary", data, c("store id", "région"), "sales (€)", "weight"))
  second <- value_of(call_candidate("dynamic_summary", shuffled, c("store id", "région"), "sales (€)", "weight"))
  testthat::expect_equal(as.data.frame(first), as.data.frame(second), tolerance = 1e-12)
})

check("integer_weights_sum_exactly_beyond_integer_range", {
  data <- tibble::tibble(
    g = c("a", "a", "a"),
    x = c(1L, 3L, 2L),
    w = c(.Machine$integer.max, .Machine$integer.max, 5L)
  )
  result <- h01_case(data, "g", "x", "w")
  testthat::expect_identical(value_of(result)$weight_sum, 2 * 2147483647 + 5)
})

check("input_is_not_modified", {
  data <- dplyr::group_by(h01_basic(), `store id`)
  attr(data, "note") <- "caller-owned"
  result <- call_candidate("dynamic_summary", data, c("région"), "sales (€)", "weight")
  value_of(result)
  testthat::expect_identical(result$args_after[[1]], data)
})
