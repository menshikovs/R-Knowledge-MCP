# Public sample fixture for XV02 (candidate-visible). Seed 2038 is NOT used by any hidden variant.
set.seed(2038, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
skus <- c("A1", "B2", "C3")
prices <- do.call(rbind, lapply(skus, function(s) {
  k <- sample(2:4, 1)
  dates <- sort(as.Date("2026-01-01") + sample(0:80, k))
  data.frame(sku = s, price_date = format(dates), price = round(cumsum(c(10, runif(k - 1, -1, 2))) , 2))
}))
n <- 25L
orders <- data.frame(order_id = 1000L + seq_len(n), sku = sample(c(skus, "Z9"), n, replace = TRUE),
                     order_date = format(as.Date("2025-12-20") + sample(0:100, n, replace = TRUE)))
out <- Sys.getenv("OUT_DIR", "/out")
write.csv(prices, file.path(out, "prices.csv"), row.names = FALSE)
write.csv(orders, file.path(out, "orders.csv"), row.names = FALSE)
