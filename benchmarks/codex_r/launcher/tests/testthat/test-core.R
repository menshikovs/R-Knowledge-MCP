cfg <- function(...) modifyList(default_config(), list(...))

test_that("the catalog is parsed and incomplete catalogs are rejected", {
  lines <- c("r=R01 R02", "hard=H01", "knowledge=B01", "tool_value=B01", "full=H01 B01",
    "instructions=diagnostic standard", "smoke=mcp-smoke", "b1_tasks=D03 D01 C01",
    "b1_repetitions=2", "b1_order=D03:1:control D03:1:treatment",
    "b1_scorers=D03:knowledge-pilot-v2 C01:legacy", "noise without equals")
  catalog <- parse_catalog(lines)
  expect_equal(catalog$full, c("H01", "B01"))
  expect_equal(catalog$b1_order, c("D03:1:control", "D03:1:treatment"))
  expect_error(parse_catalog(lines[1:3]), "incomplete")
  expect_error(parse_catalog(lines[1:7]), "b1_tasks")
})

test_that("valid configurations produce no problems", {
  expect_length(validate_config(cfg(), FAKE_CATALOG), 0)
  expect_length(validate_config(cfg(tasks = c("R01", "H01", "all")), FAKE_CATALOG), 0)
  expect_length(validate_config(cfg(preset = "tool-value", scorer = "knowledge-pilot-v2"), FAKE_CATALOG), 0)
  expect_length(validate_config(cfg(tasks = "D01", scorer = "knowledge-pilot-v2.1"), FAKE_CATALOG), 0)
})

test_that("V2.1 is limited to the D01 and D03 tasks supported by the runner", {
  expect_match(
    validate_config(cfg(tasks = "R01", scorer = "knowledge-pilot-v2.1"), FAKE_CATALOG),
    "supports D01 and D03 only"
  )
})

test_that("invalid configurations are rejected with specific messages", {
  bad <- function(...) validate_config(cfg(...), FAKE_CATALOG)
  expect_match(bad(tasks = character()), "at least one task")
  expect_match(bad(tasks = "Z99"), "Unknown task id: Z99")
  expect_match(bad(modes = character()), "at least one mode")
  expect_match(bad(effort = "low"), "medium or high")
  expect_match(bad(repetitions = 0L), "Repetitions")
  expect_match(bad(repetitions = 101L), "Repetitions")
  expect_match(bad(repetitions = NA_integer_), "Repetitions")
  expect_match(bad(timeout = 901L), "Timeout")
  expect_match(bad(instructions = "other"), "instruction")
  expect_match(bad(scorer = "knowledge-pilot-v2", tasks = "R01"), "needs at least one")
  expect_match(bad(scorer = "knowledge-pilot-v2.1", tasks = "R01"), "supports D01 and D03 only")
  expect_match(bad(tasks = c("mcp-smoke", "R01"), modes = "with-mcp"), "mcp-smoke runs alone")
  expect_match(bad(tasks = "mcp-smoke"), "only with the with-mcp")
  expect_length(bad(tasks = "mcp-smoke", modes = "with-mcp"), 0)
})

test_that("numbers are parsed strictly", {
  expect_equal(as_whole_number(" 12 "), 12L)
  expect_true(is.na(as_whole_number("1.5")))
  expect_true(is.na(as_whole_number("abc")))
  expect_true(is.na(as_whole_number("")))
})

test_that("commands are built as an argument vector, never a shell string", {
  runner <- list(command = "/py", prefix = c("-m", "benchmarks.codex_r.run_simple"), wd = "/repo")
  spec <- build_command(cfg(tasks = c("R01", "H01"), repetitions = 2L, effort = "high"), runner)
  expect_equal(spec$command, "/py")
  expect_equal(spec$wd, "/repo")
  expect_equal(
    spec$args,
    c("-m", "benchmarks.codex_r.run_simple", "--effort", "high", "--tasks", "R01", "H01",
      "--modes", "without-mcp", "with-mcp", "--repetitions", "2", "--timeout", "900",
      "--instructions", "standard", "--function-discovery", "enabled",
      "--knowledge-pilot-scorer", "legacy")
  )
  pilot <- build_args(cfg(preset = "full", modes = "with-mcp"))
  expect_equal(pilot[3:4], c("--pilot", "full"))
  expect_false("--tasks" %in% pilot)
  # A hostile task id can never be accepted, so it cannot reach the command line.
  expect_match(validate_config(cfg(tasks = "R01; rm -rf /"), FAKE_CATALOG)[1], "Unknown task id")
})

test_that("standard TUI enables function discovery while B1 keeps its frozen policy", {
  standard <- build_args(cfg(tasks = "D01", modes = "with-mcp"))
  discovery <- match("--function-discovery", standard)
  expect_false(is.na(discovery))
  expect_equal(standard[discovery + 1L], "enabled")

  b1 <- build_args(b1_config(FAKE_CATALOG))
  expect_false("--function-discovery" %in% b1)
})

test_that("trial counts mirror the runner's expansion rules", {
  expect_equal(planned_trials(cfg(), FAKE_CATALOG), 2L)
  expect_equal(planned_trials(cfg(tasks = "all", repetitions = 3L), FAKE_CATALOG), 12L * 2L * 3L)
  expect_equal(planned_trials(cfg(tasks = c("hard-pilot", "H01")), FAKE_CATALOG), 6L)
  expect_equal(planned_trials(cfg(preset = "full", modes = "with-mcp"), FAKE_CATALOG), 8L)
  expect_true(is.na(planned_trials(cfg(tasks = "nope"), FAKE_CATALOG)))
})

test_that("credential variables are reported by name only", {
  expect_equal(missing_keys(c(OPENAI_API_KEY = "x", OPENAI_EXECUTOR_API_KEY = "y")), character())
  expect_equal(missing_keys(c(OPENAI_API_KEY = "x", OPENAI_EXECUTOR_API_KEY = " ")), "OPENAI_EXECUTOR_API_KEY")
  expect_equal(missing_keys(c(OTHER = "x")), KEY_VARS)
})

test_that("only the runner's documented progress formats are recognised", {
  expect_equal(parse_runner_line("H01-A-1: session created [0.5s]")$kind, "event")
  expect_equal(parse_runner_line("H01-A-1: waiting: waiting for turn [45.0s]")$activity, "waiting for turn")
  r <- parse_runner_line("H01-A-1: scored score=4/4")
  expect_equal(c(r$kind, r$status, r$score, r$error), c("result", "scored", "4/4", "FALSE"))
  expect_true(parse_runner_line("H01-B-1: error score=None/None; error recorded")$error)
  expect_equal(parse_runner_line("Results: /a/b")$path, "/a/b")
  expect_true(parse_runner_line("Cleanup incomplete. Results: /a/b")$incomplete)
  expect_equal(parse_runner_line("random text")$kind, "other")
  expect_equal(parse_trial_id("E02-B-2-diagnostic")[c("task", "mode", "repetition")],
    list(task = "E02", mode = "with-mcp", repetition = 2L))
  expect_equal(parse_trial_id("mcp-smoke-B-1")$task, "mcp-smoke")
})

test_that("run state counts only printed results and never invents progress", {
  st <- new_run_state(4L)
  apply_runner_line(st, "H01-A-1: session created [0.5s]")
  expect_equal(c(st$task, st$mode, st$done), c("H01", "without-mcp", "0"))
  apply_runner_line(st, "H01-A-1: scored score=4/4")
  apply_runner_line(st, "H01-B-1: error score=None/None; error recorded")
  expect_equal(c(st$done, st$trial_errors), c(2L, 1L))
  expect_equal(progress_text(st), "2/4 trials finished (1 with errors)")
  expect_equal(progress_text(new_run_state()), "0/? trials finished")
  apply_runner_line(st, "H01-B-1: interrupted score=None/None; error recorded")
  expect_equal(c(st$done, st$trial_errors), c(2L, 1L))  # an interrupted trial never finished
})

test_that("final status follows the exit status and the stop request", {
  final <- function(code, stopped = FALSE) {
    st <- new_run_state(); st$stop_requested <- stopped; finish_run(st, code); st$status
  }
  expect_equal(final(0L), "COMPLETED")
  expect_equal(final(1L), "FAILED")
  expect_equal(final(130L), "INTERRUPTED")
  expect_equal(final(1L, stopped = TRUE), "INTERRUPTED")
  expect_equal(final(NA_integer_), "FAILED")
  expect_equal(final(0L, stopped = TRUE), "COMPLETED")
  st <- new_run_state(); finish_run(st, -9L)
  expect_equal(c(st$status, st$detail), c("FAILED", "runner was killed by signal 9"))
  st <- new_run_state(); finish_run(st, 127L)
  expect_match(st$detail, "command not found")
  expect_equal(format_elapsed(3725), "01:02:05")
})

test_that("the process wrapper keeps every argument positional (no shell interpretation)", {
  spec <- list(command = "/py", args = c("-m", "x; touch /tmp/pwned", "$(id)", "a b"), wd = "/w")
  wrapped <- wrap_command(spec, "/o.log", "/e.log")
  expect_equal(wrapped$command, "sh")
  expect_equal(wrapped$args[1:2], c("-c", EXEC_SNIPPET))
  expect_equal(
    tail(wrapped$args, 7),
    c("/o.log", "/e.log", "/py", "-m", "x; touch /tmp/pwned", "$(id)", "a b")
  )
  expect_false(grepl("pwned", EXEC_SNIPPET, fixed = TRUE))
  # Run it for real: the hostile-looking arguments arrive untouched, nothing is executed.
  out <- tempfile(); err <- tempfile()
  marker <- tempfile()
  w <- wrap_command(list(command = "printf", args = c("%s|", "x; touch " , marker, "$(id)"), wd = tempdir()), out, err)
  processx::run(w$command, w$args)
  expect_equal(readLines(out, warn = FALSE), paste0("x; touch |", marker, "|$(id)|"))
  expect_false(file.exists(marker))
})

test_that("the guard is a plain positional shell snippet", {
  g <- guard_command(123, 456)
  expect_equal(g$args[3:5], c("sh", "123", "456"))
  expect_match(GUARD_SNIPPET, "kill -INT \"$2\"", fixed = TRUE)
})

test_that("the output reader returns only new complete lines and bounds control characters", {
  path <- tempfile(); tl <- new_tail(path)
  expect_equal(read_tail(tl), character())
  cat("one\ntwo", file = path)
  expect_equal(read_tail(tl), "one")
  cat("\nthree\n\033[31mred\033[0m\n", file = path, append = TRUE)
  expect_equal(read_tail(tl), c("two", "three", "[31mred[0m"))
  cat("tail without newline", file = path, append = TRUE)
  expect_equal(read_tail(tl), character())
  expect_equal(read_tail(tl, final = TRUE), "tail without newline")
  expect_equal(read_tail(tl, final = TRUE), character())
  writeBin(as.raw(c(0x66, 0xff, 0x0a)), path <- tempfile()); tl2 <- new_tail(path)
  expect_equal(read_tail(tl2), "f?")
})
