#### control: reference
# Trusted reference: row-normalised table, tiles and one-decimal percent labels.
plot_proportion_heatmap <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$region), ]
  lev <- function(x) if (is.factor(x)) levels(droplevels(x)) else sort(unique(as.character(x)))
  gl <- lev(d$group)
  rl <- lev(d$region)
  tab <- table(factor(as.character(d$group), gl), factor(as.character(d$region), rl))
  prop <- as.data.frame(tab / rowSums(tab), stringsAsFactors = FALSE)
  names(prop) <- c("group", "region", "share")
  prop$group <- factor(prop$group, levels = gl)
  prop$region <- factor(prop$region, levels = rl)
  ggplot2::ggplot(prop, ggplot2::aes(region, group, fill = share)) +
    ggplot2::geom_tile() +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f%%", 100 * share))) +
    ggplot2::labs(x = "Region", y = "Group")
}

#### control: alternate_dplyr_complete
# Alternate valid solution: dplyr counting with tidyr::complete.
plot_proportion_heatmap <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$region), ]
  gl <- if (is.factor(d$group)) levels(droplevels(d$group)) else sort(unique(as.character(d$group)))
  rl <- if (is.factor(d$region)) levels(droplevels(d$region)) else sort(unique(as.character(d$region)))
  tab <- d |>
    dplyr::mutate(group = as.character(group), region = as.character(region)) |>
    dplyr::count(group, region) |>
    tidyr::complete(group = gl, region = rl, fill = list(n = 0L)) |>
    dplyr::mutate(share = n / sum(n), .by = group) |>
    dplyr::mutate(group = factor(group, gl), region = factor(region, rl))
  ggplot2::ggplot(tab, ggplot2::aes(x = region, y = group)) +
    ggplot2::geom_tile(ggplot2::aes(fill = share)) +
    ggplot2::geom_text(ggplot2::aes(label = paste0(formatC(100 * share, format = "f", digits = 1), "%"))) +
    ggplot2::labs(x = "Region", y = "Group")
}

#### control: wrong_share_of_region
# Plausible wrong strategy: normalises within region (columns) instead of within group (rows).
plot_proportion_heatmap <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$region), ]
  gl <- if (is.factor(d$group)) levels(droplevels(d$group)) else sort(unique(as.character(d$group)))
  rl <- if (is.factor(d$region)) levels(droplevels(d$region)) else sort(unique(as.character(d$region)))
  tab <- table(factor(as.character(d$group), gl), factor(as.character(d$region), rl))
  prop <- as.data.frame(sweep(tab, 2, colSums(tab), "/"), stringsAsFactors = FALSE)
  names(prop) <- c("group", "region", "share")
  prop$group <- factor(prop$group, gl)
  prop$region <- factor(prop$region, rl)
  ggplot2::ggplot(prop, ggplot2::aes(region, group, fill = share)) + ggplot2::geom_tile() +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f%%", 100 * share))) +
    ggplot2::labs(x = "Region", y = "Group")
}

#### control: wrong_share_of_all_respondents
# Plausible wrong strategy: shares of the grand total.
plot_proportion_heatmap <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$region), ]
  gl <- if (is.factor(d$group)) levels(droplevels(d$group)) else sort(unique(as.character(d$group)))
  rl <- if (is.factor(d$region)) levels(droplevels(d$region)) else sort(unique(as.character(d$region)))
  tab <- table(factor(as.character(d$group), gl), factor(as.character(d$region), rl))
  prop <- as.data.frame(tab / sum(tab), stringsAsFactors = FALSE)
  names(prop) <- c("group", "region", "share")
  prop$group <- factor(prop$group, gl)
  prop$region <- factor(prop$region, rl)
  ggplot2::ggplot(prop, ggplot2::aes(region, group, fill = share)) + ggplot2::geom_tile() +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f%%", 100 * share))) +
    ggplot2::labs(x = "Region", y = "Group")
}

#### control: wrong_drops_empty_combinations
# Plausible wrong strategy: only combinations that occur are drawn (no zero tiles).
plot_proportion_heatmap <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$region), ]
  d$group <- if (is.factor(d$group)) droplevels(d$group) else factor(as.character(d$group))
  d$region <- if (is.factor(d$region)) droplevels(d$region) else factor(as.character(d$region))
  counts <- stats::aggregate(rep(1, nrow(d)) ~ group + region, d, sum)
  names(counts)[3] <- "n"
  counts$share <- counts$n / stats::ave(counts$n, counts$group, FUN = sum)
  ggplot2::ggplot(counts, ggplot2::aes(region, group, fill = share)) + ggplot2::geom_tile() +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f%%", 100 * share))) +
    ggplot2::labs(x = "Region", y = "Group")
}

#### control: wrong_label_without_decimal
# Plausible wrong strategy: percent labels rounded to whole numbers.
plot_proportion_heatmap <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$region), ]
  gl <- if (is.factor(d$group)) levels(droplevels(d$group)) else sort(unique(as.character(d$group)))
  rl <- if (is.factor(d$region)) levels(droplevels(d$region)) else sort(unique(as.character(d$region)))
  tab <- table(factor(as.character(d$group), gl), factor(as.character(d$region), rl))
  prop <- as.data.frame(tab / rowSums(tab), stringsAsFactors = FALSE)
  names(prop) <- c("group", "region", "share")
  prop$group <- factor(prop$group, gl)
  prop$region <- factor(prop$region, rl)
  ggplot2::ggplot(prop, ggplot2::aes(region, group, fill = share)) + ggplot2::geom_tile() +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.0f%%", 100 * share))) +
    ggplot2::labs(x = "Region", y = "Group")
}

#### control: edge_default_axis_titles
# Boundary case: right data and labels, default axis titles (expected: not fully correct).
# expect: fail
plot_proportion_heatmap <- function(data) {
  d <- data[!is.na(data$group) & !is.na(data$region), ]
  lev <- function(x) if (is.factor(x)) levels(droplevels(x)) else sort(unique(as.character(x)))
  gl <- lev(d$group)
  rl <- lev(d$region)
  tab <- table(factor(as.character(d$group), gl), factor(as.character(d$region), rl))
  prop <- as.data.frame(tab / rowSums(tab), stringsAsFactors = FALSE)
  names(prop) <- c("group", "region", "share")
  prop$group <- factor(prop$group, levels = gl)
  prop$region <- factor(prop$region, levels = rl)
  ggplot2::ggplot(prop, ggplot2::aes(region, group, fill = share)) + ggplot2::geom_tile() +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f%%", 100 * share)))
}

#### control: malformed_returns_table
# Malformed submission: returns the proportion table, not a plot.
# expect: fail
plot_proportion_heatmap <- function(data) prop.table(table(data$group, data$region), 1)

#### control: malformed_incomplete_stub
# Incomplete submission: an unfinished stub.
# expect: fail
plot_proportion_heatmap <- function(data) NULL
