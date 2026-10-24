# Wrong: picks the quote nearest in absolute time, leaking quotes after the trade.
asof_price <- function(trades, quotes) {
  usable <- !is.na(quotes$symbol) & !is.na(quotes$quote_time) & !is.na(quotes$price)
  q <- quotes[usable, ]
  qt <- as.numeric(q$quote_time)
  n <- nrow(trades)
  quote_time <- rep(NA_real_, n); quote_seq <- rep(NA_integer_, n)
  price <- rep(NA_real_, n); quote_age <- rep(NA_real_, n)
  by_symbol <- split(seq_len(nrow(q)), q$symbol)
  for (i in seq_len(n)) {
    t <- as.numeric(trades$trade_time[i]); s <- trades$symbol[i]
    if (is.na(t) || is.na(s) || is.null(by_symbol[[s]])) next
    rows <- by_symbol[[s]]
    distance <- abs(qt[rows] - t)
    best <- rows[distance == min(distance)]
    best <- best[which.max(q$quote_seq[best])]
    if (abs(t - qt[best]) > 1800) next
    quote_time[i] <- qt[best]; quote_seq[i] <- q$quote_seq[best]
    price[i] <- q$price[best]; quote_age[i] <- t - qt[best]
  }
  result <- tibble::as_tibble(trades)
  result$quote_time <- .POSIXct(quote_time, tz = "UTC")
  result$quote_seq <- quote_seq
  result$price <- price
  result$quote_age_seconds <- quote_age
  result
}
