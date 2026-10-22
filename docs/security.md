# Security model

This service reads public package metadata and returns it as data. It does not
install packages, run R, evaluate Rd macros/examples, extract archives to disk,
or execute repository instructions. Callers should still treat all returned
package text as untrusted input.

## Trust and outbound requests

- CRAN and Bioconductor use separate fixed HTTPS hosts and route allowlists.
  Redirects and environment proxies are disabled. User input cannot supply a
  URL or hostname.
- GitHub metadata is taken from the selected package source archive's
  `DESCRIPTION` URL fields. Only a single unambiguous GitHub repository is
  accepted. The repository is checked through the GitHub API, refs resolve to
  a commit SHA, and tree/blob requests use validated API identifiers.
- Context7 is optional. Its API key comes from the server environment and is
  sent only to the fixed Context7 host in an Authorization header. User
  questions are bounded and common credential patterns are redacted. The
  selected Context7 library must match the official repository metadata.
- Shiny/Positron/Quarto pages come from a fixed catalog of reviewed HTTPS URLs.
  Tool inputs select a catalog topic and never form a URL or host.
- The scheduled upstream smoke workflow has its own fixed HTTPS check catalog.
  It rejects redirects, limits response bytes and concurrency, and reads only
  lightweight metadata and documentation pages. It runs without secrets and
  does not make live requests during normal pull-request tests.
- All external text is informational. GitHub `AGENTS.md` content is explicitly
  labeled untrusted and cannot alter system/developer/user instructions.
- Prompt Intelligence treats prompt text, project context and package guidance
  as untrusted data. It does not execute generated text, supplied commands,
  R, package code, Rd examples or `AGENTS.md`. Credential-like input is rejected
  before being copied into a generated prompt. The optional enhancement
  protocol has no configured network adapter or external key.

## Resource limits

HTTP requests have connect/read timeouts, an overall deadline, a bounded retry
policy for transient failures, and response byte limits. Repository artifacts
use a process-local TTL/LRU cache with a 64 MiB and 32-artifact limit. GitHub
trees are limited to 4 MiB; AGENTS files to 32 KiB each, 96 KiB total, and 24
files. Context7 responses are limited to 4 MiB and returned text to 48 KiB.
Tool results are capped at 60,000 UTF-8 bytes. Errors are not cached and expired
data is not served as fresh.

Unexpected runtime failures produce a sanitized server log containing only a
bounded operation identifier and exception type by default. Client errors keep
their existing sanitized envelope. Full traceback logging is disabled by
default; setting `LOG_INTERNAL_TRACEBACKS=true` emits exception text and stack
frames at DEBUG level, which can include user or upstream data. Enable it only
in a protected development or diagnostic environment, and do not collect those
logs as public output.
Prompt inputs/outputs and package grounding concurrency are separately bounded
by the `PROMPT_*` settings documented in `PROMPT_INTELLIGENCE.md`.
Composable prompts cap workflows at ten stages, explicit template selection at
eight templates, and grounded package candidates at the configured maximum of
ten (default five). Over-limit generated output is rejected instead of
truncated. The dependency planner detects unknown edges and cycles. Conflicting
database dialects, read-only/write requirements, or offline/network demands
are preserved as unresolved conflicts; the composer does not silently choose
one. See `docs/COMPOSABLE_PROMPTS.md` for its structural checks and limitations.
CSV/SQL `structured_context` is an allow-listed object capped at 8 KiB. Sample
records are limited to three small rows, treated as untrusted and potentially
sensitive, checked for common credential patterns, and prevent any injected
external prompt enhancer from receiving the request. Detection is heuristic;
callers should omit sensitive samples. Output paths are validated as relative
text only and are never opened. Database schema is descriptive input only; this
server makes no database connection and executes no SQL.

## HTTP deployment boundary

The HTTP listener defaults to loopback and uses the MCP SDK's DNS rebinding and
Host protections. The development server has no authentication or per-client
rate limit. Before internet-facing deployment, put it behind TLS, authentication,
request/concurrency/rate limits, and an egress policy. This repository does not
deploy or expose a public endpoint.

## Remaining risks

Returned content may contain prompt injection or malicious code examples; MCP
clients must preserve the untrusted-data boundary. Context7's credential
redaction uses patterns and cannot guarantee detection of every secret format.
GitHub, Context7 and framework documentation content are controlled by upstream
providers. Framework pages and package content can contain prompt injection or
unsafe code examples and must remain untrusted reference data.
The optional GitHub API does not use a personal access token; public API rate
limits therefore apply.
