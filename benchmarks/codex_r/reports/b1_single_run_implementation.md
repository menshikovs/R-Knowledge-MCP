# B1 single-run MCP discovery experiment

## Implementation

`benchmarks.codex_r.run_simple --experiment b1-discovery` builds one run manifest and one deterministic 12-trial plan. It uses the existing runner, executor, scorer, telemetry and result files. The plan contains D03, D01 and C01 at repetitions 1 and 2, with one Control and one Treatment trial per task/repetition pair. There are six trials per condition. First condition is balanced: Control runs first for three pairs and Treatment runs first for three. Trials execute sequentially, each with an isolated MCP container configured for its planned condition.

Trial IDs include the experiment, task, repetition and condition. Each saved trial includes its actual execution order, condition, model/effort, task-specific scorer identity and digest, task manifest/prompt/instructions digests, Docker image IDs and condition-specific MCP description/interface digests. `b1_comparison.json` is rewritten incrementally after results are saved; incomplete pairs remain present and are not assigned a score delta. Scores are compared only within each task/repetition pair and same scorer; there is no pooled score across scorer versions.

## Conditions and delivery

Control uses the existing FastMCP server instructions byte-for-byte. Treatment uses a server-level description explaining when read-only MCP tools can help with R package discovery, CRAN/Bioconductor metadata and releases, current versions, supported dependency facts, compatibility, official documentation and Rd aliases. It distinguishes repository versions from client-supplied installed versions, notes metadata cannot establish successful installation, and says MCP is optional and should not be called for every task or repeated without reason. It does not modify common agent instructions, individual tool descriptions or schemas, nor require MCP use.

The runner passes `RKMCP_BENCH_MCP_DISCOVERY_VARIANT` to each condition's MCP container. FastMCP exposes the selected text in `InitializeResult.instructions`. Offline tests initialize the existing MCP client and assert the returned instructions match each variant. The Codex 0.163.0 MCP client maps server instructions into the MCP namespace description (`codex-rs/codex-mcp/src/rmcp_client.rs`, `server_instructions` handling). Tests assert that Control and Treatment have different description SHA-256 values while advertised toolset, schemas, individual tool descriptions and the complete advertised interface have identical digests. Common agent instruction digests are also the same.

## Scoring

The explicit B1 scorer selection is `knowledge-pilot-v2`. D03 and D01 use that scorer. C01 currently has no supported V2 output contract, so its paired trials use the existing legacy scorer, recorded as `scorer_identity=legacy` with its own digest. The runner rejects B1 if a different global scorer is requested; it does not label C01 as V2 or compare C01 scores against D-task scores. Resume validates the saved task-specific scorer mapping and digests.

## Resume and analytics

`--resume RUN_DIRECTORY` uses the saved plan and execution orders. Finalized trials are retained and skipped; a trial directory without a final result is treated as an unknown outcome and is not automatically retried. Resume compares the saved experiment manifest—including condition descriptions, interface digests, task/prompt/scorer inputs and image identities—with the current configuration before continuing.

Without `--experiment`, omitted CLI arguments are normalized to their previous defaults (legacy scorer, both MCP modes and standard instructions). Existing non-B1 invocation behavior is preserved.

The existing Analytics Dashboard v2 importer/schema/queries now retain `experiment_id`, `experiment_version`, condition and execution order. B1 conditions remain explicitly `control` and `treatment`, while `mode=with-mcp` continues to describe MCP availability. Pairing is by run, task, repetition and condition. Dashboard summaries report task-local score deltas and condition-separated adoption/call, tool, application error, `docs_not_found`, repeat, duration and available usage/cost metrics. Missing measurements stay null. Legacy A/B data keeps its existing mode interpretation.

## WSL command

Run once from the repository root in WSL. It makes one run ID and plans all 12 trials; it does not invoke B2. The default MCP image is stated explicitly here for reproducibility:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple \
  --effort medium \
  --experiment b1-discovery \
  --tasks D03 D01 C01 \
  --repetitions 2 \
  --knowledge-pilot-scorer knowledge-pilot-v2 \
  --executor-image rkmcp-codex-runtime:codex-0.163.0-bioc \
  --scorer-image codex-r-benchmark:pilot-bioc \
  --mcp-image cran-knowledge-mcp:shiny-quarto
```

## Offline validation and limits

- Targeted B1/resume/analytics/diagnostics checks: 26 passed, 14 deselected.
- Full `test_mcp_discovery.py`, `test_codex_simple_resume.py` and `test_benchmark_analytics.py`: 49 passed.
- `ruff check .`: passed (Ruff emitted access-denied warnings while walking pre-existing protected temporary directories).
- `ruff format --check .`: Ruff panicked while walking protected temporary artifacts. Running `ruff format --check` against the 141 Python files listed by Git completed successfully: all were already formatted.
- `run_simple --help`: passed and lists `--experiment {b1-discovery}` and all existing CLI options.
- Windows full pytest: 1264 passed, 89 failed, 58 skipped. This host is Windows/Python 3.14, while a number of existing tests require Linux signal, filesystem, Docker or durable-private-state behavior. Representative failures reject Windows because the runner requires Linux/WSL or because the test requires Linux filesystem semantics. The WSL invocation could not be run here: the available Docker Desktop WSL environment has no `/usr/bin/python3`, and WSL distribution enumeration is denied by the host. The full Linux suite therefore remains to be run in the user's WSL environment.

No paid model/API trial or benchmark session was started. No B2 run or historical baseline file was changed.
