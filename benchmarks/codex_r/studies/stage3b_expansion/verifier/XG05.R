# Hidden checks for XG05 (grouping: per-subject lines in week order plus a mean line).

xg05_oracle <- function(df) {
  d <- df[!is.na(df$subject) & !is.na(df$week) & !is.na(df$score), , drop = FALSE]
  d <- d[order(as.character(d$subject), d$week), ]
  seqs <- lapply(split(d, as.character(d$subject)), function(s) {
    s <- s[order(s$week), ]
    data.frame(x = s$week, y = s$score)
  })
  weeks <- sort(unique(d$week))
  mean_line <- data.frame(x = weeks,
                          y = vapply(weeks, function(w) mean(d$score[d$week == w]), numeric(1)))
  list(seqs = unname(seqs), mean_line = mean_line, n_subjects = length(seqs), weeks = weeks)
}

xg05_data <- function(seed, subjects, weeks, miss = 0.15, drop_week = NULL, numeric_ids = FALSE) {
  with_seed(seed, {
    u <- stats::rnorm(length(subjects), sd = 3)
    d <- do.call(rbind, lapply(seq_along(subjects), function(i) {
      data.frame(subject = subjects[i], week = weeks,
                 score = round(30 + u[i] + 1.5 * seq_along(weeks) + stats::rnorm(length(weeks), sd = 2), 3))
    }))
    d$score[stats::runif(nrow(d)) < miss] <- NA
    if (!is.null(drop_week)) d$score[d$week == drop_week] <- NA
    if (numeric_ids) d$subject <- as.integer(factor(d$subject, subjects)) + 100L
    d[sample.int(nrow(d)), ]
  })
}

xg05_a <- xg05_data(841L, sprintf("p%02d", 1:10), 1:5)
xg05_b <- xg05_data(842L, letters[1:7], c(3L, 6L, 9L, 12L), numeric_ids = TRUE)
xg05_c <- xg05_data(843L, c("u", "v", "w", "x"), 1:4, drop_week = 3L)

local({
  stopifnot(anyNA(xg05_a$score), anyNA(xg05_c$score), all(is.na(xg05_c$score[xg05_c$week == 3L])))
  stopifnot(xg05_oracle(xg05_a)$n_subjects == 10, length(xg05_oracle(xg05_c)$weeks) == 3)
  # The input rows are shuffled, so a path drawn in data order would zig-zag.
  stopifnot(is.unsorted(xg05_a$week[xg05_a$subject == "p01"]))
})

xg05_plot <- function(df) call_wrapped("plot_trajectories", df, .digest = plot_digest)
xg05_digest <- function(df) value_of(xg05_plot(df))

xg05_line_layers <- function(g) {
  i <- layers_of(g, c("GeomLine", "GeomPath"))
  if (length(i) < 2L) stop("need a participant-line layer and a mean-line layer")
  groups <- vapply(i, function(k) length(unique(g$layers[[k]]$data$group)), 1L)
  list(subject = g$layers[[i[which.max(groups)]]], mean = g$layers[[i[setdiff(seq_along(i), which.max(groups))[1]]]],
       n_groups = groups)
}

# Week values of a layer's x positions (positions are 1..k when the x scale is discrete).
xg05_weeks <- function(g, x) {
  lv <- discrete_levels(g, "x")
  if (!is.null(lv)) as.numeric(lv)[round(x)] else x
}

xg05_sequences <- function(g, layer) {
  ld <- layer$data
  ld <- ld[!is.na(ld$y) & !is.na(ld$x), ]
  ld$week <- xg05_weeks(g, ld$x)
  parts <- split(ld, ld$group)
  lapply(parts, function(s) data.frame(x = s$week, y = s$y))
}

xg05_same_sets <- function(got, want) {
  key <- function(s) paste(sprintf("%.6f:%.6f", s$x, s$y), collapse = "|")
  testthat::expect_identical(sort(unname(vapply(got, key, ""))), sort(unname(vapply(want, key, ""))))
}

check("one_line_per_participant_with_its_observed_scores", {
  for (d in list(xg05_a, xg05_b, xg05_c)) {
    g <- xg05_digest(d)
    got <- xg05_sequences(g, xg05_line_layers(g)$subject)
    xg05_same_sets(got, xg05_oracle(d)$seqs)
  }
})

check("lines_run_in_week_order_whatever_the_row_order", {
  g <- xg05_digest(xg05_a)
  ld <- xg05_line_layers(g)$subject$data
  ld <- ld[!is.na(ld$y), ]
  for (grp in split(ld, ld$group)) {
    testthat::expect_false(is.unsorted(grp$x))
  }
})

check("participants_are_separate_lines_not_one_connected_path", {
  g <- xg05_digest(xg05_a)
  ll <- xg05_line_layers(g)
  testthat::expect_identical(max(ll$n_groups), xg05_oracle(xg05_a)$n_subjects)
})

check("mean_line_is_one_group_with_weekly_means_ignoring_missing_scores", {
  for (d in list(xg05_a, xg05_b, xg05_c)) {
    g <- xg05_digest(d)
    ml <- xg05_line_layers(g)$mean$data
    ml <- ml[!is.na(ml$y), ]
    testthat::expect_identical(length(unique(ml$group)), 1L)
    ml <- ml[order(ml$x), ]
    want <- xg05_oracle(d)$mean_line
    testthat::expect_equal(xg05_weeks(g, ml$x), want$x, tolerance = 1e-9)
    testthat::expect_equal(ml$y, want$y, tolerance = 1e-9)
  }
})

check("a_week_with_no_scores_has_no_mean_point", {
  g <- xg05_digest(xg05_c)
  ml <- xg05_line_layers(g)$mean$data
  ml <- ml[!is.na(ml$y), ]
  testthat::expect_false(3 %in% xg05_weeks(g, ml$x))
})

check("mean_line_is_at_least_one_and_a_half_times_as_thick", {
  ll <- xg05_line_layers(xg05_digest(xg05_a))
  testthat::expect_gte(mean(ll$mean$data$linewidth), 1.5 * mean(ll$subject$data$linewidth))
})

check("axis_titles_are_exactly_week_and_score", {
  g <- xg05_digest(xg05_a)
  testthat::expect_identical(trimws(g$labels$x), "Week")
  testthat::expect_identical(trimws(g$labels$y), "Score")
})

check("numeric_identifiers_and_unevenly_spaced_weeks_are_supported", {
  g <- xg05_digest(xg05_b)
  got <- xg05_sequences(g, xg05_line_layers(g)$subject)
  xg05_same_sets(got, xg05_oracle(xg05_b)$seqs)
})

check("participants_without_any_score_do_not_appear", {
  d <- xg05_a
  d$score[d$subject == "p03"] <- NA
  g <- xg05_digest(d)
  testthat::expect_identical(max(xg05_line_layers(g)$n_groups[1:2]) , 9L)
  xg05_same_sets(xg05_sequences(g, xg05_line_layers(g)$subject), xg05_oracle(d)$seqs)
})

check("input_data_frame_is_not_modified", {
  d <- xg05_a
  res <- xg05_plot(d)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], d)
})

check("no_deprecation_warnings", {
  res <- xg05_plot(xg05_a)
  value_of(res)
  expect_no_lifecycle_warnings(res)
})
