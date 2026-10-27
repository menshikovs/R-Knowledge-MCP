library(termr)

launcher_dir <- normalizePath(file.path(getwd(), "..", ".."))
source(file.path(launcher_dir, "launcher_core.R"))
source(file.path(launcher_dir, "launcher_app.R"))

FAKE_CATALOG <- list(
  r = sprintf("R%02d", 1:12), hard = c("H01", "H04", "H10"),
  knowledge = c("B01", "B02", "C01", "D01", "E01"),
  tool_value = c("B01", "B02", "C01", "D01", "E01"),
  full = c("H01", "H04", "H10", "B01", "B02", "C01", "D01", "E01"),
  instructions = c("diagnostic", "standard"), smoke = "mcp-smoke",
  b1_tasks = c("D03", "D01", "C01"), b1_repetitions = "2",
  # copied from the real planner's output (see runner_info.py catalog)
  b1_order = c("D03:1:control", "D03:1:treatment", "D01:1:treatment", "D01:1:control",
    "C01:1:control", "C01:1:treatment", "D03:2:treatment", "D03:2:control",
    "D01:2:control", "D01:2:treatment", "C01:2:treatment", "C01:2:control"),
  b1_scorers = c("D03:knowledge-pilot-v2", "D01:knowledge-pilot-v2", "C01:legacy"),
  results_dir = "/nonexistent-results"
)

python_bin <- function() {
  Sys.which(Sys.getenv("BENCH_TEST_PYTHON", "python3"))[[1]]
}

fake_runner <- function() {
  list(
    command = python_bin(),
    prefix = file.path(launcher_dir, "tests", "fake_runner.py"),
    wd = tempdir(), require_keys = FALSE, results_dir = tempfile("results-"),
    info_script = file.path(launcher_dir, "runner_info.py"),
    info_command = info_python(), info_wd = repo_root()
  )
}

repo_root <- function() normalizePath(file.path(launcher_dir, "..", "..", ".."))

# The info helper imports the real runner, so it needs the repository's virtualenv.
info_python <- function() {
  venv <- file.path(repo_root(), ".venv-wsl", "bin", "python")
  if (file.exists(venv)) venv else ""
}

skip_without_info <- function() {
  testthat::skip_if(!nzchar(info_python()), "needs .venv-wsl for the runner's own planner/resume code")
}

skip_without_python <- function() {
  testthat::skip_if(!nzchar(python_bin()), "python3 not available")
}

new_pilot <- function(runner = fake_runner(), ...) {
  dir.create(runner$results_dir %||% tempdir(), showWarnings = FALSE)
  l <- launcher_app(FAKE_CATALOG, runner, ...)
  pilot <- test_app(l$app, width = 100, height = 30)
  pilot$step()
  list(pilot = pilot, session = l$session, app = l$app)
}

wait_status <- function(h, status, timeout = 15) {
  h$pilot$wait_for(function(app) h$session$run$status %in% status, timeout = timeout)
}

# wait_for() refuses to start once the app has exited, so poll with step() instead.
wait_exit <- function(h, timeout = 15) {
  deadline <- Sys.time() + timeout
  while (!h$pilot$exited && Sys.time() < deadline) {
    h$pilot$step()
    Sys.sleep(0.05)
  }
  h$pilot$exited
}
