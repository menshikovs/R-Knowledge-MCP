cran_download_total <- function(package, fetch=cranlogs::cran_downloads) {
  from <- "2013-01-01"
  to <- "last-day"
  daily <- fetch(packages=package, from=from, to=to)
  list(package=package, total_downloads=sum(daily$count, na.rm=TRUE), from=from,
       to=to, source="RStudio CRAN mirror",
       scope="mirror downloads only; not global installations")
}
