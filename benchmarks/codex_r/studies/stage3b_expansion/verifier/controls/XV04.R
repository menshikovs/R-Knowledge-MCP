#### control: reference
# Trusted reference: after_stat(density), legend.position = "inside", linewidth.
plot_density_histogram <- function(data, bins = 10L) {
  if (!is.numeric(bins) || length(bins) != 1L || is.na(bins) || bins < 2 || bins != round(bins)) {
    stop("bins must be a single whole number >= 2")
  }
  d <- data[!is.na(data$value) & !is.na(data$group), ]
  ggplot2::ggplot(d, ggplot2::aes(value, fill = group, colour = group)) +
    ggplot2::geom_histogram(ggplot2::aes(y = ggplot2::after_stat(density)), bins = bins,
                            position = "identity", alpha = 0.4) +
    ggplot2::geom_density(fill = NA, linewidth = 1) +
    ggplot2::labs(y = "Density") +
    ggplot2::theme(legend.position = "inside", legend.position.inside = c(0.9, 0.9))
}

#### control: alternate_explicit_density_mapping
# Alternate valid solution: y = after_stat(density) set at plot level, different styling.
plot_density_histogram <- function(data, bins = 10L) {
  stopifnot(is.numeric(bins), length(bins) == 1, !is.na(bins), bins >= 2, bins == round(bins))
  d <- subset(data, !is.na(value) & !is.na(group))
  ggplot2::ggplot(d, ggplot2::aes(x = value, y = ggplot2::after_stat(density), fill = group, colour = group)) +
    ggplot2::geom_histogram(bins = bins, position = "identity", alpha = 0.5, colour = NA) +
    ggplot2::geom_density(ggplot2::aes(fill = NULL), linewidth = 0.9) +
    ggplot2::labs(x = "Value", y = "Density") +
    ggplot2::theme_minimal() +
    ggplot2::theme(legend.position = "inside", legend.position.inside = c(0.95, 0.85))
}

#### control: wrong_dot_dot_notation
# Plausible wrong strategy from older tutorials: ..density.. (deprecated since ggplot2 3.4.0).
plot_density_histogram <- function(data, bins = 10L) {
  if (!is.numeric(bins) || length(bins) != 1L || is.na(bins) || bins < 2 || bins != round(bins)) stop("bad bins")
  d <- data[!is.na(data$value) & !is.na(data$group), ]
  ggplot2::ggplot(d, ggplot2::aes(value, fill = group, colour = group)) +
    ggplot2::geom_histogram(ggplot2::aes(y = ..density..), bins = bins, position = "identity", alpha = 0.4) +
    ggplot2::geom_density(fill = NA, linewidth = 1) + ggplot2::labs(y = "Density") +
    ggplot2::theme(legend.position = "inside", legend.position.inside = c(0.9, 0.9))
}

#### control: alternate_numeric_legend_position
# Accepted: a numeric legend.position is only soft-deprecated (3.5.0) and ggplot2 4.0.3 converts it to
# an inside legend with the same coordinates, so the resulting plot is equivalent.
plot_density_histogram <- function(data, bins = 10L) {
  if (!is.numeric(bins) || length(bins) != 1L || is.na(bins) || bins < 2 || bins != round(bins)) stop("bad bins")
  d <- data[!is.na(data$value) & !is.na(data$group), ]
  ggplot2::ggplot(d, ggplot2::aes(value, fill = group, colour = group)) +
    ggplot2::geom_histogram(ggplot2::aes(y = ggplot2::after_stat(density)), bins = bins,
                            position = "identity", alpha = 0.4) +
    ggplot2::geom_density(fill = NA, linewidth = 1) + ggplot2::labs(y = "Density") +
    ggplot2::theme(legend.position = c(0.9, 0.9))
}

#### control: wrong_size_for_line_width
# Plausible wrong strategy: size = for a line width (deprecated since ggplot2 3.4.0).
plot_density_histogram <- function(data, bins = 10L) {
  if (!is.numeric(bins) || length(bins) != 1L || is.na(bins) || bins < 2 || bins != round(bins)) stop("bad bins")
  d <- data[!is.na(data$value) & !is.na(data$group), ]
  ggplot2::ggplot(d, ggplot2::aes(value, fill = group, colour = group)) +
    ggplot2::geom_histogram(ggplot2::aes(y = ggplot2::after_stat(density)), bins = bins,
                            position = "identity", alpha = 0.4) +
    ggplot2::geom_density(fill = NA, size = 1) + ggplot2::labs(y = "Density") +
    ggplot2::theme(legend.position = "inside", legend.position.inside = c(0.9, 0.9))
}

#### control: wrong_counts_and_stacked
# Plausible wrong strategy: default count scale and stacked bars (the default position).
plot_density_histogram <- function(data, bins = 10L) {
  if (!is.numeric(bins) || length(bins) != 1L || is.na(bins) || bins < 2 || bins != round(bins)) stop("bad bins")
  d <- data[!is.na(data$value) & !is.na(data$group), ]
  ggplot2::ggplot(d, ggplot2::aes(value, fill = group, colour = group)) +
    ggplot2::geom_histogram(bins = bins) + ggplot2::geom_density(fill = NA, linewidth = 1) +
    ggplot2::labs(y = "Density") +
    ggplot2::theme(legend.position = "inside", legend.position.inside = c(0.9, 0.9))
}

#### control: wrong_legend_outside_on_the_right
# Plausible wrong strategy: legend left outside the panel.
plot_density_histogram <- function(data, bins = 10L) {
  if (!is.numeric(bins) || length(bins) != 1L || is.na(bins) || bins < 2 || bins != round(bins)) stop("bad bins")
  d <- data[!is.na(data$value) & !is.na(data$group), ]
  ggplot2::ggplot(d, ggplot2::aes(value, fill = group, colour = group)) +
    ggplot2::geom_histogram(ggplot2::aes(y = ggplot2::after_stat(density)), bins = bins,
                            position = "identity", alpha = 0.4) +
    ggplot2::geom_density(fill = NA, linewidth = 1) + ggplot2::labs(y = "Density") +
    ggplot2::theme(legend.position = "right")
}

#### control: edge_bins_not_validated
# Boundary case: right for valid bins but never validates (expected: not fully correct).
# expect: fail
plot_density_histogram <- function(data, bins = 10L) {
  d <- data[!is.na(data$value) & !is.na(data$group), ]
  ggplot2::ggplot(d, ggplot2::aes(value, fill = group, colour = group)) +
    ggplot2::geom_histogram(ggplot2::aes(y = ggplot2::after_stat(density)), bins = bins,
                            position = "identity", alpha = 0.4) +
    ggplot2::geom_density(fill = NA, linewidth = 1) + ggplot2::labs(y = "Density") +
    ggplot2::theme(legend.position = "inside", legend.position.inside = c(0.9, 0.9))
}

#### control: malformed_returns_density_list
# Malformed submission: returns density estimates instead of a plot.
# expect: fail
plot_density_histogram <- function(data, bins = 10L) lapply(split(data$value, data$group), stats::density, na.rm = TRUE)

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
plot_density_histogram <- function(data, bins = 10L) stop("todo")
