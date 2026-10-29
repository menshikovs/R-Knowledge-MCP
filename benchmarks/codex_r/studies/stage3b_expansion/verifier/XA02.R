# Hidden checks for XA02 (balanced two-way factorial; simple effects against the full-model MSE).
#
# Independent oracle from the classical balanced-design formulas (no aov/lm/anova):
#   SS_A = r b sum((rowmean - grand)^2), SS_B = r a sum((colmean - grand)^2),
#   SS_AB = r sum((cell - rowmean - colmean + grand)^2), SSE = sum((y - cell)^2),
#   simple effect of A at level j: SS = r sum((cell[, j] - colmean[j])^2), df = a - 1,
#   tested against MSE = SSE / (a b (r - 1)) of the FULL model.

xa02_oracle <- function(df) {
  df <- df[stats::complete.cases(df[c("treatment", "site", "score")]), , drop = FALSE]
  tl <- sort(unique(as.character(df$treatment)))
  sl <- sort(unique(as.character(df$site)))
  a <- length(tl)
  b <- length(sl)
  ti <- match(as.character(df$treatment), tl)
  sj <- match(as.character(df$site), sl)
  n <- table(factor(ti, seq_len(a)), factor(sj, seq_len(b)))
  r <- n[1, 1]
  stopifnot(a >= 2, b >= 2, r >= 2, all(n == r))
  cell <- tapply(df$score, list(factor(ti, seq_len(a)), factor(sj, seq_len(b))), mean)
  grand <- mean(df$score)
  rowm <- rowMeans(cell)
  colm <- colMeans(cell)
  ss <- c(treatment = r * b * sum((rowm - grand)^2),
          site = r * a * sum((colm - grand)^2),
          `treatment:site` = r * sum((cell - outer(rowm, colm, "+") + grand)^2))
  sse <- sum((df$score - cell[cbind(ti, sj)])^2)
  dfe <- a * b * (r - 1)
  dfs <- c(a - 1, b - 1, (a - 1) * (b - 1))
  mse <- sse / dfe
  f <- (ss / dfs) / mse
  anova <- data.frame(df = c(dfs, dfe), sum_sq = c(ss, sse), mean_sq = c(ss / dfs, mse),
                      f_value = c(f, NA_real_),
                      p_value = c(stats::pf(f, dfs, dfe, lower.tail = FALSE), NA_real_),
                      row.names = c(names(ss), "Residuals"))
  sig <- anova["treatment:site", "p_value"] < 0.05
  ss_simple <- vapply(seq_len(b), function(j) r * sum((cell[, j] - colm[j])^2), numeric(1))
  f_simple <- (ss_simple / (a - 1)) / mse
  simple <- data.frame(site = sl, df1 = a - 1, df2 = dfe, sum_sq = ss_simple, f_value = f_simple,
                       p_value = stats::pf(f_simple, a - 1, dfe, lower.tail = FALSE),
                       stringsAsFactors = FALSE)
  # Per-site one-way ANOVAs use their own error term: a plausible, different, wrong answer.
  per_site_f <- vapply(seq_len(b), function(j) {
    s <- df[sj == j, ]
    y <- split(s$score, s$treatment)
    sse_j <- sum(vapply(y, function(v) sum((v - mean(v))^2), numeric(1)))
    (ss_simple[j] / (a - 1)) / (sse_j / (a * (r - 1)))
  }, numeric(1))
  list(
    anova = anova, interaction_significant = sig,
    report_level = if (sig) "simple_effects" else "main_effects",
    cell_means = data.frame(treatment = rep(tl, each = b), site = rep(sl, times = a),
                            mean = as.vector(t(cell)), n = as.integer(r), stringsAsFactors = FALSE),
    simple_effects = if (sig) simple else NULL, simple_all = simple, per_site_f = per_site_f
  )
}

xa02_data <- function(seed, tl, sl, reps, effect) {
  with_seed(seed, {
    grid <- expand.grid(treatment = tl, site = sl, stringsAsFactors = FALSE)
    parts <- lapply(seq_len(nrow(grid)), function(k) {
      data.frame(treatment = grid$treatment[k], site = grid$site[k],
                 score = round(50 + effect[grid$treatment[k], grid$site[k]] +
                                 stats::rnorm(reps, sd = 2), 3), stringsAsFactors = FALSE)
    })
    d <- do.call(rbind, parts)
    d$participant_id <- sprintf("p%03d", sample.int(nrow(d)))
    d[sample.int(nrow(d)), c("participant_id", "treatment", "site", "score")]
  })
}

xa02_cross <- xa02_data(401L, c("a", "b", "c"), c("x", "y", "z"), 5L,
                        matrix(c(0, 6, 3, 5, 0, -2, -3, 4, 0), 3, dimnames = list(c("a", "b", "c"), c("x", "y", "z"))))
xa02_add <- xa02_data(402L, c("ctrl", "drug"), c("n", "s", "w"), 6L,
                      matrix(rep(c(0, 4), 3) + rep(c(0, 3, -2), each = 2), 2,
                             dimnames = list(c("ctrl", "drug"), c("n", "s", "w"))))
xa02_two <- xa02_data(403L, c("lo", "hi"), c("p", "q"), 8L,
                      matrix(c(0, 7, 6, 0), 2, dimnames = list(c("lo", "hi"), c("p", "q"))))

local({
  oc <- xa02_oracle(xa02_cross)
  oa <- xa02_oracle(xa02_add)
  stopifnot(oc$interaction_significant, !oa$interaction_significant, xa02_oracle(xa02_two)$interaction_significant)
  cl <- stats::anova(stats::lm(score ~ treatment * site, data = xa02_cross))
  stopifnot(isTRUE(all.equal(unname(oc$anova$sum_sq[1:4]), cl[["Sum Sq"]], tolerance = 1e-9)),
            isTRUE(all.equal(unname(oc$anova$p_value[1:3]), cl[["Pr(>F)"]][1:3], tolerance = 1e-9)))
  # Simple effect of treatment at site "x" from a nested model comparison with the full MSE.
  # Identity: the simple-effect sums of squares add up to SS(treatment) + SS(treatment:site).
  d <- xa02_cross
  sub <- stats::lm(score ~ site + site:treatment, data = d)
  cmp <- stats::anova(stats::lm(score ~ site, data = d), sub)
  stopifnot(isTRUE(all.equal(cmp[["Sum of Sq"]][2], sum(oc$simple_all$sum_sq), tolerance = 1e-8)))
  stopifnot(all(oc$per_site_f != oc$simple_all$f_value))
})

xa02_run <- function(df) call_candidate("factorial_analysis", df)

xa02_expect_anova <- function(got, want) {
  testthat::expect_s3_class(got, "data.frame")
  testthat::expect_identical(rownames(got), rownames(want))
  for (col in c("df", "sum_sq", "mean_sq", "f_value", "p_value")) {
    testthat::expect_equal(unname(as.numeric(got[[col]])), unname(want[[col]]), tolerance = 1e-6,
                           info = col)
  }
}

check("crossover_interaction_anova_table_matches_oracle", {
  xa02_expect_anova(field(value_of(xa02_run(xa02_cross)), "anova"), xa02_oracle(xa02_cross)$anova)
})

check("additive_design_anova_table_matches_oracle", {
  xa02_expect_anova(field(value_of(xa02_run(xa02_add)), "anova"), xa02_oracle(xa02_add)$anova)
})

check("two_by_two_with_other_labels_matches_oracle", {
  xa02_expect_anova(field(value_of(xa02_run(xa02_two)), "anova"), xa02_oracle(xa02_two)$anova)
})

check("cell_means_table_is_ordered_treatment_then_site", {
  got <- field(value_of(xa02_run(xa02_cross)), "cell_means")
  want <- xa02_oracle(xa02_cross)$cell_means
  testthat::expect_identical(names(got), c("treatment", "site", "mean", "n"))
  testthat::expect_identical(as.character(got$treatment), want$treatment)
  testthat::expect_identical(as.character(got$site), want$site)
  testthat::expect_equal(as.numeric(got$mean), want$mean, tolerance = 1e-8)
  testthat::expect_equal(as.numeric(got$n), want$n)
})

check("interaction_flag_and_report_level_follow_the_fixed_rule", {
  got <- lapply(list(xa02_cross, xa02_add, xa02_two), function(d) value_of(xa02_run(d)))
  testthat::expect_identical(vapply(got, function(g) isTRUE(field(g, "interaction_significant")), TRUE),
                             c(TRUE, FALSE, TRUE))
  testthat::expect_identical(vapply(got, function(g) field(g, "report_level"), ""),
                             c("simple_effects", "main_effects", "simple_effects"))
})

check("simple_effects_use_the_full_model_residual_mean_square", {
  got <- field(value_of(xa02_run(xa02_cross)), "simple_effects")
  want <- xa02_oracle(xa02_cross)$simple_effects
  testthat::expect_identical(names(got), c("site", "df1", "df2", "sum_sq", "f_value", "p_value"))
  testthat::expect_identical(as.character(got$site), want$site)
  for (col in c("df1", "df2", "sum_sq", "f_value", "p_value")) {
    testthat::expect_equal(as.numeric(got[[col]]), want[[col]], tolerance = 1e-6, info = col)
  }
})

check("simple_effects_are_not_per_site_one_way_anovas", {
  got <- field(value_of(xa02_run(xa02_cross)), "simple_effects")
  testthat::expect_gt(max(abs(as.numeric(got$f_value) - xa02_oracle(xa02_cross)$per_site_f)), 1e-3)
  testthat::expect_identical(as.numeric(got$df2), rep(3 * 3 * (5 - 1), 3))
})

check("simple_effects_are_null_when_the_interaction_is_not_significant", {
  res <- value_of(xa02_run(xa02_add))
  testthat::expect_true("simple_effects" %in% names(res))
  testthat::expect_null(res$simple_effects)
})

check("missing_score_rows_are_dropped_and_row_order_is_irrelevant", {
  d <- xa02_cross
  extra <- d[1:3, ]
  extra$score <- NA_real_
  d <- rbind(extra, d[rev(seq_len(nrow(d))), ])
  d$treatment <- factor(d$treatment)
  xa02_expect_anova(field(value_of(xa02_run(d)), "anova"), xa02_oracle(xa02_cross)$anova)
})

check("input_data_frame_is_not_modified", {
  d <- xa02_cross
  res <- xa02_run(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("unbalanced_design_after_dropping_is_an_error", {
  expect_stops(xa02_run(xa02_cross[-4, ]), works = xa02_run(xa02_cross))
})

check("single_replicate_or_single_level_factor_is_an_error", {
  one_rep <- xa02_cross[!duplicated(xa02_cross[c("treatment", "site")]), ]
  one_level <- xa02_cross[xa02_cross$treatment == "a", ]
  expect_stops(xa02_run(one_rep), works = xa02_run(xa02_cross))
  expect_stops(xa02_run(one_level), works = xa02_run(xa02_cross))
})

check("result_has_exactly_the_documented_elements", {
  res <- value_of(xa02_run(xa02_cross))
  testthat::expect_setequal(names(res), c("anova", "cell_means", "interaction_significant",
                                          "report_level", "simple_effects"))
})
