# Benchmark telemetry (schema 1.2)

`run_simple.py` writes one structured event per line to `<results>/telemetry.jsonl`. The file
is an additional source. Schema 1.2 adds bounded local timing around session creation; schema
1.1 added closed agent-tool, exposure, evidence and answer-claim events. Trace spans and task
opportunities are versioned derived projections. Schema 1.0/1.1 files, results without JSONL,
and old answer artifacts remain readable.

| Module | Role |
|---|---|
| `schema.py` | `SCHEMA_VERSION`, event types, allowed fields, `validate_event`, `validate_stream` |
| `errors.py` | origin / category / reason_code taxonomy and trial classification |
| `recorder.py` | `RunTelemetry` (file writer), `TrialRecorder` (ids, client and server call events) |
| `aggregate.py` | per-trial and per-tool MCP metrics; CSV rows; `python -m benchmarks.codex_r.telemetry.aggregate RUN_DIR` |
| `trace_model.py` | deterministic lifecycle spans, parent relations and integrity validation |
| `opportunities.py` | researcher opportunity manifest validation and trial-level assessments |

## Identifiers

| Id | Meaning | Rule |
|---|---|---|
| `run_id` | one benchmark invocation (results directory name) | one value per file |
| `trial_id` | one task in one mode (`D01-B-1`) | belongs to exactly one run |
| `trace_id` | trace of one trial (`trace-<16 hex>`) | 1:1 with `trial_id`; run events have none |
| `call_id` | one tool call inside a trial | unique per trial; see below |

The Agents SDK gives the MCP server no call id. Calls therefore have two separate ids:
`client-call-NNNN` (seen in the agent event stream, `source: agent_stream`) and
`server-call-NNNN` (recorded by the server, `source: mcp_server`, `server_call_number`).
A server event carries `correlated_call_id` only when both sides saw the same number of calls
with the same tool names, and then `correlation` is `ordinal_unconfirmed`; otherwise it is
`unmatched`. The link is never presented as confirmed.

## Time

Every event has `timestamp_utc` (when it was observed), `monotonic_offset_ms` and `clock`.
Clocks are independent: `run` and `trial` belong to the runner, `server_process` is
milliseconds since the MCP server started. Never subtract offsets from different clocks.
`duration_ms` is always a duration measured on one clock (inside the server for tool calls).
Server events are written after the trial, when the container log is collected, so they appear
after later runner events in the file; sort by clock and offset, not by position.

Schema 1.2 records a `provider.request.started` and its terminal response/failure around the
runner's session-creation call. Its duration is the measured local call duration, not provider
internal processing time. Agent turn spans use only turn lifecycle events observable in the
agent stream. The trace projector never joins client and server tool calls by ordinal position.

## Event types

Only observable event types are emitted:

| Type | Emitted when |
|---|---|
| `benchmark.run.started` / `.completed` | start of `main()` after the task list is known / every exit path |
| `benchmark.trial.started` / `.completed` | start of a trial / after cleanup, with errors and API usage |
| `agent.session.created` | session creation returned an id |
| `agent.turn.started` / `.completed` / `.failed` | matching agent stream events |
| `agent.tool.started` / `.completed` / `.failed` | observable tool items in the agent stream; only bounded name/class/status/sequence metadata is stored |
| `agent.evidence.observed` | the closed MCP response projection contains a package/version/source fact delivered to the agent |
| `agent.url.mentioned` | an approved official URL appears in an MCP result, observed output, or final answer; access status keeps them distinct |
| `agent.answer.claims_observed` | package/version/feature/caveat identifiers projected from exported answer JSON; rationale and prose are omitted |
| `provider.request.started` / `provider.response.received` / `.failed` | local runner timing and terminal result around session creation; no request body or provider-internal timing |
| `mcp.exposure.configured` | registered, policy-allowed, request-configured and generated tool names; remote discovery remains unknown absent an authoritative API list |
| `mcp.exposure.response` | optional `agent.tools` echo in the session-creation response, recorded as an API response observation and compared with the requested allowlist |
| `mcp.tool.started` | stream item `mcp_call` added (client side) |
| `mcp.tool.completed` / `.failed` | stream item done (client, `is_error` from item status) and one per server-recorded call |
| `mcp.discovery.completed` | after the trial, from the server audit (`observation: server_audit_after_trial`, `list_tools_requests`); its timestamp is the audit time |
| `artifact.export.completed`, `scorer.started` / `.completed` | around sealing artifacts and scoring |
| `cleanup.started` / `.completed` / `.failed` | each bounded cleanup operation (`cleanup_operation`, `cleanup_status`) |

`mcp.discovery.started` is defined but never emitted: no start time of tool discovery is
observable. The existing `mcp.discovery.completed` is a post-trial server audit and records
the ListTools request count, not remote tool names. When present, the `agent.tools` field in
the session-creation response is recorded as a configuration echo. It confirms only what that
response returned; it is not an authoritative list of tools discovered by the remote runtime.
If the response omits it, the echo status and returned names remain unknown. Server calls
without a server timestamp (older server images) produce no event.

## What an event may contain

Only fields in `schema.FIELDS`; unknown fields are rejected, so arguments, MCP response text,
user code, model reasoning and credentials cannot enter by accident. MCP evidence uses the
closed `telemetry.projection.project_response` allowlist. URLs found in arbitrary non-MCP
output have access status `unknown`; a final-answer URL is `url_mention_only`. Only URLs in
projected MCP results are marked `mcp_response_observed`. New `events.json` files retain only
bounded event/item structure and drop messages, reasoning, commands, working directories,
arguments and tool output. Historical files remain untouched. `package` is written only
when a verified or partial result confirmed that exact package. The separate benchmark MCP
observation sidecar (schema 2.1) retains an allowlisted discovery query up to 8 KiB after
secret filtering, a validated function alias, page `offset`/`limit`, whether a snapshot cursor
was supplied (never the cursor itself), up to 30 validated alias names, and returned page
offsets. Server protocol call IDs are bounded and secret-filtered; client item IDs remain a
separate field. Server discovery projections are emitted only when valid benchmark run and
trial IDs are configured. The older `RKMCP_DIAGNOSTIC_FUNCTION_ALIASES=1` switch remains a
separate local diagnostic. Calls are grouped by
`argument_fingerprint`, a 12-hex keyed digest (HMAC-SHA256 with a random per-server-process key
that is never logged), so it is comparable only inside one trial. Configured credentials are also
masked in the serialized line.

## Error taxonomy

Three independent fields plus the original code:

* `origin`: component that reported it (`model`, `mcp_server`, `mcp_transport`, `candidate`,
  `scorer`, `cleanup`, `runner`, `unknown`)
* `category`: finer class (for MCP errors `not_found`, `invalid_request`, `upstream`,
  `version_mismatch`, `resource_limit`, `internal`, ...)
* `reason_code`: `MODEL_TIMEOUT`, `MODEL_GENERATION_ERROR`, `MCP_DISCOVERY_FAILED`,
  `MCP_TRANSPORT_ERROR`, `MCP_TOOL_TIMEOUT`, `MCP_PROVIDER_ERROR`, `MCP_PARTIAL_RESULT`,
  `MCP_INVALID_RESPONSE`, `R_SYNTAX_ERROR`, `R_RUNTIME_ERROR`, `ARTIFACT_INVALID`,
  `SCORER_INFRA_ERROR`, `SCORER_UNSUPPORTED_CLAIMS`, `CLEANUP_ERROR`, plus `INTERRUPTED`
  and `UNCLASSIFIED_ERROR`
* `source_code`: the machine code that was classified (`docs_not_found`, `rate_limited`,
  `turn_failed`, `exit_125`...). An unmapped code becomes `UNCLASSIFIED_ERROR` with `source_code`
  kept.

Trial level: `primary_error` (first cause of the failure), `subsequent_errors`, `cleanup_errors`
(never replaces the task error), and `mcp_errors` (every MCP error and partial result grouped by
reason, category and code with a `count`). Ordering follows pipeline stages (`order_basis:
pipeline_stage_order`) because the runner and the server share no clock: session/executor,
MCP malfunctions, turn, interrupt, artifact, scorer. "Not found", "ambiguous" and
"invalid request" MCP answers are normal tool results; they appear in `mcp_errors` but do not
become the cause of a failed trial. A provider refusal (for example `rate_limited`) stays
`MCP_PROVIDER_ERROR` even if the agent then fails to produce an artifact.

`unsupported_for_automatic_scoring` is a scorer abstention, not an R runtime failure. It is
recorded as `origin=scorer`, `category=evidence_insufficiency`,
`reason_code=SCORER_UNSUPPORTED_CLAIMS` with recoverable severity. The MCP diagnostics remain
in `mcp_errors`; a partial provider result does not replace the evidence-insufficiency cause.

MCP error shapes handled: top-level `error.code`; `errors[].error.code` (for example
`get_package` section failures); `isError=true`; `verification_status=partial` and a non-empty
`errors` list on a successful call (a partial result). `isError=false` is not "correct":
completeness is reported separately (`partial`), and `null` means the tool reports none.

## Metrics

Per trial (`overall`) and per tool (`by_tool`), also written to `mcp_metrics.csv` (tool `*` is all
tools) and to `result.json` as `mcp_metrics`. Outcomes come from server-recorded calls; the
client stream only adds calls the server never recorded.

| Metric | Definition |
|---|---|
| `mcp_calls_attempted` | max(server-recorded calls, client-observed calls) |
| `mcp_calls_failed` | server calls with `isError=true` |
| `mcp_calls_partial` | `isError=false` and known partial (`null` if no call reports completeness) |
| `mcp_calls_succeeded` | `isError=false` and not known-partial; includes `mcp_calls_completeness_unknown` |
| `mcp_calls_unresolved` | attempted calls whose outcome is unknown: seen by the client but absent from the server record, or started and never finished (Ctrl+C) |

`succeeded + partial + failed + unresolved = attempted`; nothing is counted twice.

| Metric | Definition |
|---|---|
| `mcp_latency_p50_ms`, `_p95_ms` | linear interpolation over the individual `duration_ms` of server calls (time inside the server, not network); `mcp_latency_observations` is n. p95 of fewer than ~20 calls is only indicative |
| `mcp_result_bytes_total`, `_mean` | UTF-8 bytes of the serialized MCP `CallToolResult` (`content` text plus `structuredContent`); `mcp_result_bytes_observations` is n |
| `mcp_unique_payload_bytes_total` | bytes of the `content` text when it duplicates `structuredContent` (the usual case), else text plus structured; do not treat the two copies as independent information |
| `mcp_result_tokens_estimate_total` | sum of `ceil(result bytes / 4)`; an estimate, separate from billed usage |
| `mcp_output_truncation_count` | calls whose result has `output_truncation.truncated` (response clipped to the output-size budget); `null` if any call lacks the flag |
| `mcp_page_truncation_count` | calls whose result has top-level `truncated: true` (more pages are available); `null` if any call lacks the flag |
| `mcp_verified_source_rate` | calls with `verification_status=verified` and at least one source, divided by calls that report a status (`mcp_verified_source_denominator`) |
| `mcp_version_mismatch_count` | failed calls with `version_mismatch` or `requested_version_unavailable`; `null` if any failed call has no error code |
| `mcp_repeated_identical_calls` | calls whose tool and normalized arguments were already seen in the trial (`identical` plus `identical_after_error`); `mcp_repeated_after_error` is the subset whose earlier identical call failed; `mcp_similar_calls` counts the same tool and package with other arguments |
| `mcp_cache_hit_rate` | repository HTTP lookups answered from the server's TTL cache divided by all lookups (`mcp_cache_lookups`); `null` when no call made a lookup or the server did not report it. Response time is never used as evidence |

Verification of sources, version consistency and completeness are measured independently
(`verification_status`/`source_count`, `version_mismatch`, `partial`). The server does not
inspect installed R packages, so a `verified` source says nothing about the user's installed
version. API usage is kept apart: `api_usage` has the session's input/output/total tokens, or
`null` with `status: unavailable`; cost is `null` unless the API reported it.

### Measurable now / not measurable

Measured from server events: attempted/failed/partial counts, latency, result sizes,
truncation, verification status and source count, error codes (including nested), version
mismatch codes, repeats, repository cache lookups. Not available: confirmed client-to-server
call ids, discovery timing, cache state of non-repository sources (Context7, GitHub, framework
docs, local R manual index), actual token usage when the API returns none, per-call API cost.

Raw lifecycle observations remain source-specific. In a run with 15 calls, the stream records
15 client starts and 15 client terminals; the server adds 15 terminal observations (11
successful and 4 failed). The combined raw counts are therefore 15 starts, 22 completed and
8 failed, while the canonical call count remains 15. Client/server linkage is ordinal and
unconfirmed; terminal observations are not counted as additional calls.

## Without a server log (forced stop)

If the trial is stopped before the MCP container's log is collected (a second Ctrl+C skips
`mcp_audit`), no server event exists. `summarize_trial` then reports `source:
agent_stream_only`: counts come from the agent stream's own item statuses, and every
server-only fact (completeness, latency, bytes, cache, repeats, error codes) stays `null`.

## Experiment configuration

`<results>/experiment.json` is written once per run by `run_simple.main` (never from secrets
or task data): git revision, branch and a fingerprint of uncommitted changes
(`working_tree_sha256` over paths and file contents, plus `dirty` and `changed_paths`),
MCP package version, toolset, registered and allowed tool names, `source_sha256` of `src/`
(the tree the MCP container actually executes: `start_mcp` bind-mounts it over the image), image
digests, telemetry schema version, scorer versions (D scorer and R scorer image), model,
effort, instructions variant, modes, task ids, repetitions, timeout, R version, `renv.lock`
digest and task package pins. `configuration_id` names the MCP/scorer configuration from
`knowledge_pilot/manifest.json`: `consolidated-v1` (historical, run
`20261025T083653Z-ca1d5503`, plain `docs_not_found`, original D scorer) and `consolidated-v1.1`
(current: `docs_not_found` with `alias_count` plus `available_aliases` or `closest_aliases`,
scorer `d-recommendation-2`, telemetry schema 1.0). Each with-MCP pilot trial also carries
`configuration_id` in its result record. Old results are not edited.

## Older results

`mcp_tool_aggregates.csv` has separate `output_budget_truncated_calls` and
`page_truncated_calls` counts (and corresponding `*_flags_missing` counts).
`any_truncation_calls` is the server's legacy recursive signal: any nested `truncated: true` in
the result. It can include output clipping or pagination, so it is not a substitute for either
typed count. `truncated_calls` remains as a deprecated compatibility alias for that generic
signal. New `mcp_metrics.csv` reports the two typed categories separately.
`aggregate.summarize_trial` falls back to `mcp_telemetry.calls` in an old `result.json`.
Fields that were not recorded stay `null`: completeness, source verification, repeats, cache and
version counts. Only `truncated=false` is trusted for truncation because the old flag also meant
paging. Historical numbers are never given the new fields. The saved D01 run
(`20261025T083653Z-ca1d5503`) reads this way: 55 attempted, 41 failed, 14 succeeded.

## Example (abridged; produced by a local test fixture, not a benchmark run)

```json
{"schema_version":"1.0","event_type":"mcp.tool.failed","run_id":"20260101T000000Z-example","trial_id":"D01-B-1","trace_id":"trace-fdab12c815634378","timestamp_utc":"2026-10-25T09:21:46.554Z","monotonic_offset_ms":114.236,"clock":"server_process","source":"mcp_server","call_id":"server-call-0004","tool":"get_function_docs","server_call_number":4,"is_error":true,"duration_ms":0.49,"result_bytes":1569,"error_codes":["docs_not_found"],"correlation":"ordinal_unconfirmed","correlated_call_id":"client-call-0004","repository":"cran","package":null,"verification_status":"failed","source_count":0,"partial":null,"output_truncated":false,"useful_bytes":761,"argument_fingerprint":"22d87efd972f","repeat_kind":"similar","cache_hits":1,"cache_network_requests":0}
```
