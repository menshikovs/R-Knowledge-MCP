# Hidden checks for XA01 (Brown-Forsythe, then classical or Welch one-way ANOVA with follow-ups).
#
# Independent oracle written from the closed-form definitions (no aov/oneway.test/TukeyHSD/
# pairwise.t.test): Brown-Forsythe is the classical F on |x - group median|; Welch's F uses
# weights w_i = n_i / s_i^2; Tukey-Kramer uses the studentized range with the pooled MSE.

xa01_oracle <- function(df) {
  df <- df[stats::complete.cases(df[c("group", "score")]), , drop = FALSE]
  labels <- sort(unique(as.character(df$group)))
  k <- length(labels)
  y <- lapply(labels, function(l) df$score[as.character(df$group) == l])
  n <- lengths(y)
  m <- vapply(y, mean, numeric(1))
  v <- vapply(y, stats::var, numeric(1))
  total <- sum(n)
  f_classical <- function(groups) {
    nn <- lengths(groups)
    mm <- vapply(groups, mean, numeric(1))
    grand <- sum(unlist(groups)) / sum(nn)
    ssb <- sum(nn * (mm - grand)^2)
    ssw <- sum(vapply(groups, function(g) sum((g - mean(g))^2), numeric(1)))
    f <- (ssb / (length(groups) - 1)) / (ssw / (sum(nn) - length(groups)))
    list(statistic = f, df1 = length(groups) - 1, df2 = sum(nn) - length(groups),
         p_value = stats::pf(f, length(groups) - 1, sum(nn) - length(groups), lower.tail = FALSE),
         mse = ssw / (sum(nn) - length(groups)))
  }
  bf <- f_classical(lapply(y, function(g) abs(g - stats::median(g))))
  equal <- bf$p_value >= 0.05
  w <- n / v
  mw <- sum(w * m) / sum(w)
  lam <- sum((1 - w / sum(w))^2 / (n - 1))
  welch_f <- (sum(w * (m - mw)^2) / (k - 1)) / (1 + 2 * (k - 2) / (k^2 - 1) * lam)
  welch_df2 <- (k^2 - 1) / (3 * lam)
  welch <- list(statistic = welch_f, df1 = k - 1, df2 = welch_df2,
                p_value = stats::pf(welch_f, k - 1, welch_df2, lower.tail = FALSE))
  cl <- f_classical(y)
  pairs <- t(utils::combn(k, 2))
  pairs <- pairs[order(pairs[, 1], pairs[, 2]), , drop = FALSE]
  diff <- m[pairs[, 2]] - m[pairs[, 1]]
  if (equal) {
    q <- abs(diff) / sqrt(cl$mse / 2 * (1 / n[pairs[, 1]] + 1 / n[pairs[, 2]]))
    padj <- stats::ptukey(q, nmeans = k, df = total - k, lower.tail = FALSE)
  } else {
    se2 <- v[pairs[, 1]] / n[pairs[, 1]] + v[pairs[, 2]] / n[pairs[, 2]]
    dfw <- se2^2 / ((v[pairs[, 1]] / n[pairs[, 1]])^2 / (n[pairs[, 1]] - 1) +
                    (v[pairs[, 2]] / n[pairs[, 2]])^2 / (n[pairs[, 2]] - 1))
    traw <- abs(diff) / sqrt(se2)
    padj <- stats::p.adjust(2 * stats::pt(traw, dfw, lower.tail = FALSE), method = "holm")
  }
  list(
    variance_test = bf[c("statistic", "df1", "df2", "p_value")],
    method = if (equal) "classical" else "welch",
    omnibus = if (equal) cl[c("statistic", "df1", "df2", "p_value")] else welch,
    pairwise = data.frame(group1 = labels[pairs[, 1]], group2 = labels[pairs[, 2]],
                          diff = unname(diff), p_adjusted = unname(padj),
                          stringsAsFactors = FALSE),
    classical = cl, welch = welch, pooled_tukey_p = {
      q <- abs(diff) / sqrt(cl$mse / 2 * (1 / n[pairs[, 1]] + 1 / n[pairs[, 2]]))
      stats::ptukey(q, nmeans = k, df = total - k, lower.tail = FALSE)
    }
  )
}

xa01_data <- function(seed, n, mu, sd, labels) {
  with_seed(seed, {
    y <- unlist(Map(function(k, m, s) stats::rnorm(k, m, s), n, mu, sd))
    d <- data.frame(participant_id = sprintf("s%03d", sample.int(sum(n))),
                    group = rep(labels, times = n), score = round(y, 3),
                    stringsAsFactors = FALSE)
    d[sample.int(nrow(d)), ]
  })
}

xa01_equal <- xa01_data(301L, c(12L, 15L, 10L), c(10, 12, 15), c(2, 2, 2), c("ctrl", "dose1", "dose2"))
xa01_unequal <- xa01_data(302L, c(8L, 20L, 6L, 14L), c(10, 11, 16, 12), c(1, 6, 12, 2.5),
                          c("a", "b", "c", "d"))
xa01_unbal_equal <- xa01_data(303L, c(5L, 17L, 9L, 12L), c(30, 31, 36, 29), rep(3, 4),
                              c("north", "south", "east", "west"))

# ---- oracle self-checks against base R (a failure is a verifier fault) ------------------------
local({
  o1 <- xa01_oracle(xa01_equal)
  o2 <- xa01_oracle(xa01_unequal)
  o3 <- xa01_oracle(xa01_unbal_equal)
  stopifnot(o1$method == "classical", o1$variance_test$p_value > 0.2,
            o2$method == "welch", o2$variance_test$p_value < 0.01,
            o3$method == "classical", o3$variance_test$p_value > 0.2)
  w <- stats::oneway.test(score ~ group, data = xa01_unequal, var.equal = FALSE)
  stopifnot(isTRUE(all.equal(unname(w$statistic), o2$welch$statistic)),
            isTRUE(all.equal(unname(w$parameter[2]), o2$welch$df2)),
            isTRUE(all.equal(w$p.value, o2$welch$p_value)))
  a <- stats::anova(stats::lm(score ~ group, data = xa01_unbal_equal))
  stopifnot(isTRUE(all.equal(a$`F value`[1], o3$classical$statistic)))
  tk <- stats::TukeyHSD(stats::aov(score ~ group, data = xa01_unbal_equal))$group
  stopifnot(isTRUE(all.equal(unname(tk[, "p adj"]), o3$pooled_tukey_p, tolerance = 1e-6)),
            isTRUE(all.equal(unname(tk[, "diff"]), o3$pairwise$diff, tolerance = 1e-9)))
  pw <- stats::pairwise.t.test(xa01_unequal$score, xa01_unequal$group, pool.sd = FALSE,
                               p.adjust.method = "holm")$p.value
  oracle_p <- stats::setNames(o2$pairwise$p_adjusted, paste(o2$pairwise$group1, o2$pairwise$group2))
  stopifnot(isTRUE(all.equal(unname(pw["b", "a"]), unname(oracle_p["a b"]), tolerance = 1e-8)))
})

xa01_run <- function(df) call_candidate("compare_groups", df)

xa01_expect_stat <- function(got, want, label) {
  testthat::expect_true(is.list(got), info = label)
  for (nm in c("statistic", "df1", "df2", "p_value")) {
    testthat::expect_equal(as.numeric(field(got, nm)), as.numeric(want[[nm]]), tolerance = 1e-6,
                           info = paste(label, nm))
  }
}

check("equal_variances_brown_forsythe_statistic_matches_oracle", {
  res <- value_of(xa01_run(xa01_equal))
  xa01_expect_stat(field(res, "variance_test"), xa01_oracle(xa01_equal)$variance_test, "equal")
})

check("unequal_variances_brown_forsythe_statistic_matches_oracle", {
  res <- value_of(xa01_run(xa01_unequal))
  xa01_expect_stat(field(res, "variance_test"), xa01_oracle(xa01_unequal)$variance_test, "unequal")
})

check("method_is_classical_for_equal_and_welch_for_unequal_variances", {
  got <- c(field(value_of(xa01_run(xa01_equal)), "method"),
           field(value_of(xa01_run(xa01_unequal)), "method"),
           field(value_of(xa01_run(xa01_unbal_equal)), "method"))
  testthat::expect_identical(got, c("classical", "welch", "classical"))
})

check("classical_omnibus_matches_oracle", {
  xa01_expect_stat(field(value_of(xa01_run(xa01_unbal_equal)), "omnibus"),
                   xa01_oracle(xa01_unbal_equal)$omnibus, "classical")
})

check("welch_omnibus_uses_fractional_denominator_df_and_matches_oracle", {
  got <- field(value_of(xa01_run(xa01_unequal)), "omnibus")
  want <- xa01_oracle(xa01_unequal)$omnibus
  xa01_expect_stat(got, want, "welch")
  testthat::expect_gt(abs(as.numeric(got$df2) - round(as.numeric(got$df2))), 1e-3)
})

check("tukey_kramer_adjusted_p_values_for_unbalanced_equal_variance_data", {
  pw <- field(value_of(xa01_run(xa01_unbal_equal)), "pairwise")
  want <- xa01_oracle(xa01_unbal_equal)$pairwise
  testthat::expect_identical(as.character(pw$group1), want$group1)
  testthat::expect_identical(as.character(pw$group2), want$group2)
  testthat::expect_equal(as.numeric(pw$diff), want$diff, tolerance = 1e-8)
  testthat::expect_equal(as.numeric(pw$p_adjusted), want$p_adjusted, tolerance = 1e-5)
})

check("holm_adjusted_unpooled_welch_pairwise_for_unequal_variance_data", {
  pw <- field(value_of(xa01_run(xa01_unequal)), "pairwise")
  want <- xa01_oracle(xa01_unequal)$pairwise
  testthat::expect_equal(as.numeric(pw$p_adjusted), want$p_adjusted, tolerance = 1e-5)
  testthat::expect_equal(as.numeric(pw$diff), want$diff, tolerance = 1e-8)
})

check("welch_branch_does_not_reuse_pooled_tukey_p_values", {
  pw <- field(value_of(xa01_run(xa01_unequal)), "pairwise")
  pooled <- xa01_oracle(xa01_unequal)$pooled_tukey_p
  testthat::expect_gt(max(abs(as.numeric(pw$p_adjusted) - pooled)), 1e-3)
})

check("pairwise_table_has_the_required_columns_and_pair_order", {
  pw <- field(value_of(xa01_run(xa01_unequal)), "pairwise")
  testthat::expect_s3_class(pw, "data.frame")
  testthat::expect_identical(names(pw), c("group1", "group2", "diff", "p_adjusted"))
  testthat::expect_identical(nrow(pw), 6L)
  testthat::expect_identical(paste(pw$group1, pw$group2),
                             c("a b", "a c", "a d", "b c", "b d", "c d"))
})

check("rows_with_missing_values_are_dropped_and_row_order_is_irrelevant", {
  d <- xa01_unequal
  d$score[c(2, 9, 30)] <- NA
  d$group[c(5)] <- NA
  d <- d[rev(seq_len(nrow(d))), ]
  res <- value_of(xa01_run(d))
  want <- xa01_oracle(d)
  xa01_expect_stat(field(res, "omnibus"), want$omnibus, "na")
  testthat::expect_equal(as.numeric(field(res, "pairwise")$p_adjusted), want$pairwise$p_adjusted,
                         tolerance = 1e-5)
})

check("input_data_frame_is_not_modified", {
  d <- xa01_unequal
  res <- xa01_run(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("fewer_than_three_groups_is_an_error", {
  two <- xa01_unequal[xa01_unequal$group %in% c("a", "b"), ]
  expect_stops(xa01_run(two), works = xa01_run(xa01_unequal))
})

check("a_group_with_a_single_observation_is_an_error", {
  d <- xa01_unequal[xa01_unequal$group != "c", ]
  one <- rbind(d, xa01_unequal[xa01_unequal$group == "c", ][1, ])
  expect_stops(xa01_run(one), works = xa01_run(xa01_unequal))
})
