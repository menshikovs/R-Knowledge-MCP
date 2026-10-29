# Hidden checks for XV01 (multi-row per-group summaries under a current dplyr).
# Oracle: base R split + stats::quantile(type = 7).

xv01_oracle <- function(df, group, value, probs) {
  g <- as.character(df[[group]])
  v <- df[[value]]
  keep <- !is.na(g) & !is.na(v)
  g <- g[keep]
  v <- v[keep]
  out <- lapply(sort(unique(g)), function(k) {
    data.frame(k, probs, unname(stats::quantile(v[g == k], probs, type = 7)), stringsAsFactors = FALSE)
  })
  res <- do.call(rbind, out)
  names(res) <- c(group, "prob", "value")
  res
}

xv01_data <- function(seed, n, groups, na_rate = 0.1, empty_group = NULL) {
  with_seed(seed, {
    d <- data.frame(
      grp = sample(groups, n, replace = TRUE),
      amt = round(stats::rlnorm(n, 3, 0.8), 3),
      stringsAsFactors = FALSE
    )
    d$amt[stats::runif(n) < na_rate] <- NA
    if (!is.null(empty_group)) d$amt[d$grp == empty_group] <- NA
    d
  })
}

xv01_a <- xv01_data(861L, 80L, c("a", "b", "c", "d"))
xv01_b <- xv01_data(862L, 50L, c("x", "y", "z"), empty_group = "z")
xv01_c <- xv01_a
xv01_c$grp[c(5, 17, 33)] <- NA
xv01_one <- data.frame(g = c("only", "only", "only"), v = c(2, 4, 9))

xv01_call <- function(d, g, v, ...) call_wrapped("group_quantiles", d, g, v, ..., .prelude = lifecycle_prelude)

local({
  stopifnot(anyNA(xv01_b$amt), all(is.na(xv01_b$amt[xv01_b$grp == "z"])),
            nrow(xv01_oracle(xv01_b, "grp", "amt", c(.5))) == 2)
})

check("quartiles_per_group_match_stats_quantile_type_7", {
  got <- value_of(xv01_call(xv01_a, "grp", "amt"))
  want <- xv01_oracle(xv01_a, "grp", "amt", c(0.25, 0.5, 0.75))
  testthat::expect_identical(names(got), c("grp", "prob", "value"))
  testthat::expect_identical(as.character(got$grp), want$grp)
  expect_close(got$prob, want$prob)
  expect_close(got$value, want$value, tol = 1e-9)
})

check("output_is_a_plain_data_frame", {
  got <- value_of(xv01_call(xv01_a, "grp", "amt"))
  testthat::expect_true(is.data.frame(got))
  testthat::expect_false(inherits(got, "grouped_df"))
})

check("column_names_follow_the_group_and_value_arguments", {
  got <- value_of(xv01_call(xv01_one, "g", "v", probs = c(0.5)))
  testthat::expect_identical(names(got), c("g", "prob", "value"))
  expect_close(got$value, 4)
})

check("probs_are_honoured_in_the_given_order", {
  p <- c(0.9, 0.1, 0.5)
  got <- value_of(xv01_call(xv01_a, "grp", "amt", probs = p))
  want <- xv01_oracle(xv01_a, "grp", "amt", p)
  expect_close(got$prob, want$prob)
  expect_close(got$value, want$value, tol = 1e-9)
})

check("missing_values_are_ignored_and_empty_groups_omitted", {
  got <- value_of(xv01_call(xv01_b, "grp", "amt"))
  want <- xv01_oracle(xv01_b, "grp", "amt", c(0.25, 0.5, 0.75))
  testthat::expect_identical(as.character(got$grp), want$grp)
  testthat::expect_false("z" %in% got$grp)
  expect_close(got$value, want$value, tol = 1e-9)
})

check("rows_with_a_missing_group_are_ignored", {
  got <- value_of(xv01_call(xv01_c, "grp", "amt"))
  want <- xv01_oracle(xv01_c, "grp", "amt", c(0.25, 0.5, 0.75))
  testthat::expect_identical(as.character(got$grp), want$grp)
  expect_close(got$value, want$value, tol = 1e-9)
})

check("groups_are_ordered_ascending_whatever_the_row_order", {
  d <- xv01_a[rev(seq_len(nrow(xv01_a))), ]
  got <- value_of(xv01_call(d, "grp", "amt"))
  testthat::expect_identical(unique(as.character(got$grp)), c("a", "b", "c", "d"))
})

check("invalid_probabilities_are_errors", {
  works <- xv01_call(xv01_a, "grp", "amt")
  expect_stops(xv01_call(xv01_a, "grp", "amt", probs = c(0.5, 1.5)), works = works)
  expect_stops(xv01_call(xv01_a, "grp", "amt", probs = c(0.5, NA)), works = works)
  expect_stops(xv01_call(xv01_a, "grp", "amt", probs = -0.1), works = works)
})

check("runs_without_any_warning_under_strict_lifecycle_settings", {
  res <- xv01_call(xv01_a, "grp", "amt")
  value_of(res)
  expect_no_warnings(res)
})

check("input_is_not_modified", {
  d <- xv01_a
  res <- xv01_call(d, "grp", "amt")
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})
