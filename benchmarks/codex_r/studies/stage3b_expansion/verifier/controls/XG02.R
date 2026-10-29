#### control: reference
# Trusted reference: precomputed means (NA removed, NA-only groups dropped) with geom_col.
plot_group_means <- function(data) {
  d <- data[!is.na(data$group), ]
  lev <- if (is.factor(d$group)) levels(droplevels(d$group)) else sort(unique(as.character(d$group)))
  g <- as.character(d$group)
  m <- vapply(lev, function(l) {
    v <- d$y[g == l & !is.na(d$y)]
    if (length(v)) mean(v) else NA_real_
  }, numeric(1))
  means <- data.frame(group = factor(lev[!is.na(m)], levels = lev[!is.na(m)]), mean_y = m[!is.na(m)])
  ggplot2::ggplot(means, ggplot2::aes(group, mean_y)) + ggplot2::geom_col() +
    ggplot2::labs(x = "Group", y = "Mean y")
}

#### control: alternate_stat_summary_after_filter
# Alternate valid solution: filter first, then let stat_summary compute the means.
plot_group_means <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$y), ]
  d$group <- if (is.factor(d$group)) droplevels(d$group) else factor(as.character(d$group))
  ggplot2::ggplot(d, ggplot2::aes(group, y)) +
    ggplot2::stat_summary(fun = mean, geom = "bar") +
    ggplot2::labs(x = "Group", y = "Mean y")
}

#### control: wrong_count_bars
# Plausible wrong strategy: geom_bar() with the default count statistic.
plot_group_means <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$y), ]
  ggplot2::ggplot(d, ggplot2::aes(group)) + ggplot2::geom_bar() +
    ggplot2::labs(x = "Group", y = "Mean y")
}

#### control: wrong_mean_without_na_rm
# Plausible wrong strategy: group means computed without na.rm, so affected groups have NA bars.
plot_group_means <- function(data) {
  d <- data[!is.na(data$group), ]
  means <- stats::aggregate(y ~ group, d, mean, na.action = stats::na.pass)
  ggplot2::ggplot(means, ggplot2::aes(group, y)) + ggplot2::geom_col() +
    ggplot2::labs(x = "Group", y = "Mean y")
}

#### control: wrong_alphabetical_order_for_factors
# Plausible wrong strategy: ignores factor levels and always sorts the labels alphabetically.
plot_group_means <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$y), ]
  means <- stats::aggregate(y ~ group, d, mean)
  means$group <- factor(as.character(means$group), levels = sort(unique(as.character(means$group))))
  ggplot2::ggplot(means, ggplot2::aes(group, y)) + ggplot2::geom_col() +
    ggplot2::labs(x = "Group", y = "Mean y")
}

#### control: wrong_keeps_empty_group_slot
# Plausible wrong strategy: passes the raw rows to stat_summary, so a group with no value keeps
# an empty slot on the axis.
plot_group_means <- function(data) {
  d <- data[!is.na(data$group), ]
  ggplot2::ggplot(d, ggplot2::aes(group, y)) +
    ggplot2::stat_summary(fun = mean, geom = "bar") +
    ggplot2::labs(x = "Group", y = "Mean y")
}

#### control: edge_default_axis_titles
# Boundary case: right bars, but default axis titles (expected: not fully correct).
# expect: fail
plot_group_means <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$y), ]
  d$group <- if (is.factor(d$group)) droplevels(d$group) else factor(as.character(d$group))
  ggplot2::ggplot(d, ggplot2::aes(group, y)) + ggplot2::stat_summary(fun = mean, geom = "bar")
}

#### control: malformed_returns_means_table
# Malformed submission: returns the table of means, not a plot.
# expect: fail
plot_group_means <- function(data) stats::aggregate(y ~ group, data, mean)

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
plot_group_means <- function(data) stop("not implemented")
