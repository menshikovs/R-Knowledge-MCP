# R Knowledge MCP

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
r-knowledge-mcp                         # stdio (default)
r-knowledge-mcp --transport streamable-http  # http://127.0.0.1:8000/mcp
```

The `cran-knowledge-mcp` command remains available as a backward-compatible
alias, and the Python import package remains `cran_knowledge_mcp`.

The project pins **mcp>=1.30,<2**. SDK 2 is the current stable major and renamed
FastMCP to MCPServer; using the maintained 1.x line preserves the requested
FastMCP API. See the [official SDK documentation](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
and [migration guide](https://py.sdk.modelcontextprotocol.io/migration/).

## Connect Codex

Use an absolute executable path from the installed virtual environment:

```sh
codex mcp add r-knowledge -- /absolute/path/R-Knowledge-MCP/.venv/bin/r-knowledge-mcp
codex mcp list
```

On Windows the executable is `.venv\Scripts\r-knowledge-mcp.exe`.
Alternatively put this in `~/.codex/config.toml` (use your actual absolute path):

```toml
[mcp_servers.r_knowledge]
command = "/absolute/path/R-Knowledge-MCP/.venv/bin/r-knowledge-mcp"
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

The default surface (`MCP_TOOLSET=consolidated`) has 16 tools. Every parameter has
a schema description, every tool has a title and `readOnlyHint=true`, and
`openWorldHint` is false only for tools that never contact an upstream service.
`MCP_TOOLSET=legacy` restores the original 35 tools unchanged (used by the Codex
benchmark conditions); resources and prompts are registered in both modes.

| Tool | Main arguments | Behavior | Replaces (legacy) |
| --- | --- | --- | --- |
| `search_packages` | `query`, `repository="cran"`, `bioc_version`, `limit`, `offset` | Ranked name/title search; every term must match | same name |
| `get_package` | `package`, `include=["metadata"]`, `repository`, `bioc_version`, `verify_archive=false`, `resolve_repositories`, `revision`, `question` | One call returns any of: metadata, dependencies, vignettes, agent_guidance (needs `revision`), context7 (needs `question`); each section keeps its own provenance and failure | `get_package_info`, `get_dependencies`, `get_package_vignettes`, `get_package_agent_guidance`, `get_context7_docs`, `get_package_knowledge` |
| `list_package_functions` | `package`, `repository`, `package_version`, `bioc_version`, `query`, `limit`, `offset`, `snapshot` | Source-backed exports, Rd aliases/topics and methods; explicit coverage, stable snapshot paging; runtime callability is not checked | new |
| `get_function_docs` | `package`, `function`, `offset`, `repository`, `bioc_version`, optional `package_version` | Raw Rd from the verified current source archive; a different requested version is an explicit error | `get_function_docs`, `get_shiny_docs`, `get_visualization_docs` |
| `check_package_version` | `package`, `installed_version` | Compare a client-supplied version with latest CRAN | same name |
| `check_r_compatibility` | `r_version`, optional `package`, `repository="cran"`, `bioc_version` | CRAN or Bioconductor R and direct dependency constraints; without `package` (Bioconductor) the official R/release map | `get_bioconductor_version`, `check_package_compatibility` (CRAN check is new) |
| `search_r_documentation` | `query`, `manuals`, `limit`, `r_version` | BM25 (SQLite FTS5) over the local index of six official R manuals | same name |
| `get_r_documentation_section` | `document_id`, `section_id`, `max_chars` | One indexed manual section | same name |
| `get_framework_docs` | `framework` (shiny/positron/quarto), `topic`, optional `version` and framework-specific fields | Page from the fixed official catalog | `explain_shiny_reactivity`, `get_positron_guidance`, `get_quarto_docs` |
| `get_r_workflow_guidance` | `scenario`, `packages`, `r_version`, `bioc_version`, `package_versions` | Framework scenarios combine docs and package knowledge; visualization scenarios group current Rd references | `get_r_workflow_guidance`, `get_visualization_workflow` |
| `analyze_r_source` | `kind` (ggplot, ggraph, tidyr, ggplotly, knitr, shiny, quarto), `source`, `schemas`, kind-specific options | Bounded static analysis; options that the selected kind cannot use are rejected, not ignored | `analyze_ggplot_code`, `analyze_ggraph_code`, `analyze_tidyr_pipeline`, `analyze_ggplotly_compatibility`, `analyze_knitr_chunks`, `analyze_shiny_app`, `analyze_quarto_document` |
| `analyze_r_project` | `files`, optional `file_manifest` | Workspace metadata; adds Quarto project analysis when `_quarto.yml` is supplied | `analyze_r_workspace`, `analyze_quarto_project` |
| `recommend_technology_stack` | objective, project type, requirements, stack, target, preferences | Provisional architecture with repository-checked candidates | same name |
| `build_r_prompt` | `request`, `mode="build"` or `"improve"`, prompt options | Build a prompt, or improve an existing one verbatim | `build_r_prompt`, `improve_r_prompt` |
| `validate_r_prompt` | `prompt_text` | Heuristic structural checklist | same name |
| `get_r_prompt_context` | `packages`, R/Bioconductor versions | Verified package context for prompt grounding | same name |

For proactive discovery, version pinning, matching, diagnostics and Python/Rust behavior,
see [Verified function discovery](docs/FUNCTION_DISCOVERY.md). Set
`FUNCTION_DISCOVERY_ENABLED=false` to disable only the additive discovery tool
for a controlled comparison; existing tools and server instructions stay identical.

Tools that return repository data accept `verbosity="compact"` (default) or
`"full"`. Compact responses omit repeated static notes (`limitations`,
`verification_notes`) and merge nested `sources` lists into one deduplicated
top-level list; nested results keep their own `source_url` and `checked_at`, and
safety fields such as `trust` and `not_executed` are always present. Results that
still exceed 60,000 bytes have their longest text fields shortened and list each
cut in `output_truncation`.

Resources (both tool sets):

| URI | Content |
| --- | --- |
| `r-knowledge://framework-docs` | Fixed Shiny, Positron and Quarto topic catalog |
| `r-knowledge://prompt-templates` | Built-in prompt template identifiers |
| `r-manual://{document_id}` | Section ids and headings of one indexed R manual |
| `r-manual://{document_id}/{section_id}` | One manual section (up to 32,000 characters) |
| `cran://{package}/man/{alias}` | First page of raw Rd for one alias from current CRAN |

`repository` accepts **cran**, **bioconductor**, and **all**. Existing calls default
to CRAN. `all` keeps separate identities when names overlap, and exposes source
failures in `errors` with `verification_status="partial"` or `"failed"`. Absence
from a checked index differs from an unavailable source. Combined search orders
CRAN results then Bioconductor results, using a shared offset/limit (1-20).
Within a repository, results rank exact names first, then name prefixes and name
words, then title words; title terms match whole words or word prefixes, so
`api` does not match `therapy`.

See [Technology stack recommendations](docs/TECHNOLOGY_STACK_RECOMMENDATION.md) for
the input example, evidence contract, and limits of `recommend_technology_stack`.

The legacy `get_package_info` keeps deep archive verification as its default;
`get_package` defaults to `verify_archive=false`. Without archive verification:
CRAN reads the official per-package DESCRIPTION and checks its exact package and
version against PACKAGES; if that optional endpoint returns 404, the tool returns
partial index-only metadata and identifies missing fields. Bioconductor returns
metadata available in the selected release's software, annotation, and experiment
PACKAGES index. It does not fetch a current package page or substitute another
release when DESCRIPTION fields are absent.

Inspect `metadata_verification_level` before relying on a result:

```json
{
  "package": "ExamplePkg",
  "repository": "cran",
  "package_version": "2.10-1",
  "bioc_version": null,
  "verification_status": "verified",
  "metadata_verification_level": "description_version_matched",
  "source_url": "https://cran.r-project.org/web/packages/ExamplePkg/DESCRIPTION",
  "checked_at": "2026-10-22T00:00:00+00:00"
}
```

`index_verified` means the record came from the selected repository index;
`description_version_matched` means a DESCRIPTION identity matched that index;
`archive_checksum_verified` means the indexed archive checksum was present and
matched. If an archive has no indexed checksum, deep mode still checks its
DESCRIPTION package/version and reports `description_version_matched`.
`verification_status` continues to describe whether the returned data was
retrieved and validated; it does not imply the strongest assurance level.

Only `get_package_info` exposes the lightweight option. `get_package_knowledge`,
GitHub AGENTS.md, Context7, Prompt Intelligence package grounding, and function
Rd retrieval retain deep verification by default. Dependencies and Bioconductor
compatibility already use the selected indices. See [source assurance and
performance measurements](docs/sources.md).

Prompt Intelligence also registers fourteen standard MCP Prompts, including
`r-multi-stage-workflow`, which uses the same bounded local composition pipeline
as `build_r_prompt` but does not query package providers. The other prompts cover package
development, Shiny, Quarto, Bioconductor, ggplot2, debugging, architecture,
CSV import/cleaning/validation, SQL queries/database connections, and CSV-to-SQL.
They are user-selected, deterministic drafts. Connect clients that
support MCP Prompts through their normal prompt discovery UI; MCP tools
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
Complete tool failures now set MCP `isError=true`, while preserving the structured
`error.code` envelope. Partial results keep `isError=false` and retain their
section-level failures. Clients should inspect `isError` first, then check
`verification_status` and aggregate `errors` before using results. See
[MCP tool errors and partial results](docs/MCP_ERRORS.md) for the compatibility
note and response examples.

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
CONTEXT7_API_KEY=ctx7sk-... r-knowledge-mcp
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
`LOG_INTERNAL_TRACEBACKS=true` opts into DEBUG tracebacks that can contain
request or upstream data, so use it only in a protected diagnostic environment;
`HTTP_TIMEOUT_SECONDS` controls the httpx client timeout; `HTTP_USER_AGENT`
sets its bounded User-Agent header; `CACHE_TTL_SECONDS`
sets the CRAN/Bioconductor artifact cache lifetime; `CACHE_MAX_BYTES` sets its
byte budget (maximum 256 MiB). GitHub guidance and Context7 use the same TTL
override with source-specific defaults of one and six hours. Framework pages
use a one-hour cache. `CONTEXT7_API_KEY` is
optional. Invalid numeric bounds fail with an explicit configuration error.
Prompt settings include `PROMPT_INTELLIGENCE_ENABLED`,
`PROMPT_MAX_INPUT_CHARS`, `PROMPT_MAX_OUTPUT_CHARS`,
`PROMPT_MAX_GROUNDING_PACKAGES`, `PROMPT_DEFAULT_TARGET`, and
`PROMPT_DEFAULT_DETAIL_LEVEL`. See the prompt guide for bounds and meanings.
`MCP_TOOLSET` selects `consolidated` (default, 16 tools) or `legacy` (the original
35). `GITHUB_TOKEN` is optional; it raises the GitHub API limit for AGENTS.md
lookups from 60 to 5,000 requests per hour, is sent only as an `Authorization`
header to `api.github.com`, and never appears in URLs, logs or results.
`R_KNOWLEDGE_NATIVE=0` forces the pure-Python implementations even when the
optional Rust extension is installed.

CRAN and Bioconductor indexes are fetched as `PACKAGES.gz` (falling back to
`PACKAGES` only when the compressed file is absent). Expired cache entries are
revalidated with `If-None-Match`/`If-Modified-Since`; a `304` keeps the parsed
index and records the new `checked_at`, while any error still fails explicitly
instead of serving stale data.

Compatibility returns `metadata_compatible`, `incompatible` or `unknown`, with a
nullable `compatible` flag. For CRAN it checks the current record's `R (...)`
constraint and its direct required dependencies in the CRAN index; dependencies
outside CRAN, or a patch-level bound for an R minor version such as `4.1`, make
the result `unknown`. Only the current CRAN version is checked. For Bioconductor
it checks the official R/release mapping, package R
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

CRAN/Bioconductor artifacts use a configurable 5-minute default TTL and a
64 MiB / 32-artifact LRU budget. Framework pages use a one-hour cache; GitHub
AGENTS.md uses a configurable one-hour default, and Context7 uses a configurable
six-hour default. Provider caches are bounded and failed requests never replace
fresh data. GitHub and Context7 use fixed HTTPS hosts and routes. No caller URL is fetched,
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
docker build -t r-knowledge-mcp .
docker run --rm -p 127.0.0.1:8000:8000 r-knowledge-mcp
# stdio:
docker run --rm -i r-knowledge-mcp --transport stdio
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

Optional Rust accelerators live in `native/` (PyO3, abi3 wheel for CPython
3.11+). The same scanner also accelerates conservative NAMESPACE discovery through the
shared Python semantic layer. No additional native parser/network policy is required.
They speed up R source scanning (5–9x on 250 KiB inputs) and package
search ranking (about 12x on 22k packages). The pure-Python code remains the
reference: without the extension everything works identically, and
`tests/test_native_parity.py` compares both implementations on generated inputs
(it is skipped when the extension is absent).

```sh
cd native
maturin build --release -i ../.venv/bin/python   # Windows: ..\.venv\Scripts\python.exe
pip install target/wheels/cran_knowledge_native-*.whl
cargo clippy --release -- -D warnings
```

CI tests Python 3.11–3.14 and builds Docker without pushing an image. Unit and
protocol tests mock HTTP and need no CRAN access. See [AGENTS.md](AGENTS.md).
For optional live checks after installation, run `python scripts/smoke_cran.py`
or `python scripts/smoke_repositories.py`. The scheduled
`python scripts/smoke_upstream.py` check covers selected official CRAN,
Bioconductor, Shiny, Positron and Quarto sources. It also runs manually through
the `Official upstream smoke checks` Actions workflow on the default branch.
Live source checks are separate from ordinary PR CI because upstream outages
are outside the repository's control. Coverage, failure categories and limits
are described in [Upstream monitoring](docs/UPSTREAM_MONITORING.md).

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
Optional live checks after installation: `python scripts/smoke_cran.py`,
`python scripts/smoke_repositories.py` and `python scripts/smoke_upstream.py`.
