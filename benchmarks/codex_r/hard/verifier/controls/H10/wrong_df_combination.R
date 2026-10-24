# Wrong: Barnard-Rubin df adds the two components instead of combining them
# harmonically, and omits the (nu + 1) / (nu + 3) factor.
pool_estimates <- function(estimates, std_errors, conf_level = 0.95,
                           method = c("rubin1987", "barnard_rubin1999"), complete_df = NULL) {
  fail <- function(message) {
    stop(structure(class = c("pool_input_error", "error", "condition"),
                   list(message = message, call = NULL)))
  }
  methods <- c("rubin1987", "barnard_rubin1999")
  if (identical(method, methods)) method <- methods[[1]]
  if (!is.character(method) || length(method) != 1L || is.na(method) || !method %in% methods) {
    fail("`method` must be \"rubin1987\" or \"barnard_rubin1999\".")
  }
  if (!is.numeric(estimates) || !is.numeric(std_errors) || is.object(estimates) ||
      is.object(std_errors) || length(estimates) != length(std_errors) || length(estimates) < 2L) {
    fail("`estimates` and `std_errors` must be numeric vectors of equal length >= 2.")
  }
  if (!all(is.finite(estimates)) || !all(is.finite(std_errors))) fail("Inputs must be finite.")
  if (any(std_errors < 0)) fail("Standard errors must not be negative.")
  if (!is.numeric(conf_level) || length(conf_level) != 1L || !is.finite(conf_level) ||
      conf_level <= 0 || conf_level >= 1) {
    fail("`conf_level` must be a single number in (0, 1).")
  }
  if (method == "barnard_rubin1999") {
    if (!is.numeric(complete_df) || length(complete_df) != 1L || !is.finite(complete_df) ||
        complete_df <= 0) {
      fail("`complete_df` must be a single finite positive number.")
    }
  } else if (!is.null(complete_df)) {
    fail("`complete_df` is only used by barnard_rubin1999.")
  }
  m <- length(estimates)
  q <- as.double(estimates)
  u <- as.double(std_errors)
  # sum(q / m) cannot overflow even when the estimates are near the largest double.
  center <- sum(q / m)
  center <- center + sum((q - center) / m)
  d <- q - center
  largest <- max(abs(d), u)
  # Exact power-of-two scaling keeps squares representable; ratios are unaffected.
  scale <- if (largest > 0) 2^max(ceiling(log2(largest)) - 1, -1074) else 1
  ds <- d / scale
  us <- u / scale
  ubar <- mean(us^2)
  b <- sum(ds^2) / (m - 1)
  inflation <- 1 + 1 / m
  t <- ubar + inflation * b
  riv <- if (ubar > 0) inflation * b / ubar else if (b > 0) Inf else 0
  lambda <- if (t > 0) inflation * b / t else 0
  df_old <- if (b == 0) Inf else (m - 1) / lambda^2
  df <- df_old
  if (method == "barnard_rubin1999") {
    nu <- complete_df
    df_obs <- nu * (1 - lambda)
    df <- if (is.infinite(df_old)) df_obs else df_old + df_obs
  }
  fmi <- if (t == 0) 0 else if (ubar == 0) 1 else (riv + 2 / (df + 3)) / (riv + 1)
  std_error <- sqrt(t) * scale
  if (df == 0) {
    ci <- c(NA_real_, NA_real_)
  } else {
    half <- stats::qt((1 + conf_level) / 2, df) * std_error
    ci <- c(center - half, center + half)
  }
  list(
    estimate = center,
    std_error = std_error,
    df = df,
    ci_lower = ci[[1]],
    ci_upper = ci[[2]],
    within_var = ubar * scale * scale,
    between_var = b * scale * scale,
    total_var = t * scale * scale,
    riv = riv,
    lambda = lambda,
    fmi = fmi,
    m = as.integer(m),
    method = method,
    conf_level = as.double(conf_level)
  )
}
