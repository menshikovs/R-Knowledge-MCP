source("/verifier/cranlogs_helpers.R", local=FALSE)
fixture <- read_cranlogs_http_fixture("C04.json")
empty_fixture <- read_cranlogs_http_fixture("C04-empty.json")
daily <- fixture$response
empty <- empty_fixture$response
from_date <- fixture$request$from
to_date <- fixture$request$to

check("calls cranlogs with package and from/to, without when", {
  fetch <- cranlogs_fetch(fixture$request$packages, from_date, to_date, daily)
  call_candidate("cran_download_total", "ggplot2", from_date, to_date, fetch=fetch)$ok
})
check("sums all daily counts including inclusive boundary dates", {
  fetch <- cranlogs_fetch(fixture$request$packages, from_date, to_date, daily)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", from_date, to_date, fetch=fetch))
  is.list(value) && isTRUE(all.equal(as.numeric(value$total_downloads), 40))
})
check("retains the requested package and date interval", {
  fetch <- cranlogs_fetch(fixture$request$packages, from_date, to_date, daily)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", from_date, to_date, fetch=fetch))
  identical(value$package, "ggplot2") && identical(value$from, from_date) &&
    identical(value$to, to_date)
})
check("labels the statistic as mirror downloads, not global installations", {
  fetch <- cranlogs_fetch(fixture$request$packages, from_date, to_date, daily)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", from_date, to_date, fetch=fetch))
  assert_scoped_download_result(value, "ggplot2", from_date, to_date, 40)
})
check("returns zero for an empty response", {
  fetch <- cranlogs_fetch(empty_fixture$request$packages, from_date, to_date, empty)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", from_date, to_date, fetch=fetch))
  isTRUE(all.equal(as.numeric(value$total_downloads), 0))
})
check("returns zero when every count is missing", {
  no_counts <- data.frame(package="ggplot2", date=as.Date(from_date), count=NA_real_)
  fetch <- cranlogs_fetch(fixture$request$packages, from_date, to_date, no_counts)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", from_date, to_date, fetch=fetch))
  isTRUE(all.equal(as.numeric(value$total_downloads), 0))
})
check("rejects invalid ISO dates before requesting data", {
  no_fetch <- function(...) stop("invalid date reached the HTTP boundary")
  result <- call_candidate("cran_download_total", "ggplot2", "2024-02-30", to_date, fetch=no_fetch)
  !isTRUE(result$ok)
})
check("rejects a reversed date range before requesting data", {
  no_fetch <- function(...) stop("reversed range reached the HTTP boundary")
  result <- call_candidate("cran_download_total", "ggplot2", to_date, from_date, fetch=no_fetch)
  !isTRUE(result$ok)
})
check("rejects an empty package name before requesting data", {
  no_fetch <- function(...) stop("empty package reached the HTTP boundary")
  result <- call_candidate("cran_download_total", "", from_date, to_date, fetch=no_fetch)
  !isTRUE(result$ok)
})
