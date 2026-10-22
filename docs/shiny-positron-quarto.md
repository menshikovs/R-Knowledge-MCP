# Shiny, Positron and Quarto integration

This release adds official framework documentation retrieval, bounded static
analysis of supplied text, and combined package/framework guidance. It does not
execute R or Quarto, run a Shiny app, inspect a client's filesystem, or control
the Positron GUI.

## Shiny for R

`get_shiny_docs` reads the requested function's literal Rd alias from the
current CRAN source archive. It supports the package set `shiny`, `bslib`,
`htmltools`, `shinyWidgets`, `DT`, `plotly`, `promises`, `future`,
`shinyvalidate`, `shinytest2`, `testthat`, `reactlog`, and `thematic`. Known
owners are checked for core functions: for example, `page_sidebar` is a bslib
function. The result gives the exact package version and source archive.
Historical version retrieval is not implemented; a requested version that
differs from current CRAN produces an explicit error.

`explain_shiny_reactivity` retrieves one of the fixed official article topics:
`reactivity`, `isolation`, `modules`, `async`, and `basics`. Optional supplied R
text receives the same bounded heuristic scan as `analyze_shiny_app`. Findings
distinguish definite text matches from heuristics. An input/output ID match is
not a proof of runtime behavior: generated UI, module namespaces, sourced code
and arbitrary R syntax can defeat static matching. Use `testServer()` and
`shinytest2` in a trusted local test environment for runtime behavior; this MCP
does not run those tests.

The official Shiny reference currently publishes versioned function references
and upgrade pages. This service's function tool currently retrieves the latest
indexed CRAN archive only. Shiny articles are current official pages and are not
version-pinned. See [Shiny reference](https://shiny.posit.co/r/reference/shiny/),
[reactivity overview](https://shiny.posit.co/r/articles/build/reactivity-overview),
[modules](https://shiny.posit.co/r/articles/improve/modules/), and
[non-blocking operations](https://shiny.posit.co/r/articles/improve/nonblocking).

## Positron

`get_positron_guidance` retrieves one of the catalog topics `interpreters`,
`r_installation`, `startup`, `extensions`, or `mcp`. A supplied Positron or R
version is context only; the official pages are not version-specific. Positron
is an MCP client target: add this server through Positron's MCP configuration
using the server's HTTP endpoint where reachable or stdio for a local client
that supports it. `analyze_r_workspace` accepts a text mapping explicitly
provided by the caller; it summarizes `.Rproj`, `DESCRIPTION`, `renv.lock`,
`.vscode/settings.json`, `.Rprofile`, `.Renviron`, Shiny and Quarto metadata.
It never opens local paths and never returns `.Renviron` values.

Positron's current docs describe Code OSS/VS Code extension compatibility with
exceptions, interpreter selection, and MCP support in its assistant workflows.
Some built-in MCP functionality is documented as experimental/preview; check
the installed Positron release notes before depending on it. This project does
not ship an IDE extension, send IDE commands, access live R sessions or run
code. See [Positron extensions](https://positron.posit.co/extensions.html),
[interpreter management](https://positron.posit.co/managing-interpreters.html),
[R installation discovery](https://positron.posit.co/r-installations.html),
and [Positron Assistant](https://positron.posit.co/assistant.html).

## Quarto

`get_quarto_docs` retrieves official pages for `r`, `projects`, `profiles`,
`citations`, and `rendering`. `analyze_quarto_document` parses bounded YAML
front matter with `yaml.safe_load` semantics (duplicate keys and aliases are
rejected), identifies R code fences and their `#|` options, checks declared
formats, and reports possible citation/bibliography omissions. It never renders
the document or evaluates code. Quarto-specific tags such as `!expr` may be
reported as unsupported YAML instead of evaluated. It does not validate the
full Quarto schema or verify actual files, citation keys or output targets.

`analyze_quarto_project` accepts `_quarto.yml`, optional `_metadata.yml`, and an
optional path-only file manifest; it can flag a bibliography absent from that
manifest. It does not list a real directory. Rendering commands are guidance
only: for example, `quarto render report.qmd --to html` or `--to pdf`, `--to
docx`, and `--to revealjs`. The target file is not run by this server. PDF
rendering can require a separately installed LaTeX distribution. Quarto may
execute R chunks when a user renders locally, so review trusted code and the
execution options first.

See official [R computations](https://quarto.org/docs/computations/r.html),
[project basics](https://quarto.org/docs/projects/quarto-projects.html),
[profiles](https://quarto.org/docs/projects/profiles.html), and
[citations](https://quarto.org/docs/authoring/citations.html).

## Combined workflow

`get_r_workflow_guidance` supports `shiny_bioconductor`, `quarto_positron`,
`quarto_bioconductor`, and `analysis_to_shiny`. The caller supplies the package
names and repository identities; the tool combines those verified package
records with the relevant official framework pages. If R and Bioconductor
versions are supplied for a Bioconductor package, direct compatibility checks
are included. It does not guess packages, solve a transitive environment, or
claim that the project rendered successfully.

Example Codex requests after configuring the existing MCP server:

```text
Use get_shiny_docs for shiny::moduleServer and summarize its documented
arguments. Then explain the modules topic and analyze this supplied app.R text.

Analyze this QMD front matter and R chunk options without executing it.

Give Quarto-in-Positron setup guidance for R 4.4, then analyze this explicitly
provided renv.lock and _quarto.yml metadata.
```

All retrieved external text is untrusted reference material. Static checks are
not a security audit, app test, accessibility check or deployment review.

## MCP resources and prompts

This integration uses tools rather than fixed resources or server prompts.
Package and framework responses are selected dynamically and carry request-time
provenance; publishing static resource URIs would encourage stale data or imply
that the server can see local project files. Reusable review prompts are better
owned by the connected AI client because they express user workflow rather than
authoritative source data. The official Python SDK supports all three MCP
primitives, but the current tool schemas cover these workflows without adding
resource templates or prompt-maintenance overhead. See the
[MCP Python SDK server concepts](https://py.sdk.modelcontextprotocol.io/servers/).
