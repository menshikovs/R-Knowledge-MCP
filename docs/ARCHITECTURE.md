# Repository architecture

`server.py` exposes MCP tools through the official SDK. It delegates to
`KnowledgeService`, which routes operations, adds identity/provenance/status
envelopes, combines independent results, and checks direct compatibility.
The ASGI lifespan owns the shared client and service/cache across stateless HTTP
requests; stdio owns the same resources for its process session.

## Provider contract

`PackageRepository` is a structural Protocol with repository identity, optional
Bioconductor release, index/current lookup, search, package metadata,
dependencies, function docs and vignette operations. A provider does not have to
inherit another provider. `CranProvider` and `BioconductorProvider` independently
implement this contract and share `SourceRepository`'s bounded, data-only source
archive and package-page operations.

Another repository can implement the Protocol, supply its fixed HTTP policy and
be registered through `KnowledgeService(..., providers={...})`. Add its public
selector to the MCP Literal schema and tests deliberately. No caller can turn a
repository identifier into an arbitrary URL or host.

`RepositoryHTTP` implements shared async transport and TTL/LRU policy.
`CranHTTP` and `BioconductorHTTP` own independent immutable host/route policies.
Both reject redirects, URL query strings and traversal. They share an httpx
connection pool but have separate artifact cache budgets. At most eight parsed
Bioconductor providers are retained. All byte/time limits remain in force.
`HTTP_TIMEOUT_SECONDS`, `HTTP_USER_AGENT`, `CACHE_TTL_SECONDS`, and `CACHE_MAX_BYTES` tune the
client timeout and repository artifact cache within validated bounds.
`MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, and `LOG_LEVEL` configure the CLI;
Context7 credentials are read only from `CONTEXT7_API_KEY`.

## Bioconductor identity and release resolution

Package identity is `(repository, bioc_version, category, package, package_version)`.
CRAN uses `null` for Bioconductor release. Bioconductor categories are software,
annotation and experiment data, mapped to fixed `bioc`, `data/annotation` and
`data/experiment` routes. Duplicate names across Bioconductor categories are an
explicit ambiguity error; cross-repository names are retained separately.

`BioconductorReleases` safely parses the bounded official config.yaml used by
BiocManager. It validates release/devel and R mappings. Aliases are resolved to
numeric versions before any index/archive/page fetch; no numeric release is
hard-coded. Historical versions must be in that mapping and their indices must
be available. Partial/missing indices fail; they cannot silently establish absence
or cause fallback to the current release. Alias/config refresh creates a new
provider snapshot when its checked mapping changes.

## Result and error contract

Every application envelope has package/repository/package-version/Bioconductor-
version identity, primary source URL, UTC check time, verification status and
all supporting sources. Nulls mean not applicable or unknown, never invented data.
Search results carry this identity individually. Aggregate `all` envelopes have
no single package version or primary source URL; their children retain both.

`verified` means the stated data was obtained and validated, not that installation
was tested. `partial` aggregate results retain explicit failures. A checked
package absence differs from an unavailable source. Errors preserve attempted
time and known source URL. Cached successes preserve their original check time;
failures are not cached, and stale successes are not used after expiration.

## Dependencies and compatibility

Original DCF dependency fields remain verbatim. Bioconductor dependencies are
resolved against the exact selected release's three indices and current CRAN.
CRAN retains its previous lightweight behavior unless `resolve_repositories`
is requested; `all` resolves both origins. Candidate records preserve source
timestamps and constraints. R/base packages are runtime dependencies; their
installed versions are not inspected. Ambiguous/unavailable dependencies remain
explicit. No name-based guess assigns an unknown dependency to a repository.

Compatibility checks official R major/minor mapping, direct package R patch
constraints, direct required dependency versions and their R requirements.
Suggests are listed but do not determine required-dependency compatibility.
Unresolved required dependencies yield `unknown`, never a positive claim. A
negative check is scoped to the selected release and current CRAN snapshot.
Historical/current CRAN mixing is warned about. This is not a transitive solver,
platform binary check or test of the user's installation.

## Documents and trust boundaries

Function docs are exact raw Rd, selected by literal alias from a matching indexed
source archive. Available index MD5, package name and version are checked.
Archive expansion, members, selected files and response sizes are bounded. Files
are never extracted; no R, examples, macros or package scripts run.

Vignettes are links actually present on the official package page, after its
Version cell matches PACKAGES. Links must stay within the pinned package path on
the official host. The server reports `listed_by_official_package_page` and
`content_fetched=false`; it does not claim to have downloaded or run linked docs.

## GitHub AGENTS.md provider

`GitHubAgentsProvider` receives only `DESCRIPTION` URL values after the selected
CRAN/Bioconductor provider checks the source archive against its index. It
accepts one unambiguous HTTPS `github.com/{owner}/{repo}` reference. The fixed
`api.github.com` transport verifies the canonical repository name, resolves an
explicit branch/tag/SHA through the commits endpoint, and traverses the
recursive tree for that immutable commit SHA. The GitHub tree API exposes a
`truncated` marker; truncation is an explicit incomplete-source error, never a
verified absence. AGENTS.md blobs are fetched by validated blob SHA, never by a
URL embedded in repository data. Redirects are rejected.

The response includes each path, its directory subtree scope, exact commit SHA,
GitHub source URL and per-file check time. A complete tree with no matching
files is `verified_absent`. The provider does not guess a tag from the package
version: clients select a branch, tag or SHA, and the resolved SHA is returned.
Tree JSON is capped at 4 MiB, individual files at 32 KiB, total file text at
96 KiB, and count at 24. Files are UTF-8 data; no shell, R or external command
runs. Content is marked `untrusted_reference_only` and cannot override system
instructions.

## Context7 provider

`Context7Provider` is disabled when `CONTEXT7_API_KEY` is unset. Its only routes
are the documented library-search and context endpoints on `context7.com`; the
key is sent in a bearer header, never to the caller or URL. The provider starts
from verified package `DESCRIPTION` URLs, searches by package name and official
GitHub repository hint, and requires exactly one returned Context7 library ID
matching that repository before retrieving docs. This prevents a same-name
library from being silently substituted. It pins the R package version only
when Context7 explicitly lists an exact match; otherwise it labels docs
unpinned.

Questions are bounded and common credential patterns are redacted before they
leave the server. Context7 responses are capped at 4 MiB and 48 KiB of returned
fragment text. Successful documentation results are cached for six hours;
errors, including HTTP 429 and Retry-After, are surfaced. Each fragment
identifies its library, source URL, package/repository identity, version scope
and check time. Context7 remains a secondary indexed source, not an authority
above official package archives or docs.

`get_package_knowledge` combines package info and dependencies with optional
AGENTS.md and Context7 sections. Every section preserves its own errors and
provenance. Omitting a revision or question is explicitly `not_requested`, not
evidence that the respective source has no content.

## Validation

Offline tests use synthetic HTTP responses, including mocked GitHub and Context7
APIs, and real package names with deliberately synthetic versions. They cover
CRAN regressions, release/devel/history, all three categories,
cross-repository dependencies, R compatibility, unavailable sources, malformed
YAML, missing packages, pinned vignette links, pagination, external repository
matching, commit-pinned nested AGENTS.md scopes, verified absence versus
truncated trees, Context7 version selection, key isolation, redaction and rate
limits, and MCP stdio/HTTP. Optional smoke scripts exercise real official
sources separately.
