# Next-stage tasks

## MCP SDK 2 and protocol revision support

The server currently uses the maintained SDK 1.x FastMCP API. Port to SDK 2's
MCPServer API in a separately reviewed change, keep Streamable HTTP and stdio
working, and exercise standard Prompts with both supported legacy clients and
2026-07-28 clients. Do not advertise a newer protocol revision until tests
confirm negotiation and transport behavior.

## Prompt evaluation and optional enhancement

Create a curated, versioned dataset for R package development, Shiny, Quarto,
Bioconductor release compatibility, visualization, tidyr and debugging. Use
isolated workspaces for coding-agent checks. Evaluate Promptfoo as an optional
development tool using deterministic assertions first and opt-in model graders
only under an explicit data-transmission and cost policy. Any external prompt
enhancer needs an explicit adapter, user consent, redaction policy, endpoint/key
handling, rate limits, provenance and adversarial-output tests. Do not configure
one by default.

## Version-pinned renv integration

Accept explicitly supplied lockfile data, bound its size, validate its schema and
preserve package name, Version, Repository, Source and Hash. Never follow lockfile
URLs or run restore/install. Return installed/locked and repository versions as
separate fields. Preserve Bioconductor release/category and use the dynamic R
mapping. Support historical CRAN archives with exact-version provenance;
reject unavailable or unsupported sources explicitly. Test mixed repositories,
missing archives and lockfile/metadata disagreement.

## Safe Rd rendering and alias coverage

Raw Rd is the reliable first-stage output. Implement a data-only Rd AST parser
for literal aliases, escaped braces, conditional sections, encoding overrides and
safe text rendering. Do not evaluate Sexpr, custom macros, examples or package
code. Preserve raw source, version and member path. Test operators, S3/S4 aliases,
non-UTF-8 docs and ambiguous topics. Unsupported constructs must remain explicit.

## Full-text package search

Build a refreshable bounded index of CRAN/Bioconductor DESCRIPTION titles/descriptions with
per-record provenance, atomic refresh and freshness indicators. Evaluate CRAN
metadata services with CRAN version verification; never mistake development
builds for releases or merge Bioconductor channels. Benchmark refresh costs before adding a
runtime dependency. Current name/available-title keyword search is implemented.

## Reproducible dependency environments

Current compatibility checks direct metadata constraints against the selected
Bioconductor release and current CRAN. Add explicitly versioned historical CRAN
snapshots and an independently tested transitive solver before making stronger
installation claims. Preserve unknown/ambiguous outcomes, platform constraints
and source provenance. Never run package code to inspect compatibility.

## Public hosting hardening and SDK migration

Migrate deliberately from official SDK 1.x FastMCP to SDK 2 MCPServer with
transport compatibility tests. Design TLS ingress, per-client rate and body
limits, concurrency/admission control, monitoring, resource budgets and optional
MCP authorization. Review DNS/egress policy and upstream load. No deployment or
paid services are part of this version.

## R framework intelligence follow-ups

The Shiny analyzer is heuristic and does not parse complete R syntax or
reconstruct the runtime reactive graph. A future parser could add source
locations, module-aware namespacing and testthat/shinytest2 suggestions without
running apps. Quarto analysis checks supplied YAML and chunk options only;
consider versioned Quarto schema validation and bibliography-key checking when
bibliography text is explicitly supplied. Framework docs target current official
pages; historical Shiny, Quarto and Positron docs need validated versioned
catalogs before tools can claim version-specific guidance.

Positron support is MCP configuration guidance and safe metadata analysis. An
IDE extension or live-session adapter should be separate work after evaluating
the official APIs and permission model; this server does not control the IDE.
