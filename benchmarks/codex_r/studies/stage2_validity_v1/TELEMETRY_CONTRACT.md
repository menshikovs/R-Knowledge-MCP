# Stage 2 Telemetry Contract and Mediator Observability

## 1. Purpose

Historical analyses treated tool usage as a binary flag (`used_mcp`) or conflated **MCP availability** (treatment assignment) with **MCP tool execution**. In Stage 2, [`telemetry.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/telemetry.py) projects canonical schema-1.2 `telemetry.jsonl` streams (`benchmarks/codex_r/telemetry/schema.py`) into seven distinct, non-interchangeable observability levels.

## 2. Seven Distinct Observability Levels

Every Stage 2 trial record (`trial_record.schema.json`) populates `telemetry` with the following hierarchy:

| Level | Field in `telemetry` | Source of Truth | Meaning |
| :--- | :--- | :--- | :--- |
| **1. Available** | `mcp_available` (`bool`) | Runner capability configuration + `run_finished.mcp_Enabled` / `mcp_server_initialized` | Whether the R-Knowledge-MCP server was wired into the trial container's MCP configuration. Must be `False` in Arm A and `True` in Arms B and C. |
| **2. Listed** | `mcp_listed` (`bool`) | `mcp_tools_listed` event (`schema 1.2`) | Whether the client discovered/listed the MCP server's tool catalogue during the session. |
| **3. Attempted** | `attempted` (`int >= 0`) | Client `mcp_tool_call_started` (plus unstarted terminal client events) | Number of distinct client-side MCP tool invocations initiated by the model. |
| **4. Completed** | `completed` (`int >= 0`) | Client `mcp_tool_call_finished` (`status == "ok"`) | Number of client-side tool calls that returned a normal completion status. |
| **5. Errored** | `errored` (`int >= 0`) | Client `mcp_tool_call_finished` (`status != "ok"`) | Number of client-side tool calls that terminated with an error status. |
| **6. Delivered** | `delivered` (`int >= 0`) | Server `mcp_server_tool_call_finished` (`is_error is False` and `output_bytes > 0`) | Number of server-side tool executions that produced a non-empty payload without server error. |
| **7. Result-Use Proxy** | `result_use_proxy` (`object`) | `compute_result_use_proxy(events, answer_text)` | Explicit lexical-overlap heuristic (`status: "not_applicable" \| "unverified_lexical_overlap"`). **Never interpreted as causal proof that the model understood or relied on the tool output.** |

### Invariant Guarantees

`telemetry.summarize_trace()` enforces and `trial_record.schema.json` validates:

- `0 <= completed + errored <= attempted`
- If a client stream is interrupted after `mcp_tool_call_started` without a matching `mcp_tool_call_finished`, `attempted` increments while `completed` and `errored` do not (`interrupted_calls = attempted - completed - errored`).
- If a partial log contains a terminal `mcp_tool_call_finished` whose `mcp_tool_call_started` was lost, `summarize_trace()` counts the unstarted terminal call toward `attempted` so `completed + errored <= attempted` cannot be violated.
- If duplicate events with the same `call_id` appear in a trace (e.g., log replay or retry flush), `_dedup_by_call_id()` deduplicates them deterministically (preserving the earliest start and latest finish) before counting or correlating.

## 3. Client–Server Call Correlation Contract

Because the Codex CLI client and the FastMCP server emit separate telemetry streams (`source: "client_session"` vs `source: "mcp_server"`), `telemetry.correlate_calls()` pairs client and server calls per `tool_name` and labels every pair with an explicit `correlation_certainty`:

1. **`confirmed_protocol_id`**: Both the client event and the server event carry a matching non-empty protocol call identifier (`protocol_call_id` or `server_protocol_call_id`).
2. **`ordinal_unconfirmed`**: The client and server calls match on `tool_name` and ordinal position ($k$-th call to that tool), with `server_started >= client_started - 1.0s`, **and no mismatching protocol IDs are present**. Because MCP stdio transport does not always expose the JSON-RPC request ID to the FastMCP tool handler, ordinal pairing is common in schema-1.2 traces; Stage 2 never upgrades `ordinal_unconfirmed` to `confirmed_protocol_id`.
3. **`unmatched`**:
   - Client call has no corresponding server call (`unmatched_client_calls`), OR
   - Server call has no corresponding client call (`unmatched_server_calls`), OR
   - Both sides carry non-empty protocol IDs that **disagree**, OR
   - Server start timestamp precedes client start timestamp by more than `1.0s` clock-skew tolerance.

## 4. Lexical Overlap Proxy Disclaimer

`telemetry.compute_result_use_proxy()` extracts domain tokens ($\ge 4$ characters, excluding common R/English stopwords) from server `argument_keys` and `tool_name` values and checks whether they appear in the candidate's final submission text:

- When `delivered == 0` or `answer_text` is empty, `status` is `"not_applicable"` and `overlap_ratio` is `None`.
- When `delivered > 0` and `answer_text` is non-empty, `status` is `"unverified_lexical_overlap"`.
- This metric is a **descriptive proxy only**. A high overlap ratio can occur when both the prompt and the answer mention the target package name, and a low overlap ratio can occur when a tool lookup prevents an error (negative evidence) without leaving tokens in the final code.

## 5. Control-Arm Leak Detection via Telemetry

In Arm A (`without-mcp`), `protocol.ARM_SPECS["A"]` sets `mcp_enabled = False`. If a runner bug or misconfiguration exposes MCP in an Arm A trial:

- `telemetry.summarize_trace()` records the actual observed `mcp_available`, `mcp_listed`, `attempted`, etc.
- `records.validate_record()` **does not crash** with a schema error; instead, `records.check_trial_compliance()` adds `"arm_a_mcp_available_leaked"`, `"arm_a_mcp_listed_leaked"`, or `"arm_a_mcp_call_attempted"` to `protocol.capability_violations` and sets `protocol.compliant = False`.
- `analysis.run_preregistered_analysis()` surfaces every such trial in `invalidating_violations` and sets `study_valid = False`.

