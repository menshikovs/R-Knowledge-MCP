# Trusted reference for H01. Hidden: never copied into an agent workspace.
dynamic_summary <- function(data, groups, measure, weight) {
  bad <- function(message) rlang::abort(message, class = "dynamic_summary_bad_column")
  if (!is.data.frame(data)) bad("`data` must be a data frame.")
  if (!is.character(groups) || anyNA(groups) || anyDuplicated(groups)) {
    bad("`groups` must be distinct column names.")
  }
  for (name in list(measure, weight)) {
    if (!is.character(name) || length(name) != 1L || is.na(name)) {
      bad("`measure` and `weight` must be single column names.")
    }
  }
  data <- tibble::as_tibble(dplyr::ungroup(data))
  missing <- setdiff(c(groups, measure, weight), names(data))
  if (length(missing)) bad(paste("Unknown column:", missing[[1]]))
  x <- data[[measure]]
  w <- data[[weight]]
  if (!is.numeric(x) || !is.numeric(w)) bad("`measure` and `weight` must be numeric.")
  if (any(is.finite(w) & w < 0)) {
    rlang::abort("Weights must not be negative.", class = "dynamic_summary_negative_weight")
  }
  valid <- is.finite(x) & is.finite(w)
  keys <- data[groups]
  if (length(groups) == 0L) {
    keys <- tibble::new_tibble(list(), nrow = 1L)
    id <- rep.int(1L, nrow(data))
  } else {
    id <- vctrs::vec_group_id(keys)
    keys <- vctrs::vec_slice(keys, vctrs::vec_unique_loc(id))
  }
  groups_n <- nrow(keys)
  xv <- ifelse(valid, as.double(x), 0)
  wv <- ifelse(valid, as.double(w), 0)
  weighted <- vapply(seq_len(groups_n), function(g) sum((wv * xv)[id == g]), numeric(1))
  weight_sum <- vapply(seq_len(groups_n), function(g) sum(wv[id == g]), numeric(1))
  n_valid <- tabulate(id[valid], nbins = groups_n)
  # Explicit double vector: ifelse() on zero groups would return logical(0).
  weighted_mean <- rep(NA_real_, groups_n)
  positive <- weight_sum > 0
  weighted_mean[positive] <- weighted[positive] / weight_sum[positive]
  result <- keys
  result[["weighted_mean"]] <- weighted_mean
  result[["n_valid"]] <- as.integer(n_valid)
  result[["weight_sum"]] <- weight_sum
  if (length(groups) && groups_n > 1L) {
    # No data mask here: dplyr::pick() would see the .data pronoun, not a column
    # named ".data". Radix ordering sorts strings in the C locale, factors by level.
    ord <- do.call(order, c(unname(as.list(keys)), list(na.last = TRUE, method = "radix")))
    result <- vctrs::vec_slice(result, ord)
  }
  result
}
