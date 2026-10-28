# Testing, CI/CD and packaging audit

Commit `4d2266c`. IDs refer to [`FINDINGS.md`](FINDINGS.md). All local runs used a **clean checkout** of the audited SHA (a real `git clone`, so tracked files only) and a **fresh virtual environment** built from `pyproject.toml` (`mcp 1.30.0`, `httpx 0.28.1`, `pytest 9.1.1`, `ruff 0.17.3`); nothing from the author's working tree was used.

## 1. Actual CI status at the audited commit

`https://github.com/menshikovs/R-Knowledge-MCP/actions/runs/40513710256` (workflow `Tests`, push of `4d2266c`, 2026-10-27T13:37Z), read from the public Actions API (`evidence/ci/github_actions_run.json`):

| Job | Result |
|---|---|
| `test (3.13)` | **failure** at step "Run pytest" |
| `test (3.11)`, `test (3.12)`, `test (3.14)` | cancelled after the failure at "Run pytest" (matrix fail-fast) |
| `docker` | success (build + `--help`) |
| `native (3.11)`, `native (3.14)` | success (maturin build, `cargo fmt/check/clippy/test`, installed-extension parity tests) |

`ruff check .` and `ruff format --check .` ran before pytest and did not fail. Job logs need authentication, so the reason for the failure comes from my reproduction, which matches (§2). `upstream-smoke.yml` (nightly, default branch only) did not run for this branch.

## 2. Reproduction (CI-001, CI-002, CI-003, CI-004, TST-002)

| Environment | Command | Result |
|---|---|---|
| Ubuntu (WSL2), Python 3.14.4, `pip install -e '.[dev]'`, clone of `4d2266c` | `ruff check .` / `ruff format --check .` | pass / pass (267 files) |
| same | `pytest` (the CI command) | **Interrupted: 22 errors during collection**, all `ModuleNotFoundError: No module named 'benchmarks'` → 0 tests run (`evidence/ci/wsl_ci_bare.txt`) |
| Windows 11, Python 3.14.4 | `pytest` | 23 collection errors, same cause (`pytest_bare_collect_windows.txt`) |
| Windows 11, Python 3.14.4 | `python -m pytest --collect-only` | **1 606 tests collected** |
| Windows, Python 3.11, `[dev]` only, path fixed (`-o pythonpath="src ."`) | `pytest --collect-only` | 1 554 collected, **1 error**: `No module named 'duckdb'` (`tests/test_mcp_discovery.py:16`) |
| Ubuntu, Python 3.14.4, path fixed + `[dev,analytics]` | `pytest` | **17 failed, 1 529 passed, 60 skipped** in 378 s (`pytest_linux_fixed.txt`) |
| Windows, Python 3.14.4, clean clone, `python -m pytest` | full suite with coverage | **10 failed, 1 401 passed, 195 skipped** in 409 s (`pytest_windows_clone_cov.txt`) |
| Windows, Python 3.11 / 3.12 / 3.13, path fixed + `duckdb`,`pandas`, 10 known failures deselected | `pytest` | see §4 |

The 17 Linux failures after the two cheap fixes decompose as: **8** `test_codex_expansion_registry.py` (missing git-ignored manifest, CI-003) · **1** E02 fixture pin (line-ending dependent hash, CI-004) · **5** `test_codex_launcher.py` (need R + the `termr` package; 22 failed expectations in the R suite — environment-dependent, unattributed) · **2** `test_codex_simple.py::…[environment_failed]` and **1** `test_telemetry_integration.py::test_full_chain_with_real_mcp_container` (stale/inconsistent assertions that run only when Docker is available, TST-002). The ubuntu-latest runner has Docker but not R/`termr`, so whether the five launcher tests skip or fail there is **not established**; they are guarded by `needs_termr` and will skip only if that guard detects the missing package.

### Smallest robust correction
1. `pythonpath = ["src", "."]` (CI-001) — one line; verified to restore collection.
2. `pip install -e '.[dev,analytics]'` or `importorskip("duckdb")` (CI-002).
3. `skipif` on the absent manifest, or commit it (CI-003).
4. `.gitattributes` + re-pin (CI-004); update the two stale assertions (TST-002).
Even with 1–2 only, the Linux run still fails 17 tests; the job turns green only with all four.

## 3. What the suite is and is not

| Measure | Value |
|---|---|
| Test files / lines | 67 / 27 425 |
| Test functions (static) / collected items | 900 / 1 606 (parametrised) |
| Share of test functions for benchmark/telemetry/harness code | **597 of 900 (66 %)** |
| Production code lines | 15 902 (benchmark code 31 918) |
| Skips | ≈ 60 (Linux) – 195 (Windows): Docker image/engine, R/`termr`, WSL, native module |
| Assert-free tests | 2 (`test_structured_context_is_bounded_and_validated`, `test_prompt_input_and_release_validation_are_bounded_and_explicit`: they rely on `pytest.raises` blocks, which my detector did not count — not defects) |
| Property-based tests | none (`hypothesis` absent) |
| Docker-marked tests | 15; excluded only if `-m 'not docker'` is passed |
| **Measured coverage** (line + branch, `src/cran_knowledge_mcp`, Windows, `python -m pytest`) | **84 %** total: 6 419 statements, 829 missed, 2 752 branches, 496 partial (`coverage_report.txt`). Excludes the native extension, subprocess-spawned stdio/HTTP servers and the benchmark code |
| Lowest-covered production modules | `upstream_smoke.py` 66 %, `native.py` 68 %, `composition/context.py` 74 %, `github_agents.py` 78 %, `service.py` 79 %, `visualization_analysis.py` 79 %, `prompt_intelligence/service.py` 81 %, `server.py` 82 % |

### Do the tests execute meaningful assertions, or do mocks hide integration failures?
- **Meaningful:** the unit tests I sampled assert specific values and error codes (for example the MCP error tests check `isError`, `error.code` and the envelope). Coverage of `http.py` (95 %), `providers/base.py` (93 %), `parsers.py` (90 %), `function_discovery.py` (90 %) is high, and `r01a_offline_guard` blocks sockets and subprocesses so the offline claim is enforced, not assumed. The singleflight/cancellation behaviour I probed is correct; the existing tests cover redirects, caching, 429/5xx handling and size limits.
- **Hidden by mocks:** every provider test uses synthetic archives named `ExamplePkg`; none uses a real CRAN archive. Consequently two real defects that only appear on real data were invisible: KC-001 (mixed-encoding Rd in `cluster`) and KC-002 (`useDynLib(.registration=TRUE)` and roxygen `\if{html}` marking real packages "partial"). Both were found within minutes with real tarballs. The nightly `upstream-smoke.yml` checks reachability of official sources, not parser behaviour on real packages, and runs only on the default branch.
- **Tests that test the harness:** two-thirds of the suite verifies the benchmark runner, telemetry, analytics and launcher. That is defensible while the benchmark is the project's main activity, but the product contract (tools, schemas, provider semantics) gets the minority of tests and none on real fixtures.

### Gaps by type
| Type | Gap |
|---|---|
| Unit/boundary | boundary tests for version spellings (KC-003), encodings (KC-001), `useDynLib`/macros (KC-002), pathological DESCRIPTION (SEC-001) |
| Integration | no recorded real-archive suite (1.3 in `ROADMAP.md`); stdio is tested by one subprocess test; Streamable-HTTP is tested in-process, not as a real listener under concurrent load |
| Property-based | `version_parts`, `dcf`, `aliases`, snapshot paging, NAMESPACE round-trips are natural Hypothesis targets |
| Async/concurrency | singleflight and cancellation are tested; LRU-under-threads (SEC-008) is not; no multi-client HTTP test |
| MCP protocol | in-memory sessions and one stdio subprocess; no conformance suite against the spec matrix (`MCP_PROTOCOL_AUDIT.md` §3); no schema-conformance test (MCP-001) |
| Packaging | CI builds a wheel and runs `r-knowledge-mcp --help` (good); no test that the wheel contains data files/entry points beyond `--help`; no `twine check`/metadata check |
| Rust parity | present and strong (`test_native_parity.py`, 108 parity/discovery/replay tests pass with the module; CI `native` job green); only ABI/semantic parity, no fuzzing |
| Regression | the benchmark reports record regressions carefully; the product has no regression corpus of "agent asked X, server answered Y" |
| Isolation | Windows temp-directory workarounds in `tests/conftest.py` (inherited-ACL temp factory) show real friction; tests that need Docker/R are marked, but two depend on host state without skipping (TST-002) |
| CI reproducibility | dependencies unpinned (range pins only), base image unpinned, actions pinned by tag; CI install command differs from what the tests need (CI-002) |

## 4. Python versions (advertised: 3.11–3.14)

| Version | Evidence |
|---|---|
| 3.14.4 | full runs on Windows and Ubuntu (§2); `ruff`, `native`, `docker` on CI |
| 3.11 / 3.12 / 3.13 | `ruff` target `py311` passes (syntax compatible); collection verified on 3.11 (1 554 collected; 1 duckdb error). Full runs with the path fix, `duckdb`+`pandas`, and the 10 known failures deselected: **3.11: 1 failed, 1 367 passed, 198 skipped** (the one failure is `test_benchmark_analytics.py::test_p2_trace_and_opportunity_import_…`, `ModuleNotFoundError: streamlit` — I had not installed the `streamlit` part of the `analytics` extra, so this is an installation artefact that again shows tests need the full extra); **3.12 and 3.13: identical outcome** — 1 failed (the same `streamlit` installation artefact), 1 367 passed, 198 skipped, 40 deselected (`pytest_py3.12.txt`, `pytest_py3.13.txt`) |
| Native extension | built from `native/` (7 s) for Python 3.14 via `abi3-py311`; CI also builds on 3.11 (green) |

## 5. Docker, packaging and the installed CLI

- `docker build` of the repository `Dockerfile` succeeds in 13 s (cached base), image 257 MB, user uid 10001, `ENTRYPOINT r-knowledge-mcp`, `CMD --transport streamable-http --host 0.0.0.0`, no HEALTHCHECK. Runs with `--read-only --cap-drop=ALL --security-opt=no-new-privileges`. `--help` works. A container request with the docker-network Host name is refused (421) until `--allowed-host` is passed — documented (`README.md:392`).
- The wheel installs both console scripts (`r-knowledge-mcp`, `cran-knowledge-mcp`); the stdio session via the installed script passed the protocol matrix (`MCP_PROTOCOL_AUDIT.md`).
- `pyproject.toml` version is `0.1.0` for a "2.0" branch; no tags, `CHANGELOG`, `SECURITY.md` or release workflow (DOC-001, Stage 5.4). `[project.scripts]` has no entry for the R-manual refresh command (AGT-002).
- Rust: `cargo test` 4/4, `cargo clippy --release -- -D warnings` clean, `cargo fmt --check` clean (`evidence/ci/cargo_*.txt`); `Cargo.lock` committed; no `unsafe` in `lib.rs`.

## 6. Limits of this audit
Windows and WSL Ubuntu on one machine; no macOS; GitHub job logs not readable (auth); full runs on Python 3.11–3.13 are Windows-only; the five R-dependent launcher tests were not attributed; no mutation testing was done, so the strength of assertions is judged by sampling, not measured.
