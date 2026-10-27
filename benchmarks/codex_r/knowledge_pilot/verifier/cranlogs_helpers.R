read_cranlogs_http_fixture <- function(name) {
  path <- file.path("/verifier/fixtures", name)
  fixture <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  payload <- fixture$response
  if (!length(payload)) {
    response <- data.frame(package=character(), date=as.Date(character()), count=numeric())
    return(list(request=fixture$request, response=response))
  }
  response <- data.frame(
    package=vapply(payload, `[[`, character(1L), "package"),
    date=as.Date(vapply(payload, `[[`, character(1L), "date")),
    count=vapply(
      payload,
      function(row) if (is.null(row$count)) NA_real_ else as.numeric(row$count),
      numeric(1L)
    ),
    stringsAsFactors=FALSE
  )
  list(request=fixture$request, response=response)
}

cranlogs_fetch <- function(package, expected_from, expected_to, fixture) {
  environment <- new.env(parent=baseenv())
  environment$package <- package
  environment$expected_from <- expected_from
  environment$expected_to <- expected_to
  environment$fixture <- fixture
  environment$calls <- 0L
  eval(quote(function(packages=NULL, when=NULL, from="last-day", to="last-day", ...) {
    calls <<- calls + 1L
    if (calls > 1L || !identical(packages, package) || !is.null(when) ||
        !identical(from, expected_from) || !identical(to, expected_to) ||
        length(list(...)) != 0L) {
      stop("unexpected cranlogs request arguments")
    }
    fixture
  }), envir=environment)
}

assert_scoped_download_result <- function(value, package, from, to, total) {
  fields <- c("package", "total_downloads", "from", "to", "source", "scope")
  if (!is.list(value) || !all(fields %in% names(value))) return(FALSE)
  if (!identical(value$package, package) || !identical(value$from, from) ||
      !identical(value$to, to) || length(value$total_downloads) != 1L ||
      !is.numeric(value$total_downloads) || is.na(value$total_downloads) ||
      !isTRUE(all.equal(as.numeric(value$total_downloads), as.numeric(total)))) return(FALSE)
  source <- value$source
  scope <- value$scope
  if (!is.character(source) || length(source) != 1L ||
      !grepl("RStudio.*CRAN.*mirror", source, ignore.case=TRUE)) return(FALSE)
  if (!is.character(scope) || length(scope) != 1L) return(FALSE)
  mentions_mirror <- grepl("mirror", scope, ignore.case=TRUE)
  rejects_global <- grepl("not global|not all", scope, ignore.case=TRUE)
  rejects_installation <- grepl("not.*install", scope, ignore.case=TRUE)
  mentions_mirror && rejects_global && rejects_installation
}
