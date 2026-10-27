nearest_promo <- function(sales, promos) {
  joined <- sales |>
    dplyr::mutate(.row=seq_len(dplyr::n())) |>
    dplyr::left_join(
      promos,
      by=dplyr::join_by(customer, closest(sale_date >= promo_date))
    ) |>
    dplyr::arrange(.row)
  dplyr::select(joined, dplyr::all_of(c(names(sales), "promo_id", "discount")))
}
