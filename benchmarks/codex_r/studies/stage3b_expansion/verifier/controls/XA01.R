#### control: reference
# Trusted reference built on stats::lm/anova, oneway.test, TukeyHSD and t.test.
.cg_prepare <- function(data) {
  if (!is.data.frame(data) || !all(c("group", "score") %in% names(data))) {
    stop("data needs group and score")
  }
  d <- data[stats::complete.cases(data[c("group", "score")]), c("group", "score")]
  d$group <- as.character(d$group)
  labels <- sort(unique(d$group))
  if (length(labels) < 3L) stop("at least three groups are required")
  if (any(table(d$group) < 2L)) stop("every group needs at least two observations")
  d$group <- factor(d$group, levels = labels)
  d
}

compare_groups <- function(data) {
  d <- .cg_prepare(data)
  d$dev <- stats::ave(d$score, d$group, FUN = function(x) abs(x - stats::median(x)))
  a <- stats::anova(stats::lm(dev ~ group, data = d))
  variance_test <- list(statistic = a[["F value"]][1], df1 = a$Df[1], df2 = a$Df[2],
                        p_value = a[["Pr(>F)"]][1])
  equal <- variance_test$p_value >= 0.05
  ow <- stats::oneway.test(score ~ group, data = d, var.equal = equal)
  omnibus <- list(statistic = unname(ow$statistic), df1 = unname(ow$parameter[1]),
                  df2 = unname(ow$parameter[2]), p_value = ow$p.value)
  labels <- levels(d$group)
  idx <- t(utils::combn(length(labels), 2))
  idx <- idx[order(idx[, 1], idx[, 2]), , drop = FALSE]
  means <- tapply(d$score, d$group, mean)
  diff <- unname(means[idx[, 2]] - means[idx[, 1]])
  if (equal) {
    tk <- stats::TukeyHSD(stats::aov(score ~ group, data = d))$group
    padj <- unname(tk[, "p adj"])
  } else {
    raw <- mapply(function(i, j) {
      stats::t.test(d$score[d$group == labels[j]], d$score[d$group == labels[i]],
                    var.equal = FALSE)$p.value
    }, idx[, 1], idx[, 2])
    padj <- stats::p.adjust(raw, method = "holm")
  }
  list(variance_test = variance_test, method = if (equal) "classical" else "welch",
       omnibus = omnibus,
       pairwise = data.frame(group1 = labels[idx[, 1]], group2 = labels[idx[, 2]], diff = diff,
                             p_adjusted = padj, stringsAsFactors = FALSE))
}

#### control: alternate_closed_form
# Alternate valid solution: closed-form formulas only (no model functions).
compare_groups <- function(data) {
  ok <- is.data.frame(data) && all(c("group", "score") %in% names(data))
  if (!ok) stop("data needs group and score")
  d <- data[!is.na(data$group) & !is.na(data$score), ]
  labels <- sort(unique(as.character(d$group)))
  k <- length(labels)
  y <- lapply(labels, function(l) d$score[as.character(d$group) == l])
  n <- lengths(y)
  if (k < 3 || any(n < 2)) stop("need >= 3 groups with >= 2 observations")
  Fstat <- function(groups) {
    nn <- lengths(groups)
    N <- sum(nn)
    gm <- sum(unlist(groups)) / N
    ssb <- sum(nn * (vapply(groups, mean, 0) - gm)^2)
    ssw <- sum(vapply(groups, function(g) sum((g - mean(g))^2), 0))
    f <- ssb / (length(groups) - 1) / (ssw / (N - length(groups)))
    list(statistic = f, df1 = length(groups) - 1, df2 = N - length(groups),
         p_value = pf(f, length(groups) - 1, N - length(groups), lower.tail = FALSE), mse = ssw / (N - length(groups)))
  }
  bf <- Fstat(lapply(y, function(g) abs(g - median(g))))
  equal <- bf$p_value >= 0.05
  m <- vapply(y, mean, 0)
  v <- vapply(y, var, 0)
  if (equal) {
    cl <- Fstat(y)
    omnibus <- cl[c("statistic", "df1", "df2", "p_value")]
  } else {
    w <- n / v
    mw <- sum(w * m) / sum(w)
    lam <- sum((1 - w / sum(w))^2 / (n - 1))
    f <- sum(w * (m - mw)^2) / (k - 1) / (1 + 2 * (k - 2) / (k^2 - 1) * lam)
    df2 <- (k^2 - 1) / (3 * lam)
    omnibus <- list(statistic = f, df1 = k - 1, df2 = df2, p_value = pf(f, k - 1, df2, lower.tail = FALSE))
  }
  rows <- do.call(rbind, lapply(seq_len(k - 1), function(i) cbind(i, (i + 1):k)))
  diff <- m[rows[, 2]] - m[rows[, 1]]
  if (equal) {
    q <- abs(diff) / sqrt(cl$mse / 2 * (1 / n[rows[, 1]] + 1 / n[rows[, 2]]))
    padj <- ptukey(q, nmeans = k, df = sum(n) - k, lower.tail = FALSE)
  } else {
    se2 <- v[rows[, 1]] / n[rows[, 1]] + v[rows[, 2]] / n[rows[, 2]]
    df <- se2^2 / ((v[rows[, 1]] / n[rows[, 1]])^2 / (n[rows[, 1]] - 1) + (v[rows[, 2]] / n[rows[, 2]])^2 / (n[rows[, 2]] - 1))
    padj <- p.adjust(2 * pt(abs(diff) / sqrt(se2), df, lower.tail = FALSE), "holm")
  }
  list(variance_test = bf[c("statistic", "df1", "df2", "p_value")],
       method = if (equal) "classical" else "welch", omnibus = omnibus,
       pairwise = data.frame(group1 = labels[rows[, 1]], group2 = labels[rows[, 2]],
                             diff = unname(diff), p_adjusted = unname(padj), stringsAsFactors = FALSE))
}

#### control: wrong_levene_mean_centered
# Plausible wrong strategy: Levene's test centred at the MEAN instead of the median.
compare_groups <- function(data) {
  d <- data[stats::complete.cases(data[c("group", "score")]), c("group", "score")]
  d$group <- factor(as.character(d$group))
  if (nlevels(d$group) < 3L || any(table(d$group) < 2L)) stop("insufficient data")
  d$dev <- stats::ave(d$score, d$group, FUN = function(x) abs(x - mean(x)))
  a <- stats::anova(stats::lm(dev ~ group, data = d))
  vt <- list(statistic = a[["F value"]][1], df1 = a$Df[1], df2 = a$Df[2], p_value = a[["Pr(>F)"]][1])
  equal <- vt$p_value >= 0.05
  ow <- stats::oneway.test(score ~ group, data = d, var.equal = equal)
  labels <- levels(d$group)
  idx <- t(utils::combn(length(labels), 2))
  means <- tapply(d$score, d$group, mean)
  if (equal) {
    padj <- unname(stats::TukeyHSD(stats::aov(score ~ group, data = d))$group[, "p adj"])
  } else {
    raw <- mapply(function(i, j) stats::t.test(d$score[d$group == labels[j]], d$score[d$group == labels[i]])$p.value, idx[, 1], idx[, 2])
    padj <- stats::p.adjust(raw, "holm")
  }
  list(variance_test = vt, method = if (equal) "classical" else "welch",
       omnibus = list(statistic = unname(ow$statistic), df1 = unname(ow$parameter[1]), df2 = unname(ow$parameter[2]), p_value = ow$p.value),
       pairwise = data.frame(group1 = labels[idx[, 1]], group2 = labels[idx[, 2]],
                             diff = unname(means[idx[, 2]] - means[idx[, 1]]), p_adjusted = padj,
                             stringsAsFactors = FALSE))
}

#### control: wrong_always_classical
# Plausible wrong strategy: always classical ANOVA with Tukey, ignoring the variance test result.
compare_groups <- function(data) {
  d <- data[stats::complete.cases(data[c("group", "score")]), c("group", "score")]
  d$group <- factor(as.character(d$group))
  if (nlevels(d$group) < 3L || any(table(d$group) < 2L)) stop("insufficient data")
  d$dev <- stats::ave(d$score, d$group, FUN = function(x) abs(x - stats::median(x)))
  a <- stats::anova(stats::lm(dev ~ group, data = d))
  an <- stats::anova(stats::lm(score ~ group, data = d))
  tk <- stats::TukeyHSD(stats::aov(score ~ group, data = d))$group
  labels <- levels(d$group)
  idx <- t(utils::combn(length(labels), 2))
  list(variance_test = list(statistic = a[["F value"]][1], df1 = a$Df[1], df2 = a$Df[2], p_value = a[["Pr(>F)"]][1]),
       method = "classical",
       omnibus = list(statistic = an[["F value"]][1], df1 = an$Df[1], df2 = an$Df[2], p_value = an[["Pr(>F)"]][1]),
       pairwise = data.frame(group1 = labels[idx[, 1]], group2 = labels[idx[, 2]],
                             diff = unname(tk[, "diff"]), p_adjusted = unname(tk[, "p adj"]),
                             stringsAsFactors = FALSE))
}

#### control: wrong_welch_with_pooled_tukey
# Plausible wrong strategy: right omnibus choice but pooled Tukey for the Welch branch.
compare_groups <- function(data) {
  d <- data[stats::complete.cases(data[c("group", "score")]), c("group", "score")]
  d$group <- factor(as.character(d$group))
  if (nlevels(d$group) < 3L || any(table(d$group) < 2L)) stop("insufficient data")
  d$dev <- stats::ave(d$score, d$group, FUN = function(x) abs(x - stats::median(x)))
  a <- stats::anova(stats::lm(dev ~ group, data = d))
  vt <- list(statistic = a[["F value"]][1], df1 = a$Df[1], df2 = a$Df[2], p_value = a[["Pr(>F)"]][1])
  equal <- vt$p_value >= 0.05
  ow <- stats::oneway.test(score ~ group, data = d, var.equal = equal)
  tk <- stats::TukeyHSD(stats::aov(score ~ group, data = d))$group
  labels <- levels(d$group)
  idx <- t(utils::combn(length(labels), 2))
  list(variance_test = vt, method = if (equal) "classical" else "welch",
       omnibus = list(statistic = unname(ow$statistic), df1 = unname(ow$parameter[1]), df2 = unname(ow$parameter[2]), p_value = ow$p.value),
       pairwise = data.frame(group1 = labels[idx[, 1]], group2 = labels[idx[, 2]],
                             diff = unname(tk[, "diff"]), p_adjusted = unname(tk[, "p adj"]),
                             stringsAsFactors = FALSE))
}

#### control: edge_accepts_two_groups
# Boundary case: otherwise correct, but silently accepts two groups instead of stopping.
# expect: fail
compare_groups <- function(data) {
  d <- data[stats::complete.cases(data[c("group", "score")]), c("group", "score")]
  d$group <- factor(as.character(d$group))
  if (any(table(d$group) < 2L)) stop("insufficient data")
  if (nlevels(d$group) < 2L) stop("insufficient data")
  d$dev <- stats::ave(d$score, d$group, FUN = function(x) abs(x - stats::median(x)))
  a <- stats::anova(stats::lm(dev ~ group, data = d))
  vt <- list(statistic = a[["F value"]][1], df1 = a$Df[1], df2 = a$Df[2], p_value = a[["Pr(>F)"]][1])
  equal <- vt$p_value >= 0.05
  ow <- stats::oneway.test(score ~ group, data = d, var.equal = equal)
  labels <- levels(d$group)
  idx <- t(utils::combn(length(labels), 2))
  means <- tapply(d$score, d$group, mean)
  if (equal) {
    padj <- unname(stats::TukeyHSD(stats::aov(score ~ group, data = d))$group[, "p adj"])
  } else {
    raw <- mapply(function(i, j) stats::t.test(d$score[d$group == labels[j]], d$score[d$group == labels[i]])$p.value, idx[, 1], idx[, 2])
    padj <- stats::p.adjust(raw, "holm")
  }
  list(variance_test = vt, method = if (equal) "classical" else "welch",
       omnibus = list(statistic = unname(ow$statistic), df1 = unname(ow$parameter[1]), df2 = unname(ow$parameter[2]), p_value = ow$p.value),
       pairwise = data.frame(group1 = labels[idx[, 1]], group2 = labels[idx[, 2]],
                             diff = unname(means[idx[, 2]] - means[idx[, 1]]), p_adjusted = padj,
                             stringsAsFactors = FALSE))
}

#### control: malformed_returns_vector
# Malformed submission: returns a bare numeric vector instead of the required list.
# expect: fail
compare_groups <- function(data) c(p = 0.01)

#### control: malformed_incomplete_stub
# Incomplete submission: only a stub that raises an error.
# expect: fail
compare_groups <- function(data) stop("TODO")
