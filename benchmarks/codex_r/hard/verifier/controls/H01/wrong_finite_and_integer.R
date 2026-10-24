# Wrong: treats only NA as invalid (Inf passes through) and sums integer weights in
# integer arithmetic, which overflows to NA.
dynamic_summary <- function(data, groups, measure, weight) {
  if (!all(c(groups, measure, weight) %in% names(data)) || anyDuplicated(groups) ||
      !is.numeric(data[[measure]]) || !is.numeric(data[[weight]])) {
    rlang::abort("bad column", class = "dynamic_summary_bad_column")
  }
  w <- data[[weight]]
  if (any(!is.na(w) & w < 0)) rlang::abort("negative", class = "dynamic_summary_negative_weight")
  data |>
    dplyr::ungroup() |>
    dplyr::mutate(.valid = !is.na(.data[[measure]]) & !is.na(.data[[weight]])) |>
    dplyr::group_by(dplyr::across(dplyr::all_of(groups))) |>
    dplyr::summarise(
      .ws = sum(.data[[weight]][.valid]),
      weighted_mean = if (isTRUE(.ws > 0)) sum((.data[[weight]] * .data[[measure]])[.valid]) / .ws else NA_real_,
      n_valid = sum(.valid),
      weight_sum = as.double(.ws),
      .groups = "drop"
    ) |>
    dplyr::select(-".ws") |>
    dplyr::arrange(dplyr::pick(dplyr::all_of(groups)), .locale = "C")
}
