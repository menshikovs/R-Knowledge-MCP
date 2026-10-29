# Hidden checks for XM02 (Multi-site treatment investigation with column-selective missingness
# screening, post-treatment exclusion, interaction gate and site-specific vs pooled contrasts).
#
# Independent oracle: explicit matrix-algebra OLS projection ((X'X)^-1 X'y) for the additive and
# cell-means interaction parameterizations, cross-checked at load time against stats::lm / anova.

xm02_make_data <- function(seed, site_effects, arm_labels = c("control", "active")) {
  with_seed(seed, {
    site_names <- names(site_effects)
    counts <- c(18L, 16L, 20L)
    sites <- rep(site_names, counts)
    n <- length(sites)
    arm <- unlist(lapply(counts, function(m) sample(rep(arm_labels, length.out = m))))
    base <- stats::rnorm(n, 48, 7.5)
    s_main <- stats::setNames(c(0, 3.2, -2.4), site_names)[sites]
    t_eff <- site_effects[sites] * (arm == arm_labels[2])
    y <- 15 + 0.55 * base + s_main + t_eff + stats::rnorm(n, 0, 1.9)
    # Post-treatment mediator strongly correlated with arm and outcome, and missing on 12 valid rows
    post_adh <- pmin(1, pmax(0, 0.55 + 0.22 * (arm == arm_labels[2]) + 0.03 * (y - mean(y)) + stats::rnorm(n, 0, 0.06)))
    post_adh[1:12] <- NA_real_
    df <- data.frame(
      subject_id = sprintf("S%03d", seq_len(n)),
      arm = arm,
      site = sites,
      baseline = round(base, 4),
      post_adherence = round(post_adh, 4),
      outcome = round(y, 4),
      stringsAsFactors = FALSE
    )
    # Plant 3 genuine missing values in required columns (distinct from the 12 post_adherence NAs)
    df$outcome[15L] <- NA_real_
    df$baseline[31L] <- NA_real_
    df$site[44L] <- NA_character_
    df[sample.int(nrow(df)), , drop = FALSE]
  })
}

xm02_ols <- function(X, y) {
  xtx_inv <- solve(crossprod(X))
  beta <- as.numeric(xtx_inv %*% crossprod(X, y))
  resid <- as.numeric(y - X %*% beta)
  df <- nrow(X) - ncol(X)
  rss <- sum(resid^2)
  sigma2 <- rss / df
  list(beta = beta, xtx_inv = xtx_inv, rss = rss, df = df, sigma2 = sigma2)
}

xm02_oracle <- function(records, active_arm, control_arm, alpha = 0.05) {
  keep <- !is.na(records$arm) & !is.na(records$site) & !is.na(records$baseline) & !is.na(records$outcome)
  d <- records[keep, , drop = FALSE]
  n_used <- nrow(d)
  n_dropped <- nrow(records) - n_used
  sites <- sort(unique(as.character(d$site)))
  k <- length(sites)
  act <- as.numeric(d$arm == active_arm)

  # Additive design: intercept, baseline, site indicators (2..k), active indicator
  site_mat <- sapply(sites[-1], function(s) as.numeric(d$site == s))
  X_add <- cbind(1, d$baseline, site_mat, act)
  fit_add <- xm02_ols(X_add, d$outcome)

  # Cell-indicator interaction design: baseline, then for each site s: I(site==s), I(site==s & active)
  # The coefficient on I(site==s & active) is directly the baseline-adjusted active - control contrast in site s!
  cell_cols <- do.call(cbind, lapply(sites, function(s) {
    in_s <- as.numeric(d$site == s)
    cbind(in_s, in_s * act)
  }))
  X_int <- cbind(d$baseline, cell_cols)
  fit_int <- xm02_ols(X_int, d$outcome)

  df1 <- fit_add$df - fit_int$df
  df2 <- fit_int$df
  f_val <- ((fit_add$rss - fit_int$rss) / df1) / fit_int$sigma2
  p_int <- stats::pf(f_val, df1, df2, lower.tail = FALSE)
  int_present <- isTRUE(p_int < alpha)

  # Extract site-specific contrasts (columns 3, 5, ..., 2*k + 1 of X_int)
  idx <- 1L + 2L * seq_len(k)
  est_s <- fit_int$beta[idx]
  se_s <- sqrt(diag(fit_int$xtx_inv)[idx] * fit_int$sigma2)
  p_s <- 2 * stats::pt(-abs(est_s / se_s), df = df2)
  n_ctrl <- as.integer(sapply(sites, function(s) sum(d$site == s & d$arm == control_arm)))
  n_act <- as.integer(sapply(sites, function(s) sum(d$site == s & d$arm == active_arm)))

  site_df <- data.frame(
    site = sites,
    n_control = n_ctrl,
    n_active = n_act,
    estimate = est_s,
    se = se_s,
    p_value = p_s,
    stringsAsFactors = FALSE
  )
  rownames(site_df) <- NULL

  pooled <- if (!int_present) {
    j <- ncol(X_add)
    est <- fit_add$beta[j]
    se <- sqrt(fit_add$xtx_inv[j, j] * fit_add$sigma2)
    df_a <- fit_add$df
    tcrit <- stats::qt(1 - alpha / 2, df = df_a)
    list(
      estimate = est,
      se = se,
      df = as.numeric(df_a),
      p_value = 2 * stats::pt(-abs(est / se), df = df_a),
      ci_low = est - tcrit * se,
      ci_high = est + tcrit * se
    )
  } else {
    NULL
  }

  list(
    n_used = as.integer(n_used),
    n_dropped = as.integer(n_dropped),
    interaction_test = list(
      f_value = as.numeric(f_val),
      df1 = as.numeric(df1),
      df2 = as.numeric(df2),
      p_value = as.numeric(p_int)
    ),
    interaction_present = int_present,
    site_effects = site_df,
    pooled_effect = pooled
  )
}

xm02_hom <- xm02_make_data(941L, c(alpha_site = 3.8, beta_site = 4.0, gamma_site = 3.7))
xm02_het <- xm02_make_data(942L, c(alpha_site = 6.5, beta_site = 0.8, gamma_site = -4.2), arm_labels = c("placebo", "drug"))
xm02_o_hom <- xm02_oracle(xm02_hom, "active", "control")
xm02_o_het <- xm02_oracle(xm02_het, "drug", "placebo")

# Cross-check independent matrix oracle against stats::lm and stats::anova at load time
local({
  stopifnot(!xm02_o_hom$interaction_present, !is.null(xm02_o_hom$pooled_effect))
  stopifnot(xm02_o_het$interaction_present, is.null(xm02_o_het$pooled_effect))
  stopifnot(xm02_o_hom$n_dropped == 3L, xm02_o_hom$n_used == 51L)

  d <- xm02_hom[!is.na(xm02_hom$arm) & !is.na(xm02_hom$site) & !is.na(xm02_hom$baseline) & !is.na(xm02_hom$outcome), ]
  d$arm <- factor(d$arm, levels = c("control", "active"))
  d$site <- factor(d$site)
  m_add <- stats::lm(outcome ~ baseline + site + arm, data = d)
  m_int <- stats::lm(outcome ~ baseline + site * arm, data = d)
  av <- stats::anova(m_add, m_int)
  stopifnot(isTRUE(all.equal(xm02_o_hom$interaction_test$f_value, av$F[2], tolerance = 1e-10)))
  stopifnot(isTRUE(all.equal(xm02_o_hom$pooled_effect$estimate, unname(stats::coef(m_add)["armactive"]), tolerance = 1e-10)))

  # Verify post_adherence adjustment or naive na.omit changes the answer materially
  d_na <- stats::na.omit(d)
  stopifnot(nrow(d_na) < xm02_o_hom$n_used)
  m_post <- stats::lm(outcome ~ baseline + post_adherence + site + arm, data = d_na)
  stopifnot(abs(unname(stats::coef(m_post)["armactive"]) - xm02_o_hom$pooled_effect$estimate) > 0.1)
})

xm02_call <- function(d, active = "active", control = "control", ...) {
  call_wrapped("investigate_study", d, active, control, ...)
}

xm02_check_same <- function(got, want) {
  testthat::expect_true(is.list(got))
  testthat::expect_identical(
    names(got),
    c("n_used", "n_dropped", "interaction_test", "interaction_present", "site_effects", "pooled_effect")
  )
  testthat::expect_identical(as.integer(got$n_used), want$n_used)
  testthat::expect_identical(as.integer(got$n_dropped), want$n_dropped)
  testthat::expect_identical(got$interaction_present, want$interaction_present)
  for (nm in c("f_value", "df1", "df2", "p_value")) {
    expect_close(got$interaction_test[[nm]], want$interaction_test[[nm]], tol = 1e-6, info = paste("interaction_test", nm))
  }
  se_got <- got$site_effects
  se_want <- want$site_effects
  testthat::expect_true(is.data.frame(se_got))
  testthat::expect_identical(names(se_got), c("site", "n_control", "n_active", "estimate", "se", "p_value"))
  testthat::expect_identical(as.character(se_got$site), se_want$site)
  testthat::expect_identical(as.integer(se_got$n_control), se_want$n_control)
  testthat::expect_identical(as.integer(se_got$n_active), se_want$n_active)
  for (nm in c("estimate", "se", "p_value")) {
    expect_close(se_got[[nm]], se_want[[nm]], tol = 1e-6, info = paste("site_effects", nm))
  }
  if (is.null(want$pooled_effect)) {
    testthat::expect_null(got$pooled_effect)
  } else {
    testthat::expect_true(is.list(got$pooled_effect))
    testthat::expect_identical(names(got$pooled_effect), c("estimate", "se", "df", "p_value", "ci_low", "ci_high"))
    for (nm in names(want$pooled_effect)) {
      expect_close(got$pooled_effect[[nm]], want$pooled_effect[[nm]], tol = 1e-6, info = paste("pooled_effect", nm))
    }
  }
}

check("homogeneous_sites_yield_correct_screening_interaction_and_pooled_effect", {
  xm02_check_same(value_of(xm02_call(xm02_hom)), xm02_o_hom)
})

check("post_treatment_missingness_and_values_do_not_affect_the_analysis", {
  d2 <- xm02_hom
  d2$post_adherence <- stats::rnorm(nrow(d2), 100, 50)
  d2$post_adherence[seq(1, nrow(d2), by = 2)] <- NA_real_
  xm02_check_same(value_of(xm02_call(d2)), xm02_o_hom)
})

check("heterogeneous_sites_trigger_interaction_and_suppress_pooled_effect", {
  got <- value_of(xm02_call(xm02_het, "drug", "placebo"))
  xm02_check_same(got, xm02_o_het)
  testthat::expect_true(got$interaction_present)
  testthat::expect_null(got$pooled_effect)
})

check("site_effects_use_joint_interaction_model_and_follow_contrast_direction", {
  got_fwd <- value_of(xm02_call(xm02_het, "drug", "placebo"))$site_effects
  got_rev <- value_of(xm02_call(xm02_het, "placebo", "drug"))$site_effects
  expect_close(got_fwd$estimate, xm02_o_het$site_effects$estimate, tol = 1e-6)
  expect_close(got_fwd$se, xm02_o_het$site_effects$se, tol = 1e-6)
  expect_close(got_rev$estimate, -got_fwd$estimate, tol = 1e-6)
  expect_close(got_rev$se, got_fwd$se, tol = 1e-6)
})

check("alpha_parameter_controls_interaction_decision_and_confidence_interval", {
  # Under a very strict alpha = 1e-12, even xm02_het is treated as non-significant and reports pooled_effect
  want_strict <- xm02_oracle(xm02_het, "drug", "placebo", alpha = 1e-12)
  got_strict <- value_of(xm02_call(xm02_het, "drug", "placebo", alpha = 1e-12))
  testthat::expect_false(got_strict$interaction_present)
  testthat::expect_false(is.null(got_strict$pooled_effect))
  xm02_check_same(got_strict, want_strict)

  want_90 <- xm02_oracle(xm02_hom, "active", "control", alpha = 0.10)
  got_90 <- value_of(xm02_call(xm02_hom, "active", "control", alpha = 0.10))
  xm02_check_same(got_90, want_90)
  testthat::expect_true(
    (got_90$pooled_effect$ci_high - got_90$pooled_effect$ci_low) <
      (xm02_o_hom$pooled_effect$ci_high - xm02_o_hom$pooled_effect$ci_low)
  )
})

check("result_is_invariant_to_row_order_and_site_table_has_clean_rownames", {
  d_rev <- xm02_hom[rev(seq_len(nrow(xm02_hom))), , drop = FALSE]
  got <- value_of(xm02_call(d_rev))
  xm02_check_same(got, xm02_o_hom)
  testthat::expect_false(inherits(got$site_effects, "tbl_df"))
  testthat::expect_identical(rownames(got$site_effects), as.character(seq_len(nrow(got$site_effects))))
})

check("duplicate_subjects_or_invalid_arms_stop_with_an_error", {
  works <- xm02_call(xm02_hom)
  dup <- xm02_hom
  valid_idx <- which(!is.na(dup$arm) & !is.na(dup$site) & !is.na(dup$baseline) & !is.na(dup$outcome))
  dup$subject_id[valid_idx[2]] <- dup$subject_id[valid_idx[1]]
  expect_stops(xm02_call(dup), works = works)
  expect_stops(xm02_call(xm02_hom, "unknown", "control"), works = works)
  expect_stops(xm02_call(xm02_hom, "active", "active"), works = works)
  extra_arm <- xm02_hom
  extra_arm$arm[valid_idx[1]] <- "third_arm"
  expect_stops(xm02_call(extra_arm), works = works)
})

check("small_cells_constant_baseline_or_bad_alpha_stop_with_an_error", {
  works <- xm02_call(xm02_hom)
  sparse <- xm02_hom[!(xm02_hom$site == "alpha_site" & xm02_hom$arm == "active") | seq_len(nrow(xm02_hom)) == which(xm02_hom$site == "alpha_site" & xm02_hom$arm == "active")[1], ]
  expect_stops(xm02_call(sparse), works = works)
  const_b <- xm02_hom
  const_b$baseline <- 50
  expect_stops(xm02_call(const_b), works = works)
  expect_stops(xm02_call(xm02_hom, alpha = 0), works = works)
  expect_stops(xm02_call(xm02_hom, alpha = 1), works = works)
})

check("inputs_are_not_modified_and_no_warnings", {
  d <- xm02_hom
  res <- xm02_call(d)
  value_of(res)
  expect_no_warnings(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

