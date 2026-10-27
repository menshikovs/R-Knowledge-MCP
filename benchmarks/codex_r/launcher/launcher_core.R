# Pure logic of the benchmark launcher: no termr, no processes.
# The Python runner stays authoritative; everything here only mirrors what
# `python -m benchmarks.codex_r.run_simple --help` already accepts.

MODES <- c("without-mcp", "with-mcp")
EFFORTS <- c("medium", "high")
SCORERS <- c("legacy", "knowledge-pilot-v2", "knowledge-pilot-v2.1")
PRESETS <- c(tasks = "tasks", tool_value = "tool-value", full = "full")
SUCCESS_STATUSES <- c("scored", "smoke_transport_observed")
KEY_VARS <- c("OPENAI_API_KEY", "OPENAI_EXECUTOR_API_KEY")
EXPERIMENTS <- c("standard", "b1-discovery")
# Images of the B1 setup; passed explicitly so the plan shows exactly what will run.
B1_IMAGES <- c(
  executor = "rkmcp-codex-runtime:codex-0.163.0-bioc",
  scorer = "codex-r-benchmark:pilot-bioc",
  mcp = "cran-knowledge-mcp:shiny-quarto"
)

# Task catalog -------------------------------------------------------------

#' Parse the `key=a b c` lines printed by the catalog probe.
parse_catalog <- function(lines) {
  lines <- lines[grepl("^[a-z0-9_]+=", lines)]
  keys <- sub("=.*$", "", lines)
  values <- strsplit(trimws(sub("^[a-z0-9_]+=", "", lines)), "[[:space:]]+")
  values <- lapply(values, function(v) v[nzchar(v)])
  catalog <- stats::setNames(values, keys)
  needed <- c("r", "hard", "knowledge", "tool_value", "full", "instructions", "smoke",
    "b1_tasks", "b1_repetitions", "b1_order", "b1_scorers")
  missing <- setdiff(needed, names(catalog))
  if (length(missing)) {
    stop("task catalog is incomplete (missing: ", paste(missing, collapse = ", "), ")", call. = FALSE)
  }
  catalog
}

#' Run the read-only info helper (runner_info.py) with plain argv values.
#' `runner` is list(command, wd, info_script, ...).
run_info <- function(runner, args) {
  result <- tryCatch(
    processx::run(
      runner$info_command %||% runner$command, c(runner$info_script, args),
      wd = runner$info_wd %||% runner$wd, env = c("current", PYTHONPATH = runner$info_wd %||% runner$wd),
      error_on_status = FALSE, timeout = 60
    ),
    error = function(e) NULL
  )
  if (is.null(result) || result$status != 0) return(NULL)
  strsplit(result$stdout, "\n", fixed = TRUE)[[1]]
}

#' Ask the real runner for its task ids and B1 plan.
load_catalog <- function(runner) {
  out <- run_info(runner, "catalog")
  if (is.null(out)) {
    stop("could not read the task catalog from the runner (", runner$command, ")", call. = FALSE)
  }
  parse_catalog(out)
}

selectable_tasks <- function(catalog) {
  c("all", "hard-pilot", catalog$smoke, catalog$r, catalog$hard, catalog$knowledge)
}

# Configuration --------------------------------------------------------------

default_config <- function() {
  list(
    experiment = "standard", preset = "tasks", tasks = "R01", modes = MODES,
    effort = "medium", repetitions = 1L, timeout = 900L, instructions = "standard",
    scorer = "legacy"
  )
}

is_b1 <- function(cfg) identical(cfg$experiment, "b1-discovery")

#' B1 values the runner requires (tasks, repetitions, scorer); only effort/timeout are free.
b1_config <- function(catalog, effort = "medium", timeout = 900L) {
  list(
    experiment = "b1-discovery", preset = "tasks", tasks = catalog$b1_tasks,
    modes = "with-mcp", effort = effort, repetitions = as.integer(catalog$b1_repetitions),
    timeout = timeout, instructions = "standard", scorer = "knowledge-pilot-v2"
  )
}

#' "D03:knowledge-pilot-v2 C01:legacy" -> named character vector.
b1_scorer_map <- function(catalog) {
  parts <- strsplit(catalog$b1_scorers, ":", fixed = TRUE)
  stats::setNames(vapply(parts, `[`, "", 2), vapply(parts, `[`, "", 1))
}

#' "D03, D01: knowledge-pilot-v2 | C01: legacy (no V2 contract for C01)" grouped by scorer.
b1_scorer_text <- function(catalog) {
  map <- b1_scorer_map(catalog)
  groups <- vapply(unique(map), function(scorer) {
    paste0(paste(names(map)[map == scorer], collapse = ", "), ": ", scorer,
      if (scorer == "legacy") " (no V2 contract)" else "")
  }, "")
  paste(groups, collapse = " | ")
}

#' Planner order as reported by the runner: list of (task, repetition, condition).
b1_order <- function(catalog) {
  parts <- strsplit(catalog$b1_order, ":", fixed = TRUE)
  lapply(parts, function(p) list(task = p[1], repetition = as.integer(p[2]), condition = p[3]))
}

#' Compact view of the runner's order: "D03-R1 C>T  D01-R1 T>C ..." (never reordered here).
b1_order_text <- function(catalog) {
  trials <- b1_order(catalog)
  key <- vapply(trials, function(t) paste0(t$task, "-R", t$repetition), "")
  initial <- vapply(trials, function(t) toupper(substr(t$condition, 1, 1)), "")
  pairs <- vapply(unique(key), function(k) paste(initial[key == k], collapse = ">"), "")
  paste(paste(unique(key), pairs), collapse = "  ")
}

split_tokens <- function(text) {
  tokens <- strsplit(trimws(text %||% ""), "[[:space:],]+")[[1]]
  unique(tokens[nzchar(tokens)])
}

`%||%` <- function(a, b) if (is.null(a)) b else a

as_whole_number <- function(x) {
  value <- suppressWarnings(as.numeric(trimws(as.character(x))))
  if (length(value) != 1 || is.na(value) || value != floor(value)) NA_integer_ else as.integer(value)
}

#' Tasks the runner will actually execute for this configuration.
expand_config_tasks <- function(cfg, catalog) {
  if (cfg$preset == "tool-value") return(catalog$tool_value)
  if (cfg$preset == "full") return(catalog$full)
  out <- character()
  for (task in cfg$tasks) {
    out <- c(out, if (task == "all") catalog$r else if (task == "hard-pilot") catalog$hard else task)
  }
  unique(out)
}

#' Validate a configuration against the runner's own rules (run_simple.main).
#' Returns a character vector of problems; empty means valid.
validate_config <- function(cfg, catalog) {
  errors <- character()
  add <- function(msg) errors <<- c(errors, msg)
  if (!(cfg$experiment %||% "standard") %in% EXPERIMENTS) {
    return("Unknown experiment")
  }
  if (is_b1(cfg)) return(validate_b1(cfg, catalog))
  if (!cfg$preset %in% PRESETS) add("Unknown task preset")
  if (cfg$preset == "tasks") {
    if (!length(cfg$tasks)) {
      add("Select at least one task")
    } else {
      unknown <- setdiff(cfg$tasks, selectable_tasks(catalog))
      if (length(unknown)) add(paste("Unknown task id:", paste(unknown, collapse = ", ")))
    }
  }
  if (!length(cfg$modes) || !all(cfg$modes %in% MODES)) add("Select at least one mode")
  if (!cfg$effort %in% EFFORTS) add("Effort must be medium or high")
  if (is.na(cfg$repetitions) || cfg$repetitions < 1 || cfg$repetitions > 100) {
    add("Repetitions must be a whole number from 1 to 100")
  }
  if (is.na(cfg$timeout) || cfg$timeout < 1 || cfg$timeout > 900) {
    add("Timeout must be a whole number from 1 to 900 seconds")
  }
  if (!cfg$instructions %in% catalog$instructions) add("Unknown instruction variant")
  if (!cfg$scorer %in% SCORERS) add("Unknown scorer")
  if (!length(errors)) {
    tasks <- expand_config_tasks(cfg, catalog)
    if (catalog$smoke %in% tasks && (!identical(tasks, catalog$smoke) || !identical(cfg$modes, "with-mcp"))) {
      add("mcp-smoke runs alone and only with the with-mcp mode")
    }
    if (cfg$scorer == "knowledge-pilot-v2" && !any(tasks %in% catalog$knowledge)) {
      add("knowledge-pilot-v2 needs at least one B/C/D/E pilot task")
    }
    if (cfg$scorer == "knowledge-pilot-v2.1" &&
        (!length(tasks) || !all(tasks %in% c("D01", "D03")))) {
      add("knowledge-pilot-v2.1 supports D01 and D03 only")
    }
  }
  errors
}

#' B1 accepts exactly the runner's task list and repetition count; scorer and
#' instructions are fixed by the runner, the rest of the flags are incompatible with it.
validate_b1 <- function(cfg, catalog) {
  errors <- character()
  add <- function(msg) errors <<- c(errors, msg)
  if (!identical(cfg$tasks, catalog$b1_tasks)) {
    add(paste("B1 Discovery supports exactly these tasks:", paste(catalog$b1_tasks, collapse = " ")))
  }
  if (!identical(cfg$repetitions, as.integer(catalog$b1_repetitions))) {
    add(paste("B1 Discovery requires", catalog$b1_repetitions, "repetitions"))
  }
  if (!cfg$effort %in% EFFORTS) add("Effort must be medium or high")
  if (is.na(cfg$timeout) || cfg$timeout < 1 || cfg$timeout > 900) {
    add("Timeout must be a whole number from 1 to 900 seconds")
  }
  if (!identical(cfg$instructions, "standard")) add("B1 Discovery requires standard instructions")
  if (!identical(cfg$scorer, "knowledge-pilot-v2")) add("B1 Discovery requires knowledge-pilot-v2")
  if (!identical(cfg$modes, "with-mcp")) add("B1 Discovery runs with MCP in both conditions")
  errors
}

#' Number of trials the runner will plan (standard: tasks x modes x repetitions;
#' B1: the runner's own planned_b1_trials).
planned_trials <- function(cfg, catalog) {
  if (length(validate_config(cfg, catalog))) return(NA_integer_)
  if (is_b1(cfg)) return(length(catalog$b1_order))
  length(expand_config_tasks(cfg, catalog)) * length(unique(cfg$modes)) * cfg$repetitions
}

#' Arguments after `-m benchmarks.codex_r.run_simple`; never passed through a shell.
build_args <- function(cfg) {
  if (is_b1(cfg)) {
    # No standard discovery policy flag: B1 keeps its fixed pre-discovery allow-list.
    return(c(
      "--effort", cfg$effort, "--experiment", "b1-discovery", "--tasks", cfg$tasks,
      "--repetitions", as.character(cfg$repetitions), "--timeout", as.character(cfg$timeout),
      "--knowledge-pilot-scorer", cfg$scorer,
      "--executor-image", B1_IMAGES[["executor"]], "--scorer-image", B1_IMAGES[["scorer"]],
      "--mcp-image", B1_IMAGES[["mcp"]]
    ))
  }
  args <- c("--effort", cfg$effort)
  if (cfg$preset == "tasks") {
    args <- c(args, "--tasks", cfg$tasks)
  } else {
    args <- c(args, "--pilot", cfg$preset)
  }
  args <- c(args, "--modes", MODES[MODES %in% cfg$modes])
  args <- c(
    args, "--repetitions", as.character(cfg$repetitions),
    "--timeout", as.character(cfg$timeout), "--instructions", cfg$instructions,
    "--function-discovery", "enabled",
    "--knowledge-pilot-scorer", cfg$scorer
  )
  args
}

#' Full process specification (command, args, working directory).
build_command <- function(cfg, runner) {
  list(
    command = runner$command,
    args = c(runner$prefix, build_args(cfg), results_args(runner)),
    wd = runner$wd
  )
}

#' `--results` is passed only when the runner spec overrides the default directory.
results_args <- function(runner) {
  if (is.null(runner$results_dir)) character() else c("--results", runner$results_dir)
}

#' Resume goes through the runner's own --resume; it restores every other setting.
build_resume_command <- function(run_dir, effort, runner) {
  list(
    command = runner$command,
    args = c(runner$prefix, "--effort", effort, "--resume", run_dir),
    wd = runner$wd
  )
}

shell_preview <- function(spec) {
  quote <- function(x) ifelse(grepl("^[A-Za-z0-9_./:=@%+-]+$", x), x, shQuote(x))
  paste(quote(c(spec$command, spec$args)), collapse = " ")
}

#' Names of required credential variables that are unset or blank (values are never read out).
missing_keys <- function(env = Sys.getenv()) {
  present <- vapply(
    KEY_VARS,
    function(name) name %in% names(env) && nzchar(trimws(env[[name]])),
    logical(1)
  )
  KEY_VARS[!present]
}

# Process wrapping ------------------------------------------------------------
#
# The runner's output goes to files instead of a pipe owned by this R process:
# if the launcher dies (terminal closed, SIGTERM, SIGKILL) a pipe would break and
# the runner's own bounded cleanup would then fail on its next print(). `exec`
# keeps the runner's pid and default signal handling (no shell in between).

EXEC_SNIPPET <- 'out=$1; err=$2; shift 2; exec "$@" >>"$out" 2>>"$err" </dev/null'

#' Wrap a command so stdout/stderr are appended to files; arguments stay positional.
wrap_command <- function(spec, out, err) {
  list(
    command = "sh",
    args = c("-c", EXEC_SNIPPET, "sh", out, err, spec$command, spec$args),
    wd = spec$wd
  )
}

# Watches the launcher. If it disappears while the runner is still alive the runner
# gets SIGINT, i.e. exactly what Ctrl+C does: its own bounded cleanup runs.
GUARD_SNIPPET <- paste(
  'while kill -0 "$1" 2>/dev/null && kill -0 "$2" 2>/dev/null; do sleep 1; done',
  'if kill -0 "$2" 2>/dev/null; then kill -INT "$2"; fi',
  sep = "\n"
)

guard_command <- function(launcher_pid, runner_pid) {
  list(command = "sh", args = c("-c", GUARD_SNIPPET, "sh", as.character(launcher_pid), as.character(runner_pid)))
}

# Incremental file reader ------------------------------------------------------

new_tail <- function(path) {
  tail <- new.env(parent = emptyenv())
  tail$path <- path
  tail$offset <- 0
  tail$partial <- ""
  tail
}

TAIL_CHUNK_BYTES <- 262144

#' New complete lines appended since the last call; `final` also flushes a last
#' line that has no newline. Control characters are removed, bytes are bounded.
read_tail <- function(tail, final = FALSE) {
  lines <- character()
  if (file.exists(tail$path)) {
    size <- file.size(tail$path)
    if (!is.na(size) && size > tail$offset) {
      con <- file(tail$path, "rb")
      on.exit(close(con), add = TRUE)
      seek(con, tail$offset)
      bytes <- readBin(con, "raw", min(size - tail$offset, TAIL_CHUNK_BYTES))
      tail$offset <- tail$offset + length(bytes)
      text <- iconv(rawToChar(bytes), "UTF-8", "UTF-8", sub = "?")
      pieces <- strsplit(paste0(tail$partial, text), "\n", fixed = TRUE)[[1]]
      complete <- endsWith(text, "\n")
      if (complete || !length(pieces)) {
        tail$partial <- ""
        lines <- pieces
      } else {
        tail$partial <- pieces[length(pieces)]
        lines <- pieces[-length(pieces)]
      }
    }
  }
  if (final && nzchar(tail$partial)) {
    lines <- c(lines, tail$partial)
    tail$partial <- ""
  }
  gsub("[[:cntrl:]]", "", lines)
}

# Parsing the runner's output -------------------------------------------------

#' Classify one stdout line. Only the documented progress formats are recognized.
parse_runner_line <- function(line) {
  m <- regmatches(line, regexec("^(\\S+): waiting: (.+) \\[([0-9.]+)s\\]$", line))[[1]]
  if (length(m)) return(list(kind = "heartbeat", trial = m[2], activity = m[3], seconds = as.numeric(m[4])))
  m <- regmatches(line, regexec("^(\\S+): (\\S+) score=(\\S+)(; error recorded)?$", line))[[1]]
  if (length(m)) {
    return(list(kind = "result", trial = m[2], status = m[3], score = m[4], error = nzchar(m[5])))
  }
  m <- regmatches(line, regexec("^(\\S+): (.+) \\[([0-9.]+)s\\]$", line))[[1]]
  if (length(m)) return(list(kind = "event", trial = m[2], activity = m[3], seconds = as.numeric(m[4])))
  m <- regmatches(line, regexec("^(?:Cleanup incomplete\\. |Interrupted\\. )?Results: (.+)$", line, perl = TRUE))[[1]]
  if (length(m)) {
    return(list(kind = "results", path = m[2], incomplete = grepl("^Cleanup incomplete", line), interrupted = grepl("^Interrupted", line)))
  }
  list(kind = "other")
}

#' Split a trial id such as "H01-A-1" or "E02-B-2-diagnostic".
parse_trial_id <- function(trial) {
  # B1: "b1-discovery-D03-R1-control" (both conditions run with MCP).
  b1 <- regmatches(trial, regexec("^b1-discovery-(.+)-R([0-9]+)-(control|treatment)$", trial, perl = TRUE))[[1]]
  if (length(b1)) {
    return(list(task = b1[2], mode = "with-mcp", repetition = as.integer(b1[3]), condition = b1[4]))
  }
  m <- regmatches(trial, regexec("^(.+)-([AB])-([0-9]+)(?:-.*)?$", trial, perl = TRUE))[[1]]
  if (!length(m)) {
    return(list(task = trial, mode = NA_character_, repetition = NA_integer_, condition = NA_character_))
  }
  list(
    task = m[2], mode = if (m[3] == "B") "with-mcp" else "without-mcp",
    repetition = as.integer(m[4]), condition = NA_character_
  )
}

# Stage shown to the user, from the runner's own labels (events and heartbeat stages).
# Unknown labels are shown as printed rather than guessed.
stage_for <- function(activity) {
  key <- sub(" \\(.*$", "", activity)
  table <- c(
    "preparing workspace" = "Preparing workspace",
    "starting Docker resources" = "Starting Docker resources",
    "creating session" = "Creating session",
    "session created" = "Session created",
    "starting Docker executor" = "Starting Docker executor",
    "Docker executor started" = "Waiting for executor",
    "executor not connected" = "Waiting for executor",
    "waiting for executor" = "Waiting for executor",
    "executor connected" = "Executor connected",
    "waiting for turn" = "Waiting for turn",
    "turn started" = "Running agent",
    "running turn" = "Running agent",
    "turn completed" = "Cleanup",
    "scoring started" = "Scoring",
    "scoring" = "Scoring",
    "scoring completed" = "Cleanup",
    "session deleted" = "Cleanup",
    "cleanup" = "Cleanup",
    "cleanup completed" = "Trial finished"
  )
  if (startsWith(key, "cleanup:")) return("Cleanup")
  if (key %in% names(table)) table[[key]] else activity
}

# Run state -------------------------------------------------------------------

new_run_state <- function(total = NA_integer_) {
  state <- new.env(parent = emptyenv())
  state$status <- "READY"
  state$total <- total
  state$done <- 0L
  state$trial_errors <- 0L
  state$trial <- NA_character_
  state$task <- NA_character_
  state$mode <- NA_character_
  state$condition <- NA_character_
  state$repetition <- NA_integer_
  state$stage <- NA_character_
  state$trial_seconds <- NA_real_
  state$executor_connected <- FALSE
  state$watchdog_seconds <- NA_real_
  state$timeout_code <- NA_character_
  state$cleanup_incomplete <- FALSE
  state$run_id <- NA_character_
  state$activity <- NA_character_
  state$results_dir <- NA_character_
  state$exit_status <- NA_integer_
  state$detail <- NA_character_
  state$stop_requested <- FALSE
  state$started <- NULL
  state$ended <- NULL
  state$stderr_lines <- 0L
  state
}

#' Fold one stdout line into the state. Nothing is inferred beyond what is printed.
apply_runner_line <- function(state, line) {
  parsed <- parse_runner_line(line)
  switch(parsed$kind,
    heartbeat = ,
    event = {
      id <- parse_trial_id(parsed$trial)
      if (!identical(state$trial, parsed$trial)) {
        # A new trial: nothing observed about the previous one carries over.
        state$executor_connected <- FALSE
        state$watchdog_seconds <- NA_real_
        state$timeout_code <- NA_character_
      }
      state$trial <- parsed$trial
      state$task <- id$task
      state$mode <- id$mode
      state$condition <- id$condition
      state$repetition <- id$repetition
      state$activity <- parsed$activity
      state$stage <- stage_for(parsed$activity)
      state$trial_seconds <- parsed$seconds
      label <- sub(" \\(.*$", "", parsed$activity)
      if (identical(label, "executor connected")) state$executor_connected <- TRUE
      # Printed by the runner's watchdog: an observation, not a timeout.
      if (identical(label, "executor not connected")) state$watchdog_seconds <- parsed$seconds
      # Only an explicit runner message may be called a connection timeout.
      if (grepl("EXECUTOR_CONNECTION_TIMEOUT", line, fixed = TRUE)) {
        state$timeout_code <- "EXECUTOR_CONNECTION_TIMEOUT"
      }
    },
    result = {
      # An interrupted trial did not finish; every other printed result is a finished trial.
      if (!identical(parsed$status, "interrupted")) {
        state$done <- state$done + 1L
        if (!parsed$status %in% SUCCESS_STATUSES || parsed$error) {
          state$trial_errors <- state$trial_errors + 1L
        }
      }
      state$activity <- paste0(parsed$trial, " finished: ", parsed$status, " score=", parsed$score)
    },
    results = {
      state$results_dir <- parsed$path
      if (parsed$incomplete) state$cleanup_incomplete <- TRUE
    }
  )
  if (grepl("EXECUTOR_CONNECTION_TIMEOUT", line, fixed = TRUE) && parsed$kind %in% c("result", "results", "other")) {
    state$timeout_code <- "EXECUTOR_CONNECTION_TIMEOUT"
  }
  invisible(parsed)
}

#' Final status from the process outcome. `status` is NA when killed by a signal.
finish_run <- function(state, exit_status, now = Sys.time()) {
  state$ended <- now
  state$exit_status <- exit_status
  state$status <- if (!is.na(exit_status) && exit_status == 0L) {
    "COMPLETED"
  } else if (state$stop_requested || (!is.na(exit_status) && exit_status == 130L)) {
    "INTERRUPTED"
  } else {
    "FAILED"
  }
  state$detail <- if (is.na(exit_status)) {
    "runner ended without an exit status"
  } else if (exit_status < 0) {
    # termr reports a process killed by a signal as the negative signal number.
    paste("runner was killed by signal", -exit_status)
  } else if (state$status == "COMPLETED") {
    NA_character_
  } else if (state$status == "INTERRUPTED") {
    "stopped before all trials finished"
  } else if (exit_status %in% c(126L, 127L)) {
    paste("runner exited with status", exit_status, "(usually: command not found or not executable)")
  } else {
    paste("runner exited with status", exit_status)
  }
  if (isTRUE(state$cleanup_incomplete)) {
    state$detail <- paste0(
      if (is.na(state$detail)) "" else paste0(state$detail, "; "),
      "CLEANUP INCOMPLETE: sessions or Docker resources may remain (docker ps -a); nothing was deleted"
    )
  }
  invisible(state)
}

format_elapsed <- function(seconds) {
  seconds <- max(0, floor(as.numeric(seconds)))
  sprintf("%02d:%02d:%02d", seconds %/% 3600, (seconds %% 3600) %/% 60, seconds %% 60)
}

elapsed_seconds <- function(state, now = Sys.time()) {
  if (is.null(state$started)) return(0)
  as.numeric(difftime(state$ended %||% now, state$started, units = "secs"))
}

progress_text <- function(state) {
  total <- if (is.na(state$total)) "?" else as.character(state$total)
  text <- sprintf("%d/%s trials finished", state$done, total)
  if (state$trial_errors > 0) text <- paste0(text, sprintf(" (%d with errors)", state$trial_errors))
  text
}

# Runs, resume and results ------------------------------------------------------
# Facts come from runner_info.py (which uses the runner's own resume validation);
# anything it cannot establish stays "unknown".

RUN_FIELDS <- c("run_id", "experiment", "created", "effort", "total", "recorded", "status", "cleanup", "resume")
RUN_ID_PATTERN <- "^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$"

#' Parse the tab separated lines of `runner_info.py runs`.
parse_runs <- function(lines) {
  lines <- lines[nzchar(lines)]
  lapply(lines, function(line) {
    parts <- strsplit(line, "\t", fixed = TRUE)[[1]]
    parts <- c(parts, rep("unknown", max(0, length(RUN_FIELDS) - length(parts))))
    stats::setNames(as.list(parts[seq_along(RUN_FIELDS)]), RUN_FIELDS)
  })
}

list_runs <- function(runner, results_dir, limit = 10) {
  out <- run_info(runner, c("runs", "--results", results_dir, "--limit", as.character(limit)))
  if (is.null(out)) return(NULL)
  parse_runs(out)
}

resume_allowed <- function(run) identical(run$resume, "ok") && !identical(run$status, "finished")

#' One line per run for the selection list.
run_label <- function(run) {
  sprintf(
    "%-25s %-12s %-11s %3s/%-3s cl:%-10s rs:%s",
    run$run_id, run$experiment, run$status, run$recorded, run$total,
    run$cleanup, if (identical(run$resume, "ok")) "ok" else "blocked"
  )
}

#' Warnings shown before a run is resumed. Nothing here is a claim of safety.
resume_warnings <- function(run) {
  warnings <- character()
  if (!identical(run$resume, "ok")) {
    warnings <- c(warnings, paste("The runner refuses to resume this run:", sub("^blocked: ", "", run$resume)))
  }
  if (identical(run$status, "interrupted")) {
    warnings <- c(warnings, paste(
      "This run was interrupted. The runner counts recorded trials, including interrupted ones,",
      "as done and does not repeat them."
    ))
  }
  if (identical(run$cleanup, "incomplete")) {
    warnings <- c(warnings, paste(
      "Cleanup was incomplete: the remote session may still exist and Docker containers or",
      "networks may remain (docker ps -a). The launcher never deletes them."
    ))
  }
  if (identical(run$cleanup, "unknown") || identical(run$status, "unknown")) {
    warnings <- c(warnings, "Run state is not fully recorded (unknown); its remote state was not checked.")
  }
  warnings
}

#' Parse `runner_info.py summary` lines: trial, condition, task, status, score, cleanup.
parse_summary <- function(lines) {
  lines <- lines[nzchar(lines)]
  lapply(lines, function(line) {
    p <- strsplit(line, "\t", fixed = TRUE)[[1]]
    p <- c(p, rep("", max(0, 6 - length(p))))
    list(trial = p[1], condition = p[2], task = p[3], status = p[4], score = p[5], cleanup = p[6])
  })
}

run_summary <- function(runner, run_dir) {
  out <- run_info(runner, c("summary", "--run", run_dir))
  if (is.null(out)) NULL else parse_summary(out)
}

#' Text for the results view. B1 shows Control/Treatment; no delta is computed here:
#' scoring stays with the runner and the analytics module.
summary_lines <- function(run, trials) {
  if (!length(trials)) return("No trial results are recorded in this run.")
  b1 <- identical(run$experiment, "b1-discovery")
  lines <- vapply(trials, function(t) {
    sprintf("%-34s %-9s %-12s score %-7s cleanup %s", t$trial,
      if (b1) t$condition else t$task, t$status, t$score, t$cleanup)
  }, "")
  scored <- Filter(function(t) !identical(t$score, "none"), trials)
  note <- if (b1) {
    conditions <- vapply(scored, function(t) t$condition, "")
    if (all(c("control", "treatment") %in% conditions)) {
      "Control and Treatment both have recorded scores; compare them in the analytics dashboard."
    } else {
      "No Control/Treatment comparison: scores are missing for at least one condition (no delta shown)."
    }
  } else if (!length(scored)) {
    "No recorded scores in this run."
  } else NULL
  c(lines, note)
}

#' Run directories currently present (to find the one a new launch creates).
run_dirs <- function(results_dir) {
  if (!dir.exists(results_dir)) return(character())
  dirs <- list.dirs(results_dir, full.names = FALSE, recursive = FALSE)
  dirs[grepl(RUN_ID_PATTERN, dirs)]
}
