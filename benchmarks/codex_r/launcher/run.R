#!/usr/bin/env Rscript
# Entry point: Rscript benchmarks/codex_r/launcher/run.R   (or scripts/bench-tui)
args <- commandArgs(FALSE)
here <- dirname(normalizePath(sub("^--file=", "", args[grepl("^--file=", args)][1])))
root <- normalizePath(file.path(here, "..", "..", ".."))

if (!requireNamespace("termr", quietly = TRUE)) {
  stop("The R package 'termr' is required: install.packages(\"termr\")", call. = FALSE)
}
source(file.path(here, "launcher_core.R"))
source(file.path(here, "launcher_app.R"))

python <- Sys.getenv("BENCH_PYTHON", file.path(root, ".venv-wsl", "bin", "python"))
if (!file.exists(python)) {
  stop("Python not found at ", python, ". Create .venv-wsl or set BENCH_PYTHON.", call. = FALSE)
}
runner <- list(
  command = python,
  prefix = c("-m", "benchmarks.codex_r.run_simple"),
  wd = root,
  require_keys = TRUE,
  info_script = file.path(here, "runner_info.py")
)
catalog <- load_catalog(runner)
launcher <- launcher_app(catalog, runner, log_dir = file.path(here, "logs"))
invisible(termr::run(launcher$app))
