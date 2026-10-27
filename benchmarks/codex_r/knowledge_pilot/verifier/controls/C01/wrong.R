nearest_promo <- function(sales, promos) {
  dplyr::left_join(sales, promos,
    by=dplyr::join_by(customer, closest(sale_date <= promo_date)))
}
