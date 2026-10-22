# Add GitHub AGENTS.md and Context7 package knowledge

Extends the existing CRAN and Bioconductor MCP tools with a commit-pinned GitHub
AGENTS.md reader, an optional Context7 documentation provider, and a combined
`get_package_knowledge` tool. Existing repository operations retain their
signatures and behavior.

## Behavior

- Resolves exactly one HTTPS GitHub repository from the selected package's
  verified source archive `DESCRIPTION` URL, confirms the canonical repo through
  GitHub REST, and resolves an explicit branch/tag/commit ref to a commit SHA.
- Searches the recursive tree at that SHA for root and nested `AGENTS.md` files;
  returns path, directory scope, content, source URL, version and check time.
  A complete tree verifies absence; truncated trees and API errors remain errors.
- Marks every external instruction as untrusted reference material and never
  executes commands or grants it authority over system instructions.
- Adds optional Context7 library search and query docs. It is disabled without
  server-side `CONTEXT7_API_KEY`, checks an exact package-repository ID match,
  uses a package-version pin only when Context7 lists the exact version, and
  preserves the secondary-source warning on each fragment.
- Bounds request, response, file, count, output, timeout and cache sizes; rejects
  redirects and all caller-controlled hosts. Common secret formats in user
  questions are redacted before a Context7 request. Rate-limit and API errors
  are explicit.
- `get_package_knowledge` retains package info, dependencies, requested external
  sections and per-section provenance/errors in one response.

## Validation

- 99 offline tests pass in the Linux container, including mocked GitHub and
  Context7 APIs, nested/scoped AGENTS.md, complete absence vs truncated trees,
  Context7 repository/version matching, disabled integration, key handling,
  redaction, rate limits, aggregate provenance and MCP registration.
- Ruff lint and formatting checks pass.
- Docker image build and CLI smoke check pass.
- No deployment or paid service is configured. Context7 use is opt-in via the
  server administrator's key.

## Scope and limitations

AGENTS.md lookup requires an explicit ref; the server does not guess version tag
naming conventions. Repositories with a recursive tree over the response limit
or an API-truncated tree fail explicitly rather than claiming absence. Context7
is optional, requires a matching indexed GitHub repository, may lack R package
documentation, and remains less authoritative than CRAN/Bioconductor package
archives and documentation. Secret redaction covers common token/key formats;
callers should still avoid putting credentials in documentation questions.
