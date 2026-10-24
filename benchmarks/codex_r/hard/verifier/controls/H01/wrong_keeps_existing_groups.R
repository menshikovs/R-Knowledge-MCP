# Wrong: adds to an existing grouping instead of ignoring it, and returns a grouped
# result for multiple grouping columns (summarise's default .groups).
dynamic_summary <- function(data, groups, measure, weight) {
  if (!all(c(groups, measure, weight) %in% names(data)) || anyDuplicated(groups) ||
      !is.numeric(data[[measure]]) || !is.numeric(data[[weight]])) {
    rlang::abort("bad column", class = "dynamic_summary_bad_column")
  }
  w <- data[[weight]]
  if (any(is.finite(w) & w < 0)) rlang::abort("negative", class = "dynamic_summary_negative_weight")
  data |>
    dplyr::group_by(dplyr::across(dplyr::all_of(groups)), .add = TRUE) |>
    dplyr::summarise(
      .ok = list(is.finite(.data[[measure]]) & is.finite(.data[[weight]])),
      .ws = sum(as.double(.data[[weight]])[.ok[[1]]]),
      weighted_mean = if (.ws > 0) sum((.data[[weight]] * .data[[measure]])[.ok[[1]]]) / .ws else NA_real_,
      n_valid = sum(.ok[[1]]),
      weight_sum = .ws
    ) |>
    dplyr::select(-".ok", -".ws") |>
    dplyr::arrange(dplyr::pick(dplyr::all_of(groups)), .locale = "C", .by_group = TRUE)
}
