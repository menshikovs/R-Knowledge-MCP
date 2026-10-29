#### control: reference
# Trusted reference: explicit trailing windows.
moving_average <- function(x, k) {
  if (!is.numeric(x) || is.factor(x)) stop("x must be numeric")
  if (!is.numeric(k) || length(k) != 1L || is.na(k) || k < 1 || k != round(k)) stop("bad k")
  n <- length(x)
  out <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    if (i >= k) out[i] <- mean(as.numeric(x[(i - k + 1):i]))
  }
  out
}

#### control: alternate_stats_filter
# Alternate valid solution: stats::filter() with a one-sided kernel.
moving_average <- function(x, k) {
  stopifnot(is.numeric(x), is.numeric(k), length(k) == 1, !is.na(k), k >= 1, k == round(k))
  if (!length(x)) return(numeric(0))
  if (k > length(x)) return(rep(NA_real_, length(x)))
  as.numeric(stats::filter(as.numeric(x), rep(1 / k, k), sides = 1))
}

#### control: wrong_legacy_code_unchanged
# The legacy code as delivered: fails when k > length(x), on empty input, and returns a shorter vector.
moving_average <- function(x, k) {
  out <- c()
  for (i in 1:(length(x) - k + 1)) {
    out[i] <- mean(x[i:(i + k - 1)])
  }
  out
}

#### control: wrong_leading_values_dropped
# Plausible wrong strategy: only complete windows are returned (a shorter vector).
moving_average <- function(x, k) {
  if (!is.numeric(x) || !is.numeric(k) || length(k) != 1L || is.na(k) || k < 1 || k != round(k)) stop("bad")
  n <- length(x)
  if (k > n) return(rep(NA_real_, n))
  vapply(seq_len(n - k + 1), function(i) mean(x[i:(i + k - 1)]), numeric(1))
}

#### control: wrong_skips_missing_values
# Plausible wrong strategy: mean(na.rm = TRUE) hides incomplete windows.
moving_average <- function(x, k) {
  if (!is.numeric(x) || !is.numeric(k) || length(k) != 1L || is.na(k) || k < 1 || k != round(k)) stop("bad")
  n <- length(x)
  out <- rep(NA_real_, n)
  for (i in seq_len(n)) if (i >= k) out[i] <- mean(x[(i - k + 1):i], na.rm = TRUE)
  out
}

#### control: wrong_cumsum_propagates_missing
# Plausible wrong strategy: a cumulative-sum trick lets one NA contaminate every later window.
moving_average <- function(x, k) {
  if (!is.numeric(x) || !is.numeric(k) || length(k) != 1L || is.na(k) || k < 1 || k != round(k)) stop("bad")
  n <- length(x)
  if (!n) return(numeric(0))
  cs <- cumsum(as.numeric(x))
  out <- rep(NA_real_, n)
  if (k <= n) {
    idx <- k:n
    out[idx] <- (cs[idx] - c(0, cs)[idx - k + 1]) / k
  }
  out
}

#### control: wrong_centered_window
# Plausible wrong strategy: a centered instead of trailing window.
moving_average <- function(x, k) {
  if (!is.numeric(x) || !is.numeric(k) || length(k) != 1L || is.na(k) || k < 1 || k != round(k)) stop("bad")
  n <- length(x)
  out <- rep(NA_real_, n)
  h <- k %/% 2
  for (i in seq_len(n)) {
    lo <- i - h
    hi <- lo + k - 1
    if (lo >= 1 && hi <= n) out[i] <- mean(x[lo:hi])
  }
  out
}

#### control: edge_keeps_names
# Boundary case: right values but names of x leak into the result (expected: not fully correct).
# expect: fail
moving_average <- function(x, k) {
  if (!is.numeric(x) || !is.numeric(k) || length(k) != 1L || is.na(k) || k < 1 || k != round(k)) stop("bad")
  out <- x * NA_real_
  for (i in seq_along(x)) if (i >= k) out[i] <- mean(x[(i - k + 1):i])
  out
}

#### control: malformed_returns_scalar
# Malformed submission: the overall mean.
# expect: fail
moving_average <- function(x, k) mean(x, na.rm = TRUE)

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
moving_average <- function(x, k) stop("todo")
