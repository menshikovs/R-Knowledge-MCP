skip_if_not(.Platform$OS.type == "unix", "the launcher needs POSIX signals")
skip_without_python()

finished <- c("COMPLETED", "FAILED", "INTERRUPTED")
screen <- function(h) paste(h$pilot$screen_text(), collapse = "\n")
set_mode <- function(mode) Sys.setenv(FAKE_MODE = mode, FAKE_DELAY = "0.05")
b1cfg <- function(...) modifyList(b1_config(FAKE_CATALOG), list(...))
cfg <- function(...) modifyList(default_config(), list(...))

teardown_pilot <- function(h) {
  worker <- h$session$worker
  if (!is.null(worker) && worker$is_running()) worker$cancel(grace = 0.2)
  h$pilot$stop()
}

select_b1 <- function(h) {
  h$pilot$focus("#experiment")
  h$pilot$press("down")
  expect_equal(h$app$query_one("#experiment")$value, "b1-discovery")
}

# -- configuration and command line ------------------------------------------------

test_that("standard command lines are unchanged and never carry B1 flags", {
  args <- build_args(cfg())
  expect_equal(args, c("--effort", "medium", "--tasks", "R01", "--modes", "without-mcp", "with-mcp",
    "--repetitions", "1", "--timeout", "900", "--instructions", "standard",
    "--knowledge-pilot-scorer", "legacy"))
  expect_false(any(c("--experiment", "--resume", "--executor-image") %in% args))
})

test_that("B1 builds the runner's own flags: MCP in both conditions, no --modes", {
  args <- build_args(b1cfg())
  expect_equal(args, c(
    "--effort", "medium", "--experiment", "b1-discovery", "--tasks", "D03", "D01", "C01",
    "--repetitions", "2", "--timeout", "900", "--knowledge-pilot-scorer", "knowledge-pilot-v2",
    "--executor-image", "rkmcp-codex-runtime:codex-0.163.0-bioc",
    "--scorer-image", "codex-r-benchmark:pilot-bioc",
    "--mcp-image", "cran-knowledge-mcp:shiny-quarto"
  ))
  # The runner rejects these together with --experiment b1-discovery.
  expect_false(any(c("--modes", "--instructions", "--mcp-discovery", "--pilot") %in% args))
  expect_equal(b1cfg()$modes, "with-mcp")
  expect_length(validate_config(b1cfg(), FAKE_CATALOG), 0)
})

test_that("B1 plan is the runner's 12 balanced trials and is not reordered", {
  expect_equal(planned_trials(b1cfg(), FAKE_CATALOG), 12L)
  expect_equal(b1_order_text(FAKE_CATALOG),
    "D03-R1 C>T  D01-R1 T>C  C01-R1 C>T  D03-R2 T>C  D01-R2 C>T  C01-R2 T>C")
  expect_equal(unname(b1_scorer_map(FAKE_CATALOG)), c("knowledge-pilot-v2", "knowledge-pilot-v2", "legacy"))
  expect_equal(names(b1_scorer_map(FAKE_CATALOG)), c("D03", "D01", "C01"))
})

test_that("settings the runner would reject are blocked for B1", {
  bad <- function(...) validate_config(b1cfg(...), FAKE_CATALOG)
  expect_match(bad(tasks = c("D03", "D01")), "exactly these tasks: D03 D01 C01")
  expect_match(bad(tasks = c("D03", "D01", "C01", "R01")), "exactly these tasks")
  expect_match(bad(repetitions = 3L), "requires 2 repetitions")
  expect_match(bad(instructions = "diagnostic"), "standard instructions")
  expect_match(bad(scorer = "legacy"), "knowledge-pilot-v2")
  expect_match(bad(modes = c("without-mcp", "with-mcp")), "MCP in both")
  expect_match(bad(timeout = 901L), "Timeout")
  expect_match(validate_config(modifyList(b1cfg(), list(experiment = "other")), FAKE_CATALOG), "Unknown experiment")
  expect_true(is.na(planned_trials(b1cfg(repetitions = 3L), FAKE_CATALOG)))
})

test_that("resume goes through the runner's --resume with the saved effort only", {
  runner <- list(command = "/py", prefix = c("-m", "benchmarks.codex_r.run_simple"), wd = "/repo")
  spec <- build_resume_command("/r/20261026T063723Z-c849c1af", "high", runner)
  expect_equal(spec$args, c("-m", "benchmarks.codex_r.run_simple", "--effort", "high",
    "--resume", "/r/20261026T063723Z-c849c1af"))
  expect_false(any(c("--tasks", "--modes", "--experiment", "--repetitions") %in% spec$args))
})

# -- runs, resume decisions and results text ------------------------------------------

run_row <- function(...) modifyList(list(run_id = "20261026T100000Z-aaaaaaaa", experiment = "standard",
  created = "x", effort = "medium", total = "2", recorded = "1", status = "partial",
  cleanup = "complete", resume = "ok"), list(...))

test_that("runs are parsed from the helper's output; missing fields stay unknown", {
  runs <- parse_runs(c("id1\tb1-discovery\t2026\tmedium\t12\t1\tinterrupted\tincomplete\tok", "id2\tstandard"))
  expect_equal(runs[[1]]$status, "interrupted")
  expect_equal(runs[[2]]$cleanup, "unknown")
  expect_equal(runs[[2]]$resume, "unknown")
  expect_length(parse_runs(character()), 0)
})

test_that("resume is never declared safe automatically", {
  expect_true(resume_allowed(run_row()))
  expect_false(resume_allowed(run_row(status = "finished")))
  expect_false(resume_allowed(run_row(resume = "blocked: no experiment.json")))
  expect_false(resume_allowed(run_row(resume = "unknown")))
  interrupted <- resume_warnings(run_row(status = "interrupted", cleanup = "incomplete"))
  expect_match(paste(interrupted, collapse = " "), "interrupted")
  expect_match(paste(interrupted, collapse = " "), "never deletes")
  expect_match(paste(interrupted, collapse = " "), "orphan|may still exist")
  unknown <- resume_warnings(run_row(status = "unknown", cleanup = "unknown"))
  expect_match(paste(unknown, collapse = " "), "not fully recorded")
  expect_match(paste(resume_warnings(run_row(resume = "blocked: refusing to repeat")), collapse = " "), "refuses")
})

test_that("results never show a delta without scores and name B1 conditions", {
  b1 <- run_row(experiment = "b1-discovery")
  none <- list(list(trial = "b1-discovery-D03-R1-control", condition = "control", task = "D03",
    status = "interrupted", score = "none", cleanup = "incomplete"))
  text <- paste(summary_lines(b1, none), collapse = "\n")
  expect_match(text, "control")
  expect_match(text, "no delta shown")
  expect_false(grepl("without|with-mcp", text))
  scored <- list(
    list(trial = "t1", condition = "control", task = "D03", status = "scored", score = "3/4", cleanup = "complete"),
    list(trial = "t2", condition = "treatment", task = "D03", status = "scored", score = "4/4", cleanup = "complete")
  )
  expect_match(paste(summary_lines(b1, scored), collapse = "\n"), "analytics dashboard")
  expect_equal(summary_lines(b1, list()), "No trial results are recorded in this run.")
  expect_match(paste(summary_lines(run_row(), none), collapse = ""), "No recorded scores")
})

# -- live progress ---------------------------------------------------------------------

test_that("stages come from the runner's labels and unknown labels are shown as printed", {
  expect_equal(stage_for("Docker executor started"), "Waiting for executor")
  expect_equal(stage_for("waiting for executor"), "Waiting for executor")
  expect_equal(stage_for("executor connected"), "Executor connected")
  expect_equal(stage_for("cleanup: delete_session"), "Cleanup")
  expect_equal(stage_for("something new"), "something new")
})

test_that("a missing 'executor connected' is never treated as connected, and a timeout needs the runner's word", {
  st <- new_run_state(12L)
  for (line in c("b1-discovery-D03-R1-control: session created [7.9s]",
    "b1-discovery-D03-R1-control: Docker executor started [8.2s]",
    "b1-discovery-D03-R1-control: waiting: waiting for executor [300.0s]")) apply_runner_line(st, line)
  expect_false(st$executor_connected)
  expect_equal(st$stage, "Waiting for executor")
  expect_true(is.na(st$timeout_code))
  expect_true(is.na(st$watchdog_seconds))
  expect_equal(c(st$condition, st$task, st$repetition), c("control", "D03", "1"))
  apply_runner_line(st, "b1-discovery-D03-R1-control: executor not connected [45.0s]")
  expect_equal(st$watchdog_seconds, 45)
  expect_true(is.na(st$timeout_code))
  apply_runner_line(st, "b1-discovery-D03-R1-control: EXECUTOR_CONNECTION_TIMEOUT [60.0s]")
  expect_equal(st$timeout_code, "EXECUTOR_CONNECTION_TIMEOUT")
  # Nothing observed about one trial carries over to the next.
  apply_runner_line(st, "b1-discovery-D03-R1-treatment: session created [0.5s]")
  expect_false(st$executor_connected)
  expect_true(is.na(st$timeout_code))
  apply_runner_line(st, "b1-discovery-D03-R1-treatment: executor connected [2.0s]")
  expect_true(st$executor_connected)
})

test_that("an incomplete cleanup is carried into the final state, not hidden by the status", {
  st <- new_run_state(12L)
  apply_runner_line(st, "Cleanup incomplete. Results: /r/x")
  expect_true(st$cleanup_incomplete)
  finish_run(st, 1L)
  expect_equal(st$status, "FAILED")
  expect_match(st$detail, "CLEANUP INCOMPLETE")
  st <- new_run_state(12L); st$stop_requested <- TRUE
  apply_runner_line(st, "Cleanup incomplete. Results: /r/x")
  finish_run(st, 130L)
  expect_equal(st$status, "INTERRUPTED")
  expect_match(st$detail, "nothing was deleted")
})

test_that("launcher sources never spawn through a shell", {
  sources <- c(file.path(launcher_dir, "launcher_core.R"), file.path(launcher_dir, "launcher_app.R"))
  code <- unlist(lapply(sources, readLines, warn = FALSE))
  code <- code[!grepl("^\\s*#", code)]
  expect_false(any(grepl("system2?\\(|shell\\(|shell=True|Sys\\.setenv\\(", code)))
})

# -- the interface -------------------------------------------------------------------

test_that("choosing B1 shows the plan, scorers, images and order; standard comes back unchanged", {
  set_mode("ok")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  select_b1(h)
  text <- screen(h)
  expect_match(text, "Plan: 3 tasks x 2 conditions x 2 repeats = 12 trials")
  expect_match(text, "Control \\+ Treatment")
  expect_match(text, "C01: legacy")
  expect_match(text, "D03, D01: knowledge-pilot-v2")
  expect_match(text, "rkmcp-codex-runtime:codex-0.163.0-bioc")
  expect_match(text, "D03-R1 C>T")
  expect_false(grepl("without-mcp", text))
  expect_false(grepl("Instructions", text))
  flat <- paste(trimws(h$pilot$screen_text()), collapse = "")
  expect_match(flat, "--experiment b1-discovery --tasks D03 D01 C01 --repetitions 2", fixed = TRUE)
  h$pilot$press("up")
  text <- screen(h)
  expect_match(text, "Plan: 1 tasks x 2 modes x 1 repetitions = 2 trials")
  expect_match(text, "Instructions")
  expect_false(grepl("b1-discovery --tasks", paste(trimws(h$pilot$screen_text()), collapse = ""), fixed = TRUE))
})

test_that("editing B1 tasks to something the runner does not support blocks the run", {
  set_mode("ok")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  select_b1(h)
  h$pilot$focus("#tasks")
  h$pilot$type(" R01")
  expect_match(screen(h), "exactly these tasks: D03 D01 C01")
  h$pilot$press("f5")
  expect_equal(h$session$run$status, "READY")
  expect_null(h$session$worker)
})

test_that("a B1 run shows run id, trial, condition, repetition and a stage", {
  set_mode("ok")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  select_b1(h)
  h$pilot$press("f5")
  wait_status(h, finished, timeout = 30)
  h$pilot$step()
  st <- h$session$run
  expect_equal(st$status, "COMPLETED")
  expect_equal(st$done, 12L)
  expect_match(st$run_id, RUN_ID_PATTERN)
  text <- screen(h)
  expect_match(text, "12/12 trials finished")
  expect_match(text, "Condition (control|treatment)")
  expect_match(text, "Rep [12]")
  expect_match(text, paste0("Run +", st$run_id))
  expect_match(text, "Stage ")
  expect_match(text, "MCP on")
})

test_that("without 'executor connected' the interface says not connected, not success, and no timeout", {
  set_mode("noconnect")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  select_b1(h)
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$watchdog_seconds), timeout = 15)
  h$pilot$step()
  text <- screen(h)
  expect_equal(h$session$run$status, "RUNNING")
  expect_match(text, "NOT CONNECTED after 45s")
  expect_match(text, "not a timeout")
  expect_false(grepl("EXECUTOR_CONNECTION_TIMEOUT", text, fixed = TRUE))
  expect_false(grepl("COMPLETED", text, fixed = TRUE))
  expect_false(h$session$run$executor_connected)
  h$pilot$press("ctrl+x")
  wait_status(h, finished)
  h$pilot$step()
  expect_equal(h$session$run$status, "INTERRUPTED")
  expect_false(grepl("COMPLETED", screen(h), fixed = TRUE))
})

test_that("EXECUTOR_CONNECTION_TIMEOUT appears only when the runner reports it", {
  set_mode("timeout")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  select_b1(h)
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$timeout_code), timeout = 15)
  h$pilot$step()
  expect_match(screen(h), "EXECUTOR_CONNECTION_TIMEOUT", fixed = TRUE)
})

test_that("Ctrl+X is never turned into success and an incomplete cleanup stays visible", {
  set_mode("incomplete")
  h <- new_pilot(); on.exit(teardown_pilot(h))
  select_b1(h)
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$trial), timeout = 15)
  h$pilot$press("ctrl+x")
  expect_equal(h$session$run$status, "STOPPING")
  expect_match(screen(h), "STOPPING")
  wait_status(h, finished)
  h$pilot$step()
  expect_false(h$session$run$status == "COMPLETED")
  expect_true(h$session$run$cleanup_incomplete)
  text <- screen(h)
  expect_match(text, "CLEANUP INCOMPLETE")
  expect_match(text, "does not delete anything")
  expect_match(text, "Results: ")
})

test_that("credentials never reach the screen or the saved runner logs", {
  marker <- "sk-test-secret-marker-0123456789"
  old <- Sys.getenv(KEY_VARS, unset = NA)
  Sys.setenv(OPENAI_API_KEY = marker, OPENAI_EXECUTOR_API_KEY = marker)
  on.exit({
    for (n in KEY_VARS) if (is.na(old[[n]])) Sys.unsetenv(n) else do.call(Sys.setenv, stats::setNames(list(old[[n]]), n))
  }, add = TRUE)
  set_mode("ok")
  logs <- tempfile("logs-")
  h <- new_pilot(log_dir = logs); on.exit(teardown_pilot(h), add = TRUE)
  select_b1(h)
  h$pilot$press("f5")
  wait_status(h, finished, timeout = 30)
  h$pilot$step()
  expect_false(grepl(marker, screen(h), fixed = TRUE))
  for (f in list.files(logs, full.names = TRUE)) {
    expect_false(any(grepl(marker, readLines(f, warn = FALSE), fixed = TRUE)))
  }
})

# -- resume and results screens (use the runner's own validation helper) ----------------------

write_run <- function(root, id, experiment = NULL, results = NULL, trials = NULL) {
  dir <- file.path(root, id)
  dir.create(dir, recursive = TRUE)
  if (!is.null(experiment)) writeLines(experiment, file.path(dir, "experiment.json"))
  if (!is.null(results)) writeLines(results, file.path(dir, "results.json"))
  for (name in names(trials)) {
    dir.create(file.path(dir, name))
    writeLines(trials[[name]], file.path(dir, name, "result.json"))
  }
  dir
}

experiment_json <- function(id, kind = "standard") {
  plan <- if (kind == "b1-discovery") {
    '[{"trial_id":"b1-discovery-D03-R1-control","task":"D03","mode":"with-mcp","repetition":1,"condition":"control","execution_order":1},
      {"trial_id":"b1-discovery-D03-R1-treatment","task":"D03","mode":"with-mcp","repetition":1,"condition":"treatment","execution_order":2}]'
  } else {
    '[{"trial_id":"R01-A-1","task":"R01","mode":"without-mcp","repetition":1},
      {"trial_id":"R01-B-1","task":"R01","mode":"with-mcp","repetition":1}]'
  }
  sprintf('{"run_id":"%s","experiment_id":%s,"created_at_utc":"2026-10-26T10:00:00Z","effort":"medium","trial_count":2,"trial_plan":%s}',
    id, if (kind == "standard") "null" else sprintf('"%s"', kind), plan)
}

fixture_runner <- function() {
  skip_without_info()
  runner <- fake_runner()
  root <- runner$results_dir
  dir.create(root)
  a <- "20261026T100000Z-aaaaaaaa"
  write_run(root, a, experiment_json(a), sprintf(
    '[{"run_id":"%s","trial_id":"R01-A-1","task":"R01","mode":"without-mcp","repetition":1,"status":"scored","score":{"passed":4,"total":4},"cleanup_completed":true}]', a))
  b <- "20261026T090000Z-bbbbbbbb"
  write_run(root, b, experiment_json(b, "b1-discovery"), sprintf(
    '[{"run_id":"%s","trial_id":"b1-discovery-D03-R1-control","task":"D03","mode":"with-mcp","repetition":1,"condition":"control","execution_order":1,"status":"interrupted","interrupted":true,"score":null,"cleanup_completed":false}]', b))
  write_run(root, "20261026T080000Z-cccccccc")
  runner
}

test_that("Resume lists runs with experiment, recorded/total, status and cleanup; unknown stays unknown", {
  runner <- fixture_runner()
  set_mode("ok")
  h <- new_pilot(runner); on.exit(teardown_pilot(h))
  h$pilot$press("f6")
  text <- screen(h)
  expect_match(text, "20261026T100000Z-aaaaaaaa +standard +partial +1/2 +cl:complete +rs:ok")
  expect_match(text, "20261026T090000Z-bbbbbbbb +b1-discovery +interrupted +1/2 +cl:incomplete")
  expect_match(text, "20261026T080000Z-cccccccc +unknown +unknown +unknown/unknown +cl:unknown +rs:blocked")
})

test_that("Resume passes the chosen run to the runner's --resume and starts nothing before confirmation", {
  runner <- fixture_runner()
  set_mode("ok")
  h <- new_pilot(runner); on.exit(teardown_pilot(h))
  h$pilot$press("f6")
  h$pilot$press("enter")
  expect_match(screen(h), "Resume 20261026T100000Z-aaaaaaaa")
  expect_null(h$session$worker)
  h$pilot$press("tab", "enter")
  wait_status(h, finished)
  h$pilot$step()
  text <- paste(trimws(h$pilot$screen_text()), collapse = "")
  expect_match(text, "--effort medium --resume", fixed = TRUE)
  expect_match(text, "20261026T100000Z-aaaaaaaa", fixed = TRUE)
  expect_equal(h$session$run$run_id, "20261026T100000Z-aaaaaaaa")
  expect_equal(h$session$run$status, "COMPLETED")
  expect_false(grepl("--tasks", text, fixed = TRUE))
})

test_that("an interrupted run with incomplete cleanup warns before resuming and deletes nothing", {
  runner <- fixture_runner()
  set_mode("ok")
  h <- new_pilot(runner); on.exit(teardown_pilot(h))
  h$pilot$press("f6")
  h$pilot$press("down", "enter")
  text <- screen(h)
  expect_match(text, "was interrupted")
  expect_match(text, "Cleanup was incomplete")
  expect_match(text, "never deletes")
  h$pilot$press("escape")
  expect_null(h$session$worker)
})

test_that("a run the runner cannot resume is blocked with an explanation", {
  runner <- fixture_runner()
  set_mode("ok")
  h <- new_pilot(runner); on.exit(teardown_pilot(h))
  h$pilot$press("f6")
  h$pilot$press("down", "down", "enter")
  expect_match(screen(h), "Cannot resume")
  expect_match(screen(h), "refuses to resume")
  h$pilot$press("enter")
  expect_null(h$session$worker)
})

test_that("Results shows B1 conditions, partial runs and empty runs without inventing numbers", {
  runner <- fixture_runner()
  set_mode("ok")
  h <- new_pilot(runner); on.exit(teardown_pilot(h))
  h$pilot$press("f7")
  h$pilot$press("down", "enter")
  text <- screen(h)
  expect_match(text, "b1-discovery-D03-R1-control")
  expect_match(text, "control")
  expect_match(text, "no delta shown")
  expect_false(grepl("without|with-mcp", text))
  h$pilot$press("down", "enter")
  expect_match(screen(h), "No trial results are recorded")
  h$pilot$press("escape")
  expect_match(screen(h), "Experiment")
})

test_that("Resume and Results are unavailable while an experiment runs", {
  runner <- fixture_runner()
  set_mode("sigint")
  h <- new_pilot(runner); on.exit(teardown_pilot(h))
  h$pilot$press("f5")
  h$pilot$wait_for(function(app) !is.na(h$session$run$trial), timeout = 10)
  h$pilot$press("f6")
  h$pilot$press("f7")
  expect_equal(h$session$pane, "run")
})
