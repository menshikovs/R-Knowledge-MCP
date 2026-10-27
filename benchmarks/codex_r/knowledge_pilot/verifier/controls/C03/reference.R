parse_euro_amount <- function(x) {
  suppressWarnings(
    readr::parse_number(
      x,
      locale=readr::locale(decimal_mark=",", grouping_mark="."),
      na=c("", "--"),
      trim_ws=TRUE
    )
  )
}
