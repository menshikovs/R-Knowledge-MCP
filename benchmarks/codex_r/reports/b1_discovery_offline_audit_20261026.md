# B1 Discovery offline audit — 2026-10-26

Run: `20261026T104750Z-f78eabf1`  
Audit scope: locally preserved run outputs, V2 scorer and frozen Knowledge Pilot metadata only.

## 1. Executive summary

The run completed all 12 planned trials. Six were automatically scored and six were marked `unsupported_for_automatic_scoring`: all four D03 trials and both D01-R2 trials. The six unsupported results are reproducible from the saved `answer.json` artifacts and the saved V2 scores.

Two issues explain most of the audit findings:

1. In D03, every answer selected `pointblank` and included the feature ID `cross_record_rules`. The frozen candidate table lists that ID as required for `validate`, but not for `pointblank`. V2 treats every feature ID outside `required_features` as unsupported, so the identical extra ID made all four otherwise passing D03 scores unsupported. The local frozen files do not contain the pointblank documentation text needed to decide whether the claim is factually true. This is an evidence-coverage / scorer-contract problem; a factual false positive is not proven from retained evidence.
2. `classify_trial()` maps an unsupported scorer status with no specific reason to `R_RUNTIME_ERROR`. Thus five of six unsupported results are mislabeled as candidate R runtime failures despite terminal turns and no recorded R exception. In D03-R2-Control a partial `get_package(pointblank)` result also contributes `source_unavailable` as the primary error. The retained answer still recommends pointblank; a causal effect on that answer is not established.

Across all trials, 59 `get_function_docs` calls returned `docs_not_found` (33 Control, 26 Treatment). Retained call records identify 59 distinct argument fingerprints, but the safer observation projection preserves package/function identity for only 42 of them. Those 42 are mostly exploratory or alias-like names; without the corresponding package documentation snapshots, the audit cannot distinguish nonexistent functions from spelling, namespace, version, or provider-coverage problems.

Treatment has better aggregate call outcomes in this one run (52 successful calls of 79 versus 45 of 80 under the metrics definition, plus one partial Control call). It also has fewer `docs_not_found` errors (26 vs 33). These are descriptive observations, not evidence that the changed server description caused them. The D01-R2 pair has different answers and check outcomes, but both still fail automatic scoring; no causal attribution to MCP is justified.

## 2. Experiment validity and evidence boundaries

- `experiment.json` records 12 trials, two conditions and a balanced paired order. Condition server-description digests differ; the advertised interface, toolset and schemas have the same recorded digests.
- All four C01 trials were scored 5/5 and made no MCP calls. MCP was used in all D01 and D03 trials.
- Only 2 of 6 planned pairs are reported as score-comparable in `b1_comparison.json`; both are C01 pairs. D01-R1 is scored in both conditions but does not appear in that file's `scored_pairs` count; D01-R2 and both D03 repetitions are not comparable because at least one side is unsupported. Do not calculate an overall score delta from the six unsupported trials.
- D01 and D03 used `knowledge-pilot-v2`; C01 used the legacy scorer. Run metadata records scorer, task, prompt and condition-description digests. The audit did not modify or recompute any historical score.
- The frozen D01/D03 metadata preserves source URLs, versions and retrieval time, and the verifier preserves candidate facts and reference answer JSON. It does not preserve the full cited package documentation pages. Factuality beyond those stored facts is therefore sometimes indeterminate.
- No new trials, model/API sessions, Docker operations or CRAN/Bioconductor requests were made.

## 3. Per-trial scoring audit

| Trial | Saved scorer outcome | Check findings | Unsupported feature/caveat ID | Audit interpretation |
|---|---|---|---|---|
| D03-R1-Control | unsupported | Schema 1/1; factual 4/4; identity 2/2; source 3/3; unsupported-claim check failed | `cross_record_rules` | Claim is outside pointblank's frozen `required_features`; documentation content needed to assess truth is not retained. |
| D03-R1-Treatment | unsupported | Same checks as D03-R1-Control | `cross_record_rules` | Same repeated trigger. |
| D03-R2-Control | unsupported | Same checks as other D03 trials | `cross_record_rules` | Same repeated trigger; additionally one partial pointblank package lookup returned `source_unavailable`. |
| D03-R2-Treatment | unsupported | Same checks as other D03 trials | `cross_record_rules` | Same repeated trigger. |
| D01-R2-Control | unsupported | Schema pass; factual 3/4 (`documented_limits` fail); identity pass; source 2/3 (`official_documentation_url` fail); unsupported check fail | `keyboard_single_multi_select`; required `some_apis_experimental` caveat omitted | Extra feature is absent from termr's frozen required list; documented truth is not determinable offline. Missing caveat is an answer omission, not an unsupported claim. |
| D01-R2-Treatment | unsupported | Schema pass; factual 4/4; identity pass; source 2/3 (`official_documentation_url` fail); unsupported check fail | `keyboard_single_multi_select` | Adds the required experimental-API caveat and scores factual correctness 4/4, but the same extra feature ID still trips unsupported-claim logic. |

The exact relevant answer fragments are limited to the claim text needed for this audit: D03 says “`rows_distinct()` checks cross-row uniqueness”; D01-R2 describes keyboard navigation and keyboard-toggleable/composable checkboxes for multi-select. In the structured answers, the corresponding extra feature IDs are `cross_record_rules` and `keyboard_single_multi_select`.

### Unsupported-claim classification

| Claim | Class from retained evidence | Evidence and limits |
|---|---|---|
| D03 pointblank `cross_record_rules` / `rows_distinct()` cross-row claim (all four trials) | `evidence_coverage_gap`; factuality `not_determinable` | Not in pointblank's `required_features`; the files retain official resource URLs and response verification metadata, but not the documentation text. No contradiction is retained. |
| D01 termr `keyboard_single_multi_select` (both R2 trials) | `evidence_coverage_gap`; factuality `not_determinable` | Not in termr's `required_features`; local evidence has URLs but no termr page body. The D01 contract permits this feature ID but does not map it to a candidate package. |
| D01-R2-Control missing `some_apis_experimental` | Not an unsupported claim | It is a required caveat in the frozen candidate facts and appears in the Treatment answer, but not Control. This explains the documented-limits check failure. |

No claim was established as factually wrong from saved evidence. No factually verified claim was proven to be a scorer false positive. However, a concrete scorer-design defect is reproducible: the field called `required_features` is used as a complete allow-list (`supplied_features - required_features`), so any additional task-allowed feature is labeled unsupported without checking whether frozen documentation supports it. This is sufficient to explain every D03 unsupported status and both D01-R2 unsupported statuses, but it does not establish the truth of those claims.

The documentation URL failures in D01-R2 are reproducible too: both answers use the CRAN package `index.html` URL, while the frozen documentation resources list the termr PDF and reference-manual HTML URLs. The source URL check passes; the documentation URL equality check fails. This is a source-selection error under the stored scorer contract, not evidence that the package lacks documentation.

## 4. D03 systematic failure

All four answers choose `pointblank` 0.12.4, use an official source/documentation URL accepted by the frozen resource catalog, and pass the factual, version/repository and source-quality dimensions. All provide the same four feature IDs and the same caveat ID. The saved candidate table requires `declarative_rules`, `pipeline_validation` and `row_level_failure_reports` for pointblank; the answer adds `cross_record_rules`. `_score_d()` calculates `unfrozen_claims` as any supplied feature/caveat absent from those required lists, then reports `candidate_claims_in_frozen_evidence=fail` and makes the overall status unsupported.

The task schema allows `cross_record_rules` as a feature ID, but this alone does not prove pointblank implements it. Conversely, the candidate table's required list is not a complete per-package supported-feature inventory. The retained materials therefore show why the checker rejected the answer, but cannot settle whether the claim is true. Do not call the four unsupported results factual errors or proven scorer false positives.

## 5. D01-R2 Control/Treatment

Both answers choose termr 1.0.1 and use the same package-index URL as the documentation URL, so both fail the frozen documentation-URL check. Both include the additional `keyboard_single_multi_select` ID, which triggers unsupported-claim status under the same required-list comparison.

The answer content differs. Control omits `some_apis_experimental` from caveats and fails documented limits (3/4 factual checks); Treatment includes it and passes (4/4). Treatment also explicitly mentions experimental APIs. Both still have no automatic result because the common unsupported feature ID remains and the documentation URL check fails.

The MCP call profile differs as well: R2 Control made 36 calls, including 22 `docs_not_found`; Treatment made 32, including 16 `docs_not_found`. Both used package search, package lookup and function documentation; Treatment also made one successful `search_r_documentation` call, while Control did not. Those observations show different tool-use paths, not that MCP caused the difference in caveat selection, URL choice or answer quality. Model variation, sequence and the changed server description remain confounded in this small paired sample.

## 6. `get_function_docs` and the 59 `docs_not_found` results

### Counts and retained identities

| Condition | Calls | Distinct fingerprints | Successful | `docs_not_found` | Other application errors | Exact repeats | Similar calls | Page-truncated calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Control | 67 | 64 | 34 | 33 | 0 | 3 | 58 | 11 |
| Treatment | 65 | 60 | 39 | 26 | 0 | 5 | 53 | 13 |

The 59 failures have 59 distinct argument fingerprints. The observation projection retains package/function identity for 42 events: termr 28, climenu 12, validate 2. Seventeen failures have no package/function identity in the projection. There were no identical retries of a failed docs request; there were many similar requests, consistent with attempts using alternate names. “Similar” does not prove a retry was a correction.

### Taxonomy

| Possible cause | Audited count | Finding |
|---|---:|---|
| Function absent from package | Not determinable | A `docs_not_found` response establishes retrieval failure, not absence from the package. No complete local source/manual snapshots are retained. |
| Wrong or guessed function name / alias | Likely for a subset; exact count not determinable | Projected names include clusters of lexical variants (especially termr and climenu). This is a signal of exploratory naming, not proof that any particular function is invalid. |
| Wrong package | Not determinable | Package names are projected for 42 calls and are plausible task candidates; the 17 unprojected calls prevent full review. |
| Namespace/re-export mismatch | Not determinable | Request records do not preserve enough source-level resolution detail. |
| Version incompatibility | Not demonstrated | Projected termr and validate requests include versions 1.0.1 and 1.1.7 respectively; other versions are missing for some records. No recorded `version_mismatch` code explains these 59 errors. |
| Documentation/provider limitation | Possible, not countable | Cannot separate from a genuinely missing function without provider diagnostics or preserved manual content. |
| Temporary upstream failure | Not supported as an explanation for these 59 | Their normalized code is `docs_not_found`, not timeout/rate-limit/source-unavailable. A separate partial `get_package` event is discussed below. |
| Insufficient data | 59 cannot be assigned to definitive root-cause classes | 17 call identities are absent, and even for the other 42 the manuals are not frozen locally. |

Do not report all 59 as infrastructure failures. They are application-level `docs_not_found` results. The call-level CSV identifies 59 distinct requests, but it cannot establish whether the queried functions exist or documentation is available through another interface.

Projected names for the 42 identifiable errors (version `?` means the projection did not retain a requested version):

| Package/version | Requested function names |
|---|---|
| climenu 0.2.0 | `choose_menu`, `climenu`, `climenu_menu`, `multi_menu`, `multi_select_menu`, `multiple_menu`, `multiple_select`, `select_menu`, `single_menu`, `single_select` |
| climenu version unknown | `choose`, `climenu` |
| termr 1.0.1 | `check_box`, `check_box_group`, `check_list`, `checkbox_group`, `checkbox_set`, `checklist`, `choice_list`, `key_select`, `list_view`, `menu`, `menu_screen`, `menu_select`, `multi_select`, `multiselect`, `new_app`, `run_app`, `select`, `select_input`, `select_list`, `select_many`, `select_menu`, `selection_list` |
| termr version unknown | `choice`, `menu`, `new_app`, `select`, `select_input`, `termr_app` |
| validate 1.1.7 | `violations` |
| validate version unknown | `violations` |

These are error-event request names only. The 17 unprojected requests are not represented in this list, and the list does not assert that any function is absent.

## 7. Other tool effectiveness

| Tool | Control | Treatment | Notes |
|---|---:|---:|---|
| `get_package` | 9 calls: 7 verified, 1 partial, 1 `not_configured` error | 7 calls, all verified | D03-R2-Control call 1 for pointblank returned a partial result, 2 sources, `verification_status=partial`, with `source_unavailable`; the call itself is recorded as `ok`, not failed. |
| `search_packages` | 4/4 verified | 5/5 verified | No application errors. |
| `search_r_documentation` | Not used | 2 calls: 1 successful, 1 `invalid_input` | One input rejection in D03-R1-Treatment; not evidence of provider outage. |
| `get_function_docs` | 34/67 successful; 33 not found | 39/65 successful; 26 not found | 59 total not-found responses. Page truncation was recorded on 11 and 13 calls respectively; output-budget truncation was zero. |

The errors after failed documentation searches were not followed by identical calls (`mcp_repeated_after_error=0` in both conditions), though the agent did make similar-name calls. The aggregate evidence does not preserve enough output text to assess whether successful docs were actually used in the final answer.

## 8. Error-classification audit

`benchmarks/codex_r/telemetry/errors.py::classify_trial()` maps any non-scored status not explicitly covered by `SCORER_REASONS` to `R_RUNTIME_ERROR`, except `scoring_error`, which becomes `SCORER_INFRA_ERROR`. The six unsupported scorer results have no scorer reason code, so five get a primary error with `origin=candidate`, `category=r_runtime`, `source_code=unsupported_for_automatic_scoring`. Their records show completed turns, `error=None`, successful executor exit and no R exception. The classification conflates scorer abstention with runtime failure.

D03-R2-Control is the exception because it also has an actionable upstream diagnostic. Its `get_package(pointblank)` call returned a partial verified response with `source_unavailable`; `classify_trial()` promotes that MCP diagnostic ahead of the scorer failure because the overall status is unsupported. The model still produced a schema-valid answer recommending pointblank, and every scored dimension other than unsupported claims passed. The partial lookup may have affected available information, but stored evidence does not establish an effect on the final answer.

The likely minimal taxonomy fix is to give `unsupported_for_automatic_scoring` a separate scorer/unsupported category and reason code, preserve it as an abstention, and avoid treating it as an agent runtime failure when deciding whether an MCP error is primary. Regression cases should cover (1) an unsupported scorer result without runtime exception and (2) an unsupported result plus a recoverable partial MCP `source_unavailable` event. This audit did not change the classifier or historical results.

## 9. Control/Treatment findings

| Measure | Control | Treatment | Descriptive delta |
|---|---:|---:|---:|
| MCP calls | 80 | 79 | -1 |
| Successful calls (metrics definition; partial separated) | 45 | 52 | +7 |
| Application-error calls | 34 | 27 | -7 |
| Partial calls | 1 | 0 | -1 |
| `docs_not_found` | 33 | 26 | -7 |
| `get_function_docs` successful | 34/67 | 39/65 | 50.7% vs 60.0% |
| Exact repeated calls | 3 | 5 | +2 |
| Calls after a previous error with identical arguments | 0 | 0 | no difference |
| MCP adoption in C01 | 0/4 trials | 0/4 trials | none |
| MCP adoption in D01/D03 | 4/4 trials | 4/4 trials | none |

Fingerprint-distinct total requests across all tools were 77 Control and 74 Treatment (80 and 79 calls minus 3 and 5 exact repeats). Average trial duration was 117.7 seconds Control and 100.3 seconds Treatment; by task, means were C01 57.3 vs 56.1 seconds, D01 133.4 vs 129.4, and D03 162.4 vs 115.5. These small samples include a 192.1-second D03-R2-Control trial and several unsupported outcomes, so duration differences are descriptive only. The comparison artifact marks only the two C01 pairs comparable; D01-R1 is scored in both conditions but `score_comparable=false` in the artifact.

Task totals show why the aggregate should not be read as a clean treatment effect: D01 Control made 55 calls and had 32 docs-not-found calls, while D01 Treatment made 50 calls and had 24; D03 Control made 25 calls with 1 not found, while D03 Treatment made 29 calls with 2. Trials within a task are repeated observations, and tool calls within each trial are dependent. There are only two repetitions per task/condition, several scores are unsupported, and the pairwise comparison artifact marks only C01 pairs as score-comparable. No inference of statistical significance or causality is warranted.

Answer quality: C01 was 5/5 in all four trials. Both D01-R1 answers were scored fully correct; D01-R2 and all D03 trials were unsupported, so those answers cannot be pooled into a valid score comparison. The Treatment D01-R2 answer passes documented limits where Control fails, but both remain unsupported and fail the documentation URL check. This is an observed answer difference, not an established Treatment effect.

## 10. Prioritized engineering recommendations

1. **Separate required facts from allowed documented claims.** Extend frozen per-package candidate data with source-backed `supported_features`/`supported_caveats` (or equivalent), preserving the current required subset. Compare claims against the supported inventory and distinguish unsupported from unlisted/unknown. Add focused scorer cases for D03 pointblank `cross_record_rules`, D01 termr `keyboard_single_multi_select`, and a genuinely unsupported ID.
2. **Fix unsupported scorer error classification.** Give scorer abstention its own reason/category; do not emit `R_RUNTIME_ERROR`. Keep recoverable/partial MCP events as contributing diagnostics unless evidence shows they caused an agent outcome failure.
3. **Improve docs-not-found observability.** Preserve safe package, version, repository and function identifiers in the bounded projection for every event; include a normalized provider diagnostic that distinguishes lookup miss from missing manual/source, without recording raw payloads.
4. **Reduce exploratory calls.** Use package metadata/function indexes to validate names before repeated `get_function_docs` lookups. Log corrected-name attempts distinctly from ordinary similar requests so retries can be evaluated.
5. **Give the model canonical documentation URLs.** D01-R2 used the package index where the scorer expects the manual URL; include the source/manual distinction in the task or retrieved result.
6. **Keep experiment conclusions pair-aware.** Mark unsupported pairs explicitly and report call-level changes as descriptive. Compare answer dimensions only where both sides are scored under the same contract.

## 11. Remaining uncertainty

- The full archived termr and pointblank manuals are not present in the frozen evidence files inspected; truth of the extra feature claims cannot be conclusively adjudicated offline.
- Seventeen `docs_not_found` requests have no projected package/function identity; the cause of all 59 cannot be assigned to definitive classes.
- Sanitized telemetry does not show whether each successful documentation result changed the final answer or whether the partial pointblank lookup changed D03-R2-Control's recommendation.
- The observed Control/Treatment differences cannot isolate instruction effects from generation variability or call-level dependence.
- Token and cost fields are unavailable in the saved results; no cost comparison is supported.

## 12. Reproducibility notes

Primary local artifacts inspected: run `results.json`, `experiment.json`, `b1_comparison.json`, trial `result.json` and six `artifacts/answer.json` files, `mcp_calls.csv`, `mcp_metrics.csv`, `mcp_observations_v2.jsonl`, `knowledge_pilot_v2.py`, `telemetry/errors.py`, D01/D03 task contracts, candidate facts, metadata and reference JSON. Metrics in this report are projections and aggregates only; raw tool payloads and full transcripts are not reproduced.

