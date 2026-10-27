cran_download_total <- function(package, from, to, fetch=cranlogs::cran_downloads) {
  daily <- fetch(packages=package, from=to, to=from)
  list(package=package, total_downloads=sum(daily$count, na.rm=TRUE), from=to, to=from,
       source="RStudio CRAN mirror", scope="mirror downloads only; not global installations")
}
