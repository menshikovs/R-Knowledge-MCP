cran_download_total <- function(package, fetch=cranlogs::cran_downloads) {
  daily <- fetch(packages=package, when="all")
  list(package=package, total_downloads=sum(daily$count, na.rm=TRUE), from="2012-10-01",
       to="last-day", source="RStudio CRAN mirror",
       scope="mirror downloads only; not global installations")
}
