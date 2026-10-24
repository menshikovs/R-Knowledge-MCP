# H04 — Point-in-time quote matching without future leakage

Write `/candidate/solution.R` defining:

```r
asof_price(trades, quotes)
```

Installed packages you may use include dplyr 1.2.1 and tibble 3.3.1 (see
`renv.lock`); data.table is not installed. Do not install packages. Sourcing
`solution.R` must only define functions.

## Inputs

- `trades`: a data frame with at least `symbol` (character) and `trade_time`
  (POSIXct). It may contain any other columns, but never columns named
  `quote_time`, `quote_seq`, `price` or `quote_age_seconds`.
- `quotes`: a data frame with `symbol` (character), `quote_time` (POSIXct),
  `quote_seq` (integer) and `price` (double).

`trade_time` and `quote_time` may carry different `tzone` attributes and may have
fractional seconds; only the underlying instants matter. Neither table is sorted.

## Matching rule

For each trade row, consider the quotes with exactly the same `symbol` (case
sensitive), a non-missing `quote_time` and a non-missing `price`, and with
`quote_time <= trade_time`. Take the one with the latest `quote_time`; if several
share that latest time, take the one with the largest `quote_seq`.

The match is used only if `trade_time - quote_time` is at most 30 minutes
(1800 seconds, inclusive). A trade with a missing `symbol` or `trade_time`, no
eligible quote, or only a stale latest quote gets no match.

## Result

A data frame (a tibble is fine) with one row per trade row, in the original trade
order (duplicate trade rows stay duplicated), with all original `trades` columns
first and unchanged, followed by:

- `quote_time`: POSIXct with `tzone` `"UTC"` (`NA` when unmatched);
- `quote_seq`: integer (`NA_integer_` when unmatched);
- `price`: double (`NA_real_` when unmatched);
- `quote_age_seconds`: double, `trade_time - quote_time` in seconds (`NA_real_`
  when unmatched).

Zero-row `trades` give a zero-row result with these columns; zero-row `quotes` give
no matches. Neither input may be modified. Inputs with 100,000 trades and
100,000 quotes must finish within 30 seconds on 2 CPUs.

`data/trades.csv` and `data/quotes.csv` are a small example with times in UTC (for
example `as.POSIXct(x, tz = "UTC")`). Test your function locally with installed R
before finishing.
