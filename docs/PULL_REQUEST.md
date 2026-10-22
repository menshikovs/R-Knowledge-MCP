# Build a source-attributed R package knowledge MCP

Adds a read-only MCP server for CRAN and Bioconductor package metadata,
version-specific Rd documentation, dependencies, vignette links and
conservative R/Bioconductor compatibility checks. Optional GitHub and Context7
providers add commit-pinned package guidance and indexed documentation while
preserving per-source provenance.

## Implementation

- Adds a `PackageRepository` contract with separate CRAN and Bioconductor
  providers. Bioconductor releases and R mappings are discovered from the
  official configuration, and software, annotation and experiment indices are
  handled independently.
- Registers eleven FastMCP tools for package search/info/dependencies/docs,
  compatibility and version checks, vignettes, GitHub AGENTS.md, Context7, and
  combined package knowledge. Both stdio and Streamable HTTP are supported.
- Verifies official index/archive identity and preserves source URL, source
  version and retrieval time. Missing packages, incomplete upstream data,
  incompatible constraints and upstream failures remain explicit.
- Resolves GitHub only from verified package metadata, pins requested refs to
  commit SHA, and labels every AGENTS.md file untrusted. Context7 is optional,
  server-keyed, repository matched, version scoped where supported, and labeled
  as a secondary source.
- Restricts outbound calls to fixed HTTPS routes, rejects redirects, caps
  downloads and outputs, applies bounded timeouts/retries and cache limits, and
  exposes validated runtime configuration. No package code or external
  instructions are executed.
- Adds security/source authority docs and future limitations to the README and
  roadmap. No public deployment or paid service is configured.

## Validation

- 109 tests pass in Linux Docker, including mocked CRAN, Bioconductor, GitHub
  and Context7 APIs, unavailable sources, compatibility checks, cache behavior,
  secret redaction, MCP stdio/HTTP, and configuration validation.
- `ruff check .` and `ruff format --check .` pass.
- Docker image builds and the packaged CLI help check passes.

## Known limitations

Compatibility checks cover official R/release mapping and direct required
dependencies; they do not solve transitive/platform dependencies or inspect an
installed R environment. CRAN archive lookups, `renv.lock` parsing and
installation testing remain future work. Context7 may not index an R package;
AGENTS.md retrieval requires an explicit ref and fails closed on truncated
GitHub trees. See `docs/ROADMAP.md` and `docs/security.md`.
