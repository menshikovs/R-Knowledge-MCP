# Wrong: filters invalid rows before grouping (drops all-invalid groups) and lets
# 0/0 produce NaN instead of NA_real_.
dynamic_summary <- function(data, groups, measure, weight) {
  if (!all(c(groups, measure, weight) %in% names(data)) || anyDuplicated(groups) ||
      !is.numeric(data[[measure]]) || !is.numeric(data[[weight]])) {
    rlang::abort("bad column", class = "dynamic_summary_bad_column")
  }
  w <- data[[weight]]
  if (any(is.finite(w) & w < 0)) rlang::abort("negative", class = "dynamic_summary_negative_weight")
  data |>
    dplyr::ungroup() |>
    dplyr::filter(is.finite(.data[[measure]]), is.finite(.data[[weight]])) |>
    dplyr::group_by(dplyr::across(dplyr::all_of(groups))) |>
    dplyr::summarise(
      weighted_mean = sum(.data[[weight]] * .data[[measure]]) / sum(.data[[weight]]),
      n_valid = dplyr::n(),
      weight_sum = as.double(sum(.data[[weight]])),
      .groups = "drop"
    ) |>
    dplyr::arrange(dplyr::pick(dplyr::all_of(groups)), .locale = "C")
}
