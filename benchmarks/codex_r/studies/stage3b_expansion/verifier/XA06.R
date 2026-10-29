# Hidden checks for XA06 (random-intercept mixed model with ML likelihood-ratio test).
#
# Independent oracle: an explicit profile-likelihood implementation of the Gaussian random-
# intercept model y_i = X_i beta + b_i 1 + e_i. With lambda = var(b)/var(e), the subject-level
# inverse covariance is W_i = I - lambda/(1 + lambda n_i) 11' and det = 1 + lambda n_i. Given
# lambda, beta is the GLS solution and sigma^2 = r'Wr / N (ML, not REML); the profile
# log-likelihood is maximised over log(lambda) by optimize(). nlme is used only to cross-check
# the oracle at load time, never as the oracle.

xa06_design <- function(trt, tm, interaction) {
  a <- sort(unique(trt))
  k <- sort(unique(tm))
  dt <- vapply(a[-1], function(l) as.numeric(trt == l), numeric(length(trt)))
  dk <- vapply(k[-1], function(l) as.numeric(tm == l), numeric(length(tm)))
  dt <- matrix(dt, length(trt))
  dk <- matrix(dk, length(tm))
  cols <- list(rep(1, length(trt)), dt, dk)
  if (interaction) {
    ix <- do.call(cbind, lapply(seq_len(ncol(dt)), function(i) dt[, i] * dk))
    cols <- c(cols, list(ix))
  }
  do.call(cbind, cols)
}

xa06_profile <- function(X, y, id) {
  ids <- unique(id)
  idx <- split(seq_along(y), factor(id, ids))
  ni <- unname(lengths(idx))
  n <- length(y)
  fit_for <- function(lam) {
    w <- lam / (1 + lam * ni)
    xtwx <- matrix(0, ncol(X), ncol(X))
    xtwy <- numeric(ncol(X))
    for (g in seq_along(idx)) {
      xi <- X[idx[[g]], , drop = FALSE]
      yi <- y[idx[[g]]]
      sx <- colSums(xi)
      xtwx <- xtwx + crossprod(xi) - w[g] * tcrossprod(sx)
      xtwy <- xtwy + drop(crossprod(xi, yi)) - w[g] * sx * sum(yi)
    }
    beta <- solve(xtwx, xtwy)
    quad <- 0
    for (g in seq_along(idx)) {
      r <- y[idx[[g]]] - X[idx[[g]], , drop = FALSE] %*% beta
      quad <- quad + sum(r^2) - w[g] * sum(r)^2
    }
    s2 <- quad / n
    list(ll = -n / 2 * (log(2 * pi * s2) + 1) - 0.5 * sum(log(1 + lam * ni)), s2 = s2, lam = lam)
  }
  opt <- stats::optimize(function(t) -fit_for(exp(t))$ll, c(-10, 7), tol = 1e-12)
  best <- fit_for(exp(opt$minimum))
  list(ll = best$ll, sigma = sqrt(best$s2), sd_b = sqrt(best$lam * best$s2), lambda = best$lam)
}

xa06_oracle <- function(df) {
  d <- df[stats::complete.cases(df[c("id", "treatment", "time", "score")]), , drop = FALSE]
  trt <- as.character(d$treatment)
  tm <- as.character(d$time)
  a <- length(unique(trt))
  k <- length(unique(tm))
  full <- xa06_profile(xa06_design(trt, tm, TRUE), d$score, as.character(d$id))
  red <- xa06_profile(xa06_design(trt, tm, FALSE), d$score, as.character(d$id))
  stat <- 2 * (full$ll - red$ll)
  dfree <- (a - 1) * (k - 1)
  p <- stats::pchisq(stat, dfree, lower.tail = FALSE)
  list(n_subjects = length(unique(d$id)), n_observations = nrow(d),
       lrt = list(statistic = stat, df = dfree, p_value = p), significant = p < 0.05,
       random_intercept_sd = full$sd_b, residual_sd = full$sigma, ll_full = full$ll,
       ll_red = red$ll)
}

xa06_data <- function(seed, n_per_group, groups, visits, trend, sd_id = 3, sd_e = 2, miss = 0.25) {
  with_seed(seed, {
    n <- n_per_group * length(groups)
    id <- sprintf("s%03d", seq_len(n))
    grp <- rep(groups, each = n_per_group)
    u <- stats::rnorm(n, sd = sd_id)
    rows <- lapply(seq_len(n), function(i) {
      keep <- if (stats::runif(1) < miss) sort(sample(length(visits), length(visits) - 1)) else seq_along(visits)
      data.frame(id = id[i], treatment = grp[i], time = visits[keep],
                 score = round(30 + u[i] + trend[[grp[i]]][keep] + stats::rnorm(length(keep), sd = sd_e), 3),
                 stringsAsFactors = FALSE)
    })
    d <- do.call(rbind, rows)
    d[sample.int(nrow(d)), ]
  })
}

xa06_sig <- xa06_data(701L, 18L, c("ctl", "trt"), c("v1", "v2", "v3"),
                      list(ctl = c(0, 0.3, 0.6), trt = c(0, 2, 4.5)))
xa06_null <- xa06_data(703L, 14L, c("a", "b"), c("t1", "t2", "t3", "t4"),
                       list(a = c(0, 1, 2, 3), b = c(0.5, 1.5, 2.5, 3.5)))
xa06_three <- xa06_data(703L, 10L, c("x", "y", "z"), c("m0", "m6", "m12"),
                        list(x = c(0, 0, 0), y = c(0, 1.5, 3), z = c(0, -1, -2.5)))

# ---- oracle self-checks (a failure here is a verifier fault) ----------------------------------
local({
  for (d in list(xa06_sig, xa06_null, xa06_three)) {
    o <- xa06_oracle(d)
    full <- nlme::lme(score ~ treatment * time, random = ~ 1 | id, data = d, method = "ML")
    stopifnot(isTRUE(all.equal(as.numeric(stats::logLik(full)), o$ll_full, tolerance = 1e-6)),
              isTRUE(all.equal(full$sigma, o$residual_sd, tolerance = 1e-3)))
  }
  stopifnot(xa06_oracle(xa06_sig)$lrt$p_value < 0.01, xa06_oracle(xa06_null)$lrt$p_value > 0.2,
            xa06_oracle(xa06_three)$lrt$p_value < 0.01)
  stopifnot(nrow(xa06_sig) < 18 * 2 * 3)  # some visits are missing
})

xa06_run <- function(df) call_candidate("longitudinal_test", df, .timeout = 120)

xa06_expect <- function(got, want, tol = 1e-4) {
  testthat::expect_true(is.list(got))
  lrt <- field(got, "lrt")
  for (nm in c("statistic", "df", "p_value")) {
    testthat::expect_equal(as.numeric(field(lrt, nm)), as.numeric(want$lrt[[nm]]), tolerance = tol,
                           info = nm)
  }
}

check("significant_interaction_lrt_matches_the_ml_profile_oracle", {
  xa06_expect(value_of(xa06_run(xa06_sig)), xa06_oracle(xa06_sig))
})

check("null_interaction_with_four_visits_matches_the_oracle", {
  xa06_expect(value_of(xa06_run(xa06_null)), xa06_oracle(xa06_null))
})

check("three_treatment_groups_use_the_right_degrees_of_freedom", {
  got <- value_of(xa06_run(xa06_three))
  xa06_expect(got, xa06_oracle(xa06_three))
  testthat::expect_equal(as.numeric(field(field(got, "lrt"), "df")), 4)
})

check("counts_use_all_available_observations_not_completers", {
  got <- value_of(xa06_run(xa06_sig))
  want <- xa06_oracle(xa06_sig)
  testthat::expect_identical(as.integer(field(got, "n_subjects")), as.integer(want$n_subjects))
  testthat::expect_identical(as.integer(field(got, "n_observations")), as.integer(want$n_observations))
  testthat::expect_lt(field(got, "n_observations"), field(got, "n_subjects") * 3)
})

check("random_intercept_and_residual_sds_are_ml_estimates", {
  got <- value_of(xa06_run(xa06_sig))
  want <- xa06_oracle(xa06_sig)
  testthat::expect_equal(as.numeric(field(got, "random_intercept_sd")), want$random_intercept_sd,
                         tolerance = 1e-3)
  testthat::expect_equal(as.numeric(field(got, "residual_sd")), want$residual_sd, tolerance = 1e-3)
})

check("significance_flag_follows_the_005_rule", {
  flags <- vapply(list(xa06_sig, xa06_null, xa06_three),
                  function(d) isTRUE(field(value_of(xa06_run(d)), "significant")), TRUE)
  testthat::expect_identical(flags, c(TRUE, FALSE, TRUE))
})

check("the_test_is_not_the_reml_likelihood_ratio", {
  # REML likelihoods of models with different fixed effects are not comparable; the statistic from
  # REML fits differs from the ML one, so a candidate using REML cannot match the oracle above.
  d <- xa06_sig
  reml_full <- nlme::lme(score ~ treatment * time, random = ~ 1 | id, data = d, method = "REML")
  reml_red <- nlme::lme(score ~ treatment + time, random = ~ 1 | id, data = d, method = "REML")
  reml_stat <- 2 * (as.numeric(stats::logLik(reml_full)) - as.numeric(stats::logLik(reml_red)))
  testthat::expect_gt(abs(reml_stat - xa06_oracle(d)$lrt$statistic), 0.05)
  got <- field(field(value_of(xa06_run(d)), "lrt"), "statistic")
  testthat::expect_lt(abs(as.numeric(got) - xa06_oracle(d)$lrt$statistic),
                      abs(as.numeric(got) - reml_stat))
})

check("row_order_factor_levels_and_integer_time_codes_do_not_matter", {
  d <- xa06_sig
  d$time <- as.integer(sub("v", "", d$time))
  d$treatment <- factor(d$treatment, levels = c("trt", "ctl"))
  d <- d[rev(seq_len(nrow(d))), ]
  xa06_expect(value_of(xa06_run(d)), xa06_oracle(xa06_sig))
})

check("rows_with_missing_values_are_dropped", {
  d <- xa06_sig
  extra <- d[1:4, ]
  extra$score[1:2] <- NA
  extra$time[3] <- NA
  extra$id[4] <- NA
  d <- rbind(extra, d)
  xa06_expect(value_of(xa06_run(d)), xa06_oracle(xa06_sig))
})

check("input_data_frame_is_not_modified", {
  d <- xa06_sig
  res <- xa06_run(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("a_participant_in_two_treatment_arms_is_an_error", {
  d <- xa06_sig
  d$treatment[d$id == "s001"][1] <- "trt"
  d$treatment[d$id == "s001"][-1] <- "ctl"
  expect_stops(xa06_run(d), works = xa06_run(xa06_sig))
})

check("single_treatment_arm_or_single_visit_is_an_error", {
  one_arm <- xa06_sig[xa06_sig$treatment == "ctl", ]
  one_visit <- xa06_sig[xa06_sig$time == "v1", ]
  expect_stops(xa06_run(one_arm), works = xa06_run(xa06_sig))
  expect_stops(xa06_run(one_visit), works = xa06_run(xa06_sig))
})

check("result_has_exactly_the_documented_elements", {
  testthat::expect_setequal(names(value_of(xa06_run(xa06_sig))),
                            c("n_subjects", "n_observations", "lrt", "significant",
                              "random_intercept_sd", "residual_sd"))
})
