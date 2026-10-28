# Data sources and authority

The service preserves a source URL and original UTC retrieval time for each
successful source artifact. `verification_status="verified"` means the
specific response was retrieved and passed the checks described below; it does
not mean package installation or code behavior was tested. Cached results keep
their original retrieval time.

| Data | Primary source | Checks and scope |
| --- | --- | --- |
| CRAN package index and metadata | `cran.r-project.org/src/contrib/PACKAGES`, per-package `web/packages/{name}/DESCRIPTION`, and exact source archive | Exact package/version match; archive MD5 when supplied; current repository snapshot |
| Bioconductor release map | Official `bioconductor.org/config.yaml` | Release and R mapping parsed dynamically; no release number is embedded in code |
| Bioconductor package records | Official versioned software, annotation, and experiment `PACKAGES` indices | Package identity, category, release and version; index records may omit descriptive fields |
| Function documentation | `man/*.Rd` inside the checked source archive | Literal Rd aliases; macros and examples are not evaluated or rendered |
| Vignettes | Official package page for the selected package/release | Version is checked against the index; links are listed, linked content is not claimed as fetched |
| Agent guidance | GitHub REST API for the metadata-declared repository at an explicitly requested ref | Ref is pinned to commit SHA; complete tree required to assert absence; text is untrusted |
| Shiny framework guidance | Fixed pages on `shiny.posit.co` | Current official articles; not version-pinned |
| Positron guidance | Fixed pages on `positron.posit.co` | Current official IDE docs; no GUI/session access |
| Quarto guidance | Fixed pages on `quarto.org` | Current official authoring/project docs; not version-pinned |

Framework catalog pages were checked against the official documentation on
2026-10-22. A topic lookup fails explicitly when the upstream page is missing or
unavailable; it never substitutes another framework's page or a third-party service.

Official package metadata and version-specific package documentation take
precedence over GitHub guidance. Third-party documentation is never silently
substituted for official docs. Each returned fragment carries its own origin and
version information where the source provides it.

## Package metadata assurance

`get_package_info` defaults to deep archive verification for compatibility. The
optional `verify_archive=false` mode is intended for bounded metadata lookups
where transferring a large source archive is unnecessary.

CRAN's `web/packages/{name}/DESCRIPTION` endpoint returned HTTP 200 for the
verified sample `ggplot2` on 2026-10-22. It is a fixed, package-name-validated
route with a 2 MiB response limit and redirects disabled. The selected record
must contain one DCF record whose exact Package and Version match the CRAN
`PACKAGES` index. A 404 is explicitly reported as partial index-only metadata;
other source errors stay errors. The route is not assumed to exist for every
package.

Bioconductor's `config.yaml` and selected-release `PACKAGES` files were verified
at HTTP 200 without redirects for release 3.23, historical 3.22, and devel 3.24
on 2026-10-22. This was checked for software, annotation, and experiment
indices. Sample records contain version/dependency/license fields but do not
reliably contain Title, Description, Author, or URL. Lightweight mode therefore
returns only the exact index record's available fields with level
`index_verified`. It does not use the HTML package pages or borrow metadata from
another category or release. Historical and devel index availability is still
required; a missing index remains an explicit error.

The additive `metadata_verification_level` values are:

- `index_verified`: selected official PACKAGES record parsed and package identity
  found in the requested repository/category/release.
- `description_version_matched`: official DESCRIPTION or archive DESCRIPTION
  matched the exact index package/version; no archive checksum guarantee is
  implied.
- `archive_checksum_verified`: exact archive matched an MD5 checksum provided
  by the selected index, and its DESCRIPTION identity matched.

The existing `verification_status` remains `verified` when returned fields have
been retrieved and checked, even if the metadata assurance is only
`index_verified`; it becomes `partial` when CRAN falls back to index-only fields
because the optional DESCRIPTION route is absent. Consumers should inspect the
assurance level and `metadata_fields_missing`, not infer it from the broad status.

GitHub AGENTS.md, `get_package_knowledge`, Prompt
Intelligence package grounding, and exact function Rd docs retain deep archive
verification by default. Dependencies and compatibility use repository indices.
Vignette links retain their version-checked official package-page contract.
Thus an explicit lightweight call to `get_package_info` does not weaken those
trust boundaries.

## Deterministic transfer measurements

`tests/test_metadata_modes.py` measures response body bytes, request counts,
elapsed client time, cache hits, and archive requests through
`httpx.MockTransport`; it compares separate lightweight and deep calls using
fixed synthetic CRAN metadata and deterministic 2 KiB (small) and 180 KiB
(medium) archive payloads. It also confirms the lightweight CRAN call never
opens a lazy 26 MiB archive stream. The large Bioconductor experiment test
measures config plus three selected-release index responses and verifies that
no archive request occurs. These are reproducible test-fixture measurements,
not production benchmarks, and mock timings make no latency claims.

`RepositoryHTTP` narrowly negative-caches only `source_too_large` failures for
60 seconds, with a 128-route bound. The route key is exact: repository transport
instances are separate, and Bioconductor paths include release/category while
archive paths include package version. Errors remain explicit and cache hits
carry `error.cached=true`; no absence or stale metadata is inferred. Rate limits,
other transport failures and not-found responses are not cached.

## Coverage and limits

The current implementation does not query CRAN publication databases or
archive history for old versions. It does not parse `renv.lock`, determine a
user's installed packages, solve transitive dependencies, or validate platform
binaries/system libraries. Bioconductor compatibility is a conservative check
of the official R/release mapping and direct required dependency metadata.
A missing package or unavailable
source is reported explicitly and is not filled with inferred content.

See [architecture](ARCHITECTURE.md) and [security model](security.md) for
provider behavior and network/resource boundaries.
