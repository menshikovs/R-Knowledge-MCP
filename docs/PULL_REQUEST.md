# Implement initial source-attributed CRAN Knowledge MCP server

Adds a working read-only MCP server with all five tools: `search_packages`,
`get_package_info`, `get_dependencies`, `get_function_docs`, and
`check_package_version`. Supports stdio and stateless Streamable HTTP using the
official SDK FastMCP. The initially empty repository has an MIT-only `main`
baseline; implementation changes are isolated in `feat/initial-cran-knowledge-mcp`.

Versions and dependencies come from the canonical CRAN `src/contrib/PACKAGES`
index. Metadata and raw Rd documentation come from the exact indexed source
archive, with package/version identity and available index MD5 checks. CRAN's
R-specific Recommended entries with `Path` overrides cannot overwrite canonical
root records. All results retain source URLs and original UTC verification times.
Client-supplied installed versions remain explicitly unverified and separate.

Async httpx downloads use fixed HTTPS routes, no redirects/environment proxies,
bounded downloads, deadlines and a bounded TTL/LRU cache shared across HTTP
requests. Archive parsing is bounded and in memory, with no filesystem
extraction, R/package execution or Rd macro evaluation. Search and documentation
support pagination. Source failures produce explicit error objects.

Includes Docker with an unprivileged runtime, CLI, pyproject.toml, MIT license,
AGENTS.md, Codex connection instructions, and GitHub Actions for Python 3.11–3.14
and Docker. Current official SDK and source documentation were reviewed before
implementation. The maintained `mcp>=1.30,<2` line preserves the requested FastMCP
API; SDK 2 renamed it to MCPServer.

## Validation

- 51 tests passed on Windows / Python 3.14.
- 51 tests passed in the Linux Docker image / Python 3.11.
- Ruff lint and format checks passed.
- Docker image build and container CLI smoke check passed.
- Live CRAN smoke check passed for all five tools against dplyr, including actual
  filter Rd documentation and version/source provenance. No version was assumed.

## Remaining limitations

- Search covers package names/titles, not descriptions or full manuals.
- Documentation is raw paginated Rd matched by literal aliases. Conditional
  content and custom macros are not rendered or evaluated.
- renv.lock, historical versions and local installed-package inspection are
  deferred. Follow-up tasks and acceptance criteria are in [ROADMAP.md](ROADMAP.md).
- Oversized artifacts and index/archive release races produce explicit errors.
- No hosted endpoint, deployment, paid services, authentication or per-client
  rate limiting. Public hosting needs ingress/resource policy review.

No deployment, package publication or merge is part of this change.
