# Hidden checks for XG03 (within-group proportion heatmap with exact percent labels).

xg03_levels <- function(x) if (is.factor(x)) levels(droplevels(x)) else sort(unique(as.character(x)))

xg03_oracle <- function(df) {
  d <- df[!is.na(df$group) & !is.na(df$region), , drop = FALSE]
  gl <- xg03_levels(d$group)
  rl <- xg03_levels(d$region)
  tab <- table(factor(as.character(d$group), gl), factor(as.character(d$region), rl))
  prop <- tab / rowSums(tab)
  out <- expand.grid(region = rl, group = gl, stringsAsFactors = FALSE)[c("group", "region")]
  out$prop <- as.vector(t(prop))
  out$label <- sprintf("%.1f%%", 100 * out$prop)
  list(grid = out, group_levels = gl, region_levels = rl)
}

xg03_data <- function(seed, groups, regions, n, probs, as_factor = FALSE, add_na = FALSE) {
  with_seed(seed, {
    d <- do.call(rbind, Map(function(g, k) {
      data.frame(group = g, region = sample(regions, k, replace = TRUE, prob = probs[[g]]),
                 stringsAsFactors = FALSE)
    }, groups, n))
    d$respondent_id <- sprintf("r%03d", sample.int(nrow(d)))
    d <- d[sample.int(nrow(d)), c("respondent_id", "group", "region")]
    if (as_factor) {
      d$group <- factor(d$group, levels = c(rev(groups), "unused_group"))
      d$region <- factor(d$region, levels = c(rev(regions), "unused_region"))
    }
    if (add_na) {
      d$group[c(2, 9)] <- NA
      d$region[c(4, 15)] <- NA
    }
    d
  })
}

xg03_a <- xg03_data(821L, c("g1", "g2", "g3", "g4"), c("north", "south", "west"), c(40L, 33L, 52L, 21L),
                    list(g1 = c(.5, .5, 0), g2 = c(.2, .3, .5), g3 = c(.6, .1, .3), g4 = c(.25, .25, .5)))
xg03_b <- xg03_data(822L, c("retail", "online", "partner"), c("east", "central", "far"),
                    c(30L, 45L, 17L), list(retail = c(.7, .3, 0), online = c(.2, .5, .3),
                                          partner = c(.1, .1, .8)), as_factor = TRUE, add_na = TRUE)
xg03_single <- data.frame(respondent_id = letters[1:5], group = "only",
                          region = c("x", "x", "y", "y", "y"))

local({
  o <- xg03_oracle(xg03_a)$grid
  stopifnot(nrow(o) == 12, any(o$prop == 0), all(abs(tapply(o$prop, o$group, sum) - 1) < 1e-12))
  ob <- xg03_oracle(xg03_b)
  stopifnot(identical(ob$group_levels, c("partner", "online", "retail")),
            identical(ob$region_levels, c("far", "central", "east")))
  stopifnot(nrow(xg03_oracle(xg03_single)$grid) == 2)
})

xg03_plot <- function(df) call_wrapped("plot_proportion_heatmap", df, .digest = plot_digest)
xg03_digest <- function(df) value_of(xg03_plot(df))

xg03_layer_table <- function(g, geoms, aesthetics) {
  i <- layers_of(g, geoms)
  if (!length(i)) stop("no ", paste(geoms, collapse = "/"), " layer")
  m <- g$layers[[i[1]]]$mapped
  cols <- lapply(aesthetics, function(a) {
    if (is.null(m[[a]])) stop("layer does not map ", a)
    as.character(m[[a]])
  })
  names(cols) <- aesthetics
  as.data.frame(cols, stringsAsFactors = FALSE)
}

xg03_tiles <- function(g) {
  t <- xg03_layer_table(g, c("GeomTile", "GeomRaster"), c("x", "y", "fill"))
  data.frame(group = t$y, region = t$x, prop = as.numeric(t$fill), stringsAsFactors = FALSE)
}
xg03_labels <- function(g) {
  t <- xg03_layer_table(g, "GeomText", c("x", "y", "label"))
  data.frame(group = t$y, region = t$x, label = t$label, stringsAsFactors = FALSE)
}
xg03_key <- function(t) paste(t$group, t$region, sep = "\r")

check("tiles_cover_every_group_region_combination_with_within_group_shares", {
  for (d in list(xg03_a, xg03_b)) {
    want <- xg03_oracle(d)$grid
    got <- xg03_tiles(xg03_digest(d))
    testthat::expect_identical(nrow(got), nrow(want))
    got <- got[match(xg03_key(want), xg03_key(got)), ]
    testthat::expect_false(anyNA(got$prop))
    testthat::expect_equal(got$prop, want$prop, tolerance = 1e-9)
  }
})

check("each_groups_shares_add_up_to_one", {
  got <- xg03_tiles(xg03_digest(xg03_a))
  testthat::expect_equal(as.numeric(tapply(got$prop, got$group, sum)), rep(1, 4), tolerance = 1e-9)
})

check("empty_combinations_are_present_as_zero_tiles", {
  got <- xg03_tiles(xg03_digest(xg03_a))
  testthat::expect_true(any(got$prop == 0))
  testthat::expect_identical(nrow(got), 12L)
})

check("labels_are_one_decimal_percentages_matching_the_shares", {
  for (d in list(xg03_a, xg03_b)) {
    want <- xg03_oracle(d)$grid
    got <- xg03_labels(xg03_digest(d))
    got <- got[match(xg03_key(want), xg03_key(got)), ]
    testthat::expect_identical(got$label, want$label)
  }
})

check("zero_share_is_labelled_0_0_percent", {
  got <- xg03_labels(xg03_digest(xg03_a))
  testthat::expect_true("0.0%" %in% got$label)
})

check("axes_follow_factor_or_sorted_order_without_unused_levels", {
  g <- xg03_digest(xg03_b)
  testthat::expect_identical(discrete_levels(g, "x"), c("far", "central", "east"))
  testthat::expect_identical(discrete_levels(g, "y"), c("partner", "online", "retail"))
  g2 <- xg03_digest(xg03_a)
  testthat::expect_identical(discrete_levels(g2, "x"), c("north", "south", "west"))
  testthat::expect_identical(discrete_levels(g2, "y"), c("g1", "g2", "g3", "g4"))
})

check("fill_uses_a_continuous_colour_scale", {
  g <- xg03_digest(xg03_a)
  fill <- Filter(function(s) "fill" %in% s$aesthetics, g$scales)
  testthat::expect_length(fill, 1L)
  testthat::expect_match(fill[[1]]$class, "Continuous")
})

check("axis_titles_are_exactly_region_and_group", {
  g <- xg03_digest(xg03_a)
  testthat::expect_identical(trimws(g$labels$x), "Region")
  testthat::expect_identical(trimws(g$labels$y), "Group")
})

check("single_group_gives_one_row_of_tiles_summing_to_one", {
  got <- xg03_tiles(xg03_digest(xg03_single))
  testthat::expect_identical(nrow(got), 2L)
  testthat::expect_equal(sort(got$prop), c(0.4, 0.6), tolerance = 1e-9)
})

check("rows_with_missing_values_are_ignored_and_row_order_is_irrelevant", {
  d <- xg03_a
  extra <- d[1:3, ]
  extra$group[1] <- NA
  extra$region[2:3] <- NA
  d <- rbind(extra, d[rev(seq_len(nrow(d))), ])
  want <- xg03_oracle(xg03_a)$grid
  got <- xg03_tiles(xg03_digest(d))
  got <- got[match(xg03_key(want), xg03_key(got)), ]
  testthat::expect_equal(got$prop, want$prop, tolerance = 1e-9)
})

check("input_data_frame_is_not_modified", {
  d <- xg03_b
  res <- xg03_plot(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("no_deprecation_warnings", {
  res <- xg03_plot(xg03_a)
  value_of(res)
  expect_no_lifecycle_warnings(res)
})
