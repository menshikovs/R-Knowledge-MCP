# Wrong: base merge() + aggregation reorders rows and collapses duplicate trades.
asof_price <- function(trades, quotes) {
  q <- quotes[!is.na(quotes$quote_time) & !is.na(quotes$price), ]
  t <- unique(as.data.frame(trades))
  joined <- merge(t, q, by = "symbol", all.x = TRUE, sort = TRUE)
  joined$age <- as.numeric(joined$trade_time) - as.numeric(joined$quote_time)
  ok <- !is.na(joined$age) & joined$age >= 0 & joined$age <= 1800
  joined <- joined[ok | is.na(joined$age), ]
  joined <- joined[order(joined$symbol, joined$trade_time, -as.numeric(joined$quote_time), -joined$quote_seq), ]
  key <- do.call(paste, c(joined[names(trades)], sep = ""))
  joined <- joined[!duplicated(key), ]
  result <- tibble::as_tibble(joined[names(trades)])
  result$quote_time <- .POSIXct(as.numeric(joined$quote_time), tz = "UTC")
  result$quote_seq <- as.integer(joined$quote_seq)
  result$price <- as.double(joined$price)
  result$quote_age_seconds <- as.double(joined$age)
  result
}
