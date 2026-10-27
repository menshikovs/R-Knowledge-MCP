# Full H/B/C/D/E benchmark: offline validation, 2026-10-25

This is reference/mutant and runtime validation, **not model trials**. OpenAI API
calls: **0**. The saved historical benchmark results were not modified.

## E02 data repair

The original 20 rows were almost deterministic inside each condition. The
unchanged reference scored 0/5 because DESeq2 reported that every gene-wise
dispersion estimate was within two orders of magnitude of its minimum; the
standard dispersion trend could not be fitted. The complete observed failure is
in [the original-fixture diagnostic](../E02-original-fixture-diagnostic-20261025.json).

The replacement is a synthetic negative-binomial RNA-seq count matrix:

- R 4.5.2; seed **20261025**; Mersenne-Twister / Inversion / Rejection RNG kinds.
- **500 genes × 6 samples**, three control and three treatment biological replicates.
- Lognormal baseline abundance, gene-specific biological dispersion and sample
  library-size factors; variance is `mu + dispersion * mu^2`.
- Genes 1–10 have a simulated fourfold increase, 11–20 a fourfold decrease;
  the remaining 480 have no simulated condition effect.
- Counts are nonnegative integers. Sample names/order and sample metadata are
  unchanged. No fitted dispersion or synthetic output is supplied to the model.

The generator is
[`generate_E02_fixture.R`](../../knowledge_pilot/generate_E02_fixture.R).
With R 4.5.2 it can be run independently, optionally to a new output file:

```sh
Rscript --vanilla benchmarks/codex_r/knowledge_pilot/generate_E02_fixture.R /tmp/E02-counts.csv
sha256sum /tmp/E02-counts.csv
```

Expected CSV SHA-256:
`f34b1c2edfc505407e8119a9d71e6b491cb82e3e252ea865b8917eb58010473c`.
Generator SHA-256:
`cfaddaa81ab5ca16809c859fbb92fbb2b48243fafe4885170c6c88a3945b2477`.
The fixture metadata records the seed, generator/hash, parameters, prior CSV
hash and reason for replacement. `E-source-snapshot.sha256` was refreshed.
The frozen official-source snapshot facts were not changed.

The reference itself is unchanged (SHA-256
`a4da84f1cc568105444085a7898b251aa7ebc4a2d78394e837736e1ad5a511ce`).
Only two numerical shape expectations were updated: the old hardcoded 20 genes
now means exactly `nrow(counts)` (500), and dimensions must exactly match the
input. All five check groups, the complete-gene-set requirement, expected
contrast signs and package pins remain enforced.

| E02 control | Result | Accepted as correct |
| --- | ---: | --- |
| Unchanged reference | **5/5** | yes |
| Wrong design (`~1`) | 4/5 | no; fails the contrast/sign requirement |
| Fractional counts (`+0.5`) | 0/5 | no |

The standard reference calls `DESeq(dds, quiet=TRUE)` with its default
**parametric** fit. There is no gene-wise-dispersion override or error bypass.
Two regenerated CSV files match the checked-in CSV byte for byte. The full
workflow was repeated twice in **each** image. Its JSON of all 500 numerical
result rows was identical in all four executions, SHA-256
`0bfc47e72844c8804b32f6cac5b2dd66ac32dbdd90881222437b5cbd3398fce2`.

## Runtime images and boundary

| Role | Tag | Docker digest / immutable image ID |
| --- | --- | --- |
| Scorer | `codex-r-benchmark:pilot-bioc` | `sha256:a4e959f2ed9af8141ecec5d95d727880fd5dfc325efc19cb55032d6d34899161` |
| Executor | `rkmcp-codex-runtime:codex-0.163.0-bioc` | `sha256:ab9eefda7d00d6872d1e62f5e3fba2a683317f6969b3ac3ab5bfa94f42c9976d` |
| Executor base | `rkmcp-codex-runtime:codex-0.163.0` | `sha256:ea7eaa089df6671c5eb7dc913fb752909dff5344aafe5f8c4974aa97e2365074` |

Both scorer and executor provide R **4.5.2**, Bioconductor **3.22**
(`BiocVersion` **3.22.0**), DESeq2 **1.50.2**, SummarizedExperiment **1.40.0**,
Biobase **2.70.0**, and GenomicRanges **1.62.0**. All existing `renv.lock`
package versions pass semantic R-version comparison (R normalizes a hyphen
separator to a dot when printing package versions).

The executor Dockerfile starts from the Codex base and copies only the donor's
installed `/opt/benchmark-library`. Its base layer prefix, Codex binary SHA-256,
`codex-cli 0.163.0`, uid/gid **65534:65534**, ENTRYPOINT, CMD, WORKDIR, environment,
volumes and other execution configuration are unchanged. The original
`exec-server --remote ... --environment-id ...` contract remains supported.
No scorer harness, oracle, hidden fixtures or references are copied. Both images
are checked for absent benchmark paths; the installed library contains only its
112 registered package directories. Per-task exports contain only the public
specification, lock, declared fixtures and any erroneous starter.

The runner keeps its existing nonroot, read-only filesystem, capability drop,
resource limits, tmpfs and controlled candidate bind mount. No package is
installed during scoring or agent execution. All R integration checks use
`--network=none`, including the R workflow executed inside the executor.

Build the executor using the pinned local source images:

```sh
docker build --pull=false --network=none -f benchmarks/codex_r/runtime/bioc.Dockerfile -t rkmcp-codex-runtime:codex-0.163.0-bioc benchmarks/codex_r/runtime
```

## Complete suite and runner fixes

Ready tasks: **H01, H04, H10; B01–B03; C01–C05; D01–D03; E01–E05**.
There are **19 tasks / 38 trials** for one repetition in the two modes.
H02–H03 and H05–H09 are not registered. R01–R12 retain their separate legacy
`--tasks all` selector and original default images.

The saved [validation.json](validation.json) contains the real outcomes of
**22 reference executions** (hard references are repeated) and **45 semantic
negative controls**. Every reference passes and every semantic mutant fails
full-task correctness. Extra hard controls also check empty/syntax-invalid
solutions and resistance to a forged score line.

Ubuntu WSL2 checks: **77 targeted pytest passed** (5 Docker cases deselected in
that invocation), then **3 real Docker integration tests passed**. Targeted Ruff
check and format check passed. The full [112-package version snapshot](runtime-packages.json)
is identical between scorer and executor. No `rkmcp-simple-*` containers/networks
or `codex-r-score-*` containers remained after the checks; unrelated resources
were not removed.

Minimal runner corrections made while validating:

- Full pilot selects all 19 registered tasks and automatically chooses the two
  Bioconductor images when E02/E03 are requested. Both roles are version-probed
  before a session is created; hard IDs are not sent to the tool-value registry.
- The tool catalog is inspected from the **same source** mounted into the MCP
  container, rather than an old controller wheel lacking `toolset`. The catalog
  child receives no application/executor API credentials. MCP code is unchanged.
- Singleton failed checks are normalized to JSON arrays, including CSV JSON
  cells. Empty checks (`[]`) remain distinct from unknown/unscored values.
- An unsupported `completed_trials` field was removed from the run-start event,
  preserving telemetry schema 1.0 and valid `telemetry.jsonl` output.
- Diagnostic trial IDs use the same suffix in planning, storage and resume.
  Completed per-trial records are recovered, while ambiguous unfinished folders
  are never automatically repeated. Ordinary task errors still allow later trials.
- The manifest records immutable image IDs, actual runtime package probes,
  verifier source hashes and public task/fixture hashes, in addition to the
  existing model/effort/toolset, Git revision/dirty fingerprint and telemetry schema.

The [experiment.json](experiment.json) beside this report is a free plan snapshot;
its `trial_plan` is not evidence of paid model execution. Each real run writes
its own manifest and saves results after every trial.

## Commands

Free offline verification and fixture reproduction inside Docker:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.full_selftest
.venv-wsl/bin/python -m pytest tests/test_bioc_benchmark.py -q
```

Real paired launch (not executed during this work):

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium --pilot full
```

Resume a directory created by this runner, without replaying finalized trials:

```sh
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple --effort medium --resume benchmarks/codex_r/results/RUN_ID
```

Both modes use `gpt-6-luna`, `medium`, the same task instructions/inputs and the
same R runtime; with-MCP retains `consolidated-v1.1` and voluntary tool use.
Only `OPENAI_API_KEY` and `OPENAI_EXECUTOR_API_KEY` are needed. No approval,
spend-control, permission JSON, F09 or Git commit was introduced.

## Observed R diagnostic

The pinned image sometimes emits native R `stack imbalance` messages while
loading the DESeq2 namespace, before any E02 data are read. This was independently
reproduced with `loadNamespace("DESeq2")`, exit status 0, in
[the namespace diagnostic](../E02-namespace-diagnostic-20261025.json).
The messages are not suppressed or claimed to be fixed. Every reference/mutant
test and the repeated parametric workflow succeeds with identical numerical
results; no grading failure attributable to this diagnostic was observed.
