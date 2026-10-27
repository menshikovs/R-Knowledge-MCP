# Function discovery: Python/Rust architecture decision

Status: implementation decision, 2026-10-26. Local sources are authoritative.

## Inspected architecture

The repository has one optional Rust cdylib in native/src/lib.rs, not a Cargo workspace. Cargo depends only on PyO3 0.30 (abi3-py311). native/pyproject.toml builds cran_knowledge_native with maturin and extension-module; the main setuptools Python package does not require Rust. src/cran_knowledge_mcp/native.py selects the extension automatically when ABI_VERSION=3 matches; R_KNOWLEDGE_NATIVE=0 disables it. Import/ABI failure falls back to Python. Existing native bindings are synchronous scan_calls and SearchIndex; CPU work releases the GIL with py.detach. scan_calls returns None for unsupported Unicode code classes so the Python reference can handle them. Syntax failures use ValueError(code,message), converted to KnowledgeError in the Python adapter. Native code does not download, validate or cache package archives, parse Rd, resolve releases, register MCP tools, or own source provenance. Only Python owns these policies. At the inspection baseline CI tested the Python fallback; tests/test_native_parity.py skipped if native was absent. P1-B adds a Linux CI job that builds the real wheel, asserts the extension loaded, runs Cargo checks and executes shared parity fixtures on CPython 3.11/3.14. Published platform guarantees are CPython >=3.11 where an appropriate abi3 wheel/toolchain exists; no claim of universal wheel availability.

## Existing call paths

server.py -> KnowledgeService -> CranProvider/BioconductorProvider -> SourceRepository.source -> RepositoryHTTP -> in-memory source_files -> DESCRIPTION verification. SourceRepository builds a literal alias-to-Rd-member cache. HTTP performs fixed-host routing, limits, checksum/version validation and bounded process-local caching. Bioconductor is scoped by config.yaml release/R mapping. get_function_docs returns raw Rd pages; search_r_documentation separately searches six local general R manuals. Python owns deadlines, errors and output limits. PackageSearchIndex delegates ranking to Rust when available. visualization_analysis.scan_calls delegates R lexical call scanning to Rust and falls back on Unicode; its wrapper validates a 256 KiB source bound.

The existing source analyzers already offload analysis through KnowledgeService._visualization_analysis -> asyncio.to_thread. Existing package-search ranking invokes a synchronous native binding on its async provider path; releasing the GIL alone does not make that call asynchronous. The new discovery construction, digest and query path is explicitly offloaded. SearchIndex is specialized for package-name/title AND-term ranking, so it is not reused as an alias/topic/export resolver.

## Decision before implementation

Use a common Python semantic layer for discovery, reusing the existing scan_calls adapter for conservative NAMESPACE call scanning. This uses native acceleration through the existing PyO3 boundary without duplicating export/alias verification rules or introducing another Rust parser. Python tokenize_r validates literal directive arguments and whole top-level statement spans, including conservative bare-symbol grammar; only unconditional isolated supported declarations become claims. Rd literal aliases reuse parsers.aliases. The normalized index, matching, pagination and verification semantics are identical in both backend modes. No new binding, dependency, native network stack or ABI change is necessary. Rust tests cover the reused scanner on namespace inputs; shared Python provider/semantic fixtures run with both scanner adapters and test actual bindings when installed.

## Responsibilities and contract

Python: MCP registration, schema, repository routing, HTTP/security policy, archive validation, DESCRIPTION/NAMESPACE/Rd material selection, static export/alias/topic/method association, deterministic ranking and pagination, snapshot identity, cache and error normalization. Heavy source parsing/index construction/query run via asyncio.to_thread; archive/index cache follows existing per-provider size/identity boundaries.

Rust: existing bounded-input call scanning and package search acceleration. No native claim is independently labelled verified. The discovery path calls scan_calls using its existing automatic selection/fallback. Native absence never lowers semantic coverage or changes output claims.

Shared representation separates explicit namespace exports, unresolved export patterns, imported/re-export declarations, S3/S4 methods, documentation topics and literal aliases. All callability is not_checked. Dynamic directives, unsupported escapes/macros and malformed sections produce partial/unknown status, never inferred exports. Fuzzy ranking cannot create new names or relationships. Discovery pages have one ordered union of entity keys; all collection arrays are projections of that same page, with explicit totals/counts/completeness. Continuations require a source/query snapshot token and exact package identity.

## Limits and tradeoffs

NAMESPACE is statically inspected, never evaluated. exportPattern is preserved as an unresolved declaration rather than expanded against guessed runtime symbols. importFrom plus explicit export is only a possible re-export, not proven runtime origin. Rd macros are never expanded; literal topic/alias coverage is explicitly reported. No RDS parser or installed R session is introduced. No current/historical version substitution is allowed. A content digest pins pages and invalidates stale snapshots even if the published version remains unchanged. The common semantic layer deliberately adds Python work; using the already tested Rust scanner avoids a second source of truth and keeps the optional extension contract.

## Build and validation

Native: cd native; maturin build --release --offline -i ../.venv/Scripts/python.exe (Windows) or ../.venv-wsl/bin/python (WSL); install the resulting local wheel with pip --no-deps --force-reinstall. Run cargo fmt --check, cargo check --offline, cargo clippy --offline --release -- -D warnings, cargo test --offline. Then run shared discovery and existing native parity tests through the same Python interpreter, once with R_KNOWLEDGE_NATIVE=0 and once automatic. Cargo tests alone do not prove bindings/parity. Exact commands/results and any environment limitations are recorded in the implementation verification report.
