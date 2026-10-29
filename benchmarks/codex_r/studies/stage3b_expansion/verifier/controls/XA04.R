#### control: reference
# Trusted reference: aov() with an Error() stratum and epsilon from the double-centred covariance.
.rm_prepare <- function(data) {
  if (!is.data.frame(data) || !all(c("subject", "time", "score") %in% names(data))) {
    stop("data needs subject, time, score")
  }
  d <- data[!is.na(data$subject) & !is.na(data$time), c("subject", "time", "score")]
  occasions <- sort(unique(as.character(d$time)))
  d <- d[!is.na(d$score), ]
  d$subject <- as.character(d$subject)
  d$time <- as.character(d$time)
  if (anyDuplicated(d[c("subject", "time")])) stop("duplicate subject x occasion")
  counts <- table(d$subject, factor(d$time, levels = occasions))
  keep <- rownames(counts)[rowSums(counts) == length(occasions)]
  d <- d[d$subject %in% keep, ]
  if (length(occasions) < 3L || length(keep) < 4L) stop("need >= 3 occasions and >= 4 subjects")
  d$subject <- factor(d$subject)
  d$time <- factor(d$time, levels = occasions)
  d
}

rm_anova <- function(data) {
  d <- .rm_prepare(data)
  k <- nlevels(d$time)
  n <- nlevels(d$subject)
  st <- summary(stats::aov(score ~ time + Error(subject / time), data = d))
  w <- st[["Error: subject:time"]][[1]]
  df1 <- w$Df[1]
  df2 <- w$Df[2]
  f <- w[["F value"]][1]
  wide <- stats::reshape(d, idvar = "subject", timevar = "time", direction = "wide")
  s <- stats::cov(as.matrix(wide[-1]))
  cm <- diag(k) - matrix(1 / k, k, k)
  ev <- eigen(cm %*% s %*% cm, symmetric = TRUE, only.values = TRUE)$values
  eps <- sum(ev)^2 / ((k - 1) * sum(ev^2))
  p <- stats::pf(f, df1, df2, lower.tail = FALSE)
  p_gg <- stats::pf(f, df1 * eps, df2 * eps, lower.tail = FALSE)
  use_gg <- eps < 0.75
  list(n_subjects = n, n_levels = k, ss_time = w[["Sum Sq"]][1], ss_error = w[["Sum Sq"]][2],
       df1 = df1, df2 = df2, f_value = f, p_value = p, epsilon_gg = eps, p_gg = p_gg,
       correction = if (use_gg) "greenhouse_geisser" else "none",
       p_primary = if (use_gg) p_gg else p)
}

#### control: alternate_matrix_formulas
# Alternate valid solution: subjects-by-occasions matrix and closed-form sums of squares.
rm_anova <- function(data) {
  d <- data[!is.na(data$subject) & !is.na(data$time), ]
  occ <- sort(unique(as.character(d$time)))
  d <- d[!is.na(d$score), ]
  key <- paste(d$subject, d$time, sep = "|")
  if (any(duplicated(key))) stop("duplicates")
  subj <- unique(as.character(d$subject))
  mat <- matrix(NA_real_, length(subj), length(occ), dimnames = list(subj, occ))
  mat[cbind(match(as.character(d$subject), subj), match(as.character(d$time), occ))] <- d$score
  mat <- mat[complete.cases(mat), , drop = FALSE]
  n <- nrow(mat)
  k <- ncol(mat)
  if (k < 3 || n < 4) stop("too little data")
  g <- mean(mat)
  sst <- n * sum((colMeans(mat) - g)^2)
  sss <- k * sum((rowMeans(mat) - g)^2)
  sse <- sum((mat - g)^2) - sst - sss
  df1 <- k - 1
  df2 <- (n - 1) * (k - 1)
  f <- sst / df1 / (sse / df2)
  S <- cov(mat)
  eps <- k^2 * (mean(diag(S)) - mean(S))^2 /
    ((k - 1) * (sum(S^2) - 2 * k * sum(rowMeans(S)^2) + k^2 * mean(S)^2))
  p <- pf(f, df1, df2, lower.tail = FALSE)
  pg <- pf(f, df1 * eps, df2 * eps, lower.tail = FALSE)
  list(n_subjects = n, n_levels = k, ss_time = sst, ss_error = sse, df1 = df1, df2 = df2,
       f_value = f, p_value = p, epsilon_gg = eps, p_gg = pg,
       correction = ifelse(eps < 0.75, "greenhouse_geisser", "none")[[1]],
       p_primary = if (eps < 0.75) pg else p)
}

#### control: wrong_independent_oneway
# Plausible wrong strategy: one-way ANOVA that treats all measurements as independent.
rm_anova <- function(data) {
  d <- data[stats::complete.cases(data[c("subject", "time", "score")]), ]
  d$time <- factor(as.character(d$time))
  k <- nlevels(d$time)
  n <- length(unique(d$subject))
  if (k < 3 || n < 4) stop("too little data")
  a <- stats::anova(stats::lm(score ~ time, data = d))
  list(n_subjects = n, n_levels = k, ss_time = a[["Sum Sq"]][1], ss_error = a[["Sum Sq"]][2],
       df1 = a$Df[1], df2 = a$Df[2], f_value = a[["F value"]][1], p_value = a[["Pr(>F)"]][1],
       epsilon_gg = 1, p_gg = a[["Pr(>F)"]][1], correction = "none", p_primary = a[["Pr(>F)"]][1])
}

#### control: wrong_no_df_adjustment
# Plausible wrong strategy: epsilon computed, but the degrees of freedom are not multiplied by it.
rm_anova <- function(data) {
  d <- data[!is.na(data$subject) & !is.na(data$time), ]
  occ <- sort(unique(as.character(d$time)))
  d <- d[!is.na(d$score), ]
  subj <- unique(as.character(d$subject))
  mat <- matrix(NA_real_, length(subj), length(occ))
  mat[cbind(match(as.character(d$subject), subj), match(as.character(d$time), occ))] <- d$score
  mat <- mat[complete.cases(mat), , drop = FALSE]
  if (anyDuplicated(paste(d$subject, d$time))) stop("duplicates")
  n <- nrow(mat)
  k <- ncol(mat)
  if (k < 3 || n < 4) stop("too little data")
  g <- mean(mat)
  sst <- n * sum((colMeans(mat) - g)^2)
  sss <- k * sum((rowMeans(mat) - g)^2)
  sse <- sum((mat - g)^2) - sst - sss
  df1 <- k - 1
  df2 <- (n - 1) * (k - 1)
  f <- sst / df1 / (sse / df2)
  S <- cov(mat)
  eps <- k^2 * (mean(diag(S)) - mean(S))^2 /
    ((k - 1) * (sum(S^2) - 2 * k * sum(rowMeans(S)^2) + k^2 * mean(S)^2))
  p <- pf(f, df1, df2, lower.tail = FALSE)
  list(n_subjects = n, n_levels = k, ss_time = sst, ss_error = sse, df1 = df1, df2 = df2,
       f_value = f, p_value = p, epsilon_gg = eps, p_gg = p, correction = if (eps < 0.75) "greenhouse_geisser" else "none",
       p_primary = p)
}

#### control: wrong_huynh_feldt
# Plausible wrong strategy: reports the Huynh-Feldt epsilon where Greenhouse-Geisser is required.
rm_anova <- function(data) {
  d <- data[!is.na(data$subject) & !is.na(data$time), ]
  occ <- sort(unique(as.character(d$time)))
  d <- d[!is.na(d$score), ]
  if (anyDuplicated(paste(d$subject, d$time))) stop("duplicates")
  subj <- unique(as.character(d$subject))
  mat <- matrix(NA_real_, length(subj), length(occ))
  mat[cbind(match(as.character(d$subject), subj), match(as.character(d$time), occ))] <- d$score
  mat <- mat[complete.cases(mat), , drop = FALSE]
  n <- nrow(mat)
  k <- ncol(mat)
  if (k < 3 || n < 4) stop("too little data")
  g <- mean(mat)
  sst <- n * sum((colMeans(mat) - g)^2)
  sss <- k * sum((rowMeans(mat) - g)^2)
  sse <- sum((mat - g)^2) - sst - sss
  df1 <- k - 1
  df2 <- (n - 1) * (k - 1)
  f <- sst / df1 / (sse / df2)
  S <- cov(mat)
  gg <- k^2 * (mean(diag(S)) - mean(S))^2 /
    ((k - 1) * (sum(S^2) - 2 * k * sum(rowMeans(S)^2) + k^2 * mean(S)^2))
  eps <- min(1, (n * (k - 1) * gg - 2) / ((k - 1) * (n - 1 - (k - 1) * gg)))
  p <- pf(f, df1, df2, lower.tail = FALSE)
  pc <- pf(f, df1 * eps, df2 * eps, lower.tail = FALSE)
  list(n_subjects = n, n_levels = k, ss_time = sst, ss_error = sse, df1 = df1, df2 = df2,
       f_value = f, p_value = p, epsilon_gg = eps, p_gg = pc,
       correction = if (eps < 0.75) "greenhouse_geisser" else "none", p_primary = if (eps < 0.75) pc else p)
}

#### control: wrong_always_corrects
# Plausible wrong strategy: always reports the corrected p-value as primary, ignoring the rule.
rm_anova <- function(data) {
  d <- data[!is.na(data$subject) & !is.na(data$time), ]
  occ <- sort(unique(as.character(d$time)))
  d <- d[!is.na(d$score), ]
  if (anyDuplicated(paste(d$subject, d$time))) stop("duplicates")
  subj <- unique(as.character(d$subject))
  mat <- matrix(NA_real_, length(subj), length(occ))
  mat[cbind(match(as.character(d$subject), subj), match(as.character(d$time), occ))] <- d$score
  mat <- mat[complete.cases(mat), , drop = FALSE]
  n <- nrow(mat)
  k <- ncol(mat)
  if (k < 3 || n < 4) stop("too little data")
  g <- mean(mat)
  sst <- n * sum((colMeans(mat) - g)^2)
  sss <- k * sum((rowMeans(mat) - g)^2)
  sse <- sum((mat - g)^2) - sst - sss
  df1 <- k - 1
  df2 <- (n - 1) * (k - 1)
  f <- sst / df1 / (sse / df2)
  S <- cov(mat)
  eps <- k^2 * (mean(diag(S)) - mean(S))^2 /
    ((k - 1) * (sum(S^2) - 2 * k * sum(rowMeans(S)^2) + k^2 * mean(S)^2))
  p <- pf(f, df1, df2, lower.tail = FALSE)
  pg <- pf(f, df1 * eps, df2 * eps, lower.tail = FALSE)
  list(n_subjects = n, n_levels = k, ss_time = sst, ss_error = sse, df1 = df1, df2 = df2,
       f_value = f, p_value = p, epsilon_gg = eps, p_gg = pg, correction = "greenhouse_geisser", p_primary = pg)
}

#### control: edge_keeps_incomplete_subjects
# Boundary case: right on complete data, but averages over available cases instead of dropping
# subjects that lack an occasion (expected: not fully correct).
# expect: fail
rm_anova <- function(data) {
  d <- data[stats::complete.cases(data[c("subject", "time", "score")]), ]
  if (anyDuplicated(paste(d$subject, d$time))) stop("duplicates")
  d$subject <- factor(as.character(d$subject))
  d$time <- factor(as.character(d$time))
  k <- nlevels(d$time)
  n <- nlevels(d$subject)
  if (k < 3 || n < 4) stop("too little data")
  st <- summary(stats::aov(score ~ time + Error(subject / time), data = d))
  w <- st[["Error: subject:time"]][[1]]
  df1 <- w$Df[1]
  df2 <- w$Df[2]
  f <- w[["F value"]][1]
  p <- stats::pf(f, df1, df2, lower.tail = FALSE)
  list(n_subjects = n, n_levels = k, ss_time = w[["Sum Sq"]][1], ss_error = w[["Sum Sq"]][2],
       df1 = df1, df2 = df2, f_value = f, p_value = p, epsilon_gg = 1, p_gg = p,
       correction = "none", p_primary = p)
}

#### control: malformed_wrong_names
# Malformed submission: returns the right idea under different element names.
# expect: fail
rm_anova <- function(data) list(F = 1, p = 0.5, eps = 0.9)

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
rm_anova <- function(data) stop("not done")
