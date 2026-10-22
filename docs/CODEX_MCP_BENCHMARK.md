# Independent Codex benchmark for R Knowledge MCP

## Question and status

Does access to the current R Knowledge MCP improve Codex's R code correctness,
reliability or efficiency? Null and negative results are valid. Primary outcomes
come from independent R execution and testthat checks, not prompt length, tool
invocations or the evaluator's impression.

**No comparative agent execution results are available yet.**
Actual candidate sessions: 0. Actual completed/scored Codex trials: 0.
No model-token usage, model cost, comparative correctness or savings were measured.

This PR delivers a pilot specification, fixtures, private evaluation code, a
locked R image, safe artifact/scorer runner, condition gateway, external-run
importer, report generator and Python infrastructure tests. Trusted oracle
self-tests are a separate validation activity. Their results cannot support a
claim that MCP improves Codex.

## Verified production baseline

The benchmark branch starts from main edab8244ae8fa77f33d0dd750323405aacf5985b.
The following merged PRs are present, rather than merely assumed available:

- [#3: Shiny URLs/function errors](https://github.com/menshikovs/R-Knowledge-MCP/pull/3)
- [#4: lightweight metadata](https://github.com/menshikovs/R-Knowledge-MCP/pull/4)
- [#5: MCP error semantics](https://github.com/menshikovs/R-Knowledge-MCP/pull/5)
- [#6: concise Prompt Intelligence](https://github.com/menshikovs/R-Knowledge-MCP/pull/6)
- [#7: upstream diagnostics, including Linux smoke imports](https://github.com/menshikovs/R-Knowledge-MCP/pull/7)

[Baseline CI](https://github.com/menshikovs/R-Knowledge-MCP/actions/runs/39804509868)
completed successfully. Registration, provider modes, error adapter, prompt
interfaces, packaging, existing tests and developer documentation were inspected.
The benchmark records normalized SHA256 hashes of every production Python source
file; the gateway refuses to evaluate another installed source tree.
No production provider, prompt, registration, cache, dependency or deployment
configuration is modified.

## Treatments and information access

| Access | A: baseline | B: core MCP | C: core + PI |
| --- | --- | --- | --- |
| Original public task and fixture | Same | Same | Same |
| Locked R packages and installed help | Same | Same | Same |
| Ordinary browsing/network/data downloads | Disabled | Disabled | Disabled |
| Controlled model endpoint | Same | Same | Same |
| CRAN/Bioconductor metadata, docs, compatibility | No MCP | Allowlist | Same allowlist |
| Fixed official framework/visualization docs | No MCP | Allowlist | Same allowlist |
| Public Prompt Intelligence tools | None | None | Five allowlisted tools |
| MCP native Prompts/Resources, other connectors | None | None | None |
| Hidden oracle/reference/other trial artifacts | Inaccessible while solving | Inaccessible while solving | Inaccessible while solving |

manifest.json is the authoritative exact tool inventory. The common core is:
search_packages, get_package_info, get_dependencies, get_function_docs,
check_package_version, get_bioconductor_version, check_package_compatibility,
get_package_vignettes, get_shiny_docs, explain_shiny_reactivity,
get_positron_guidance, get_quarto_docs, get_r_workflow_guidance,
get_visualization_docs and get_visualization_workflow.

C additionally allows build_r_prompt, improve_r_prompt, validate_r_prompt,
list_r_prompt_templates and get_r_prompt_context. Composition and template
selection use public build_r_prompt arguments, not a benchmark optimizer.
PI use is **optional**, preregistered before execution. Agent instruction text is
otherwise identical. Record compliance and both intention-to-treat and descriptive
actual-use counts; do not make a causal comparison of self-selected users.

The benchmark gateway is an independent list/call filter in front of the public
production stdio MCP interface. It neither assumes nor implements a production
tool profile. No Prompts/Resources handler bypasses the filter. B cannot call PI
by guessing a tool name. Upstream is a fresh process for every trial, so its cache
is not warmed differently by prior conditions. SDK/httpx versions are also fixed
for this intervention (1.30.0/0.28.1). Complete actual response material, versions,
sources, check times, transport errors, PI arguments and PI outputs are recorded.
Default gateway limits: 100 calls, 64 KiB argument JSON, 4 MiB result, 32 MiB audit
and 45 seconds per call; production HTTP/SSRF/size restrictions remain in force.
No API keys or proprietary/user data are part of the benchmark.

## Twelve tasks and independent outcomes

Every task has public instructions, a CSV example, a typed output contract,
failure conditions, the same resource/time budget and four hidden test groups.
Scoring fixtures are synthetic and generated locally; no scoring data is fetched.

| ID | Area | Independently checked outcomes |
| --- | --- | --- |
| R01 | Base R control | validation, missingness, first valid duplicate, typed empty output, input preservation |
| R02 | dplyr | groups, negative/zero totals, filtering, types, ungrouping |
| R03 | readr | explicit types, malformed cells retained, actual parser diagnostics, missing/empty files |
| R04 | ggplot2 | plot object/build, log scale, points/lines, group mappings, invalid rows |
| R05 | tidyr | aligned .value reshaping, identifiers, missing measurements, empty types |
| R06 | DBI/RSQLite | bound owner/threshold, SQL-looking strings, NULLs, success/error connection cleanup |
| R07 | SQL | date boundaries, left joins, NULL aggregation, literal parameters, caller connection preservation |
| R08 | Shiny | server factory, reactive input/data invalidation, defaults, ordered filtering |
| R09 | Shiny modules | namespace, cutoff/data changes, finite/empty values, independent sessions |
| R10 | Quarto | executable configuration, hidden replacement CSVs, actual HTML rendering/table contents |
| R11 | Bioconductor | IRanges 2.44.0 merging/adjacency, covered width, chromosome isolation, invalid coordinates |
| R12 | Composed workflow | typed CSV cleaning, duplicate semantics, grouping, serialized plots, actual report render |

R01 is a low-documentation-value control. R11 is deliberately version-sensitive.
R06/R07 measure safety, and R12 has multiple dependencies. Cosmetic choices in
R04/R10 remain deliberately open and unscored. No entire task is scored solely by
text inspection. Quarto configuration checks accompany real rendering; plots are
checked as objects/build data rather than pixels. All assertions are independent
of generated prompts and MCP claims.

## R environment and reproducibility

The actual renv.lock fixes R 4.5.2, Bioconductor 3.22 and 89 package records with
their dependency closure. Direct task packages include dplyr 1.2.1, readr 2.2.0,
ggplot2 4.0.3, tidyr 1.3.2, DBI 1.3.0, RSQLite 3.53.3, shiny 1.14.0 and
IRanges 2.44.0 (S4Vectors 0.48.1, BiocGenerics 0.56.0). Quarto is 1.8.27.

The lock originated from a real installed R inventory. Before any trials, the
Windows-only S7 0.2.1-1 record was replaced using renv::record with the available
official CRAN source version 0.2.2 for Linux portability. No trial was scored
against a moving package environment. R normalizes hyphens in package versions;
preflight compares package_version objects rather than unequal display strings.

[Bioconductor's release mapping](https://bioconductor.org/about/release-announcements/)
and the [3.22 IRanges metadata](https://bioconductor.org/packages/3.22/bioc/html/IRanges.html)
confirm the chosen R 4.5 / Bioconductor pairing. This is a benchmark-specific
historical pin, not a hard-coded current release in the MCP server.
The [renv lock/restore interface](https://rstudio.github.io/renv/reference/lockfiles.html)
was checked. The Dockerfile uses a verified R base digest, installs Linux system
build dependencies and the [official fixed Quarto release](https://github.com/quarto-dev/quarto-cli/releases/tag/v1.8.27),
then restores before timing. Cache packages are copied into the image, not
symlinked to an absent build cache. Each scoring preflight verifies the complete
R/package lock and Quarto where needed. Restoration failure is infrastructure
failure, never a fabricated candidate score. Freeze the resulting Docker image
ID for all trials; rebuilding on another date is not assumed bit-identical.

## Hidden-test boundaries and safety

The candidate image build context explicitly excludes tasks, oracles, references
and the repository. prepare refuses workspaces inside the evaluator repository
and exports only TASK.md, renv.lock and the task's public CSV. A candidate container
mounts only that directory; it has no oracle, repository mount, Docker socket or
host credentials. Container arguments specify a readonly root, unprivileged UID,
no privileges/capabilities, no network, 2 CPUs, 2048 MiB including swap cap, 256
processes and bounded writable tmpfs. Scorers additionally have an internal
deadline, bounded stdout/stderr and forced container cleanup on exit/timeout.

The actual external **agent controller** must enforce equivalent filesystem
boundaries for every agent tool. A host-level Codex session, even workspace-write,
does not establish read isolation. The emitted offline R shell command is not
a claim of automatic authenticated Codex operation. The importer requires an
operator isolation attestation; it cannot independently prove an arbitrary
external attestation. Unverified attempts must not enter the blinded cohort.

Terminate the agent, seal hash-addressed allowlisted source artifacts and disable
further access before mounting the readonly hidden oracle in a separate scoring
container. Fresh scoring has no network or production database. Private scores
and test details are not returned for repairs. Candidate R does see the oracle
during test execution in that **post-agent** scoring process, as in conventional
unit-test evaluation. This design separates the coding agent from hidden tests;
it is not a tamper-proof evaluator for deliberately adversarial R submissions
that inspect/alter the scorer process. Do not use it as a security competition.
Public benchmark publication also leaves a future training-contamination risk.

## Predeclared execution design and metrics

Default design: 12 tasks × 3 conditions × 2 independent repetitions = 72 trials.
A minimum one-repetition plan has 36. Seed 1729, shuffled tasks within each
repetition, shuffled A/B/C within each task block. No resume/fork, prior messages,
shared workspace, cache, memory or cross-condition output. No post-scoring retries.
In-budget local repairs are allowed. No ordinary browsing for any condition.
MCP/PI work and latency count inside the same 900-second, 30,000 actual-model-token
budget. Packages are installed before the clock. No hard token cap is fabricated:
the external controller must demonstrate enforcement before any compliant run.

Model and reasoning have no implicit machine default: plan requires an exact
authorized model identifier and explicit effort, fixed across all records.
No model configuration was selected or run for comparative evaluation in this PR.
Record the provider-resolved model snapshot as part of external execution evidence;
a CLI alias alone is insufficient to prove a fixed backend snapshot.

Primary scores are macro-averages over four equally weighted test groups per
task. A group passes only when all of its assertions pass, with no skip or error.
Full-task success is 4/4. Candidate source/runtime failures, deadline/resource or
security failures are zero. Scorer/environment failures and absent trials are
missing, with rates against all assigned trials. They cannot become successes.

The report presents evaluable denominators, full success, average hidden-group
score, per-task means, observed failures, timing, actual input/output/total usage,
MCP calls/errors, independently observed invalid API use, and repairs when known.
Unavailable metrics remain null; no character-to-token or invented price/cost
conversion is used. Runtime/syntax/import/security details can be independently
classified from private artifacts/logs; they are not guessed from a failed score.
The condition mean score first averages available repetitions within each task,
then equally averages observed tasks; absent tasks remain missing. Full-task
success is also reported as an explicit numerator/evaluable-trial denominator.

B−A and C−A use complete paired task/repetition blocks, averaged within task,
then equally across paired tasks. Descriptive 95% intervals use 2,000 bootstrap
resamples of task clusters, with the preregistered seed; fewer than two task
clusters produces no interval. Missing paired tasks are disclosed. This small,
heterogeneous pilot does not support broad significance or causal claims without
verified execution compliance and adequate complete observations. Scoring weights
and exclusions must not be changed after seeing candidate results.

## Execution capability, results and reproduction

Codex CLI 0.162.1 was inspected, including ephemeral noninteractive sessions,
JSON events, model/config flags and workspace selection. Official
[noninteractive documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
and [MCP configuration](https://learn.chatgpt.com/docs/config-file/config-reference)
were consulted. A supported uniform hard token/cost controller and a fully isolated,
authenticated model/agent execution service were not verified. No paid calls or
agent sessions were made. A follow-up branch adds an offline controller
preflight and fake-process dry-run; real execution still fails closed. The current
Managed Agents API adds isolated environments and monetary spend controls, but its
documented session token usage is best effort and not a preemptive cumulative
30,000-token cap. A monetary limit is not substituted. No paid calls or model
requests were made. See
[the controller status](../benchmarks/codex_r/runner/CONTROLLER.md) and
[capability audit](../benchmarks/codex_r/configs/CAPABILITIES.md).

The checked-in reports directory contains infrastructure evidence only. No mock
trial is published as an observation. Python tests use explicitly synthetic trial
records; the real results section remains empty. No comparative conclusion can
be drawn yet. Reference solutions passing the oracle do not establish agent skill
or treatment effect.

Observed development validation on 2026-10-22:

- Ruff check and format check pass.
- Full Python suite: 283 passed, including 28 new infrastructure cases. The
  unmodified suite ran with Windows temp/named-pipe access outside the restricted
  sandbox; no tests were deselected or weakened.
- Base R parsed all 18 benchmark R files successfully.
- In the pinned Linux image, all 12 trusted references passed all 48 groups;
  all 12 semantic mutants were rejected as full successes. R10/R12 performed
  actual offline Quarto renders. See reports/oracle-selftest.json.
- Actual candidate R-container probing confirmed only public task files, with
  no oracle, repository mount or Docker socket. See reports/boundary.json;
  it explicitly does not attest an external Codex session's isolation.
- Actual stdio MCP handshakes exposed 15 tools in B and 20 in C; the offline
  template tool was denied in B and allowed in C. See reports/mcp-interface.json.

These observations validate infrastructure, not comparative agent performance.

Follow [the benchmark README](../benchmarks/codex_r/README.md) for environment build,
private oracle validation, preregistration, public workspace preparation, condition
gateway, controller dry-run, artifact scoring, external-record import and report generation.
Retain raw private JSONL evidence and source hashes; validate against
configs/result.schema.json and the cross-field importer. Normal PR CI runs only
Python infrastructure tests: manifest/fixture loading, schema, report/score rules,
deterministic scheduling, actual public tool names, allowlist/error handling and
mount boundaries. It starts no paid trials and requires no CRAN downloads.

Next: provide an isolated controller with a preemptive cumulative token guard,
verify all boundary checks, pre-register an authorized exact model, execute the
randomized 72-run pilot, independently audit
API/repair/safety metrics, then publish complete raw synthetic-task evidence and
paired summaries. Extend tasks/repetitions only in a new preregistered protocol.
Any production defect revealed by future trials belongs in a separate issue/PR.
