invoice_totals <- function(lines) {
  # BUG: sums duplicate ingestion records and ignores latest cancellations.
  lines |>
    dplyr::group_by(invoice_id) |>
    dplyr::summarise(
      line_count = dplyr::n(),
      total = sum(quantity * unit_price),
      .groups = "drop"
    )
}
