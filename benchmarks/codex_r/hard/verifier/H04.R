# Hidden behavioral checks for H04 (point-in-time quote matching).

utc <- function(x, tz = "UTC") as.POSIXct(x, tz = tz, format = "%Y-%m-%d %H:%M:%OS")

# Independent slow oracle: a nested scan in base R, no joins.
h04_oracle <- function(trades, quotes) {
  qt <- as.numeric(quotes$quote_time)
  usable <- !is.na(quotes$symbol) & !is.na(qt) & !is.na(quotes$price)
  n <- nrow(trades)
  out <- data.frame(quote_time = rep(NA_real_, n), quote_seq = rep(NA_integer_, n),
                    price = rep(NA_real_, n), quote_age_seconds = rep(NA_real_, n))
  for (i in seq_len(n)) {
    s <- trades$symbol[i]
    t <- as.numeric(trades$trade_time[i])
    if (is.na(s) || is.na(t)) next
    rows <- which(usable & quotes$symbol == s & qt <= t)
    if (!length(rows)) next
    latest <- rows[qt[rows] == max(qt[rows])]
    best <- latest[which.max(quotes$quote_seq[latest])]
    if (t - qt[best] > 1800) next
    out$quote_time[i] <- qt[best]
    out$quote_seq[i] <- quotes$quote_seq[best]
    out$price[i] <- quotes$price[best]
    out$quote_age_seconds[i] <- t - qt[best]
  }
  out
}

expect_asof <- function(result, trades, quotes) {
  expected <- h04_oracle(trades, quotes)
  testthat::expect_true(is.data.frame(result))
  testthat::expect_identical(
    names(result), c(names(trades), "quote_time", "quote_seq", "price", "quote_age_seconds")
  )
  testthat::expect_identical(nrow(result), nrow(trades))
  for (column in names(trades)) {
    testthat::expect_identical(result[[column]], trades[[column]], info = column)
  }
  testthat::expect_s3_class(result$quote_time, "POSIXct")
  testthat::expect_identical(attr(result$quote_time, "tzone"), "UTC")
  testthat::expect_identical(as.numeric(result$quote_time), expected$quote_time)
  testthat::expect_identical(result$quote_seq, expected$quote_seq)
  testthat::expect_identical(result$price, expected$price)
  testthat::expect_type(result$quote_age_seconds, "double")
  testthat::expect_equal(result$quote_age_seconds, expected$quote_age_seconds, tolerance = 1e-9)
}

h04_case <- function(trades, quotes) {
  result <- call_candidate("asof_price", trades, quotes)
  expect_no_candidate_warnings(result)
  expect_asof(value_of(result), trades, quotes)
  value_of(result)
}

h04_quotes <- function() {
  data.frame(
    symbol = c("ACME", "ACME", "ACME", "ACME", "GLOBX", "ACME"),
    quote_time = utc(c("2026-03-02 14:29:59", "2026-03-02 14:30:00.25", "2026-03-02 14:30:00.25",
                       "2026-03-02 14:30:00.3", "2026-03-02 13:59:00", "2026-03-02 13:59:30")),
    quote_seq = c(7L, 9L, 8L, 10L, 3L, 2L),
    price = c(101.5, 101.75, 101.7, 999, 55.2, 100)
  )
}

h04_trades <- function() {
  data.frame(
    trade_id = c("T1", "T2", "T3", "T1", "T4"),
    symbol = c("ACME", "ACME", "GLOBX", "ACME", "ACME"),
    trade_time = utc(c("2026-03-02 14:30:00.25", "2026-03-02 14:00:00", "2026-03-02 14:31:00",
                       "2026-03-02 14:30:00.25", "2026-03-02 15:10:00")),
    qty = c(100L, 50L, 10L, 100L, 20L)
  )
}

check("matches_latest_prior_quote", {
  h04_case(h04_trades(), h04_quotes())
})

check("quote_one_millisecond_after_trade_never_matches", {
  base <- as.numeric(utc("2026-03-02 10:00:00"))
  trades <- data.frame(symbol = "A", trade_time = .POSIXct(base + 10, tz = "UTC"))
  quotes <- data.frame(symbol = c("A", "A"), quote_time = .POSIXct(c(base, base + 10.001), tz = "UTC"),
                       quote_seq = c(1L, 2L), price = c(1, 2))
  result <- h04_case(trades, quotes)
  testthat::expect_identical(result$quote_seq, 1L)
})

check("quote_at_exact_trade_time_matches", {
  at <- utc("2026-03-02 10:00:00.5")
  trades <- data.frame(symbol = "A", trade_time = at)
  quotes <- data.frame(symbol = c("A", "A"), quote_time = c(at - 1, at),
                       quote_seq = c(1L, 2L), price = c(1, 2))
  result <- h04_case(trades, quotes)
  testthat::expect_identical(result$price, 2)
})

check("staleness_bound_is_inclusive_1800_seconds", {
  q <- as.numeric(utc("2026-03-02 10:00:00.25"))
  trades <- data.frame(symbol = c("A", "A", "A"),
                       trade_time = .POSIXct(q + c(1800, 1800.001, 1799.999), tz = "UTC"))
  quotes <- data.frame(symbol = "A", quote_time = .POSIXct(q, tz = "UTC"), quote_seq = 1L, price = 5)
  result <- h04_case(trades, quotes)
  testthat::expect_identical(result$price, c(5, NA, 5))
})

check("equal_time_ties_use_largest_quote_seq", {
  at <- utc("2026-03-02 11:00:00")
  trades <- data.frame(symbol = "A", trade_time = at + 5)
  quotes <- data.frame(symbol = rep("A", 4), quote_time = c(at, at, at, at - 1),
                       quote_seq = c(5L, 9L, 7L, 20L), price = c(1, 2, 3, 4))
  result <- h04_case(trades, quotes)
  testthat::expect_identical(result$quote_seq, 9L)
})

check("unsorted_inputs_match_sorted_inputs", {
  trades <- h04_trades()
  quotes <- h04_quotes()
  h04_case(trades[c(5, 2, 4, 1, 3), ], quotes[c(6, 4, 1, 5, 3, 2), ])
})

check("trade_order_and_duplicates_are_preserved", {
  trades <- h04_trades()[c(1, 4, 1, 2, 1), ]
  result <- h04_case(trades, h04_quotes())
  testthat::expect_identical(result$trade_id, c("T1", "T1", "T1", "T2", "T1"))
})

check("unmatched_columns_are_typed_missing_values", {
  trades <- data.frame(symbol = c("NONE", "ACME"), trade_time = utc(c("2026-03-02 14:00:00", "2026-03-02 09:00:00")))
  result <- h04_case(trades, h04_quotes())
  testthat::expect_true(all(is.na(result$quote_time)))
  testthat::expect_type(result$quote_seq, "integer")
  testthat::expect_type(result$price, "double")
})

check("different_time_zones_and_dst_use_instants", {
  quotes <- data.frame(
    symbol = c("A", "A", "B"),
    quote_time = as.POSIXct(c("2026-03-08 15:30:00", "2026-03-08 16:10:00", "2026-11-01 15:20:00"),
                            tz = "Asia/Tokyo"),
    quote_seq = 1:3, price = c(10, 11, 12)
  )
  # 01:59 EST and 03:05 EDT straddle the US spring-forward jump; 01:30 occurs twice in fall.
  trades <- data.frame(
    symbol = c("A", "A", "B", "B"),
    trade_time = .POSIXct(c(1772953140, 1772953500, 1793511000, 1793514600), tz = "America/New_York")
  )
  result <- h04_case(trades, quotes)
  # 06:59Z uses the 06:30Z quote; 07:05Z must not use the future 07:10Z quote and the
  # 06:30Z one is stale; the first 01:30 (EDT) precedes the 06:20Z quote, the second
  # 01:30 (EST) is 10 minutes after it.
  testthat::expect_identical(result$price, c(10, NA, NA, 12))
})

check("quotes_with_missing_time_or_price_are_ignored", {
  at <- utc("2026-03-02 12:00:00")
  trades <- data.frame(symbol = "A", trade_time = at + 60)
  quotes <- data.frame(symbol = c("A", "A", "A"), quote_time = c(at, at + 30, as.POSIXct(NA)),
                       quote_seq = c(1L, 2L, 3L), price = c(7, NA, 9))
  result <- h04_case(trades, quotes)
  testthat::expect_identical(result$price, 7)
})

check("missing_trade_symbol_or_time_gets_no_match", {
  at <- utc("2026-03-02 12:00:00")
  trades <- data.frame(symbol = c(NA, "A", "A"), trade_time = c(at, as.POSIXct(NA), at))
  quotes <- data.frame(symbol = c(NA, "A"), quote_time = c(at - 1, at - 1), quote_seq = 1:2, price = c(1, 2))
  result <- h04_case(trades, quotes)
  testthat::expect_identical(result$price, c(NA, NA, 2))
})

check("symbols_are_case_sensitive", {
  at <- utc("2026-03-02 12:00:00")
  trades <- data.frame(symbol = c("abc", "ABC"), trade_time = c(at, at))
  quotes <- data.frame(symbol = "ABC", quote_time = at - 10, quote_seq = 1L, price = 3)
  result <- h04_case(trades, quotes)
  testthat::expect_identical(result$price, c(NA, 3))
})

check("extra_trade_columns_are_kept_unchanged", {
  trades <- h04_trades()
  trades$day <- as.Date("2026-03-02")
  trades$note <- c("a", NA, "c", "a", "e")
  h04_case(trades, h04_quotes())
  h04_case(tibble::as_tibble(trades), h04_quotes())
})

check("empty_trades_and_empty_quotes", {
  result <- h04_case(h04_trades()[0, ], h04_quotes())
  testthat::expect_identical(nrow(result), 0L)
  testthat::expect_s3_class(result$quote_time, "POSIXct")
  testthat::expect_type(result$quote_seq, "integer")
  none <- h04_case(h04_trades(), h04_quotes()[0, ])
  testthat::expect_true(all(is.na(none$price)))
})

check("inputs_are_not_modified", {
  trades <- h04_trades()
  quotes <- h04_quotes()
  result <- call_candidate("asof_price", trades, quotes)
  value_of(result)
  testthat::expect_identical(result$args_after[[1]], trades)
  testthat::expect_identical(result$args_after[[2]], quotes)
})

check("matches_slow_oracle_on_generated_data", {
  start <- as.numeric(utc("2026-03-02 09:30:00"))
  symbols <- c("A", "B", "C")
  i <- 0:399
  quotes <- data.frame(
    symbol = symbols[i %% 3 + 1],
    # Many repeated instants so ties are common; quarter-second resolution.
    quote_time = .POSIXct(start + ((i * 7919) %% 8000) * 0.25 * 3, tz = "UTC"),
    quote_seq = as.integer((i * 37) %% 101),
    price = 100 + i / 8
  )
  j <- 0:299
  trades <- data.frame(
    id = j,
    symbol = symbols[(j * 5) %% 3 + 1],
    trade_time = .POSIXct(start + ((j * 104729) %% 9000) * 0.75 + 1800 * (j %% 4 == 0), tz = "UTC")
  )
  h04_case(trades, quotes)
})

check("scales_to_100k_trades_and_quotes_within_30s", {
  n <- 100000L
  k <- seq_len(n) - 1L
  base <- as.numeric(utc("2026-03-02 09:30:00"))
  symbols <- sprintf("S%03d", 0:199)
  quotes <- data.frame(
    symbol = symbols[(k * 7L) %% 200L + 1L],
    quote_time = .POSIXct(base + (k * 13L) %% 23400L + 0.5, tz = "UTC"),
    quote_seq = k,
    price = 50 + (k %% 1000L) / 100
  )
  trades <- data.frame(
    symbol = symbols[(k * 11L) %% 200L + 1L],
    trade_time = .POSIXct(base + (k * 17L) %% 23400L, tz = "UTC")
  )
  result <- call_candidate("asof_price", trades, quotes, .timeout = 60)
  testthat::expect_lt(result$elapsed, 30)
  value <- value_of(result)
  sample_rows <- seq(1L, n, by = 997L)
  expected <- h04_oracle(trades[sample_rows, ], quotes)
  testthat::expect_identical(value$quote_seq[sample_rows], expected$quote_seq)
  testthat::expect_identical(value$price[sample_rows], expected$price)
})
