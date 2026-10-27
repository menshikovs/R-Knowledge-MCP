cran_download_total <- function(package, from, to, fetch=cranlogs::cran_downloads) {
  daily <- fetch(packages=package, when="all")
  list(package=package, total_downloads=sum(daily$count), from=from, to=to,
       source="RStudio CRAN mirror", scope="mirror downloads only; not global installations")
}
