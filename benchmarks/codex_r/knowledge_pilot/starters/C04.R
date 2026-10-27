cran_download_total <- function(package, from, to, fetch = cranlogs::cran_downloads) {
  # Bug: cranlogs 2.1.1 does not support when = "all". For a date interval,
  # it must receive from and to. Also return a scoped sum, not raw daily rows.
  daily <- fetch(packages = package, when = "all")
  sum(daily$count)
}
