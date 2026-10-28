# Performance and scalability audit

Commit `4d2266c`. IDs refer to [`FINDINGS.md`](FINDINGS.md). **Measured** values are labelled as such and come from `evidence/probes/*.txt`; **estimated** values are analytic.
Environment: Windows 11 (10.0.26100), CPython 3.14.4, pure-Python path unless stated; one process; no concurrency beyond what is stated. These are deterministic local micro-measurements,
not load tests; absolute numbers will differ on other hardware, ratios are the useful part. No high-volume traffic was sent to public services.

## 1. Measured results

| Operation | Input | Result (median of 3–5 unless noted) |
|---|---|---|
| Parse CRAN `PACKAGES` (DCF → dict) | real, 7.4 MB expanded, 25 529 records | **99 ms** (`probe_perf`) |
| Build name/title search index | 25 529 entries | Python **41–44 ms**; Rust **22 ms** (`probe_parity`) |
| Package search query | 25 529 entries | Python **17–31 ms** ("a": 17, "ggplot": 30, "time series forecasting": 31); Rust **0.8–1.9 ms** (≈ 15–20×); identical rankings |
| Expand and filter an archive (`source_files`) | synthetic 500 Rd / 1.05 MB; 1 800 Rd / 3.8 MB | **9 ms**; **29 ms** |
| Build discovery index | 10 real archives (MASS … rpart) | **7–84 ms** each, identical with or without Rust (the Rust scan is a small share) |
| Build discovery index | synthetic 1 800 Rd / 9 000 entries via the service (cold, includes fetch from a mock) | **453 ms** cold, **13 ms** warm query |
| Discovery page | 9 000-entry index | no query **4.7 ms**; fuzzy query **15 ms** |
| 40 concurrent `get_function_docs` for one cached archive | synthetic | **106 ms** total, 40/40 ok (an event-loop heartbeat showed one gap of ≈ 106 ms, i.e. the batch is effectively serialised on the loop for the Rd decoding step; inconclusive about cause) |
| Singleflight | 50 identical concurrent `fetch()` | **1** upstream request, one shared artifact; lock registry empty afterwards; leader cancellation does not strand waiters; semaphore restored (`probe_conc`) |
| Real end-to-end, warm index | seeded sample of 30 CRAN packages: discovery page + first docs lookup, including the tarball download | median **0.1 s**, max **0.5 s** (`evidence/real_cran_sample.json`) |
| Discovery paging, real | `Matrix` (3 000+ entities) | 89 pages, 0.45 s total |
| Bioconductor `config.yaml` parse | real, 12.9 KB | **12.2 ms per call**, repeated on every Bioconductor tool call (PERF-001) |
| Bioconductor 3-category index parse | real 3.23, 3 747 records | **17 ms**, repeated when the provider is rebuilt (PERF-001) |
| Hostile archive peak memory | ≈ 1 MB gzip expanding to 105 MB / 133 MB | peak working set **134 MB / 164 MB** from a 19 MB baseline (`probe_rss_hostile_archive`) |
| Algorithmic worst case | 2 MiB DESCRIPTION, 698 000 continuation lines | **≈ 57 s**, on the event loop (SEC-001) |
| Static analyzers at 256 KiB | ggplot/tidyr/knitr analyzers on 9 adversarial shapes | **≤ 0.4 s**, in worker threads |
| Prompt composition output (offline evaluator, 20 scenarios) | `scripts/evaluate_prompt_output.py` | concise median 1 340 characters (max 5 708), standard 3 300 (max 7 542), comprehensive 3 675 (max 7 862) ≈ 335–920 tokens by the byte/4 estimate (`evidence/benchmark/prompt_eval.json`) |
| Analytics rebuild | 30 saved runs / 91 trials / 20 MB → DuckDB | **10.9 s**, 21 tables, 13 MB database; dashboard/query latency **not measured** |

## 2. Context-window cost (what an agent pays for the information)

Server-measured serialized result sizes from the frozen D01 runs (`evidence/benchmark/response_sizes.txt`, derived from `baseline_tool_calls.csv` and the P1-E timeline):

| Tool | n | median | max |
|---|---|---|---|
| `get_function_docs` (success) | 23 + 12 | 4.9 KB / 6.1 KB | 19.8 KB |
| `get_function_docs` (error: `docs_not_found`, `requested_version_unavailable`) | 26 + 5 | 1.8 KB / 2.2 KB | 4.6 KB |
| `get_package` | 7 + 2 | 8.9 KB / 5.8 KB | 12.3 KB |
| `list_package_functions` | 9 | 7.9 KB | **40.8 KB** |

One discovery-enabled D01 trial (P1-E, 28 calls) returned 241 KB in total. By the repository's own `bytes/4` estimate that is ≈ 60 k tokens; because each result is sent twice (`content` + `structuredContent`, MCP-003) a text-only client puts roughly half of that, ≈ 27 k tokens, into the model's context — still about the benchmark's whole 30 000-token task budget. The 40.8 KB `list_package_functions` maximum is consistent with the tool's own 20 KiB guard (`service.py:452`) once the ≈ 2.2× duplication in the recorded size is taken into account (≈ 18.5 KB per copy). Output shaping (compact mode, page caps, truncation notices) exists and works; the duplication and the repeated `sources` blocks are the main avoidable cost.

## 3. Complexity and design review

| Path | Time | Memory | Notes |
|---|---|---|---|
| CRAN index parse | O(n) in index size | whole expanded index + record dicts (≈ tens of MB for 25 k records) | to_thread; ≤ 64 MiB expanded cap |
| Package search | O(N·T) per query (N = 25.5 k entries, T terms) in Python; same in Rust, 15–20× faster | index kept per provider | no inverted index; fine at this N |
| Archive load | O(archive) | `bytearray` + `bytes(chunks)` copy during download (2× up to 25 MB), 128 MiB expansion buffer, retained parsed files ≤ 48 MiB LRU (8 entries) | 4 download slots per route; archive expansion serialised per provider by `_parse_lock` |
| Discovery build | O(R·L + E log E) for R Rd files of length L, E entries | ≤ 8 MiB estimated index, entries ≤ 10 000 | serialised per provider by `_discovery_lock` (also across different packages) |
| Discovery page | O(E) for ranking + O(limit × page) because each appended entry re-serialises the output to check the 16 KiB cap | page ≤ 16 KiB | fuzzy shortlist capped at 1 000 candidates (`fuzzy_search_complete=false` beyond) |
| `get_function_docs` | O(archive) first time, then O(alias index) | alias index cached per archive | `ambiguous`/miss path builds the discovery index for suggestions |
| `dcf()` | **O(n²)** worst case | O(n) | SEC-001 |
| `search_packages(repository="all")` | CRAN then Bioconductor *sequentially* (offset accounting needs the CRAN total) | — | latency is the sum; a cold Bioconductor release adds three index fetches |
| Cache eviction | LRU by bytes and count (32 artifacts / 64 MiB default) | — | an agent touching > 32 distinct archives within the 5-minute TTL re-downloads; revalidation with `ETag`/`Last-Modified` exists, so a refresh is usually a 304 |

Blocking operations inside async paths: `dcf()` for DESCRIPTION (SEC-001), `yaml.safe_load` of `config.yaml` (PERF-001, 12 ms), Rd decoding of matched documents, and result compaction/`json.dumps` for 60 KB results. Everything else heavy is in `asyncio.to_thread`. Because CPython's GIL still serialises pure-Python parsing, to_thread keeps the loop *responsive* but does not add throughput.

Singleflight and the semaphore (4 per repository route) behave correctly under cancellation (§1). Locks: `_cache_lock` is held only around dict updates; the per-path lock is held across the network call, so unrelated routes do not contend.

## 4. Scalability assessment

- **Single local user (stdio):** adequate. Cold calls are dominated by one download; warm calls by 5–15 ms of parsing; nothing measured approaches a second except the hostile-input cases.
- **Shared HTTP deployment:** one process, one event loop, GIL-bound parsing, no per-client limits. Realistic risks are SEC-001 (a single request can stall everyone for a minute), cold-start herds (singleflight handles identical routes, not distinct packages: up to 4 concurrent downloads/route, then queueing behind `_parse_lock`), and the 64 MiB cache sizing for many distinct packages. Throughput under real concurrent load was **not measured**.
- **Native accelerator:** worth having for search only; it does not change discovery build time and is not needed for correctness.

## 5. Recommended changes (ordered by measured benefit)

1. Fix `dcf()` (SEC-001): removes the only multi-second stall.
2. Report model-visible bytes and stop duplicating the payload where a client does not need it (MCP-003); drop repeated `sources` from compact `list_package_functions` pages: largest *context* saving, no latency change.
3. Memoise `releases.catalog()` by artifact identity and compare `Release` by value (PERF-001): −12 ms per Bioconductor call, no cache loss on refresh.
4. Only if a shared deployment is planned: per-client concurrency limits and a load test with N concurrent distinct-package requests; consider a process pool for archive expansion.
