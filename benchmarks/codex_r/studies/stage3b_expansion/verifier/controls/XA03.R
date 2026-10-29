#### control: reference
# Trusted reference: Type III tests via drop1() on a sum-to-zero (effect-coded) fit.
.prep3 <- function(data) {
  need <- c("treatment", "program", "score")
  if (!is.data.frame(data) || !all(need %in% names(data))) {
    stop("data must contain treatment, program and score")
  }
  d <- data[stats::complete.cases(data[need]), need, drop = FALSE]
  d$treatment <- factor(as.character(d$treatment))
  d$program <- factor(as.character(d$program))
  if (any(table(d$treatment, d$program) == 0L)) stop("every treatment x program cell needs data")
  d
}

type3_anova <- function(data) {
  d <- .prep3(data)
  fit <- stats::lm(score ~ treatment * program, data = d,
                   contrasts = list(treatment = "contr.sum", program = "contr.sum"))
  tab <- stats::drop1(fit, scope = ~ treatment + program + treatment:program, test = "F")
  terms <- c("treatment", "program", "treatment:program")
  out <- data.frame(
    df = c(tab[terms, "Df"], stats::df.residual(fit)),
    sum_sq = c(tab[terms, "Sum of Sq"], sum(stats::residuals(fit)^2)),
    row.names = c(terms, "Residuals")
  )
  out$mean_sq <- out$sum_sq / out$df
  out$f_value <- c(tab[terms, "F value"], NA_real_)
  out$p_value <- c(tab[terms, "Pr(>F)"], NA_real_)
  out
}

type1_order_dependent <- function(data) {
  d <- .prep3(data)
  ab <- stats::anova(stats::lm(score ~ treatment * program, data = d))
  ba <- stats::anova(stats::lm(score ~ program * treatment, data = d))
  differs <- function(x, y) !isTRUE(all.equal(x, y, tolerance = 1e-8))
  differs(ab["treatment", "Sum Sq"], ba["treatment", "Sum Sq"]) ||
    differs(ab["program", "Sum Sq"], ba["program", "Sum Sq"])
}

#### control: alternate_model_comparison
# Alternate valid solution: residual-SS differences between the full model and the model with a
# term's effect-coded columns removed (no drop1, no anova()).
.fit_rss <- function(X, y) {
  if (ncol(X) == 0L) return(sum(y^2))
  sum(stats::lm.fit(X, y)$residuals^2)
}

type3_anova <- function(data) {
  if (!is.data.frame(data) || !all(c("treatment", "program", "score") %in% names(data))) {
    stop("missing columns")
  }
  keep <- stats::complete.cases(data[c("treatment", "program", "score")])
  tr <- factor(as.character(data$treatment[keep]))
  pr <- factor(as.character(data$program[keep]))
  y <- data$score[keep]
  if (any(table(tr, pr) == 0)) stop("empty cell")
  xt <- stats::contr.sum(nlevels(tr))[as.integer(tr), , drop = FALSE]
  xp <- stats::contr.sum(nlevels(pr))[as.integer(pr), , drop = FALSE]
  xi <- do.call(cbind, lapply(seq_len(ncol(xt)), function(i) xt[, i] * xp))
  blocks <- list(treatment = xt, program = xp, `treatment:program` = xi)
  intercept <- matrix(1, length(y), 1)
  full <- cbind(intercept, xt, xp, xi)
  rss_full <- .fit_rss(full, y)
  df_res <- length(y) - ncol(full)
  rows <- lapply(names(blocks), function(nm) {
    others <- blocks[names(blocks) != nm]
    reduced <- cbind(intercept, do.call(cbind, others))
    ss <- .fit_rss(reduced, y) - rss_full
    d <- ncol(blocks[[nm]])
    f <- (ss / d) / (rss_full / df_res)
    c(df = d, sum_sq = ss, mean_sq = ss / d, f_value = f,
      p_value = stats::pf(f, d, df_res, lower.tail = FALSE))
  })
  out <- as.data.frame(do.call(rbind, rows))
  rownames(out) <- names(blocks)
  out["Residuals", ] <- c(df_res, rss_full, rss_full / df_res, NA, NA)
  out
}

type1_order_dependent <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "program", "score")]), ]
  d$treatment <- factor(d$treatment)
  d$program <- factor(d$program)
  seq_ss <- function(f) stats::anova(stats::lm(f, data = d))[, "Sum Sq"]
  a <- seq_ss(score ~ treatment * program)
  b <- seq_ss(score ~ program * treatment)
  !isTRUE(all.equal(a[1], b[2], tolerance = 1e-8)) || !isTRUE(all.equal(a[2], b[1], tolerance = 1e-8))
}

#### control: alternate_cell_means
# Alternate valid solution: cell-means contrasts with explicit equal-weight averaging.
type3_anova <- function(data) {
  if (!is.data.frame(data) || !all(c("treatment", "program", "score") %in% names(data))) stop("columns")
  d <- data[stats::complete.cases(data[c("treatment", "program", "score")]), ]
  tr <- factor(as.character(d$treatment))
  pr <- factor(as.character(d$program))
  a <- nlevels(tr)
  b <- nlevels(pr)
  n <- table(tr, pr)
  if (any(n == 0)) stop("empty cell")
  means <- tapply(d$score, list(tr, pr), mean)
  sse <- sum((d$score - means[cbind(as.integer(tr), as.integer(pr))])^2)
  df_res <- nrow(d) - a * b
  v <- 1 / as.vector(n)
  mu <- as.vector(means)
  cm <- function(k) cbind(diag(k - 1), -1)
  test <- function(L) {
    est <- L %*% mu
    ss <- drop(t(est) %*% solve(L %*% (v * t(L))) %*% est)
    k <- nrow(L)
    f <- ss / k / (sse / df_res)
    c(k, ss, ss / k, f, stats::pf(f, k, df_res, lower.tail = FALSE))
  }
  rows <- rbind(
    test(cm(a) %*% kronecker(t(rep(1 / b, b)), diag(a))),
    test(cm(b) %*% kronecker(diag(b), t(rep(1 / a, a)))),
    test(kronecker(cm(b), cm(a)))
  )
  out <- data.frame(df = rows[, 1], sum_sq = rows[, 2], mean_sq = rows[, 3], f_value = rows[, 4],
                    p_value = rows[, 5],
                    row.names = c("treatment", "program", "treatment:program"))
  out["Residuals", ] <- c(df_res, sse, sse / df_res, NA, NA)
  out
}

type1_order_dependent <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "program", "score")]), ]
  n <- table(d$treatment, d$program)
  # Sequential and marginal SS coincide exactly when cell sizes are proportional.
  expected <- outer(rowSums(n), colSums(n)) / sum(n)
  max(abs(n - expected)) > 1e-9
}

#### control: wrong_type1_sequential
# Plausible wrong strategy: the default sequential (Type I) ANOVA table.
type3_anova <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "program", "score")]), ]
  d$treatment <- factor(d$treatment)
  d$program <- factor(d$program)
  tab <- stats::anova(stats::lm(score ~ treatment * program, data = d))
  data.frame(df = tab$Df, sum_sq = tab$`Sum Sq`, mean_sq = tab$`Mean Sq`,
             f_value = tab$`F value`, p_value = tab$`Pr(>F)`, row.names = rownames(tab))
}
type1_order_dependent <- function(data) TRUE

#### control: wrong_type2
# Plausible wrong strategy: Type II tests (each main effect adjusted for the other only).
type3_anova <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "program", "score")]), ]
  d$treatment <- factor(d$treatment)
  d$program <- factor(d$program)
  full <- stats::anova(stats::lm(score ~ treatment * program, data = d))
  t_adj <- stats::anova(stats::lm(score ~ program + treatment, data = d))["treatment", "Sum Sq"]
  p_adj <- stats::anova(stats::lm(score ~ treatment + program, data = d))["program", "Sum Sq"]
  rss <- full["Residuals", "Sum Sq"]
  dfr <- full["Residuals", "Df"]
  ss <- c(t_adj, p_adj, full["treatment:program", "Sum Sq"])
  df <- full[c("treatment", "program", "treatment:program"), "Df"]
  f <- (ss / df) / (rss / dfr)
  data.frame(df = c(df, dfr), sum_sq = c(ss, rss), mean_sq = c(ss / df, rss / dfr),
             f_value = c(f, NA), p_value = c(stats::pf(f, df, dfr, lower.tail = FALSE), NA),
             row.names = c("treatment", "program", "treatment:program", "Residuals"))
}
type1_order_dependent <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "program", "score")]), ]
  length(unique(as.vector(table(d$treatment, d$program)))) > 1
}

#### control: wrong_treatment_contrasts
# Classic trap: drop1() on a default treatment-coded fit. With an interaction in the model the
# "main effect" rows then test effects at the reference level, not equal-weight marginal means.
type3_anova <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "program", "score")]), ]
  d$treatment <- factor(d$treatment)
  d$program <- factor(d$program)
  fit <- stats::lm(score ~ treatment * program, data = d)
  tab <- stats::drop1(fit, scope = ~ treatment + program + treatment:program, test = "F")
  terms <- c("treatment", "program", "treatment:program")
  out <- data.frame(df = c(tab[terms, "Df"], stats::df.residual(fit)),
                    sum_sq = c(tab[terms, "Sum of Sq"], sum(stats::residuals(fit)^2)),
                    row.names = c(terms, "Residuals"))
  out$mean_sq <- out$sum_sq / out$df
  out$f_value <- c(tab[terms, "F value"], NA_real_)
  out$p_value <- c(tab[terms, "Pr(>F)"], NA_real_)
  out
}
type1_order_dependent <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "program", "score")]), ]
  max(table(d$treatment, d$program)) != min(table(d$treatment, d$program))
}

#### control: edge_ignores_missing_scores
# Boundary case: correct on complete data, but refuses NA scores (expected: not fully correct).
# expect: fail
.prep <- function(data) {
  d <- data[c("treatment", "program", "score")]
  d$treatment <- factor(as.character(d$treatment))
  d$program <- factor(as.character(d$program))
  d
}
type3_anova <- function(data) {
  d <- .prep(data)
  if (anyNA(d$score)) stop("missing scores are not supported")
  fit <- stats::lm(score ~ treatment * program, data = d,
                   contrasts = list(treatment = "contr.sum", program = "contr.sum"))
  tab <- stats::drop1(fit, scope = ~ treatment + program + treatment:program, test = "F")
  terms <- c("treatment", "program", "treatment:program")
  out <- data.frame(df = c(tab[terms, "Df"], stats::df.residual(fit)),
                    sum_sq = c(tab[terms, "Sum of Sq"], sum(stats::residuals(fit)^2)),
                    row.names = c(terms, "Residuals"))
  out$mean_sq <- out$sum_sq / out$df
  out$f_value <- c(tab[terms, "F value"], NA_real_)
  out$p_value <- c(tab[terms, "Pr(>F)"], NA_real_)
  out
}
type1_order_dependent <- function(data) {
  d <- .prep(data)
  d <- d[!is.na(d$score), ]
  ab <- stats::anova(stats::lm(score ~ treatment * program, data = d))
  ba <- stats::anova(stats::lm(score ~ program * treatment, data = d))
  !isTRUE(all.equal(ab["treatment", "Sum Sq"], ba["treatment", "Sum Sq"], tolerance = 1e-8))
}

#### control: malformed_incomplete_missing_function
# Incomplete submission: only one of the two required functions exists and it does nothing.
# expect: fail
type3_anova <- function(data) {
  stop("not implemented")
}

#### control: malformed_returns_list
# Malformed submission: wrong return type (a list instead of a data frame).
# expect: fail
type3_anova <- function(data) list(treatment = 1, program = 2)
type1_order_dependent <- function(data) NA
