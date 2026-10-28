# MCP protocol and tool-interface audit

Commit `4d2266c`. IDs refer to [`FINDINGS.md`](FINDINGS.md). Tested with the project's pinned SDK in a clean environment:
`mcp 1.30.0` (`pyproject.toml`: `mcp>=1.30,<2`), `httpx 0.28.1`, Python 3.14.4. The audit machine's global Python had `mcp 2.2.0`
(outside the pin); it was not used. Specification consulted: MCP 2025-11-25 `server/tools` and `basic/transports`
(modelcontextprotocol.io), fetched 2026-10-27.

## 1. Actual registered surface

Listed through the real `list_tools`/`list_resources`/`list_prompts` handlers (`evidence/mcp/tools_consolidated.json`, `tools_legacy.json`).

| | consolidated (default) | legacy |
|---|---|---|
| Tools | **16** (README says 16; `.env.example:22` says 15 — DOC-001) | **35** (README: 35) |
| Parameters / with description | 109 / 109 | 140 / **0** |
| Titles | 16 / 16 | 0 / 35 |
| Description length (chars) | min 60, median 82, max 407 | min 63, median 77, max 88 |
| Annotations | `readOnlyHint=true` on all; `openWorldHint=false` on 4 (`search_r_documentation`, `get_r_documentation_section`, `analyze_r_project`, `validate_r_prompt`) | `readOnlyHint=true, destructiveHint=false, openWorldHint=true` on all 35 |
| `outputSchema` | present on all, **empty object schema** (MCP-001) | same |
| Tools with > 8 parameters | `build_r_prompt` 21, `analyze_r_source` 13, `get_package` 9, `list_package_functions` 9 | `build_r_prompt` 18, `improve_r_prompt` 10 |
| Resources / templates / prompts | 2 / 3 / 14 | 2 / 3 / 14 |

Consolidated tools: `search_packages`, `get_package`, `get_function_docs`, `list_package_functions`, `check_package_version`, `check_r_compatibility`,
`search_r_documentation`, `get_r_documentation_section`, `get_framework_docs`, `get_r_workflow_guidance`, `analyze_r_source`, `analyze_r_project`,
`recommend_technology_stack`, `build_r_prompt`, `validate_r_prompt`, `get_r_prompt_context`.
Resources: `r-knowledge://framework-docs`, `r-knowledge://prompt-templates`; templates `r-manual://{document_id}`, `r-manual://{document_id}/{section_id}`, `cran://{package}/man/{alias}`.
Prompts: 13 single-task templates + `r-multi-stage-workflow`, registered natively and user-selected (`get_prompt` verified in-memory and over stdio).

Feature flags (verified, `evidence/probes/probe_flags.txt`): `MCP_TOOLSET` ∈ {consolidated, legacy}; `FUNCTION_DISCOVERY_ENABLED=false` removes only `list_package_functions` in the
consolidated set (legacy never had it, so the flag is inert there — consistent with "additive tool" wording); `PROMPT_INTELLIGENCE_ENABLED=false` removes 3 tools, the 14 prompts and 1 resource.
Backward compatibility: the legacy set is byte-stable by design ("unchanged for benchmark comparability", `server.py:340`); no test asserts the legacy schema against a stored snapshot beyond names (not verified in depth).

## 2. Annotation accuracy

Every tool is read-only: no handler writes files, mutates remote state or executes input (read in `server.py`/`service.py`; confirmed by the `r01a_offline_guard` tests and the fixed-route HTTP layer).
`readOnlyHint=true` is therefore accurate. Per spec, `destructiveHint`/`idempotentHint` are meaningful only when `readOnlyHint=false`, and the code comment says so (`server.py:1008-1009`), so omitting them is correct.
`openWorldHint` in the consolidated set is plausible: it is false for the four tools that never contact an upstream service (reading the local R-manual index, supplied-source analysis, prompt validation) and true otherwise.
`analyze_r_source` is `true` because supplying `package_versions` triggers a CRAN comparison (`service.py:831-845`). In the **legacy** set `openWorldHint=true` is claimed for tools that never leave the process (MCP-002); harmless but inaccurate.
The spec says clients must treat annotations as untrusted; nothing here depends on them for safety.

## 3. Conformance matrix (spec 2025-11-25)

| Requirement | Result | Evidence |
|---|---|---|
| stdio: nothing but MCP messages on stdout; logs to stderr | **Pass.** A raw JSON-RPC session over the installed script parsed every stdout line; 14 log lines went to stderr | `probe_stdio_protocol.txt` |
| Version negotiation | **Pass.** Requests for `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05` echo the same version; an unknown `2099-01-01` is answered with `2025-11-25` | same |
| `tools/list`, `tools/call`, `ping`, `resources/list`, `prompts/get` | Pass | same; `probe_mcp_shape.txt` |
| Input validation failure → tool execution error (`isError: true`) | **Pass** (2025-11-25 prefers this so models can self-correct): bad enum and missing required argument return `isError: true` with `error.code = invalid_input` | `probe_mcp_shape.txt` |
| Unknown tool → JSON-RPC protocol error (`-32602`) | **Deviation (intentional, MCP-002):** `ErrorAwareFastMCP` rewrites it to an `isError` result with code `tool_not_found` (`server.py:119-120`). Low impact | `probe_stdio_protocol.txt` |
| `structuredContent` plus serialized JSON in a text block | Pass (both present; payload therefore sent twice, MCP-003) | `probe_mcp_shape.txt` |
| `outputSchema` ⇒ results MUST conform | Trivially satisfied by an empty-object schema (MCP-001) | `evidence/mcp/tools_consolidated.json` |
| Streamable HTTP: validate `Origin`, 403 if invalid | **Pass.** Foreign origin 403; `null` origin 403; `http://localhost.evil.example` 403; loopback origins accepted; absent `Origin` accepted | `probe_http_transport.txt` |
| DNS-rebinding / Host validation | **Pass** (421 for foreign Host; default allow-list loopback only; `127.0.0.1.evil.example` rejected) | same |
| `MCP-Protocol-Version` invalid ⇒ 400 | **Pass** (400, lists supported versions) | same |
| GET on the MCP endpoint: SSE stream or 405 | **Pass** (returns an SSE stream) — but the stream stays open indefinitely without authentication (SEC-002) | same |
| Servers SHOULD authenticate; MUST rate-limit tool invocations (Security Considerations) | **Not met.** No authentication, no rate limit. Documented as a development server (`docs/security.md:70-75`); a blocker for remote hosting | SEC-002 |
| Bind to localhost when local | Pass for the CLI default (`127.0.0.1`); the Docker image binds `0.0.0.0` (`Dockerfile:10`) and then rejects foreign Host headers until `--allowed-host` is set | local container run |
| Body-size limit | Pass (HTTP 413 above the SDK's limit at 20 MiB test) | `probe_http_transport.txt` |
| Hostile JSON | Partial: 100 000-deep nesting → HTTP 500 plus a logged `RecursionError` (SDK path), no crash | same |

Stateless mode: `FastMCP(stateless_http=True, json_response=True)` (`server.py:316-317`), so no `MCP-Session-Id`, no server-initiated messages, and `listChanged` is `false`. For a read-only reference server this is the right choice.
HTTP lifespan: `create_http_app` owns one shared `httpx` client and cache for the process because SDK 1.x would otherwise invoke the lifespan per request (`server.py:1709-1724`) — a necessary workaround that should be re-examined on the SDK 2 migration (see ROADMAP).

## 4. Schema quality

- **Input schemas** are generated from type hints and `Annotated[..., Field(description=...)]`. Constraints are mostly stated in prose ("Results per page, 1..20.") and enforced in the service, returning an `invalid_input` envelope; only **26 of 109** consolidated parameters carry a machine-readable `enum`/`minimum`/`maximum`/`maxLength`/`pattern`. Package names have a strict regex in `http.package_name` but the schema shows a bare `string` (MCP-004). Consequence: clients cannot pre-validate, and an agent sees the constraint only if it reads descriptions.
- **Defaults** are declared (`repository="cran"`, `verbosity="compact"`, `limit` defaults) and the schema has no `additionalProperties: false`, so unknown arguments are rejected only by Pydantic's model behaviour (not verified for extra keys).
- **Conditional parameters** (`get_package`: `revision` only with `include=["agent_guidance"]`, `question` only with `context7`; `verify_archive` only with `metadata`; `resolve_repositories` only with `dependencies`) are enforced at runtime with explicit `invalid_input` errors (`service.py:1597-1617`). Good error text, but a `oneOf` in the schema or separate tools would let clients avoid the round-trip.
- **Output**: see MCP-001. The shared envelope (`package`, `repository`, `package_version`, `bioc_version`, `source_url`, `checked_at`, `verification_status`, `sources`, `error`) is documented in `README.md` and honoured in every path I called; combined responses (`repository="all"`, `get_package` sections) expose per-section `errors` and `partial` status, and `isError` is set only when every section failed (`server.py:40-52`). A fully-failed `get_package` has no top-level `error` object (the error is in `errors[]`), which a client that only checks `result.error` would miss — documented behaviour but easy to trip over.

## 5. Error semantics

`KnowledgeError(code, message, source_url, related_sources, details)` → `failure()` envelope with `verification_status: "failed"` and `error{code, message, source_url, attempted_at, …}`. Codes observed: `invalid_input`, `tool_not_found`, `package_not_found`, `docs_not_found`, `requested_version_unavailable`, `unsupported_encoding`, `source_too_large`, `rate_limited`, `blocked_url`, `timeout`, `internal_error` (see `docs/MCP_ERRORS.md`). Internal exceptions are logged with an operation id and exception type only. `docs_not_found` carries `suggestions`, `closest_aliases` or the full alias list for small packages — a genuinely useful self-correction channel (it turned the hallucinated `validate::violations` into the real `violating`).
Gap: `unsupported_encoding` on `get_function_docs` is reported for the *whole package* (KC-001).

## 6. Tool discovery behaviour and client compatibility

- Discovery is by `tools/list` only; the server provides no search-style meta tool and relies on names + one-line descriptions + the server-level `instructions` string.
- The benchmark's Codex 0.163.0 client receives `InitializeResult.instructions` as the MCP namespace description (README "B1 single-run MCP discovery experiment"), so the *server instructions text is the main steering surface* for that client. The default text is provenance/safety oriented (AGT-001).
- Stdio launch works unchanged with any client that spawns `r-knowledge-mcp`; HTTP clients must send `Accept: application/json, text/event-stream`. I tested no third-party client beyond the SDK's in-memory and raw JSON-RPC sessions (limitation).
- Resource errors have no error channel: a missing alias returns a normal resource body containing an error envelope (MCP-002).

## 7. Is the consolidated surface "too broad"?

Measured facts only: 16 tools is a modest number; four have 9–21 parameters; `get_package` multiplexes five sections and `analyze_r_source` seven analyzers behind a discriminator. No data in the repository isolates tool-selection error as a function of overload (the benchmark records tool *use*, not mis-selection; see `AGENT_USABILITY_AUDIT.md`). My assessment: the consolidation is sensible for discovery; the risk is concentrated in `build_r_prompt` (21 parameters, optional nested objects) and in `get_package`'s conditional parameters. Recommendations are in `AGENT_USABILITY_AUDIT.md` §4 with an experiment to validate them.

## 8. Limitations of this audit

Not tested: third-party MCP clients (Claude Desktop, Cursor, VS Code); SDK 2.x; protocol revision 2026-07-28 mentioned in `docs/ROADMAP.md`; HTTP behaviour behind a TLS reverse proxy; concurrent HTTP sessions under load.
