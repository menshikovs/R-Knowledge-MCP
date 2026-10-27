# Benchmark launcher (termr front end)

A terminal UI to configure, start, resume, watch and stop runs of
`benchmarks/codex_r/run_simple.py`, including the B1 MCP discovery experiment. The
Python runner stays authoritative: the launcher builds its command line, runs it as a
child process and shows what it prints. It scores nothing, deletes nothing and has no
benchmark logic of its own. Task ids, the B1 plan and per-task scorers are read from
the runner at startup, and resume validation is the runner's own `load_resume_records`
(through the read-only helper `runner_info.py`).

## Install and start

Ubuntu WSL, from the repository root, in the shell that exports
`OPENAI_API_KEY` and `OPENAI_EXECUTOR_API_KEY` (the launcher only checks that they
are set, never prints them):

```sh
Rscript -e 'install.packages("termr")'   # CRAN release, tested with 1.0.1
scripts/bench-tui
```

It uses `.venv-wsl/bin/python`; set `BENCH_PYTHON` to use another interpreter.

## Standard benchmark

`Experiment (•) standard`: tasks (ids, `tool-value` or `full`), modes `without-mcp` /
`with-mcp`, effort, repeats, timeout, instructions and scorer, exactly as before. Plan:
tasks × modes × repetitions.

The scorer selector mirrors the runner choices: `legacy`, `knowledge-pilot-v2` and
`knowledge-pilot-v2.1`. V2.1 is valid only when the selected tasks are D01 and/or D03;
the launcher blocks other task combinations before building a command. B1 Discovery
continues to use its fixed V2/legacy task-scoped scorers.

Standard TUI commands explicitly pass `--function-discovery enabled`. The runner also
accepts `--function-discovery disabled` for a separately controlled discovery-off run;
B1 keeps its frozen pre-discovery allow-list and does not inherit the standard policy.

## B1 Discovery

`Experiment (•) b1-discovery` runs the existing `--experiment b1-discovery`:

* Control and Treatment, both with MCP (so there are no without/with-MCP groups).
  Control/Treatment descriptions and digests are untouched; they live in the runner.
* Tasks `D03 D01 C01`, 2 repetitions, scorer `knowledge-pilot-v2` as the runner
  requires. You may change effort and timeout; edited tasks or repetitions that the
  runner would reject are reported and block the start.
* Scorer per task as the runner resolves it: D03 and D01 use V2, C01 uses `legacy`
  (it has no V2 contract). The launcher shows this and never marks C01 as V2.
* Images passed explicitly and shown: `rkmcp-codex-runtime:codex-0.163.0-bioc`,
  `codex-r-benchmark:pilot-bioc`, `cran-knowledge-mcp:shiny-quarto`.
* Plan `3 tasks x 2 conditions x 2 repeats = 12 trials` plus the runner's order
  (`D03-R1 C>T  D01-R1 T>C ...`). The launcher does not reorder anything.

Command line (shown before the run, no secrets in it):

```text
python -m benchmarks.codex_r.run_simple --effort medium --experiment b1-discovery \
  --tasks D03 D01 C01 --repetitions 2 --timeout 900 \
  --knowledge-pilot-scorer knowledge-pilot-v2 --executor-image ... --scorer-image ... --mcp-image ...
```

The process is started as an argument vector without a shell.

## Keys

| Key | Action |
|---|---|
| F2 | Open the task picker; task IDs are shown directly, Enter adds multiple IDs, and Esc returns to the configuration |
| Tab / Shift+Tab | next / previous control; arrows and Space/Enter change radios and checkboxes |
| F5 | run (only when the configuration is valid) |
| F6 | resume: choose a recent run, confirm |
| F7 | results: choose a recent run, see its trials |
| Ctrl+X | stop: sends SIGINT, the runner runs its own bounded cleanup |
| Ctrl+X again | confirm dialog for a force kill (may leave Docker resources behind) |
| Esc | back to the configuration (not while running) |
| Ctrl+C, F10 | quit; while running: confirm, stop gracefully, exit when cleanup is done |
| F1, Ctrl+P | termr help and command palette |

## Resume (F6)

Lists the newest runs of the results directory with experiment, recorded/total
trials, status, cleanup state and whether the runner accepts a resume. Selecting one
asks for confirmation and then runs `run_simple --effort <saved effort> --resume
<run dir>`; the runner restores everything else, does not repeat recorded trials and
refuses incompatible or ambiguous runs (shown as `blocked`, with its message).
Fields that are not recorded are `unknown`; nothing is guessed.

Read this before resuming an interrupted run: the runner counts every recorded trial,
including an interrupted one, as done. A run with `cl:incomplete` may still have a
remote session and Docker containers or networks (`docker ps -a`); the launcher warns
about this and never deletes them. For `20261026T063640Z-e23efc9e` (no manifest) and
`20261026T063723Z-c849c1af` (interrupted, cleanup incomplete) check the remote state
first.

## Results (F7)

For the chosen run: path, experiment, creation time, effort, status and one line per
recorded trial (B1 shows Control/Treatment). No score or delta is computed here; if
scores are missing it says so. Use `benchmarks/codex_r/analytics/README.md` for the
analytics dashboard.

## Live progress

Run id (detected from the new results directory), trial, task, condition or mode,
repetition, stage, trial time, finished trials out of the runner's plan, elapsed time
and the last runner event. Stages come from the runner's own progress labels (stdout
format covered by a contract test against the real `Progress` class); an unknown label
is shown as printed. "Executor" is `connected` only after the runner printed
`executor connected`. If the runner's watchdog printed `executor not connected` the
line says so with its time, as an observation, not a timeout.
`EXECUTOR_CONNECTION_TIMEOUT` is shown only if the runner itself prints that text. The
launcher draws no conclusion about DNS, Docker or the Agents API. MCP is shown as on
for trials that run with MCP, because it is started before the session is created; it
is not probed separately.

## Stopping and Ctrl+C

The first stop sends SIGINT (what Ctrl+C does) and shows `STOPPING` while the runner
cleans up. Quit during a run asks, stops gracefully and exits only afterwards. A
second Ctrl+X asks before a force kill. The final state is never `COMPLETED` unless
the runner exited with status 0; a runner that reported `Cleanup incomplete` is shown
with a CLEANUP INCOMPLETE warning and the results path. Nothing is retried.

## Process safety

* Arguments are positional (`sh -c 'exec "$@"'`), so ids and options are never
  interpreted by a shell.
* The runner's stdout/stderr go to files in `launcher/logs/` (git-ignored), not a pipe
  owned by R, so its cleanup does not fail if the launcher dies.
* A small guard sends SIGINT to the runner if the launcher is killed (SIGTERM, SIGHUP,
  SIGKILL). Verified on a real PTY with the fake runner, not with real Docker.
* termr's `app$exit()` / `Worker$cancel()` kill a worker after 0.3 s, so the launcher
  never exits that way while a run is active.

## Tests

```sh
.venv-wsl/bin/python -m pytest tests/test_codex_launcher.py   # needs R + termr + testthat
```

testthat suites (`tests/testthat`): configuration, command building, B1, parsing,
progress, resume and results with synthetic run directories, headless UI with the
harmless `tests/fake_runner.py`. pytest additionally checks that the generated
command lines pass the real runner's argument validation, that the B1 plan and scorers
equal the runner's planner output, the run index on synthetic fixtures, and drives the
real terminal through a PTY (`tests/pty_drive.py`). No Docker, network or paid trial
is involved.

## Limitations

* The executor connection hang seen in the first real B1 attempts is not solved by
  the launcher; it only shows what the runner observed.
* Run listings use the newest 10 directories; progress depends on the runner's stdout
  labels (stable here, but a format change in `run_simple.py` would need a matching
  update; the contract test catches it).
* Custom image names, result directories and `mcp-discovery` are CLI-only.
* Tested on a pseudo-terminal and headless; not on Windows Terminal, tmux or ssh.
