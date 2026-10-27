source("/verifier/cranlogs_helpers.R", local=FALSE)
fixture <- read_cranlogs_http_fixture("C05.json")
empty_fixture <- read_cranlogs_http_fixture("C05-empty.json")
full_history <- fixture$response
empty <- empty_fixture$response
history_from <- fixture$request$from
history_to <- fixture$request$to

check("requests the whole history with packages/from/to and no when", {
  fetch <- cranlogs_fetch(fixture$request$packages, history_from, history_to, full_history)
  call_candidate("cran_download_total", "ggplot2", fetch=fetch)$ok
})
check("sums observations across the full fixture period", {
  fetch <- cranlogs_fetch(fixture$request$packages, history_from, history_to, full_history)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", fetch=fetch))
  is.list(value) && isTRUE(all.equal(as.numeric(value$total_downloads), 81))
})
check("reports the full-period boundaries and package", {
  fetch <- cranlogs_fetch(fixture$request$packages, history_from, history_to, full_history)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", fetch=fetch))
  identical(value$package, "ggplot2") && identical(value$from, history_from) &&
    identical(value$to, history_to)
})
check("labels mirror downloads without claiming global installs", {
  fetch <- cranlogs_fetch(fixture$request$packages, history_from, history_to, full_history)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", fetch=fetch))
  assert_scoped_download_result(value, "ggplot2", history_from, history_to, 81)
})
check("returns zero for missing observations", {
  fetch <- cranlogs_fetch(empty_fixture$request$packages, history_from, history_to, empty)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", fetch=fetch))
  isTRUE(all.equal(as.numeric(value$total_downloads), 0))
})
check("ignores missing counts while summing the available observations", {
  fetch <- cranlogs_fetch(fixture$request$packages, history_from, history_to, full_history)
  value <- value_of(call_candidate("cran_download_total", "ggplot2", fetch=fetch))
  isTRUE(all.equal(as.numeric(value$total_downloads), 81))
})
check("rejects missing package input before requesting data", {
  no_fetch <- function(...) stop("missing package reached the HTTP boundary")
  result <- call_candidate("cran_download_total", "", fetch=no_fetch)
  !isTRUE(result$ok)
})
