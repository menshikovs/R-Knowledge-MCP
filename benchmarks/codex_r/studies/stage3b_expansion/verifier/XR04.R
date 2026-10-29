# Hidden checks for XR04 (reshaping with repeated measurements; spread() errors on duplicates).
# Oracle: base-R loops over sorted ids and keys.

xr04_oracle <- function(df) {
  ids <- sort(unique(df$id))
  keys <- sort(unique(as.character(df$key)), method = "radix")
  cells <- lapply(keys, function(k) vapply(ids, function(i) {
    v <- df$value[df$id == i & as.character(df$key) == k]
    v <- v[!is.na(v)]
    if (length(v)) sum(v) / length(v) else NA_real_
  }, numeric(1)))
  names(cells) <- keys
  out <- data.frame(id = ids, cells, check.names = FALSE, stringsAsFactors = FALSE)
  names(out) <- c("id", keys)
  out
}

xr04_data <- function(seed, ids, keys, n, dup = 0.3, na = 0.15, chr_ids = FALSE) {
  with_seed(seed, {
    d <- data.frame(id = sample(ids, n, replace = TRUE), key = sample(keys, n, replace = TRUE),
                    stringsAsFactors = FALSE)
    d <- rbind(d, d[sample.int(nrow(d), ceiling(dup * n), replace = TRUE), ])
    d$value <- round(stats::rnorm(nrow(d), 50, 10), 3)
    d$value[stats::runif(nrow(d)) < na] <- NA
    d[sample.int(nrow(d)), ]
  })
}

xr04_a <- xr04_data(921L, c(3L, 1L, 12L, 7L, 25L, 10L), c("weight", "height", "bp sys", "2nd visit"), 30L)
xr04_b <- xr04_data(922L, c("u2", "u10", "a1", "b7"), c("x", "Y", "z1"), 14L)
xr04_allna <- data.frame(id = c(1L, 1L, 2L, 3L), key = c("a", "a", "b", "a"), value = c(NA, NA, 4, 6))

local({
  for (d in list(xr04_a, xr04_b)) {
    stopifnot(anyDuplicated(d[c("id", "key")]) > 0L, anyNA(d$value))
  }
  stopifnot(identical(names(xr04_oracle(xr04_b)), c("id", "Y", "x", "z1")),
            identical(sort(c("x", "Y", "z1"), method = "radix"), c("Y", "x", "z1")))
})

xr04_call <- function(d) call_wrapped("wide_means", d, .prelude = lifecycle_prelude)

xr04_same <- function(got, want) {
  testthat::expect_identical(names(got), names(want))
  testthat::expect_identical(got$id, want$id)
  for (nm in setdiff(names(want), "id")) {
    testthat::expect_identical(is.na(got[[nm]]), is.na(want[[nm]]), info = nm)
    expect_close(got[[nm]][!is.na(got[[nm]])], want[[nm]][!is.na(want[[nm]])], tol = 1e-9, info = nm)
  }
}

check("repeated_measurements_are_averaged_ignoring_missing_values", {
  for (d in list(xr04_a, xr04_b)) {
    xr04_same(as.data.frame(value_of(xr04_call(d))), xr04_oracle(d))
  }
})

check("rows_are_sorted_by_id_in_its_own_type", {
  got <- as.data.frame(value_of(xr04_call(xr04_a)))
  testthat::expect_identical(got$id, c(1L, 3L, 7L, 10L, 12L, 25L))
  got2 <- as.data.frame(value_of(xr04_call(xr04_b)))
  testthat::expect_identical(got2$id, c("a1", "b7", "u10", "u2"))
})

check("key_columns_are_sorted_c_locale_and_named_exactly", {
  got <- as.data.frame(value_of(xr04_call(xr04_b)))
  testthat::expect_identical(names(got), c("id", "Y", "x", "z1"))
  got1 <- as.data.frame(value_of(xr04_call(xr04_a)))
  testthat::expect_identical(names(got1), c("id", "2nd visit", "bp sys", "height", "weight"))
})

check("ids_with_only_missing_values_still_appear", {
  got <- as.data.frame(value_of(xr04_call(xr04_allna)))
  testthat::expect_identical(got$id, 1:3)
  testthat::expect_true(is.na(got$a[1]))
  expect_close(got$a[3], 6)
  testthat::expect_true(is.na(got$b[1]) && is.na(got$b[3]))
  expect_close(got$b[2], 4)
})

check("missing_combinations_are_NA", {
  got <- as.data.frame(value_of(xr04_call(xr04_allna)))
  testthat::expect_true(is.na(got$a[2]))
})

check("id_keeps_its_type", {
  testthat::expect_true(is.integer(as.data.frame(value_of(xr04_call(xr04_a)))$id))
  testthat::expect_true(is.character(as.data.frame(value_of(xr04_call(xr04_b)))$id))
})

check("empty_input_gives_an_id_only_zero_row_frame", {
  empty <- data.frame(id = integer(), key = character(), value = numeric())
  got <- as.data.frame(value_of(xr04_call(empty)))
  testthat::expect_identical(names(got), "id")
  testthat::expect_identical(nrow(got), 0L)
})

check("result_is_a_plain_data_frame_without_list_columns", {
  got <- value_of(xr04_call(xr04_a))
  testthat::expect_true(is.data.frame(got))
  testthat::expect_false(any(vapply(got, is.list, logical(1))))
  testthat::expect_false(inherits(got, "grouped_df"))
  testthat::expect_true(all(vapply(got[-1], is.double, logical(1))))
})

check("runs_without_warnings_or_errors", {
  res <- xr04_call(xr04_a)
  value_of(res)
  expect_no_warnings(res)
})

check("input_is_not_modified", {
  d <- xr04_a
  res <- xr04_call(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})
