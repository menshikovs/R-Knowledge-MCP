parse_euro_amount <- function(x) {
  # BUG: the default locale treats the comma and period incorrectly.
  readr::parse_number(x)
}
