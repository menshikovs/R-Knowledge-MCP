#### control: reference
# Trusted reference: aov/anova for the table, nested-model comparison for the simple effects.
.fa_prepare <- function(data) {
  need <- c("treatment", "site", "score")
  if (!is.data.frame(data) || !all(need %in% names(data))) stop("data needs treatment, site, score")
  d <- data[stats::complete.cases(data[need]), need]
  d$treatment <- factor(as.character(d$treatment))
  d$site <- factor(as.character(d$site))
  n <- table(d$treatment, d$site)
  if (nlevels(d$treatment) < 2L || nlevels(d$site) < 2L) stop("each factor needs two levels")
  if (any(n != n[1, 1]) || n[1, 1] < 2L) stop("design must be balanced with >= 2 per cell")
  d
}

factorial_analysis <- function(data) {
  d <- .fa_prepare(data)
  tab <- stats::anova(stats::lm(score ~ treatment * site, data = d))
  anova <- data.frame(df = tab$Df, sum_sq = tab[["Sum Sq"]], mean_sq = tab[["Mean Sq"]],
                      f_value = tab[["F value"]], p_value = tab[["Pr(>F)"]],
                      row.names = rownames(tab))
  tl <- levels(d$treatment)
  sl <- levels(d$site)
  means <- tapply(d$score, list(d$treatment, d$site), mean)
  cell <- data.frame(treatment = rep(tl, each = length(sl)), site = rep(sl, times = length(tl)),
                     mean = as.vector(t(means)), n = as.integer(table(d$treatment, d$site)[1, 1]),
                     stringsAsFactors = FALSE)
  sig <- anova["treatment:site", "p_value"] < 0.05
  simple <- NULL
  if (sig) {
    mse <- anova["Residuals", "mean_sq"]
    dfe <- anova["Residuals", "df"]
    rows <- lapply(sl, function(s) {
      sub <- d[d$site == s, ]
      m <- tapply(sub$score, sub$treatment, mean)
      r <- as.integer(table(sub$treatment)[1])
      ss <- r * sum((m - mean(sub$score))^2)
      f <- ss / (length(tl) - 1) / mse
      data.frame(site = s, df1 = length(tl) - 1, df2 = dfe, sum_sq = ss, f_value = f,
                 p_value = stats::pf(f, length(tl) - 1, dfe, lower.tail = FALSE),
                 stringsAsFactors = FALSE)
    })
    simple <- do.call(rbind, rows)
  }
  list(anova = anova, cell_means = cell, interaction_significant = sig,
       report_level = if (sig) "simple_effects" else "main_effects", simple_effects = simple)
}

#### control: alternate_closed_form
# Alternate valid solution: balanced-design formulas, simple effects via per-site SS and the full MSE.
factorial_analysis <- function(data) {
  d <- data[!is.na(data$treatment) & !is.na(data$site) & !is.na(data$score), ]
  tl <- sort(unique(as.character(d$treatment)))
  sl <- sort(unique(as.character(d$site)))
  a <- length(tl)
  b <- length(sl)
  i <- match(as.character(d$treatment), tl)
  j <- match(as.character(d$site), sl)
  cnt <- matrix(0, a, b)
  for (k in seq_len(nrow(d))) cnt[i[k], j[k]] <- cnt[i[k], j[k]] + 1
  r <- cnt[1, 1]
  if (a < 2 || b < 2 || r < 2 || any(cnt != r)) stop("unsuitable design")
  cm <- matrix(0, a, b)
  for (k in seq_len(nrow(d))) cm[i[k], j[k]] <- cm[i[k], j[k]] + d$score[k] / r
  g <- mean(d$score)
  rm <- rowMeans(cm)
  cmn <- colMeans(cm)
  ss <- c(r * b * sum((rm - g)^2), r * a * sum((cmn - g)^2), r * sum((cm - outer(rm, cmn, "+") + g)^2))
  sse <- sum((d$score - cm[cbind(i, j)])^2)
  dfe <- a * b * (r - 1)
  dfs <- c(a - 1, b - 1, (a - 1) * (b - 1))
  f <- ss / dfs / (sse / dfe)
  anova <- data.frame(df = c(dfs, dfe), sum_sq = c(ss, sse), mean_sq = c(ss / dfs, sse / dfe),
                      f_value = c(f, NA), p_value = c(pf(f, dfs, dfe, lower.tail = FALSE), NA),
                      row.names = c("treatment", "site", "treatment:site", "Residuals"))
  sig <- anova[3, "p_value"] < 0.05
  simple <- NULL
  if (sig) {
    sj <- vapply(seq_len(b), function(q) r * sum((cm[, q] - cmn[q])^2), 0)
    ff <- sj / (a - 1) / (sse / dfe)
    simple <- data.frame(site = sl, df1 = a - 1, df2 = dfe, sum_sq = sj, f_value = ff,
                         p_value = pf(ff, a - 1, dfe, lower.tail = FALSE), stringsAsFactors = FALSE)
  }
  list(anova = anova,
       cell_means = data.frame(treatment = rep(tl, each = b), site = rep(sl, times = a),
                               mean = as.vector(t(cm)), n = as.integer(r), stringsAsFactors = FALSE),
       interaction_significant = sig, report_level = if (sig) "simple_effects" else "main_effects",
       simple_effects = simple)
}

#### control: wrong_per_site_anova
# Plausible wrong strategy: a separate one-way ANOVA at each site (own error term and df).
factorial_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "site", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  d$site <- factor(as.character(d$site))
  n <- table(d$treatment, d$site)
  if (nlevels(d$treatment) < 2L || nlevels(d$site) < 2L || any(n != n[1, 1]) || n[1, 1] < 2L) stop("bad design")
  tab <- stats::anova(stats::lm(score ~ treatment * site, data = d))
  anova <- data.frame(df = tab$Df, sum_sq = tab[["Sum Sq"]], mean_sq = tab[["Mean Sq"]],
                      f_value = tab[["F value"]], p_value = tab[["Pr(>F)"]], row.names = rownames(tab))
  sl <- levels(d$site)
  tl <- levels(d$treatment)
  means <- tapply(d$score, list(d$treatment, d$site), mean)
  sig <- anova["treatment:site", "p_value"] < 0.05
  simple <- NULL
  if (sig) {
    simple <- do.call(rbind, lapply(sl, function(s) {
      t <- stats::anova(stats::lm(score ~ treatment, data = d[d$site == s, ]))
      data.frame(site = s, df1 = t$Df[1], df2 = t$Df[2], sum_sq = t[["Sum Sq"]][1],
                 f_value = t[["F value"]][1], p_value = t[["Pr(>F)"]][1], stringsAsFactors = FALSE)
    }))
  }
  list(anova = anova,
       cell_means = data.frame(treatment = rep(tl, each = length(sl)), site = rep(sl, times = length(tl)),
                               mean = as.vector(t(means)), n = as.integer(n[1, 1]), stringsAsFactors = FALSE),
       interaction_significant = sig, report_level = if (sig) "simple_effects" else "main_effects",
       simple_effects = simple)
}

#### control: wrong_ignores_interaction
# Plausible wrong strategy: additive model (no interaction term) and main effects only.
factorial_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "site", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  d$site <- factor(as.character(d$site))
  n <- table(d$treatment, d$site)
  if (nlevels(d$treatment) < 2L || nlevels(d$site) < 2L || any(n != n[1, 1]) || n[1, 1] < 2L) stop("bad design")
  tab <- stats::anova(stats::lm(score ~ treatment + site, data = d))
  anova <- data.frame(df = tab$Df, sum_sq = tab[["Sum Sq"]], mean_sq = tab[["Mean Sq"]],
                      f_value = tab[["F value"]], p_value = tab[["Pr(>F)"]], row.names = rownames(tab))
  sl <- levels(d$site)
  tl <- levels(d$treatment)
  means <- tapply(d$score, list(d$treatment, d$site), mean)
  list(anova = anova,
       cell_means = data.frame(treatment = rep(tl, each = length(sl)), site = rep(sl, times = length(tl)),
                               mean = as.vector(t(means)), n = as.integer(n[1, 1]), stringsAsFactors = FALSE),
       interaction_significant = FALSE, report_level = "main_effects", simple_effects = NULL)
}

#### control: wrong_always_reports_simple_effects
# Plausible wrong strategy: right table, but reports simple effects even without an interaction.
factorial_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "site", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  d$site <- factor(as.character(d$site))
  n <- table(d$treatment, d$site)
  if (nlevels(d$treatment) < 2L || nlevels(d$site) < 2L || any(n != n[1, 1]) || n[1, 1] < 2L) stop("bad design")
  tab <- stats::anova(stats::lm(score ~ treatment * site, data = d))
  anova <- data.frame(df = tab$Df, sum_sq = tab[["Sum Sq"]], mean_sq = tab[["Mean Sq"]],
                      f_value = tab[["F value"]], p_value = tab[["Pr(>F)"]], row.names = rownames(tab))
  sl <- levels(d$site)
  tl <- levels(d$treatment)
  means <- tapply(d$score, list(d$treatment, d$site), mean)
  mse <- anova["Residuals", "mean_sq"]
  dfe <- anova["Residuals", "df"]
  simple <- do.call(rbind, lapply(sl, function(s) {
    sub <- d[d$site == s, ]
    m <- tapply(sub$score, sub$treatment, mean)
    ss <- n[1, 1] * sum((m - mean(sub$score))^2)
    f <- ss / (length(tl) - 1) / mse
    data.frame(site = s, df1 = length(tl) - 1, df2 = dfe, sum_sq = ss, f_value = f,
               p_value = stats::pf(f, length(tl) - 1, dfe, lower.tail = FALSE), stringsAsFactors = FALSE)
  }))
  sig <- anova["treatment:site", "p_value"] < 0.05
  list(anova = anova,
       cell_means = data.frame(treatment = rep(tl, each = length(sl)), site = rep(sl, times = length(tl)),
                               mean = as.vector(t(means)), n = as.integer(n[1, 1]), stringsAsFactors = FALSE),
       interaction_significant = sig, report_level = "simple_effects", simple_effects = simple)
}

#### control: edge_accepts_unbalanced_data
# Boundary case: correct on balanced data but silently accepts unbalanced designs (no error).
# expect: fail
factorial_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "site", "score")]), ]
  d$treatment <- factor(as.character(d$treatment))
  d$site <- factor(as.character(d$site))
  n <- table(d$treatment, d$site)
  if (nlevels(d$treatment) < 2L || nlevels(d$site) < 2L) stop("bad design")
  tab <- stats::anova(stats::lm(score ~ treatment * site, data = d))
  anova <- data.frame(df = tab$Df, sum_sq = tab[["Sum Sq"]], mean_sq = tab[["Mean Sq"]],
                      f_value = tab[["F value"]], p_value = tab[["Pr(>F)"]], row.names = rownames(tab))
  sl <- levels(d$site)
  tl <- levels(d$treatment)
  means <- tapply(d$score, list(d$treatment, d$site), mean)
  sig <- anova["treatment:site", "p_value"] < 0.05
  simple <- NULL
  if (sig) {
    mse <- anova["Residuals", "mean_sq"]
    dfe <- anova["Residuals", "df"]
    simple <- do.call(rbind, lapply(sl, function(s) {
      sub <- d[d$site == s, ]
      m <- tapply(sub$score, sub$treatment, mean)
      ss <- as.integer(table(sub$treatment)[1]) * sum((m - mean(sub$score))^2)
      f <- ss / (length(tl) - 1) / mse
      data.frame(site = s, df1 = length(tl) - 1, df2 = dfe, sum_sq = ss, f_value = f,
                 p_value = stats::pf(f, length(tl) - 1, dfe, lower.tail = FALSE), stringsAsFactors = FALSE)
    }))
  }
  list(anova = anova,
       cell_means = data.frame(treatment = rep(tl, each = length(sl)), site = rep(sl, times = length(tl)),
                               mean = as.vector(t(means)), n = as.integer(n[1, 1]), stringsAsFactors = FALSE),
       interaction_significant = sig, report_level = if (sig) "simple_effects" else "main_effects",
       simple_effects = simple)
}

#### control: malformed_missing_elements
# Malformed submission: returns the ANOVA table only, without the other required elements.
# expect: fail
factorial_analysis <- function(data) {
  d <- data[stats::complete.cases(data[c("treatment", "site", "score")]), ]
  list(anova = stats::anova(stats::lm(score ~ treatment * site, data = d)))
}

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
factorial_analysis <- function(data) NULL
