# Architecture and code-quality audit

Commit `4d2266c`. Finding IDs refer to [`FINDINGS.md`](FINDINGS.md). Raw numbers: `evidence/inventory.txt`
(static `ast` pass over the 515 tracked files; nothing imported or executed).

## 1. Repository inventory (Phase A)

| Area | Files / lines | Notes |
|---|---|---|
| Production Python `src/cran_knowledge_mcp/` | 44 files / 15 902 lines | the shipped package |
| Rust/PyO3 `native/` | `lib.rs` 644 lines, `Cargo.lock` committed | optional accelerator; ABI version 3 (`native.py:11`) |
| Tests `tests/` | 67 files / 27 425 lines / 900 test functions (static) → 1 606 collected | 66 % of test functions target benchmark/telemetry code |
| Benchmarks `benchmarks/codex_r/` | 50 Python files / 31 918 lines, 100 R files, 124 knowledge-pilot files, 52 reports | **twice the size of the product** |
| Scripts `scripts/` | 4 files / 360 lines | smoke checks, prompt evaluation |
| Docs | 102 Markdown files (19 under `docs/`) | 12 relative links broken at the commit (BEN-005, DOC-001) |
| CI | `.github/workflows/tests.yml` (test×4 Pythons, docker, native×2), `upstream-smoke.yml` (nightly) | CI is red (CI-001..003) |

### Production modules (lines)

| Subsystem | Modules |
|---|---|
| MCP registration, transports, error/telemetry wrapper | `server.py` 1 758 |
| Routing, envelopes, compatibility, workflows, framework/Shiny/Quarto/visualization entry points, technology recommendation | `service.py` 2 283 |
| Repository contract and shared source logic | `providers/protocol.py` 28, `providers/base.py` 507 |
| Concrete providers | `providers/cran.py` 214, `providers/bioconductor.py` 122, `releases.py` 107, `providers/github_agents.py` 319, `providers/context7.py` 266, `providers/framework_docs.py` 150, `providers/r_documentation.py` 1 145 |
| HTTP policy, cache, singleflight | `http.py` 340 |
| Parsing (DCF, NAMESPACE, Rd, HTML) | `parsers.py` 433 |
| Function Discovery | `function_discovery.py` 327 (+ Rust `scan_calls`, `SearchIndex`) |
| Static R/Quarto/Shiny analysis | `visualization_analysis.py` 980, `project_analysis.py` 732, `technology_recommendation.py` 456 |
| Prompt Intelligence | `prompt_intelligence/` 8 modules + `composition/` 9 modules; `service.py` 1 757, `composition/*` ≈ 1 400, `templates.py` 479, `quality.py` 219, `intent.py` 270, `native_prompts.py` 182 |
| Telemetry, diagnostics, config | `telemetry.py` 279, `diagnostics.py` 32, `config.py` 120, `input_safety.py` 40, `mcp_discovery.py` 45, `errors.py` 21 |
| Release smoke | `upstream_smoke.py` 442 |

### MCP surface (verified by listing, not by documentation)

| Toolset | Tools | Resources | Templates | Prompts |
|---|---|---|---|---|
| `consolidated` (default) | **16** | 2 | 3 | 14 |
| `legacy` | **35** | 2 | 3 | 14 |
| consolidated, `FUNCTION_DISCOVERY_ENABLED=false` | 15 (removes `list_package_functions`) | 2 | not measured | 14 |
| consolidated, `PROMPT_INTELLIGENCE_ENABLED=false` | 13 (removes 3 prompt tools) | 1 | not measured | 0 |
| legacy, discovery flag false | 35 (flag is a no-op: legacy never had the tool) | 2 | not measured | 14 |

`MCP_TOOLSET=bogus` fails at startup with `KnowledgeError`. Source: `evidence/mcp/tools_*.json`, `evidence/probes/probe_flags.txt`.

## 2. Dependency map and boundaries

```
server.py ──► service.py ──► providers/{cran,bioconductor}.py ──► providers/base.py ──► http.py
   │             │                 │                                   │
   │             │                 └► releases.py                      ├► parsers.py ──(lazy)──► visualization_analysis.py   [ARCH-002]
   │             │                                                     └► function_discovery.py ──► parsers.py
   │             ├► providers/{github_agents,context7,framework_docs,r_documentation}.py
   │             ├► project_analysis.py, visualization_analysis.py, technology_recommendation.py
   │             └► prompt_intelligence/ (separate layer; calls back into service via the provider API)
   └► telemetry.py, diagnostics.py, mcp_discovery.py, config.py
errors.py is imported by 25 of 44 modules (fan-in leader); http.py by 10.
```

- **Import cycles:** none, at module top level or counting function-local imports (Tarjan SCC over all `import` nodes).
- **Highest fan-out:** `prompt_intelligence/service.py` 17, `service.py` 14, `server.py` 11 — consistent with their orchestrator roles.
- **Boundary rules in `AGENTS.md`** (registration in `server.py`; routing in `service.py`; provider behaviour in `providers/`; HTTP policy in `http.py`; data-only parsing in `parsers.py`) are *mostly* respected. Exceptions: `parsers.py` imports an analyzer (ARCH-002); `server.py` also hosts the telemetry/error wrapper (`ErrorAwareFastMCP` and helpers, lines 73-287) that exists mainly for the benchmark.
- **Independence of CranProvider and BioconductorProvider** (an `AGENTS.md` rule): satisfied. They share only `SourceRepository` (`providers/base.py`), which contains repository-neutral logic; the Bioconductor-specific parts are `releases.py` and the three-category index. Duplicate package names keep separate identities (`service.search_packages(repository="all")` returns both; `aggregate()` keeps `results` and `errors` apart).

## 3. Assessment by criterion

| Criterion | Assessment | Evidence |
|---|---|---|
| Separation of responsibilities | Good at the provider/HTTP/parser level; weak inside `service.py` | ARCH-001 |
| Cohesion / coupling | Low coupling (no cycles, narrow `errors`/`http` fan-in); low cohesion in `KnowledgeService` and `PromptIntelligence` | `evidence/inventory.txt` |
| Dependency inversion | `PackageRepository` protocol exists; `KnowledgeService.__init__` accepts injected providers/HTTP, which is what makes the 1 400-test offline suite possible. `KnowledgeService` still constructs the Bioconductor providers, GitHub/Context7/framework providers itself when not injected | `service.py:186-207` |
| Type safety | No type checker in CI (only ruff E,F,I,B,UP). Envelopes are `dict[str, Any]` end to end, which also leaves `outputSchema` empty (MCP-001). Dataclasses are used where shapes are stable (`Release`, `Artifact`, `DiscoveryIndex`) | `pyproject.toml` `[tool.ruff.lint]` |
| Async correctness | CPU-heavy parsing is correctly moved to `asyncio.to_thread` (archive parse, discovery index, search index, analyzers). Exceptions: `dcf()` for DESCRIPTION runs on the loop (SEC-001) and `yaml.safe_load` on the loop (SEC-009/PERF-001). Cancellation is safe: singleflight leader cancelled → waiter proceeds, lock registry empties, semaphore restored (`probe_conc.txt`) | `http.py:122-137` |
| Exception propagation | Uniform: `KnowledgeError(code, message, source_url, related_sources, details)` → `failure()` envelope; `bounded()` converts timeout/Unicode/recursion/internal errors to envelopes and logs only an operation id and exception type (`diagnostics.py`). `ErrorAwareFastMCP.call_tool` turns SDK validation errors into `invalid_input` | `service.py:2262-2283`, `server.py:82-141` |
| Resource lifecycle | One `httpx.AsyncClient` per process (HTTP) or per server run (stdio), `trust_env=False`, `follow_redirects=False`, 12 connections; closed by lifespan. Four download slots per repository route (`http.py:120`) | `server.py:303-309,1709-1724` |
| Shared mutable state | All in-process: HTTP TTL/LRU cache (32 artifacts / 64 MiB default), parsed-source LRU (8 entries / 48 MiB), per-provider index records, GitHub/Context7 caches (64 entries), `RepeatTracker`, a telemetry call counter. No cross-request mutation of returned dicts was found, but cached provider results are returned by reference (`github_agents.py:166-167`, `context7.py:135-136`) | — |
| Race conditions | Singleflight verified: 50 concurrent identical fetches → 1 upstream request (`probe_conc.txt`). One possible race: LRU `OrderedDict` touched from a worker thread (SEC-008) | `providers/base.py:143-148,240-252` |
| Cache consistency | `checked_at` always reflects an actual fetch or a 304 revalidation; errors are not cached except a 60-second oversized-failure marker, which is reported as `cached`. Defect: Bioconductor provider identity includes `checked_at` (PERF-001) | `http.py:139-279` |
| Configuration | All variables validated in `config.py` with explicit bounds, but errors surface when first read (e.g. `HTTP_TIMEOUT_SECONDS` at client construction), not uniformly at startup | `config.py` |
| Testability | High at unit level (MockTransport, injected service); in-memory MCP sessions used by `test_server.py`; stdio subprocess test exists | TST-001 |
| Extensibility | Adding a repository means subclassing `SourceRepository` and registering in `KnowledgeService.providers`; `service.py` still special-cases `"bioconductor"` and `"all"` in `provider()`, `enrich()`, `_dispatch()`, so a third repository (e.g. R-universe) would touch ~6 places | `service.py:209-350` |
| Maintainability | Dead code is minimal (`vulture` ≥ 60 %: 9 hits, 1 real: `parsers._gap`); no function-local import abuse (8 in the whole package). The cost is *surface area*: two generations of tools (35 + 16), a research harness twice the size of the product in the same repository, and benchmark instrumentation in the request path | ARCH-001 |

### Python/Rust boundary

`native/src/lib.rs` implements (a) an R tokenizer/call scanner used by NAMESPACE parsing and (b) the package-name search index. Measured: `cargo test` 4/4, `cargo clippy -D warnings` clean, `cargo fmt --check` clean (`evidence/ci/cargo_*.txt`); a release wheel builds in 7 s; the 108 parity/discovery/replay tests pass with the extension loaded;
on 10 real CRAN source archives the Python and Rust discovery indexes have **identical SHA-256 digests** and 5 real search queries give identical rankings (`evidence/probes/parity_*.json`). Speed: search 17–30 ms → 0.8–1.9 ms (≈ 15–20×); discovery build unchanged (6–84 ms either way) because the scan is a small part of it. The accelerator is therefore a convenience for search, not a requirement; the pure-Python path remains the reference as designed. The `native` CI job passed on the audited SHA.

## 4. Where a split would solve a demonstrated problem (and where it would not)

I do **not** recommend splitting anything merely because of line count. Each item names the concrete problem.

| # | Change | Concrete problem solved | Benefit | Migration risk | Regression surface |
|---|---|---|---|---|---|
| A1 | Move the 35 legacy entry points out of `KnowledgeService` into a `legacy_service.py` adapter that delegates to the consolidated methods | One class serves two interface generations; consolidated routing methods duplicate legacy behaviour (`get_function_docs` vs `get_versioned_function_docs`, `get_package_info`/`get_dependencies`/`get_package_vignettes` vs `get_package`); parallel paths invite the kind of drift seen in KC-003 | Legacy can be deleted when the benchmark no longer needs it; `KnowledgeService` shrinks by roughly a third | Low (pure delegation) | `tests/test_service.py`, `test_server.py`, legacy benchmark conditions |
| A2 | Extract Shiny/Quarto/Positron/visualization/technology-recommendation entry points from `KnowledgeService` into a `workspace_service.py` that shares `bounded()` | Unrelated domains (static analysis, documentation catalogue, recommendation) sit beside repository routing; this is the biggest cohesion problem | Smaller review unit for provider changes | Medium | Framework/workflow/visualization tests |
| A3 | Put the R tokenizer in a neutral module (`rlex.py`) used by both `parsers.py` and `visualization_analysis.py`; point `native.py` at it | ARCH-002 inverted dependency; the tokenizer is the Rust-accelerated piece | Restores "parsers are data-only" | Low | `tests/test_native_parity.py`, discovery/NAMESPACE tests |
| A4 | Move `ErrorAwareFastMCP`, telemetry helpers and the `RKMCP_BENCH_TELEMETRY` log line into `server_telemetry.py`, emitted only when `RKMCP_BENCH_RUN_ID`/`TRIAL_ID` are set | Benchmark instrumentation runs, and logs a ~900-byte JSON line, on every production call; it couples the product to the research harness | Cleaner production path; fewer log bytes | Low–medium (benchmark parser depends on the line) | `tests/test_telemetry_integration.py`, `test_benchmark_telemetry*.py` |
| A5 | Introduce typed envelope models (`TypedDict`/Pydantic) for the common result fields | MCP-001, and a type checker has nothing to check today | Real `outputSchema`; safer refactors | Medium (clients may start validating) | All contract tests |
| A6 | Split `PromptIntelligence` along its existing seams: context validation (`_validate_*`), grounding (`_ground_*`), assembly | 1 648-line class with 283- and 592-line methods | Reviewability; focused tests | Medium | `tests/test_prompt_intelligence.py`, `test_composable_prompts.py` |
| — | Splitting `server.py` registration | **Not recommended.** `_register_tools` (605 lines) is a flat list of declarative decorators; `AGENTS.md` mandates that registration live there; splitting would scatter tool contracts | — | — | — |
| — | Splitting `providers/r_documentation.py` (1 145 lines) | **Not recommended now.** One cohesive concern (index build/refresh/FTS5 search); it is also unaffected by any finding | — | — | — |

## 5. Code-quality observations worth keeping

- Strong: fixed-route allowlists per repository (`http.py:304-327`), bounded decompression (`parsers.py:86-121`, `http.py:48-57`), explicit `follow_redirects=False`/`trust_env=False`, no archive extraction to disk, per-response byte limits, uniform provenance (`source_url`, `checked_at`, `verification_status`, `sources`), honest failure envelopes, a deterministic snapshot token for paging (`function_discovery.snapshot_id`).
- Weak: heuristics encoded as long regex lists (`intent.py`, `quality.py`, `parsers.py` Rd checks) with no measurement of accuracy; `service.py` methods up to 485 lines (`recommend_technology_stack`).

## 6. Not reviewed in depth

`visualization_analysis.py` and `project_analysis.py` internals (only bounded timing at the 256 KiB cap: ≤ 0.4 s in the worst case tried, `probe_static.txt`), `technology_recommendation.py` logic, `upstream_smoke.py`, the 31 918 lines of benchmark Python beyond the scorer/runner paths cited in `BENCHMARK_SCIENTIFIC_AUDIT.md`, and the R launcher application under `benchmarks/codex_r/launcher/`.
