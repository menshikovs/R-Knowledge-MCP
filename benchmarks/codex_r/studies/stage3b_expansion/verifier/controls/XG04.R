#### control: reference
# Trusted reference: lm line from all finite rows, zoom through coord_cartesian.
plot_zoomed_fit <- function(data, xlim) {
  if (!is.numeric(xlim) || length(xlim) != 2L || any(!is.finite(xlim)) || xlim[1] >= xlim[2]) {
    stop("xlim must be two finite, increasing numbers")
  }
  d <- data[is.finite(data$x) & is.finite(data$y), ]
  ggplot2::ggplot(d, ggplot2::aes(x, y)) +
    ggplot2::geom_point() +
    ggplot2::geom_smooth(method = "lm", formula = y ~ x, se = FALSE) +
    ggplot2::coord_cartesian(xlim = xlim)
}

#### control: alternate_abline_from_lm
# Alternate valid solution: the line is drawn with geom_abline from an lm fit on all rows.
plot_zoomed_fit <- function(data, xlim) {
  stopifnot(is.numeric(xlim), length(xlim) == 2, all(is.finite(xlim)), xlim[1] < xlim[2])
  d <- data[is.finite(data$x) & is.finite(data$y), ]
  fit <- stats::lm(y ~ x, data = d)
  ggplot2::ggplot(d, ggplot2::aes(x = x, y = y)) +
    ggplot2::geom_point(alpha = 0.7) +
    ggplot2::geom_abline(intercept = stats::coef(fit)[[1]], slope = stats::coef(fit)[[2]]) +
    ggplot2::coord_cartesian(xlim = xlim, expand = TRUE)
}

#### control: wrong_scale_limits_drop_points
# Plausible wrong strategy: zoom with scale limits, which censors points and refits on the window.
plot_zoomed_fit <- function(data, xlim) {
  if (!is.numeric(xlim) || length(xlim) != 2L || any(!is.finite(xlim)) || xlim[1] >= xlim[2]) stop("bad xlim")
  d <- data[is.finite(data$x) & is.finite(data$y), ]
  ggplot2::ggplot(d, ggplot2::aes(x, y)) + ggplot2::geom_point() +
    ggplot2::geom_smooth(method = "lm", formula = y ~ x, se = FALSE) +
    ggplot2::scale_x_continuous(limits = xlim)
}

#### control: wrong_fit_on_window_subset
# Plausible wrong strategy: zooms through the coordinates but fits the line on the window subset.
plot_zoomed_fit <- function(data, xlim) {
  if (!is.numeric(xlim) || length(xlim) != 2L || any(!is.finite(xlim)) || xlim[1] >= xlim[2]) stop("bad xlim")
  d <- data[is.finite(data$x) & is.finite(data$y), ]
  inside <- d[d$x >= xlim[1] & d$x <= xlim[2], ]
  ggplot2::ggplot(d, ggplot2::aes(x, y)) + ggplot2::geom_point() +
    ggplot2::geom_smooth(data = inside, method = "lm", formula = y ~ x, se = FALSE) +
    ggplot2::coord_cartesian(xlim = xlim)
}

#### control: wrong_default_loess_smoother
# Plausible wrong strategy: zoom is right but geom_smooth() keeps the default (loess) curve.
plot_zoomed_fit <- function(data, xlim) {
  if (!is.numeric(xlim) || length(xlim) != 2L || any(!is.finite(xlim)) || xlim[1] >= xlim[2]) stop("bad xlim")
  d <- data[is.finite(data$x) & is.finite(data$y), ]
  ggplot2::ggplot(d, ggplot2::aes(x, y)) + ggplot2::geom_point() +
    ggplot2::geom_smooth(formula = y ~ x, method = "loess", se = FALSE) +
    ggplot2::coord_cartesian(xlim = xlim)
}

#### control: wrong_zoom_by_filtering_rows
# Plausible wrong strategy: the zoom is implemented by removing rows outside the window.
plot_zoomed_fit <- function(data, xlim) {
  if (!is.numeric(xlim) || length(xlim) != 2L || any(!is.finite(xlim)) || xlim[1] >= xlim[2]) stop("bad xlim")
  d <- data[is.finite(data$x) & is.finite(data$y) & data$x >= xlim[1] & data$x <= xlim[2], ]
  ggplot2::ggplot(d, ggplot2::aes(x, y)) + ggplot2::geom_point() +
    ggplot2::geom_smooth(method = "lm", formula = y ~ x, se = FALSE)
}

#### control: edge_no_window_validation
# Boundary case: right for valid windows but never validates xlim (expected: not fully correct).
# expect: fail
plot_zoomed_fit <- function(data, xlim) {
  d <- data[is.finite(data$x) & is.finite(data$y), ]
  ggplot2::ggplot(d, ggplot2::aes(x, y)) + ggplot2::geom_point() +
    ggplot2::geom_smooth(method = "lm", formula = y ~ x, se = FALSE) +
    ggplot2::coord_cartesian(xlim = xlim)
}

#### control: malformed_returns_coefficients
# Malformed submission: returns the regression coefficients instead of a plot.
# expect: fail
plot_zoomed_fit <- function(data, xlim) stats::coef(stats::lm(y ~ x, data))

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
plot_zoomed_fit <- function(data, xlim) stop("todo")
