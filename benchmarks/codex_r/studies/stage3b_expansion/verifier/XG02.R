# Hidden checks for XG02 (group-mean bars; missing values; axis hygiene).

xg02_oracle <- function(df) {
  d <- df[!is.na(df$group), , drop = FALSE]
  present <- if (is.factor(d$group)) levels(droplevels(d$group)) else sort(unique(as.character(d$group)))
  g <- as.character(d$group)
  means <- vapply(present, function(l) {
    v <- d$y[g == l & !is.na(d$y)]
    if (length(v)) mean(v) else NA_real_
  }, numeric(1))
  keep <- !is.na(means)
  data.frame(group = present[keep], mean = unname(means[keep]), stringsAsFactors = FALSE)
}

xg02_data <- function(seed, groups, n, mu, na_rate = 0.2, all_na = character(), as_factor = NULL) {
  with_seed(seed, {
    d <- do.call(rbind, Map(function(g, k, m) {
      data.frame(group = g, y = round(stats::rnorm(k, m, 2), 3), stringsAsFactors = FALSE)
    }, groups, n, mu))
    d$y[stats::runif(nrow(d)) < na_rate] <- NA
    d$y[d$group %in% all_na] <- NA
    d$participant_id <- sprintf("p%03d", sample.int(nrow(d)))
    d <- d[sample.int(nrow(d)), c("participant_id", "group", "y")]
    if (!is.null(as_factor)) d$group <- factor(d$group, levels = as_factor)
    d
  })
}

xg02_chr <- xg02_data(811L, c("delta", "alpha", "charlie", "bravo", "echo"), c(7L, 9L, 6L, 11L, 5L),
                      c(10, 14, 9, 12, 20), all_na = "echo")
xg02_fct <- xg02_data(812L, c("low", "mid", "high", "extra"), c(10L, 8L, 12L, 6L), c(5, 7, 12, 3),
                      as_factor = c("low", "mid", "high", "extra", "unused"), all_na = "extra")
xg02_plain <- xg02_data(813L, c("b", "a", "c"), c(8L, 8L, 9L), c(3, 6, 4), na_rate = 0.1)

local({
  stopifnot(nrow(xg02_oracle(xg02_chr)) == 4, !"echo" %in% xg02_oracle(xg02_chr)$group,
            identical(xg02_oracle(xg02_fct)$group, c("low", "mid", "high")),
            identical(xg02_oracle(xg02_plain)$group, c("a", "b", "c")))
  stopifnot(anyNA(xg02_plain$y), anyNA(xg02_chr$y))
})

xg02_plot <- function(df) call_wrapped("plot_group_means", df, .digest = plot_digest)
xg02_digest <- function(df) value_of(xg02_plot(df))
xg02_bars <- function(g) {
  i <- layers_of(g, c("GeomBar", "GeomCol"))
  if (!length(i)) stop("no bar layer")
  b <- g$layers[[i[1]]]$data
  b[order(b$x), ]
}

check("bar_heights_are_group_means_ignoring_missing_values", {
  for (d in list(xg02_chr, xg02_plain)) {
    b <- xg02_bars(xg02_digest(d))
    want <- xg02_oracle(d)
    testthat::expect_equal(b$y, want$mean, tolerance = 1e-9)
    testthat::expect_equal(as.numeric(b$x), seq_len(nrow(want)))
  }
})

check("bars_start_at_zero", {
  b <- xg02_bars(xg02_digest(xg02_plain))
  testthat::expect_true(all(b$ymin == 0, na.rm = TRUE))
  testthat::expect_true(all(b$ymax == b$y))
})

check("character_groups_are_in_sorted_order", {
  g <- xg02_digest(xg02_plain)
  testthat::expect_identical(discrete_levels(g), c("a", "b", "c"))
})

check("factor_levels_set_the_order_and_unused_levels_do_not_appear", {
  g <- xg02_digest(xg02_fct)
  testthat::expect_identical(discrete_levels(g), c("low", "mid", "high"))
  testthat::expect_equal(xg02_bars(g)$y, xg02_oracle(xg02_fct)$mean, tolerance = 1e-9)
})

check("group_without_any_value_leaves_no_bar_and_no_empty_axis_slot", {
  g <- xg02_digest(xg02_chr)
  testthat::expect_false("echo" %in% discrete_levels(g))
  testthat::expect_identical(nrow(xg02_bars(g)), 4L)
  testthat::expect_false(anyNA(xg02_bars(g)$y))
})

check("no_bar_has_a_missing_height", {
  for (d in list(xg02_chr, xg02_fct, xg02_plain)) {
    testthat::expect_false(anyNA(xg02_bars(xg02_digest(d))$y))
  }
})

check("axis_titles_are_exactly_group_and_mean_y", {
  g <- xg02_digest(xg02_plain)
  testthat::expect_identical(trimws(g$labels$x), "Group")
  testthat::expect_identical(trimws(g$labels$y), "Mean y")
})

check("bars_are_not_counts", {
  b <- xg02_bars(xg02_digest(xg02_plain))
  counts <- as.numeric(table(xg02_plain$group[!is.na(xg02_plain$group)])[c("a", "b", "c")])
  testthat::expect_gt(max(abs(b$y - counts)), 0.5)
})

check("rows_with_missing_group_are_ignored_and_row_order_is_irrelevant", {
  d <- xg02_plain
  extra <- d[1:3, ]
  extra$group <- NA
  d <- rbind(extra, d[rev(seq_len(nrow(d))), ])
  testthat::expect_equal(xg02_bars(xg02_digest(d))$y, xg02_oracle(xg02_plain)$mean, tolerance = 1e-9)
})

check("input_data_frame_is_not_modified", {
  d <- xg02_fct
  res <- xg02_plot(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("plot_has_a_bar_layer_and_no_deprecation_warnings", {
  res <- xg02_plot(xg02_plain)
  value_of(res)
  expect_no_lifecycle_warnings(res)
  testthat::expect_gte(length(layers_of(res$value, c("GeomBar", "GeomCol"))), 1L)
})
