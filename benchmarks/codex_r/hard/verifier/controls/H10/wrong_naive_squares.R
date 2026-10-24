# Wrong only numerically: textbook formulas on raw values, so squares and sums
# underflow or overflow for very small/large inputs.
pool_estimates <- function(estimates, std_errors, conf_level = 0.95,
                           method = c("rubin1987", "barnard_rubin1999"), complete_df = NULL) {
  fail <- function(message) {
    stop(structure(class = c("pool_input_error", "error", "condition"),
                   list(message = message, call = NULL)))
  }
  method <- tryCatch(match.arg(method), error = function(e) fail("bad method"))
  if (!is.numeric(estimates) || !is.numeric(std_errors) || length(estimates) != length(std_errors) ||
      length(estimates) < 2L || !all(is.finite(c(estimates, std_errors))) || any(std_errors < 0)) {
    fail("bad inputs")
  }
  if (!is.numeric(conf_level) || length(conf_level) != 1L || !is.finite(conf_level) ||
      conf_level <= 0 || conf_level >= 1) fail("bad conf_level")
  if (method == "barnard_rubin1999") {
    if (!is.numeric(complete_df) || length(complete_df) != 1L || !is.finite(complete_df) ||
        complete_df <= 0) fail("bad complete_df")
  } else if (!is.null(complete_df)) fail("complete_df not used")
  m <- length(estimates)
  qbar <- sum(estimates) / m
  ubar <- mean(std_errors^2)
  b <- sum((estimates - qbar)^2) / (m - 1)
  t <- ubar + (1 + 1 / m) * b
  riv <- if (ubar > 0) (1 + 1 / m) * b / ubar else if (b > 0) Inf else 0
  lambda <- if (t > 0) (1 + 1 / m) * b / t else 0
  df <- if (b == 0) Inf else (m - 1) / lambda^2
  if (method == "barnard_rubin1999") {
    obs <- (complete_df + 1) / (complete_df + 3) * complete_df * (1 - lambda)
    df <- if (is.infinite(df)) obs else df * obs / (df + obs)
  }
  fmi <- if (t == 0) 0 else if (ubar == 0) 1 else (riv + 2 / (df + 3)) / (riv + 1)
  se <- sqrt(t)
  ci <- if (df == 0) c(NA_real_, NA_real_) else qbar + c(-1, 1) * stats::qt((1 + conf_level) / 2, df) * se
  list(estimate = qbar, std_error = se, df = df, ci_lower = ci[[1]], ci_upper = ci[[2]],
       within_var = ubar, between_var = b, total_var = t, riv = riv, lambda = lambda, fmi = fmi,
       m = as.integer(m), method = method, conf_level = conf_level)
}
