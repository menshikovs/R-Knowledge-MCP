#### control: reference
# Trusted reference: column-selective screening, lm additive vs interaction F test, cell-contrast extraction.
investigate_study <- function(records, active_arm, control_arm, alpha = 0.05) {
  if (!is.data.frame(records)) stop("records must be a data.frame")
  req <- c("subject_id", "arm", "site", "baseline", "outcome")
  if (!all(req %in% names(records))) stop("missing required columns")
  if (!is.numeric(alpha) || length(alpha) != 1L || is.na(alpha) || alpha <= 0 || alpha >= 1) stop("bad alpha")
  if (!is.character(active_arm) || length(active_arm) != 1L || !is.character(control_arm) ||
      length(control_arm) != 1L || identical(active_arm, control_arm)) stop("bad arm labels")

  keep <- !is.na(records$arm) & !is.na(records$site) & !is.na(records$baseline) & !is.na(records$outcome)
  d <- records[keep, , drop = FALSE]
  if (nrow(d) == 0L || anyNA(d$subject_id) || anyDuplicated(d$subject_id)) stop("invalid subject_id")
  arms <- unique(as.character(d$arm))
  if (!setequal(arms, c(control_arm, active_arm))) stop("unexpected arm values")
  sites <- sort(unique(as.character(d$site)))
  if (length(sites) < 2L) stop("need at least 2 sites")
  tab <- table(d$site, d$arm)
  if (any(tab < 2L)) stop("every (site, arm) cell needs at least 2 observations")
  if (!is.numeric(d$baseline) || !is.numeric(d$outcome) || stats::sd(d$baseline) <= 0) stop("invalid numeric columns")

  d$arm_f <- factor(as.character(d$arm), levels = c(control_arm, active_arm))
  d$site_f <- factor(as.character(d$site), levels = sites)

  m_add <- stats::lm(outcome ~ baseline + site_f + arm_f, data = d)
  m_int <- stats::lm(outcome ~ baseline + site_f + site_f:arm_f, data = d)
  av <- stats::anova(m_add, m_int)
  f_val <- as.numeric(av$F[2])
  df1 <- as.numeric(av$Df[2])
  df2 <- as.numeric(av$Res.Df[2])
  p_int <- as.numeric(av$`Pr(>F)`[2])
  int_present <- isTRUE(p_int < alpha)

  cf_int <- stats::coef(summary(m_int))
  site_rows <- lapply(sites, function(s) {
    term <- paste0("site_f", s, ":arm_f", active_arm)
    est <- as.numeric(cf_int[term, "Estimate"])
    se <- as.numeric(cf_int[term, "Std. Error"])
    pval <- as.numeric(cf_int[term, "Pr(>|t|)"])
    data.frame(
      site = s,
      n_control = as.integer(sum(d$site == s & d$arm == control_arm)),
      n_active = as.integer(sum(d$site == s & d$arm == active_arm)),
      estimate = est,
      se = se,
      p_value = pval,
      stringsAsFactors = FALSE
    )
  })
  site_df <- do.call(rbind, site_rows)
  rownames(site_df) <- NULL

  pooled <- if (!int_present) {
    cf_add <- stats::coef(summary(m_add))
    term <- paste0("arm_f", active_arm)
    est <- as.numeric(cf_add[term, "Estimate"])
    se <- as.numeric(cf_add[term, "Std. Error"])
    df_a <- as.numeric(m_add$df.residual)
    pval <- as.numeric(cf_add[term, "Pr(>|t|)"])
    tcrit <- stats::qt(1 - alpha / 2, df = df_a)
    list(estimate = est, se = se, df = df_a, p_value = pval, ci_low = est - tcrit * se, ci_high = est + tcrit * se)
  } else {
    NULL
  }

  list(
    n_used = as.integer(nrow(d)),
    n_dropped = as.integer(nrow(records) - nrow(d)),
    interaction_test = list(f_value = f_val, df1 = df1, df2 = df2, p_value = p_int),
    interaction_present = int_present,
    site_effects = site_df,
    pooled_effect = pooled
  )
}

#### control: alternate_vcov_linear_combinations
# Alternate valid solution: standard site * arm parameterization with linear-combination vectors and vcov().
investigate_study <- function(records, active_arm, control_arm, alpha = 0.05) {
  stopifnot(is.data.frame(records), all(c("subject_id", "arm", "site", "baseline", "outcome") %in% names(records)),
            is.numeric(alpha), length(alpha) == 1L, !is.na(alpha), alpha > 0, alpha < 1,
            is.character(active_arm), length(active_arm) == 1L,
            is.character(control_arm), length(control_arm) == 1L, active_arm != control_arm)
  ok <- stats::complete.cases(records[, c("arm", "site", "baseline", "outcome")])
  d <- records[ok, , drop = FALSE]
  stopifnot(nrow(d) > 0L, !anyNA(d$subject_id), !anyDuplicated(d$subject_id),
            setequal(unique(as.character(d$arm)), c(control_arm, active_arm)),
            length(unique(d$site)) >= 2L, all(table(d$site, d$arm) >= 2L),
            is.numeric(d$baseline), is.numeric(d$outcome), stats::sd(d$baseline) > 0)
  sites <- sort(unique(as.character(d$site)))
  d$arm_f <- factor(as.character(d$arm), levels = c(control_arm, active_arm))
  d$site_f <- factor(as.character(d$site), levels = sites)
  m0 <- stats::lm(outcome ~ baseline + site_f + arm_f, data = d)
  m1 <- stats::lm(outcome ~ baseline + site_f * arm_f, data = d)
  rss0 <- sum(stats::resid(m0)^2)
  rss1 <- sum(stats::resid(m1)^2)
  df1 <- m0$df.residual - m1$df.residual
  df2 <- m1$df.residual
  f_val <- ((rss0 - rss1) / df1) / (rss1 / df2)
  p_int <- stats::pf(f_val, df1, df2, lower.tail = FALSE)
  b <- stats::coef(m1)
  V <- stats::vcov(m1)
  main_nm <- paste0("arm_f", active_arm)
  est <- numeric(length(sites))
  se <- numeric(length(sites))
  for (i in seq_along(sites)) {
    w <- stats::setNames(numeric(length(b)), names(b))
    w[main_nm] <- 1
    if (i > 1L) {
      int_nm <- paste0("site_f", sites[i], ":", main_nm)
      w[int_nm] <- 1
    }
    est[i] <- sum(w * b)
    se[i] <- sqrt(as.numeric(t(w) %*% V %*% w))
  }
  p_s <- 2 * stats::pt(-abs(est / se), df = df2)
  site_df <- data.frame(
    site = sites,
    n_control = as.integer(vapply(sites, function(s) sum(d$site == s & d$arm == control_arm), 0L)),
    n_active = as.integer(vapply(sites, function(s) sum(d$site == s & d$arm == active_arm), 0L)),
    estimate = est,
    se = se,
    p_value = p_s,
    stringsAsFactors = FALSE
  )
  pooled <- if (p_int >= alpha) {
    est_p <- unname(stats::coef(m0)[main_nm])
    se_p <- sqrt(stats::vcov(m0)[main_nm, main_nm])
    df_p <- as.numeric(m0$df.residual)
    tc <- stats::qt(1 - alpha / 2, df = df_p)
    list(estimate = est_p, se = se_p, df = df_p, p_value = 2 * stats::pt(-abs(est_p / se_p), df = df_p),
         ci_low = est_p - tc * se_p, ci_high = est_p + tc * se_p)
  } else NULL
  list(
    n_used = as.integer(nrow(d)),
    n_dropped = as.integer(nrow(records) - nrow(d)),
    interaction_test = list(f_value = as.numeric(f_val), df1 = as.numeric(df1), df2 = as.numeric(df2), p_value = as.numeric(p_int)),
    interaction_present = isTRUE(p_int < alpha),
    site_effects = site_df,
    pooled_effect = pooled
  )
}

#### control: wrong_na_omit_all_columns
# Plausible wrong strategy: na.omit(records) drops valid rows where only post_adherence is NA.
investigate_study <- function(records, active_arm, control_arm, alpha = 0.05) {
  stopifnot(is.data.frame(records), alpha > 0, alpha < 1, active_arm != control_arm)
  d <- stats::na.omit(records)
  stopifnot(nrow(d) > 0L, !anyDuplicated(d$subject_id),
            setequal(unique(as.character(d$arm)), c(control_arm, active_arm)),
            length(unique(d$site)) >= 2L, all(table(d$site, d$arm) >= 2L), stats::sd(d$baseline) > 0)
  sites <- sort(unique(as.character(d$site)))
  d$arm_f <- factor(as.character(d$arm), levels = c(control_arm, active_arm))
  d$site_f <- factor(as.character(d$site), levels = sites)
  m_add <- stats::lm(outcome ~ baseline + site_f + arm_f, data = d)
  m_int <- stats::lm(outcome ~ baseline + site_f + site_f:arm_f, data = d)
  av <- stats::anova(m_add, m_int)
  p_int <- as.numeric(av$`Pr(>F)`[2])
  cf_int <- stats::coef(summary(m_int))
  terms <- paste0("site_f", sites, ":arm_f", active_arm)
  site_df <- data.frame(
    site = sites,
    n_control = as.integer(vapply(sites, function(s) sum(d$site == s & d$arm == control_arm), 0L)),
    n_active = as.integer(vapply(sites, function(s) sum(d$site == s & d$arm == active_arm), 0L)),
    estimate = as.numeric(cf_int[terms, "Estimate"]),
    se = as.numeric(cf_int[terms, "Std. Error"]),
    p_value = as.numeric(cf_int[terms, "Pr(>|t|)"]),
    stringsAsFactors = FALSE
  )
  pooled <- if (p_int >= alpha) {
    cf_add <- stats::coef(summary(m_add))
    term <- paste0("arm_f", active_arm)
    est <- as.numeric(cf_add[term, "Estimate"])
    se <- as.numeric(cf_add[term, "Std. Error"])
    df_a <- as.numeric(m_add$df.residual)
    tc <- stats::qt(1 - alpha / 2, df = df_a)
    list(estimate = est, se = se, df = df_a, p_value = as.numeric(cf_add[term, "Pr(>|t|)"]),
         ci_low = est - tc * se, ci_high = est + tc * se)
  } else NULL
  list(n_used = nrow(d), n_dropped = nrow(records) - nrow(d),
       interaction_test = list(f_value = as.numeric(av$F[2]), df1 = as.numeric(av$Df[2]), df2 = as.numeric(av$Res.Df[2]), p_value = p_int),
       interaction_present = p_int < alpha, site_effects = site_df, pooled_effect = pooled)
}

#### control: wrong_separate_within_site_regressions
# Plausible wrong strategy: fits separate lm(outcome ~ baseline + arm) inside each site instead of using the joint interaction model.
investigate_study <- function(records, active_arm, control_arm, alpha = 0.05) {
  stopifnot(is.data.frame(records), alpha > 0, alpha < 1, active_arm != control_arm)
  keep <- !is.na(records$arm) & !is.na(records$site) & !is.na(records$baseline) & !is.na(records$outcome)
  d <- records[keep, , drop = FALSE]
  stopifnot(nrow(d) > 0L, !anyDuplicated(d$subject_id),
            setequal(unique(as.character(d$arm)), c(control_arm, active_arm)),
            length(unique(d$site)) >= 2L, all(table(d$site, d$arm) >= 2L), stats::sd(d$baseline) > 0)
  sites <- sort(unique(as.character(d$site)))
  d$arm_f <- factor(as.character(d$arm), levels = c(control_arm, active_arm))
  d$site_f <- factor(as.character(d$site), levels = sites)
  m_add <- stats::lm(outcome ~ baseline + site_f + arm_f, data = d)
  m_int <- stats::lm(outcome ~ baseline + site_f * arm_f, data = d)
  av <- stats::anova(m_add, m_int)
  p_int <- as.numeric(av$`Pr(>F)`[2])
  site_rows <- lapply(sites, function(s) {
    ds <- d[d$site == s, , drop = FALSE]
    ms <- stats::lm(outcome ~ baseline + arm_f, data = ds)
    cf <- stats::coef(summary(ms))[paste0("arm_f", active_arm), ]
    data.frame(site = s, n_control = sum(ds$arm == control_arm), n_active = sum(ds$arm == active_arm),
               estimate = unname(cf["Estimate"]), se = unname(cf["Std. Error"]), p_value = unname(cf["Pr(>|t|)"]),
               stringsAsFactors = FALSE)
  })
  site_df <- do.call(rbind, site_rows)
  rownames(site_df) <- NULL
  pooled <- if (p_int >= alpha) {
    cf_add <- stats::coef(summary(m_add))[paste0("arm_f", active_arm), ]
    df_a <- as.numeric(m_add$df.residual)
    tc <- stats::qt(1 - alpha / 2, df = df_a)
    list(estimate = unname(cf_add["Estimate"]), se = unname(cf_add["Std. Error"]), df = df_a,
         p_value = unname(cf_add["Pr(>|t|)"]),
         ci_low = unname(cf_add["Estimate"]) - tc * unname(cf_add["Std. Error"]),
         ci_high = unname(cf_add["Estimate"]) + tc * unname(cf_add["Std. Error"]))
  } else NULL
  list(n_used = nrow(d), n_dropped = nrow(records) - nrow(d),
       interaction_test = list(f_value = as.numeric(av$F[2]), df1 = as.numeric(av$Df[2]), df2 = as.numeric(av$Res.Df[2]), p_value = p_int),
       interaction_present = p_int < alpha, site_effects = site_df, pooled_effect = pooled)
}

#### control: wrong_always_reports_pooled_effect
# Plausible wrong strategy: always returns pooled_effect even when interaction_present is TRUE.
investigate_study <- function(records, active_arm, control_arm, alpha = 0.05) {
  stopifnot(is.data.frame(records), alpha > 0, alpha < 1, active_arm != control_arm)
  keep <- !is.na(records$arm) & !is.na(records$site) & !is.na(records$baseline) & !is.na(records$outcome)
  d <- records[keep, , drop = FALSE]
  stopifnot(nrow(d) > 0L, !anyDuplicated(d$subject_id),
            setequal(unique(as.character(d$arm)), c(control_arm, active_arm)),
            length(unique(d$site)) >= 2L, all(table(d$site, d$arm) >= 2L), stats::sd(d$baseline) > 0)
  sites <- sort(unique(as.character(d$site)))
  d$arm_f <- factor(as.character(d$arm), levels = c(control_arm, active_arm))
  d$site_f <- factor(as.character(d$site), levels = sites)
  m_add <- stats::lm(outcome ~ baseline + site_f + arm_f, data = d)
  m_int <- stats::lm(outcome ~ baseline + site_f + site_f:arm_f, data = d)
  av <- stats::anova(m_add, m_int)
  p_int <- as.numeric(av$`Pr(>F)`[2])
  cf_int <- stats::coef(summary(m_int))
  terms <- paste0("site_f", sites, ":arm_f", active_arm)
  site_df <- data.frame(
    site = sites,
    n_control = as.integer(vapply(sites, function(s) sum(d$site == s & d$arm == control_arm), 0L)),
    n_active = as.integer(vapply(sites, function(s) sum(d$site == s & d$arm == active_arm), 0L)),
    estimate = as.numeric(cf_int[terms, "Estimate"]),
    se = as.numeric(cf_int[terms, "Std. Error"]),
    p_value = as.numeric(cf_int[terms, "Pr(>|t|)"]),
    stringsAsFactors = FALSE
  )
  cf_add <- stats::coef(summary(m_add))[paste0("arm_f", active_arm), ]
  df_a <- as.numeric(m_add$df.residual)
  tc <- stats::qt(1 - alpha / 2, df = df_a)
  pooled <- list(estimate = unname(cf_add["Estimate"]), se = unname(cf_add["Std. Error"]), df = df_a,
                 p_value = unname(cf_add["Pr(>|t|)"]),
                 ci_low = unname(cf_add["Estimate"]) - tc * unname(cf_add["Std. Error"]),
                 ci_high = unname(cf_add["Estimate"]) + tc * unname(cf_add["Std. Error"]))
  list(n_used = nrow(d), n_dropped = nrow(records) - nrow(d),
       interaction_test = list(f_value = as.numeric(av$F[2]), df1 = as.numeric(av$Df[2]), df2 = as.numeric(av$Res.Df[2]), p_value = p_int),
       interaction_present = p_int < alpha, site_effects = site_df, pooled_effect = pooled)
}

#### control: edge_no_input_validation
# Boundary case: skips duplicate-subject, arm-set, cell-size and alpha validation.
# expect: fail
investigate_study <- function(records, active_arm, control_arm, alpha = 0.05) {
  keep <- !is.na(records$arm) & !is.na(records$site) & !is.na(records$baseline) & !is.na(records$outcome)
  d <- records[keep, , drop = FALSE]
  sites <- sort(unique(as.character(d$site)))
  d$arm_f <- factor(as.character(d$arm), levels = c(control_arm, active_arm))
  d$site_f <- factor(as.character(d$site), levels = sites)
  m_add <- stats::lm(outcome ~ baseline + site_f + arm_f, data = d)
  m_int <- stats::lm(outcome ~ baseline + site_f + site_f:arm_f, data = d)
  av <- stats::anova(m_add, m_int)
  p_int <- as.numeric(av$`Pr(>F)`[2])
  cf_int <- stats::coef(summary(m_int))
  terms <- paste0("site_f", sites, ":arm_f", active_arm)
  site_df <- data.frame(
    site = sites,
    n_control = as.integer(vapply(sites, function(s) sum(d$site == s & d$arm == control_arm), 0L)),
    n_active = as.integer(vapply(sites, function(s) sum(d$site == s & d$arm == active_arm), 0L)),
    estimate = as.numeric(cf_int[terms, "Estimate"]),
    se = as.numeric(cf_int[terms, "Std. Error"]),
    p_value = as.numeric(cf_int[terms, "Pr(>|t|)"]),
    stringsAsFactors = FALSE
  )
  pooled <- if (p_int >= alpha) {
    cf_add <- stats::coef(summary(m_add))[paste0("arm_f", active_arm), ]
    df_a <- as.numeric(m_add$df.residual)
    tc <- stats::qt(1 - alpha / 2, df = df_a)
    list(estimate = unname(cf_add["Estimate"]), se = unname(cf_add["Std. Error"]), df = df_a,
         p_value = unname(cf_add["Pr(>|t|)"]),
         ci_low = unname(cf_add["Estimate"]) - tc * unname(cf_add["Std. Error"]),
         ci_high = unname(cf_add["Estimate"]) + tc * unname(cf_add["Std. Error"]))
  } else NULL
  list(n_used = nrow(d), n_dropped = nrow(records) - nrow(d),
       interaction_test = list(f_value = as.numeric(av$F[2]), df1 = as.numeric(av$Df[2]), df2 = as.numeric(av$Res.Df[2]), p_value = p_int),
       interaction_present = p_int < alpha, site_effects = site_df, pooled_effect = pooled)
}

#### control: malformed_returns_lm_object
# Malformed submission: returns the fitted lm object instead of the structured report list.
# expect: fail
investigate_study <- function(records, active_arm, control_arm, alpha = 0.05) {
  stats::lm(outcome ~ baseline + site * arm, data = records)
}

