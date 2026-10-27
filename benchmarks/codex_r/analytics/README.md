# Local benchmark analytics

Python + DuckDB + Streamlit; no benchmark execution or API credentials are needed.
Run commands from the repository root. Install the optional dependencies once:

```sh
uv pip install --python .venv-wsl/bin/python -e ".[analytics]"
```

Windows equivalent: `uv pip install --python .venv/Scripts/python.exe -e ".[analytics]"`.
Use `.venv/Scripts/python.exe` instead of `.venv-wsl/bin/python` below on Windows.
The dashboard requires Streamlit 1.55 or newer for lazy tab rendering.

## Import, update and rebuild

```sh
# Discover saved runs; update the derived database atomically per run.
.venv-wsl/bin/python -m benchmarks.codex_r.analytics.import_results

# Import a chosen set of saved Run IDs only.
.venv-wsl/bin/python -m benchmarks.codex_r.analytics.import_results --runs 20261025T083653Z-ca1d5503 20261025T100159Z-a939d94f 20261025T100740Z-9746f577

# Rebuild derived tables from the files. No source file is modified.
.venv-wsl/bin/python -m benchmarks.codex_r.analytics.import_results --rebuild

# Local dashboard: http://127.0.0.1:8501
.venv-wsl/bin/python -m benchmarks.codex_r.analytics.dashboard
```

The default database is `benchmarks/codex_r/analytics.duckdb` (ignored by Git).
`--database PATH`, `--results PATH` and importer `--reports PATH` support other local
locations. A database inside the source results directory is refused.
The importer is an explicit command: no watcher or background service is installed.
Re-run it after new trials finish, then refresh the dashboard. DuckDB takes a write
lock during import; if an active dashboard request holds a read lock in another
process, finish that request or stop the dashboard and retry the importer.

The launcher fixes `server.address=127.0.0.1`, disables Streamlit usage statistics
and file watching, and does not open a browser automatically. The equivalent
direct Streamlit command is:

```sh
.venv-wsl/bin/python -m streamlit run benchmarks/codex_r/analytics/dashboard.py --server.address=127.0.0.1 --server.headless=true --server.fileWatcherType=none --browser.gatherUsageStats=false
```

## Files and schema

| Module | Purpose |
| --- | --- |
| `schema.sql` | Version 6 derived schema with additive migrations |
| `import_results.py` | Bounded, idempotent import and stable per-run transactions |
| `safety.py` | Identifier projections, numeric/null handling, path confinement and redaction |
| `queries.py` | Parameterized SQL, A/B pairing, CSV/Markdown exports and artifact previews |
| `dashboard.py` | Six read-only Streamlit views, including P2 trace and opportunity analysis |

B1 rows retain `mode=with-mcp` and also store their explicit `condition` and
execution order. The importer validates the balanced pair plan. Dashboard score
comparisons stay within each task/scorer pair; condition-specific MCP telemetry
uses trial-level observations and does not attribute run-only V2 projections.

| Table | Key and logical relationships | Stored facts |
| --- | --- | --- |
| `runs` | `run_id` | Completion/import state, model, configuration provenance, Git/source/image fingerprints, tool catalogs, package pins, schema and source fingerprint |
| `run_metadata` | `run_id` -> runs | Explicit timestamp, suite/task/condition/repetition plan, scorer/prompt/environment metadata, verified full-scope status and reason |
| `trial_plan` | `(run_id, planned_trial_id)` -> runs | Expected task, condition, repetition and optional task input hash; compared with observed trial identities |
| `trials` | `(run_id, trial_id)` -> runs | Task/block/condition/repetition, scorer, original score/failed checks, duration, discovery/call counts, metrics provenance, cleanup, observed API tokens and cost |
| `score_checks` | `(run_id, trial_id, scoring_id, check_name)` -> trials/revisions | Only check identifiers and known pass/fail; no hidden test code |
| `score_dimensions` | `(run_id, trial_id, scoring_id, dimension)` -> trials/revisions | Safe allowlisted scorer dimensions; original and each report revision remain separate |
| `mcp_calls` | `(run_id, trial_id, observation_source, call_id)` -> trials | Separate client/server/legacy observations, outcome, bytes, approximate MCP tokens, latency, partial/truncation, verification, repeats, cache and correlation status |
| `mcp_observations_v2` | `(run_id, observation_id)` -> runs | Safe V2 request/response projections without trial/task identity; never joined by row order |
| `events` | `(run_id, event_id)` -> runs and optional trials | Stable content-hash IDs; closed lifecycle fields and classified errors |
| `agent_telemetry` | `(run_id, event_id)` -> runs and optional trials | Schema-validated closed tool/exposure/evidence/answer projections; no raw stream payloads |
| `scoring_revisions` | `(run_id, trial_id, revision_id)` -> trials | Report SHA-256 as revision ID, scorer version/status, dimension and claim audit, primary error, rescored score and original-answer checksum status |
| `artifacts` | `(run_id, trial_id, relative_path)` -> trials | Relative artifact path, actual SHA-256 and byte count; no answer contents |
| `source_files` | `(run_id, relative_path)` -> runs | Checksums and sizes of source files used in the snapshot |
| `import_issues` | `(run_id, issue_code)` | Safe import diagnostics without arbitrary exception text |

Relationships are validated by the importer; physical foreign keys are omitted
so a complete run snapshot can be replaced in one transaction. No raw JSON
payload column is provided for caller arguments, MCP responses or reasoning.
API token counts and MCP byte-derived token estimates are separate columns.

### P2 trace and opportunity projections

Schema 6 adds `agent_traces`, `agent_spans`, `observability_checkpoints`,
`task_opportunity_registry`, `task_mcp_opportunities`, and
`trial_opportunity_assessments`. The migration is additive; run import replaces
these rows inside the existing per-run transaction, so a repeated import is
idempotent and a failure rolls back the full run update. Existing schema 1–5
databases remain readable until reimported; they do not receive inferred activity.

`benchmarks/codex_r/opportunities.json` is versioned researcher annotation based
on the public task manifests. A task with an explicit empty opportunity list has
no researcher-identified opportunity. A task missing from the registry has
unknown annotation status. Opportunity annotations are independent of trial
outputs and have evidence class `researcher_annotation`.

The trace projector gives each observed lifecycle span a deterministic ID from
the existing run/trial/trace and event identity. Parent references are emitted
only for the trial root and observed same-clock containment (for example a tool
item within an observed agent turn). Parent cycles, invalid IDs, missing parents,
negative durations and same-clock temporal violations mark integrity invalid.
Traces with absent starts/terminals remain partial; no missing event is created.
Cross-clock comparisons are skipped. Server/client calls remain distinct when
their protocol identifiers are unavailable.

Checkpoint states are `observed`, `not_observed`, `unknown`, `unavailable`, and
`not_applicable`. A captured `not_observed` counts as captured only when the
relevant instrumented stream is complete. Unknown and unavailable states never
count as captured. Trace coverage is captured expected checkpoints divided by
the explicit expected-checkpoint count; not-applicable checkpoints are excluded.
Unavailable history has NULL counts and coverage.

`configured` means the runner's requested tool allow-list contains the tool.
`advertised` means a candidate name was observed in the API session echo or in
an actual tool invocation. `discovery_confirmed` is populated per tool only if
the event stream contains an explicit tool-name list; current server audit data
exposes list-tools request counts but not the remote tool-name list. An API echo
is not proof of remote MCP discovery. Invocation is direct evidence of a call;
success requires an observed successful terminal response. A call does not
prove that its result influenced the final answer.

Opportunity Utilization Rate is the number of applicable opportunities with an
observed relevant call divided by applicable opportunities with adequate
invocation observation (complete trial and completed agent turn). Missed
Opportunity Rate uses only that adequately observed denominator subset whose
candidate visibility was confirmed by an API echo or invocation; its numerator
is the subset with no relevant call. A complete trace with no call but unknown
visibility is labeled `no_relevant_call_observed`, not a confirmed miss. Unknown
and non-applicable opportunities are excluded and displayed separately. These
descriptive rates do not measure motivation, correctness, evidence influence,
or causality. Comparisons across task sets with different annotation coverage
need qualification.

The Agent & Evidence tab displays event timelines, parent IDs, capture state,
tool visibility, per-opportunity assessments and numerators/denominators. Older
runs without P2 telemetry show unavailable; synthetic test fixtures are not
empirical benchmark runs.

## Import rules and limitations

- Prefer `results.json` and finalized per-trial `result.json`; fall back to
  `results.csv`. `experiment.json` schema 1 and JSONL schemas 1.0, 1.1 and 1.2 are supported.
  Unknown versions and inconsistent run/trial identities are rejected.
- JSONL is validated against the existing telemetry schema. A missing final
  newline, malformed line or invalid event leaves the run incomplete. A trailing
  partial line is excluded and can be imported on the next update. A completed
  marker alone is insufficient: expected trials and finalized results must agree.
- Legacy runs without JSONL are supported. Without a recorded planned trial
  count, finalized trials are labeled `legacy_finalized_scope_unknown`, never
  represented as a proven complete experiment.
- A source file that changes during import causes rollback for that run. A
  rejected update preserves the last accepted data, marks the snapshot rejected
  and records a safe diagnostic. Runs are re-imported atomically, so repeated
  import never appends duplicate trials/events/calls or score revisions.
- Server JSONL is authoritative for detailed tool aggregates. If absent, use
  saved legacy per-call server logs (`mcp_telemetry` / `mcp_calls.csv`), then client
  observations. Both client and server rows remain visible, but only one source
  has `counted=true`. Trial client/server counts are separate; incomplete coverage
  is not filled with invented calls. Ordinal correlations are **unconfirmed**.
- Missing partial/error/cache/byte/usage/cost facts stay SQL NULL. MCP-disabled
  assignment alone is not evidence of a measured zero count. Explicit recorded
  zero is preserved. No billing rates or financial estimates are applied.
- Historical configurations are taken from the experiment/trial record or the
  explicit checked-in historical registry. Their provenance is shown. Unknown
  scorer/source identities remain scoped to the original run.
- Original scores remain the default. Selecting a rescore report shows only
  trials present in that report. Original and revised checks are separate;
  absence of a revision never falls back to another scorer automatically.
- V2.1 rescoring keeps unknown claims and overall abstentions as null, records
  `SCORER_UNSUPPORTED_CLAIMS` separately from MCP diagnostics, and retains the
  original trial status and primary error beside the selected revision.
- Raw `events.json` is deliberately not read: it can contain agent text and
  reasoning. Full artifacts stay on disk. User-requested previews are bounded,
  confined to `answer.json` / `solution.R` below `artifacts/`, reject symlinks and
  changed checksums, and redact known credential forms and sensitive JSON fields.
  No R code or saved content is executed. Unknown secret formats cannot be
  identified reliably; inspect artifacts locally if they may contain such data.

## Dashboard views

The dashboard selects exactly one Run ID at a time. Its initial selection is the
latest run marked `full_comparable`; that status requires a valid saved plan,
all expected finalized scores, the checked-in registered task scope, both A/B
conditions, standard instructions, and matching scorer/denominator/model/effort
for every pair. If no run qualifies, the newest imported run is shown with an
explicit warning. Partial, diagnostic, corrupt, and legacy runs remain manually
selectable, but never become the default full run. Missing metadata is not
inferred from directory names or recent timestamps.

The six views are:

- **Overview:** A/B passed checks and fully-correct counts with denominators,
  task-level MCP adoption, observed calls/errors, duration, repeated calls, and
  API token/cost availability. Missing usage and cost remain unavailable, not 0.
- **Adoption by Task:** one row per task, observed A/B trial IDs and scores,
  matched repetition and scorer evidence, score delta, MCP availability,
  discovery status, call/error counts, tools used, and duration. A recorded zero
  call count does not explain why the agent did not call a tool. `tools/list`
  discovery is separate from agent choice.
- **Tool Effectiveness:** per-tool successful/error outcomes, safe distinct
  requests where trial scope permits, repeats, bytes, server latency, and
  verified-source responses, plus a call drilldown. `docs_not_found` is an
  application outcome and is not automatically a server malfunction.
- **Scorer & Evidence:** V1 failed checks, separate V2 diagnostic dimensions,
  fixed offline root-cause classifications as secondary evidence, safe local
  artifact references, and bounded redacted previews. Audit references are
  never followed as filesystem paths.
- **Compare Runs:** explicit baseline and comparison Run IDs with compatibility
  warnings. Score values/deltas are withheld when either run is not a verified
  full scope or task/condition/repetition/scorer/generation/denominators differ. Other
  telemetry is descriptive and includes MCP invocation, researcher-annotated
  opportunity utilization/missed rates, trace latency, and checkpoint coverage
  with their own denominators. Opportunity version and task-scope differences are
  called out. A single pair of runs does not establish statistical significance
  or causality.
- **Agent & Evidence:** registered, policy-allowed and generated tool names;
  optional Agents API session-configuration echo shown separately from remote
  discovery (the echo is not proof of remote discovery); observed agent tool classes/outcomes; projected
  package/version facts; answer claims versus pinned versions; and final-answer
  URL mentions versus URLs present in MCP responses. Old runs display telemetry
  as unavailable. A URL in command output is not treated as proof of access.

V1 counted trial telemetry is used for call totals. V2 projections stay at run
scope because they do not carry trial/task IDs; client events plus unmatched
server-only events form the canonical total, while ordinal-linked server rows
are not counted twice. The dashboard does not pool V1 and V2 scorer generations.
Displayed tables offer CSV and Markdown downloads, and CSV export guards against
spreadsheet formula interpretation.

## Historical import example

The three historical runs below import as **3 runs / 6 trials / 78 counted MCP calls**:

| Run | Task | State | Counted calls | MCP errors |
| --- | --- | --- | ---: | ---: |
| `20261025T083653Z-ca1d5503` | D01 | legacy finalized; planned scope unknown | 55 | 41 |
| `20261025T100159Z-a939d94f` | D02 | completed | 0 (recorded client count) | unknown server detail |
| `20261025T100740Z-9746f577` | D01 | completed | 23 | 9 |

The newer D01 has 23 additional **uncounted client observations**, so the tool
aggregate remains 23, not 46. The old D01 rescore is stored as two revised trial
scores; its with-MCP score is 4/4 under `d-recommendation-2`, while its original
3/4 remains unchanged. All six trials have unknown API usage and cost.
These small, stochastic runs provide observations, not a causal estimate of MCP
benefit. The example import output is in `example_import.json`.

## Offline verification

```sh
.venv/Scripts/python.exe -m pytest tests/test_benchmark_analytics.py -q
.venv/Scripts/python.exe -m ruff check benchmarks/codex_r/analytics tests/test_benchmark_analytics.py
.venv/Scripts/python.exe -m ruff format --check benchmarks/codex_r/analytics tests/test_benchmark_analytics.py
```

Tests build synthetic runs only inside pytest temporary fixtures and never alter
saved benchmark results. They cover run completeness and selection, pairing and
repetitions, scorer V1/V2 separation, safe V2 projections, call deduplication,
exports, and metadata unknowns. Historical regression tests use local saved runs
when those ignored fixtures are present. Optional analytics tests skip cleanly
when the analytics extra is not installed.

Library references: [DuckDB Python](https://duckdb.org/docs/stable/clients/python/overview),
[DuckDB concurrency](https://duckdb.org/docs/stable/clients/concurrency),
[Streamlit configuration](https://docs.streamlit.io/develop/api-reference/configuration/config.toml),
[Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.AppTest).
