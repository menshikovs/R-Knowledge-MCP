## Summary

- **Stage 0 remediation** (`audits/2026-10-27-r-knowledge-mcp-2.0/STAGE0_REMEDIATION.md`): CI-001 (console-script `pytest` imports `benchmarks`), CI-002 (CI installs the `analytics` extra), CI-003 (bundle-backed tests skip explicitly; synthetic public fixtures cover the manifest contract), CI-004 (LF canonical byte semantics + versioned migration record), TST-002 (stale telemetry schema assertion, `environment_error` shape).
- **Context7 removal** (`CONTEXT7_REMOVAL.md`): provider, legacy tool, `context7` section, `question` parameter and `CONTEXT7_API_KEY` deleted. No replacement service.
- **CI stabilization** (`STAGE05_VERIFICATION.md`): stale launcher test double fixed, telemetry integration test builds its MCP image from the checkout, E02 Docker test guards a measured Docker Desktop mount-depth limit, new `launcher` job.
- **Real-data Rd encoding fix (KC-001):** per-file `\encoding{}` → DESCRIPTION `Encoding` → UTF-8, strict. Verified on CRAN `cluster` (`agnes`, `daisy`, `plantTraits` were `unsupported_encoding`).
- **DESCRIPTION parser performance fix (SEC-001):** linear `dcf()`; 698 000 continuation lines 80 s → 0.2 s; parsing off the event loop.
- **Benchmark evidence preservation:** no scorer, verifier, task, fixture, frozen manifest, report or saved result is modified. Legacy CRLF digests stay traceable through `benchmarks/codex_r/LINE_ENDING_MIGRATION-v1.json`.

## Verification

- **GitHub Actions run [40664343797](https://github.com/menshikovs/R-Knowledge-MCP/actions/runs/40664343797)** on `verify/stage0-ci` @ `d7db829`: all 8 jobs `success` (`test` 3.11/3.12/3.13/3.14, `native` 3.11/3.14, `docker`, `launcher`). An earlier run on the first commit (`40663724217`) failed only in `launcher` (testthat not installed); fixed in `d7db829`.
- Local (not CI), Windows 3.14 + Docker, and Ubuntu (WSL) 3.14 with R/termr: see `STAGE05_VERIFICATION.md` for counts; 0 failures on both.
- Rust/Python parity: `cargo fmt/clippy/test` pass; built extension, 108 parity + discovery tests pass.
- Wheel (49 files, no Context7, no benchmarks/tests/audits) and Docker image build; installed CLI `--help` works; stdio session (protocol 2025-11-25, 16 tools, 2 resources, 14 prompts, ping) checked.

## Compatibility (intentional API changes)

| Surface | Change |
|---|---|
| Legacy toolset | `get_context7_docs` removed: 35 → **34** tools |
| `get_package_knowledge` (legacy) | `question` parameter and `context7_docs` section removed |
| `get_package` (consolidated) | `question` removed; `include` no longer accepts `"context7"`. Consolidated stays at 16 tools |
| Unknown arguments | `get_package` and `get_package_knowledge` now advertise `additionalProperties:false` and reject stale arguments (e.g. `question`) with `invalid_input` instead of silently ignoring them. Other tools keep the SDK default |
| Config | `CONTEXT7_API_KEY` is no longer read |
| Python API | `KnowledgeService(context7_provider=…)`, `Context7Provider`, `config.context7_api_key` removed |

Schema diff against `2.0`: no other tool, parameter or annotation changed.

## Known limitations

- Private-bundle registry tests (8) skip without the git-ignored `benchmark_expansion_sources/` bundle, including in CI.
- Docker-marked telemetry/benchmark tests need locally built pinned images and skip in CI.
- Historical benchmark results are unchanged; new runs on LF checkouts record LF digests for 6 files, bridged by the migration record. The `environment_error` runner fix changes the shape of that field on the event path for new runs only.
- **CI on `2.0` has not run.** The green run is on the verification branch.
- Unknown arguments are still ignored by the other 14 consolidated tools.
- `audits/` is excluded from ruff; it contains 44 evidence scripts and some logs with local paths.

## Review checklist

- [ ] **Benchmark runner** (`benchmarks/codex_r/run_simple.py`): only `environment_failure()` extracted (behavior-preserving) and used on the event path; covered by a platform-independent test.
- [ ] **Line-ending migration:** `LINE_ENDING_MIGRATION-v1.json` entries vs `git show 4d2266c:<path>`; 12 entries flagged `mutable`; `E-source-snapshot.sha256` untouched; `.gitattributes` scope (`benchmarks/**`, `tests/data/**`).
- [ ] **Security-sensitive:** `server.py::_reject_unknown_arguments`; Rd decoding (`parsers.py`, no R/Rd macro executed); `dcf()` rewrite (equivalence tests against the old algorithm); no Context7 network path left.
- [ ] **Environment-dependent tests:** bundle skips, E02 mount-depth skip, `BENCH_PYTHON` launcher skip, telemetry integration image build; confirm none hides a regression.
- [ ] **CI:** `launcher` job fails on any skip; `pytest --collect-only` step; `.[dev,analytics]`.
- [ ] **Audit evidence:** local username path components replaced by `<user>` in 24 evidence files, 242 occurrences (only those tokens changed; digests in `SANITIZATION_RECORD-v1.json`). The earlier commit `2abac89` on the branch still contains the original text; decide whether that is acceptable or whether the branch should be recreated before merge. `.7z` archive intentionally not committed.
