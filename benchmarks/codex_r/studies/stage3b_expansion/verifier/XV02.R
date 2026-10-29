# Hidden checks for XV02 (as-of / rolling price join, no future leakage, no join warnings).
# Oracle: explicit base-R scan of each sku's price history.

xv02_oracle <- function(orders, prices) {
  n <- nrow(orders)
  pd <- rep(NA_real_, n)
  pr <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    od <- orders$order_date[i]
    if (is.na(od)) next
    hist <- prices[prices$sku == orders$sku[i] & !is.na(prices$sku), , drop = FALSE]
    hist <- hist[hist$price_date <= od & !is.na(hist$price_date), , drop = FALSE]
    if (nrow(hist)) {
      j <- which.max(as.numeric(hist$price_date))
      pd[i] <- as.numeric(hist$price_date[j])
      pr[i] <- hist$price[j]
    }
  }
  list(price_date = pd, price = pr)
}

xv02_data <- function(seed, n_orders, skus, k_prices, unpriced = character(), same_day = TRUE) {
  with_seed(seed, {
    pr <- do.call(rbind, lapply(skus, function(s) {
      k <- sample(k_prices, 1)
      dates <- sort(as.Date("2026-01-01") + sample(0:120, k))
      data.frame(sku = s, price_date = dates, price = round(stats::runif(k, 5, 50), 2),
                 stringsAsFactors = FALSE)
    }))
    pr <- pr[sample.int(nrow(pr)), ]
    ord <- data.frame(
      order_id = 5000L + seq_len(n_orders),
      sku = sample(c(skus, unpriced), n_orders, replace = TRUE),
      order_date = as.Date("2025-12-25") + sample(0:140, n_orders, replace = TRUE),
      stringsAsFactors = FALSE
    )
    if (same_day) {
      pick <- which(ord$sku %in% pr$sku)[1:3]
      ord$order_date[pick] <- pr$price_date[match(ord$sku[pick], pr$sku)]
    }
    list(orders = ord, prices = pr)
  })
}

xv02_a <- xv02_data(871L, 60L, c("p1", "p2", "p3", "p4"), 2:5, unpriced = "zz")
xv02_b <- xv02_data(872L, 40L, c("k1", "k2"), 3:6, same_day = TRUE)
xv02_b$orders$order_date[c(4, 9)] <- NA

local({
  for (v in list(xv02_a, xv02_b)) {
    o <- xv02_oracle(v$orders, v$prices)
    stopifnot(anyNA(o$price), any(!is.na(o$price)))
    # Same-day orders exist, so a strict inequality would change the answer.
    stopifnot(any(vapply(seq_len(nrow(v$orders)), function(i) {
      isTRUE(any(v$prices$sku == v$orders$sku[i] & v$prices$price_date == v$orders$order_date[i]))
    }, logical(1))))
    stopifnot(!anyDuplicated(paste(v$prices$sku, v$prices$price_date)))
  }
})

xv02_call <- function(v) call_wrapped("price_in_force", v$orders, v$prices, .prelude = lifecycle_prelude)

check("price_matches_latest_start_on_or_before_the_order_date", {
  for (v in list(xv02_a, xv02_b)) {
    got <- value_of(xv02_call(v))
    want <- xv02_oracle(v$orders, v$prices)
    expect_close(ifelse(is.na(got$price), -1, got$price), ifelse(is.na(want$price), -1, want$price))
    testthat::expect_identical(is.na(got$price), is.na(want$price))
  }
})

check("price_date_is_the_start_of_the_applicable_price", {
  for (v in list(xv02_a, xv02_b)) {
    got <- value_of(xv02_call(v))
    want <- xv02_oracle(v$orders, v$prices)
    testthat::expect_s3_class(got$price_date, "Date")
    testthat::expect_identical(is.na(got$price_date), is.na(want$price_date))
    expect_close(ifelse(is.na(got$price_date), -1, as.numeric(got$price_date)),
                 ifelse(is.na(want$price_date), -1, want$price_date))
  }
})

check("one_row_per_order_in_the_original_order", {
  v <- xv02_a
  got <- value_of(xv02_call(v))
  testthat::expect_identical(nrow(got), nrow(v$orders))
  testthat::expect_identical(as.integer(got$order_id), as.integer(v$orders$order_id))
  testthat::expect_identical(as.character(got$sku), as.character(v$orders$sku))
  testthat::expect_identical(as.numeric(got$order_date), as.numeric(v$orders$order_date))
})

check("columns_are_exactly_the_specified_ones_in_order", {
  got <- value_of(xv02_call(xv02_a))
  testthat::expect_identical(names(got), c("order_id", "sku", "order_date", "price_date", "price"))
  testthat::expect_false(inherits(got, "grouped_df"))
})

check("orders_without_an_applicable_price_are_kept_with_missing_values", {
  v <- xv02_a
  got <- value_of(xv02_call(v))
  none <- v$orders$sku == "zz"
  testthat::expect_true(any(none))
  testthat::expect_true(all(is.na(got$price[none])))
  testthat::expect_true(all(is.na(got$price_date[none])))
  before <- v$orders$order_date < as.Date("2026-01-01")
  testthat::expect_true(all(is.na(got$price[before])))
})

check("a_price_that_starts_on_the_order_date_applies", {
  v <- xv02_a
  got <- value_of(xv02_call(v))
  hit <- which(vapply(seq_len(nrow(v$orders)), function(i) {
    isTRUE(any(v$prices$sku == v$orders$sku[i] & v$prices$price_date == v$orders$order_date[i]))
  }, logical(1)))
  testthat::expect_true(length(hit) >= 3)
  testthat::expect_identical(as.numeric(got$price_date[hit]), as.numeric(v$orders$order_date[hit]))
})

check("no_future_price_is_used", {
  for (v in list(xv02_a, xv02_b)) {
    got <- value_of(xv02_call(v))
    ok <- !is.na(got$price_date)
    testthat::expect_true(all(got$price_date[ok] <= got$order_date[ok]))
  }
})

check("missing_order_date_gives_missing_price_but_keeps_the_row", {
  v <- xv02_b
  got <- value_of(xv02_call(v))
  testthat::expect_true(all(is.na(got$price[c(4, 9)])))
  testthat::expect_identical(nrow(got), nrow(v$orders))
})

check("runs_without_warnings_including_join_relationship_notices", {
  res <- xv02_call(xv02_a)
  value_of(res)
  expect_no_warnings(res)
})

check("inputs_are_not_modified", {
  v <- xv02_a
  res <- xv02_call(v)
  value_of(res)
  testthat::expect_identical(res$args_after[[1]], v$orders)
  testthat::expect_identical(res$args_after[[2]], v$prices)
})
