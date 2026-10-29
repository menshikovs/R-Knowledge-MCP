# Hidden checks for XR03 (edge cases of a trailing moving average).
# Oracle: explicit loop over positions with a window membership test.

xr03_oracle <- function(x, k) {
  n <- length(x)
  out <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    if (i >= k) {
      w <- x[(i - k + 1):i]
      if (!anyNA(w)) out[i] <- sum(w) / k
    }
  }
  out
}

xr03_x <- with_seed(911L, {
  v <- round(cumsum(stats::rnorm(60, 0.1, 2)) + 100, 3)
  v[c(7, 8, 30, 59)] <- NA
  v
})
xr03_int <- c(4L, 8L, 15L, 16L, 23L, 42L)

xr03_call <- function(x, k) call_wrapped("moving_average", x, k)

check("matches_the_oracle_for_several_window_lengths", {
  for (k in c(1L, 2L, 3L, 5L, 10L)) {
    got <- value_of(xr03_call(xr03_x, k))
    expect_close(ifelse(is.na(got), -999, got), ifelse(is.na(xr03_oracle(xr03_x, k)), -999, xr03_oracle(xr03_x, k)), tol = 1e-9)
    testthat::expect_identical(is.na(got), is.na(xr03_oracle(xr03_x, k)))
  }
})

check("result_has_the_same_length_as_the_input", {
  for (k in c(1L, 4L, 60L)) {
    testthat::expect_length(value_of(xr03_call(xr03_x, k)), length(xr03_x))
  }
})

check("incomplete_leading_windows_are_missing", {
  got <- value_of(xr03_call(xr03_x, 5L))
  testthat::expect_true(all(is.na(got[1:4])))
  testthat::expect_false(is.na(got[5]))
})

check("windows_with_a_missing_value_are_missing_not_skipped", {
  got <- value_of(xr03_call(xr03_x, 3L))
  # positions 7 and 8 are NA; windows ending at 7, 8, 9 and 10 contain one of them; 11 does not
  testthat::expect_true(all(is.na(got[c(7, 8, 9, 10)])))
  testthat::expect_false(is.na(got[11]))
  testthat::expect_true(all(is.na(got[c(30, 31, 32)])))
})

check("missing_values_do_not_contaminate_later_windows", {
  got <- value_of(xr03_call(xr03_x, 2L))
  testthat::expect_false(is.na(got[20]))
  testthat::expect_false(is.na(got[45]))
})

check("window_longer_than_the_input_gives_all_missing", {
  got <- value_of(xr03_call(c(1, 2, 3), 4L))
  testthat::expect_identical(got, rep(NA_real_, 3))
})

check("window_equal_to_the_input_length_gives_one_value_at_the_end", {
  got <- value_of(xr03_call(c(2, 4, 9), 3L))
  testthat::expect_identical(is.na(got), c(TRUE, TRUE, FALSE))
  expect_close(got[3], 5)
})

check("empty_input_gives_an_empty_numeric_vector", {
  got <- value_of(xr03_call(numeric(0), 3L))
  testthat::expect_identical(got, numeric(0))
  testthat::expect_identical(value_of(xr03_call(integer(0), 1L)), numeric(0))
})

check("integer_input_and_a_double_whole_k_are_accepted", {
  got <- value_of(xr03_call(xr03_int, 2))
  expect_close(got[-1], c(6, 11.5, 15.5, 19.5, 32.5))
  testthat::expect_true(is.double(got))
})

check("result_is_a_plain_double_vector_without_attributes", {
  got <- value_of(xr03_call(xr03_x, 3L))
  testthat::expect_true(is.double(got))
  testthat::expect_null(attributes(got))
  named <- c(a = 1, b = 2, c = 3)
  testthat::expect_null(attributes(value_of(xr03_call(named, 2L))))
})

check("invalid_arguments_are_errors", {
  works <- xr03_call(xr03_x, 3L)
  expect_stops(xr03_call(xr03_x, 0L), works = works)
  expect_stops(xr03_call(xr03_x, 2.5), works = works)
  expect_stops(xr03_call(xr03_x, c(2L, 3L)), works = works)
  expect_stops(xr03_call(xr03_x, NA_integer_), works = works)
  expect_stops(xr03_call(letters, 2L), works = works)
  expect_stops(xr03_call(list(1, 2), 2L), works = works)
})

check("input_is_not_modified", {
  x <- xr03_x
  res <- xr03_call(x, 4L)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], x)
})
