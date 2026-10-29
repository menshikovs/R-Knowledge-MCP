#### control: reference
# Trusted reference using lm(), anova() and predict().
.an_prepare <- function(data) {
  need <- c("treatment", "baseline", "score")
  if (!is.data.frame(data) || !all(need %in% names(data))) stop("data needs treatment, baseline, score")
  d <- data[stats::complete.cases(data[need]), need]
  d$treatment <- factor(as.character(d$treatment))
  if (nlevels(d$treatment) < 2L || any(table(d$treatment) < 3L)) stop("insufficient groups")
  if (stats::var(d$baseline) == 0) stop("constant baseline")
  d
}

ancova_analysis <- function(data) {
  d <- .an_prepare(data)
  par <- stats::lm(score ~ baseline + treatment, data = d)
  sep <- stats::lm(score ~ baseline * treatment, data = d)
  cmp <- stats::anova(par, sep)
  slope_test <- list(f_value = cmp[["F"]][2], df1 = cmp[["Df"]][2], df2 = cmp[["Res.Df"]][2],
                     p_value = cmp[["Pr(>F)"]][2])
  homog <- slope_test$p_value >= 0.05
  xbar <- mean(d$baseline)
  tl <- levels(d$treatment)
  out <- list(slope_test = slope_test, slopes_homogeneous = homog,
              model = if (homog) "parallel" else "separate",
              treatment_test = NULL, adjusted_means = NULL, conditional_means = NULL)
  if (homog) {
    tab <- stats::anova(par)
    out$treatment_test <- list(f_value = tab[["F value"]][2], df1 = tab$Df[2], df2 = tab$Df[3],
                               p_value = tab[["Pr(>F)"]][2])
    pr <- stats::predict(par, data.frame(baseline = xbar, treatment = factor(tl, levels = tl)))
    out$adjusted_means <- data.frame(treatment = tl, adjusted_mean = unname(pr), stringsAsFactors = FALSE)
  } else {
    s <- stats::sd(d$baseline)
    at <- c(minus_1sd = xbar - s, mean = xbar, plus_1sd = xbar + s)
    grid <- data.frame(treatment = rep(tl, each = 3), at = rep(names(at), times = length(tl)),
                       baseline = rep(unname(at), times = length(tl)), stringsAsFactors = FALSE)
    fitted <- stats::predict(sep, data.frame(baseline = grid$baseline,
                                             treatment = factor(grid$treatment, levels = tl)))
    grid$fitted <- unname(fitted)
    out$conditional_means <- grid
  }
  out
}

#### control: alternate_matrix_algebra
# Alternate valid solution: explicit design matrices and RSS differences.
ancova_analysis <- function(data) {
  d <- data[!is.na(data$treatment) & !is.na(data$baseline) & !is.na(data$score), ]
  tl <- sort(unique(as.character(d$treatment)))
  a <- length(tl)
  g <- match(as.character(d$treatment), tl)
  if (a < 2 || any(tabulate(g, a) < 3) || var(d$baseline) == 0) stop("insufficient data")
  x <- d$baseline
  y <- d$score
  n <- length(y)
  D <- sapply(2:a, function(i) as.numeric(g == i))
  D <- matrix(D, n, a - 1)
  fit <- function(X) { b <- qr.solve(X, y); list(b = b, rss = sum((y - X %*% b)^2)) }
  m0 <- fit(cbind(1, x)); m1 <- fit(cbind(1, D, x)); m2 <- fit(cbind(1, D, x, D * x))
  fs <- ((m1$rss - m2$rss) / (a - 1)) / (m2$rss / (n - 2 * a))
  ps <- pf(fs, a - 1, n - 2 * a, lower.tail = FALSE)
  homog <- ps >= 0.05
  xbar <- mean(x)
  res <- list(slope_test = list(f_value = fs, df1 = a - 1, df2 = n - 2 * a, p_value = ps),
              slopes_homogeneous = homog, model = if (homog) "parallel" else "separate",
              treatment_test = NULL, adjusted_means = NULL, conditional_means = NULL)
  if (homog) {
    ft <- ((m0$rss - m1$rss) / (a - 1)) / (m1$rss / (n - a - 1))
    res$treatment_test <- list(f_value = ft, df1 = a - 1, df2 = n - a - 1,
                               p_value = pf(ft, a - 1, n - a - 1, lower.tail = FALSE))
    b <- m1$b
    res$adjusted_means <- data.frame(treatment = tl,
                                     adjusted_mean = vapply(seq_len(a), function(i) b[1] + (if (i > 1) b[i] else 0) + b[a + 1] * xbar, 0),
                                     stringsAsFactors = FALSE)
  } else {
    b <- m2$b
    s <- sd(x)
    at <- c(minus_1sd = xbar - s, mean = xbar, plus_1sd = xbar + s)
    rows <- lapply(seq_len(a), function(i) {
      ic <- b[1] + (if (i > 1) b[i] else 0)
      sl <- b[a + 1] + (if (i > 1) b[a + i] else 0)
      data.frame(treatment = tl[i], at = names(at), baseline = unname(at), fitted = unname(ic + sl * at),
                 stringsAsFactors = FALSE)
    })
    res$conditional_means <- do.call(rbind, rows)
  }
  res
}

#### control: wrong_sequential_unadjusted
# Plausible wrong strategy: treatment entered first, so its F test is not adjusted for baseline.
ancova_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "baseline", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  if (nlevels(d$treatment) < 2L || any(table(d$treatment) < 3L) || stats::var(d$baseline) == 0) stop("bad")
  par <- stats::lm(score ~ baseline + treatment, data = d)
  sep <- stats::lm(score ~ baseline * treatment, data = d)
  cmp <- stats::anova(par, sep)
  st <- list(f_value = cmp[["F"]][2], df1 = cmp[["Df"]][2], df2 = cmp[["Res.Df"]][2], p_value = cmp[["Pr(>F)"]][2])
  homog <- st$p_value >= 0.05
  xbar <- mean(d$baseline)
  tl <- levels(d$treatment)
  res <- list(slope_test = st, slopes_homogeneous = homog, model = if (homog) "parallel" else "separate",
              treatment_test = NULL, adjusted_means = NULL, conditional_means = NULL)
  if (homog) {
    tab <- stats::anova(stats::lm(score ~ treatment + baseline, data = d))
    res$treatment_test <- list(f_value = tab[["F value"]][1], df1 = tab$Df[1], df2 = tab$Df[3], p_value = tab[["Pr(>F)"]][1])
    pr <- stats::predict(par, data.frame(baseline = xbar, treatment = factor(tl, levels = tl)))
    res$adjusted_means <- data.frame(treatment = tl, adjusted_mean = unname(pr), stringsAsFactors = FALSE)
  } else {
    s <- stats::sd(d$baseline)
    at <- c(minus_1sd = xbar - s, mean = xbar, plus_1sd = xbar + s)
    grid <- data.frame(treatment = rep(tl, each = 3), at = rep(names(at), times = length(tl)),
                       baseline = rep(unname(at), times = length(tl)), stringsAsFactors = FALSE)
    grid$fitted <- unname(stats::predict(sep, data.frame(baseline = grid$baseline, treatment = factor(grid$treatment, levels = tl))))
    res$conditional_means <- grid
  }
  res
}

#### control: wrong_skips_slope_test
# Plausible wrong strategy: always runs the parallel-slopes ANCOVA, whatever the slope test says.
ancova_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "baseline", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  if (nlevels(d$treatment) < 2L || any(table(d$treatment) < 3L) || stats::var(d$baseline) == 0) stop("bad")
  par <- stats::lm(score ~ baseline + treatment, data = d)
  sep <- stats::lm(score ~ baseline * treatment, data = d)
  cmp <- stats::anova(par, sep)
  st <- list(f_value = cmp[["F"]][2], df1 = cmp[["Df"]][2], df2 = cmp[["Res.Df"]][2], p_value = cmp[["Pr(>F)"]][2])
  tab <- stats::anova(par)
  tl <- levels(d$treatment)
  pr <- stats::predict(par, data.frame(baseline = mean(d$baseline), treatment = factor(tl, levels = tl)))
  list(slope_test = st, slopes_homogeneous = TRUE, model = "parallel",
       treatment_test = list(f_value = tab[["F value"]][2], df1 = tab$Df[2], df2 = tab$Df[3], p_value = tab[["Pr(>F)"]][2]),
       adjusted_means = data.frame(treatment = tl, adjusted_mean = unname(pr), stringsAsFactors = FALSE),
       conditional_means = NULL)
}

#### control: wrong_means_at_zero_baseline
# Plausible wrong strategy: adjusted means evaluated at baseline = 0 instead of the overall mean.
ancova_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "baseline", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  if (nlevels(d$treatment) < 2L || any(table(d$treatment) < 3L) || stats::var(d$baseline) == 0) stop("bad")
  par <- stats::lm(score ~ baseline + treatment, data = d)
  sep <- stats::lm(score ~ baseline * treatment, data = d)
  cmp <- stats::anova(par, sep)
  st <- list(f_value = cmp[["F"]][2], df1 = cmp[["Df"]][2], df2 = cmp[["Res.Df"]][2], p_value = cmp[["Pr(>F)"]][2])
  homog <- st$p_value >= 0.05
  tl <- levels(d$treatment)
  res <- list(slope_test = st, slopes_homogeneous = homog, model = if (homog) "parallel" else "separate",
              treatment_test = NULL, adjusted_means = NULL, conditional_means = NULL)
  if (homog) {
    tab <- stats::anova(par)
    res$treatment_test <- list(f_value = tab[["F value"]][2], df1 = tab$Df[2], df2 = tab$Df[3], p_value = tab[["Pr(>F)"]][2])
    pr <- stats::predict(par, data.frame(baseline = 0, treatment = factor(tl, levels = tl)))
    res$adjusted_means <- data.frame(treatment = tl, adjusted_mean = unname(pr), stringsAsFactors = FALSE)
  } else {
    xbar <- mean(d$baseline)
    s <- stats::sd(d$baseline)
    at <- c(minus_1sd = xbar - s, mean = xbar, plus_1sd = xbar + s)
    grid <- data.frame(treatment = rep(tl, each = 3), at = rep(names(at), times = length(tl)),
                       baseline = rep(unname(at), times = length(tl)), stringsAsFactors = FALSE)
    grid$fitted <- unname(stats::predict(sep, data.frame(baseline = grid$baseline, treatment = factor(grid$treatment, levels = tl))))
    res$conditional_means <- grid
  }
  res
}

#### control: edge_accepts_tiny_groups
# Boundary case: right otherwise, but only requires two observations per level (no error at 2).
# expect: fail
ancova_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "baseline", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  if (nlevels(d$treatment) < 2L || stats::var(d$baseline) == 0) stop("bad")
  par <- stats::lm(score ~ baseline + treatment, data = d)
  sep <- stats::lm(score ~ baseline * treatment, data = d)
  cmp <- stats::anova(par, sep)
  st <- list(f_value = cmp[["F"]][2], df1 = cmp[["Df"]][2], df2 = cmp[["Res.Df"]][2], p_value = cmp[["Pr(>F)"]][2])
  homog <- st$p_value >= 0.05
  tl <- levels(d$treatment)
  xbar <- mean(d$baseline)
  res <- list(slope_test = st, slopes_homogeneous = homog, model = if (homog) "parallel" else "separate",
              treatment_test = NULL, adjusted_means = NULL, conditional_means = NULL)
  if (homog) {
    tab <- stats::anova(par)
    res$treatment_test <- list(f_value = tab[["F value"]][2], df1 = tab$Df[2], df2 = tab$Df[3], p_value = tab[["Pr(>F)"]][2])
    pr <- stats::predict(par, data.frame(baseline = xbar, treatment = factor(tl, levels = tl)))
    res$adjusted_means <- data.frame(treatment = tl, adjusted_mean = unname(pr), stringsAsFactors = FALSE)
  } else {
    s <- stats::sd(d$baseline)
    at <- c(minus_1sd = xbar - s, mean = xbar, plus_1sd = xbar + s)
    grid <- data.frame(treatment = rep(tl, each = 3), at = rep(names(at), times = length(tl)),
                       baseline = rep(unname(at), times = length(tl)), stringsAsFactors = FALSE)
    grid$fitted <- unname(stats::predict(sep, data.frame(baseline = grid$baseline, treatment = factor(grid$treatment, levels = tl))))
    res$conditional_means <- grid
  }
  res
}

#### control: malformed_flat_output
# Malformed submission: a flat vector instead of the documented list.
# expect: fail
ancova_analysis <- function(data) c(f = 1, p = 0.4)

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
ancova_analysis <- function(data) stop("TODO")
