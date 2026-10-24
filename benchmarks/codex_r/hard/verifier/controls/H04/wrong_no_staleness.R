# Wrong: ignores the 30-minute staleness bound.
asof_price <- function(trades, quotes) {
  usable <- !is.na(quotes$symbol) & !is.na(quotes$quote_time) & !is.na(quotes$price)
  left <- tibble::tibble(
    .row = seq_len(nrow(trades)),
    symbol = as.character(trades$symbol),
    .t = as.numeric(trades$trade_time)
  )
  right <- tibble::tibble(
    symbol = as.character(quotes$symbol[usable]),
    .q = as.numeric(quotes$quote_time[usable]),
    quote_seq = as.integer(quotes$quote_seq[usable]),
    price = as.double(quotes$price[usable])
  )
  # closest() keeps every quote tied at the latest time; ties are resolved below.
  matched <- dplyr::left_join(
    left,
    right,
    by = dplyr::join_by(symbol, closest(.t >= .q)),
    na_matches = "never",
    relationship = "many-to-many"
  )
  matched <- matched[order(matched$.row, -matched$quote_seq, na.last = TRUE), ]
  matched <- matched[!duplicated(matched$.row), ]
  age <- matched$.t - matched$.q
  # The latest earlier quote is the freshest one, so a stale match means no match.
  fresh <- !is.na(age)
  # Typed vectors: ifelse() on zero trades would return logical(0).
  n <- nrow(trades)
  quote_time <- rep(NA_real_, n)
  quote_seq <- rep(NA_integer_, n)
  price <- rep(NA_real_, n)
  quote_age <- rep(NA_real_, n)
  quote_time[fresh] <- matched$.q[fresh]
  quote_seq[fresh] <- matched$quote_seq[fresh]
  price[fresh] <- matched$price[fresh]
  quote_age[fresh] <- age[fresh]
  result <- tibble::as_tibble(trades)
  result$quote_time <- .POSIXct(quote_time, tz = "UTC")
  result$quote_seq <- quote_seq
  result$price <- price
  result$quote_age_seconds <- quote_age
  result
}
