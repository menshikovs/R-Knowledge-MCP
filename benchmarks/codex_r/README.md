# Independent Codex / R pilot

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
