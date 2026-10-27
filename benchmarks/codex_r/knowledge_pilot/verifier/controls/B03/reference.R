invoice_totals <- function(lines) {
  lines |>
    dplyr::arrange(invoice_id, line_id, revision, dplyr::desc(received_at)) |>
    dplyr::distinct(invoice_id, line_id, revision, .keep_all=TRUE) |>
    dplyr::group_by(invoice_id, line_id) |>
    dplyr::slice_max(revision, n=1, with_ties=FALSE) |>
    dplyr::ungroup() |>
    dplyr::filter(status == "active") |>
    dplyr::group_by(invoice_id) |>
    dplyr::summarise(line_count=as.integer(dplyr::n()),
                     total=sum(quantity * unit_price), .groups="drop") |>
    dplyr::arrange(invoice_id)
}
