# Hidden checks for XG01 (daily means on a complete calendar, broken line at gaps).
# The plot is built inside the candidate session (plot_digest); only plain data comes back.

xg01_oracle <- function(df) {
  d <- df[!is.na(df$day), , drop = FALSE]
  all_days <- seq(min(d$day), max(d$day), by = "day")
  keep <- !is.na(d$score)
  m <- tapply(d$score[keep], factor(as.integer(d$day[keep]), levels = as.integer(all_days)), mean)
  data.frame(x = as.integer(all_days), y = as.numeric(m))
}

xg01_data <- function(seed, start, span, present, score_na = 0.15) {
  with_seed(seed, {
    days <- as.Date(start) + seq_len(span) - 1L
    seen <- sort(sample(days, present))
    rows <- lapply(seen, function(day) {
      data.frame(day = day, score = round(stats::rnorm(sample(1:4, 1), 50, 8), 3))
    })
    d <- do.call(rbind, rows)
    d$score[stats::runif(nrow(d)) < score_na] <- NA
    d$reading_id <- sprintf("r%03d", sample.int(nrow(d)))
    d[sample.int(nrow(d)), c("reading_id", "day", "score")]
  })
}

xg01_a <- xg01_data(801L, "2025-03-01", 30L, 17L)
xg01_b <- local({
  d <- xg01_data(802L, "2025-09-10", 24L, 15L)
  first <- sort(unique(d$day))[2]
  d$score[d$day == first] <- NA       # a day with readings but no usable score
  d
})
xg01_single <- data.frame(reading_id = c("a", "b", "c"), day = as.Date("2025-01-15"),
                          score = c(10, 20, NA))

local({
  stopifnot(sum(is.na(xg01_oracle(xg01_a)$y)) >= 6, sum(is.na(xg01_oracle(xg01_b)$y)) >= 6,
            nrow(xg01_oracle(xg01_single)) == 1, !is.na(xg01_oracle(xg01_single)$y))
  stopifnot(isTRUE(all.equal(xg01_oracle(xg01_single)$y, 15)))
})

xg01_plot <- function(df) call_wrapped("plot_daily_means", df, .digest = plot_digest)
xg01_digest <- function(df) value_of(xg01_plot(df))

xg01_line <- function(g) {
  i <- layers_of(g, c("GeomLine", "GeomPath"))
  if (!length(i)) stop("no line layer")
  g$layers[[i[1]]]
}
xg01_points <- function(g) {
  i <- layers_of(g, "GeomPoint")
  if (!length(i)) stop("no point layer")
  g$layers[[i[1]]]
}

check("line_layer_covers_every_calendar_day_with_na_on_gap_days", {
  for (d in list(xg01_a, xg01_b)) {
    ln <- xg01_line(xg01_digest(d))$data
    want <- xg01_oracle(d)
    ln <- ln[order(ln$x), ]
    testthat::expect_identical(as.integer(ln$x), want$x)
    testthat::expect_identical(is.na(ln$y), is.na(want$y))
    testthat::expect_equal(ln$y[!is.na(ln$y)], want$y[!is.na(want$y)], tolerance = 1e-9)
  }
})

check("gap_days_are_missing_not_zero_and_the_line_is_not_bridged", {
  g <- xg01_digest(xg01_a)
  ln <- xg01_line(g)
  testthat::expect_false(isTRUE(ln$geom_params$na.rm))
  testthat::expect_true(any(is.na(ln$data$y)))
  testthat::expect_false(any(ln$data$y == 0, na.rm = TRUE))
})

check("point_layer_marks_exactly_the_days_with_a_mean", {
  for (d in list(xg01_a, xg01_b)) {
    pt <- xg01_points(xg01_digest(d))$data
    pt <- pt[!is.na(pt$y), ]
    want <- xg01_oracle(d)
    want <- want[!is.na(want$y), ]
    testthat::expect_identical(as.integer(pt$x[order(pt$x)]), want$x)
    testthat::expect_equal(pt$y[order(pt$x)], want$y, tolerance = 1e-9)
  }
})

check("a_day_with_only_missing_scores_has_no_mean", {
  g <- xg01_digest(xg01_b)
  ln <- xg01_line(g)$data
  first <- sort(unique(xg01_b$day))[2]
  testthat::expect_true(is.na(ln$y[ln$x == as.integer(first)]))
  testthat::expect_false(as.integer(first) %in% xg01_points(g)$data$x[!is.na(xg01_points(g)$data$y)])
})

check("horizontal_axis_is_a_date_scale", {
  g <- xg01_digest(xg01_a)
  classes <- vapply(g$scales, function(s) paste(s$aesthetics, collapse = "/"), "")
  xs <- g$scales[[which(grepl("x", classes))[1]]]
  testthat::expect_match(xs$class, "Date")
})

check("axis_titles_are_exactly_day_and_mean_score", {
  g <- xg01_digest(xg01_a)
  testthat::expect_identical(trimws(g$labels$x), "Day")
  testthat::expect_identical(trimws(g$labels$y), "Mean score")
})

check("single_day_data_gives_one_point_and_one_line_row", {
  g <- xg01_digest(xg01_single)
  testthat::expect_identical(nrow(xg01_line(g)$data), 1L)
  testthat::expect_equal(xg01_points(g)$data$y, 15)
})

check("rows_with_missing_day_are_ignored_and_row_order_is_irrelevant", {
  d <- xg01_a
  extra <- d[1:3, ]
  extra$day <- as.Date(NA)
  d <- rbind(extra, d[rev(seq_len(nrow(d))), ])
  ln <- xg01_line(xg01_digest(d))$data
  want <- xg01_oracle(xg01_a)
  ln <- ln[order(ln$x), ]
  testthat::expect_identical(as.integer(ln$x), want$x)
  testthat::expect_equal(ln$y[!is.na(ln$y)], want$y[!is.na(want$y)], tolerance = 1e-9)
})

check("input_data_frame_is_not_modified", {
  d <- xg01_a
  res <- xg01_plot(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("plot_has_a_line_layer_and_a_point_layer", {
  g <- xg01_digest(xg01_a)
  testthat::expect_gte(length(layers_of(g, c("GeomLine", "GeomPath"))), 1L)
  testthat::expect_gte(length(layers_of(g, "GeomPoint")), 1L)
})

check("returned_object_is_a_ggplot_without_deprecation_warnings", {
  res <- xg01_plot(xg01_a)
  value_of(res)
  expect_no_lifecycle_warnings(res)
})
