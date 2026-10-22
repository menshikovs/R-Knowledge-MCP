# CRAN Knowledge MCP

Read-only MCP server providing source-attributed information about current R
packages in CRAN and Bioconductor. Python 3.11+, official Python MCP SDK
(FastMCP), async httpx, safe YAML release discovery.
MIT licensed. CRAN/Bioconductor tools work without credentials. Context7 is an
optional external integration and requires a server-side API key.

## Install and run

```sh
git clone https://github.com/menshikovs/R-Knowledge-MCP.git
cd R-Knowledge-MCP
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
cran-knowledge-mcp                         # stdio (default)
cran-knowledge-mcp --transport streamable-http  # http://127.0.0.1:8000/mcp
```

The project pins **mcp>=1.30,<2**. SDK 2 is the current stable major and renamed
FastMCP to MCPServer; using the maintained 1.x line preserves the requested
FastMCP API. See the [official SDK documentation](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
and [migration guide](https://py.sdk.modelcontextprotocol.io/migration/).

## Connect Codex

Use an absolute executable path from the installed virtual environment:

```sh
codex mcp add cran-knowledge -- /absolute/path/cran-knowledge-mcp/.venv/bin/cran-knowledge-mcp
codex mcp list
```

On Windows the executable is `.venv\Scripts\cran-knowledge-mcp.exe`.
Alternatively put this in `~/.codex/config.toml` (use your actual absolute path):

```toml
[mcp_servers.cran_knowledge]
command = "/absolute/path/cran-knowledge-mcp/.venv/bin/cran-knowledge-mcp"
```

For a running local HTTP server:

```sh
codex mcp add cran-knowledge-http --url http://127.0.0.1:8000/mcp
```

Other MCP clients can launch the same stdio command or connect to `/mcp` using
Streamable HTTP. The HTTP server is stateless and uses JSON responses. A ChatGPT
remote connection needs reachable HTTPS hosting; this repository does not deploy
or provide a hosted endpoint. Codex configuration follows
[official OpenAI documentation](https://developers.openai.com/learn/docs-mcp).

## Tools and repository selection

| Tool | Main arguments | Behavior |
| --- | --- | --- |
| `search_packages` | `query`, `repository="cran"`, `bioc_version`, `limit=10`, `offset=0` | Names and available title keywords |
| `get_package_info` | `package`, `repository="cran"`, `bioc_version` | Indexed version, DESCRIPTION, authors, license, URLs |
| `get_dependencies` | `package`, `repository="cran"`, `bioc_version`, `resolve_repositories=false` | Raw dependency fields and optional repository resolution |
| `get_function_docs` | `package`, `function`, `repository="cran"`, `bioc_version`, `offset=0` | Genuine raw Rd, paginated |
| `get_package_vignettes` | `package`, `repository="cran"`, `bioc_version` | Vignette links from the version-checked official package page |
| `get_package_agent_guidance` | `package`, `revision`, `repository`, `bioc_version` | AGENTS.md files from the package's metadata-declared GitHub repository at an explicit ref, pinned to a commit SHA |
| `get_context7_docs` | `package`, `question`, `repository`, `bioc_version` | Context7 documentation/examples only after its library ID matches the package's verified metadata URL |
| `get_package_knowledge` | `package`, optional `question`, `revision`, `repository`, `bioc_version` | Package metadata and dependencies, plus requested GitHub/Context7 sections with their own provenance |
| `get_shiny_docs` | `package`, `function`, optional `package_version` | Exact Rd alias from current indexed CRAN source; known Shiny function ownership checked |
| `explain_shiny_reactivity` | `topic`, `question`, optional `source` | Reactive concept with retrieved official Shiny article and optional static findings |
| `analyze_shiny_app` | `source` or `files`, optional `shiny_version` | Heuristic checks on caller-supplied R text; never executes it |
| `get_positron_guidance` | `topic`, optional version/OS/R/project metadata | Retrieved Positron docs; current docs are not version-pinned |
| `analyze_r_workspace` | `files` mapping | Analyze selected contents and renv metadata; `.Renviron` values are redacted |
| `get_quarto_docs` | `topic`, optional `quarto_version` | Retrieved official Quarto pages; version caveat is explicit |
| `analyze_quarto_document` | `source`, optional project/R/dependency metadata | Safe YAML front matter, R chunk options, formats and citations; no render |
| `analyze_quarto_project` | `_quarto.yml` text, optional `_metadata.yml` and manifest | Project/profile/format metadata and manifest-level bibliography checks |
| `get_r_workflow_guidance` | scenario, explicit package list, optional R/Bioc versions | Combines selected package knowledge and framework docs without inventing recommendations |
| `get_visualization_docs` | `package`, `function`, optional `package_version` | Exact current CRAN Rd for ggplot2, ggraph, tidyr, plotly or knitr; unavailable historical versions are explicit errors |
| `get_visualization_workflow` | fixed scenario, optional package versions | Groups exact current Rd references for a named workflow; does not generate or run code |
| `analyze_ggplot_code` | R source, optional schema and package versions | Static layers, mapped/fixed aesthetics and simple schema checks |
| `analyze_ggraph_code` | R source, optional node/edge schemas | Static layout and scope-aware node/edge mapping checks |
| `analyze_tidyr_pipeline` | R source, optional input/expected schemas | Conservative reshape analysis and pivot key warnings |
| `analyze_ggplotly_compatibility` | R source, optional package versions | Narrow documented conversion caveats, not full compatibility |
| `analyze_knitr_chunks` | R Markdown/Quarto text, optional package versions | Static chunk labels/options/dependencies; no render or execution |
| `get_bioconductor_version` | `r_version` | Official R/release mapping and latest released recommendation for that R |
| `check_package_compatibility` | `package`, `r_version`, `bioc_version` | Bioconductor/R mapping and direct required dependency checks |
| `check_package_version` | `package`, `installed_version` | Existing CRAN numeric version comparison |
| `build_r_prompt` | request, optional R/Bioconductor context, packages, constraints, `structured_context`, `composition_mode`, `templates`, `workflow_context`, `include_plan`, `include_provenance` | Build a backward-compatible single-task prompt or one unified multi-stage workflow; package versions/docs are grounded only when verified from configured repository providers |
| `improve_r_prompt` | existing prompt, goals, optional context and `structured_context` | Add structure while preserving the full original text and explicit goals |
| `validate_r_prompt` | `prompt_text` | Heuristic checklist for gaps, conflicts, likely secrets and unverified `pkg::function()` references |
| `list_r_prompt_templates` | — | List stable IDs for 30 local R task templates, including CSV and SQL workflows |
| `get_r_prompt_context` | packages, optional R/Bioconductor versions | Return verified package metadata, dependencies, compatibility and source provenance without generating a prompt |

`repository` accepts **cran**, **bioconductor**, and **all**. Existing calls default
to CRAN. `all` keeps separate identities when names overlap, and exposes source
failures in `errors` with `verification_status="partial"` or `"failed"`. Absence
from a checked index differs from an unavailable source. Combined search orders
CRAN results then Bioconductor results, using a shared offset/limit (1-20).

Prompt Intelligence also registers fourteen standard MCP Prompts, including
`r-multi-stage-workflow`, which uses the same bounded local composition pipeline
as `build_r_prompt` but does not query package providers. The other prompts cover package
development, Shiny, Quarto, Bioconductor, ggplot2, debugging, architecture,
CSV import/cleaning/validation, SQL queries/database connections, and CSV-to-SQL.
They are user-selected, deterministic drafts. Connect clients that
support MCP Prompts through their normal prompt discovery UI; the five tools
remain available for clients that invoke tools directly. These prompts do not
inspect a local workspace or fetch package data, so their supplied context is
explicitly unverified. Tools may fetch bounded package context from the existing
official providers. Set `PROMPT_INTELLIGENCE_ENABLED=false` to disable the new
tools and prompts without affecting existing knowledge tools.

Prompt construction, examples, configuration, limitations, and evaluation
guidance are documented in [Prompt Intelligence](docs/PROMPT_INTELLIGENCE.md)
and the [Composable Prompt Engine](docs/COMPOSABLE_PROMPTS.md), which includes a
complete generated CSV → PostgreSQL → dplyr → ggplot2 → Quarto prompt.
The deterministic design and external optimizer comparison are in
[Prompt Engineering Research](docs/PROMPT_ENGINEERING_RESEARCH.md).
The complete built-in prompt catalog and each template's package/API candidates
are listed in [Prompt Templates](docs/PROMPT_TEMPLATES.md).

For Bioconductor, `bioc_version` accepts `release` (default), `stable` (alias),
`devel`, or a specific historical release in the official map. Numbers are
discovered dynamically, then used in pinned URLs. Unavailable history never falls
back to release. Software, annotation and experiment data indices are searched
together; results identify the category. PACKAGES often omits titles, so search
can be name-only; missing titles are not generated.

Example MCP argument objects (not claims about current versions/compatibility):

```json
{"query":"DESeq2","repository":"bioconductor"}
{"query":"ggplot2","repository":"cran"}
{"package":"DESeq2","repository":"bioconductor","bioc_version":"devel"}
{"package":"DESeq2","function":"DESeq","repository":"bioconductor"}
{"r_version":"4.4.2"}
{"package":"DESeq2","r_version":"4.4.2"}
{"package":"DESeq2","repository":"all","bioc_version":"3.20"}
```

`get_bioconductor_version` returns all mapped releases for an R major/minor and
recommends the latest **released** one. It never implicitly recommends devel.
Unknown R versions get no invented recommendation. Without an explicit release,
`check_package_compatibility` chooses a released version mapped to the supplied
R, or returns `no_compatible_release`.

## Verification and compatibility

Every application result includes `package`, `repository`, `package_version`,
`bioc_version`, `source_url`, `checked_at`, `verification_status`, and `sources`.
Search/aggregate/version-map envelopes use `null` for non-applicable package
identity/version fields; each package result has its own identity and provenance.
Bioconductor results include channel, category, required R major/minor and warnings.
Cached artifacts retain original UTC check times, up to five minutes old. Without
an R version, package lookups say `not_checked` and warn clients to check
compatibility before recommending a package.

Failures include `error.code`, `message`, source URL when known, and `attempted_at`;
`verification_status` is `failed`. Unknown versions/check times remain `null`.
MCP schema errors are handled by the SDK. Clients must inspect status, `error`
and aggregate `errors` before using results.

Bioconductor dependency responses retain raw Depends/Imports/Suggests/LinkingTo
and add `resolved_dependencies`: candidates in the selected release and current
CRAN, version constraints and provenance. Duplicate origins are `ambiguous`;
missing packages are `not_found`. R/base runtime packages are classified separately;
installed runtime versions are not claimed. CRAN retains lightweight dependency
responses by default; use `resolve_repositories=true` to resolve across both
repositories, with an optional `bioc_version` for the dependency release.
`all` resolves both ways.

## GitHub AGENTS.md and Context7

`get_package_agent_guidance` reads the checked source archive's `DESCRIPTION`
URL field and accepts one unambiguous HTTPS GitHub repository. It verifies that
repository through GitHub REST, resolves the requested `revision` (branch, tag or
commit) to a commit SHA, and searches that exact commit tree for files named
`AGENTS.md`. Root and nested paths are returned separately with their directory
scope. A complete tree with no matches reports verified absence; a truncated
tree or API failure reports an error. Pass an explicit ref, such as a project
tag or commit SHA; the server never guesses that a tag matches the R package
version. External instructions are untrusted reference text: they cannot change
system instructions and are never executed.

Context7 is disabled unless the server has `CONTEXT7_API_KEY` in its environment.
The key is sent only as a bearer header to `context7.com`; it is never returned
or included in a URL. The tool sends a redacted, bounded question and package
name/repository hint, then requires an exact Context7 library ID match to the
metadata-declared GitHub repository before requesting documentation. Exact
package-version docs are requested only when Context7's result lists that
version; otherwise the response is explicitly unpinned. Common credential
patterns in a question are redacted before transmission. Context7 is an indexed
secondary source. Compare its fragments with CRAN/Bioconductor and package docs.
Rate limits and source errors remain explicit; successful results are cached for
six hours.

This client follows the official [Context7 API guide](https://context7.com/docs/api-guide)
and [GitHub REST Git Trees](https://docs.github.com/en/rest/git/trees) and
[Git Blobs](https://docs.github.com/en/rest/git/blobs) APIs.

Set the key only on the server process:

```sh
CONTEXT7_API_KEY=ctx7sk-... cran-knowledge-mcp
```

Without the key, `get_context7_docs` returns `not_configured` and the
existing repository tools remain available. `get_package_knowledge` accepts
optional `question` and `revision`; unrequested sections are marked
`not_requested`, and each returned fragment retains its source URL and check
time.

## Configuration

Use `.env.example` as a reference and export only the settings you need in the
server process. The application does not automatically load `.env` files.
`MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, and `LOG_LEVEL` configure the CLI;
`HTTP_TIMEOUT_SECONDS` controls the httpx client timeout; `HTTP_USER_AGENT`
sets its bounded User-Agent header; `CACHE_TTL_SECONDS`
sets the repository artifact cache lifetime; `CACHE_MAX_BYTES` sets its byte
budget (maximum 256 MiB). GitHub guidance and Context7 use the same TTL override
with source-specific defaults of one and six hours. `CONTEXT7_API_KEY` is
optional. Invalid numeric bounds fail with an explicit configuration error.
Prompt settings include `PROMPT_INTELLIGENCE_ENABLED`,
`PROMPT_MAX_INPUT_CHARS`, `PROMPT_MAX_OUTPUT_CHARS`,
`PROMPT_MAX_GROUNDING_PACKAGES`, `PROMPT_DEFAULT_TARGET`, and
`PROMPT_DEFAULT_DETAIL_LEVEL`. See the prompt guide for bounds and meanings.

Compatibility returns `metadata_compatible`, `incompatible` or `unknown`, with a
nullable `compatible` flag. It checks the official R/release mapping, package R
constraints including patch requirements, and direct required dependency
availability/version/R constraints. It does not solve transitive dependencies,
inspect installed packages, or test platform binaries/system libraries.
Historical releases use current CRAN candidates and warn that these may not match
the historical environment. A successful metadata check is not an installation test.

`latest_cran_version` is retained only on CRAN results, separately from explicitly
unverified, client-supplied `installed_version`. Neither provider infers local state.

## Official sources and architecture

CRAN uses `/src/contrib/PACKAGES`, its name/title catalog and exact indexed source
archives. Recommended `Path` overrides cannot replace canonical root records.
Bioconductor uses:

- [config.yaml](https://bioconductor.org/config.yaml): release/devel and
  `r_ver_for_bioc_ver`, also used by BiocManager. No release number is fixed in code.
- `/packages/{version}/bioc/src/contrib/PACKAGES`: software.
- `/packages/{version}/data/annotation/src/contrib/PACKAGES`: annotation data.
- `/packages/{version}/data/experiment/src/contrib/PACKAGES`: experiment data.
- Exact indexed source archives for DESCRIPTION and raw `man/*.Rd`.
- Numeric versioned official package pages for vignette links. Page/index
  disagreement is an error; linked content is not downloaded or executed.

Archive identity and available index MD5 are checked. MD5 detects consistency
errors; HTTPS provides transport authenticity. No silent version substitution.
Sources reviewed: [installation](https://bioconductor.org/install/),
[release/R history](https://bioconductor.org/about/release-announcements/),
[BiocManager mapping](https://github.com/Bioconductor/BiocManager/blob/devel/R/version.R),
[Writing R Extensions](https://cran.r-project.org/doc/manuals/r-release/R-exts.html).
Source formats and live package requests were checked on 2026-10-22.

```text
src/cran_knowledge_mcp/
  server.py              MCP registration, lifecycle, stdio/HTTP CLI
  service.py             routing, provenance, combined results, compatibility
  releases.py            dynamic official Bioconductor/R map
  providers/protocol.py  PackageRepository extension contract
  providers/base.py      repository-neutral source/document operations
  providers/cran.py      CranProvider
  providers/bioconductor.py  BioconductorProvider, three categories per release
  providers/github_agents.py  pinned GitHub tree/blob reader for untrusted AGENTS.md
  providers/context7.py       optional, repository-matched Context7 client
  http.py                independent fixed-route policies, async HTTP, TTL/LRU
  parsers.py             bounded data-only DCF, HTML, gzip/tar and Rd aliases
```

See [architecture details](docs/ARCHITECTURE.md), [source authority](docs/sources.md),
[security model](docs/security.md), and [development rules](AGENTS.md).
For framework behavior and limits, see the
[Shiny, Positron and Quarto integration guide](docs/shiny-positron-quarto.md).
Visualization, tidyr and reproducible reporting analysis is described in the
[visualization and reporting guide](docs/visualization-data-reporting.md).

## Limits and security

No arbitrary outbound URLs, redirects, environment proxies, archive extraction,
R installation, package execution or Rd evaluation. Vignette links are restricted
to exact official host/package/release paths. Package text remains untrusted data.

CRAN/Bioconductor artifacts use a 5-minute TTL and 64 MiB / 32-artifact LRU
budget. External docs have bounded payloads and a six-hour success cache. GitHub
and Context7 use fixed HTTPS hosts and routes. No caller URL is fetched,
redirects are rejected, GitHub tree/blob sizes and per-file/total AGENTS.md
bytes are limited, and all external text remains untrusted.
At most eight Bioconductor release providers are retained per service. Downloads
are serialized per transport. Connect/read timeout is 15 seconds, download
deadline 45 seconds, tool deadline 60 seconds. No error cache or stale fallback.

Config: 1 MiB; index/catalog/page: 16 MiB; source download: 25 MiB; expanded tar:
128 MiB; members: 20,000; selected file: 2 MiB; selected files: 16 MiB. Oversized
annotation/experiment archives fail explicitly; index-level search/dependencies
still work. JSON tool data: 60,000 UTF-8 bytes; raw Rd: 8,000 characters per page;
direct dependency resolution: 250 entries.

HTTP defaults to loopback with DNS rebinding protection. A future domain can use
repeatable `--allowed-host cran.example.org` (include port if needed). Public
hosting needs TLS, ingress rate/body/concurrency limits and an egress policy.
There is no deployment, hosted endpoint, authentication or per-client rate
limiting here. Upstream documentation retains its package license.

## Docker

```sh
docker build -t cran-knowledge-mcp .
docker run --rm -p 127.0.0.1:8000:8000 cran-knowledge-mcp
# stdio:
docker run --rm -i cran-knowledge-mcp --transport stdio
```

The container runs as an unprivileged user. Binding `0.0.0.0` inside the container
allows port forwarding; HTTP Host validation remains enabled.

## Develop and verify

```sh
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest
```

CI tests Python 3.11–3.14 and builds Docker without pushing an image. Unit and
protocol tests mock HTTP and need no CRAN access. See [AGENTS.md](AGENTS.md).
For an optional real-source check after installation, run
`python scripts/smoke_cran.py`; it checks all five tools against CRAN without
assuming a package version.

## Known limitations and next stage

Documentation is raw Rd with literal aliases; macros and conditional content are
not rendered. Vignettes are verified link listings, not a claim that code was run
or every linked document was downloaded. Bioconductor history requires an
official mapping and all three retrievable indices. Missing/redirected legacy
endpoints fail explicitly. Workflows/books are outside the requested categories.

No local inspection, renv lock restoration, archived CRAN version lookup,
transitive solver, installation test or public hosting is included. Visualization
tools can inspect bounded lock JSON explicitly supplied by the client, without
restoring or verifying an installed library. See [the roadmap](docs/ROADMAP.md).
`analyze_r_workspace` only sees text provided by the client. Shiny and Quarto
analyzers are static checks, not runtime, schema-complete, browser or security
tests.
Optional live checks after installation: `python scripts/smoke_cran.py` and
`python scripts/smoke_repositories.py`.
