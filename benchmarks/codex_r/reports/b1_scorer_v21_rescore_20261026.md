# B1 Discovery — V2.1 versioned offline rescore

Run: `20261026T104750Z-f78eabf1`  
Original results checksum: `8dab038ca58f683c377e5684546a864cd01748c3e35c60f775af644b1b4e02e0`  
V2.1 evaluator: `e714f14d915dcff42b4fb62fba62f860066a0300ef527930e1f2ca9ecc2978af`  
Claim evidence: `af2ce8d3a9ed944fa9179bcd4ae03138ffb26e1175f08471ed5ada17dadb864f`

## Summary

Read-only rescore verified 12 original trial records and answer/artifact checksums. No original result, artifact, experiment manifest, task, prompt, or condition digest was rewritten.
C01 remains under its original legacy scorer. D01/D03 use `knowledge-pilot-v2.1`; unknown claims remain unscored.

## Trial outcomes

| Trial | Original | V2.1 / retained status | Original fully correct | New fully correct | Claim state | Changes |
|---|---|---|---:|---:|---|---:|
| `b1-discovery-D03-R1-control` | unsupported_for_automatic_scoring | unsupported_for_automatic_scoring | None | None | unknown | 4 |
| `b1-discovery-D03-R1-treatment` | unsupported_for_automatic_scoring | unsupported_for_automatic_scoring | None | None | unknown | 4 |
| `b1-discovery-D01-R1-treatment` | scored | scored | True | True | supported | 3 |
| `b1-discovery-D01-R1-control` | scored | scored | True | True | supported | 3 |
| `b1-discovery-C01-R1-control` | scored | legacy_retained | True | None | legacy retained | 0 |
| `b1-discovery-C01-R1-treatment` | scored | legacy_retained | True | None | legacy retained | 0 |
| `b1-discovery-D03-R2-treatment` | unsupported_for_automatic_scoring | unsupported_for_automatic_scoring | None | None | unknown | 4 |
| `b1-discovery-D03-R2-control` | unsupported_for_automatic_scoring | unsupported_for_automatic_scoring | None | None | unknown | 4 |
| `b1-discovery-D01-R2-control` | unsupported_for_automatic_scoring | unsupported_for_automatic_scoring | False | None | unknown | 4 |
| `b1-discovery-D01-R2-treatment` | unsupported_for_automatic_scoring | unsupported_for_automatic_scoring | False | None | unknown | 4 |
| `b1-discovery-C01-R2-treatment` | scored | legacy_retained | True | None | legacy retained | 0 |
| `b1-discovery-C01-R2-control` | scored | legacy_retained | True | None | legacy retained | 0 |

## Claim evidence results

| Trial | Supported claims | Unknown claims | Contradicted claims |
|---|---|---|---|
| `b1-discovery-D03-R1-control` | features:declarative_rules, features:pipeline_validation, features:row_level_failure_reports, caveats:broader_validation_framework | features:cross_record_rules | — |
| `b1-discovery-D03-R1-treatment` | features:declarative_rules, features:pipeline_validation, features:row_level_failure_reports, caveats:broader_validation_framework | features:cross_record_rules | — |
| `b1-discovery-D01-R1-treatment` | features:keyboard_single_multi_select, features:stable_return_values, caveats:menu_focused | — | — |
| `b1-discovery-D01-R1-control` | features:keyboard_single_multi_select, features:stable_return_values, caveats:menu_focused | — | — |
| `b1-discovery-D03-R2-treatment` | features:declarative_rules, features:pipeline_validation, features:row_level_failure_reports, caveats:broader_validation_framework | features:cross_record_rules | — |
| `b1-discovery-D03-R2-control` | features:declarative_rules, features:pipeline_validation, features:row_level_failure_reports, caveats:broader_validation_framework | features:cross_record_rules | — |
| `b1-discovery-D01-R2-control` | features:headless_app_tests, features:reactive_terminal_ui, features:stable_return_values, caveats:real_terminal_required | features:keyboard_single_multi_select | — |
| `b1-discovery-D01-R2-treatment` | features:headless_app_tests, features:reactive_terminal_ui, features:stable_return_values, caveats:real_terminal_required, caveats:some_apis_experimental | features:keyboard_single_multi_select | — |

## Revised paired comparison

| Task | Rep | Comparable | Metric | Original comparable | Delta |
|---|---:|---:|---|---:|---:|
| C01 | 1 | True | check_fraction | True | 0.0 |
| C01 | 2 | True | check_fraction | True | 0.0 |
| D01 | 1 | True | fully_correct | False | 0.0 |
| D01 | 2 | False | — | False | None |
| D03 | 1 | False | — | False | None |
| D03 | 2 | False | — | False | None |

## Error taxonomy

Scorer abstentions use `origin=scorer`, `category=evidence_insufficiency`, `reason_code=SCORER_UNSUPPORTED_CLAIMS`. Partial and provider MCP diagnostics remain in `mcp_errors`; they do not replace the scorer abstention as `primary_error`.

## Provenance and verification

- Scorer version: `knowledge-pilot-v2.1`.
- Contract digest: `6f71b49432c09c2e948aeb9c6d48a48deb89a19aac6b2b4bf1f7a57ea06dbb0d`.
- Frozen basis verified: `True`.
- Original inputs unchanged after rescore: `True`.
- Original scorer digests retained per trial: yes.
- No model, Agents API, Docker, web, CRAN or Bioconductor calls were made.
- The saved D01/D03 documentation bodies are unavailable; their unregistered claims remain unknown.
