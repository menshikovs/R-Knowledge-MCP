# Runs the real launcher UI against the fake runner on a real terminal (used by pty tests).
here <- dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])))
launcher_dir <- normalizePath(file.path(here, ".."))
source(file.path(launcher_dir, "launcher_core.R"))
source(file.path(launcher_dir, "launcher_app.R"))
catalog <- list(
  r = sprintf("R%02d", 1:12), hard = c("H01", "H04", "H10"), knowledge = c("B01", "D01"),
  tool_value = c("B01", "D01"), full = c("H01", "B01", "D01"),
  instructions = c("diagnostic", "standard"), smoke = "mcp-smoke",
  b1_tasks = c("D03", "D01", "C01"), b1_repetitions = "2",
  b1_order = c("D03:1:control", "D03:1:treatment"), b1_scorers = c("D03:knowledge-pilot-v2", "C01:legacy"),
  results_dir = tempdir()
)
runner <- list(
  command = Sys.which("python3")[[1]], prefix = file.path(here, "fake_runner.py"),
  wd = tempdir(), require_keys = FALSE, results_dir = tempdir()
)
invisible(termr::run(launcher_app(catalog, runner)$app))
cat("LAUNCHER-EXITED\n")
