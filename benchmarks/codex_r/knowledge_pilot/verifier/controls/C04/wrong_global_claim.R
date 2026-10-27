cran_download_total <- function(package, from, to, fetch=cranlogs::cran_downloads) {
  daily <- fetch(packages=package, from=from, to=to)
  list(package=package, total_downloads=sum(daily$count, na.rm=TRUE), from=from, to=to,
       source="RStudio CRAN mirror", scope="global CRAN downloads and package installations")
}
