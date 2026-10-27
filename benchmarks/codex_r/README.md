# Independent Codex / R pilot

## Local analytics (no API calls)

Saved experiments can be imported into a derived DuckDB database and explored
in a local read-only Streamlit dashboard. Source results remain unchanged.
See [analytics/README.md](analytics/README.md) for installation, schema, import,
rebuild, historical examples and the five dashboard views.

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.analytics.import_results
.venv-wsl/bin/python -m benchmarks.codex_r.analytics.dashboard
```

## Simple R01 runner (Ubuntu WSL2)

Run from the repository root, in the terminal that already exports
`OPENAI_API_KEY` and `OPENAI_EXECUTOR_API_KEY`. The application key stays outside
Docker; the executor receives the second key as `CODEX_API_KEY`, as required by
the executor protocol. No other credential variables or env files are used.

First run one real baseline task:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium --tasks R01 --modes without-mcp
```

Then run the R01 comparison, without MCP (A) and with MCP (B):

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium
```

Use `--effort high` for high reasoning. The model is always `gpt-6-luna`.
`--repetitions 2` repeats both modes; `--tasks all` selects all 12 existing tasks.
Each attempt has a fresh OpenAI session and disposable Docker workspace. The
session is deleted and the executor removed before the existing scorer runs.
An ordinary task or scorer failure is saved and the runner continues to the next
assignment. It does not retry the failed task. An interruption or unconfirmed
resource cleanup stops the run.

This command reuses the installed Python environment and existing images:
`rkmcp-codex-runtime:codex-0.163.0`, `codex-r-benchmark:pilot`, and
`cran-knowledge-mcp:shiny-quarto`. It resolves them to immutable IDs without
pulling or building images. The MCP image runs the current `src` read-only.
Image overrides are available through `--executor-image`, `--scorer-image`,
and `--mcp-image`.

Results go to `benchmarks/codex_r/results/<UTC-run-id>/results.csv` and
`results.json`, with per-attempt results, events and source artifacts underneath.
They include the model, effort, task, mode, score, errors, elapsed time, actual
API usage and API cost when available. Missing usage/cost remains null. These
are best-effort API measurements, not a final bill. Missing credentials also
produce CSV/JSON with `startup_error`; that is not a completed model trial.

## B1 single-run MCP discovery experiment

`--experiment b1-discovery` creates one run ID with 12 paired trials: Control and
Treatment for D03, D01 and C01, each repeated twice. The plan balances which
condition runs first across the six task/repetition pairs. A run can be resumed
with `--resume RUN_DIRECTORY`; completed trials are not replayed, and the saved
plan keeps the condition order.

Control retains the current server-level MCP description. Treatment describes
how the read-only tools can check CRAN/Bioconductor metadata, release and version
facts, compatibility, and official function documentation. Both conditions use
the same MCP tools, schemas and individual tool descriptions. The existing
Codex 0.163.0 client receives MCP `InitializeResult.instructions` as its MCP
namespace description; this does not require MCP use and does not change common
agent instructions. Results save description, toolset, schema, individual tool
description and advertised-interface SHA-256 digests for both variants.

Run this once from the repository root in WSL with the existing images. The
command starts no B2 sessions:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple \
  --effort medium --experiment b1-discovery \
  --tasks D03 D01 C01 --repetitions 2 \
  --knowledge-pilot-scorer knowledge-pilot-v2 \
  --executor-image rkmcp-codex-runtime:codex-0.163.0-bioc \
  --scorer-image codex-r-benchmark:pilot-bioc \
  --mcp-image cran-knowledge-mcp:shiny-quarto
```

The runner writes `b1_comparison.json` incrementally, including missing and
failed pairs. Import the completed run with the existing analytics importer.
D01 and D03 use the knowledge-pilot-v2 scorer; C01 uses its supported legacy
scorer. The summary and Dashboard compare scores only within each task/scorer
pair and do not pool those score scales. MCP calls, `docs_not_found`, repeats,
duration, observed token usage and cost remain condition-specific. Missing
measurements stay null.

Scoring uses the durable artifact export. R02's observed `summarize_sales.R`
filename is accepted only inside the validated workspace root and exported as
`solution.R`; `artifact_sources` records that mapping. Existing symlink, size
and UTF-8 checks still apply. Exports can be rescored offline without another
model turn; a deleted workspace without an export cannot be reconstructed from
test output or an agent's success message.

Executor startup runs concurrently with opening the event stream and never waits
for SSE headers or a connection event. A session-state check handles a connection
event missed during subscription; task submission happens once. On connection
failure, `result.json` retains `environment_error` and `executor_diagnostics`
(container state and bounded, redacted logs captured before cleanup). Terminal
messages contain progress and error status; detailed diagnostics stay in JSON.

Ctrl+C requests shutdown and exits with code 130 after cleanup. Cancellation of an
active or possibly submitted turn is requested before deletion is attempted. Each API and
Docker cleanup operation has a 10-second deadline and its own safe result in
`cleanup_operations` (also exported in CSV). `session_deleted=true` requires the
API's matching ID and `deleted=true`; errors, timeouts and unconfirmed responses
leave it null. The primary task error is retained separately from cleanup errors.
A second Ctrl+C aborts the remaining cleanup, saves which results are unknown or
skipped, and exits without starting another assignment.

The terminal prints session/executor/turn/scoring/deletion/cleanup milestones.
Every 15 seconds, a heartbeat shows elapsed time and the
current stage. This does not alter the agent timeout. Terminal progress contains
fixed labels and counters, without request bodies, MCP responses or credentials.

The simple runner has no approval files, Git checks, preliminary audits or
`spend_control` request field. It enforces a wall-clock timeout (default 900
seconds), CPU/memory/process limits and networkless scoring. The executor uses
a Docker bridge network for the OpenAI relay and MCP; it does not enforce the
older pilot's egress allowlist or a hard 30,000-token cap. These results are
simple benchmark runs, not compliance with the preregistered protocol below.

## Paired tool-value pilot

Run the sixteen B/C/D/E tasks in both modes, with the same standard instructions and
GPT-6 Luna `medium` reasoning:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium --pilot tool-value
```

To select only E01-E05 through the existing task selector:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium --tasks E01 E02 E03 E04 E05
```

The runner schedules each task without MCP and then with the consolidated MCP
tool set. MCP use remains optional. `--pilot tool-value` cannot be combined with
`--tasks`; the existing `--tasks hard-pilot`, R01..R12 and default R01 behavior
remain available. Use `--effort high` to select high reasoning.

`--pilot full` runs all 19 registered H/B/C/D/E tasks: H01, H04, H10, B01-B03,
C01-C05, D01-D03 and E01-E05 (38 paired trials). H02-H03 and H05-H09 are not
registered; the legacy R01-R12 suite remains under `--tasks all`. E02 uses the
repaired 500-gene negative-binomial fixture and is included. The runner selects
`codex-r-benchmark:pilot-bioc` and `rkmcp-codex-runtime:codex-0.163.0-bioc`
automatically when E02/E03 are selected, and probes both images before creating
an OpenAI session. To continue an interrupted run without replaying completed trials,
pass its result directory with `--resume` and the same effort. Resume checks the
saved manifest against current source, dirty-tree, image, toolset, scorer and
task configuration; it refuses to replay any trial directory that lacks a
finalized `result.json`.

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium --pilot full
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium --resume benchmarks/codex_r/results/RUN_ID
```

B01-B03 test bug fixes, C01-C03 test behavior tied to pinned dplyr 1.2.1,
tidyr 1.3.2 and readr 2.2.0 documentation, C04-C05 test cranlogs 2.1.1 date-range
and mirror-scoped download totals, D01-D03 test package discovery, and E01-E05
test CRAN/Bioconductor release alignment, a DESeq2 workflow, a documented
namespace relocation, mixed-repository dependencies and three-way compatibility
classification. E02/E03 require the E-specific Bioconductor package pins listed
in their task provenance; the default `codex-r-benchmark:pilot` image currently
does not contain these packages. `configs/bioc.Dockerfile` adds them on top of the frozen
image (build-time network only; Bioconductor 3.22; DESeq2 1.50.2, SummarizedExperiment
1.40.0, Biobase 2.70.0; GenomicRanges 1.62.0 from the release Archive, SHA-256 checked; every
renv.lock version is asserted unchanged):

```sh
docker build --pull=false -f benchmarks/codex_r/configs/bioc.Dockerfile -t codex-r-benchmark:pilot-bioc benchmarks/codex_r
```

The paired Bioconductor executor is built from the existing Codex runtime and
copies only `/opt/benchmark-library` from the pinned scorer donor. Its Codex
binary, entrypoint, user and execution contract remain inherited from the runtime:

```sh
docker build --pull=false --network=none -f benchmarks/codex_r/runtime/bioc.Dockerfile -t rkmcp-codex-runtime:codex-0.163.0-bioc benchmarks/codex_r/runtime
.venv-wsl/bin/python -m benchmarks.codex_r.full_selftest
```

No hidden benchmark files are copied to the executor. E02 passes 5/5 with the
unchanged reference and standard DESeq2 parametric fitting; E03 and all other
registered H/B/C/D/E reference/mutant pairs pass their offline self-tests.
See [the full offline report](reports/full-offline-readiness-20261025/README.md)
for image digests, fixture reproduction and the exact checks. No package
installation occurs while scoring or during agent tasks.
R 4.5.2 and the existing locked environment are used. Public fixture and task
hashes, package versions, documentation URLs and check timestamps are saved in
each trial's `task_provenance`. The hidden reference controls and verifiers are
mounted only into the networkless scorer, never into the agent workspace.

The run directory contains `results.csv` / `results.json`, `mcp_calls.csv` and
`mcp_tool_aggregates.csv`. Per-call rows report request/result JSON byte counts,
an explicitly approximate result-token count (`ceil(bytes / 4)`), duration,
status, error category and truncation. This byte-based estimate is not a model
token count or a billed token count. MCP arguments and full results are removed
from the saved agent events. `tool_search_calls` and server `tools/list` counts
remain separate diagnostics, and client calls are reconciled against the
server's audit and per-call log.

The E-block snapshot facts and their SHA-256 list are in
[`knowledge_pilot/metadata/E-source-snapshot.json`](knowledge_pilot/metadata/E-source-snapshot.json)
and [`knowledge_pilot/metadata/E-source-snapshot.sha256`](knowledge_pilot/metadata/E-source-snapshot.sha256).
E01/E04/E05 have deterministic offline JSON scorers. E02/E03 use the existing
networkless R scorer and fail closed unless the scorer image has the exact E
package pins. The currently available `codex-r-benchmark:pilot` image does not
contain those packages; their Docker reference/mutant checks must be run against
an image restored with the task metadata's package versions before interpreting
their scores. The runner probes those exact package pins and aborts before an
OpenAI session if they are absent. The scorer itself reports `environment_mismatch`
rather than grading those tasks as candidate failures. No installation occurs
while scoring.

The opt-in [`measurement_hardening_v2.md`](measurement_hardening_v2.md) documents the
versioned D/E evaluator, public output contracts, open-world alternative policy, safe MCP
observation schema 2.1, with bounded discovery query/alias/pagination fields and server protocol
call IDs, and separate adoption/effectiveness/efficiency metrics. Legacy scoring
remains the default; select V2 with `--knowledge-pilot-scorer knowledge-pilot-v2`. The separate
`knowledge-pilot-v2.1` scorer is opt-in for D01/D03 and adds a versioned local claim registry
with `supported`, `unknown` and `contradicted` states. Unknown claims cause automatic-scoring
abstention and remain null in the overall score. V2 and saved B1 results are unchanged. The
offline B1 rescore is documented in
[`reports/b1_scorer_v21_rescore_20261026.md`](reports/b1_scorer_v21_rescore_20261026.md)
and its machine-readable report; it leaves C01 on its original legacy scorer.

Agent input/output/cached/reasoning usage is copied from session/turn usage when
the API provides it. The API calls those counts best-effort and they can change;
missing values stay null. Cost is saved only when returned by the API. The
runner does not infer cost from MCP bytes or from token estimates. A local
server-call example with no agent session is in
[`reports/tool-value-example.md`](reports/tool-value-example.md).

The scorer reference/mutant self-test can run without OpenAI credentials:

```sh
.venv-wsl/bin/python -m pytest tests/test_knowledge_pilot.py -q
```

It checks the existing B/C R references, D JSON references and E01/E04/E05
JSON references against deliberately incorrect controls. E02/E03 require the
exact package-enabled scorer image described above.

The protocol follows official OpenAI documentation for
[self-hosted executors](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted),
[MCP connections](https://developers.openai.com/api/docs/guides/agents-api/tools/mcp),
and [usage](https://developers.openai.com/api/docs/guides/agents-api/observability).
The real model turn must be verified from the terminal containing the keys;
Docker component checks and mocked API tests do not establish that it completed.

## Separate MCP documentation smoke test

This task uses the same session, Docker executor, consolidated MCP configuration
and event/server auditing as the hard runner. It does not select a hard task,
export hard fixtures, or run a hidden R verifier. Standard agent instructions
remain byte-for-byte unchanged. Only the separate TASK.md comes from
[`smoke_mcp_closest.md`](smoke_mcp_closest.md).

From the WSL2 terminal with the existing two keys exported, run:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium --tasks mcp-smoke --modes with-mcp
```

Results use a new directory with `mcp-smoke-B-1/events.json` and `result.json`.
`mcp_server_audit` is in that result and the aggregate `results.json`. There is
no solution.R requirement, R score or `fully_correct` grade for this diagnostic.

The runner redacts MCP arguments and response bodies from saved `events.json`.
The smoke result therefore records transport evidence only:

1. A completed MCP call is identified in redacted `events.json` by
   `r_knowledge` / `get_function_docs`; `mcp_usage.calls >= 1`.
2. This status does not certify that the returned documentation contained
   closest() or that its provider result was successful.
3. `mcp_server_audit.list_tools_requests >= 1`, `call_tool_requests >= 1`,
   `tool_names` includes `get_function_docs`, and `rejected_requests == 0`.
4. The turn completes and session/container cleanup succeeds.

`mcp_usage.tool_search_calls` remains a separate diagnostic metric. A separate
tool-search event is not required for `smoke_transport_observed`: the agent's
documentation call and server's `CallToolRequest` must both be present, alongside
the list-tools request and zero rejected requests. This status confirms traffic,
not a successful documentation response. `smoke_transport_missing` exits
nonzero. A tool error can
produce a CallToolRequest, so counts alone cannot establish documentation retrieval.

## Original preregistered pilot

Status: benchmark infrastructure; **zero actual Codex trials**. R oracle self-tests
use private developer reference programs and semantic mutants. They do not measure
Codex or the effect of MCP. See [methodology](../../docs/CODEX_MCP_BENCHMARK.md).

Nothing under this directory is part of the MCP runtime or installed wheel.
Ordinary pytest tests only infrastructure with synthetic records and mocked MCP.
It neither installs R packages nor starts paid agents.

## Prepare the environment before timing

From the repository root, after installing the project's development dependencies:

```sh
python benchmarks/codex_r/runner/bench.py validate
docker build -f benchmarks/codex_r/configs/Dockerfile \
  -t codex-r-benchmark:pilot benchmarks/codex_r
docker image inspect codex-r-benchmark:pilot --format '{{.Id}}'
```

Use the resulting **sha256 image ID**, not the tag, for every condition and scorer.
The image pins R 4.5.2, Quarto 1.8.27, Bioconductor 3.22 and the actual 89-record
renv.lock. It contains no oracle, task answers, candidate artifacts or credentials.
Restoration downloads approved dependencies at image build time only. Do not run
configs/capture_environment.R to refresh dependencies after preregistration.
The optional capture script is a development inventory tool, not restoration.

Static R syntax and actual boundary/interface probes are separate from agent trials:

```sh
Rscript --vanilla benchmarks/codex_r/configs/check_syntax.R benchmarks/codex_r
python benchmarks/codex_r/runner/boundary.py --image sha256:ACTUAL_IMAGE_ID --output boundary.json
python benchmarks/codex_r/runner/verify_mcp.py --output mcp-interface.json
```

Verify the private oracles before any agent trial:

```sh
python benchmarks/codex_r/runner/selftest.py \
  --image sha256:ACTUAL_IMAGE_ID --output oracle-selftest.json
```

This runs 12 trusted references and 12 semantic negative controls in disposable
scoring containers. The output is labelled oracle_selftest_not_agent_trials.
Do not give oracle/selftest to a coding agent.

## Pre-register and export tasks

Replace every uppercase placeholder; these examples do not select a paid model.

```sh
python benchmarks/codex_r/runner/bench.py plan \
  --model EXACT_AUTHORIZED_MODEL_ID --reasoning-effort high \
  --image sha256:ACTUAL_IMAGE_ID --seed 1729 --repetitions 2 --output plan.json
python benchmarks/codex_r/runner/bench.py prepare \
  --task R01 --workspace /absolute/outside-repository/trial-R01-A-1
python benchmarks/codex_r/runner/bench.py container \
  --image sha256:ACTUAL_IMAGE_ID --workspace /absolute/outside-repository/trial-R01-A-1
```

The final command emits a JSON **argument array**, never a shell string. It describes
a restricted, networkless R tool-execution container, **not a runnable Codex adapter**.
A separate authorized external agent controller must bind ALL agent filesystem
tools to its disposable candidate workspace/container. Never launch a host-level
Codex session in the full repository and call it blinded. Host workspace-write
alone permits reads outside the workspace.

prepare exports only TASK.md, the lock and one public CSV. Hidden inputs/assertions,
references, other attempts and evaluator configuration are not exported.
No source-file starter contains a solution. Follow the randomized trial order in
plan.json; use a fresh session and workspace for each of 72 assignments.

## Conditions and MCP gateway

A has no MCP connection. B exposes the explicit core tool allowlist in manifest.json.
C exposes those same tools plus the five public Prompt Intelligence tools.
Prompt composition uses build_r_prompt's public composition_mode/templates arguments.
PI use is OPTIONAL, specified before trials. There is no extra hidden enhancement,
automatic hint, or native MCP Prompts/Resources route.

For B/C the external controller connects only the benchmark recording gateway:

```sh
python benchmarks/codex_r/runner/gateway.py --condition B --audit trial-mcp.jsonl
```

Use C for Condition C. Run this trusted service outside the candidate's filesystem.
It forwards MCP list/call operations over the production server's public stdio
interface. Install the evaluated production source and mcp==1.30.0 / httpx==0.28.1;
the gateway refuses source hashes or SDK versions different from the manifest.
It enforces list AND call allowlists, exposes no resources/prompts, preserves
isError/structuredContent, bounds calls/responses and records complete returned
documentation/provenance and PI arguments/results. It never starts Codex.
The gateway has no GitHub/Context7 keys and accepts only synthetic public trial
material. Keep raw transcripts private until all attempts are sealed.

Record PI template selections, detail level, composition mode, generated prompt
character/byte size and final instructions from its full actual response and
Codex transcript. These diagnostic sizes are NOT token metrics or correctness.
The trial metadata must retain final instruction text separately from hidden
scoring material; never edit the original task during enhancement.

## External execution requirements

Read configs/CAPABILITIES.md first. Codex CLI was inspected but no supported hard
token/cost cap and no fully isolated authenticated agent controller were verified
here. No sessions or paid calls were started. Do not treat the shell-container
configuration as proof of complete Codex filesystem/network isolation.

Use a provisioned, separately audited container/VM agent runner, fresh memory/
configuration, no ordinary browsing, equal model/reasoning/budgets and only a
controlled model endpoint plus B/C gateway. Candidate R commands stay networkless.
The same common instruction is each task's public TASK.md. Package help bundled
with R is allowed equally. Provision packages before the 900-second/30,000-token
budget starts. Include PI and MCP waiting in elapsed time. Allow zero external
reruns; repairs within the original budget are permitted and counted if observable.
If hard uniform token enforcement is unavailable, do not start a compliant pilot.

### Controller status

`runner/controller.py` now provides a fail-closed preflight and an offline
synthetic dry-run. It derives the exact A/B/C tool configuration from the plan,
checks public workspace contents, redacts credential-shaped strings and exercises
missing-usage, timeout and cleanup paths. It does not start Codex, inspect
credentials, contact a model endpoint or create benchmark records. The preflight
currently returns `blocked`; see [controller documentation](runner/CONTROLLER.md)
for the exact token-budget and isolation blockers. Do not interpret a dry-run as a
candidate attempt.

```sh
python benchmarks/codex_r/runner/controller.py preflight \
  --plan plan.json --trial R01-A-1
python benchmarks/codex_r/runner/controller.py dry-run \
  --plan plan.json --trial R01-A-1 --output dry-run.json
```

## Seal, score, import and report

Terminate the candidate session, export its source files, and prohibit further
candidate access before mounting an oracle. Never give hidden feedback or a repair
opportunity after scoring. The scorer imports only allowlisted UTF-8 source
artifacts (8 MiB total), fixes public fixtures, and mounts the sealed export readonly.

```sh
python benchmarks/codex_r/runner/bench.py score \
  --task R01 --artifacts /absolute/outside-repository/finished-artifacts \
  --image sha256:ACTUAL_IMAGE_ID > trial-score.json
python benchmarks/codex_r/runner/bench.py record \
  --plan plan.json --trial R01-B-1 --metadata trial-metadata.json \
  --score trial-score.json --events codex-events.jsonl --audit trial-mcp.jsonl \
  --output trial-record.jsonl
python benchmarks/codex_r/runner/bench.py import --plan plan.json --input results.jsonl
python benchmarks/codex_r/runner/bench.py report --plan plan.json --input results.jsonl > report.md
```

For A omit --audit. Concatenate each exclusive-created trial-record.jsonl once, in
the assigned order. Never concatenate mock infrastructure test data into results.
Keep raw events, gateway audit, source artifact hashes, final instructions,
execution/isolation evidence and plan together in private run storage; publish only
reviewed synthetic-task evidence, with no credentials.

trial-metadata.json contains: started_at/completed_at (timezone-aware ISO timestamps),
isolation_verified (true only after the external boundary audit), model,
reasoning_effort, image, production_commit, fingerprint (from plan), invalid_api_calls
and repairs (nonnegative integers or null when no independent measurement exists).
The control metadata must come from the external controller's actual configuration,
not a candidate's claim. It is an attestation, not automatically proven by this
importer. --score is produced by score, and --events is actual codex exec --json
output. record derives token counts from turn.completed usage and MCP counts/errors
from gateway logs. If usage is absent, it stays null; do not estimate it from text.
All final record fields and types are in configs/result.schema.json; the importer
additionally checks assigned identity, controls, time/token limits and scoring rules.

A score is four equally weighted hidden test GROUPS, not an arbitrary assertion
count. A group's assertions must all pass, with no skips/errors. Full success is 4/4.
Candidate failure/timeout/security violation scores zero; environment/scorer failures
are missing. Missing data remains visible against all assigned trials.

The report shows per-condition/per-task outcomes, missingness, paired task-cluster
bootstrap intervals, timing and observed metrics. A small pilot cannot establish
a general improvement; a null/negative result is valid.
