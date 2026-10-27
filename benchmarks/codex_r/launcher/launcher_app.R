# termr front end for the benchmark runner. The Python runner stays authoritative:
# this file builds its command line, starts it as a child process and shows what the
# process prints. Run listings and resume validation come from runner_info.py, which
# calls the runner's own functions; the launcher never scores or deletes anything.

library(termr)

# Seconds without runner exit after which the footer suggests a forced stop.
STOP_HINT_SECONDS <- 60

#' @param catalog Task catalog from load_catalog().
#' @param runner list(command, prefix, wd, require_keys, info_script, results_dir).
#' @param log_dir Directory for the runner's stdout/stderr files (kept after the run).
#' @param signal_fn Sends a signal to a pid (replaceable in tests).
#' @return list(app, session); `session` holds the current run state for tests.
launcher_app <- function(catalog, runner, signal_fn = tools::pskill, log_dir = tempdir()) {
  s <- new.env(parent = emptyenv())
  s$run <- new_run_state()
  s$worker <- NULL
  s$exit_when_done <- FALSE
  s$stop_at <- NULL
  s$tails <- list()
  s$launches <- 0L
  s$pane <- "config"
  s$list_mode <- "resume"
  s$runs <- list()
  s$before_dirs <- NULL
  s$resume_run <- NULL
  results_root <- runner$results_dir %||% catalog$results_dir

  radio <- function(id, values, selected) {
    do.call(radio_set, c(
      lapply(values, function(v) radio_button(paste0(v, "   "), v)),
      list(selected = selected, id = id, style = style(layout = "horizontal", height = 1, width = "1fr"))
    ))
  }
  row <- function(title, ..., id = NULL) {
    horizontal(label(sprintf("%-11s", title)), ..., id = id, style = style(height = 1))
  }
  defaults <- default_config()
  field <- function(width) style(width = width, height = 1, border = "none", background = "$surface")
  flat_button <- function(text, id) button(text, id = id, style = style(height = 1, border = "none", width = 18))

  # label() has no `visible` argument (vertical() does); hide it after construction.
  b1_info <- label("", id = "b1_info", style = style(height = 8, wrap = "word"))
  b1_info$visible <- FALSE

  config_pane <- vertical(
    row("Experiment", radio("experiment", EXPERIMENTS, "standard")),
    row("Tasks", radio("preset", c("tasks", "tool-value", "full"), "tasks"), id = "row_preset"),
    row(
      "Task ids",
      input(defaults$tasks, id = "tasks", placeholder = "e.g. R01 H01 D03, all, hard-pilot", style = field(34)),
      label(sprintf(" (%d tool-value, %d full)", length(catalog$tool_value), length(catalog$full)), id = "task_hint")
    ),
    row(
      "Modes",
      checkbox("without-mcp", TRUE, id = "mode_without", style = style(width = 16)),
      checkbox("with-mcp", TRUE, id = "mode_with"),
      id = "row_modes"
    ),
    row("Effort", radio("effort", EFFORTS, defaults$effort)),
    row(
      "Repeats",
      input(as.character(defaults$repetitions), id = "repetitions", style = field(7)),
      label("  Timeout s "),
      input(as.character(defaults$timeout), id = "timeout", style = field(7))
    ),
    row("Instructions", radio("instructions", catalog$instructions, "standard"), id = "row_instructions"),
    row("Scorer", radio("scorer", SCORERS, "legacy"), id = "row_scorer"),
    b1_info,
    label("", id = "plan", style = style(height = 1)),
    label("", id = "review", style = style(height = 1, foreground = "$muted")),
    label("", id = "problems", style = style(height = 2, foreground = "$error")),
    label("", id = "command", style = style(height = 3, foreground = "$muted", wrap = "char")),
    horizontal(
      flat_button("[F2] Pick task", "btn_pick_task"),
      flat_button("[F5] Run", "btn_run"), flat_button("[F6] Resume", "btn_resume"),
      flat_button("[F7] Results", "btn_results"),
      style = style(height = 1)
    ),
    id = "config_pane",
    style = style(height = "auto")
  )

  run_pane <- vertical(
    label("", id = "run_where", style = style(height = 1)),
    label("", id = "run_progress", style = style(height = 1)),
    label("", id = "run_trial", style = style(height = 1)),
    label("", id = "run_stage", style = style(height = 1)),
    label("", id = "run_executor", style = style(height = 1)),
    label("", id = "run_activity", style = style(height = 1)),
    label("", id = "run_detail", style = style(height = 2, wrap = "word")),
    log_view(max_lines = 1000, id = "log", style = style(height = "1fr")),
    id = "run_pane",
    visible = FALSE,
    style = style(height = "1fr")
  )

  runs_pane <- vertical(
    label("", id = "runs_title", style = style(height = 1, bold = TRUE)),
    option_list(c("(loading)"), id = "runs_list", style = style(height = 7)),
    log_view(max_lines = 200, id = "runs_detail", style = style(height = "1fr")),
    id = "runs_pane",
    visible = FALSE,
    style = style(height = "1fr")
  )

  task_picker_pane <- vertical(
    label("Select task IDs; Enter adds one. Add more tasks, then press Esc to return.", id = "task_picker_hint",
      style = style(height = 1, foreground = "$muted")),
    label("", id = "task_picker_selected", style = style(height = 3, wrap = "word", foreground = "$accent")),
    option_list(c("(loading)"), id = "task_picker", style = style(height = 12)),
    id = "task_picker_pane",
    visible = FALSE,
    style = style(height = "1fr")
  )

  ui <- vertical(
    horizontal(
      label("Benchmark launcher", style = style(bold = TRUE, width = 22), id = "title"),
      label("", id = "badge", style = style(width = "1fr", align = "right", bold = TRUE)),
      style = style(height = 1)
    ),
    config_pane,
    run_pane,
    runs_pane,
    task_picker_pane,
    label("", id = "footer", style = style(height = 1, foreground = "$muted")),
    style = style(padding = c(0, 1))
  )

  # -- helpers ---------------------------------------------------------------

  q <- function(app, id) app$query_one(paste0("#", id))

  task_choices <- function() {
    tasks <- unique(c(catalog$r, catalog$hard, catalog$knowledge, catalog$smoke))
    stats::setNames(tasks, tasks)
  }

  update_task_picker_summary <- function(app) {
    selected <- split_tokens(q(app, "tasks")$value)
    text <- if (length(selected)) paste(selected, collapse = ", ") else "(none)"
    q(app, "task_picker_selected")$update(paste("Selected task IDs:", text))
  }

  read_config <- function(app) {
    experiment <- q(app, "experiment")$value
    effort <- q(app, "effort")$value
    repetitions <- as_whole_number(q(app, "repetitions")$value)
    timeout <- as_whole_number(q(app, "timeout")$value)
    if (identical(experiment, "b1-discovery")) {
      # Only tasks, repetitions, effort and timeout come from the user; the runner
      # fixes the rest, and validate_config checks the typed values against it.
      cfg <- b1_config(catalog, effort, timeout)
      cfg$tasks <- split_tokens(q(app, "tasks")$value)
      cfg$repetitions <- repetitions
      return(cfg)
    }
    modes <- c(
      if (isTRUE(q(app, "mode_without")$value)) "without-mcp",
      if (isTRUE(q(app, "mode_with")$value)) "with-mcp"
    )
    list(
      experiment = "standard",
      preset = q(app, "preset")$value,
      tasks = split_tokens(q(app, "tasks")$value),
      modes = modes,
      effort = effort,
      repetitions = repetitions,
      timeout = timeout,
      instructions = q(app, "instructions")$value,
      scorer = q(app, "scorer")$value
    )
  }

  running <- function() !is.null(s$worker) && s$run$status %in% c("RUNNING", "STOPPING")

  badge_style <- function(status) {
    colour <- switch(status,
      READY = "$muted", RUNNING = "$accent", STOPPING = "$warning",
      COMPLETED = "$success", INTERRUPTED = "$warning", FAILED = "$error", "$muted"
    )
    style(foreground = colour, bold = TRUE)
  }

  set_badge <- function(app, text, status = text) {
    q(app, "badge")$update(text)
    q(app, "badge")$set(style = badge_style(status))
  }

  refresh_footer <- function(app) {
    text <- if (running()) {
      if (s$run$status == "STOPPING") {
        "Stopping: runner is cleaning up. Ctrl+X again = force kill (may leave Docker resources)"
      } else {
        "Ctrl+X stop (graceful)  Ctrl+C stop and quit  Tab to scroll the log"
      }
    } else if (s$pane == "runs") {
      "Up/Down choose  Enter select  Esc back  F10 quit"
    } else if (s$pane == "task_picker") {
      "Up/Down choose ID  Enter add another  Esc back  F10 quit"
    } else if (s$run$status == "READY") {
      "F2 choose task  F5 run  F6 resume  F7 results  Tab/Shift+Tab move  F10 quit"
    } else {
      "F2 choose task  F5 run again  F6 resume  F7 results  Esc configuration  F10 quit"
    }
    q(app, "footer")$update(text)
  }

  b1_info_text <- function() {
    paste(
      "Conditions   Control + Treatment (MCP on in both)",
      paste0("Scorer       ", b1_scorer_text(catalog)),
      paste0("Images       executor ", B1_IMAGES[["executor"]], ", scorer ", B1_IMAGES[["scorer"]],
        ", mcp ", B1_IMAGES[["mcp"]]),
      paste0("Order        ", b1_order_text(catalog), "  (C=control, T=treatment; the runner's plan)"),
      sep = "\n"
    )
  }

  refresh_review <- function(app) {
    cfg <- read_config(app)
    b1 <- is_b1(cfg)
    q(app, "tasks")$set(disabled = !b1 && cfg$preset != "tasks")
    q(app, "btn_pick_task")$set(disabled = b1 || cfg$preset != "tasks")
    problems <- validate_config(cfg, catalog)
    absent <- if (isTRUE(runner$require_keys)) missing_keys() else character()
    if (length(absent)) problems <- c(problems, paste("Not exported in this shell:", paste(absent, collapse = ", ")))
    plan <- planned_trials(cfg, catalog)
    q(app, "plan")$update(
      if (is.na(plan)) "Plan: -"
      else if (b1) sprintf("Plan: %d tasks x 2 conditions x %d repeats = %d trials",
        length(cfg$tasks), cfg$repetitions, plan)
      else sprintf("Plan: %d tasks x %d modes x %d repetitions = %d trials",
        length(expand_config_tasks(cfg, catalog)), length(cfg$modes), cfg$repetitions, plan)
    )
    review <- if (b1) {
      paste0("Review: ", paste(cfg$tasks, collapse = ", "), " | Control + Treatment | MCP on in both")
    } else {
      task_scope <- if (cfg$preset == "tasks") {
        selected <- expand_config_tasks(cfg, catalog)
        if (length(selected) <= 3) paste(selected, collapse = ", ")
        else sprintf("%d selected tasks", length(selected))
      } else if (cfg$preset == "tool-value") {
        sprintf("tool-value (%d tasks)", length(catalog$tool_value))
      } else {
        sprintf("full (%d tasks)", length(catalog$full))
      }
      modes <- if (length(cfg$modes)) {
        paste(ifelse(cfg$modes == "with-mcp", "MCP on", "MCP off"), collapse = " + ")
      } else {
        "no MCP mode selected"
      }
      paste("Review:", task_scope, "|", modes, "|", cfg$effort, "|", cfg$scorer)
    }
    q(app, "review")$update(review)
    q(app, "problems")$update(paste(utils::head(problems, 2), collapse = "\n"))
    q(app, "command")$update(
      if (length(validate_config(cfg, catalog))) "" else shell_preview(build_command(cfg, runner))
    )
    s$problems <- problems
    invisible(problems)
  }

  # Show the controls that belong to the chosen experiment.
  apply_experiment <- function(app) {
    b1 <- identical(q(app, "experiment")$value, "b1-discovery")
    for (id in c("row_preset", "row_modes", "row_instructions", "row_scorer", "task_hint")) {
      widget <- q(app, id)
      widget$visible <- !b1
    }
    info <- q(app, "b1_info")
    info$visible <- b1
    tasks <- q(app, "tasks")
    repetitions <- q(app, "repetitions")
    if (b1) {
      info$update(b1_info_text())
      tasks$value <- paste(catalog$b1_tasks, collapse = " ")
      repetitions$value <- as.character(catalog$b1_repetitions)
    } else {
      tasks$value <- defaults$tasks
      repetitions$value <- as.character(defaults$repetitions)
    }
    refresh_review(app)
  }

  executor_text <- function(st) {
    on <- identical(st$mode, "with-mcp")
    mcp <- if (is.na(st$mode)) "MCP -" else if (on) "MCP on (started before the session was created)" else "MCP off"
    state <- if (isTRUE(st$executor_connected)) {
      "connected"
    } else if (!is.na(st$timeout_code)) {
      st$timeout_code
    } else if (!is.na(st$watchdog_seconds)) {
      sprintf("NOT CONNECTED after %ds (runner watchdog, not a timeout)", round(st$watchdog_seconds))
    } else if (identical(st$stage, "Waiting for executor")) {
      "not connected yet"
    } else "-"
    if (is.na(st$trial)) mcp <- "MCP -"
    paste0("Executor     ", state, "   ", mcp)
  }

  refresh_run <- function(app) {
    st <- s$run
    set_badge(app, st$status)
    q(app, "run_where")$update(paste0("Run          ", if (is.na(st$run_id)) "(not created yet)" else st$run_id))
    q(app, "run_progress")$update(sprintf(
      "%s   elapsed %s%s", progress_text(st), format_elapsed(elapsed_seconds(st)),
      if (is.na(st$exit_status)) "" else paste0("   exit status ", st$exit_status)
    ))
    q(app, "run_trial")$update(paste0("Trial        ", if (is.na(st$trial)) "starting runner..." else st$trial))
    q(app, "run_stage")$update(paste0(
      "Task ", if (is.na(st$task)) "-" else st$task,
      if (!is.na(st$condition)) paste0("  Condition ", st$condition) else paste0("  Mode ", st$mode %||% "-"),
      if (!is.na(st$repetition)) paste0("  Rep ", st$repetition) else "",
      "  Stage ", if (is.na(st$stage)) "-" else toupper(st$stage),
      if (!is.na(st$trial_seconds)) sprintf(" (%.0fs)", st$trial_seconds) else ""
    ))
    q(app, "run_activity")$update(paste("Last event   ", if (is.na(st$activity)) "-" else st$activity))
    q(app, "run_executor")$update(executor_text(st))
    detail <- c(
      if (!is.na(st$detail)) st$detail,
      if (!is.na(st$results_dir)) paste("Results:", st$results_dir),
      if (st$stderr_lines > 0) sprintf("%d stderr line(s)", st$stderr_lines)
    )
    q(app, "run_detail")$update(paste(detail, collapse = "   "))
    refresh_footer(app)
  }

  show_pane <- function(app, pane) {
    s$pane <- pane
    for (id in c("config", "run", "runs", "task_picker")) {
      widget <- q(app, paste0(id, "_pane"))
      widget$visible <- id == pane
    }
    if (pane == "config") {
      set_badge(app, s$run$status)
      refresh_review(app)
    } else if (pane == "runs") {
      set_badge(app, toupper(s$list_mode), "READY")
    } else if (pane == "task_picker") {
      set_badge(app, "TASK PICKER", "READY")
    }
    refresh_footer(app)
  }

  log_line <- function(app, text, level = "info") q(app, "log")$write(text, level = level)

  handle_stdout <- function(app, line) {
    apply_runner_line(s$run, line)
    log_line(app, line, "info")
  }

  handle_stderr <- function(app, line) {
    s$run$stderr_lines <- s$run$stderr_lines + 1L
    log_line(app, line, if (grepl("error|traceback|exception", line, ignore.case = TRUE)) "error" else "warning")
  }

  # The new run directory is the one that appeared after launch (the runner prints
  # the path only at the end).
  detect_run_id <- function() {
    if (!is.na(s$run$run_id) || is.null(s$before_dirs)) return(invisible())
    fresh <- setdiff(run_dirs(results_root), s$before_dirs)
    if (length(fresh) == 1L) s$run$run_id <- fresh
  }

  # The runner writes to files (see wrap_command); read what is new.
  poll_output <- function(app, final = FALSE) {
    if (!length(s$tails)) return(invisible(FALSE))
    out <- read_tail(s$tails$out, final)
    err <- read_tail(s$tails$err, final)
    for (line in out) handle_stdout(app, line)
    for (line in err) handle_stderr(app, line)
    detect_run_id()
    if (length(out) || length(err)) refresh_run(app)
    invisible(length(out) + length(err) > 0)
  }

  finish <- function(app, exit_status, note = NULL) {
    poll_output(app, final = TRUE)
    finish_run(s$run, exit_status)
    if (!is.null(note)) s$run$detail <- paste(c(note, if (s$run$cleanup_incomplete) s$run$detail), collapse = "; ")
    level <- switch(s$run$status, COMPLETED = "success", INTERRUPTED = "warning", "error")
    log_line(app, sprintf("--- %s%s ---", s$run$status,
      if (is.na(exit_status)) "" else paste0(" (exit status ", exit_status, ")")), level)
    if (isTRUE(s$run$cleanup_incomplete)) {
      log_line(app, "--- CLEANUP INCOMPLETE: check `docker ps -a`; the launcher does not delete anything ---", "error")
    }
    s$worker <- NULL
    refresh_run(app)
    if (s$exit_when_done) app$exit()
  }

  # Start the runner for a new experiment (spec from build_command) or a resume.
  launch <- function(app, spec, total, run_id = NA_character_) {
    s$run <- new_run_state(total)
    s$run$status <- "RUNNING"
    s$run$started <- Sys.time()
    s$run$run_id <- run_id
    s$exit_when_done <- FALSE
    s$before_dirs <- if (is.na(run_id)) run_dirs(results_root) else NULL
    q(app, "log")$clear()
    log_line(app, paste("$", shell_preview(spec)), "debug")
    show_pane(app, "run")
    refresh_run(app)
    # The counter keeps two launches within one second from sharing (appending to) a file.
    s$launches <- s$launches + 1L
    stem <- sprintf("runner-%s-%d-%d", format(Sys.time(), "%Y%m%dT%H%M%S"), Sys.getpid(), s$launches)
    dir.create(log_dir, recursive = TRUE, showWarnings = FALSE)
    out_file <- file.path(log_dir, paste0(stem, ".out.log"))
    err_file <- file.path(log_dir, paste0(stem, ".err.log"))
    s$tails <- list(out = new_tail(out_file), err = new_tail(err_file))
    s$run$log_files <- c(out_file, err_file)
    wrapped <- wrap_command(spec, out_file, err_file)
    s$worker <- app$run_process(
      wrapped$command, wrapped$args, wd = wrapped$wd, name = "benchmark-runner",
      # A non-zero exit also arrives here; on_exit reports it, so only log other failures.
      on_error = function(message, app) {
        if (!grepl("^The process exited with status", message)) log_line(app, paste("process error:", message), "error")
      },
      on_exit = function(status, app) {
        # termr passes the exit status (negative for a signal), or NA.
        if (!identical(s$run$status, "RUNNING") && !identical(s$run$status, "STOPPING")) return(invisible())
        finish(app, as_whole_number(status))
      }
    )
    # If this R process dies (terminal closed, SIGTERM, SIGKILL) the guard still
    # interrupts the runner so that its own cleanup runs instead of leaving it orphaned.
    guard <- guard_command(Sys.getpid(), s$worker$pid())
    s$guard <- app$run_process(guard$command, guard$args, name = "runner-guard")
    invisible(TRUE)
  }

  start_run <- function(app) {
    if (running() || s$pane %in% c("runs", "task_picker")) return(invisible(FALSE))
    refresh_review(app)
    if (length(s$problems)) return(invisible(FALSE))
    cfg <- read_config(app)
    launch(app, build_command(cfg, runner), planned_trials(cfg, catalog))
  }

  # -- resume and results ------------------------------------------------------

  open_task_picker <- function(app) {
    cfg <- read_config(app)
    if (running() || s$pane != "config" || is_b1(cfg) || cfg$preset != "tasks") {
      return(invisible(FALSE))
    }
    q(app, "task_picker")$set_choices(task_choices())
    update_task_picker_summary(app)
    show_pane(app, "task_picker")
    q(app, "task_picker")$focus()
    invisible(TRUE)
  }

  add_selected_task <- function(event, app) {
    if (s$pane != "task_picker") return(invisible(FALSE))
    selected <- q(app, "task_picker")$value
    if (is.null(selected) || !selected %in% task_choices()) return(invisible(FALSE))
    task_input <- q(app, "tasks")
    current <- split_tokens(task_input$value)
    if (!selected %in% current) current <- c(current, selected)
    task_input$value <- paste(current, collapse = " ")
    update_task_picker_summary(app)
    refresh_review(app)
    q(app, "task_picker")$focus()
    invisible(TRUE)
  }

  open_runs <- function(app, mode) {
    if (running()) return(invisible(FALSE))
    s$list_mode <- mode
    runs <- list_runs(runner, results_root, limit = 10)
    s$runs <- runs %||% list()
    title <- if (mode == "resume") "Resume: choose a run (the runner re-validates it)" else "Results: choose a run"
    q(app, "runs_title")$update(paste(title, "-", results_root))
    choices <- if (length(s$runs)) {
      stats::setNames(vapply(s$runs, function(r) r$run_id, ""), vapply(s$runs, run_label, ""))
    } else c("(no runs found)" = "")
    q(app, "runs_list")$set_choices(choices)
    q(app, "runs_detail")$clear()
    if (is.null(runs)) {
      q(app, "runs_detail")$write("Could not read the results directory with the runner's helper.", level = "error")
    }
    show_pane(app, "runs")
    q(app, "runs_list")$focus()
  }

  chosen_run <- function(app) {
    id <- q(app, "runs_list")$value
    hit <- which(vapply(s$runs, function(r) identical(r$run_id, id), logical(1)))
    if (length(hit)) s$runs[[hit[1]]] else NULL
  }

  show_results <- function(app, run) {
    detail <- q(app, "runs_detail")
    detail$clear()
    path <- file.path(results_root, run$run_id)
    detail$write(paste("Path:", path), level = "info")
    detail$write(sprintf("Experiment %s   created %s   effort %s   status %s   cleanup %s",
      run$experiment, run$created, run$effort, run$status, run$cleanup), level = "info")
    trials <- run_summary(runner, path)
    for (line in summary_lines(run, trials %||% list())) detail$write(line, level = "info")
    detail$write("Analytics: see benchmarks/codex_r/analytics/README.md (the launcher computes no scores).", level = "debug")
  }

  resume_run <- function(app, run) {
    effort <- run$effort
    if (!effort %in% EFFORTS) return(invisible(FALSE))
    path <- file.path(results_root, run$run_id)
    spec <- build_resume_command(path, effort, runner)
    total <- suppressWarnings(as.integer(run$total))
    launch(app, spec, total, run_id = run$run_id)
  }

  confirm_resume <- function(app, run) {
    warnings <- resume_warnings(run)
    if (!resume_allowed(run)) {
      text <- paste(c(
        if (identical(run$status, "finished")) "This run is already finished; nothing to resume.",
        warnings
      ), collapse = "\n")
      app$push_screen(alert_dialog(text, title = "Cannot resume", width = 70))
      return(invisible(FALSE))
    }
    app$push_screen(confirm_dialog(
      paste(c(paste("Resume", run$run_id, "?"), warnings, "Recorded trials are not repeated; new trials make paid API calls."),
        collapse = "\n"),
      on_confirm = function(app) resume_run(app, run),
      title = "Resume", confirm_label = "Resume", cancel_label = "Cancel", width = 70
    ))
  }

  run_selected <- function(event, app) {
    run <- chosen_run(app)
    if (is.null(run)) return(invisible())
    if (s$list_mode == "resume") confirm_resume(app, run) else show_results(app, run)
  }

  force_kill <- function(app) {
    if (!running()) return(invisible())
    worker <- s$worker
    worker$cancel(grace = 0.3)
    finish(app, NA_integer_, "force-killed: check `docker ps -a` and delete leftover rkmcp-simple-* resources")
  }

  stop_run <- function(app) {
    if (!running()) return(invisible(FALSE))
    if (s$run$status == "STOPPING") {
      app$push_screen(confirm_dialog(
        paste("Force kill the runner now?\nIts cleanup is not finished: Docker containers,",
          "networks or API sessions may be left behind."),
        on_confirm = function(app) force_kill(app),
        title = "Force kill", confirm_label = "Force kill", cancel_label = "Keep waiting"
      ))
      return(invisible(FALSE))
    }
    s$run$stop_requested <- TRUE
    s$run$status <- "STOPPING"
    s$run$stage <- "Cleanup (stop requested)"
    s$stop_at <- Sys.time()
    pid <- s$worker$pid()
    # SIGINT is what Ctrl+C sends: the runner starts its bounded cleanup.
    if (!is.na(pid)) signal_fn(pid, tools::SIGINT)
    log_line(app, "--- stop requested: SIGINT sent, waiting for the runner's cleanup ---", "warning")
    refresh_run(app)
    invisible(TRUE)
  }

  quit_app <- function(app) {
    if (!running()) return(app$exit())
    app$push_screen(confirm_dialog(
      "An experiment is running.\nStop it gracefully and quit once its cleanup has finished?",
      on_confirm = function(app) {
        s$exit_when_done <- TRUE
        if (s$run$status != "STOPPING") stop_run(app)
      },
      title = "Quit", confirm_label = "Stop and quit", cancel_label = "Keep running"
    ))
  }

  back <- function(app) {
    if (running()) return(invisible())
    if (s$pane %in% c("runs", "run", "task_picker")) show_pane(app, "config")
  }

  tick <- function(app) {
    if (running()) {
      poll_output(app)
      st <- s$run
      q(app, "run_progress")$update(sprintf(
        "%s   elapsed %s", progress_text(st), format_elapsed(elapsed_seconds(st))
      ))
      if (st$status == "STOPPING" && as.numeric(difftime(Sys.time(), s$stop_at, units = "secs")) > STOP_HINT_SECONDS) {
        q(app, "run_detail")$update("Cleanup is taking long. Ctrl+X to force kill, or keep waiting.")
      }
    }
  }

  # -- application ------------------------------------------------------------

  changed <- function(event, app) refresh_review(app)

  launcher <- app(
    ui,
    title = "Benchmark launcher",
    bind("f5", function(app) start_run(app), "Run experiment"),
    bind("f2", function(app) open_task_picker(app), "Choose a task"),
    bind("f6", function(app) open_runs(app, "resume"), "Resume a run"),
    bind("f7", function(app) open_runs(app, "results"), "Results"),
    bind("ctrl+x", function(app) stop_run(app), "Stop experiment"),
    bind("escape", function(app) back(app), "Back to configuration"),
    bind("ctrl+c", function(app) quit_app(app), "Quit"),
    bind("f10", function(app) quit_app(app), "Quit"),
    on("input.changed", "#tasks, #repetitions, #timeout", changed),
    on("checkbox.changed", "#mode_without, #mode_with", changed),
    on("radio_set.changed", "#preset, #effort, #instructions, #scorer", changed),
    on("radio_set.changed", "#experiment", function(event, app) apply_experiment(app)),
    on("option_list.selected", "#runs_list", run_selected),
    on("option_list.selected", "#task_picker", add_selected_task),
    on("button.pressed", "#btn_pick_task", function(event, app) open_task_picker(app)),
    on("button.pressed", "#btn_run", function(event, app) start_run(app)),
    on("button.pressed", "#btn_resume", function(event, app) open_runs(app, "resume")),
    on("button.pressed", "#btn_results", function(event, app) open_runs(app, "results"))
  )
  launcher$add_command(command("Run experiment", function(app) start_run(app), category = "Run", shortcut = "f5",
    enabled = function(app) !running()))
  launcher$add_command(command("Resume a run", function(app) open_runs(app, "resume"), category = "Run", shortcut = "f6",
    enabled = function(app) !running()))
  launcher$add_command(command("Results", function(app) open_runs(app, "results"), category = "Run", shortcut = "f7",
    enabled = function(app) !running()))
  launcher$add_command(command("Stop experiment", function(app) stop_run(app), category = "Run", shortcut = "ctrl+x",
    enabled = function(app) running()))
  launcher$call_later(function(app) {
    show_pane(app, "config")
    app$set_interval(0.25, tick)
  })
  list(app = launcher, session = s)
}
