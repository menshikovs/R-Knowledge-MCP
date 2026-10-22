# Private evaluator. Mount only after the candidate session has terminated.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==2L, grepl("^R(0[1-9]|1[0-2])$",args[1]))
task <- args[1]; candidate_dir <- normalizePath(args[2],mustWork=TRUE)
script <- sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[1])
oracle_dir <- dirname(normalizePath(script))
config_dir <- Sys.getenv("BENCH_CONFIG",unset="/config")
lib <- Sys.getenv("BENCH_R_LIBRARY")
if (nzchar(lib)) .libPaths(c(lib,.libPaths()))
emit <- function(status,passed=NULL,reason=NULL,details=NULL) {
  cat("BENCH_RESULT=", jsonlite::toJSON(list(status=status,passed=passed,total=4L,reason=reason,details=details),
                                      auto_unbox=TRUE,null="null"),"\n",sep="")
}
preflight <- tryCatch({
  lock <- jsonlite::read_json(file.path(config_dir,"renv.lock"))
  stopifnot(as.character(getRversion())==lock$R$Version)
  for (record in lock$Packages) {
    stopifnot(requireNamespace(record$Package,quietly=TRUE))
    actual <- as.character(packageVersion(record$Package))
    if (package_version(actual) != package_version(record$Version)) {
      stop(paste(record$Package, actual, "!=", record$Version))
    }
  }
  if (task %in% c("R10","R12")) {
    stopifnot(nzchar(Sys.which("quarto")))
    stopifnot(trimws(system2(Sys.which("quarto"),"--version",stdout=TRUE))=="1.8.27")
  }
  TRUE
},error=function(e) {
  if (identical(Sys.getenv("BENCH_SELFTEST"), "1")) message(conditionMessage(e))
  FALSE
})
if (!preflight) {
  emit("scoring_error",reason="environment_preflight_failed"); quit(status=0)
}
subject <- new.env(parent=globalenv())
if (task!="R10") {
  loaded <- tryCatch({
    sys.source(file.path(candidate_dir,"solution.R"),envir=subject)
    TRUE
  },error=function(e) FALSE)
  if (!loaded) { emit("candidate_error",0L,"source_error"); quit(status=0) }
}
source(file.path(oracle_dir,"helpers.R"),local=globalenv())
result <- testthat::test_file(file.path(oracle_dir,paste0(task,".R")),
                              reporter=testthat::SilentReporter$new(),env=globalenv())
table <- as.data.frame(result)
if (nrow(table)!=4L) {
  emit("scoring_error",reason="unexpected_oracle_group_count"); quit(status=0)
}
passed <- sum(table$failed==0L & !table$error & !table$skipped & table$nb>0L)
if (passed < 4L && identical(Sys.getenv("BENCH_SELFTEST"), "1")) print(result)
details <- unlist(lapply(result,function(test) {
  vapply(Filter(function(x) inherits(x,c("expectation_failure","expectation_error")),test$results),
         function(x) substr(x$message,1L,2000L),character(1))
}),use.names=FALSE)
emit("scored",as.integer(passed),details=details)
