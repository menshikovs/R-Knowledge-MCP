# Prepared pull request description

Adds a reproducible 12-task pilot for independently measuring whether R Knowledge MCP improves Codex's R code correctness, reliability or efficiency. Production MCP behavior and dependencies are unchanged.

**No comparative agent execution results are available yet.** This PR contains infrastructure and actual oracle/interface self-test evidence, not measured agent improvement. Zero Codex candidate sessions, zero completed comparative trials and no model cost/token/savings claims.

### Experimental design
- A: baseline, no MCP. B: 15 explicitly allowlisted core tools. C: the same core plus five public Prompt Intelligence tools; optional PI use is preregistered.
- R01–R12 cover base R, dplyr, malformed readr CSV, ggplot2, tidyr, DBI/RSQLite, safe SQL, Shiny reactivity, modules, Quarto, pinned Bioconductor IRanges and a composed reporting workflow.
- Default 72-run blocked/randomized plan (12 × 3 × 2; seed 1729), explicit identical model/reasoning/image/budgets, independent fresh sessions, no ordinary browsing or timed package installation.
- Four equally weighted hidden test groups per task, full success at 4/4, candidate failures at zero, infrastructure failures as disclosed missing data. Per-task/condition summaries and paired task-cluster bootstrap intervals.

### Reproducibility and boundaries
- Verified latest main base: edab824, containing merged stabilization PRs #3–#7 with green CI.
- Actual 89-record renv lock: R 4.5.2 / Bioconductor 3.22 / IRanges 2.44.0; Quarto 1.8.27 and a digest-pinned R base image.
- Public workspace export excludes hidden assertions, reference solutions and other conditions. Actual networkless candidate R-container probe confirms no oracle/repository/Docker socket mount.
- Safe sealed artifact import, readonly scorer mounts, CPU/memory/process/tmpfs/time/output bounds and forced container cleanup.
- Benchmark-only public stdio MCP gateway enforces list and call filtering, records complete actual results/provenance/PI responses and checks evaluated production-source hashes.
- External-run import, result schema, actual CLI-usage parsing and reproducible reporting; mock records exist only in unit tests.

### Actual validation
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- Full `pytest`: **283 passed**, including 28 new infrastructure cases. Unmodified Windows tests ran with temp/named-pipe access outside the restrictive sandbox; no deselection or weakened assertions.
- R parsed all 18 benchmark R files.
- Pinned Linux image: all 12 trusted references passed all **48/48** groups; all 12 semantic mutants failed full-task success, including actual offline Quarto rendering.
- Actual MCP stdio probes: B exposes 15 tools and denies the offline PI template call; C exposes 20 and allows it. No upstream network tool calls or agent sessions.
- Evidence: `benchmarks/codex_r/reports/`. Methodology: `docs/CODEX_MCP_BENCHMARK.md`.

### Remaining execution requirements
Codex CLI capability was inspected, but a fully isolated authenticated external agent controller and uniform hard token/cost enforcement were not verified. The provided offline R shell is explicitly not an invented Codex runner. External isolation attestations cannot be proved by importing a JSON record; no blinded agent experiment is claimed. The post-agent unit-test scorer is not tamper-proof against deliberately adversarial R code.

Next: provision/audit that controller, authorize and preregister an exact model configuration, run the randomized 72 assignments, independently audit API/safety/repair metrics and publish raw synthetic-task evidence plus paired results. Null and negative outcomes are valid. Do not merge or deploy as part of this task.
