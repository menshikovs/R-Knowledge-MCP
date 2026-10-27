fixture <- jsonlite::fromJSON("/candidate/data/promo_fixture.json")
sales <- fixture$sales
promos <- fixture$promos
sales$sale_date <- as.Date(sales$sale_date)
promos$promo_date <- as.Date(promos$promo_date)
check("keeps every sale and original order", {
  out <- value_of(call_candidate("nearest_promo", sales, promos))
  identical(out$sale_id, sales$sale_id) && nrow(out) == nrow(sales)
})
check("chooses closest earlier promo", {
  out <- value_of(call_candidate("nearest_promo", sales, promos))
  identical(out$promo_id, c("p2", "p1", NA_character_, "p4"))
})
check("never joins a future promotion", {
  out <- value_of(call_candidate("nearest_promo", sales, promos))
  is.na(out$promo_id[[3L]]) && is.na(out$discount[[3L]])
})
check("matches same customer and inclusive date", {
  out <- value_of(call_candidate("nearest_promo", sales, promos))
  identical(out$discount, c(0.2, 0.1, NA_real_, 0.3))
})
check("adds only the requested promotion columns", {
  out <- value_of(call_candidate("nearest_promo", sales, promos))
  identical(names(out), c(names(sales), "promo_id", "discount"))
})
