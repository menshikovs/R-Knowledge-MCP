cran_download_total <- function(package, fetch=cranlogs::cran_downloads) {
  if (!is.character(package) || length(package) != 1L || is.na(package) || !nzchar(package)) {
    stop("package must be one non-empty name")
  }
  from <- "2012-10-01"
  to <- "last-day"
  daily <- fetch(packages=package, from=from, to=to)
  if (!is.data.frame(daily) || !"count" %in% names(daily) || !is.numeric(daily$count)) {
    stop("cranlogs response must contain a numeric count column")
  }
  list(
    package=package,
    total_downloads=unname(sum(daily$count, na.rm=TRUE)),
    from=from,
    to=to,
    source="RStudio CRAN mirror",
    scope="RStudio mirror downloads only; not global CRAN downloads or installations"
  )
}
