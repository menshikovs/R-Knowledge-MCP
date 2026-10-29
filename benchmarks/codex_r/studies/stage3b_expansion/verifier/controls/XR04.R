#### control: reference
# Trusted reference: pivot_wider() with an explicit aggregation function, then explicit sorting.
wide_means <- function(data) {
  if (!nrow(data)) return(data.frame(id = data$id))
  d <- data[!is.na(data$value), c("id", "key", "value")]
  ids <- sort(unique(data$id))
  keys <- sort(unique(as.character(data$key)), method = "radix")
  agg <- stats::aggregate(value ~ id + key, data = d, FUN = mean)
  out <- data.frame(id = ids, stringsAsFactors = FALSE)
  for (k in keys) {
    sub <- agg[agg$key == k, ]
    out[[k]] <- as.numeric(sub$value[match(ids, sub$id)])
  }
  names(out) <- c("id", keys)
  out
}

#### control: alternate_tidyr_pivot_wider
# Alternate valid solution: tidyr::pivot_wider with values_fn.
wide_means <- function(data) {
  ids <- sort(unique(data$id))
  keys <- sort(unique(as.character(data$key)), method = "radix")
  w <- tidyr::pivot_wider(data, id_cols = "id", names_from = "key", values_from = "value",
                          values_fn = function(v) if (all(is.na(v))) NA_real_ else mean(v, na.rm = TRUE))
  w <- as.data.frame(w)
  for (k in setdiff(keys, names(w))) w[[k]] <- NA_real_
  w <- w[match(ids, w$id), c("id", keys), drop = FALSE]
  w$id <- ids
  rownames(w) <- NULL
  w
}

#### control: wrong_legacy_spread_unchanged
# The legacy code as delivered: spread() errors on duplicated id/key pairs.
wide_means <- function(data) {
  as.data.frame(tidyr::spread(data, key, value))
}

#### control: wrong_pivot_wider_list_columns
# Plausible wrong strategy: pivot_wider() without values_fn gives list-columns (and warns).
wide_means <- function(data) {
  as.data.frame(tidyr::pivot_wider(data, names_from = key, values_from = value))
}

#### control: wrong_sum_instead_of_mean
# Plausible wrong strategy: duplicates summed.
wide_means <- function(data) {
  ids <- sort(unique(data$id))
  keys <- sort(unique(as.character(data$key)), method = "radix")
  out <- data.frame(id = ids)
  for (k in keys) {
    out[[k]] <- vapply(ids, function(i) {
      v <- data$value[data$id == i & data$key == k]
      v <- v[!is.na(v)]
      if (length(v)) sum(v) else NA_real_
    }, numeric(1))
  }
  names(out) <- c("id", keys)
  out
}

#### control: wrong_missing_values_poison_the_mean
# Plausible wrong strategy: mean() without na.rm, so a missing repeat voids the cell.
wide_means <- function(data) {
  ids <- sort(unique(data$id))
  keys <- sort(unique(as.character(data$key)), method = "radix")
  out <- data.frame(id = ids)
  for (k in keys) {
    out[[k]] <- vapply(ids, function(i) {
      v <- data$value[data$id == i & data$key == k]
      if (length(v)) mean(v) else NA_real_
    }, numeric(1))
  }
  names(out) <- c("id", keys)
  out
}

#### control: wrong_columns_in_order_of_appearance
# Plausible wrong strategy: key columns follow first appearance instead of alphabetical order.
wide_means <- function(data) {
  ids <- sort(unique(data$id))
  keys <- unique(as.character(data$key))
  out <- data.frame(id = ids)
  for (k in keys) {
    out[[k]] <- vapply(ids, function(i) {
      v <- data$value[data$id == i & data$key == k]
      v <- v[!is.na(v)]
      if (length(v)) mean(v) else NA_real_
    }, numeric(1))
  }
  names(out) <- c("id", keys)
  out
}

#### control: edge_drops_ids_with_only_missing_values
# Boundary case: right except that all-missing ids vanish (expected: not fully correct).
# expect: fail
wide_means <- function(data) {
  d <- data[!is.na(data$value), ]
  ids <- sort(unique(d$id))
  keys <- sort(unique(as.character(data$key)), method = "radix")
  out <- data.frame(id = ids)
  for (k in keys) {
    out[[k]] <- vapply(ids, function(i) {
      v <- d$value[d$id == i & d$key == k]
      if (length(v)) mean(v) else NA_real_
    }, numeric(1))
  }
  names(out) <- c("id", keys)
  out
}

#### control: malformed_returns_matrix
# Malformed submission: a numeric matrix.
# expect: fail
wide_means <- function(data) tapply(data$value, list(data$id, data$key), mean, na.rm = TRUE)

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
wide_means <- function(data) NULL
