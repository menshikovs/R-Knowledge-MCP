skip_if_not(.Platform$OS.type == "unix", "the launcher needs POSIX signals")
skip_without_python()

alive <- function(pid) !is.na(pid) && file.exists(file.path("/proc", pid))
screen <- function(h) paste(h$pilot$screen_text(), collapse = "\n")
finished <- c("COMPLETED", "FAILED", "INTERRUPTED")
set_mode <- function(mode, delay = "0.05") Sys.setenv(FAKE_MODE = mode, FAKE_DELAY = delay)

teardown_pilot <- function(h) {
  worker <- h$session$worker
  if (!is.null(worker) && worker$is_running()) worker$cancel(grace = 0.2)
  h$pilot$stop()
}

test_that("the first screen is READY with the real runner's defaults", {
  set_mode("ok")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  text <- screen(h)
  expect_match(text, "READY")
  expect_match(text, "Plan: 1 tasks x 2 modes x 1 repetitions = 2 trials")
  # The preview wraps by character, so compare it with the line breaks removed.
  flat <- paste(trimws(h$pilot$screen_text()), collapse = "")
  expect_match(flat, "--effort medium --tasks R01 --modes without-mcp with-mcp", fixed = TRUE)
  expect_match(text, "F5 run")
})

test_that("editing a field re-validates and F5 refuses an invalid configuration", {
  set_mode("ok")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$focus("#tasks")
  h$pilot$type(" Z99")
  expect_match(screen(h), "Unknown task id: Z99")
  h$pilot$press("f5")
  expect_equal(h$session$run$status, "READY")
  expect_null(h$session$worker)
})

test_that("a successful run streams output and ends COMPLETED", {
  set_mode("ok")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  expect_equal(h$session$run$status, "RUNNING")
  wait_status(h, finished)
  h$pilot$step()
  expect_equal(h$session$run$status, "COMPLETED")
  expect_equal(h$session$run$exit_status, 0L)
  text <- screen(h)
  expect_match(text, "COMPLETED")
  expect_match(text, "2/2 trials finished")
  expect_match(text, "R01-A-1: session created")
  expect_match(text, "Results: .*/results-")
  expect_match(text, "Task R01")
})

test_that("a failing runner leaves the interface usable and shows the failure", {
  set_mode("fail")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  wait_status(h, finished)
  h$pilot$step()
  expect_equal(h$session$run$status, "FAILED")
  expect_equal(h$session$run$exit_status, 1L)
  expect_match(screen(h), "runner exited with status 1")
  expect_match(screen(h), "1 with errors")
  h$pilot$press("escape")
  expect_match(screen(h), "Task ids")
  expect_false(h$pilot$exited)
})

test_that("stderr is shown and counted as a warning", {
  set_mode("stderr")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  wait_status(h, finished)
  h$pilot$step()
  expect_equal(h$session$run$stderr_lines, 1L)
  expect_match(screen(h), "fake: a warning on stderr")
  expect_match(screen(h), "1 stderr line")
})

test_that("Ctrl+X sends SIGINT and the runner's own cleanup decides the end", {
  set_mode("sigint")
  signals <- list()
  h <- new_pilot(signal_fn = function(pid, sig) { signals[[length(signals) + 1]] <<- sig; tools::pskill(pid, sig) })
  on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$trial), timeout = 10)
  pid <- h$session$worker$pid()
  h$pilot$press("ctrl+x")
  expect_equal(h$session$run$status, "STOPPING")
  expect_match(screen(h), "STOPPING")
  wait_status(h, finished)
  h$pilot$step()
  expect_equal(h$session$run$status, "INTERRUPTED")
  expect_equal(h$session$run$exit_status, 130L)
  expect_equal(unlist(signals), as.integer(tools::SIGINT))
  expect_false(alive(pid))
  expect_match(screen(h), "interrupted score")
})

test_that("a second Ctrl+X offers a confirmed force kill that leaves no process", {
  set_mode("ignore")
  h <- new_pilot(signal_fn = function(pid, sig) invisible(NULL))
  on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$trial), timeout = 10)
  pid <- h$session$worker$pid()
  h$pilot$press("ctrl+x")
  h$pilot$press("ctrl+x")
  expect_match(screen(h), "Force kill")
  h$pilot$press("tab", "enter")
  expect_false(alive(pid))
  # The user asked to stop, so the outcome is INTERRUPTED; the detail records the kill.
  expect_equal(h$session$run$status, "INTERRUPTED")
  expect_match(h$session$run$detail, "force-killed")
  expect_match(screen(h), "force-killed")
})

test_that("an unexpected runner death is reported as FAILED, not as progress", {
  set_mode("crash")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  wait_status(h, finished)
  h$pilot$step()
  expect_equal(h$session$run$status, "FAILED")
  expect_equal(h$session$run$done, 0L)
  expect_equal(h$session$run$exit_status, -9L)
  expect_match(h$session$run$detail, "killed by signal 9")
  expect_match(screen(h), "FAILED")
  h$pilot$press("escape")
  expect_match(screen(h), "Task ids")
})

test_that("several experiments can be run in one session", {
  h <- new_pilot(); on.exit(teardown_pilot(h))
  for (mode in c("ok", "fail", "ok")) {
    set_mode(mode)
    h$pilot$press("f5")
    wait_status(h, finished)
    h$pilot$step()
    expect_equal(h$session$run$status, if (mode == "ok") "COMPLETED" else "FAILED")
    # The failing fake reports its first trial as an error result, then stops.
    expect_equal(h$session$run$done, if (mode == "ok") 2L else 1L)
    h$pilot$press("escape")
    expect_match(screen(h), "Task ids")
  }
  # Output of the previous run must not leak into the next one.
  set_mode("ok")
  h$pilot$press("f5")
  wait_status(h, finished)
  h$pilot$step()
  expect_false(grepl("Cleanup incomplete", screen(h)))
})

test_that("F5 and Escape do nothing harmful while an experiment runs", {
  set_mode("sigint")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$trial), timeout = 10)
  first <- h$session$worker$pid()
  h$pilot$press("f5")
  h$pilot$press("escape")
  expect_equal(h$session$worker$pid(), first)
  expect_match(screen(h), "RUNNING")
  expect_false(grepl("Task ids", screen(h)))
})

test_that("quitting while running asks, stops gracefully and exits only afterwards", {
  set_mode("sigint")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$trial), timeout = 10)
  pid <- h$session$worker$pid()
  h$pilot$press("ctrl+c")
  expect_match(screen(h), "An experiment is running")
  expect_false(h$pilot$exited)
  h$pilot$press("tab", "enter")
  expect_equal(h$session$run$status, "STOPPING")
  expect_false(h$pilot$exited)
  expect_true(wait_exit(h))
  expect_false(alive(pid))
  expect_equal(h$session$run$status, "INTERRUPTED")
})

test_that("declining the quit dialog keeps the experiment running", {
  set_mode("sigint")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$trial), timeout = 10)
  h$pilot$press("ctrl+c")
  h$pilot$press("escape")
  expect_false(h$pilot$exited)
  expect_equal(h$session$run$status, "RUNNING")
})

test_that("Ctrl+C when idle quits immediately", {
  set_mode("ok")
  h <- new_pilot(); on.exit(h$pilot$stop())
  h$pilot$press("ctrl+c")
  expect_true(h$pilot$exited)
})

test_that("Tab and Shift+Tab move focus between the configuration controls", {
  set_mode("ok")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  h$pilot$press("tab")
  first <- h$app$focused
  expect_false(is.null(first))
  h$pilot$press("tab")
  second <- h$app$focused
  expect_false(identical(first, second))
  h$pilot$press("shift+tab")
  expect_true(identical(h$app$focused, first))
})

test_that("a missing credential blocks the start when keys are required", {
  withr_env <- Sys.getenv(KEY_VARS, unset = NA)
  Sys.unsetenv(KEY_VARS)
  on.exit(for (n in KEY_VARS) if (!is.na(withr_env[[n]])) do.call(Sys.setenv, stats::setNames(list(withr_env[[n]]), n)), add = TRUE)
  runner <- fake_runner(); runner$require_keys <- TRUE
  set_mode("ok")
  h <- new_pilot(runner); on.exit(teardown_pilot(h), add = TRUE)
  expect_match(screen(h), "Not exported in this shell: OPENAI_API_KEY")
  h$pilot$press("f5")
  expect_equal(h$session$run$status, "READY")
  expect_false(grepl("sk-", screen(h)))
})

test_that("a runner that cannot be started is reported as FAILED with a hint", {
  runner <- fake_runner(); runner$command <- "/nonexistent/python"
  h <- new_pilot(runner); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  wait_status(h, finished)
  h$pilot$step()
  expect_equal(h$session$run$status, "FAILED")
  expect_match(screen(h), "command not found")
  h$pilot$press("escape")
  expect_match(screen(h), "Task ids")
})

test_that("Ctrl+C inside a text field still quits (no selection to copy)", {
  set_mode("ok")
  h <- new_pilot(); on.exit(h$pilot$stop())
  h$pilot$focus("#tasks")
  h$pilot$press("ctrl+c")
  expect_true(h$pilot$exited)
})
