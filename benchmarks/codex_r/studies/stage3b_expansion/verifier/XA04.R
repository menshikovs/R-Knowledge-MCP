# Hidden checks for XA04 (one-factor repeated-measures ANOVA with Greenhouse-Geisser correction).
#
# Independent oracle: the subjects x occasions matrix Y gives SS_time = n sum((col means - grand)^2),
# SS_subject = k sum((row means - grand)^2), SS_error = SS_total - SS_time - SS_subject. Epsilon is
# Box's formula on the sample covariance matrix S:
#   eps = k^2 (mean(diag S) - mean(S))^2 / ((k - 1) (sum(S^2) - 2 k sum(rowmeans(S)^2) + k^2 mean(S)^2)).

xa04_oracle <- function(df) {
  d <- df[!is.na(df$subject) & !is.na(df$time), , drop = FALSE]
  occ <- sort(unique(as.character(d$time)))
  k <- length(occ)
  dd <- d[!is.na(d$score), , drop = FALSE]
  if (anyDuplicated(paste(dd$subject, as.character(dd$time), sep = "\r"))) stop("duplicate")
  tab <- table(as.character(dd$subject), factor(as.character(dd$time), occ))
  keep <- rownames(tab)[rowSums(tab) == k]
  n <- length(keep)
  stopifnot(k >= 3, n >= 4)
  y <- vapply(occ, function(o) {
    sub <- dd[as.character(dd$time) == o & as.character(dd$subject) %in% keep, ]
    sub$score[match(keep, as.character(sub$subject))]
  }, numeric(n))
  gm <- mean(y)
  ss_time <- n * sum((colMeans(y) - gm)^2)
  ss_subject <- k * sum((rowMeans(y) - gm)^2)
  ss_error <- sum((y - gm)^2) - ss_time - ss_subject
  df1 <- k - 1
  df2 <- (n - 1) * (k - 1)
  f <- (ss_time / df1) / (ss_error / df2)
  s <- stats::cov(y)
  eps <- k^2 * (mean(diag(s)) - mean(s))^2 /
    ((k - 1) * (sum(s^2) - 2 * k * sum(rowMeans(s)^2) + k^2 * mean(s)^2))
  gg <- eps < 0.75
  p <- stats::pf(f, df1, df2, lower.tail = FALSE)
  p_gg <- stats::pf(f, df1 * eps, df2 * eps, lower.tail = FALSE)
  hf <- min(1, (n * (k - 1) * eps - 2) / ((k - 1) * (n - 1 - (k - 1) * eps)))
  list(n_subjects = n, n_levels = k, ss_time = ss_time, ss_error = ss_error, df1 = df1, df2 = df2,
       f_value = f, p_value = p, epsilon_gg = eps, p_gg = p_gg,
       correction = if (gg) "greenhouse_geisser" else "none", p_primary = if (gg) p_gg else p,
       eps_hf = hf, y = y)
}

xa04_data <- function(seed, n, means, sigma, times) {
  with_seed(seed, {
    k <- length(times)
    z <- matrix(stats::rnorm(n * k), n, k) %*% chol(sigma)
    y <- sweep(z, 2, means, "+")
    d <- data.frame(subject = rep(sprintf("s%02d", seq_len(n)), times = k),
                    time = rep(times, each = n), score = round(as.vector(y), 3),
                    stringsAsFactors = FALSE)
    d[sample.int(nrow(d)), ]
  })
}

xa04_low <- xa04_data(501L, 14L, c(10, 11.5, 14), matrix(c(1, .9, .1, .9, 1, .4, .1, .4, 5), 3),
                      c("t1", "t2", "t3"))
xa04_cs <- xa04_data(502L, 18L, c(20, 21, 20.5, 23), 2 * (0.5 * diag(4) + 0.5 * matrix(1, 4, 4)),
                     c("w0", "w1", "w2", "w3"))

local({
  lo <- xa04_oracle(xa04_low)
  cs <- xa04_oracle(xa04_cs)
  stopifnot(lo$epsilon_gg < 0.7, lo$correction == "greenhouse_geisser",
            cs$epsilon_gg > 0.8, cs$correction == "none")
  # Cross-check 1: aov with an Error() stratum.
  d <- xa04_cs
  d$subject <- factor(d$subject)
  d$time <- factor(d$time)
  st <- summary(stats::aov(score ~ time + Error(subject / time), data = d))
  within <- st[["Error: subject:time"]][[1]]
  stopifnot(isTRUE(all.equal(within[["F value"]][1], cs$f_value, tolerance = 1e-8)),
            isTRUE(all.equal(within[["Sum Sq"]][1], cs$ss_time, tolerance = 1e-8)),
            isTRUE(all.equal(within[["Sum Sq"]][2], cs$ss_error, tolerance = 1e-8)))
  # Cross-check 2: epsilon from the eigenvalues of the double-centred covariance matrix.
  s <- stats::cov(lo$y)
  k <- ncol(lo$y)
  cm <- diag(k) - matrix(1 / k, k, k)
  ev <- eigen(cm %*% s %*% cm, symmetric = TRUE, only.values = TRUE)$values
  stopifnot(isTRUE(all.equal(sum(ev)^2 / ((k - 1) * sum(ev^2)), lo$epsilon_gg, tolerance = 1e-8)))
})

xa04_run <- function(df) call_candidate("rm_anova", df)

xa04_expect <- function(got, want, fields) {
  testthat::expect_true(is.list(got))
  for (nm in fields) {
    testthat::expect_equal(as.numeric(field(got, nm)), as.numeric(want[[nm]]), tolerance = 1e-6,
                           info = nm)
  }
}

check("uncorrected_test_matches_oracle_for_three_occasions", {
  xa04_expect(value_of(xa04_run(xa04_low)), xa04_oracle(xa04_low),
              c("df1", "df2", "f_value", "p_value"))
})

check("uncorrected_test_matches_oracle_for_four_occasions", {
  xa04_expect(value_of(xa04_run(xa04_cs)), xa04_oracle(xa04_cs),
              c("df1", "df2", "f_value", "p_value"))
})

check("time_and_error_sums_of_squares_use_the_time_by_subject_error_term", {
  xa04_expect(value_of(xa04_run(xa04_low)), xa04_oracle(xa04_low), c("ss_time", "ss_error"))
})

check("greenhouse_geisser_epsilon_matches_oracle", {
  xa04_expect(value_of(xa04_run(xa04_low)), xa04_oracle(xa04_low), "epsilon_gg")
  xa04_expect(value_of(xa04_run(xa04_cs)), xa04_oracle(xa04_cs), "epsilon_gg")
})

check("corrected_p_multiplies_both_degrees_of_freedom_by_epsilon", {
  xa04_expect(value_of(xa04_run(xa04_low)), xa04_oracle(xa04_low), "p_gg")
  xa04_expect(value_of(xa04_run(xa04_cs)), xa04_oracle(xa04_cs), "p_gg")
})

check("correction_rule_and_primary_p_follow_the_075_threshold", {
  lo <- value_of(xa04_run(xa04_low))
  cs <- value_of(xa04_run(xa04_cs))
  testthat::expect_identical(c(field(lo, "correction"), field(cs, "correction")),
                             c("greenhouse_geisser", "none"))
  testthat::expect_equal(as.numeric(field(lo, "p_primary")), as.numeric(field(lo, "p_gg")))
  testthat::expect_equal(as.numeric(field(cs, "p_primary")), as.numeric(field(cs, "p_value")))
})

check("subjects_with_a_missing_occasion_are_dropped_entirely", {
  d <- xa04_low
  d <- d[!(d$subject == "s03" & d$time == "t2"), ]
  d$score[d$subject == "s07" & d$time == "t1"] <- NA
  want <- xa04_oracle(d)
  got <- value_of(xa04_run(d))
  testthat::expect_identical(as.integer(field(got, "n_subjects")), 12L)
  xa04_expect(got, want, c("df2", "f_value", "epsilon_gg", "p_primary", "ss_error"))
})

check("integer_or_factor_time_codes_and_row_order_do_not_matter", {
  d <- xa04_low
  d$time <- as.integer(sub("t", "", d$time))
  d <- d[rev(seq_len(nrow(d))), ]
  xa04_expect(value_of(xa04_run(d)), xa04_oracle(xa04_low), c("f_value", "epsilon_gg", "p_gg"))
  f <- xa04_low
  f$time <- factor(f$time, levels = c("t3", "t1", "t2"))
  xa04_expect(value_of(xa04_run(f)), xa04_oracle(xa04_low), c("f_value", "epsilon_gg"))
})

check("numeric_subject_identifiers_are_supported", {
  d <- xa04_cs
  d$subject <- as.integer(sub("s", "", d$subject)) + 100L
  xa04_expect(value_of(xa04_run(d)), xa04_oracle(xa04_cs), c("f_value", "p_value", "epsilon_gg"))
})

check("input_data_frame_is_not_modified", {
  d <- xa04_low
  res <- xa04_run(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("duplicate_subject_by_occasion_rows_are_an_error", {
  d <- rbind(xa04_low, xa04_low[1, ])
  expect_stops(xa04_run(d), works = xa04_run(xa04_low))
})

check("too_few_occasions_or_subjects_is_an_error", {
  two_times <- xa04_low[xa04_low$time != "t3", ]
  three_subjects <- xa04_low[xa04_low$subject %in% c("s01", "s02", "s03"), ]
  expect_stops(xa04_run(two_times), works = xa04_run(xa04_low))
  expect_stops(xa04_run(three_subjects), works = xa04_run(xa04_low))
})

check("result_has_exactly_the_documented_elements", {
  testthat::expect_setequal(
    names(value_of(xa04_run(xa04_low))),
    c("n_subjects", "n_levels", "ss_time", "ss_error", "df1", "df2", "f_value", "p_value",
      "epsilon_gg", "p_gg", "correction", "p_primary")
  )
})
