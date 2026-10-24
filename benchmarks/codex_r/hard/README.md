# R-Knowledge-MCP Hard Benchmark v1 — pilot

Implements the pilot of `R_Knowledge_MCP_Hard_Benchmark_v1.md`: **H01, H04, H10**.
The other seven specified tasks are **not implemented**.

| Task | Topic | Hidden checks | Packages |
| --- | --- | --- | --- |
| H01 | Dynamic weighted group summaries (literal names, `.data`/`.env` collisions, grouping, NA/NaN, integer overflow) | 18 | dplyr 1.2.1, rlang 1.3.0, tibble 3.3.1 |
| H04 | Point-in-time quote matching (rolling join, ties, staleness, DST instants, 100k × 100k in 30 s) | 17 | dplyr 1.2.1, tibble 3.3.1 |
| H10 | Rubin's rules pooling (Rubin 1987 and Barnard–Rubin 1999 df, zero-variance limits, underflow/overflow) | 18 | base R |

**H04 is a documented substitute.** The specification targets data.table, which is
not installed in the pinned executor or scorer image (both: R 4.5.2; data.table,
lubridate, clock, broom, dbplyr, httr2 and curl absent — inspected 2026-10-24). The
task keeps the same as-of semantics with dplyr's `join_by(closest())`; see
`tasks/H04/metadata.json`.

## Layout

- `tasks/Hxx/prompt.md`, `tasks/Hxx/fixture/` — the only files an agent sees
  (exported to `TASK.md`, `renv.lock` and `data/` in a fresh workspace outside the
  repository). `tasks/Hxx/metadata.json` (source, versions, difficulty hypothesis,
  expected MCP relevance) is never exported.
- `verifier/` — hidden: `run.R` entry point, `harness.R`, `Hxx.R` checks with an
  independent oracle, and `controls/Hxx/` (trusted reference plus deliberately wrong
  strategies). It is mounted read-only into the networkless scorer only after the
  agent session and executor container are gone.
- `suite.py` — registry, export, artifact sealing and scoring with the same
  interface as `runner/bench.py`; `selftest.py` — offline verifier validation.

## Scoring

Each `check()` is one named behavioral check on real outputs of the candidate's
functions. The primary metric is `fully_correct` (all checks pass); `passed/total`
is secondary. Candidate code is sourced into a separate `callr::r_session`; all
comparisons run in the verifier process on returned values, so a solution cannot
redefine expectations or base functions, and anything it prints cannot forge the
`BENCH_RESULT` line. A hang in one call restarts the candidate process for the
remaining checks. `scoring_error` (environment preflight or verifier fault) is
reported with `passed = null` and `fully_correct = null`, never as a candidate
failure; candidate errors and timeouts score 0.

## Offline validation (done, no API calls)

```sh
python -m benchmarks.codex_r.hard.selftest          # all tasks, ~3 minutes
pytest tests/test_codex_hard.py                     # unit tests; -m docker runs the gate too
```

The gate requires: the reference passes every check twice with identical results;
at least two wrong strategies exist and every one is rejected; an empty solution
passes **zero** checks (no vacuous checks); a syntax error is a candidate error; a
forged result line does not change the score. The H10 oracle is also validated
against exact rational values every time the verifier loads. Results are in
`reports/offline-validation.json`. On 2026-10-24 the gate passed for all three
tasks (Docker Desktop engine from the Windows host; the same images serve WSL2).
The checks also caught two bugs in the first H01 reference (a `.data` column
breaking `dplyr::pick()`, and `ifelse()` returning logical for empty input).

## Paired pilot (paid; not run)

From Ubuntu/WSL2 with `OPENAI_API_KEY` and `OPENAI_EXECUTOR_API_KEY` exported:

```sh
python -m benchmarks.codex_r.run_simple --effort medium --tasks hard-pilot
```

This runs H01, H04 and H10 once each in `without-mcp` and `with-mcp` (6 trials),
model `gpt-6-luna`, the same images, prompts and 900 s limit. In `with-mcp` the
server runs the current `src` with `MCP_TOOLSET=consolidated` and exposes the 12
knowledge tools listed in `manifest.json` (prompt-construction tools excluded, as
in condition B). Results go to `benchmarks/codex_r/results/<UTC>-<id>/`:
`results.json`, `results.csv` and one directory per trial with `result.json`,
`events.json` and the sealed `artifacts/`. Each record keeps `fully_correct`,
`score.passed/total/failed_checks`, `duration_seconds`, `agent_seconds`,
`mcp_usage` (calls and tool names actually observed in session events),
`usage`/`cost` with `usage_status`/`cost_status` (`unavailable` and `null` when the
API reports nothing — earlier R01/R02 sessions reported no usage), and
`environment_versions` (R and package versions from the scorer). Every invocation
writes a new results directory; completed trials are never re-run automatically.
The original R01..R12 suite keeps `MCP_TOOLSET=legacy`.

Do not treat three pairs as statistically meaningful. If the `without-mcp` arm is
fully correct on all three tasks, replace or harden tasks before wider spending.
