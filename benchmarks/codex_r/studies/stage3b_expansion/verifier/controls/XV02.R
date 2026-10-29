#### control: reference
# Trusted reference: dplyr rolling join on the price start date.
price_in_force <- function(orders, prices) {
  o <- orders
  o$.row <- seq_len(nrow(o))
  j <- dplyr::left_join(o, prices, by = dplyr::join_by(sku, closest(order_date >= price_date)))
  j <- j[order(j$.row), ]
  out <- data.frame(order_id = j$order_id, sku = j$sku, order_date = j$order_date,
                    price_date = j$price_date, price = j$price, stringsAsFactors = FALSE)
  out
}

#### control: alternate_base_r_findinterval
# Alternate valid solution: base R, per-sku findInterval on sorted start dates.
price_in_force <- function(orders, prices) {
  n <- nrow(orders)
  pd <- as.Date(rep(NA_real_, n))
  pr <- rep(NA_real_, n)
  for (s in unique(orders$sku)) {
    h <- prices[prices$sku == s, ]
    h <- h[order(h$price_date), ]
    idx <- which(orders$sku == s & !is.na(orders$order_date))
    if (!nrow(h) || !length(idx)) next
    k <- findInterval(as.numeric(orders$order_date[idx]), as.numeric(h$price_date))
    ok <- k > 0
    pd[idx[ok]] <- h$price_date[k[ok]]
    pr[idx[ok]] <- h$price[k[ok]]
  }
  data.frame(order_id = orders$order_id, sku = orders$sku, order_date = orders$order_date,
             price_date = pd, price = pr, stringsAsFactors = FALSE)
}

#### control: wrong_filter_after_join_warns_and_duplicates
# Plausible wrong strategy: join by sku, filter on the date, no deduplication of history rows.
price_in_force <- function(orders, prices) {
  j <- dplyr::left_join(orders, prices, by = "sku")
  j <- j[is.na(j$price_date) | j$price_date <= j$order_date, ]
  data.frame(order_id = j$order_id, sku = j$sku, order_date = j$order_date,
             price_date = j$price_date, price = j$price)
}

#### control: wrong_strict_inequality
# Plausible wrong strategy: price must start strictly before the order date.
price_in_force <- function(orders, prices) {
  n <- nrow(orders)
  pd <- rep(NA_real_, n)
  pr <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    h <- prices[prices$sku == orders$sku[i] & prices$price_date < orders$order_date[i], ]
    h <- h[!is.na(h$price_date), ]
    if (nrow(h)) {
      j <- which.max(as.numeric(h$price_date))
      pd[i] <- as.numeric(h$price_date[j])
      pr[i] <- h$price[j]
    }
  }
  data.frame(order_id = orders$order_id, sku = orders$sku, order_date = orders$order_date,
             price_date = as.Date(pd), price = pr)
}

#### control: wrong_uses_next_price
# Plausible wrong strategy (future leakage): takes the next price change after the order date.
price_in_force <- function(orders, prices) {
  n <- nrow(orders)
  pd <- rep(NA_real_, n)
  pr <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    h <- prices[prices$sku == orders$sku[i] & prices$price_date >= orders$order_date[i], ]
    h <- h[!is.na(h$price_date), ]
    if (nrow(h)) {
      j <- which.min(as.numeric(h$price_date))
      pd[i] <- as.numeric(h$price_date[j])
      pr[i] <- h$price[j]
    }
  }
  data.frame(order_id = orders$order_id, sku = orders$sku, order_date = orders$order_date,
             price_date = as.Date(pd), price = pr)
}

#### control: wrong_drops_unmatched_orders
# Plausible wrong strategy: inner join semantics, orders without a price vanish.
price_in_force <- function(orders, prices) {
  o <- orders
  o$.row <- seq_len(nrow(o))
  j <- dplyr::inner_join(o, prices, by = dplyr::join_by(sku, closest(order_date >= price_date)))
  j <- j[order(j$.row), ]
  data.frame(order_id = j$order_id, sku = j$sku, order_date = j$order_date,
             price_date = j$price_date, price = j$price)
}

#### control: wrong_output_sorted_by_date
# Plausible wrong strategy: right values but rows are returned sorted by order date.
price_in_force <- function(orders, prices) {
  o <- orders
  j <- dplyr::left_join(o, prices, by = dplyr::join_by(sku, closest(order_date >= price_date)))
  j <- j[order(j$order_date), ]
  data.frame(order_id = j$order_id, sku = j$sku, order_date = j$order_date,
             price_date = j$price_date, price = j$price)
}

#### control: edge_extra_helper_column
# Boundary case: correct values but an extra helper column leaks into the result (expected: fail).
# expect: fail
price_in_force <- function(orders, prices) {
  o <- orders
  o$.row <- seq_len(nrow(o))
  j <- dplyr::left_join(o, prices, by = dplyr::join_by(sku, closest(order_date >= price_date)))
  j <- j[order(j$.row), ]
  as.data.frame(j)
}

#### control: malformed_returns_vector
# Malformed submission: only the prices as a vector.
# expect: fail
price_in_force <- function(orders, prices) prices$price[match(orders$sku, prices$sku)]

#### control: malformed_incomplete_stub
# Incomplete submission.
# expect: fail
price_in_force <- function(orders, prices) NULL
