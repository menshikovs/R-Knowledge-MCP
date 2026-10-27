measurements_wide <- function(data) {
  out <- data |>
    tidyr::pivot_wider(
      id_cols=sample, names_from=analyte, values_from=value,
      values_fn=list(value=function(x) if (all(is.na(x))) NA_real_ else sum(x, na.rm=TRUE)),
      values_fill=0
    )
  dplyr::select(out, sample, dplyr::all_of(sort(setdiff(names(out), "sample"))))
}
