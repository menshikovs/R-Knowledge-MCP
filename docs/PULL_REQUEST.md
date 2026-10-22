# Add independent CRAN and Bioconductor repository providers

Extends the working CRAN MCP server while preserving default CRAN calls and the
existing version checker. This is a stacked change based on
`feat/initial-cran-knowledge-mcp`; main still has only the MIT baseline.

## Behavior

- Independent CranProvider and BioconductorProvider implement PackageRepository.
  Shared source/document and bounded HTTP layers remain repository-neutral.
- Official config.yaml dynamically resolves release/stable, devel, history and R
  mappings. No current release is coded. Supports software, annotation and
  experiment data PACKAGES with exact numeric release/package identities.
- Search/info/dependencies/docs support cran, bioconductor and all. Combined
  responses retain independent names and partial failures. Missing data cannot
  fall back to another release.
- Adds get_bioconductor_version, check_package_compatibility and
  get_package_vignettes. check_package_version remains CRAN-specific.
- Bioconductor dependencies resolve against selected-release indices and current
  CRAN; CRAN can opt in explicitly. Verbatim DCF constraints are retained.
- Application responses include identity, versions, URLs, UTC checks and status.
  Unknown R, devel and historical/current CRAN mixing carry explicit warnings.

## Safety

Independent fixed HTTPS routes, no redirects/proxies/arbitrary URLs, bounded
cache/download/archive/output. Safe YAML loading. No R, package code, Rd macro
or vignette execution. Vignette links are actually listed on a version-checked
package page and restricted to the pinned official host/package/release path.

## Validation

- 91 offline tests passed on Windows/Python 3.14 and Docker Linux/Python 3.11.
- Covers DESeq2/ggplot2, both dependency directions, categories, release/devel/
  history, R patch constraints, source failures, absent packages, unsafe YAML,
  SSRF, vignette version mismatch, paging and MCP protocol calls.
- Ruff lint/format, Docker build and container CLI checks passed.
- Live official-source checks passed for search, metadata, dependencies, raw Rd,
  vignette listings, R mapping, direct compatibility and release/devel discovery.
- Historical DESeq2 metadata was checked against the previous official release,
  selected dynamically without an assumed release number.

## Limits and follow-up

Compatibility covers R/release and direct required dependency metadata; it is
not a transitive solver or installation/platform test. Historical Bioconductor
uses current CRAN candidates with a warning. A separate follow-up with acceptance
criteria is in [issues/reproducible-compatibility.md](issues/reproducible-compatibility.md).

Rd remains raw with literal aliases; vignette content is not fetched or run.
Oversized data archives fail explicitly. History requires three retrievable
indices; there are no fake metadata or compatibility results.

README, AGENTS.md, architecture docs and roadmap are updated. No deployment,
paid service, publication or merge is part of this change.
