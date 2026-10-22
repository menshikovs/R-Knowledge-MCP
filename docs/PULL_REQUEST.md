# Deep Shiny, Positron and Quarto integration

Adds source-attributed guidance and bounded project analysis for common R
development workflows while preserving the existing CRAN, Bioconductor,
GitHub AGENTS.md and Context7 providers.

## Changes

- Adds a fixed-catalog provider for official Shiny, Positron and Quarto
  documentation, with bounded async HTTP, redirect rejection, caching, source
  timestamps and explicit current-documentation/version caveats.
- Adds nine MCP tools: `get_shiny_docs`, `explain_shiny_reactivity`,
  `analyze_shiny_app`, `get_positron_guidance`, `analyze_r_workspace`,
  `get_quarto_docs`, `analyze_quarto_document`, `analyze_quarto_project` and
  `get_r_workflow_guidance`.
- Provides heuristic-only Shiny source checks, safe YAML/QMD parsing, Quarto
  project and bibliography-manifest checks, and metadata-only R workspace
  analysis including bounded `renv.lock` summaries. No user R, YAML objects,
  Quarto chunks, startup files or external instructions are executed.
- Adds explicit Shiny function ownership checks and refuses silent substitution
  when the requested historical package documentation is not available.
- Adds cross-framework workflows that combine selected official docs and only
  explicitly named package knowledge. Caller-supplied dependency names remain
  unverified unless a separate package metadata check succeeds.
- Updates user and developer documentation, security boundaries, architecture,
  source catalog and roadmap.

## Validation

- Docker image build succeeded; the full Linux Docker suite passed (**127
  tests**), `ruff check .` and `ruff format --check .` passed, and the packaged
  CLI help check passed.
- New tests mock external documentation HTTP and cover static analysis,
  malformed/unsafe metadata, secret redaction, bounded inputs, provenance,
  service behavior and MCP registration.

## Limits

- Shiny source checks are lexical heuristics, not R parsing, execution, reactive
  graph reconstruction, browser testing or security certification.
- Quarto analysis does not render documents and can only compare bibliography
  references against a caller-provided path manifest.
- Workspace inspection is limited to explicitly supplied bounded file text;
  it never reads a local path. `.Renviron` values are omitted and `.Rprofile` is
  never executed.
- Shiny Rd is retrieved from the current indexed CRAN source archive. Requested
  historical versions are reported unavailable rather than substituted.
- Positron and Quarto docs use current official pages and are not pinned to
  supplied versions. The MCP integration does not control the IDE, interpreter
  or terminal.
- Workflow advice does not infer package selections, solve full dependency
  graphs, install packages, render output or test deployment.
- MCP resources, reusable prompts, full R AST analysis, live IDE adapters and
  optional local R/Quarto smoke tests remain future work.
