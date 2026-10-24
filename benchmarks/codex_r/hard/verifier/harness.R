# Shared hidden-verifier harness. Each `check()` is one named behavioral check;
# a task is fully correct only when every check passes.

.checks <- list()
.candidate <- new.env(parent = emptyenv())

check <- function(name, code) {
  stopifnot(is.character(name), length(name) == 1L, !name %in% names(.checks))
  .checks[[name]] <<- substitute(code)
  invisible(NULL)
}

check_count <- function() length(.checks)

start_candidate <- function(path, timeout = 60) {
  .candidate$path <- path
  .candidate$load_error <- NULL
  .candidate$session <- callr::r_session$new(
    options = callr::r_session_options(env = c(TZ = "UTC", LC_ALL = "C.UTF-8")),
    wait = TRUE
  )
  .candidate$session$call(function(path) {
    sys.source(path, envir = globalenv(), keep.source = FALSE)
    TRUE
  }, list(path))
  state <- .candidate$session$poll_process(as.integer(timeout * 1000))
  if (state != "ready") {
    .candidate$load_error <- "timed out while sourcing solution.R"
    .candidate$session$kill()
    return(invisible(FALSE))
  }
  result <- .candidate$session$read()
  if (!is.null(result$error)) {
    parent <- result$error$parent
    .candidate$load_error <- conditionMessage(if (is.null(parent)) result$error else parent)
  }
  invisible(is.null(.candidate$load_error))
}

candidate_loaded <- function() is.null(.candidate$load_error)
candidate_load_error <- function() .candidate$load_error

stop_candidate <- function() {
  if (!is.null(.candidate$session) && .candidate$session$is_alive()) .candidate$session$close()
}

# Call a candidate function in the isolated process. Returns a list with `ok`,
# `value` or `message`/`classes`, captured `warnings`, the argument list as seen
# after the call (`args_after`), and the parent's wall-clock `elapsed` seconds.
call_candidate <- function(fun, ..., .timeout = 30) {
  args <- list(...)
  session <- .candidate$session
  if (is.null(session) || !session$is_alive()) {
    start_candidate(.candidate$path)
    session <- .candidate$session
  }
  started <- proc.time()[["elapsed"]]
  session$call(function(fun, args) {
    warnings <- character()
    result <- withCallingHandlers(
      tryCatch(
        list(ok = TRUE, value = do.call(fun, args, envir = globalenv())),
        error = function(e) list(ok = FALSE, message = conditionMessage(e), classes = class(e))
      ),
      warning = function(w) {
        warnings <<- c(warnings, conditionMessage(w))
        invokeRestart("muffleWarning")
      }
    )
    result$warnings <- warnings
    result$args_after <- args
    result
  }, list(fun, args))
  state <- session$poll_process(as.integer(.timeout * 1000))
  elapsed <- proc.time()[["elapsed"]] - started
  if (state != "ready") {
    session$kill()
    # Later checks get a fresh process, so one hang does not zero the whole task.
    start_candidate(.candidate$path)
    return(list(ok = FALSE, message = sprintf("timed out after %ss", .timeout),
                classes = "candidate_timeout", warnings = character(), elapsed = elapsed))
  }
  response <- session$read()
  if (!is.null(response$error)) {
    return(list(ok = FALSE, message = conditionMessage(response$error),
                classes = "candidate_process_error", warnings = character(), elapsed = elapsed))
  }
  result <- response$result
  result$elapsed <- elapsed
  result
}

# Value of a successful call, or a check failure naming the candidate error.
value_of <- function(result) {
  if (!isTRUE(result$ok)) {
    stop(paste0("candidate call failed: ", substr(paste(result$message, collapse = " "), 1L, 300L)))
  }
  result$value
}

expect_candidate_error <- function(result, class) {
  if (isTRUE(result$ok)) stop("expected an error of class ", class, " but the call succeeded")
  if (!class %in% result$classes) {
    stop("expected error class ", class, "; got ", paste(result$classes, collapse = "/"),
         ": ", substr(paste(result$message, collapse = " "), 1L, 200L))
  }
  invisible(TRUE)
}

expect_no_candidate_warnings <- function(result) {
  if (length(result$warnings)) {
    stop("unexpected warning: ", substr(result$warnings[[1]], 1L, 200L))
  }
  invisible(TRUE)
}

run_checks <- function() {
  testthat::local_edition(3)
  failed <- character()
  details <- character()
  for (name in names(.checks)) {
    passed <- tryCatch({
      eval(.checks[[name]], new.env(parent = globalenv()))
      TRUE
    }, error = function(e) {
      details <<- c(details, paste0(name, ": ", substr(conditionMessage(e), 1L, 500L)))
      FALSE
    })
    if (!passed) failed <- c(failed, name)
  }
  list(passed = length(.checks) - length(failed), total = length(.checks),
       failed = failed, details = details)
}
