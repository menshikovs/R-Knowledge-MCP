# Hidden checks for XR02 (paired t-test; the formula interface with paired = TRUE is an error in R >= 4.4).
# Oracle: closed-form paired t statistics from the differences; stats::t.test is used only to
# cross-check the oracle at load time.

xr02_oracle <- function(df) {
  ok <- !is.na(df$before) & !is.na(df$after)
  d <- df$after[ok] - df$before[ok]
  n <- length(d)
  m <- sum(d) / n
  s <- sqrt(sum((d - m)^2) / (n - 1))
  se <- s / sqrt(n)
  t <- m / se
  dfree <- n - 1
  q <- stats::qt(0.975, dfree)
  list(n = n, mean_difference = m, sd_difference = s, statistic = t, df = dfree,
       p_value = 2 * stats::pt(-abs(t), dfree), conf_low = m - q * se, conf_high = m + q * se)
}

xr02_data <- function(seed, n, effect, sd_noise = 5, na = 0.1) {
  with_seed(seed, {
    before <- round(stats::rnorm(n, 100, 15), 2)
    after <- round(before + effect + stats::rnorm(n, 0, sd_noise), 2)
    d <- data.frame(id = seq_len(n), before = before, after = after)
    d$before[stats::runif(n) < na] <- NA
    d$after[stats::runif(n) < na] <- NA
    d$before[2] <- NA
    d$after[5] <- NA
    d[sample.int(n), ]
  })
}

xr02_a <- xr02_data(901L, 30L, 3)
xr02_b <- xr02_data(902L, 12L, -6, sd_noise = 8, na = 0.2)

local({
  for (d in list(xr02_a, xr02_b)) {
    o <- xr02_oracle(d)
    tt <- stats::t.test(d$after, d$before, paired = TRUE)
    stopifnot(isTRUE(all.equal(o$statistic, unname(tt$statistic))),
              isTRUE(all.equal(o$p_value, tt$p.value)),
              isTRUE(all.equal(c(o$conf_low, o$conf_high), as.numeric(tt$conf.int))),
              any(is.na(d$before)) || any(is.na(d$after)))
  }
  # Unpaired and paired analyses must differ, otherwise the pairing is untested.
  d <- xr02_a
  u <- stats::t.test(d$after, d$before)
  stopifnot(abs(u$p.value - xr02_oracle(d)$p_value) > 1e-3)
})

xr02_call <- function(d) call_wrapped("paired_difference", d, .prelude = lifecycle_prelude)

xr02_fields <- c("n", "mean_difference", "sd_difference", "statistic", "df", "p_value", "conf_low", "conf_high")

check("returns_exactly_the_documented_elements", {
  got <- value_of(xr02_call(xr02_a))
  testthat::expect_identical(sort(names(got)), sort(xr02_fields))
})

check("sample_size_counts_complete_pairs_only", {
  for (d in list(xr02_a, xr02_b)) {
    got <- value_of(xr02_call(d))
    testthat::expect_identical(as.integer(got$n), as.integer(xr02_oracle(d)$n))
  }
})

check("mean_and_sd_of_differences_after_minus_before", {
  for (d in list(xr02_a, xr02_b)) {
    got <- value_of(xr02_call(d))
    o <- xr02_oracle(d)
    expect_close(got$mean_difference, o$mean_difference, tol = 1e-9)
    expect_close(got$sd_difference, o$sd_difference, tol = 1e-9)
  }
})

check("paired_t_statistic_df_and_p_value", {
  for (d in list(xr02_a, xr02_b)) {
    got <- value_of(xr02_call(d))
    o <- xr02_oracle(d)
    expect_close(got$statistic, o$statistic, tol = 1e-9)
    expect_close(got$df, o$df)
    expect_close(got$p_value, o$p_value, tol = 1e-9)
  }
})

check("confidence_interval_is_the_95_percent_t_interval", {
  for (d in list(xr02_a, xr02_b)) {
    got <- value_of(xr02_call(d))
    o <- xr02_oracle(d)
    expect_close(got$conf_low, o$conf_low, tol = 1e-9)
    expect_close(got$conf_high, o$conf_high, tol = 1e-9)
    testthat::expect_lt(got$conf_low, got$mean_difference)
    testthat::expect_gt(got$conf_high, got$mean_difference)
  }
})

check("values_are_plain_unnamed_numbers", {
  got <- value_of(xr02_call(xr02_a))
  for (nm in xr02_fields) {
    testthat::expect_true(is.numeric(got[[nm]]) && length(got[[nm]]) == 1L, info = nm)
    testthat::expect_null(names(got[[nm]]))
  }
})

check("row_order_does_not_matter", {
  d <- xr02_a[rev(seq_len(nrow(xr02_a))), ]
  a <- value_of(xr02_call(d))
  b <- value_of(xr02_call(xr02_a))
  expect_close(a$statistic, b$statistic, tol = 1e-9)
})

check("fewer_than_two_pairs_or_constant_differences_are_errors", {
  works <- xr02_call(xr02_a)
  one <- data.frame(id = 1:3, before = c(1, NA, NA), after = c(2, 3, NA))
  const <- data.frame(id = 1:4, before = c(1, 2, 3, 4), after = c(3, 4, 5, 6))
  expect_stops(xr02_call(one), works = works)
  expect_stops(xr02_call(const), works = works)
})

check("runs_without_warnings_or_errors_in_the_pinned_r", {
  res <- xr02_call(xr02_a)
  value_of(res)
  expect_no_warnings(res)
})

check("input_is_not_modified", {
  d <- xr02_a
  res <- xr02_call(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})
