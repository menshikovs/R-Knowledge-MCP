# Next-stage tasks

## Version-pinned renv integration

Accept explicitly supplied lockfile data, bound its size, validate its schema and
preserve package name, Version, Repository, Source and Hash. Never follow lockfile
URLs or run restore/install. Return installed/locked and current CRAN versions as
separate fields. Support historical CRAN archives with exact-version provenance;
reject unavailable or non-CRAN sources explicitly. Test mixed repositories,
missing archives and lockfile/metadata disagreement.

## Safe Rd rendering and alias coverage

Raw Rd is the reliable first-stage output. Implement a data-only Rd AST parser
for literal aliases, escaped braces, conditional sections, encoding overrides and
safe text rendering. Do not evaluate Sexpr, custom macros, examples or package
code. Preserve raw source, version and member path. Test operators, S3/S4 aliases,
non-UTF-8 docs and ambiguous topics. Unsupported constructs must remain explicit.

## Full-text package search

Build a refreshable bounded index of CRAN DESCRIPTION titles/descriptions with
per-record provenance, atomic refresh and freshness indicators. Evaluate CRAN
metadata services with CRAN version verification; never mistake development
builds for CRAN releases. Benchmark relevance and refresh costs before adding a
runtime dependency. Current title/name keyword search is fully implemented.

## Public hosting hardening and SDK migration

Migrate deliberately from official SDK 1.x FastMCP to SDK 2 MCPServer with
transport compatibility tests. Design TLS ingress, per-client rate and body
limits, concurrency/admission control, monitoring, resource budgets and optional
MCP authorization. Review DNS/egress policy and upstream load. No deployment or
paid services are part of this version.
