# Development rules

- Use Python 3.11+ and the official `mcp` SDK. This release deliberately pins
  `mcp>=1.30,<2` for FastMCP; SDK 2 renamed it to MCPServer. Migrate explicitly.
- Keep transport registration in `server.py`, domain operations in `service.py`,
  HTTP policy in `http.py`, data-only parsing in `parsers.py`.
- Verify upstream documentation before changing SDK or CRAN source contracts.
- Never invent metadata, versions, documentation, or successful fallback results.
  Preserve source URLs and actual UTC check times, including cache timestamps.
- Never execute R, package scripts, Rd expressions, shell commands from tool
  arguments, or metadata. Never extract upstream archives onto the filesystem.
- Do not allow caller-supplied URLs, arbitrary hosts, redirects, or implicit HTTP
  proxy configuration. Retain timeout, byte, archive, cache and output limits.
- Keep latest CRAN versions separate from user-supplied installed versions.
  Future renv integration must accept explicit lock data, preserve repository and
  version identity, and never silently substitute current CRAN documentation.
- Use `httpx.MockTransport` for unit tests. Synthetic package fixtures belong only
  in tests; no network access is required by CI tests.
- Before a PR run `ruff check .`, `ruff format --check .` and `pytest`.
  Build Docker when an engine is available; report unavailable checks honestly.
- Keep stdio stdout exclusively for MCP. Operational logs go to stderr.
- No public deployment, paid service, publishing to PyPI, or merge as part of
  routine implementation work. Add focused tests for behavior and security fixes.
