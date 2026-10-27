ledger_summary <- function(data, from, through) {
  # BUG: date range is exclusive and unposted rows are included.
  dplyr::filter(data, posted_at > from, posted_at < through) |>
    dplyr::group_by(account) |>
    dplyr::summarise(
      transactions = dplyr::n(),
      total = sum(amount),
      first_posted = min(posted_at),
      last_posted = max(posted_at),
      .groups = "drop"
    )
}
