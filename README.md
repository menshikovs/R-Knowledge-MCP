# CRAN Knowledge MCP

Read-only MCP server providing source-attributed information about current R
packages on CRAN. Python 3.11+, official Python MCP SDK (FastMCP), async httpx.
MIT licensed. No R runtime, API key, or paid service is required.

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

## Tools

| Tool | Parameters | Data returned |
| --- | --- | --- |
| `search_packages` | `query`, `limit=10` (1–20), `offset=0` | Name/title keyword search, current CRAN versions, total, next offset |
| `get_package_info` | `package` | Version, title, description, authors, raw Authors@R, license, URLs |
| `get_dependencies` | `package` | Verbatim Depends, Imports, Suggests, LinkingTo constraints |
| `get_function_docs` | `package`, `function`, `offset=0` | Raw Rd text matched by literal alias, package version, archive member, pagination |
| `check_package_version` | `package`, `installed_version` | Numeric R comparison: older, equal, newer |

Example requests: `get_function_docs(package="dplyr", function="filter")`,
`search_packages(query="linear models")`. Function names are aliases rather than
evaluated R expressions. Rd examples and macros are returned as data only.

Each successful result contains `sources`, with `source_url` and UTC `checked_at`
for every artifact used. A cached result retains the time of its original check.
Read and cite these fields. A source failure returns an explicit `error` object
with `code`, `message`, `source_url` when known, and `attempted_at`; clients must
check this field before using results. MCP schema validation errors are handled
by the SDK. Missing optional DESCRIPTION fields are `null`; absent dependency
fields are empty strings. Neither means a source request failed.

`latest_cran_version` is the version in the CRAN source index, not a claim about
the user's environment. `installed_version` is unknown (`null`) in package info;
in version checks it is supplied by the client and explicitly marked unverified.
Comparison uses numeric components separated by dots or hyphens and ignores
trailing zero components. It does not test R/platform compatibility or upgrades.

## Sources and architecture

All runtime requests go to fixed HTTPS routes on **cran.r-project.org**:

- `/src/contrib/PACKAGES`: authoritative version and dependency index (DCF).
- `/web/packages/available_packages_by_name.html`: package names and title keywords.
- `/src/contrib/{package}_{version}.tar.gz`: DESCRIPTION and `man/*.Rd` for the
  exact indexed version. Package/version identity and available index MD5 are
  checked before returning metadata or documentation. MD5 detects consistency
  errors; HTTPS provides transport authenticity.

No third-party metadata snapshot is treated as current CRAN. R-universe's
[documented APIs](https://docs.r-universe.dev/browse/api.html) were evaluated;
they include development builds, so this first version uses CRAN artifacts
directly. DCF, DESCRIPTION and Rd behavior follow
[Writing R Extensions](https://cran.r-project.org/doc/manuals/r-release/R-exts.html).
Documentation and live source formats were checked on 2026-10-22.
The canonical source index scope is the `src/contrib` root. Entries carrying
`Path` overrides for R-specific Recommended subdirectories are excluded, so they
cannot overwrite the canonical package version or its dependency constraints.

```text
src/cran_knowledge_mcp/
  server.py     FastMCP registration, lifecycle, stdio/HTTP CLI
  service.py    transport-independent knowledge operations
  http.py       fixed routes, async HTTP, TTL/LRU, provenance
  parsers.py    DCF, catalog HTML, bounded gzip/tar, literal Rd aliases
  errors.py     explicit domain errors
tests/          synthetic HTTP fixtures, parsers, MCP transport tests
docs/ROADMAP.md follow-up work and acceptance criteria
```

## Limits and security

- No arbitrary outbound URLs, redirect following, environment proxies, archive
  extraction, R installation, package code execution or Rd evaluation.
- Connect/read timeout 15 seconds, download deadline 45 seconds, tool deadline
  60 seconds. Downloads are serialized per service instance.
- Process-local cache: 5-minute TTL, 64 MiB / 32 artifact LRU limit. No stale
  fallback and no caching of failures. A cached successful check does not probe
  whether CRAN is currently reachable.
- Index/catalog: 16 MiB each; compressed source: 25 MiB; expanded tar: 128 MiB;
  20,000 archive members; each selected file: 2 MiB; selected files: 16 MiB.
- Tool data is limited to 60,000 UTF-8 JSON bytes. Documentation uses 8,000
  character pages and explicit `next_offset`; search supports pagination.
- HTTP defaults to loopback with DNS rebinding protection. For a future domain,
  pass repeatable `--allowed-host cran.example.org` (include port when applicable).
  Keep a trusted TLS reverse proxy and network egress policy for public hosting.
  This release has no user authentication or per-client rate limiting; public
  hosting needs ingress limits and operational review. It is not deployed here.
- Package text and links are untrusted content. They are never fetched as URLs
  or followed as instructions. Returned upstream documentation retains its own
  package license; this project's MIT license covers the server code.

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

Search covers names and titles, not descriptions, vignettes or full manuals.
Documentation is raw Rd, with literal aliases only; user macros and conditional
content are not expanded. Built-in R functions and archived package versions are
outside the current CRAN source index. A package exceeding limits returns a
clear error. CRAN releases can change between index and archive downloads; a
404/checksum mismatch is an error, never a silent version substitution.

No local filesystem inspection, `renv.lock` parser, historical docs, dependency
solver, OAuth, distributed cache, or hosted service is included. See
[the roadmap](docs/ROADMAP.md) for explicit follow-up tasks.
