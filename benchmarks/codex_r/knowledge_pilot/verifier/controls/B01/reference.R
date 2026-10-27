ledger_summary <- function(data, from, through) {
  x <- data |>
    dplyr::mutate(.date = suppressWarnings(as.Date(posted_at))) |>
    dplyr::filter(
      posted %in% TRUE, !is.na(account), nzchar(account), is.finite(amount),
      !is.na(.date), .date >= as.Date(from), .date <= as.Date(through)
    )
  if (!nrow(x)) {
    return(data.frame(account=character(), transactions=integer(), total=double(),
                      first_posted=character(), last_posted=character()))
  }
  x |>
    dplyr::group_by(account) |>
    dplyr::summarise(
      transactions=as.integer(dplyr::n()), total=sum(amount),
      first_posted=format(min(.date), "%Y-%m-%d"),
      last_posted=format(max(.date), "%Y-%m-%d"), .groups="drop"
    ) |>
    dplyr::arrange(account) |>
    dplyr::select(account, transactions, total, first_posted, last_posted)
}
