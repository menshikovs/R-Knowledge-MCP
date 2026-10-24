# Wrong: turns column names into code with rlang::parse_expr(), which breaks on
# non-syntactic names and can capture variables instead of columns.
dynamic_summary <- function(data, groups, measure, weight) {
  if (!all(c(groups, measure, weight) %in% names(data)) || anyDuplicated(groups) ||
      !is.numeric(data[[measure]]) || !is.numeric(data[[weight]])) {
    rlang::abort("bad column", class = "dynamic_summary_bad_column")
  }
  w <- data[[weight]]
  if (any(is.finite(w) & w < 0)) rlang::abort("negative", class = "dynamic_summary_negative_weight")
  x_expr <- rlang::parse_expr(measure)
  w_expr <- rlang::parse_expr(weight)
  out <- data |>
    dplyr::ungroup() |>
    dplyr::mutate(.valid = is.finite(!!x_expr) & is.finite(!!w_expr)) |>
    dplyr::group_by(dplyr::across(dplyr::all_of(groups))) |>
    dplyr::summarise(
      weight_sum = sum(as.double((!!w_expr)[.valid])),
      weighted_mean = if (weight_sum > 0) sum(((!!w_expr) * (!!x_expr))[.valid]) / weight_sum else NA_real_,
      n_valid = sum(.valid),
      .groups = "drop"
    )
  out <- dplyr::relocate(out, "weight_sum", .after = "n_valid")
  dplyr::arrange(out, dplyr::pick(dplyr::all_of(groups)), .locale = "C")
}
