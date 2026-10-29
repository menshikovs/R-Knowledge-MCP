#### control: reference
# Trusted reference: t.test() on the two vectors with paired = TRUE (the default method).
paired_difference <- function(data) {
  ok <- !is.na(data$before) & !is.na(data$after)
  b <- data$before[ok]
  a <- data$after[ok]
  if (length(a) < 2L || stats::sd(a - b) == 0) stop("need two or more pairs with varying differences")
  tt <- stats::t.test(a, b, paired = TRUE)
  list(n = as.integer(length(a)), mean_difference = unname(tt$estimate), sd_difference = stats::sd(a - b),
       statistic = unname(tt$statistic), df = unname(tt$parameter), p_value = tt$p.value,
       conf_low = tt$conf.int[[1]], conf_high = tt$conf.int[[2]])
}

#### control: alternate_manual_formulas
# Alternate valid solution: closed-form t statistics.
paired_difference <- function(data) {
  d <- (data$after - data$before)
  d <- d[!is.na(d)]
  n <- length(d)
  if (n < 2L || stats::var(d) == 0) stop("not enough information")
  m <- mean(d)
  se <- stats::sd(d) / sqrt(n)
  tq <- stats::qt(0.975, n - 1)
  t <- m / se
  list(n = n, mean_difference = m, sd_difference = stats::sd(d), statistic = t, df = n - 1,
       p_value = 2 * stats::pt(abs(t), n - 1, lower.tail = FALSE),
       conf_low = m - tq * se, conf_high = m + tq * se)
}

#### control: wrong_legacy_formula_paired
# The legacy code as delivered: the formula method rejects paired = TRUE in R >= 4.4.
paired_difference <- function(data) {
  long <- stack(data[c("before", "after")])
  tt <- stats::t.test(values ~ ind, data = long, paired = TRUE)
  list(n = nrow(data), mean_difference = unname(tt$estimate), p_value = tt$p.value)
}

#### control: wrong_unpaired_welch
# Plausible wrong strategy: ignores the pairing and runs Welch's two-sample t-test.
paired_difference <- function(data) {
  a <- data$after[!is.na(data$after)]
  b <- data$before[!is.na(data$before)]
  tt <- stats::t.test(a, b)
  d <- data$after - data$before
  list(n = sum(!is.na(d)), mean_difference = unname(tt$estimate[1] - tt$estimate[2]), sd_difference = stats::sd(d, na.rm = TRUE),
       statistic = unname(tt$statistic), df = unname(tt$parameter), p_value = tt$p.value,
       conf_low = tt$conf.int[[1]], conf_high = tt$conf.int[[2]])
}

#### control: wrong_sign_before_minus_after
# Plausible wrong strategy: differences taken as before - after.
paired_difference <- function(data) {
  ok <- !is.na(data$before) & !is.na(data$after)
  d <- data$before[ok] - data$after[ok]
  if (length(d) < 2L || stats::sd(d) == 0) stop("bad")
  tt <- stats::t.test(d)
  list(n = length(d), mean_difference = mean(d), sd_difference = stats::sd(d), statistic = unname(tt$statistic),
       df = unname(tt$parameter), p_value = tt$p.value, conf_low = tt$conf.int[[1]], conf_high = tt$conf.int[[2]])
}

#### control: wrong_independent_na_removal
# Plausible wrong strategy: missing values dropped per column, so participants are misaligned.
paired_difference <- function(data) {
  a <- stats::na.omit(data$after)
  b <- stats::na.omit(data$before)
  m <- min(length(a), length(b))
  d <- as.numeric(a[seq_len(m)] - b[seq_len(m)])
  tt <- stats::t.test(d)
  list(n = m, mean_difference = mean(d), sd_difference = stats::sd(d), statistic = unname(tt$statistic),
       df = unname(tt$parameter), p_value = tt$p.value, conf_low = tt$conf.int[[1]], conf_high = tt$conf.int[[2]])
}

#### control: wrong_ninety_percent_interval
# Plausible wrong strategy: the interval level is left at a different confidence level.
paired_difference <- function(data) {
  ok <- !is.na(data$before) & !is.na(data$after)
  d <- data$after[ok] - data$before[ok]
  if (length(d) < 2L || stats::sd(d) == 0) stop("bad")
  tt <- stats::t.test(d, conf.level = 0.90)
  list(n = length(d), mean_difference = mean(d), sd_difference = stats::sd(d), statistic = unname(tt$statistic),
       df = unname(tt$parameter), p_value = tt$p.value, conf_low = tt$conf.int[[1]], conf_high = tt$conf.int[[2]])
}

#### control: edge_names_left_on_values
# Boundary case: numerically right but values keep t.test()'s names (expected: not fully correct).
# expect: fail
paired_difference <- function(data) {
  ok <- !is.na(data$before) & !is.na(data$after)
  d <- data$after[ok] - data$before[ok]
  if (length(d) < 2L || stats::sd(d) == 0) stop("bad")
  tt <- stats::t.test(d)
  list(n = length(d), mean_difference = tt$estimate, sd_difference = stats::sd(d), statistic = tt$statistic,
       df = tt$parameter, p_value = tt$p.value, conf_low = tt$conf.int[[1]], conf_high = tt$conf.int[[2]])
}

#### control: malformed_returns_htest
# Malformed submission: returns the htest object.
# expect: fail
paired_difference <- function(data) stats::t.test(data$after, data$before, paired = TRUE)

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
paired_difference <- function(data) stop("todo")
