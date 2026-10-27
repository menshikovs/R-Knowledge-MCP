# P1-D telemetry architecture and observability

## Scope

This audit follows the implementation in `run_simple.py`, the benchmark telemetry
schema and recorder, the Agents API client calls made by `SimpleClient`, the DuckDB
importer and schema, the analytics queries, and the Streamlit dashboard. The runner
uses `POST /v1/agents/sessions`, streams `GET /v1/agents/sessions/{id}/events?stream=true`
as SSE, and reads the session snapshot and usage through `GET /v1/agents/sessions/{id}`.
These are the endpoints the local client actually calls; this report makes no broader
claim about API fields that it does not consume.

## Observability matrix

| Signal | Source | Available? | Recorded now? | Change in P1-D / limitation |
|---|---|---|---|---|
| Registered MCP tool names | Local server registry selected by toolset | Yes | `mcp.exposure.configured.registered_tools` | Kept separate from policy and generated session configuration. |
| Policy-allowed tool names | Task/tool allowlist passed to the runner | Yes | `policy_allowed_tools` | Records the local allowlist selected for this trial. |
| Generated session tool configuration | `agent_mcp_tools()` request body | Yes | `configured_allowed_tools`, `generated_agent_tool_names` | Records tool names only, not schemas or descriptions. |
| API session response tool echo | Optional `agent.tools` in `POST /v1/agents/sessions` response | Conditional | `mcp.exposure.response` (`source=agents_api`) | Name-set equality checks whether the response echoed the requested configuration. It does not prove remote tool discovery or runtime availability. If absent, status/names/match remain unknown. |
| Remote MCP discovery list | Agents API response/stream | No authoritative list seen by this client | `remote_discovery_status=unknown`, names `null` | The post-trial server audit records only `list_tools_requests`; `mcp.discovery.completed` is not treated as a discovered-name list. |
| Agent-visible tool call identity and order | SSE event JSON: `type`, `sequence_number`, `item.type/id/name/status` | Yes, for streamed items | `agent.tool.*` stores a locally assigned call ID, bounded tool name/class, item type, sequence, outcome and stream sequence. | The original item ID is used in memory to pair start/end but is not persisted in generic agent telemetry. MCP also has client sequence IDs and a separate server call number. |
| MCP call starts and terminal outcomes | SSE `agent.session.turn.item.added` / `.done`; MCP server log projection | Yes, when each side emits it | `mcp.tool.*` retains client/server observations separately. | Client/server linking is ordinal and explicitly `ordinal_unconfirmed` when count and tool-name order align; it is never a confirmed shared call ID. |
| Non-MCP tool classes | SSE item `type` and optional `name` | Yes, for items present in the stream | `agent.tool.*` classes MCP, tool search, web, browser, terminal, file search or other. | Only observable items are counted. The classification does not establish complete coverage of external retrieval mechanisms. |
| Structured tool input | SSE item payload in process memory | Present in streamed event, but not needed for these measurements | No raw arguments are stored in telemetry or DuckDB. MCP requests retain only existing bounded fingerprints/metrics. | No raw input, source code, command, or schema is added. |
| Structured tool output | SSE item payload in process memory; safe MCP response projection | MCP outputs are available to the existing projection; other outputs depend on item type | MCP evidence records allowlisted package/version/repository/verification facts and official URLs. Other tool output is scanned only for allowlisted official URL mentions, with access status `unknown`. | Raw response text/pages are not persisted. A URL in arbitrary output is not evidence that its page was fetched. |
| Execution status and timing | Stream item status, sequence and local timestamps; MCP server timing when present | Yes, partially | Normalized success/error/unknown outcome, stream sequence, event time and same-clock durations where supplied. | No cross-clock latency is inferred. Older server records without timestamps cannot be ordered and produce no server lifecycle event. |
| Source URLs returned by MCP | Closed MCP response projection linked to the client item | Yes, when projection contains an allowlisted official URL | `agent.url.mentioned` with `source_access_status=mcp_response_observed`; version facts use `agent.evidence.observed`. | This proves a projected URL/fact appeared in the observed MCP response, not that the agent independently browsed the cited web page. |
| Final-answer claims and citations | Exported `artifacts/answer.json` | Yes, when artifact exists and passes bounded parsing | Package/version/feature/caveat IDs and official URL identities only; final-answer URLs are `url_mention_only`. | Rationale and free prose are excluded from the new telemetry projection. Existing answer artifacts remain as before. |
| Intermediate agent messages/reasoning | SSE event payload | Some event data may be present in memory | No message or reasoning text is written to new `events.json`, JSONL telemetry, or `agent_telemetry`. | Hidden reasoning is not inferred or reconstructed. |
| Final response artifact | Runner artifact export | Yes, if exported | Existing `answer.json` remains in the trial artifact directory; DuckDB stores artifact path, checksum and size, not its contents. | The audit reads only bounded answer claim fields and never rewrites the artifact. |
| Token usage and cost | Session snapshot/turn-completed event, where fields are returned | Conditional | Usage is retained in result/CSV and trial telemetry; absent usage/cost is marked unavailable/null. | No usage or cost is estimated from text or MCP byte counts. |
| Model and reasoning effort | Runner configuration plus validated session response | Yes | Experiment/trial metadata; model and effort are checked against the response. | Tool telemetry does not claim that model internals or hidden reasoning effort are observable. |
| Artifact export and cleanup | Runner artifact sealing and cleanup lifecycle | Yes | Existing export and cleanup events, with bounded statuses and error codes. | No R source, package script, or saved answer is executed by the audit/importer. |

## P1-D event additions

Schema 1.1 adds `agent.tool.started`, `.completed`, and `.failed` for all
observable agent tool items; `mcp.exposure.configured` and `.response` for the
three distinct exposure stages and the optional API echo; `agent.evidence.observed`
for closed MCP response facts; `agent.url.mentioned` for returned/output/final-answer
URL identities; and `agent.answer.claims_observed` for bounded final claim IDs.
Events use closed field validators. The importer accepts telemetry schema 1.0 and
1.1 and stores the new projections in additive DuckDB table `agent_telemetry`
(analytics schema 5). The Streamlit dashboard adds an **Agent & Evidence** view;
older runs show unavailable telemetry rather than measured zeroes.

The evidence audit compares answer claims with two separate sources: frozen
benchmark references and actual projected tool-result facts. A mismatch with a
frozen version is a reference mismatch; it is not evidence that the agent ignored
a tool response. URL presence in the answer is separate from observed response
access. Historical runs remain schema 1.0 and are not backfilled with events that
were never recorded.

## Retention and security boundaries

- New stream `events.json` contains bounded event/item metadata only; messages,
  reasoning, command text, working directories, tool arguments and raw tool output
  are omitted.
- JSONL telemetry accepts only fields declared in the schema. MCP facts come from
  the existing response projection. URL identities are restricted to reviewed
  official hosts and exclude query strings and fragments.
- The evidence audit bounds JSON/JSONL sizes, validates telemetry events, rejects
  run/trial path components that are not identifiers, and emits only validated
  package/version/official-URL identities from answer artifacts.
- DuckDB stores the closed telemetry projection. It does not copy raw event items,
  arguments, response bodies, or answer contents.
- Known credentials and API relay URLs continue to be scrubbed. Unknown secret
  formats cannot be guaranteed detectable; no new raw payload storage is added.

## Historical D01 interpretation

In the enabled run, the saved client and server observations both show zero MCP
calls; `list_package_functions` was allowed but was not observed as called. The
answer says `termr 0.1.0` while the frozen benchmark version is `1.0.1`. The
historical telemetry contains no version-specific MCP response evidence, so this
is a pinned-reference mismatch with insufficient tool observability, not proof
that the model ignored a retrieved `1.0.1` fact. The cited CRAN package URL alone
does not establish page access.

In the disabled run, 15 canonical MCP calls are observed, while raw lifecycle
events contain 15 starts, 22 completions and 8 failures across client and server
sources. The counts describe different source/lifecycle observations, not 30
distinct calls. Client/server links are ordinal and unconfirmed. The answer's
`climenu 0.2.0` matches the pinned version and documentation identity; its source
URL is a version-specific official CRAN tarball rather than the frozen package-page
URL. Historical responses do not preserve the exact version/source facts delivered
to the agent, so evidence support and source-page access remain unknown.

These are one-trial historical observations per condition and do not establish a
causal effect. The bounded replication status and validated command shapes are in
`p1d_replication_results.md`.

## Implementation impact

P1-D changes Python benchmark telemetry/analytics only. No Rust implementation,
scorer logic, frozen evidence, recorded B1 result, or existing rescore report was
changed.
