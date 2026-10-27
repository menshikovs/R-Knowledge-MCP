nearest_promo <- function(sales, promos) {
  # BUG: matches the closest promotion after a sale, including future offers.
  dplyr::left_join(
    sales,
    promos,
    by = dplyr::join_by(customer, dplyr::closest(sale_date <= promo_date))
  )
}
