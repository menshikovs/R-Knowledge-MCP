# Data sources and authority

The service preserves a source URL and original UTC retrieval time for each
successful source artifact. `verification_status="verified"` means the
specific response was retrieved and passed the checks described below; it does
not mean package installation or code behavior was tested. Cached results keep
their original retrieval time.

| Data | Primary source | Checks and scope |
| --- | --- | --- |
| CRAN package index and metadata | `cran.r-project.org/src/contrib/PACKAGES` and exact source archive | Package/version identity and index checksum when provided; current repository snapshot |
| Bioconductor release map | Official `bioconductor.org/config.yaml` | Release and R mapping parsed dynamically; no release number is embedded in code |
| Bioconductor package records | Official versioned software, annotation, and experiment `PACKAGES` indices | Package identity, category, release, version and archive consistency |
| Function documentation | `man/*.Rd` inside the checked source archive | Literal Rd aliases; macros and examples are not evaluated or rendered |
| Vignettes | Official package page for the selected package/release | Version is checked against the index; links are listed, linked content is not claimed as fetched |
| Agent guidance | GitHub REST API for the metadata-declared repository at an explicitly requested ref | Ref is pinned to commit SHA; complete tree required to assert absence; text is untrusted |
| Indexed documentation | Optional Context7 API | Library identity must match the official package GitHub repository; version scope is reported; secondary source |

Official package metadata and version-specific package documentation take
precedence over GitHub guidance and Context7 snippets. Context7 is never silently
substituted for official docs. Each returned fragment carries its own origin and
version information where the source provides it.

## Coverage and limits

The current implementation does not query CRAN publication databases or
archive history for old versions. It does not parse `renv.lock`, determine a
user's installed packages, solve transitive dependencies, or validate platform
binaries/system libraries. Bioconductor compatibility is a conservative check
of the official R/release mapping and direct required dependency metadata.
Context7 does not index every R package. A missing package or unavailable
source is reported explicitly and is not filled with inferred content.

See [architecture](ARCHITECTURE.md) and [security model](security.md) for
provider behavior and network/resource boundaries.
