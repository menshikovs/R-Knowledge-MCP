# Hidden checks for XA05 (ANCOVA with a slope-homogeneity decision rule).
#
# Independent oracle by normal-equation least squares (no lm/aov/anova): the parallel and separate
# slope models and the no-treatment model are fitted from explicit design matrices; F tests use
# residual-sum-of-squares differences; adjusted means evaluate the fitted coefficients.

xa05_rss <- function(X, y) {
  b <- solve(crossprod(X), crossprod(X, y))
  list(rss = sum((y - X %*% b)^2), beta = drop(b))
}

xa05_oracle <- function(df) {
  df <- df[stats::complete.cases(df[c("treatment", "baseline", "score")]), , drop = FALSE]
  tl <- sort(unique(as.character(df$treatment)))
  a <- length(tl)
  g <- match(as.character(df$treatment), tl)
  x <- df$baseline
  y <- df$score
  n <- length(y)
  dm <- vapply(2:a, function(i) as.numeric(g == i), numeric(n))
  dm <- matrix(dm, n, a - 1)
  m0 <- xa05_rss(cbind(1, x), y)
  m1 <- xa05_rss(cbind(1, dm, x), y)
  m2 <- xa05_rss(cbind(1, dm, x, dm * x), y)
  df_slope <- a - 1
  df2_slope <- n - 2 * a
  f_slope <- ((m1$rss - m2$rss) / df_slope) / (m2$rss / df2_slope)
  p_slope <- stats::pf(f_slope, df_slope, df2_slope, lower.tail = FALSE)
  homog <- p_slope >= 0.05
  f_trt <- ((m0$rss - m1$rss) / (a - 1)) / (m1$rss / (n - a - 1))
  xbar <- mean(x)
  sx <- stats::sd(x)
  b1 <- m1$beta
  adj <- vapply(seq_len(a), function(i) b1[1] + (if (i > 1) b1[i] else 0) + b1[a + 1] * xbar, 0)
  b2 <- m2$beta
  at <- c(minus_1sd = xbar - sx, mean = xbar, plus_1sd = xbar + sx)
  cond <- do.call(rbind, lapply(seq_len(a), function(i) {
    int <- b2[1] + (if (i > 1) b2[i] else 0)
    slp <- b2[a + 1] + (if (i > 1) b2[a + i] else 0)
    data.frame(treatment = tl[i], at = names(at), baseline = unname(at),
               fitted = unname(int + slp * at), stringsAsFactors = FALSE)
  }))
  list(
    slope_test = list(f_value = f_slope, df1 = df_slope, df2 = df2_slope, p_value = p_slope),
    slopes_homogeneous = homog, model = if (homog) "parallel" else "separate",
    treatment_test = if (homog) list(f_value = f_trt, df1 = a - 1, df2 = n - a - 1,
                                     p_value = stats::pf(f_trt, a - 1, n - a - 1, lower.tail = FALSE)),
    adjusted_means = if (homog) data.frame(treatment = tl, adjusted_mean = adj, stringsAsFactors = FALSE),
    conditional_means = if (!homog) cond,
    raw_means = unname(tapply(y, factor(g, seq_len(a)), mean)), adj_all = adj, cond_all = cond
  )
}

xa05_data <- function(seed, labels, n, slope, shift, sd = 3) {
  with_seed(seed, {
    parts <- lapply(seq_along(labels), function(i) {
      b <- round(stats::rnorm(n[i], 40, 8), 2)
      data.frame(treatment = labels[i], baseline = b,
                 score = round(5 + shift[i] + slope[i] * b + stats::rnorm(n[i], sd = sd), 3),
                 stringsAsFactors = FALSE)
    })
    d <- do.call(rbind, parts)
    d$participant_id <- sprintf("p%03d", sample.int(nrow(d)))
    d[sample.int(nrow(d)), c("participant_id", "treatment", "baseline", "score")]
  })
}

xa05_par <- xa05_data(603L, c("a", "b", "c"), c(12L, 9L, 15L), c(0.9, 0.9, 0.9), c(0, 4, 7))
xa05_het <- xa05_data(600L, c("x", "y", "z"), c(14L, 13L, 11L), c(0.3, 1.1, 1.8), c(0, -2, -6))
xa05_two <- xa05_data(604L, c("ctl", "trt"), c(16L, 19L), c(0.7, 0.7), c(0, 0.5), sd = 5)

local({
  p <- xa05_oracle(xa05_par)
  h <- xa05_oracle(xa05_het)
  # Decisions must sit well away from the 0.05 boundary so no platform noise can flip them.
  stopifnot(p$slope_test$p_value > 0.2, h$slope_test$p_value < 0.01,
            xa05_oracle(xa05_two)$slope_test$p_value > 0.2)
  d <- xa05_par
  d$treatment <- factor(d$treatment)
  full <- stats::lm(score ~ baseline + treatment, data = d)
  tab <- stats::anova(full)
  stopifnot(isTRUE(all.equal(tab[["F value"]][2], p$treatment_test$f_value, tolerance = 1e-8)))
  sep <- stats::lm(score ~ treatment * baseline, data = d)
  cmp <- stats::anova(full, sep)
  stopifnot(isTRUE(all.equal(cmp[["F"]][2], p$slope_test$f_value, tolerance = 1e-8)))
  pr <- stats::predict(full, data.frame(treatment = factor(c("a", "b", "c")), baseline = mean(d$baseline)))
  stopifnot(isTRUE(all.equal(unname(pr), p$adjusted_means$adjusted_mean, tolerance = 1e-8)))
  stopifnot(max(abs(p$adj_all - p$raw_means)) > 0.05)
})

xa05_run <- function(df) call_candidate("ancova_analysis", df)

xa05_expect_list <- function(got, want, label) {
  testthat::expect_true(is.list(got), info = label)
  for (nm in names(want)) {
    testthat::expect_equal(as.numeric(field(got, nm)), as.numeric(want[[nm]]), tolerance = 1e-6,
                           info = paste(label, nm))
  }
}

check("slope_homogeneity_test_matches_oracle_for_parallel_data", {
  xa05_expect_list(field(value_of(xa05_run(xa05_par)), "slope_test"),
                   xa05_oracle(xa05_par)$slope_test, "parallel")
})

check("slope_homogeneity_test_matches_oracle_for_heterogeneous_data", {
  xa05_expect_list(field(value_of(xa05_run(xa05_het)), "slope_test"),
                   xa05_oracle(xa05_het)$slope_test, "heterogeneous")
})

check("decision_flags_and_model_labels_follow_the_005_rule", {
  got <- lapply(list(xa05_par, xa05_het, xa05_two), function(d) value_of(xa05_run(d)))
  testthat::expect_identical(vapply(got, function(g) isTRUE(field(g, "slopes_homogeneous")), TRUE),
                             c(TRUE, FALSE, TRUE))
  testthat::expect_identical(vapply(got, function(g) field(g, "model"), ""),
                             c("parallel", "separate", "parallel"))
})

check("treatment_test_is_adjusted_for_baseline", {
  xa05_expect_list(field(value_of(xa05_run(xa05_par)), "treatment_test"),
                   xa05_oracle(xa05_par)$treatment_test, "par")
  xa05_expect_list(field(value_of(xa05_run(xa05_two)), "treatment_test"),
                   xa05_oracle(xa05_two)$treatment_test, "two")
})

check("adjusted_means_are_evaluated_at_the_overall_baseline_mean", {
  got <- field(value_of(xa05_run(xa05_par)), "adjusted_means")
  want <- xa05_oracle(xa05_par)$adjusted_means
  testthat::expect_identical(names(got), c("treatment", "adjusted_mean"))
  testthat::expect_identical(as.character(got$treatment), want$treatment)
  testthat::expect_equal(as.numeric(got$adjusted_mean), want$adjusted_mean, tolerance = 1e-8)
})

check("adjusted_means_differ_from_raw_group_means", {
  got <- field(value_of(xa05_run(xa05_par)), "adjusted_means")
  testthat::expect_gt(max(abs(as.numeric(got$adjusted_mean) - xa05_oracle(xa05_par)$raw_means)), 0.05)
})

check("conditional_means_for_heterogeneous_slopes_use_mean_plus_minus_one_sd", {
  got <- field(value_of(xa05_run(xa05_het)), "conditional_means")
  want <- xa05_oracle(xa05_het)$conditional_means
  testthat::expect_identical(names(got), c("treatment", "at", "baseline", "fitted"))
  testthat::expect_identical(as.character(got$treatment), want$treatment)
  testthat::expect_identical(as.character(got$at), want$at)
  testthat::expect_equal(as.numeric(got$baseline), want$baseline, tolerance = 1e-8)
  testthat::expect_equal(as.numeric(got$fitted), want$fitted, tolerance = 1e-7)
})

check("elements_of_the_other_branch_are_null", {
  par <- value_of(xa05_run(xa05_par))
  het <- value_of(xa05_run(xa05_het))
  testthat::expect_true(all(c("treatment_test", "adjusted_means", "conditional_means") %in% names(par)))
  testthat::expect_null(par$conditional_means)
  testthat::expect_null(het$treatment_test)
  testthat::expect_null(het$adjusted_means)
})

check("missing_values_row_order_and_factor_labels_do_not_matter", {
  d <- xa05_par
  d$score[c(2, 11)] <- NA
  d$baseline[20] <- NA
  d$treatment <- factor(d$treatment, levels = c("c", "a", "b"))
  d <- d[rev(seq_len(nrow(d))), ]
  want <- xa05_oracle(d)
  got <- value_of(xa05_run(d))
  xa05_expect_list(field(got, "slope_test"), want$slope_test, "na")
  testthat::expect_equal(as.numeric(field(got, "adjusted_means")$adjusted_mean),
                         want$adjusted_means$adjusted_mean, tolerance = 1e-7)
})

check("input_data_frame_is_not_modified", {
  d <- xa05_het
  res <- xa05_run(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("single_level_small_group_or_constant_baseline_is_an_error", {
  one <- xa05_par[xa05_par$treatment == "a", ]
  tiny <- rbind(xa05_par[xa05_par$treatment != "b", ], xa05_par[xa05_par$treatment == "b", ][1:2, ])
  constant <- xa05_par
  constant$baseline <- 10
  expect_stops(xa05_run(one), works = xa05_run(xa05_par))
  expect_stops(xa05_run(tiny), works = xa05_run(xa05_par))
  expect_stops(xa05_run(constant), works = xa05_run(xa05_par))
})

check("result_has_exactly_the_documented_elements", {
  testthat::expect_setequal(names(value_of(xa05_run(xa05_par))),
                            c("slope_test", "slopes_homogeneous", "model", "treatment_test",
                              "adjusted_means", "conditional_means"))
})
