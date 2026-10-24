# Independent Codex / R pilot

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
A failure stops the run after saving its reason; there are no automatic reruns.

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
(container state and bounded, redacted logs captured before cleanup). Diagnostics
are also printed on failure; neither API key nor executor routing URLs are logged.

The simple runner has no approval files, Git checks, preliminary audits or
`spend_control` request field. It enforces a wall-clock timeout (default 900
seconds), CPU/memory/process limits and networkless scoring. The executor uses
a Docker bridge network for the OpenAI relay and MCP; it does not enforce the
older pilot's egress allowlist or a hard 30,000-token cap. These results are
simple benchmark runs, not compliance with the preregistered protocol below.

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

Success requires inspecting both sides:

1. `events.json` contains a completed native `tool_search_call` (or the actual
   emitted tool-search item type) discovering the R-Knowledge-MCP documentation
   tool. `mcp_usage.tool_search_calls >= 1`. Automatic server `tools/list` is not
   a model tool-search call.
2. A completed MCP call targets `r_knowledge` / `get_function_docs` with actual
   arguments `package="dplyr"`, `function="closest"`, `repository="cran"`.
   `mcp_usage.calls >= 1` and its tool names contain `get_function_docs`.
3. The actual tool result contains documentation for closest(), without an MCP
   error or a provider error payload. Inspect the returned version, source URL
   and UTC check time. An agent's success message alone is insufficient.
4. `mcp_server_audit.list_tools_requests >= 1`, `call_tool_requests >= 1`,
   `tool_names` includes `get_function_docs`, and `rejected_requests == 0`.
5. The turn completes and session/container cleanup succeeds.

`smoke_transport_checks` automatically checks the observable discovery/call
counters on both sides. `smoke_transport_observed` is a traffic result, not proof
of a successful documentation response; step 3 still requires inspecting the
saved result. `smoke_transport_missing` exits nonzero. A tool error can produce
a CallToolRequest, so counts alone cannot establish documentation retrieval.
If MCP is called but tool_search is absent, MCP invocation is demonstrated but
the discovery portion of this smoke test has not passed. The task requests native
discovery explicitly; it cannot create a search capability absent from the API.

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
