measurements_wide <- function(data) {
  # BUG: duplicate values error and explicit missing cells become zero.
  tidyr::pivot_wider(
    data,
    names_from = analyte,
    values_from = value,
    values_fill = 0
  )
}
