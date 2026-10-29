# Private Stage 3B evaluator. Mounted read-only into a networkless scorer container only after
# the agent session and executor have terminated.
#
# Candidate code never runs in this process: it is sourced into a separate callr::r_session
# (hard-v1 harness, reused unchanged), and every comparison happens here on returned plain
# values, so a solution cannot redefine testthat expectations or base functions used by checks.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2L, grepl("^X[AGPVRM][0-9]{2}$", args[1]))
task <- args[1]
candidate_dir <- normalizePath(args[2], mustWork = TRUE)
script <- sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[1])
verifier_dir <- dirname(normalizePath(script))
hard_dir <- Sys.getenv("BENCH_HARD_VERIFIER", unset = "/hardv")
config_dir <- Sys.getenv("BENCH_CONFIG", unset = "/config")

emit <- function(status, passed = NULL, total = NULL, failed = character(), details = character(),
                 reason = NULL, environment = NULL) {
  cat("BENCH_RESULT=", jsonlite::toJSON(
    list(status = status, passed = passed, total = total, reason = reason,
         failed_checks = I(failed), details = I(details), environment = environment),
    auto_unbox = TRUE, null = "null", digits = NA
  ), "\n", sep = "")
}

# Versions come from the lockfile where the package is locked; otherwise from the pins that the
# host passes from manifest.json (BENCH_PINS="pkg=version,..."), never from a mutable index.
task_packages <- Filter(nzchar, strsplit(Sys.getenv("BENCH_TASK_PACKAGES"), ",", fixed = TRUE)[[1]])
pin_pairs <- Filter(nzchar, strsplit(Sys.getenv("BENCH_PINS"), ",", fixed = TRUE)[[1]])
pins <- setNames(sub("^[^=]*=", "", pin_pairs), sub("=.*$", "", pin_pairs))
environment <- tryCatch({
  lock <- jsonlite::read_json(file.path(config_dir, "renv.lock"))
  stopifnot(as.character(getRversion()) == lock$R$Version)
  required <- unique(c("callr", "processx", "testthat", "jsonlite", task_packages))
  versions <- list()
  for (package in required) {
    wanted <- lock$Packages[[package]]$Version
    if (is.null(wanted)) wanted <- pins[[package]]
    actual <- as.character(packageVersion(package))
    if (is.null(wanted) || package_version(actual) != package_version(wanted)) {
      stop(paste("package", package, actual, "differs from pinned", wanted))
    }
    versions[[package]] <- actual
  }
  list(r = as.character(getRversion()), packages = versions)
}, error = function(e) {
  if (identical(Sys.getenv("BENCH_SELFTEST"), "1")) message(conditionMessage(e))
  NULL
})
if (is.null(environment)) {
  emit("scoring_error", reason = "environment_preflight_failed")
  quit(status = 0)
}

source(file.path(hard_dir, "harness.R"), local = globalenv())
source(file.path(verifier_dir, "lib.R"), local = globalenv())
# Register checks first so a candidate that fails to load still reports the total. A failing
# oracle self-check is a verifier fault, never a candidate failure.
verifier_loaded <- tryCatch({
  source(file.path(verifier_dir, paste0(task, ".R")), local = globalenv())
  TRUE
}, error = function(e) {
  if (identical(Sys.getenv("BENCH_SELFTEST"), "1")) message(conditionMessage(e))
  FALSE
})
if (!verifier_loaded) {
  emit("scoring_error", reason = "verifier_load_failed", environment = environment)
  quit(status = 0)
}
start_candidate(file.path(candidate_dir, "solution.R"))
if (!candidate_loaded()) {
  emit("candidate_error", passed = 0L, total = check_count(), reason = "source_error",
       details = substr(candidate_load_error(), 1L, 2000L), environment = environment)
  quit(status = 0)
}
outcome <- run_checks()
stop_candidate()
emit("scored", passed = outcome$passed, total = outcome$total, failed = outcome$failed,
     details = outcome$details, environment = environment)
