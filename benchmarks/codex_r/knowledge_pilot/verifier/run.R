args <- commandArgs(trailingOnly = TRUE)
task_id <- args[[1L]]
candidate_root <- args[[2L]]
source("/harness.R", local = FALSE)
register_pilot_check <- function(name, code) {
  stopifnot(is.character(name), length(name) == 1L, !name %in% names(.checks))
  expression <- substitute(code)
  .checks[[name]] <<- bquote(if (!isTRUE(.(expression))) stop("check returned false"))
  invisible(NULL)
}
check <- register_pilot_check
manifest <- jsonlite::fromJSON("/verifier/manifest.json", simplifyVector = FALSE)
task <- manifest$tasks[[task_id]]
if (is.null(task)) stop("task is not registered")
package_pins <- c(unlist(task$packages), unlist(task$required_packages))
package_names <- names(package_pins)
versions <- if (length(package_names)) vapply(package_names, function(package) {
  if (!requireNamespace(package, quietly = TRUE)) return(NA_character_)
  as.character(utils::packageVersion(package))
}, character(1L)) else character()
locked_versions <- unname(package_pins)
if (!length(locked_versions)) locked_versions <- character()
if (getRversion() != "4.5.2" || anyNA(versions) ||
    !identical(unname(versions), locked_versions)) {
  cat("BENCH_RESULT=", jsonlite::toJSON(list(status="scoring_error", reason="environment_mismatch"), auto_unbox=TRUE), "\n", sep="")
  quit(status = 0L)
}
source(file.path("/verifier", paste0(task_id, ".R")), local = FALSE)
if (check_count() != task$checks) stop("registered check count differs")
loaded <- start_candidate(file.path(candidate_root, "solution.R"))
result <- if (!loaded) {
  list(passed=0L, total=task$checks, failed=rep("candidate_load", 1L), details=candidate_load_error())
} else {
  run_checks()
}
stop_candidate()
payload <- list(
  status="scored", passed=as.integer(result$passed), total=as.integer(result$total),
  failed_checks=result$failed, details=result$details,
  environment=list(r=as.character(getRversion()), packages=as.list(versions))
)
cat("BENCH_RESULT=", jsonlite::toJSON(payload, auto_unbox=TRUE, null="null"), "\n", sep="")
