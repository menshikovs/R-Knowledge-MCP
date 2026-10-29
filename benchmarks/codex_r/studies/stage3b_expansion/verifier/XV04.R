# Hidden checks for XV04 (density-scale histograms, current ggplot2 API, inside legend).
# Oracle: densities integrate to one per group; counts equal group sizes (base R), bin count equals
# `bins`; deprecated spellings are caught by the strict lifecycle prelude (warnings are failures).

xv04_data <- function(seed, sizes, shift, add_na = TRUE) {
  with_seed(seed, {
    d <- do.call(rbind, lapply(seq_along(sizes), function(i) {
      data.frame(value = round(stats::rnorm(sizes[i], shift[i], 1.5), 3), group = names(sizes)[i],
                 stringsAsFactors = FALSE)
    }))
    if (add_na) {
      d$value[c(3, 50)] <- NA
      d$group[7] <- NA
    }
    d[sample.int(nrow(d)), ]
  })
}

xv04_a <- xv04_data(881L, c(ctl = 90L, trt = 45L), c(0, 1.2))
xv04_b <- xv04_data(882L, c(a = 30L, b = 70L, c = 50L), c(-1, 0, 2), add_na = FALSE)

xv04_plot <- function(d, ...) call_wrapped("plot_density_histogram", d, ..., .digest = plot_digest,
                                           .prelude = lifecycle_prelude)
xv04_digest <- function(d, ...) value_of(xv04_plot(d, ...))

xv04_hist <- function(g) {
  i <- layers_of(g, "GeomBar")
  if (!length(i)) stop("no histogram layer")
  g$layers[[i[1]]]
}

xv04_clean <- function(d) d[!is.na(d$value) & !is.na(d$group), ]

local({
  stopifnot(anyNA(xv04_a$value), anyNA(xv04_a$group), length(unique(xv04_b$group)) == 3)
})

check("histogram_uses_the_requested_number_of_bins_per_group", {
  for (case in list(list(xv04_a, 10L), list(xv04_b, 7L))) {
    g <- xv04_digest(case[[1]], bins = case[[2]])
    h <- xv04_hist(g)
    testthat::expect_identical(h$stat, "StatBin")
    per_group <- tapply(h$data$xmin, h$data$group, function(z) length(unique(z)))
    testthat::expect_true(all(per_group == case[[2]]))
  }
})

check("bars_are_on_the_density_scale_so_each_group_integrates_to_one", {
  for (case in list(list(xv04_a, 10L), list(xv04_b, 8L))) {
    h <- xv04_hist(xv04_digest(case[[1]], bins = case[[2]]))
    area <- tapply(h$data$y * (h$data$xmax - h$data$xmin), h$data$group, sum)
    expect_close(unname(area), rep(1, length(area)), tol = 1e-6)
    expect_close(h$data$y, h$data$density, tol = 1e-9)
  }
})

check("counts_equal_group_sizes_after_dropping_missing_rows", {
  for (d in list(xv04_a, xv04_b)) {
    h <- xv04_hist(xv04_digest(d, bins = 9L))
    sizes <- table(xv04_clean(d)$group)
    got <- tapply(h$data$count, h$data$fill, sum)
    testthat::expect_identical(sort(as.numeric(got)), sort(as.numeric(sizes)))
  }
})

check("groups_are_overlaid_not_stacked", {
  h <- xv04_hist(xv04_digest(xv04_a))
  testthat::expect_identical(h$position, "PositionIdentity")
})

check("bars_are_filled_by_group", {
  g <- xv04_digest(xv04_b)
  h <- xv04_hist(g)
  testthat::expect_identical(sort(unique(as.character(h$mapped$fill))), c("a", "b", "c"))
})

check("a_density_curve_layer_per_group_with_a_line_width_of_at_least_0_8", {
  g <- xv04_digest(xv04_b)
  i <- layers_of(g, "GeomDensity")
  testthat::expect_true(length(i) >= 1L)
  ld <- g$layers[[i[1]]]$data
  testthat::expect_identical(length(unique(ld$group)), 3L)
  testthat::expect_true(all(ld$linewidth >= 0.8))
})

check("vertical_axis_title_is_density", {
  testthat::expect_identical(trimws(xv04_digest(xv04_a)$labels$y), "Density")
})

check("legend_is_inside_in_the_upper_right_part", {
  g <- xv04_digest(xv04_a)
  testthat::expect_identical(g$legend_position, "inside")
  testthat::expect_length(g$legend_inside, 2L)
  testthat::expect_true(all(g$legend_inside >= 0.5 & g$legend_inside <= 1))
})

check("missing_values_are_ignored", {
  h <- xv04_hist(xv04_digest(xv04_a))
  testthat::expect_false(anyNA(h$data$count))
  testthat::expect_identical(sort(unique(as.character(h$mapped$fill))), c("ctl", "trt"))
})

check("invalid_bins_are_errors", {
  works <- xv04_plot(xv04_a)
  expect_stops(xv04_plot(xv04_a, bins = 1L), works = works)
  expect_stops(xv04_plot(xv04_a, bins = 2.5), works = works)
  expect_stops(xv04_plot(xv04_a, bins = c(5L, 6L)), works = works)
  expect_stops(xv04_plot(xv04_a, bins = NA_integer_), works = works)
})

check("no_deprecation_warning_when_the_plot_is_built", {
  res <- xv04_plot(xv04_a)
  value_of(res)
  expect_no_warnings(res)
})

check("input_data_frame_is_not_modified", {
  d <- xv04_a
  res <- xv04_plot(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})
