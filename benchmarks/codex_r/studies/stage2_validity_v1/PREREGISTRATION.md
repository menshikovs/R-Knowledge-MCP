# Preregistration - stage2_validity_v1 v1.0.0

> Generated from `experiment_manifest.json` (`python -m benchmarks.codex_r.studies.stage2_validity_v1.cli render-prereg`).
> **Status: DRAFT - not registered; no confirmatory run is authorised.** Core manifest SHA-256 `4eaee4975f9b7f7cd94ed875ab1464e4b35dcb7f57c52f8a3a2a60c20fcf603e`.
> This document becomes binding only when the final manifest and this rendering are committed as the
> registration commit and the randomization seed is derived from that commit. Until then every
> value is a proposal. No confirmatory run may start before registration.

## 1. Question and hypothesis

Does making R-Knowledge-MCP available improve an agent's task performance compared with an otherwise equivalent agent without it?

* H0: mean within-task score difference (B - A) over the task population is 0.
* H1: it is not 0 (two-sided); the direction is not assumed.
* A negative or inconclusive result is a valid outcome and will be reported as such.

## 2. Estimand and outcome

* Primary estimand: Average over tasks of the within-task mean score difference B - A, by assignment of tool access (intention to treat); never conditioned on whether a tool was called.
* Primary metric: task score = passed checks / total checks of the preregistered scorer, in [0,1].
* Aggregation: mean over blocks within task, then mean over tasks (equal task weights).
* Candidate failures are scored scored as 0; missing outcomes: infrastructure_failure, scoring_error, not_executed.
* Secondary outcomes: C - B, C - A, B - A fully_correct, adoption, cost, latency.

## 3. Arms

| arm | label | MCP available | encouragement sentence | instruction SHA-256 |
|---|---|---|---|---|
| A | baseline | no | no | `e275f7d098de3ef4...` |
| B | mcp-voluntary | yes | no | `e275f7d098de3ef4...` |
| C | mcp-encouraged | yes | yes | `1b861607634c863d...` |

Arms A and B receive byte-identical instructions (SHA-256 `e275f7d098de3ef4a478d0ae6eba62d1fb8082381df62421babbcd606c026f78`); arm C adds exactly
one sentence: *"When R-Knowledge-MCP tools are connected, use them to verify package, function and version facts before relying on memory; do not call them when they cannot help."* The MCP tool descriptions in B and C are part of the treatment.
MCP tools (16): `analyze_r_project`, `analyze_r_source`, `build_r_prompt`, `check_package_version`, `check_r_compatibility`, `get_framework_docs`, `get_function_docs`, `get_package`, `get_r_documentation_section`, `get_r_prompt_context`, `get_r_workflow_guidance`, `list_package_functions`, `recommend_technology_stack`, `search_packages`, `search_r_documentation`, `validate_r_prompt`. Surface digest `ddbf572e5fd18cc6...`.

Model: `gpt-6-luna`, effort `medium` (historical default; the exact model version string must be pinned at registration).
Every other executor tool, image, limit and the scorer are identical across arms.

## 4. Information channels (egress policy)

* All arms: internal network with an observing allow-list proxy.
* Allowed destinations: arm A ['model-api'], arms B/C ['model-api', 'r-knowledge-mcp'].
* Violations: `egress_not_restricted`, `egress_unverified`, `egress_unexpected_destination`.
* Implementation status: **NOT IMPLEMENTED in the runner (plain bridge network)** - a confirmatory run is not allowed until this is implemented and tested.

## 5. Tasks

Pilot tasks (feasibility only; not an effect test):

| task | role | suite | scorer | pinned files (SHA-256 prefix) |
|---|---|---|---|---|
| D01 | exploratory_replication | knowledge-D | knowledge-pilot-v2.1 | `D01.md` e0a92d2d234e<br>`D01.json` 86ac0a4c6f2e |
| D02 | exploratory_replication | knowledge-D | knowledge-pilot-v2.1 | `D02.md` 72ba8265c4df<br>`D02.json` 3ab899f88a8c |
| D03 | exploratory_replication | knowledge-D | knowledge-pilot-v2.1 | `D03.md` 5df2fd3b36d5<br>`D03.json` be20f9c48b4e |
| C01 | recalibration | knowledge-C | knowledge-pilot-v2.1 | `C01.md` 5e7b9250a52d<br>`C01.json` 51e22f854614<br>`C01.R` 3b8022e757c1 |
| C04 | recalibration | knowledge-C | knowledge-pilot-v2.1 | `C04.md` ae01dc4939c8<br>`C04.json` 2fa1533fe08a<br>`C04.R` 0067eed9a379 |
| E02 | recalibration | knowledge-E | knowledge-pilot-v2.1 | `E02.md` 57d0a3cbe86d<br>`E02.json` 1bc5801814af<br>`E02.R` e85004acdd78 |
| E03 | recalibration | knowledge-E | knowledge-pilot-v2.1 | `E03.md` 5e7ea57a1d23<br>`E03.json` 701af8490dd3<br>`E03.R` 5e8d1909b85d |
| E05 | scorer_reliability | knowledge-E | knowledge-pilot-v2.1 | `E05.md` 130587efdbbf<br>`E05.json` 910dd7985196 |
| R01 | control | legacy-R | legacy | `task.md` 7ed1dd81045c<br>`R01.R` 1488e1cbe546 |
| H10 | control | hard | hard-v1 | `prompt.md` d298b344069a<br>`metadata.json` 46a3d624c43d<br>`H10.R` 11b5b1809af4 |

Confirmatory task rule (minimum 30 tasks; tasks meeting it today: **0**):

* verifier kept private (only its SHA-256 is committed until the study ends)
* reference solution and >= 3 wrong strategies pass/fail as expected
* >= 5 independently written correct alternatives all pass (0 false negatives)
* dimensions classified before any trial from task text only
* arm-A calibration screen: mean in [0.10, 0.90] over >= 3 trials
* outcomes of arms with MCP access never used for inclusion

## 6. Design and randomization

| design | tasks | repetitions | arms | trials |
|---|---|---|---|---|
| pilot | 10 | 3 | ABC | 90 |
| recommended_confirmatory | 30 | 3 | ABC | 270 |
| higher_confidence | 40 | 5 | ABC | 600 |

* Algorithm `blocked-latin-permutations-v1`; block = task x repetition; every arm once per block, in a seeded random order; blocks shuffled globally; fresh context per trial.
* Seed: derive_seed(sha256(core manifest), registration commit) (not yet derived).

## 7. Analysis

* Primary: task-level sign-flip test on task mean differences (exact <= 16 tasks, else Monte Carlo); block-level flip as sensitivity analysis; interval: two-stage percentile bootstrap (tasks, then blocks within task); alpha 0.05.
* Secondary family: Holm over C-B, C-A, B-A fully_correct.
* Monte Carlo permutations 19999; bootstrap resamples 5000.
* Full plan: `STATISTICAL_ANALYSIS_PLAN.md`.

## 8. Exclusions, failures, stopping, budget

* Trials with an invalidating protocol violation are excluded from the primary analysis, reported, and bounded by sensitivity analyses: `arm_a_mcp_reachable`, `arm_a_mcp_called`, `treatment_not_delivered`, `instructions_mismatch`, `model_mismatch`, `effort_mismatch`, `scorer_version_mismatch`, `egress_not_restricted`, `egress_unverified`, `egress_unexpected_destination`, `tool_allowlist_unrecorded`.
* Failures: one re-run per infrastructure failure, same assignment, at most 10% of trials. a failed or missing trial is never deleted or replaced by a different task.
* Stopping: fixed sample size; no interim looks; stop only for budget exhaustion or a safety issue.
* Budget: model spend limit `None` - not authorised - a limit must be set and approved before any paid run. Timeout per trial 900 s.
* Scorers: knowledge-pilot-v2.1, hard-v1, legacy; module digests are in the manifest. Historical results are never rescored with a new scorer.

## 9. Exploratory analyses (no confirmatory claims)

* per-stratum and per-task effects
* adoption by task
* descriptive comparison of trials with and without tool calls (confounded)
* tool-result use proxy
* token and latency tradeoffs
