#### control: reference
# Trusted reference: sorted rows, group = subject for thin lines, stat_summary mean line.
plot_trajectories <- function(data) {
  d <- data[!is.na(data$subject) & !is.na(data$week) & !is.na(data$score), ]
  d <- d[order(as.character(d$subject), d$week), ]
  means <- stats::aggregate(score ~ week, d, mean)
  ggplot2::ggplot(d, ggplot2::aes(week, score)) +
    ggplot2::geom_line(ggplot2::aes(group = subject), linewidth = 0.4, colour = "grey55") +
    ggplot2::geom_line(data = means, ggplot2::aes(week, score, group = 1), linewidth = 1.6) +
    ggplot2::labs(x = "Week", y = "Score")
}

#### control: alternate_stat_summary_mean_line
# Alternate valid solution: geom_path on week-sorted rows and stat_summary for the mean line.
plot_trajectories <- function(data) {
  d <- data[!is.na(data$score), ]
  d <- d[order(d$subject, d$week), ]
  ggplot2::ggplot(d, ggplot2::aes(x = week, y = score)) +
    ggplot2::geom_path(ggplot2::aes(group = subject), linewidth = 0.3) +
    ggplot2::stat_summary(fun = mean, geom = "line", ggplot2::aes(group = 1), linewidth = 1.2) +
    ggplot2::labs(x = "Week", y = "Score")
}

#### control: wrong_no_group_aesthetic
# Plausible wrong strategy: no group aesthetic, so all rows form one path in data order.
plot_trajectories <- function(data) {
  d <- data[!is.na(data$score), ]
  means <- stats::aggregate(score ~ week, d, mean)
  ggplot2::ggplot(d, ggplot2::aes(week, score)) + ggplot2::geom_path(linewidth = 0.4) +
    ggplot2::geom_line(data = means, ggplot2::aes(week, score, group = 1), linewidth = 1.6) +
    ggplot2::labs(x = "Week", y = "Score")
}

#### control: wrong_path_in_row_order
# Plausible wrong strategy: grouped by subject, but geom_path joins points in data row order.
plot_trajectories <- function(data) {
  d <- data[!is.na(data$score), ]
  means <- stats::aggregate(score ~ week, d, mean)
  ggplot2::ggplot(d, ggplot2::aes(week, score)) +
    ggplot2::geom_path(ggplot2::aes(group = subject), linewidth = 0.4) +
    ggplot2::geom_line(data = means, ggplot2::aes(week, score, group = 1), linewidth = 1.6) +
    ggplot2::labs(x = "Week", y = "Score")
}

#### control: wrong_mean_with_missing_as_zero
# Plausible wrong strategy: missing scores are treated as 0 when averaging.
plot_trajectories <- function(data) {
  d <- data[!is.na(data$subject) & !is.na(data$week), ]
  zero <- d
  zero$score[is.na(zero$score)] <- 0
  means <- stats::aggregate(score ~ week, zero, mean)
  d <- d[!is.na(d$score), ]
  d <- d[order(as.character(d$subject), d$week), ]
  ggplot2::ggplot(d, ggplot2::aes(week, score)) +
    ggplot2::geom_line(ggplot2::aes(group = subject), linewidth = 0.4) +
    ggplot2::geom_line(data = means, ggplot2::aes(week, score, group = 1), linewidth = 1.6) +
    ggplot2::labs(x = "Week", y = "Score")
}

#### control: wrong_mean_line_same_width
# Plausible wrong strategy: right data, but the mean line is not visually emphasised.
plot_trajectories <- function(data) {
  d <- data[!is.na(data$subject) & !is.na(data$week) & !is.na(data$score), ]
  d <- d[order(as.character(d$subject), d$week), ]
  means <- stats::aggregate(score ~ week, d, mean)
  ggplot2::ggplot(d, ggplot2::aes(week, score)) +
    ggplot2::geom_line(ggplot2::aes(group = subject), linewidth = 0.5) +
    ggplot2::geom_line(data = means, ggplot2::aes(week, score, group = 1), linewidth = 0.5) +
    ggplot2::labs(x = "Week", y = "Score")
}

#### control: edge_default_axis_titles
# Boundary case: right lines, default axis titles (expected: not fully correct).
# expect: fail
plot_trajectories <- function(data) {
  d <- data[!is.na(data$subject) & !is.na(data$week) & !is.na(data$score), ]
  d <- d[order(as.character(d$subject), d$week), ]
  means <- stats::aggregate(score ~ week, d, mean)
  ggplot2::ggplot(d, ggplot2::aes(week, score)) +
    ggplot2::geom_line(ggplot2::aes(group = subject), linewidth = 0.4) +
    ggplot2::geom_line(data = means, ggplot2::aes(week, score, group = 1), linewidth = 1.6)
}

#### control: malformed_returns_means_table
# Malformed submission: returns the table of weekly means.
# expect: fail
plot_trajectories <- function(data) stats::aggregate(score ~ week, data, mean)

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
plot_trajectories <- function(data) NULL
