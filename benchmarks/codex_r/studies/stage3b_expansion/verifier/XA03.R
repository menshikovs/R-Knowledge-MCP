# Hidden checks for XA03 (unbalanced two-factor ANOVA, equal-weight marginal / Type III tests).
#
# Independent oracle: no lm/aov/anova. With cell means m_k and cell sizes n_k the cell-means model
# gives Var(m) = sigma^2 diag(1/n), so a linear hypothesis L m = 0 has
#   SS = (L m)' (L diag(1/n) L')^{-1} (L m).
# Main-effect hypotheses average cell means with EQUAL weights over the other factor (Type III);
# the interaction hypothesis is the Kronecker product of the two factors' difference contrasts.

xa03_levels <- function(x) sort(unique(as.character(x)))

xa03_oracle <- function(df) {
  df <- df[stats::complete.cases(df[c("treatment", "program", "score")]), , drop = FALSE]
  tl <- xa03_levels(df$treatment)
  pl <- xa03_levels(df$program)
  a <- length(tl)
  b <- length(pl)
  ti <- match(as.character(df$treatment), tl)
  pj <- match(as.character(df$program), pl)
  cell <- ti + a * (pj - 1L)                      # treatment varies fastest
  n <- tabulate(cell, nbins = a * b)
  if (any(n == 0L)) stop("empty cell")
  m <- as.vector(tapply(df$score, cell, mean))[seq_len(a * b)]
  sse <- sum((df$score - m[cell])^2)
  df_res <- nrow(df) - a * b
  mse <- sse / df_res
  contr <- function(k) cbind(diag(k - 1L), -1)     # (k-1) x k difference contrasts
  r_a <- kronecker(t(rep(1 / b, b)), diag(a))      # equal-weight treatment means
  r_b <- kronecker(diag(b), t(rep(1 / a, a)))      # equal-weight program means
  hyp <- list(
    treatment = contr(a) %*% r_a,
    program = contr(b) %*% r_b,
    `treatment:program` = kronecker(contr(b), contr(a))
  )
  rows <- lapply(hyp, function(L) {
    lm_ <- L %*% m
    ss <- drop(t(lm_) %*% solve(L %*% diag(1 / n, nrow = a * b) %*% t(L)) %*% lm_)
    d <- nrow(L)
    f <- (ss / d) / mse
    c(df = d, sum_sq = ss, mean_sq = ss / d, f_value = f,
      p_value = stats::pf(f, d, df_res, lower.tail = FALSE))
  })
  out <- as.data.frame(do.call(rbind, rows))
  out["Residuals", ] <- c(df_res, sse, mse, NA_real_, NA_real_)
  out
}

# Sequential (Type I) SS of a main effect when entered first versus second.
xa03_sequential_main <- function(df, first, second) {
  f <- stats::as.formula(paste("score ~", first, "*", second))
  tab <- stats::anova(stats::lm(f, data = df))
  c(tab[first, "Sum Sq"], tab[second, "Sum Sq"])
}
xa03_order_dependent <- function(df) {
  df <- df[stats::complete.cases(df[c("treatment", "program", "score")]), , drop = FALSE]
  df$treatment <- factor(df$treatment)
  df$program <- factor(df$program)
  ab <- xa03_sequential_main(df, "treatment", "program")
  ba <- xa03_sequential_main(df, "program", "treatment")
  isTRUE(abs(ab[1] - ba[2]) > 1e-6 * max(1, abs(ab[1])) || abs(ab[2] - ba[1]) > 1e-6 * max(1, abs(ab[2])))
}

xa03_data <- function(seed, sizes, effects = c(0, 2.5, -1), prog = c(0, 3), interaction = 4,
                      tl = c("control", "low", "high"), pl = c("A", "B")) {
  with_seed(seed, {
    a <- length(tl)
    b <- length(pl)
    stopifnot(length(sizes) == a * b)
    grid <- expand.grid(treatment = tl, program = pl, stringsAsFactors = FALSE)
    grid$n <- sizes
    parts <- lapply(seq_len(nrow(grid)), function(k) {
      i <- match(grid$treatment[k], tl)
      j <- match(grid$program[k], pl)
      mu <- 50 + effects[i] + prog[j] + if (i == 2L && j == 2L) interaction else 0
      data.frame(treatment = grid$treatment[k], program = grid$program[k],
                 score = round(mu + stats::rnorm(grid$n[k], sd = 3), 3), stringsAsFactors = FALSE)
    })
    out <- do.call(rbind, parts)
    out$participant_id <- sprintf("p%03d", sample.int(nrow(out)))
    out[sample.int(nrow(out)), c("participant_id", "treatment", "program", "score")]
  })
}

# ---- oracle self-checks (a failure here is a verifier fault, never a candidate failure) --------
local({
  bal <- xa03_data(11L, rep(6L, 6))
  o <- xa03_oracle(bal)
  classical <- stats::anova(stats::lm(score ~ treatment * program, data = bal))
  stopifnot(isTRUE(all.equal(o[c("treatment", "program", "treatment:program"), "sum_sq"],
                             classical[c("treatment", "program", "treatment:program"), "Sum Sq"],
                             check.attributes = FALSE, tolerance = 1e-9)))
  unb <- xa03_data(12L, c(4L, 9L, 7L, 12L, 6L, 5L))
  seq_tab <- stats::anova(stats::lm(score ~ treatment * program, data = unb))
  stopifnot(abs(xa03_oracle(unb)["treatment", "sum_sq"] - seq_tab["treatment", "Sum Sq"]) > 1e-3)
})

xa03_v1 <- xa03_data(101L, c(4L, 9L, 7L, 12L, 6L, 5L))
xa03_v2 <- xa03_data(102L, c(11L, 3L, 8L, 5L, 14L, 6L), effects = c(1, -2, 4), prog = c(0, -3),
                     interaction = -5, tl = c("t1", "t2", "t3"), pl = c("north", "south"))
xa03_bal <- xa03_data(103L, rep(5L, 6))
xa03_case <- function(df) call_candidate("type3_anova", df)

xa03_expect_table <- function(res, expected) {
  tab <- value_of(res)
  testthat::expect_s3_class(tab, "data.frame")
  testthat::expect_identical(rownames(tab), rownames(expected))
  testthat::expect_true(all(c("df", "sum_sq", "mean_sq", "f_value", "p_value") %in% names(tab)))
  for (col in c("df", "sum_sq", "mean_sq", "f_value", "p_value")) {
    testthat::expect_true(is.numeric(tab[[col]]), info = col)
    testthat::expect_equal(unname(tab[[col]]), unname(expected[[col]]), tolerance = 1e-6,
                           info = col)
  }
  testthat::expect_true(all(is.na(tab[["f_value"]][4]), is.na(tab[["p_value"]][4])))
}

check("unbalanced_3x2_matches_independent_type3_oracle", {
  xa03_expect_table(xa03_case(xa03_v1), xa03_oracle(xa03_v1))
})

check("second_unbalanced_design_with_other_labels_and_interaction_sign", {
  xa03_expect_table(xa03_case(xa03_v2), xa03_oracle(xa03_v2))
})

check("main_effects_are_not_the_sequential_type1_values", {
  tab <- value_of(xa03_case(xa03_v1))
  seq_tab <- stats::anova(stats::lm(score ~ treatment * program, data = xa03_v1))
  testthat::expect_gt(abs(tab["treatment", "sum_sq"] - seq_tab["treatment", "Sum Sq"]), 1e-3)
})

check("balanced_design_reduces_to_the_classical_table", {
  tab <- value_of(xa03_case(xa03_bal))
  classical <- stats::anova(stats::lm(score ~ treatment * program, data = xa03_bal))
  testthat::expect_equal(unname(tab[1:3, "sum_sq"]), unname(classical[1:3, "Sum Sq"]), tolerance = 1e-8)
  testthat::expect_equal(unname(tab[1:3, "p_value"]), unname(classical[1:3, "Pr(>F)"]), tolerance = 1e-6)
})

check("residual_row_has_error_df_ss_and_ms_with_missing_test_columns", {
  tab <- value_of(xa03_case(xa03_v1))
  testthat::expect_identical(rownames(tab)[4], "Residuals")
  testthat::expect_equal(tab["Residuals", "df"], nrow(xa03_v1) - 6)
  expected <- xa03_oracle(xa03_v1)
  testthat::expect_equal(tab["Residuals", "sum_sq"], expected["Residuals", "sum_sq"], tolerance = 1e-8)
  testthat::expect_equal(tab["Residuals", "mean_sq"], expected["Residuals", "mean_sq"], tolerance = 1e-8)
})

check("ordered_factor_inputs_do_not_switch_to_polynomial_contrasts", {
  d <- xa03_v1
  d$treatment <- factor(d$treatment, levels = c("control", "low", "high"), ordered = TRUE)
  d$program <- factor(d$program, ordered = TRUE)
  xa03_expect_table(xa03_case(d), xa03_oracle(xa03_v1))
})

check("result_is_invariant_to_row_order_and_factor_level_order", {
  d <- xa03_v1[rev(seq_len(nrow(xa03_v1))), ]
  d$treatment <- factor(d$treatment, levels = c("high", "low", "control"))
  d$program <- factor(d$program, levels = c("B", "A"))
  xa03_expect_table(xa03_case(d), xa03_oracle(xa03_v1))
})

check("missing_scores_are_dropped_listwise", {
  d <- xa03_v1
  d$score[c(3, 17, 31)] <- NA
  xa03_expect_table(xa03_case(d), xa03_oracle(d))
})

check("input_data_frame_is_not_modified", {
  d <- xa03_v1
  res <- xa03_case(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("empty_cell_is_an_error_not_a_silent_table", {
  d <- xa03_v1[!(xa03_v1$treatment == "low" & xa03_v1$program == "B"), ]
  expect_stops(xa03_case(d), works = xa03_case(xa03_v1))
})

check("missing_required_column_is_an_error", {
  expect_stops(xa03_case(xa03_v1[c("treatment", "program")]), works = xa03_case(xa03_v1))
})

check("order_dependence_of_sequential_ss_detected_for_unbalanced_only", {
  yes <- value_of(call_candidate("type1_order_dependent", xa03_v1))
  yes2 <- value_of(call_candidate("type1_order_dependent", xa03_v2))
  no <- value_of(call_candidate("type1_order_dependent", xa03_bal))
  testthat::expect_identical(c(yes, yes2, no), c(TRUE, TRUE, FALSE))
  testthat::expect_identical(c(xa03_order_dependent(xa03_v1), xa03_order_dependent(xa03_bal)),
                             c(TRUE, FALSE))
})

check("normal_input_runs_without_warnings", {
  res <- xa03_case(xa03_v1)
  value_of(res)
  expect_no_candidate_warnings(res)
})
