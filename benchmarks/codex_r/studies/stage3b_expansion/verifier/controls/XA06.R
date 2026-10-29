#### control: reference
# Trusted reference: nlme::lme with maximum likelihood and a likelihood-ratio test.
.lt_prepare <- function(data) {
  need <- c("id", "treatment", "time", "score")
  if (!is.data.frame(data) || !all(need %in% names(data))) stop("data needs id, treatment, time, score")
  d <- data[stats::complete.cases(data[need]), need]
  d$id <- factor(as.character(d$id))
  d$treatment <- factor(as.character(d$treatment))
  d$time <- factor(as.character(d$time))
  if (nlevels(d$treatment) < 2L || nlevels(d$time) < 2L) stop("need >= 2 treatments and >= 2 visits")
  if (any(rowSums(table(d$id, d$treatment) > 0) > 1L)) stop("a participant is in two treatment arms")
  d
}

longitudinal_test <- function(data) {
  d <- .lt_prepare(data)
  full <- nlme::lme(score ~ treatment * time, random = ~ 1 | id, data = d, method = "ML")
  red <- nlme::lme(score ~ treatment + time, random = ~ 1 | id, data = d, method = "ML")
  stat <- 2 * (as.numeric(stats::logLik(full)) - as.numeric(stats::logLik(red)))
  df <- (nlevels(d$treatment) - 1) * (nlevels(d$time) - 1)
  p <- stats::pchisq(stat, df, lower.tail = FALSE)
  list(n_subjects = nlevels(d$id), n_observations = nrow(d),
       lrt = list(statistic = stat, df = df, p_value = p), significant = p < 0.05,
       random_intercept_sd = as.numeric(nlme::VarCorr(full)[1, "StdDev"]), residual_sd = full$sigma)
}

#### control: alternate_gls_compound_symmetry
# Alternate valid solution: gls() with compound-symmetry correlation (equivalent to a random
# intercept when the intraclass correlation is non-negative), fitted by ML.
longitudinal_test <- function(data) {
  d <- data[stats::complete.cases(data[c("id", "treatment", "time", "score")]), ]
  d$id <- factor(as.character(d$id))
  d$treatment <- factor(as.character(d$treatment))
  d$time <- factor(as.character(d$time))
  if (nlevels(d$treatment) < 2 || nlevels(d$time) < 2) stop("insufficient levels")
  if (any(rowSums(table(d$id, d$treatment) > 0) > 1)) stop("participant in two arms")
  cs <- nlme::corCompSymm(form = ~ 1 | id)
  full <- nlme::gls(score ~ treatment * time, data = d, correlation = cs, method = "ML")
  red <- nlme::gls(score ~ treatment + time, data = d, correlation = cs, method = "ML")
  stat <- 2 * (as.numeric(logLik(full)) - as.numeric(logLik(red)))
  df <- (nlevels(d$treatment) - 1) * (nlevels(d$time) - 1)
  p <- pchisq(stat, df, lower.tail = FALSE)
  rho <- coef(full$modelStruct$corStruct, unconstrained = FALSE)[[1]]
  s <- full$sigma
  list(n_subjects = nlevels(d$id), n_observations = nrow(d),
       lrt = list(statistic = stat, df = df, p_value = p), significant = p < 0.05,
       random_intercept_sd = s * sqrt(rho), residual_sd = s * sqrt(1 - rho))
}

#### control: wrong_complete_case_anova
# Plausible wrong strategy: classical repeated-measures ANOVA on participants who attended
# every visit (discards partial participants).
longitudinal_test <- function(data) {
  d <- data[stats::complete.cases(data[c("id", "treatment", "time", "score")]), ]
  d$id <- factor(as.character(d$id))
  d$treatment <- factor(as.character(d$treatment))
  d$time <- factor(as.character(d$time))
  if (nlevels(d$treatment) < 2 || nlevels(d$time) < 2) stop("insufficient levels")
  if (any(rowSums(table(d$id, d$treatment) > 0) > 1)) stop("participant in two arms")
  full_ids <- rownames(table(d$id, d$time))[rowSums(table(d$id, d$time) > 0) == nlevels(d$time)]
  c <- d[d$id %in% full_ids, ]
  st <- summary(stats::aov(score ~ treatment * time + Error(id), data = c))
  w <- st[["Error: Within"]][[1]]
  stat <- w[["F value"]][2]
  df <- w$Df[2]
  p <- w[["Pr(>F)"]][2]
  list(n_subjects = length(full_ids), n_observations = nrow(c),
       lrt = list(statistic = stat, df = df, p_value = p), significant = p < 0.05,
       random_intercept_sd = 1, residual_sd = 1)
}

#### control: wrong_reml_comparison
# Plausible wrong strategy: likelihood-ratio test between REML fits with different fixed effects.
longitudinal_test <- function(data) {
  d <- data[stats::complete.cases(data[c("id", "treatment", "time", "score")]), ]
  d$id <- factor(as.character(d$id))
  d$treatment <- factor(as.character(d$treatment))
  d$time <- factor(as.character(d$time))
  if (nlevels(d$treatment) < 2 || nlevels(d$time) < 2) stop("insufficient levels")
  if (any(rowSums(table(d$id, d$treatment) > 0) > 1)) stop("participant in two arms")
  full <- nlme::lme(score ~ treatment * time, random = ~ 1 | id, data = d, method = "REML")
  red <- nlme::lme(score ~ treatment + time, random = ~ 1 | id, data = d, method = "REML")
  stat <- 2 * (as.numeric(logLik(full)) - as.numeric(logLik(red)))
  df <- (nlevels(d$treatment) - 1) * (nlevels(d$time) - 1)
  p <- pchisq(stat, df, lower.tail = FALSE)
  list(n_subjects = nlevels(d$id), n_observations = nrow(d),
       lrt = list(statistic = stat, df = df, p_value = p), significant = p < 0.05,
       random_intercept_sd = as.numeric(nlme::VarCorr(full)[1, "StdDev"]), residual_sd = full$sigma)
}

#### control: wrong_ignores_clustering
# Plausible wrong strategy: ordinary least squares F test that treats all visits as independent.
longitudinal_test <- function(data) {
  d <- data[stats::complete.cases(data[c("id", "treatment", "time", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  d$time <- factor(as.character(d$time))
  if (nlevels(d$treatment) < 2 || nlevels(d$time) < 2) stop("insufficient levels")
  if (any(rowSums(table(d$id, d$treatment) > 0) > 1)) stop("participant in two arms")
  cmp <- stats::anova(stats::lm(score ~ treatment + time, data = d),
                      stats::lm(score ~ treatment * time, data = d))
  stat <- cmp[["F"]][2] * cmp$Df[2]
  df <- cmp$Df[2]
  p <- pchisq(stat, df, lower.tail = FALSE)
  list(n_subjects = length(unique(d$id)), n_observations = nrow(d),
       lrt = list(statistic = stat, df = df, p_value = p), significant = p < 0.05,
       random_intercept_sd = 0, residual_sd = sigma(stats::lm(score ~ treatment * time, data = d)))
}

#### control: edge_does_not_check_arm_membership
# Boundary case: correct on valid data but accepts a participant listed in two arms.
# expect: fail
longitudinal_test <- function(data) {
  d <- data[stats::complete.cases(data[c("id", "treatment", "time", "score")]), ]
  d$id <- factor(as.character(d$id))
  d$treatment <- factor(as.character(d$treatment))
  d$time <- factor(as.character(d$time))
  if (nlevels(d$treatment) < 2L || nlevels(d$time) < 2L) stop("insufficient levels")
  full <- nlme::lme(score ~ treatment * time, random = ~ 1 | id, data = d, method = "ML")
  red <- nlme::lme(score ~ treatment + time, random = ~ 1 | id, data = d, method = "ML")
  stat <- 2 * (as.numeric(stats::logLik(full)) - as.numeric(stats::logLik(red)))
  df <- (nlevels(d$treatment) - 1) * (nlevels(d$time) - 1)
  p <- stats::pchisq(stat, df, lower.tail = FALSE)
  list(n_subjects = nlevels(d$id), n_observations = nrow(d),
       lrt = list(statistic = stat, df = df, p_value = p), significant = p < 0.05,
       random_intercept_sd = as.numeric(nlme::VarCorr(full)[1, "StdDev"]), residual_sd = full$sigma)
}

#### control: malformed_missing_lrt
# Malformed submission: returns counts only, without the likelihood-ratio test.
# expect: fail
longitudinal_test <- function(data) list(n_subjects = length(unique(data$id)), n_observations = nrow(data))

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
longitudinal_test <- function(data) stop("TODO")
