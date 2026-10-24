# Wrong only on scale: correct per-trade scan over every quote, O(trades x quotes).
asof_price <- function(trades, quotes) {
  usable <- !is.na(quotes$symbol) & !is.na(quotes$quote_time) & !is.na(quotes$price)
  qt <- as.numeric(quotes$quote_time)
  n <- nrow(trades)
  quote_time <- rep(NA_real_, n); quote_seq <- rep(NA_integer_, n)
  price <- rep(NA_real_, n); quote_age <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    t <- as.numeric(trades$trade_time[i]); s <- trades$symbol[i]
    if (is.na(t) || is.na(s)) next
    rows <- which(usable & quotes$symbol == s & qt <= t)
    if (!length(rows)) next
    latest <- rows[qt[rows] == max(qt[rows])]
    best <- latest[which.max(quotes$quote_seq[latest])]
    if (t - qt[best] > 1800) next
    quote_time[i] <- qt[best]; quote_seq[i] <- quotes$quote_seq[best]
    price[i] <- quotes$price[best]; quote_age[i] <- t - qt[best]
  }
  result <- tibble::as_tibble(trades)
  result$quote_time <- .POSIXct(quote_time, tz = "UTC")
  result$quote_seq <- quote_seq
  result$price <- price
  result$quote_age_seconds <- quote_age
  result
}
