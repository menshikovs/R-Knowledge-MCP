# Stage 0.5 — CI verification and release gate

Branch `2.0`, HEAD `4d2266c` plus the uncommitted working tree (nothing committed, pushed or merged by this stage).
Raw outputs: `stage05-evidence/`. Scope: verify Stage 0 (`STAGE0_REMEDIATION.md`) and the Context7 removal
(`CONTEXT7_REMOVAL.md`); no KC-002/KC-003, new tools or benchmark redesign.

## Status: STAGE 0 VERIFIED — CI PASSED ON VERIFICATION BRANCH

CI passed on the verification branch `verify/stage0-ci`, **not on `2.0`**: `2.0` has not run these changes.
The sections below were written before the push and are kept as the historical local record; §9 records the
GitHub result. Original local-only status at that time: *STAGE 0 VERIFIED WITH DOCUMENTED LIMITATIONS* (CI not run).

## 1. Reviewed changes

Reviewed the full working-tree diff (32 modified/deleted tracked files + 6 new, excluding `audits/`).

| Area | Result |
|---|---|
| `run_simple.py` (6 lines) | Only change under frozen benchmark paths (`git diff HEAD --stat -- benchmarks tests/data`, before this stage's launcher edits). Event path now reuses the reviewed-code helper; no scorer/verifier touched |
| `pyproject.toml` | `pythonpath = ["src", "."]`, `audits` ruff exclude, description text. Exclusion is a directory of audit evidence scripts, not product code |
| `.gitattributes` | LF for `benchmarks/**` and `tests/data/**` only |
| CI workflow | `.[dev,analytics]`, collection step; **this stage adds a `launcher` job** (§3) |
| Context7 removal | Complete in code; remaining mentions are the regression tests, "removed" notes in README/AGENTS/ARCHITECTURE, and frozen historical benchmark files. Built Docker image and wheel contain no `providers.context7` module |
| Test diffs | No weakened assertions found. Context7 tests were removed with the feature (replaced by `test_context7_tool_and_section_are_removed_and_never_contacted`); pin checks now use `pin_matches` (accepts exactly the canonical or legacy digest). Skips added: 8 bundle-backed registry tests (explicit reason, §4) |
| Public API | Intentional: `get_context7_docs` removed (35→34 legacy tools), `question`/`context7` removed from `get_package` and `get_package_knowledge`, consolidated tool count unchanged at 16. No other API change found |

## 2. Findings

### Fixed in this stage

| # | Finding | Classification | Fix |
|---|---|---|---|
| F1 | A stale `question` argument was **silently ignored** by `get_package` / `get_package_knowledge` (FastMCP drops unknown args). Reproduced on both toolsets | Production defect (Context7 removal side effect) | `server.py`: `_reject_unknown_arguments` sets `extra="forbid"` and `additionalProperties:false` for these two tools only. Stale clients get `invalid_input`. Test: `test_removed_question_parameter_is_rejected_not_ignored` (both toolsets). Docs: `docs/ARCHITECTURE.md`, `CONTEXT7_REMOVAL.md` corrected |
| F2 | 5 launcher tests (22 failed + 5 errored R expectations) | **Test isolation defect**, not R/termr or platform. The launcher passes `--function-discovery enabled`; `tests/fake_runner.py` argparse did not know it, so every fake run exited 2. Two R expectations (`test-b1.R:24`, `test-core.R:54`) were also stale and contradicted `test-core.R:72` | `fake_runner.py` accepts the flag; both expected vectors updated. `test-core.R` flagged `mutable` in the migration record (its CRLF digest described the baseline only) |
| F3 | Last launcher test needed the author's private `.venv-wsl` | Private-local-file dependency | Skip now honours `BENCH_PYTHON` (which `run.R` already supports). New CI job sets it |
| F4 | `test_full_chain_with_real_mcp_container` | **Test isolation + three stale-test defects**: (a) hard-coded hand-built image `cran-knowledge-mcp:shiny-quarto`, which has no `telemetry.py` (verified by listing the image's modules); (b) `client_done` filter counted the runner's schema-valid `agent.tool.started` events (the `is_error` KeyError); (c) the "no arguments in results.json" check ignored the deliberate `discovery_request_projection` that copies validated package/function/version names | (a) module fixture builds the image from the checkout (`cran-knowledge-mcp:telemetry-test`, passed via `--mcp-image`); skip now covers only the two heavy images CI cannot build; (b) filter is `schema.TOOL_TERMINAL`; (c) the check still covers every other field, `telemetry.jsonl` and both CSVs, and excludes only that documented key |
| F5 | `test_e02_reproduction…` (Docker, Windows) fails from some checkouts | **Genuine platform incompatibility**, now measured: Docker Desktop fails with `Input/output error` when bind-mounting any file whose host path has more than 16 components after the drive (16 mounts, 17 fails; synthetic probe, 14–23 levels). Not path length, not content. Not a production defect | Explicit, evidence-based skip only when the checkout is deeper than that limit, with the measured reason. Passes from the normal checkout (28 s) |

### Verified without change
- CI-001..004, KC-001, SEC-001 fixes hold (suite results below).
- `environment_error` runner fix: covered by `test_codex_simple.py::test_trial_deletes_session_and_executor_before_scoring[environment_failed]`. **Coverage limitation:** that test is Linux-only (`SIGALRM`). Mutation check on Windows (revert the fix, rerun) still passes, because the test is skipped there. It runs in the Linux CI matrix and in the WSL run below.

### Unresolved (documented, not fixed)
- U1. Unknown arguments are still silently ignored by the other 14 consolidated tools (SDK default). Out of scope; changing it globally would alter the benchmarked surface.
- U2. The `invalid_input` message for rejected arguments is the generic "Tool arguments failed validation" (existing behaviour); it does not name the offending argument.
- U3. The author's `.venv` holds a **stale non-editable install** of `cran_knowledge_mcp` that still contains Context7. Pytest is unaffected (`pythonpath` puts `src` first) but any direct `.venv\Scripts\python` import uses the old code. Reinstall with `pip install -e .`.
- U4. 8 registry tests need the git-ignored private bundle and never run in CI.
- U5. Docker-marked telemetry/benchmark tests need locally built pinned images (`rkmcp-codex-runtime`, `codex-r-benchmark:pilot`); they skip in CI by design.
- U6. For the one `mixed`-line-ending entry (`benchmarks/codex_r/.gitignore`) the record's legacy digest is the CRLF-normalised form, not the file's actual mixed bytes. No historical result or pin references it.

## 3. CI readiness

| Check | Result |
|---|---|
| All tests collect | 1 650 collected, 0 errors (console-script `pytest`), Windows 3.14 and Ubuntu 3.14, and on 3.11/3.12/3.13/3.14 |
| `.[dev,analytics]` installs | Python 3.11.17, 3.12.15, 3.13.5, 3.14.4 (uv, Windows) and Ubuntu 3.14.4 (pip) |
| No private local files | Verified from clean copies of tracked + unignored files (no `.venv*`, no bundle). Remaining private-file dependencies are the explicit skips in §4 |
| ruff check / format | pass / pass (269 files) on all four Pythons and Ubuntu |
| Rust/Python parity | `cargo fmt --check`, `clippy -D warnings`, `cargo test` pass; maturin wheel built and installed: `test_native_parity` + discovery suites **108 passed** |
| Wheel | Builds; 49 files, none named context7; installed in a clean 3.11 venv, `r-knowledge-mcp --help` works |
| Docker | `docker build` succeeds; `--help` works; `providers.context7` absent; 16 consolidated / 34 legacy tools |
| Workflow change | New `launcher` job: installs R (`r-lib/actions/setup-r@v2`), `termr` (on CRAN, 1.0.1) and `testthat`, sets `BENCH_PYTHON`, **fails if any launcher test is skipped**. Local equivalent: 20 passed, 0 skipped on Ubuntu. **The job itself has not run on GitHub** |

## 4. Test results by platform

| Platform | Result |
|---|---|
| Windows 11, Python 3.14.4, author's tree, Docker engine running | **1 507 passed, 143 skipped, 0 failed** (9 min). Before this stage's fixes: 1 498 passed, 150 skipped, 0 failed |
| Ubuntu (WSL2), Python 3.14.4, copy of tracked+unignored files, committed scratch repo, R 4.5.2 + termr + testthat, Docker, `BENCH_PYTHON` set | **1 583 passed, 67 skipped, 0 failed** (8 min). Before fixes: 8 failed (5 launcher, 2 telemetry integration, 1 caused by my scratch copy lacking a git repo, not by the code) |
| Python 3.11 / 3.12 / 3.13 / 3.14 (Windows, uv) | Install, ruff, full collection, and a 128-test subset (server, consolidated server, mcp errors, stage0 regressions, line endings, parsers, service, native parity): 104 passed, 24 skipped on each. **Full suites were not rerun on 3.11–3.13 this stage** (Stage 0 did: 1 444 passed on each from a clean clone) |
| GitHub Actions | **Not run** |

Test count check: 1 507 + 143 = 1 583 + 67 = 1 650.

## 5. Skip analysis

No skip is unconditional or for convenience; each names a prerequisite.

**Windows (143):** POSIX/Linux-only semantics (signals, PTY, `SIGALRM`, ACLs, symlink/mode/file-replacement, private durable-evidence storage): 127; Windows sandbox limits (symlink privilege, child-process creation): 2; telemetry integration tests that require Linux with a Docker CLI: 6; `R_KNOWLEDGE_*_IMAGE_ID` opt-ins for pinned-image integration: 7; BENCH_PYTHON/`.venv-wsl` not available: 1.
**Ubuntu (67):** PyO3 extension not installed in that venv: 43 (covered by the separate `native` job and the Windows parity run in §3); 8 private-bundle registry tests; saved historical result directories absent from a clone: 9; `R_KNOWLEDGE_*_IMAGE_ID` opt-ins and pinned Codex/R images: 7.

Skips added or changed by Stage 0/0.5: bundle-backed registry tests (private data, cannot be published), E02 mount-depth guard (measured platform limit), BENCH_PYTHON-aware launcher skip. Skips on Windows for R/termr launcher tests were not added; they pre-existed (`sys.platform != "linux"`).

## 6. Benchmark integrity

Checked independently of the repo's own helper, from `git show 4d2266c:<path>` blobs:
- 117 record entries; 106 non-mutable entries: canonical digest = SHA-256(LF(blob)) for **106/106**; legacy digest = SHA-256(CRLF(LF(blob))) for **106/106** (105/106 also equal the digest of the actual CRLF working-tree bytes; the exception is the mixed `.gitignore`, U6).
- 12 entries are `mutable` (11 `.py` + `test-core.R`); for 11 of those the LF content still equals the baseline, only `run_simple.py` differs (the 6-line fix).
- `python -m benchmarks.codex_r.line_endings --verify` passes; `test_line_endings_migration.py` (9) and `test_stage0_regressions.py` pass: all 36 frozen pins verify, exactly 6 through the legacy digest; historical `source_snapshot_sha256 = 6a3046f5…` (20 saved results) is preserved and reproducible from the record.
- `git diff HEAD --stat -- benchmarks tests/data` shows only `run_simple.py`, plus this stage's launcher test files (`fake_runner.py`, `test-b1.R`, `test-core.R`). No scorer, verifier, task, reference, fixture, frozen manifest, report or saved result changed. `E-source-snapshot.sha256` untouched.
- New LF digests are deterministic: `canonical_sha256` is a pure function of LF-normalised bytes; `.gitattributes` makes every checkout LF.
- Not changed by design: `bench.digest` (runtime provenance) still hashes raw bytes; new runs on LF checkouts record LF digests for the 6 affected files, bridged by the record.

## 7. Remaining release blockers

1. **CI has not run.** Local runs do not substitute. User action (needs authorization to push; nothing was pushed):
   ```
   git switch -c verify/stage0-ci            # or use 2.0 if intended
   git add -A && git commit -m "Stage 0/0.5 verification"
   git push -u origin verify/stage0-ci       # workflow triggers on push
   gh run list --branch verify/stage0-ci     # or open the Actions tab
   ```
   Check: `test` ×4 Pythons, `launcher` (new, unverified), `docker`, `native` ×2.
2. All work is uncommitted on `2.0`.
3. The new `launcher` job may need adjustment on first run (R/RSPM install time, termr availability on the runner).
4. U3 (stale `.venv` install) before any local manual testing.

## 8. Changes made in this stage

`src/cran_knowledge_mcp/server.py`, `tests/test_consolidated_server.py`, `docs/ARCHITECTURE.md`, `benchmarks/codex_r/launcher/tests/fake_runner.py`, `…/testthat/test-b1.R`, `…/testthat/test-core.R`, `benchmarks/codex_r/LINE_ENDING_MIGRATION-v1.json` (`mutable` flag), `tests/test_codex_launcher.py`, `tests/test_telemetry_integration.py`, `tests/test_bioc_benchmark.py`, `.github/workflows/tests.yml`, `CONTEXT7_REMOVAL.md`, this report and `stage05-evidence/`.

## 9. GitHub Actions verification (added after push)

| | |
|---|---|
| Branch | `verify/stage0-ci` (2 commits ahead of `2.0` @ `4d2266c`, 0 behind; 189 files; rechecked against the GitHub compare API) |
| Verified commit | `d7db82992531a80fa8b24f54c8f087ba690ad8b7` |
| Run | https://github.com/menshikovs/R-Knowledge-MCP/actions/runs/40664343797 (event `push`, attempt 1, conclusion `success`) |

Jobs read back from the GitHub API (each job's `head_sha` is `d7db829`): `test` 3.11, 3.12, 3.13, 3.14; `native` 3.11, 3.14; `docker`; `launcher` — **all `success`**. Job logs were not downloadable without authentication (HTTP 403), so per-step output was not inspected; conclusions come from the API.

CI history (kept): baseline run 40513710256 failed in "Run pytest" (before Stage 0); run 40663724217 on the first commit `2abac89`: 7 jobs passed, `launcher` failed because `testthat` was not installed (`install.packages` only warns; the CRAN-only `repos` argument forced source builds); fixed in `d7db829` by trying the RSPM binary repository first with CRAN as fallback.

**Local vs CI:** §3–§6 are local runs (Windows, WSL Ubuntu, uv Python matrix). §9 is the first independent confirmation on GitHub runners. The CI `test` job runs without R, termr, Docker images or the private bundle, so those tests skip there (the `launcher` job covers the R/termr tests and fails on any skip).

## 10. Finalization review (pre-PR)

- Diff reviewed against `origin/2.0`: no credentials, tokens, debug leftovers or hard-coded local paths in non-audit files; largest tracked additions are evidence logs (<220 KB). `audits/` evidence contained the local username in paths (24 evidence files with 242 occurrences, not 5 files as first estimated). They are sanitized in the working tree (user-name path components replaced by `<user>`; only those tokens changed, verified against `HEAD`; published and sanitized SHA-256 digests per file are in `SANITIZATION_RECORD-v1.json`, and `EVIDENCE_MANIFEST.json` holds no per-file digests so nothing in it needed re-pinning). A full secret scan of the published `audits/` tree found no real credentials: matches are synthetic test values (`sk-proj-synthe…`, `S3cretPass`, `hunter2`, the AWS documentation key), the example.com address 93.184.216.34 and version strings that resemble IPs. **The unsanitized versions are already in the pushed commit `2abac89` on `origin/verify/stage0-ci`; removing them from published history would need a history rewrite, which was not performed.** No machine hostname occurs in any published audit file. `audits/*.7z` is not committed.
- Stale tool counts found and corrected (comments/docs only): `.env.example` ("15 tools / 35") now "16 / 34"; docstrings in `config.py` and `server.py`.
- **New platform-independent test:** `environment_failure()` extracted from the trial loop in `run_simple.py` (behavior-preserving) and covered by `test_environment_failure_record_uses_reviewed_code_or_fixed_marker` (5 cases). Mutation check: replacing the helper body with a constant makes it fail. This closes the Windows coverage gap noted in §2.
- Tool-schema diff vs `origin/2.0` (tools/list on both toolsets): only `get_context7_docs` removed (legacy 35→34) and `question` removed with `additionalProperties:false` on `get_package` / `get_package_knowledge`; annotations unchanged. Stdio session: protocol 2025-11-25, 16 tools, 2 resources, 14 prompts, ping OK, stale `question` → `invalid_input`.
- Benchmark integrity vs `origin/2.0`: changed under `benchmarks/` only the new record/helper, `run_simple.py`, and three launcher test files; no scorer, verifier, manifest, result, report, task or fixture. `line_endings --verify` passes.
- Rebuilt wheel: 49 files, no Context7, no `benchmarks`/`tests`/`audits`. Docker image builds; the Dockerfile copies only `pyproject.toml`, `README.md`, `LICENSE`, `src` (the build context still includes `audits/`; harmless, could be ignored in `.dockerignore`).
- Rust: `cargo fmt/clippy -D warnings/test` pass; built extension, 108 parity + discovery tests pass (re-run).

### Release-readiness caveats
1. `2.0` itself has not run CI; re-run after merge.
2. Private-bundle registry tests (8) never run in CI.
3. Docker/pinned-image tests never run in CI.
4. Unknown arguments are still ignored by the other 14 consolidated tools.
5. Context7 removal: complete (code, config, docs, tests); remaining mentions are regression tests, "removed" notes and frozen historical files.

### New local run for the finalization changes (not CI)
Windows 11, Python 3.14.4, Docker running: `ruff check` / `ruff format --check` pass (269 files); **1 655 collected; 1 512 passed, 143 skipped, 0 failed** (`stage05-evidence/windows_py3.14_full_pytest_pr_prep.txt`). The +5 tests are the new `environment_failure` cases.

**These finalization edits (helper extraction, new test, count corrections, this report, `PULL_REQUEST_BODY.md`) are uncommitted and unpushed, so they are not covered by run 40664343797**, which verified `d7db829` exactly. They should be committed and pushed so CI re-verifies them before merge.
