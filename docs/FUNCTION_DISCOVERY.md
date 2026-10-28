# Verified package API discovery

Use **list_package_functions** when the precise R function name is unknown. First
identify the package/repository, inspect its source-backed declarations and
documented names, then call **get_function_docs** with a returned literal alias.
The tool is part of the consolidated surface; the legacy surface is unchanged.

## Inputs

| Argument | Default | Meaning |
|---|---|---|
| package | required | Exact, case-sensitive repository package name |
| repository | cran | cran or bioconductor; one package identity per response |
| bioc_version | current release | Bioconductor numeric release, release or devel |
| package_version | none | Exact version of the selected repository source; unavailable history returns requested_version_unavailable |
| query | none | Printable optional name/topic query, 1–200 characters |
| limit | 20 | Maximum entries across all arrays, 1–50 |
| offset | 0 | Shared entity offset returned as next_offset |
| snapshot | none | SHA256 snapshot token; required for offset > 0 |
| verbosity | compact | compact or full; provenance/coverage always retained |

No argument accepts a URL, archive path, installed library path or R expression.
A package version is not a Bioconductor release or an installed R version.

## Output and verification

Schema version 1 keeps four different collections: exports, aliases,
documentation_topics, methods. Each item has a stable id, name, evidence and
callability=not_checked. A topic may document several aliases, classes, datasets
or methods. An export declaration can lack docs. An alias can lack export
evidence. An imported symbol becomes only a **possible** re-export if the same
name is explicitly exported; origin is not runtime-verified.

Coverage has separate namespace and rd statuses: verified, partial or unavailable.
Here verified means supported static source material was parsed, not that the
package loads or a symbol is callable. exportPattern is retained without
evaluating its regex or guessing runtime symbols. Unsupported/dynamic directives
and malformed material mark coverage partial. Missing NAMESPACE is unavailable;
empty NAMESPACE is a verified empty declaration set. Filename-derived topic IDs
are labelled archive_filename and partial; literal names are labelled rd_name.

Collections have total, matched, returned, source_status and page_complete.
Empty arrays mean **no entries of that kind on this page**; consult these counts
and source coverage to distinguish no matches, another page and unavailable
evidence. All arrays project one ordered entity stream; limit is not per array.
matches contains references and match types, not another independent page.
Bounded alias/topic relation lists have their own count/complete fields.

Results carry package_version, repository, resolved Bioconductor channel/category
and required R version when applicable, version_scope, archive_sha256, snapshot,
sources with actual checked_at, and source_verification_level. Archive
DESCRIPTION identity is checked; the repository index checksum is checked when
present. Cached source timestamps remain the original check/revalidation times.
R compatibility here is metadata scope, not an installation test.

## Matching

Exact exported symbols and literal aliases rank first, followed by exact topic
matches. A same-package prefix, call parentheses or case correction is labelled
normalized. Related names can be returned as fuzzy, only from the verified
source index. The fuzzy relationship is inferred and cannot prove the user's
intended API. It is never an automatic successful docs retrieval.

Exact search scans the full bounded index. Fuzzy scoring uses a deterministic
shortlist of at most 1000 entries; fuzzy_search_complete explicitly reports a
limited search. Ordering is deterministic for a fixed query/snapshot.

## Fixture-grounded example

The shared synthetic fixture in tests/data/function_discovery_cases.json declares
export(select, undocumented). The selection topic documents select and choose.

A request with package=DiscoveryPkg, repository=cran, package_version=1.0.0,
query=choose returns a documented alias choose associated with
DiscoveryPkg/man/selection.Rd. Its export_status is unknown; it is not claimed to
be an exported callable function. Requesting get_function_docs with
package=DiscoveryPkg, function=choose, package_version=1.0.0 returns that raw Rd.
These names/versions are synthetic test data, not claims about a published package.

To continue a listing, send the returned next_offset and snapshot with the same
package, version and query. The snapshot binds schema, repository, release/channel,
version, source digest and query. Source/query drift yields source_identity_drift
and requires restarting from zero; results from two snapshots are never merged.

## Completeness and diagnostics (Stage 1, KC-002)

`verification_status` is `verified` only when the enumeration is trustworthy, and the
additive `coverage.completeness` says why. Every observation is a `diagnostics` item with
a class; `issues` lists only the limiting ones.

| completeness | verification_status | Meaning |
|---|---|---|
| complete | verified | Nothing unusual was observed |
| complete_with_diagnostics | verified | Only `info` observations that cannot change the enumerated names |
| incomplete | partial | A known gap: `exportPattern()`, non-literal NAMESPACE arguments, unreadable Rd files, non-literal `\alias`/`\name` |
| unestablished | partial | Completeness cannot be determined statically: missing or conditional NAMESPACE, arbitrary calls, top-level `\Sexpr`/`\RdOpts`, `\if` bodies that contain Rd structure, unbalanced braces |

`info` observations: `useDynLib()`/`import()` options such as `.registration = TRUE` (they
cannot add exports, methods or re-export origins), conditional formatting such as
`\if{html}{...}`, and `\Sexpr`/`\eval` inside a section (R 4.5.2 was used to confirm that a
top-level `\Sexpr[results=rd]` can add an alias while a nested one cannot). Each diagnostic
carries a `count` and at most three `examples` (directive and line, or archive member).
`S3method(pkg::generic, class)` is enumerated as a method with `generic = "pkg::generic"` and
`generic_package`. A topic named `\name{\%>\%}` is a literal topic. Codes absent from the
class table in `parsers.py` default to `incomplete`, never to harmless.

## Version contract (Stage 1, KC-003)

`list_package_functions` and `get_function_docs` share one rule (`http.version_match`):
`.` and `-` are interchangeable and leading/trailing zero components are ignored, which is
R's `numeric_version ==` (so `2.10.1`, `2.10-1.0` and `2.10-01` equal `2.10-1`, while `2.1-1`
and `1.10` vs `1.1` stay different). Every successful answer carries
`requested_package_version`, the source's own `package_version`, and
`version_resolution = {requested, resolved, match, verified_for_requested_version,
version_scope}` with `match` one of `not_requested`, `identical` or `equivalent` (the latter
adds the `equivalence_rule`). The resolved spelling is never replaced by the requested one.

Only the repository's current source is available. A different version fails with
`requested_version_unavailable` and the details `requested_package_version`,
`available_package_version`, `requested_relation` (`older_than_available` /
`newer_than_available`), `reason` (`historical_versions_not_supported` /
`not_in_repository_index`), `substituted: false` and `version_scope`; no documentation or
discovery data is returned. A malformed version is `invalid_input` before any fetch. An
upstream outage keeps its own code and is never reported as a version problem.

## Documentation misses and errors

Successful get_function_docs remains literal, case-sensitive and returns its
original raw Rd/page fields. docs_not_found keeps its existing code/message and
available_aliases/closest_aliases. Additive diagnostics include requested package,
function/version, resolved version, lookup stage, sources, discovery coverage,
structured suggestions and callability. Existing failed-envelope package_version and
checked_at remain null; resolved_package_version and source_checked_at explicitly
label the new source evidence inside error. Suggestions distinguish source-backed
alias presence from export declarations; fuzzy candidates remain error recovery.

Invalid input, absent package/release, requested_version_unavailable, archive
not_found/source_unavailable, checksum_mismatch, invalid_source,
source_identity_drift and ambiguous_docs remain distinct. A docs_not_found result
is never proof that a function does not exist or a package is unsuitable.

## Python and Rust

Data-only parsers live in parsers.py; function_discovery.py owns the normalized
index, relationships, matching and paging. Namespace call scanning goes through
the existing visualization_analysis.scan_calls adapter: optional PyO3 native
scanner, otherwise Python reference, with Unicode fallback. There is no second
native downloader, cache, source verifier or export oracle. No new Rust dependency
or ABI is required. Heavy index/query work runs with asyncio.to_thread; Rust
scanner work also releases the GIL. Runtime does not require a Rust toolchain.

R_KNOWLEDGE_NATIVE=0 explicitly selects Python. Native absence/ABI mismatch falls
back to the same semantics. Actual compiled-binding and provider fixture parity
tests compare declarations, aliases, topics, methods, coverage, matching, ordering
and pages. Native-only skips do not verify parity.

Build from native/ with maturin build --release --offline and the appropriate
Python interpreter. Install the resulting local wheel with pip --no-index
--no-deps. When the venv has no pip, use an available pip's --python VENV_PYTHON
option. See architecture/function-discovery-python-rust.md and the root README.

## Resource and security bounds

No R, NAMESPACE, scripts, Rd macros, package binaries or RDS are executed/loaded.
The existing fixed-host HTTP policy, redirects/proxy rejection, timeouts, checksum
checks, tar member limits and in-memory archive reading remain in force.
Only the exact package NAMESPACE plus existing DESCRIPTION/man paths are selected.

NAMESPACE scanning is limited to 256 KiB, 4000 directives and 10000 declarations;
Rd nesting is checked to depth 128; names are limited to 160 printable characters.
Index relations are bounded, with at most 10000 entity entries/20000 alias
relations and an 8 MiB serialized index budget. Parsed cache accounting includes
the index under the existing 8 archive/48 MiB per-provider budget. No persistent
cross-repository cache is added. Cached archives are rechecked if an index checksum
changes.

Query output has a 16 KiB core page budget, a 20 KiB service cap and the existing
60 KB transport limit. Whole entity entries are paged; names and JSON are never
silently truncated. Relation sublists expose truncation/completeness explicitly.

## Controlled tool availability

FUNCTION_DISCOVERY_ENABLED=false disables only registration of the new tool.
It leaves existing tool schemas/descriptions and server instructions identical.
The default is enabled. This supports a B2 availability-only treatment; no
experiment or model call is launched by this setting.

Offline replay: benchmarks/codex_r/replay_function_discovery.py. Historical source
archives are currently missing; generated reports show excluded observations and
null historical improvement metrics. Synthetic regression recovery is kept
separate from historical measurements and AI-agent experiments.
