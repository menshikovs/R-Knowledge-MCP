# Stage 0 remediation report

Scope: `ROADMAP.md` Stage 0 — CI-001, CI-002, CI-003, CI-004, KC-001, SEC-001 and the part of TST-002 needed for reliable CI.
Raw outputs: `stage0-evidence/`. The Context7 removal requested in the same session is reported separately in
`CONTEXT7_REMOVAL.md`; it shares the working tree, so its effect on counts is called out where relevant.

## 1. Baseline and final state

| | |
|---|---|
| Baseline | branch `2.0`, HEAD `4d2266c994849ac460514ac2ae6df8a6fc5c180e` (= audited commit = `origin/2.0`) |
| Uncommitted user changes at start | none (`git status` clean; only my untracked `audits/` directory existed) |
| Findings confirmed against current source before editing | all six (source identical to the audited commit; reproduced again: bare `pytest` → `Interrupted: 23 errors during collection`, `stage0-evidence/baseline_collect_console_script.txt`). None was already fixed |
| Final state | **uncommitted working-tree changes on `2.0`; nothing committed, pushed or merged** (no instruction to do so; `AGENTS.md` forbids merge/publish as routine work). 34 tracked files modified/deleted + 5 new files (below) |
| Baseline lint caveat | `ruff check .`/`format --check .` failed in the working tree at baseline only because my own audit evidence scripts under `audits/` are linted; with `--exclude audits` the baseline was clean (`baseline_ruff_*.txt`) |

Files (Stage 0 only; Context7 files are listed in `CONTEXT7_REMOVAL.md`):
`pyproject.toml`, `.github/workflows/tests.yml`, `.gitattributes` (new), `src/cran_knowledge_mcp/parsers.py`, `providers/base.py`, `providers/cran.py`,
`function_discovery.py`, `benchmarks/codex_r/run_simple.py` (6 lines), `benchmarks/codex_r/line_endings.py` (new),
`benchmarks/codex_r/LINE_ENDING_MIGRATION-v1.json` (new), `tests/test_stage0_regressions.py` (new),
`tests/test_line_endings_migration.py` (new), `tests/test_codex_expansion_registry.py`, `tests/test_bioc_benchmark.py`,
`tests/test_telemetry_integration.py`. **No scorer, verifier, task, reference solution, fixture, frozen manifest, report or saved result was modified**
(`git diff HEAD --stat -- benchmarks tests/data` shows only `run_simple.py`).

## 2. Finding by finding

### CI-001 — console-script `pytest` could not import `benchmarks` — **FIXED**
- Root cause: `pythonpath = ["src"]`; `pip install -e .` exposes only `src/`; `python -m pytest` adds the cwd, the `pytest` script does not.
- Change: `pyproject.toml` `pythonpath = ["src", "."]` (explicit, cwd-independent); CI gains a `pytest --collect-only -q` step before `pytest`. Also `audits` added to ruff `extend-exclude` (see deviations).
- Evidence: console-script collection before: 23 errors (Windows), 22 (Linux); after: **1 648 tests collected, 0 errors** on Windows/3.14 and Ubuntu/3.14 (`windows_collect_console_script_after.txt`, `linux_ruff_collect.txt`).

### CI-002 — CI did not install what tests import — **FIXED**
- Root cause: `tests/test_mcp_discovery.py:16` → `benchmarks…import_results` → `import duckdb`; CI installed `.[dev]` only (and one analytics test needs `streamlit`).
- Change: CI installs `.[dev,analytics]`. No test was skipped to hide this. Verified on Python 3.11 earlier in the audit: with `[dev]` only the module failed collection, with the extra it collects and runs.

### CI-003 — tests needed a git-ignored private bundle — **FIXED (by explicit skip + public synthetic fixtures)**
- Root cause: `benchmark_expansion_sources/` is deliberately ignored (`private/` holds answer keys); `registry.build_registry()` needs its `SOURCE_MANIFEST.json`.
- Decision: **do not commit** the bundle or its manifest (its own README says the private part must never be published, and the public part is the owner's call). The 8 bundle-backed tests now skip with an explicit reason when the manifest is absent; they still run, unchanged, when the bundle is present (verified: 16 passed with the bundle, 8 passed + 8 skipped without it).
- New public tests (synthetic bundle in `tmp_path`, no benchmark content): manifest accepts a consistent bundle; tampered/missing/unsupported-version bundles are rejected; an absent bundle is a clear `RegistryError`; the path allow-list refuses `private/…`, traversal, absolute and unlisted paths (5 parametrised cases).

### CI-004 — pinned hashes depended on line endings — **FIXED without touching frozen evidence**
- Root cause (confirmed): 116 tracked benchmark text files are CRLF on the author's tree but LF in git; six of the 36 files pinned in `E-source-snapshot.sha256` were hashed over CRLF bytes, so the pin test failed on every LF checkout (Linux CI) and, conversely, failed on Windows clones with `autocrlf` for LF-pinned files. Historical results recorded the CRLF digests (verified: `source_snapshot_sha256 = 6a3046f5…`, `source_checksum_manifest_sha256 = 2a293194…` in run `20261025T135949Z-9ff06c47`).
- Canonical byte semantics: **LF**. `.gitattributes` (`benchmarks/** text=auto eol=lf`, `tests/data/** text=auto eol=lf`) makes every future checkout LF; `git status` stays clean on the author's CRLF tree and the index is unchanged (verified, `git ls-files --eol`).
- `benchmarks/codex_r/line_endings.py`: `canonical_sha256`, `legacy_crlf_sha256`, `pin_matches` (accepts exactly the canonical or the legacy digest of the same content — no weaker than before).
- **Versioned migration record** `benchmarks/codex_r/LINE_ENDING_MIGRATION-v1.json` (117 entries, baseline commit recorded): per file the legacy digest (CRLF, as recorded historically) next to the canonical digest; 11 `.py` entries are flagged `mutable` (digests describe the baseline only). `E-source-snapshot.sha256`, all historical results and all scorers are untouched; `source_*_sha256` values in old results remain valid and are reproducible from the record.
- Tests: `test_line_endings_migration.py` (9) — round-trip, strictness (content change still detected), record consistency, the exact historical digests preserved, all 36 frozen pins verify on any checkout with exactly 6 resolved through the record, `.gitattributes` content. `test_bioc_benchmark.py::test_e02_fixture…` now uses `pin_matches` for its five pins.
- Consequence to note: new benchmark runs will record LF digests for those files (different from historical runs); the record bridges the two. `bench.digest` (runtime provenance) was intentionally not changed.

### TST-002 — **PARTIALLY FIXED**
- Fixed (verified stale/inconsistent): `tests/test_telemetry_integration.py` asserted schema `"1.1"` while `schema.SCHEMA_VERSION == "1.2"` (and the same file asserts 1.2 elsewhere) → now asserts the constant and `"1.2"`.
- Fixed (real inconsistency, Linux-only test): `run_simple.py` stored `environment_error` as the string `"environment_failed"` on the event path but as `{"code": …}` on the session path; the test expected the dict with the reviewed code. The event path now uses the same reviewed-code helper (`error_code`) and falls back to the string when no reviewed code is present. Verified on Ubuntu: both `…[environment_failed]` cases pass; 66 related runner/telemetry tests pass.
- **Not fixed (environmental, unattributed):** `test_codex_launcher.py` ×5 (need R + `termr`; fail in WSL with 22 failed R expectations / PTY behaviour) and `test_telemetry_integration.py::test_full_chain_with_real_mcp_container` (needs the author's locally built Docker images; after the schema fix it fails later with `KeyError: 'is_error'` on a client event — possibly a stale local image, not established). Both groups skip on a machine without R/`termr` or the images, so they should skip on `ubuntu-latest`; **that is unverified until CI runs**.

### KC-001 — one undecodable Rd broke the whole package — **FIXED**
- Root cause: `providers/base.py::_alias_index` decoded every Rd with the DESCRIPTION encoding; one file with its own `\encoding{latin1}` raised `unsupported_encoding` for every lookup, while discovery tolerated the same file → the tools disagreed.
- Change (`parsers.py`): `rd_declared_encoding` (reads the file's `\encoding{}` from raw ASCII bytes, ignores commented lines, rejects unknown codecs, `unknown` = none) and `decode_rd` (precedence **file declaration → DESCRIPTION `Encoding` → UTF-8**, strict, nothing replaced or guessed). `_alias_index` skips and records undecodable files; `get_function_docs` decodes each matched file with its own encoding; `function_discovery.build_discovery_index` uses the same helper.
- Provenance/verification (additive fields only): success results carry `rd_encoding: {encoding, source}` and, only when some files were unreadable, `unreadable_rd_members_in_package`; a `docs_not_found` for such a package adds `alias_index_complete: false`, `unreadable_rd_members`, `unreadable_rd_member_names` (≤ 20) so absence is not presented as verified. No new fields appear for healthy packages (the existing 1 500-byte error-size regression budget still passes). No R code or Rd macro is executed (test with an Rd containing `\Sexpr[results=rd]{stop(...)}` returns it as inert text).
- Tests (synthetic mixed-encoding archives): UTF-8 + `\encoding{latin1}` + undecodable file → unrelated and latin1 aliases succeed, the unreadable one is reported; discovery and docs agree; DESCRIPTION `Encoding: latin1` honoured and the file's own declaration wins; plus 3 unit tests for the helpers.
- **Real-data check (read-only CRAN fetch, one tarball):** before — `cluster::agnes`, `daisy`, `plantTraits` all `unsupported_encoding`; after — all OK (`plantTraits` decoded as `iso8859-1` via `rd_declaration`), discovery lists `plantTraits` (84 aliases, equal to R's 84) and no longer reports `rd_encoding_unavailable` (`kc001_real_cluster_after.txt`; `MASS::lm.ridge` still OK).

### SEC-001 — quadratic `dcf()` — **FIXED**
- Root cause: `record[key] += " " + line.strip()` copied the growing string for every continuation line.
- Change: continuation parts are collected in a list and joined once per field; DESCRIPTION parsing at both call sites (`providers/cran.py::_lightweight_description`, `providers/base.py::source`) now runs in `asyncio.to_thread`. Behaviour preserved exactly: continuation joining (including the leading space for an empty first value), duplicate-field error (per record), malformed-line error, blank-line record separation, CRLF; no new size limits (existing caps untouched).
- Tests: equivalence against the verbatim old algorithm on 13 fixed inputs and 400 seeded random inputs (identical results or identical error codes); explicit error semantics; a 698 000-line field parses in < 10 s (limit chosen generously; actual ≈ 0.2 s); four adversarial shapes (200 000 records, 100 000 fields, one 1 MB value, 200 000 blank lines); and an async test that a 600 000-line DESCRIPTION through `get_package_info` leaves the event loop responsive (max heartbeat gap < 2 s).
- **Measurements** (same machine, `stage0-evidence/sec001_dcf_before_after.txt`, median of 3–5 runs; the old algorithm copied verbatim):

| continuation lines | input | old | new | speed-up | peak memory old → new |
|---|---|---|---|---|---|
| 20 000 | 0.06 MB | 0.010 s | 0.002 s | 4× | 1.2 → 2.1 MB |
| 80 000 | 0.24 MB | 0.118 s | 0.011 s | 10× | 4.8 → 8.4 MB |
| 350 000 | 1.05 MB | 2.6 s | 0.056 s | 46× | 20.8 → 36.5 MB |
| 698 000 | 2.09 MB | 80.4 s (57.4 s in the audit run) | 0.207 s | 388× | 41.5 → 72.9 MB |

  Honest trade-off: peak memory for a pathological field is about 1.75× higher (a list of small strings instead of one growing string); it is bounded by the existing 2 MiB DESCRIPTION cap (≈ 73 MB at the cap). The old-algorithm times vary with machine load (57 s in the audit, 80 s here); the new one is linear.

## 3. Commands executed (all recorded under `stage0-evidence/`)
`git rev-parse/status`; `ruff check .` / `ruff format --check .`; `pytest --collect-only -q` (console script); `python -m pytest` and bare `pytest`; targeted suites (MCP interface: `test_server`, `test_consolidated_server`, `test_mcp_errors`, `test_mcp_discovery`; CRAN provider: `test_service`, `test_metadata_modes`, `test_http`; Function Discovery: `test_function_discovery`, `test_function_discovery_replay`, `test_function_docs_hints`; security/regression: `test_stage0_regressions`, `test_parsers`, `test_external_knowledge`); Python/Rust parity with the built extension; `pip wheel` + isolated install + stdio/HTTP probes; `docker build` / `run`; WSL Ubuntu clean-clone runs (`pip install -e '.[dev,analytics]'`, `ruff`, `pytest --collect-only`, `pytest`); `python -I bench_dcf.py`; `real_cluster_check.py` (read-only CRAN fetch).

## 4. Results

| Check | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | pass / pass (269 files), Windows and Ubuntu |
| Console-script collection | 1 648 collected, 0 errors, Windows/3.14 and Ubuntu/3.14 |
| **Ubuntu 26.04 (WSL2), Python 3.14.4, clean clone + overlay, `pip install -e '.[dev,analytics]'`, `pytest`** (CI-equivalent; Docker present, R/`termr` present) | 7 failed, 1 573 passed, 68 skipped (`linux_full_pytest_final.txt`). The 7: the 5 launcher tests and the real-container test described above, plus `test_migration_record_is_consistent_with_the_files` which failed only because the record had been generated before the `run_simple.py` edit — fixed by the `mutable` flag and re-verified (76 targeted tests pass). **Before Stage 0 the same environment: 17 failures after the cheapest fixes, 22 collection errors at the start** |
| Windows 11, Python 3.14.4, author's working tree (bundle present, CRLF files) | **1 462 passed, 186 skipped, 0 failed** (`windows_full_pytest_final.txt`) |
| Windows 11 clean clone + overlay (scratch path), Python **3.11 / 3.12 / 3.13**, `python -m pytest` | each: **1 failed, 1 444 passed, 203 skipped** (`windows_cleanclone_py3.1x_full_pytest.txt`). The single failure is `test_bioc_benchmark.py::test_e02_reproduction_and_standard_workflow_in_both_images`, a Docker test whose container-generated CSV differs from the fixture when the checkout lives under this scratch path; it failed identically from a scratch-path clone at the audited baseline and it passes from the author's checkout path, also after forcing every `knowledge_pilot` file to LF (`windows_cleanclone_lf_e02_docker_test.txt`) — i.e. environmental (Docker Desktop bind-mount path), not caused by Stage 0. Not investigated further |
| Python/Rust parity (built extension) + discovery + Stage 0 tests | 135 passed (`native_parity_check.txt`) |
| Packaging/CLI | wheel builds; installed `r-knowledge-mcp --help` works; stdio session identical to the audited baseline; HTTP probe identical (`wheel_cli_stdio_check.txt`, `http_transport_check.txt`) |
| Docker | image builds, `--help` works, no `providers.context7` module (`docker_check.txt`) |
| Rd real-data check | cluster fixed (above) |

## 5. Remaining limitations
- The six environment-dependent Linux failures above are unresolved and unattributed; they depend on a locally installed R/`termr` and locally built Docker images.
- `test_e02_reproduction_and_standard_workflow_in_both_images` (Docker) fails on Windows when the repository is checked out under the scratch path used for the clean-clone runs and passes from the author's path; the cause (Docker Desktop mount of that path) is not established.
- `test_full_chain_with_real_mcp_container` exercises a locally built MCP image; its `is_error` failure may reflect a stale image.
- KC-002 (partial-status noise), KC-003 (version spelling), the other Stage 1+ items and all other audit findings are untouched by design.
- Old `.venv-wsl/bin/python` (a Linux symlink in the author's Windows tree) makes `tests/test_codex_launcher.py` fail at *collection* on Windows for Python 3.11–3.13 (`WinError 1920`; 3.14 tolerates it); this exists only in that working tree, not in a clone, which is why the 3.11–3.13 runs use a clean clone.
- Line-ending policy applies to new checkouts; existing CRLF working files stay CRLF until re-checked-out (the author's tree is unaffected and `git status` is clean).
- Peak memory of the new `dcf()` is ~1.75× the old one on pathological input (bounded by the existing cap).

## 6. CI workflow status — **BLOCKED**
Nothing was committed or pushed, so the GitHub Actions matrix (Python 3.11–3.14, docker, native) has **not** been run on these changes. The workflow was edited (analytics extra + collection step). The last known real CI result for the baseline is run 40513710256 (test jobs failed at "Run pytest"; docker and native passed). Local equivalents are in §4. Re-run CI after committing before treating Stage 0 as complete.

## 7. Deviations from the audit recommendation
1. **CI-003:** skip-with-reason plus synthetic public tests instead of committing a manifest (the bundle's private part must not be published; the public part is the owner's decision).
2. **CI-004:** the audit suggested `.gitattributes` and re-pinning; I did **not** re-pin or edit `E-source-snapshot.sha256` (frozen). Instead a versioned migration record plus canonical-or-legacy verification preserves every historical digest.
3. **CI-002:** installs the full `analytics` extra (duckdb, pandas, streamlit) rather than splitting a lighter extra — simplest, no skips, slower installs.
4. `audits` was added to ruff `extend-exclude` because the audit directory contains non-conforming evidence scripts that would otherwise break `ruff check .`.
5. **TST-002** needed a 6-line change in the benchmark runner (`run_simple.py`) to make the record shape consistent; it is not a scorer/verifier/frozen file but it is benchmark code — flagged for review.
6. KC-001 additions to the response (`rd_encoding`, conditional unreadable-member fields) are additive; the audit only asked for correct decoding and explicit provenance.
7. Python 3.11–3.13 were run locally from a clean clone (not via CI) because CI was not available.

## 8. Acceptance criteria

| Criterion | Status |
|---|---|
| All intended tests collect without import errors | **PASS** (console script, Windows and Ubuntu) |
| CI-required dependencies available | **PASS** (`.[dev,analytics]` in workflow; verified by install) |
| Fresh clone needs no private files for public tests | **PASS** (Ubuntu clean clone; bundle-backed tests skip explicitly) |
| Frozen benchmark integrity preserved | **PASS** (no frozen file changed; migration record preserves old/new digests) |
| Rd decoding no longer causes package-wide failure | **PASS** (synthetic + real `cluster`) |
| DESCRIPTION parsing no longer quadratic | **PASS** (0.2 s vs 57–80 s at the cap) |
| Python 3.11–3.14 **CI** jobs pass | **BLOCKED** — not run (nothing pushed); local matrix in §4 |
| Native and Docker checks remain green | **PASS locally**; **CI BLOCKED** |
| No unintended MCP protocol behaviour change | **PASS** for Stage 0 (stdio/HTTP probes identical); the Context7 removal changes the tool surface intentionally (`CONTEXT7_REMOVAL.md`) |
| Report includes reproducible evidence | **PASS** |

**Overall: Stage 0 is NOT yet complete** — the CI matrix is unverified (BLOCKED) and six environment-dependent Linux test failures remain unattributed.
