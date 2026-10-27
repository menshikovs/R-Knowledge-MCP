ledger_summary <- function(data, from, through) {
  dplyr::filter(data, posted_at > from, posted_at < through) |>
    dplyr::group_by(account) |>
    dplyr::summarise(transactions=dplyr::n(), total=sum(amount), .groups="drop")
}
