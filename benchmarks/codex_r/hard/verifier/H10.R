# Hidden behavioral checks for H10 (Rubin's rules pooling).

# Independent oracle. It uses R's two-pass long-double mean() and a floor-based
# power-of-two scale (the reference uses a different centering and scale choice).
h10_oracle <- function(q, u, conf = 0.95, method = "rubin1987", nu = NULL) {
  m <- length(q)
  qbar <- mean(q)
  d <- q - qbar
  top <- max(abs(d), u)
  k <- if (top > 0) max(floor(log2(top)), -1074) else 0
  ds <- d / 2^k
  us <- u / 2^k
  w <- sum(us * us) / m
  b <- sum(ds * ds) / (m - 1)
  tt <- w + (m + 1) / m * b
  riv <- if (w > 0) (m + 1) / m * b / w else if (b > 0) Inf else 0
  lambda <- if (tt > 0) (m + 1) / m * b / tt else 0
  df <- if (b > 0) (m - 1) / lambda^2 else Inf
  if (method == "barnard_rubin1999") {
    obs <- nu * (nu + 1) * (1 - lambda) / (nu + 3)
    df <- if (is.finite(df)) 1 / (1 / df + 1 / obs) else obs
  }
  fmi <- if (tt == 0) 0 else if (w == 0) 1 else (riv + 2 / (df + 3)) / (riv + 1)
  se <- sqrt(tt) * 2^k
  half <- if (df > 0) stats::qt(1 - (1 - conf) / 2, df) * se else NA_real_
  list(estimate = qbar, std_error = se, df = df, ci_lower = qbar - half, ci_upper = qbar + half,
       within_var = w * 2^k * 2^k, between_var = b * 2^k * 2^k, total_var = tt * 2^k * 2^k,
       riv = riv, lambda = lambda, fmi = fmi, m = as.integer(m), method = method,
       conf_level = conf)
}

# Validate the oracle analytically before it judges anything (m = 2, q = 1, 3, se = 1).
local({
  r <- h10_oracle(c(1, 3), c(1, 1))
  stopifnot(r$estimate == 2, r$within_var == 1, r$between_var == 2, r$total_var == 4,
            r$std_error == 2, r$lambda == 0.75, r$riv == 3,
            abs(r$df - 16 / 9) < 1e-15, abs(r$fmi - 147 / 172) < 1e-15,
            abs(r$ci_upper - (2 + 2 * stats::qt(0.975, 16 / 9))) < 1e-12)
  br <- h10_oracle(c(1, 3), c(1, 1), method = "barnard_rubin1999", nu = 10)
  stopifnot(abs(br$df - 880 / 911) < 1e-15, abs(br$fmi - 12661 / 14452) < 1e-15)
})

h10_fields <- c("estimate", "std_error", "df", "ci_lower", "ci_upper", "within_var",
                "between_var", "total_var", "riv", "lambda", "fmi", "m", "method", "conf_level")
h10_accurate <- c("estimate", "std_error", "df", "ci_lower", "ci_upper", "riv", "lambda", "fmi")

expect_close <- function(actual, expected, label, tolerance = 1e-10) {
  testthat::expect_length(actual, 1L)
  if (is.na(expected)) {
    testthat::expect_true(is.na(actual), info = label)
  } else if (is.infinite(expected) || expected == 0) {
    testthat::expect_identical(as.double(actual), expected, info = label)
  } else {
    testthat::expect_true(is.finite(actual), info = label)
    relative <- abs(actual - expected) / abs(expected)
    if (!(relative <= tolerance)) {
      stop(sprintf("%s: got %.17g, expected %.17g (relative error %.3g)", label, actual,
                   expected, relative))
    }
  }
}

expect_pooled <- function(result, expected, fields = h10_fields) {
  testthat::expect_type(result, "list")
  testthat::expect_identical(names(result), h10_fields)
  for (field in intersect(fields, h10_accurate)) {
    expect_close(result[[field]], expected[[field]], field)
  }
  for (field in intersect(fields, c("within_var", "between_var", "total_var"))) {
    expect_close(result[[field]], expected[[field]], field)
  }
  testthat::expect_identical(result$m, expected$m)
  testthat::expect_identical(result$method, expected$method)
  testthat::expect_identical(result$conf_level, as.double(expected$conf_level))
}

h10_case <- function(q, u, conf = 0.95, method = "rubin1987", nu = NULL, fields = h10_fields) {
  result <- if (method == "rubin1987" && is.null(nu)) {
    call_candidate("pool_estimates", q, u, conf, method)
  } else {
    call_candidate("pool_estimates", q, u, conf, method, nu)
  }
  expect_no_candidate_warnings(result)
  value <- value_of(result)
  expect_pooled(value, h10_oracle(q, u, conf, method, nu), fields)
  value
}

h10_q20 <- 3 + ((1:20 * 7919) %% 13) / 10
h10_u20 <- 0.5 + ((1:20 * 104729) %% 7) / 20

check("two_imputations_match_analytic_rubin_values", {
  r <- h10_case(c(1, 3), c(1, 1))
  expect_close(r$df, 16 / 9, "df")
  expect_close(r$fmi, 147 / 172, "fmi")
  expect_close(r$ci_lower, 2 - 2 * stats::qt(0.975, 16 / 9), "ci_lower")
})

check("two_imputations_match_analytic_barnard_rubin_values", {
  r <- h10_case(c(1, 3), c(1, 1), method = "barnard_rubin1999", nu = 10)
  expect_close(r$df, 880 / 911, "df")
  expect_close(r$fmi, 12661 / 14452, "fmi")
})

check("twenty_imputations_match_oracle_for_both_methods", {
  h10_case(h10_q20, h10_u20)
  h10_case(h10_q20, h10_u20, method = "barnard_rubin1999", nu = 57)
})

check("default_method_is_rubin1987", {
  result <- call_candidate("pool_estimates", h10_q20, h10_u20)
  expect_pooled(value_of(result), h10_oracle(h10_q20, h10_u20))
})

check("identical_estimates_have_zero_between_variance", {
  r <- h10_case(rep(1.5, 6), c(0.2, 0.3, 0.25, 0.2, 0.3, 0.25))
  testthat::expect_identical(r$df, Inf)
  expect_close(r$ci_upper, 1.5 + stats::qnorm(0.975) * r$std_error, "ci_upper")
  br <- h10_case(rep(1.5, 6), c(0.2, 0.3, 0.25, 0.2, 0.3, 0.25), method = "barnard_rubin1999", nu = 40)
  expect_close(br$df, 41 / 43 * 40, "df")
})

check("zero_total_variance_collapses_the_interval", {
  r <- h10_case(rep(-2.25, 3), c(0, 0, 0))
  testthat::expect_identical(c(r$std_error, r$ci_lower, r$ci_upper), c(0, -2.25, -2.25))
  br <- h10_case(rep(-2.25, 3), c(0, 0, 0), method = "barnard_rubin1999", nu = 5)
  testthat::expect_identical(c(br$riv, br$lambda, br$fmi), c(0, 0, 0))
})

check("zero_within_variance_limits", {
  r <- h10_case(c(1, 2, 4), c(0, 0, 0))
  testthat::expect_identical(c(r$df, r$lambda, r$riv, r$fmi), c(2, 1, Inf, 1))
  br <- h10_case(c(1, 2, 4), c(0, 0, 0), method = "barnard_rubin1999", nu = 12)
  testthat::expect_identical(br$df, 0)
  testthat::expect_true(is.na(br$ci_lower) && is.na(br$ci_upper))
})

check("confidence_levels_090_and_099", {
  h10_case(h10_q20, h10_u20, conf = 0.90)
  h10_case(h10_q20[1:4], h10_u20[1:4], conf = 0.99, method = "barnard_rubin1999", nu = 8)
})

check("interval_uses_student_t_not_normal", {
  r <- h10_case(c(10, 14, 11), c(1, 1.5, 1.2))
  width <- (r$ci_upper - r$ci_lower) / 2
  expect_close(width, stats::qt(0.975, r$df) * r$std_error, "half_width")
})

check("between_variance_uses_m_minus_one", {
  r <- h10_case(c(2, 4, 9), c(1, 1, 1))
  expect_close(r$between_var, 13, "between_var")
  expect_close(r$total_var, 1 + 4 / 3 * 13, "total_var")
})

check("tiny_standard_errors_whose_variances_underflow", {
  q <- c(1, 2, 3, 2.5) * 1e-170
  u <- c(1, 2, 1.5, 1) * 1e-170
  h10_case(q, u, fields = h10_accurate)
  h10_case(q, u, method = "barnard_rubin1999", nu = 30, fields = h10_accurate)
})

check("huge_standard_errors_whose_variances_overflow", {
  q <- c(1, 2, 3, 4) * 1e200
  u <- c(3, 1, 2, 2) * 1e200
  h10_case(q, u, fields = h10_accurate)
  h10_case(q, u, conf = 0.9, method = "barnard_rubin1999", nu = 30, fields = h10_accurate)
})

check("estimates_near_the_largest_double", {
  r <- h10_case(c(1.0, 1.1, 1.05) * 1e308, c(1, 2, 1) * 1e305, fields = h10_accurate)
  testthat::expect_true(is.finite(r$ci_upper))
})

check("invalid_inputs_signal_pool_input_error", {
  bad <- list(
    list(1, 1),
    list(c(1, 2), c(1, 2, 3)),
    list(c(1, NA), c(1, 1)),
    list(c(1, Inf), c(1, 1)),
    list(c(1, 2), c(1, -0.1)),
    list(c("1", "2"), c(1, 1)),
    list(c(1, 2), c(1, 1), 1),
    list(c(1, 2), c(1, 1), c(0.9, 0.95)),
    list(c(1, 2), c(1, 1), 0.95, "rubin"),
    list(c(1, 2), c(1, 1), 0.95, "barnard_rubin1999"),
    list(c(1, 2), c(1, 1), 0.95, "barnard_rubin1999", -3),
    list(c(1, 2), c(1, 1), 0.95, "barnard_rubin1999", Inf),
    list(c(1, 2), c(1, 1), 0.95, "rubin1987", 10)
  )
  for (arguments in bad) {
    expect_candidate_error(do.call(call_candidate, c(list("pool_estimates"), arguments)),
                           "pool_input_error")
  }
})

check("result_structure_and_types", {
  r <- value_of(call_candidate("pool_estimates", c(1, 2, 4), c(0.5, 0.4, 0.6), 0.9))
  testthat::expect_identical(names(r), h10_fields)
  for (field in setdiff(h10_fields, c("m", "method"))) {
    testthat::expect_type(r[[field]], "double")
    testthat::expect_length(r[[field]], 1L)
  }
  testthat::expect_identical(r$m, 3L)
  testthat::expect_identical(r$method, "rubin1987")
})

check("inputs_not_modified_and_no_warnings", {
  q <- c(a = 1, b = 2.5, c = 2)
  u <- c(0.3, 0.2, 0.4)
  result <- call_candidate("pool_estimates", q, u, 0.95, "barnard_rubin1999", 20)
  value_of(result)
  expect_no_candidate_warnings(result)
  testthat::expect_identical(result$args_after[[1]], q)
  testthat::expect_identical(result$args_after[[2]], u)
})

check("huge_complete_df_approaches_rubin1987", {
  br <- h10_case(h10_q20, h10_u20, method = "barnard_rubin1999", nu = 1e15)
  rubin <- h10_oracle(h10_q20, h10_u20)
  expect_close(br$df, rubin$df, "df", tolerance = 1e-6)
})

check("imputation_order_does_not_matter", {
  order <- c(20, 3, 17, 1, 9, 12, 5, 14, 7, 2, 19, 10, 4, 16, 8, 11, 6, 18, 13, 15)
  a <- value_of(call_candidate("pool_estimates", h10_q20, h10_u20, 0.95, "barnard_rubin1999", 25))
  b <- value_of(call_candidate("pool_estimates", h10_q20[order], h10_u20[order], 0.95,
                               "barnard_rubin1999", 25))
  for (field in h10_accurate) expect_close(b[[field]], a[[field]], field, tolerance = 1e-12)
})
