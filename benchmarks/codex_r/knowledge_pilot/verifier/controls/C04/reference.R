cran_download_total <- function(package, from, to, fetch=cranlogs::cran_downloads) {
  valid_date <- function(value) {
    is.character(value) && length(value) == 1L && !is.na(value) &&
      grepl("^\\d{4}-\\d{2}-\\d{2}$", value) &&
      !is.na(suppressWarnings(as.Date(value))) && format(as.Date(value), "%Y-%m-%d") == value
  }
  if (!is.character(package) || length(package) != 1L || is.na(package) || !nzchar(package)) {
    stop("package must be one non-empty name")
  }
  if (!valid_date(from) || !valid_date(to) || as.Date(from) > as.Date(to)) {
    stop("from and to must be ordered ISO dates")
  }
  daily <- fetch(packages=package, from=from, to=to)
  if (!is.data.frame(daily) || !"count" %in% names(daily) || !is.numeric(daily$count)) {
    stop("cranlogs response must contain a numeric count column")
  }
  total <- sum(daily$count, na.rm=TRUE)
  list(
    package=package,
    total_downloads=unname(total),
    from=from,
    to=to,
    source="RStudio CRAN mirror",
    scope="RStudio mirror downloads only; not global CRAN downloads or installations"
  )
}
