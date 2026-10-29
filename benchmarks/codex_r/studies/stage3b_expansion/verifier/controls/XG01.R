#### control: reference
# Trusted reference: complete calendar, means via tapply, line and points, explicit labels.
plot_daily_means <- function(data) {
  d <- data[!is.na(data$day), ]
  cal <- seq(min(d$day), max(d$day), by = "day")
  keep <- !is.na(d$score)
  m <- tapply(d$score[keep], factor(as.integer(d$day[keep]), levels = as.integer(cal)), mean)
  daily <- data.frame(day = cal, mean_score = as.numeric(m))
  ggplot2::ggplot(daily, ggplot2::aes(day, mean_score)) +
    ggplot2::geom_line() +
    ggplot2::geom_point() +
    ggplot2::scale_x_date() +
    ggplot2::labs(x = "Day", y = "Mean score")
}

#### control: alternate_dplyr_complete
# Alternate valid solution: dplyr/tidyr to complete the calendar; line drawn in a path-like way.
plot_daily_means <- function(data) {
  d <- dplyr::filter(data, !is.na(day))
  means <- d |>
    dplyr::filter(!is.na(score)) |>
    dplyr::summarise(m = mean(score), .by = day)
  cal <- tidyr::complete(means, day = seq(min(d$day), max(d$day), by = "day"))
  ggplot2::ggplot(cal, ggplot2::aes(x = day, y = m)) +
    ggplot2::geom_path() +
    ggplot2::geom_point(na.rm = TRUE) +
    ggplot2::labs(x = "Day", y = "Mean score")
}

#### control: wrong_observed_days_only
# Plausible wrong strategy: only the observed days, so the line is interpolated across gaps.
plot_daily_means <- function(data) {
  d <- data[!is.na(data$day) & !is.na(data$score), ]
  daily <- stats::aggregate(score ~ day, d, mean)
  ggplot2::ggplot(daily, ggplot2::aes(day, score)) + ggplot2::geom_line() + ggplot2::geom_point() +
    ggplot2::labs(x = "Day", y = "Mean score")
}

#### control: wrong_gaps_filled_with_zero
# Plausible wrong strategy: complete calendar, but gap days are filled with 0.
plot_daily_means <- function(data) {
  d <- data[!is.na(data$day), ]
  cal <- seq(min(d$day), max(d$day), by = "day")
  keep <- !is.na(d$score)
  m <- tapply(d$score[keep], factor(as.integer(d$day[keep]), levels = as.integer(cal)), mean)
  m[is.na(m)] <- 0
  daily <- data.frame(day = cal, mean_score = as.numeric(m))
  ggplot2::ggplot(daily, ggplot2::aes(day, mean_score)) + ggplot2::geom_line() + ggplot2::geom_point() +
    ggplot2::labs(x = "Day", y = "Mean score")
}

#### control: wrong_na_rm_bridges_gaps
# Plausible wrong strategy: complete calendar with NA, but na.rm = TRUE joins the line across gaps.
plot_daily_means <- function(data) {
  d <- data[!is.na(data$day), ]
  cal <- seq(min(d$day), max(d$day), by = "day")
  keep <- !is.na(d$score)
  m <- tapply(d$score[keep], factor(as.integer(d$day[keep]), levels = as.integer(cal)), mean)
  daily <- data.frame(day = cal, mean_score = as.numeric(m))
  ggplot2::ggplot(daily, ggplot2::aes(day, mean_score)) + ggplot2::geom_line(na.rm = TRUE) +
    ggplot2::geom_point(na.rm = TRUE) + ggplot2::labs(x = "Day", y = "Mean score")
}

#### control: wrong_median_instead_of_mean
# Plausible wrong strategy: daily median instead of the daily mean.
plot_daily_means <- function(data) {
  d <- data[!is.na(data$day), ]
  cal <- seq(min(d$day), max(d$day), by = "day")
  keep <- !is.na(d$score)
  m <- tapply(d$score[keep], factor(as.integer(d$day[keep]), levels = as.integer(cal)), stats::median)
  daily <- data.frame(day = cal, mean_score = as.numeric(m))
  ggplot2::ggplot(daily, ggplot2::aes(day, mean_score)) + ggplot2::geom_line() + ggplot2::geom_point() +
    ggplot2::labs(x = "Day", y = "Mean score")
}

#### control: edge_default_axis_titles
# Boundary case: correct data and layers, but the default axis titles (expected: not fully correct).
# expect: fail
plot_daily_means <- function(data) {
  d <- data[!is.na(data$day), ]
  cal <- seq(min(d$day), max(d$day), by = "day")
  keep <- !is.na(d$score)
  m <- tapply(d$score[keep], factor(as.integer(d$day[keep]), levels = as.integer(cal)), mean)
  daily <- data.frame(day = cal, mean_score = as.numeric(m))
  ggplot2::ggplot(daily, ggplot2::aes(day, mean_score)) + ggplot2::geom_line() + ggplot2::geom_point()
}

#### control: malformed_returns_data_frame
# Malformed submission: returns the aggregated data frame instead of a plot.
# expect: fail
plot_daily_means <- function(data) stats::aggregate(score ~ day, data, mean)

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
plot_daily_means <- function(data) NULL
