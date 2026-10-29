#### control: reference
# Trusted reference: dplyr::reframe() returns several rows per group.
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) {
  if (!is.numeric(probs) || anyNA(probs) || any(probs < 0 | probs > 1)) stop("bad probs")
  d <- data.frame(g = as.character(data[[group]]), v = data[[value]], stringsAsFactors = FALSE)
  d <- d[!is.na(d$g) & !is.na(d$v), ]
  out <- dplyr::reframe(dplyr::group_by(d, g), prob = probs,
                        value = unname(stats::quantile(v, probs, type = 7)))
  out <- as.data.frame(dplyr::ungroup(out))
  names(out)[1] <- group
  out[order(out[[group]], match(out$prob, probs)), ]
}

#### control: alternate_base_r_split
# Alternate valid solution: base R only.
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) {
  stopifnot(is.numeric(probs), !anyNA(probs), all(probs >= 0 & probs <= 1))
  g <- as.character(data[[group]])
  v <- data[[value]]
  ok <- !is.na(g) & !is.na(v)
  rows <- lapply(sort(unique(g[ok])), function(k) {
    x <- v[ok & g == k]
    data.frame(k, probs, as.numeric(stats::quantile(x, probs)), stringsAsFactors = FALSE)
  })
  out <- do.call(rbind, rows)
  names(out) <- c(group, "prob", "value")
  rownames(out) <- NULL
  out
}

#### control: wrong_summarise_multirow
# Plausible wrong strategy from older tutorials: summarise() with several rows per group.
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) {
  if (anyNA(probs) || any(probs < 0 | probs > 1)) stop("bad probs")
  d <- data.frame(g = data[[group]], v = data[[value]])
  d <- d[!is.na(d$g) & !is.na(d$v), ]
  out <- dplyr::summarise(dplyr::group_by(d, g), prob = probs,
                          value = stats::quantile(v, probs), .groups = "drop")
  names(out)[1] <- group
  as.data.frame(out)
}

#### control: wrong_quantile_type_6
# Plausible wrong strategy: a different quantile definition.
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) {
  if (anyNA(probs) || any(probs < 0 | probs > 1)) stop("bad probs")
  g <- as.character(data[[group]])
  v <- data[[value]]
  ok <- !is.na(g) & !is.na(v)
  rows <- lapply(sort(unique(g[ok])), function(k) {
    data.frame(k, probs, as.numeric(stats::quantile(v[ok & g == k], probs, type = 6)), stringsAsFactors = FALSE)
  })
  out <- do.call(rbind, rows)
  names(out) <- c(group, "prob", "value")
  out
}

#### control: wrong_ignores_probs_argument
# Plausible wrong strategy: quartiles hard-coded, probs ignored.
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) {
  if (anyNA(probs) || any(probs < 0 | probs > 1)) stop("bad probs")
  probs <- c(0.25, 0.5, 0.75)
  g <- as.character(data[[group]])
  v <- data[[value]]
  ok <- !is.na(g) & !is.na(v)
  rows <- lapply(sort(unique(g[ok])), function(k) {
    data.frame(k, probs, as.numeric(stats::quantile(v[ok & g == k], probs)), stringsAsFactors = FALSE)
  })
  out <- do.call(rbind, rows)
  names(out) <- c(group, "prob", "value")
  out
}

#### control: wrong_keeps_empty_group_as_na
# Plausible wrong strategy: groups without data stay as NA rows instead of being omitted.
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) {
  if (anyNA(probs) || any(probs < 0 | probs > 1)) stop("bad probs")
  g <- as.character(data[[group]])
  v <- data[[value]]
  rows <- lapply(sort(unique(g[!is.na(g)])), function(k) {
    x <- v[!is.na(g) & g == k & !is.na(v)]
    q <- if (length(x)) as.numeric(stats::quantile(x, probs)) else rep(NA_real_, length(probs))
    data.frame(k, probs, q, stringsAsFactors = FALSE)
  })
  out <- do.call(rbind, rows)
  names(out) <- c(group, "prob", "value")
  out
}

#### control: edge_no_probs_validation
# Boundary case: correct for valid input but never validates probs (expected: not fully correct).
# expect: fail
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) {
  g <- as.character(data[[group]])
  v <- data[[value]]
  ok <- !is.na(g) & !is.na(v)
  rows <- lapply(sort(unique(g[ok])), function(k) {
    data.frame(k, probs, as.numeric(stats::quantile(v[ok & g == k], probs, names = FALSE)), stringsAsFactors = FALSE)
  })
  out <- do.call(rbind, rows)
  names(out) <- c(group, "prob", "value")
  out
}

#### control: malformed_returns_list
# Malformed submission: a named list instead of a data frame.
# expect: fail
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) {
  split(data[[value]], data[[group]])
}

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
group_quantiles <- function(data, group, value, probs = c(0.25, 0.5, 0.75)) stop("todo")
