# Hidden checks for XG04 (coordinate zoom versus scale limits; fit uses all finite rows).

xg04_ols <- function(d) {
  x <- d$x
  y <- d$y
  slope <- sum((x - mean(x)) * (y - mean(y))) / sum((x - mean(x))^2)
  c(slope = slope, intercept = mean(y) - slope * mean(x))
}
xg04_finite <- function(d) d[is.finite(d$x) & is.finite(d$y), , drop = FALSE]

xg04_data <- function(seed, n, lo, hi, quad, noise = 0.8, add_bad = FALSE) {
  with_seed(seed, {
    x <- round(stats::runif(n, lo, hi), 3)
    y <- round(1 + 1.2 * x + quad * x^2 + stats::rnorm(n, sd = noise), 3)
    d <- data.frame(sample_id = sprintf("s%03d", seq_len(n)), x = x, y = y)
    if (add_bad) {
      d$y[c(3, 21)] <- NA
      d$x[c(8)] <- NA
      d$x[c(30)] <- Inf
    }
    d[sample.int(nrow(d)), ]
  })
}

xg04_a <- xg04_data(831L, 120L, -2, 3, 1.8)
xg04_b <- xg04_data(832L, 80L, 0, 4, -0.6, add_bad = TRUE)
xg04_win_a <- c(-0.5, 0.5)
xg04_win_b <- c(1, 2.5)

local({
  for (case in list(list(xg04_a, xg04_win_a), list(xg04_b, xg04_win_b))) {
    d <- xg04_finite(case[[1]])
    w <- case[[2]]
    full <- xg04_ols(d)
    sub <- xg04_ols(d[d$x >= w[1] & d$x <= w[2], ])
    stopifnot(abs(full["slope"] - sub["slope"]) > 0.2, sum(d$x < w[1] | d$x > w[2]) > 10)
  }
})

xg04_plot <- function(df, win) call_wrapped("plot_zoomed_fit", df, win, .digest = plot_digest)
xg04_digest <- function(df, win) value_of(xg04_plot(df, win))

xg04_points <- function(g) {
  i <- layers_of(g, "GeomPoint")
  if (!length(i)) stop("no point layer")
  g$layers[[i[1]]]$data
}

# Slope and intercept of the plotted line, from whatever layer draws it.
xg04_line_coef <- function(g) {
  i <- layers_of(g, c("GeomSmooth", "GeomAbline", "GeomLine", "GeomPath"))
  if (!length(i)) stop("no line layer")
  ld <- g$layers[[i[1]]]$data
  if (all(c("slope", "intercept") %in% names(ld))) {
    return(c(slope = ld$slope[1], intercept = ld$intercept[1]))
  }
  ld <- ld[is.finite(ld$x) & is.finite(ld$y), ]
  if (nrow(ld) < 2L) stop("line layer has fewer than two points")
  fit <- xg04_ols(ld)
  if (max(abs(ld$y - (fit["intercept"] + fit["slope"] * ld$x))) > 1e-6 * max(1, diff(range(ld$y)))) {
    stop("the plotted line is not straight")
  }
  fit
}

check("points_include_every_finite_row_even_outside_the_window", {
  for (case in list(list(xg04_a, xg04_win_a), list(xg04_b, xg04_win_b))) {
    pts <- xg04_points(xg04_digest(case[[1]], case[[2]]))
    pts <- pts[is.finite(pts$x) & is.finite(pts$y), ]
    testthat::expect_identical(nrow(pts), nrow(xg04_finite(case[[1]])))
    testthat::expect_equal(sort(pts$x), sort(xg04_finite(case[[1]])$x), tolerance = 1e-9)
  }
})

check("regression_line_is_fitted_to_all_finite_rows", {
  for (case in list(list(xg04_a, xg04_win_a), list(xg04_b, xg04_win_b))) {
    got <- xg04_line_coef(xg04_digest(case[[1]], case[[2]]))
    want <- xg04_ols(xg04_finite(case[[1]]))
    testthat::expect_equal(unname(got["slope"]), unname(want["slope"]), tolerance = 1e-6)
    testthat::expect_equal(unname(got["intercept"]), unname(want["intercept"]), tolerance = 1e-6)
  }
})

check("line_is_not_the_fit_to_the_window_subset", {
  d <- xg04_finite(xg04_a)
  sub <- xg04_ols(d[d$x >= xg04_win_a[1] & d$x <= xg04_win_a[2], ])
  got <- xg04_line_coef(xg04_digest(xg04_a, xg04_win_a))
  testthat::expect_gt(abs(unname(got["slope"]) - unname(sub["slope"])), 0.1)
})

check("zoom_is_applied_through_the_coordinate_system", {
  g <- xg04_digest(xg04_a, xg04_win_a)
  testthat::expect_identical(g$coord, "CoordCartesian")
  testthat::expect_equal(as.numeric(g$coord_limits$x), xg04_win_a, tolerance = 1e-9)
})

check("horizontal_scale_has_no_limits_that_censor_observations", {
  g <- xg04_digest(xg04_a, xg04_win_a)
  testthat::expect_false(anyNA(xg04_points(g)$x[is.finite(xg04_finite(xg04_a)$x)]))
  xs <- g$position$x
  testthat::expect_gte(xs$range[1], min(xg04_finite(xg04_a)$x) - 1e-9)
  testthat::expect_lte(xs$range[2], max(xg04_finite(xg04_a)$x) + 1e-9)
})

check("visible_horizontal_range_is_the_window_plus_default_expansion", {
  for (case in list(list(xg04_a, xg04_win_a), list(xg04_b, xg04_win_b))) {
    g <- xg04_digest(case[[1]], case[[2]])
    w <- case[[2]]
    pad <- 0.06 * diff(w)
    testthat::expect_gte(g$panel_x_range[1], w[1] - pad)
    testthat::expect_lte(g$panel_x_range[1], w[1])
    testthat::expect_lte(g$panel_x_range[2], w[2] + pad)
    testthat::expect_gte(g$panel_x_range[2], w[2])
  }
})

check("rows_with_missing_or_infinite_values_are_ignored", {
  pts <- xg04_points(xg04_digest(xg04_b, xg04_win_b))
  testthat::expect_false(any(is.infinite(pts$x), na.rm = TRUE))
  got <- xg04_line_coef(xg04_digest(xg04_b, xg04_win_b))
  testthat::expect_equal(unname(got["slope"]), unname(xg04_ols(xg04_finite(xg04_b))["slope"]), tolerance = 1e-6)
})

check("a_different_window_changes_the_view_but_not_the_line", {
  other <- c(-1.5, -0.5)
  a <- xg04_line_coef(xg04_digest(xg04_a, xg04_win_a))
  b <- xg04_line_coef(xg04_digest(xg04_a, other))
  testthat::expect_equal(unname(a["slope"]), unname(b["slope"]), tolerance = 1e-6)
  testthat::expect_equal(as.numeric(xg04_digest(xg04_a, other)$coord_limits$x), other, tolerance = 1e-9)
})

check("invalid_windows_are_errors", {
  works <- xg04_plot(xg04_a, xg04_win_a)
  expect_stops(xg04_plot(xg04_a, c(1, 1)), works = works)
  expect_stops(xg04_plot(xg04_a, c(2, -2)), works = works)
  expect_stops(xg04_plot(xg04_a, 1), works = works)
  expect_stops(xg04_plot(xg04_a, c(NA, 1)), works = works)
  expect_stops(xg04_plot(xg04_a, c(0, Inf)), works = works)
})

check("input_data_frame_is_not_modified", {
  d <- xg04_b
  res <- xg04_plot(d, xg04_win_b)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("no_deprecation_warnings", {
  res <- xg04_plot(xg04_a, xg04_win_a)
  value_of(res)
  expect_no_lifecycle_warnings(res)
})
