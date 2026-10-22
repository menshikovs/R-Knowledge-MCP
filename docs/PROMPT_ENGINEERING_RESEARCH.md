# Prompt Engineering Integration Research

Research checked 2026-10-22. This note distinguishes deterministic prompt
composition, external prompt optimization, and evaluation. They solve different
problems and should not be combined behind a misleading “optimize” operation.

## MCP Prompts and SDK

The [MCP Prompts specification](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts)
defines prompts as user-controlled templates discoverable with `prompts/list`
and fetched with `prompts/get`. This project registers seven standard Prompts
in its SDK FastMCP server and verifies listing/fetching over local in-memory and
Streamable HTTP sessions. Prompts are static local drafts. They do not inspect
project files or call package APIs.

The project currently depends on `mcp>=1.30,<2`, preserving the official
[Python SDK 1.x FastMCP API](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x).
The official [SDK documentation](https://py.sdk.modelcontextprotocol.io/)
identifies SDK 2 as the current stable major; its
[what's new page](https://py.sdk.modelcontextprotocol.io/whats-new/) documents
support for protocol revision 2026-07-28 and the FastMCP-to-MCPServer naming
change. The installed SDK 1.30.0 negotiates protocol revision 2025-11-25 and
does not advertise the newer revision. We therefore retain tested standard
Prompts on the existing SDK and defer SDK 2 migration to a separate change with
client/transport compatibility coverage.

## Existing optimizer and evaluation options

| Project | Strength | Concern for this service | Decision |
| --- | --- | --- | --- |
| [Promptfoo](https://github.com/promptfoo/promptfoo) | Active MIT-licensed testing and red-teaming framework; official docs describe evaluation of MCP servers and coding agents. It can exercise tools over stdio/HTTP and score outputs with custom assertions. | A test/evaluation harness, not a deterministic R prompt composer. Model-based graders need a separately configured model provider and may send evaluation content to it. Adds Node/npm when used. | Best optional development evaluation candidate; keep out of runtime dependencies and CI until a curated benchmark and cost/privacy policy exist. |
| [Prompt-Optimizer](https://github.com/Godhelpsme/Prompt-Optimizer) | User-facing iterative prompt optimization UI/server; describes optimizing system/user prompts with MCP support. | Requires an external LLM provider/API key and submits prompt content for iterative generation. Generic rather than R-specific; no package-version grounding contract. | Do not integrate by default. Revisit only as an explicitly selected adapter with consent, redaction, provider and retention controls. |
| [prompt-lab-mcp](https://github.com/jurek-f/prompt-lab-mcp) | MCP-oriented prompt experimentation and saved prompt workflows. | Public repository snapshot reviewed had a very small contribution/issue history and depends on hosted/persistent components. Maturity and data-flow model are not strong enough for a default source of truth. | Do not add as a runtime dependency; reassess if project maturity and self-hosting guarantees improve. |
| [simple-prompt-optimizer](https://github.com/Chumbayoumba/simple-prompt-optimizer) | Small CO-STAR-style optimizer with a simple integration concept. | Public snapshot reviewed was a minimal implementation and routed requests through OpenRouter; no R package grounding or source provenance. | Not selected. |

The primary documentation reviewed was Promptfoo's
[MCP server integration](https://www.promptfoo.dev/docs/integrations/mcp-server/),
[MCP provider](https://www.promptfoo.dev/docs/providers/mcp/) and
[coding-agent evaluation guide](https://www.promptfoo.dev/docs/guides/evaluate-coding-agents/).
Those guides support using Promptfoo as an optional test harness, with
structured assertions and isolated coding-agent workspaces. They do not imply
that automated grades prove runtime correctness.

## Chosen design

The runtime feature composes prompts deterministically from a typed
specification, stable local templates, conservative intent detection and
existing official package providers. It carries package/repository/release/
version/source/check-time evidence into the output and states when information
is absent or unverified. No optimizer API, Promptfoo process, new paid service
or network endpoint is called by the feature.

An enhancement protocol seam exists to avoid coupling future experiments to the
composer. There is no adapter implementation or default provider. Requests for
`auto` or `external` mode therefore fall back deterministically and disclose
that fact. Any future external adapter needs a separate review of prompt
transmission, consent, credential handling, redaction, rate limits, provider
retention, output preservation and adversarial prompt injection.

Promptfoo should be evaluated later with a curated local dataset covering R
package development, Shiny, Quarto, Bioconductor release/R compatibility,
ggplot2, tidyr and debugging. First-stage assertions should check that outputs
preserve requirements, cite only returned source URLs, avoid invented package
versions, label unresolved compatibility, and never execute supplied text.
Model-based grading should be optional; coding-agent evaluations should use
isolated temporary repositories and behavior-focused tests. This repository
currently runs deterministic pytest tests with mocked external APIs; no
Promptfoo or model evaluation has been run.
