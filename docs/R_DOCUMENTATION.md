# Official R Manual Search

R-Knowledge-MCP can index and search six fixed official R manuals hosted by
CRAN. MCP requests read a local index and never fetch pages. Refresh is an
explicit operator action.

## Registered sources

| Document ID | Source title | Canonical URL |
| --- | --- | --- |
| `r-data-import-export` | R Data Import/Export | <https://cran.r-project.org/doc/manuals/r-release/R-data.html> |
| `r-installation-administration` | R Installation and Administration | <https://cran.r-project.org/doc/manuals/r-release/R-admin.html> |
| `writing-r-extensions` | Writing R Extensions | <https://cran.r-project.org/doc/manuals/r-release/R-exts.html> |
| `r-internals` | R Internals | <https://cran.r-project.org/doc/manuals/r-release/R-ints.html> |
| `r-faq` | R FAQ | <https://cran.r-project.org/doc/FAQ/R-FAQ.html> |
| `introduction-to-r` | An Introduction to R | <https://cran.r-project.org/doc/manuals/r-release/R-intro.html> |

The registry is compiled into `providers/r_documentation.py`. Tool arguments
select registered document IDs only; they cannot choose a URL or host.

## Build and refresh the local index

Install the project in its Python environment, then explicitly run:

```powershell
python -m cran_knowledge_mcp.providers.r_documentation --refresh
```

This command contacts the six registered CRAN sources. Run it only as a
separately approved operator action; MCP tool calls and prompt generation do
not trigger a refresh.

On Linux or macOS, use the same command in the environment where the MCP server
runs. To select a different local cache path, add `--index-path PATH` or set
`R_DOCUMENTATION_INDEX_PATH`. Neither setting is accepted from MCP arguments.
Ordinary tool calls, prompt generation, and stack recommendations never refresh
the index.

Refresh uses the six fixed HTTPS URLs, bounded response sizes and timeouts,
`trust_env=False`, and no redirects. A redirect is reported as unavailable
until its destination can be reviewed and added to the fixed source policy.
Conditional ETag and Last-Modified requests reuse unchanged indexed content.
Refresh writes a temporary file in the cache directory and atomically replaces
the previous JSON index. This is an atomic-replacement mechanism, not a
power-loss durability guarantee. Failed refreshes retain previously indexed
sections and mark them `stale_after_refresh_error`; the response includes a
per-source status.

The index contains section text needed for local retrieval. It is kept in the
user cache, not checked into the repository. CRAN source licensing and
attribution must be reviewed before distributing a generated manual index or
reproducing larger excerpts. This repository does not bundle or publish the
manuals.

## MCP tools

`search_r_documentation` accepts a query, optional registered `manuals`, a
result `limit` from 1 to 10, and an optional exact `r_version`. It performs
bounded lexical keyword matching; no semantic model or paid inference is
used. Results include document and section identity, heading hierarchy,
short excerpt, canonical source and anchor URLs, detected R version, retrieval
and check times, content hash, refresh status, matched terms, and a lexical
relevance score.

`get_r_documentation_section` accepts the `document_id` and opaque `section_id`
returned by search and retrieves that exact indexed section, returning at most
8,000 characters by default (configurable up to 32,000 characters). Truncated
sections report their full character count and a `truncated` flag. Neither tool
executes R code or documentation examples.

Example search:

```json
{
  "query": "CSV import connections encodings",
  "manuals": ["r-data-import-export"],
  "limit": 3,
  "r_version": "4.5.1"
}
```

Versioned sections for another requested R version are excluded. If only
different versioned content is available, the result reports
`requested_r_version_unavailable`. A manual without a detected version may be
returned as `unversioned_source`, with compatibility left unknown. The `r-release`
URLs move over time; content hash, detected version, retrieval time and last
check time make that movement visible. The index does not provide historical
manual versions.

The parser retains heading-based sections, anchors when present, code blocks,
function names and table cell boundaries, while removing common navigation,
script, style and footer content. Content is bounded and treated as untrusted
reference data. Keyword matching is lexical and can miss relevant passages.

## Prompt Intelligence and stack recommendations

Prompt Intelligence searches only the relevant selected manuals for supported
task categories, adds at most two bounded excerpts, and cites each source. The
generated English instruction labels retrieved text as untrusted reference
material; caller-supplied multilingual text remains unchanged. If the index is
missing, corrupt, stale, or has no usable matching sections, the prompt reports
that evidence is unavailable and continues without inventing manual claims.

`recommend_technology_stack` uses the same local retrieval interface for R
runtime, package-development, programming, or data import/export topics. Its
`official_r_documentation` field contains citations and excerpts separately
from package metadata. R manuals do not substantiate recommendations about
unrelated third-party products, prove installation success, or establish a
solved dependency graph.

## Index and verification status

The MCP surface distinguishes an unavailable index (`index_unavailable`), an
invalid or unsupported-schema index (`index_invalid`), a valid index with no
sections (`index_empty`), unavailable source content (`sources_unavailable`),
no query matches (`no_matching_sections`), and successful indexed results.
Refresh failures that retain previous content are reported per source as
`stale_after_refresh_error`; returned citations also include the original
retrieval time and latest successful check time. No age-based expiry threshold
is configured, so callers must assess those timestamps rather than treating
old content as current. `indexed_official_documentation`
means a local index was built from a fixed official URL; it does not mean that
the current live page was checked during the tool call. Search returns the
original retrieval timestamp, latest successful check time, refresh status and
SHA-256 content hash so callers can judge freshness.

Offline tests use local HTML fixtures and mocked HTTP transports. They cover
section parsing, heading hierarchy, anchors, code and tables, metadata,
duplicates, refresh validators, search ranking, version mismatches, redirect
rejection, MCP schemas and invocation, prompt citations, and graceful behavior
without an index. No manual downloads are needed to run them.
