# P1-E — Offline audit of function discovery, evidence and scorer diagnostics

Generated 2026-10-27T09:49:49Z. Offline only: no R, Docker, model, Agents API, live MCP request or network access.

## 1. Executive summary

Enabled run `20261027T092234Z-5d712f1d` has 28 canonical MCP calls and scores 3/4; only `official_source_and_docs` fails. Nine `list_package_functions` calls returned without RPC errors, but all nine are recorded partial and unverified (0 fully successful, 9 partial). Saved telemetry cannot verify discovery-to-docs linkage because request names and response aliases were not retained.

The answer’s `termr 1.0.1` matches the frozen candidate and resource version. The source archive URL is accepted. The documentation URL is an official CRAN package index, but the frozen scorer accepts only the pinned documentation PDF/reference-manual URLs; exact URL membership fails.

The dashboard’s empty observed-version field is explained by a telemetry mapping defect: the projector discarded provider `package_version`, and the evidence emitter read only `version`. The old raw responses are absent, so this does not prove that historical responses contained 1.0.1. The projection is fixed for future events; no historical data was backfilled.

## 2. Data sources and completeness

Read enabled `20261027T092234Z-5d712f1d` and disabled `20261027T091937Z-29e767cb` saved D01 runs, P1-D reports, scorer source, candidate/frozen-resource files and D01 contract. Enabled telemetry parsed completely: 220 valid/deduplicated schema-1.1 events, no importer issues. `events.json` is the redacted export and strips commands/output. The V2 observation file is absent for the legacy scorer. No historical artifact changed.

## 3. Verified MCP exposure

Registry 16; policy allowlist and generated session config 13. Agents API echoed 13 configured names with `session_config_match=true`. Server audit: {'list_tools_requests': 1, 'call_tool_requests': 28, 'tool_names': ['get_function_docs', 'get_package', 'list_package_functions'], 'rejected_requests': 0}. Remote server-discovered names remain unknown. Used tools: `{"get_function_docs": 17, "get_package": 2, "list_package_functions": 9}`.

## 4. Canonical tool timeline

Reused `analytics.import_results.import_calls`: 28 client and 28 server observations; canonical source `server_telemetry`, 28 calls. All cross-side correlations are `ordinal_unconfirmed`, not proof of request identity. Full bounded timeline: [CSV](p1e_discovery_call_timeline_20261027.csv). Arguments, queries, function identifiers, versions and response projections were not persisted.

| # | UTC completion | Tool | Outcome | Partial / verification | Error | Package |
|---:|---|---|---|---|---|---|
| 1 | 2026-10-27T09:24:21.887Z | `get_package` | ok | False / verified | — | termr |
| 2 | 2026-10-27T09:24:26.419Z | `list_package_functions` | ok | True / partial | — | termr |
| 3 | 2026-10-27T09:24:28.787Z | `list_package_functions` | ok | True / partial | — | termr |
| 4 | 2026-10-27T09:24:30.762Z | `list_package_functions` | ok | True / partial | — | termr |
| 5 | 2026-10-27T09:24:32.168Z | `get_function_docs` | ok | False / verified | — | termr |
| 6 | 2026-10-27T09:24:42.597Z | `list_package_functions` | ok | True / partial | — | termr |
| 7 | 2026-10-27T09:24:45.799Z | `get_function_docs` | ok | False / verified | — | termr |
| 8 | 2026-10-27T09:24:45.815Z | `get_function_docs` | ok | False / verified | — | termr |
| 9 | 2026-10-27T09:24:45.819Z | `get_function_docs` | ok | False / verified | — | termr |
| 10 | 2026-10-27T09:24:45.828Z | `get_function_docs` | error | None / failed | docs_not_found | unknown |
| 11 | 2026-10-27T09:24:45.831Z | `get_function_docs` | ok | False / verified | — | termr |
| 12 | 2026-10-27T09:25:00.861Z | `get_function_docs` | ok | False / verified | — | termr |
| 13 | 2026-10-27T09:25:00.865Z | `get_function_docs` | ok | False / verified | — | termr |
| 14 | 2026-10-27T09:25:00.868Z | `get_function_docs` | ok | False / verified | — | termr |
| 15 | 2026-10-27T09:25:00.870Z | `get_function_docs` | ok | False / verified | — | termr |
| 16 | 2026-10-27T09:25:00.879Z | `get_function_docs` | error | None / failed | docs_not_found | unknown |
| 17 | 2026-10-27T09:25:00.882Z | `get_function_docs` | ok | False / verified | — | termr |
| 18 | 2026-10-27T09:25:09.819Z | `get_function_docs` | error | None / failed | requested_version_unavailable | unknown |
| 19 | 2026-10-27T09:25:09.822Z | `get_function_docs` | error | None / failed | requested_version_unavailable | unknown |
| 20 | 2026-10-27T09:25:09.824Z | `get_function_docs` | error | None / failed | requested_version_unavailable | unknown |
| 21 | 2026-10-27T09:25:09.827Z | `get_package` | ok | False / verified | — | termr |
| 22 | 2026-10-27T09:25:20.592Z | `list_package_functions` | ok | True / partial | — | termr |
| 23 | 2026-10-27T09:25:20.598Z | `list_package_functions` | ok | True / partial | — | termr |
| 24 | 2026-10-27T09:25:20.605Z | `list_package_functions` | ok | True / partial | — | termr |
| 25 | 2026-10-27T09:25:20.613Z | `list_package_functions` | ok | True / partial | — | termr |
| 26 | 2026-10-27T09:25:20.619Z | `list_package_functions` | ok | True / partial | — | termr |
| 27 | 2026-10-27T09:25:22.717Z | `get_function_docs` | ok | False / verified | — | termr |
| 28 | 2026-10-27T09:25:22.719Z | `get_function_docs` | ok | False / verified | — | termr |

## 5. Nine discovery calls

Sequences [2, 3, 4, 6, 22, 23, 24, 25, 26] target recorded `termr` / `cran`. All have RPC status `ok`, `partial=true`, `verification_status=partial`, and source_count 2. Metrics count 9 partial and 0 fully successful results. One identical repeat is recorded. Exact/alias/fuzzy matches, query/version/pagination arguments and returned alias/topic identifiers are unknown.

## 6. Seventeen documentation calls

17 attempts: 12 successful and 5 errors. The errors are 2 `docs_not_found` and 3 `requested_version_unavailable`; the latter three have `version_mismatch=true`. All five failed fingerprints are distinct. One successful request repeats identically; three calls report page truncation. Eight successful docs calls follow an earlier error, but lookup names and suggestion links are unknown.

## 7. Discovery-to-docs linkage

No transition is verified. No safe response aliases/topics or docs-request function identifiers were persisted. All 17 docs calls are `insufficient_observability`; no call is classified speculative or linked based on chronology. Misses after a discovered identifier are unknown.

## 8. Version fact provenance

The answer version matches frozen `termr 1.0.1`; 27 `agent.evidence.observed` events have `package_version=null` (one fewer event than the 28 canonical MCP calls). Thus the version matches frozen reference but is not supported or contradicted by an observed tool version; status is `insufficient_observability`. The raw historical response is unavailable, and ordinal-only correlation does not identify which call lacks a fact event.

Root cause: the provider field is `package_version`, `_project_response` allowed only `version`, and `emit_projected_client_evidence` copied only projected `version` to the event. The run has no V2 projection JSONL because `d-recommendation-2` is outside the versioned scorer allowlist.

## 9. Command execution and source access

The redacted executor data records 8 command_execution observations: 7 completed with exit code 0 and 1 failed with exit code 1; 18 output-delta events have no payload bytes. Command categories/arguments, stdout/stderr, network use, HTTP outcomes and extracted facts are unknown. Process exit is not HTTP retrieval evidence.

| URL | Observation | Classification | Retrieval proved |
|---|---|---|---|
| `https://cran.r-project.org/src/contrib/termr_1.0.1.tar.gz` | tool_output:unknown, answer:url_mention_only | `url_reference_only` | no |
| `https://cran.r-project.org/web/packages/termr/termr.pdf` | tool_output:unknown | `observability_unknown` | no |
| `https://cran.r-project.org/web/packages/termr/index.html` | answer:url_mention_only | `url_reference_only` | no |
| `https://cran.r-project.org/web/packages/termr/refman/termr.html` | not observed | `not_observed` | no |
| `https://stat.ethz.ch/CRAN/web/packages/termr/refman/termr.html` | not observed | `not_observed` | no |
| `https://cran.r-project.org/src/base/R-4/R-4.5.2.tar.gz` | disabled_control:tool_output:unknown, disabled_control:answer:url_mention_only | `url_reference_only` | no |
| `https://stat.ethz.ch/R-manual/R-patched/library/utils/html/select.list.html` | disabled_control:tool_output:unknown, disabled_control:answer:url_mention_only | `url_reference_only` | no |

No recorded event contains an HTTP status, response body metadata, bytes or digest. The source archive and package index are URL mentions; `termr.pdf` appears in tool output with access status unknown. None proves download or page retrieval.

## 10. Exact scorer URL comparison

- Package accepted: `True`; version accepted: `True`.
- Frozen resource version matches candidate: `True`; answer version matches resource: `True`.
- Source URL recognized: `True` — `https://cran.r-project.org/src/contrib/termr_1.0.1.tar.gz`.
- Documentation URL recognized: `False` — `https://cran.r-project.org/web/packages/termr/index.html`.

The package index is official CRAN and listed as `kind=source`, but is not one of the frozen documentation URLs. Documentation URL membership is the exact failed conjunct. Scorer and frozen resources remain unchanged.

## 11. Observability gaps

- Request query, package/version/function arguments, aliases and pagination were not persisted.
- No V2 request/response projection file exists for this run.
- Client/server call links are ordinal and unconfirmed.
- Command text/output and HTTP-level retrieval metadata are absent.
- There are 27 evidence fact events for 28 canonical calls; the one-event count difference cannot be assigned to a specific call from ordinal-only correlation.

## 12. Telemetry fix

Changed `telemetry/projection.py` to map provider `package_version` into the existing closed-schema `version` field. This preserves existing `version` responses and keeps absent values null. Regression tests cover both field names and missing version. No scorer, frozen data, prompt, discovery implementation or historical run changed.

## 13. Test results

- Focused offline pytest: **9 passed, 0 failed, 1 deselected** (the deselected test needs `tmp_path`).
- Broader pytest attempt: **26 passed, 77 setup errors** because WinError 5 denied the global pytest temporary directory; these are fixture setup errors.
- `ruff check .`: **passed**, with access-denied traversal warnings.
- Full `ruff format --check .`: Ruff panicked (`Expected a ruff source file`); both changed Python files passed targeted format check.
- Offline analytics import: **220 valid events**, complete, no issues; canonical call count **28**, matching the aggregate.
- No full pytest rerun.

## 14. Remaining unknowns

Exact discovery arguments/aliases/match classes; discovery-to-docs links and speculative lookup count; historical raw response version fields; command categories/network/HTTP outcomes; independent remote tool catalog; and the call without an evidence event.

## 15. Recommendation for the next experiment

Do not start another model run until the telemetry fix is included. Then capture bounded package/version/function requests and alias/version responses for both conditions with provable call IDs or explicit uncertain ordinal links. Add bounded HTTP result metadata if retrieval matters. Use multiple randomized repetitions with identical pinned inputs; the latest 3/4 versus 1/4 pair is descriptive, not causal.
