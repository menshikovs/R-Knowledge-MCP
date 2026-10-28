# Findings register — R-Knowledge-MCP 2.0

Audited commit: `4d2266c994849ac460514ac2ae6df8a6fc5c180e` (branch `2.0`; local HEAD equals
`refs/heads/2.0` on `origin` at audit time). Audit date 2026-10-27. This file is the canonical register;
every other report links here by finding ID instead of repeating the analysis.

Severity: **P0** confirmed compromise / data-integrity failure / cannot operate; **P1** significant correctness,
reliability, security or measurement-validity problem; **P2** substantial maintainability, performance,
usability or testability issue; **P3** localized improvement or documentation inconsistency.
Confidence: **confirmed** (reproduced by me, evidence stored) / **probable** (code reading + partial
reproduction) / **possible** (code reading only, not reproduced).

No P0 finding was identified. CI is red at this commit (confirmed against the actual GitHub Actions run), but
that alone is not P0: the production server, its stdio/HTTP transports and its container image work.

## Summary table

| ID | Sev | Conf. | Title |
|---|---|---|---|
| CI-001 | P1 | confirmed | Bare `pytest` (the CI command) cannot import `benchmarks`; whole test job fails at collection |
| KC-001 | P1 | confirmed | One Rd file with its own `\encoding{}` makes `get_function_docs` fail for every function of the package (real CRAN `cluster`) |
| BEN-001 | P1 | confirmed | The benchmark programme has produced no evidence that can support (or refute) an MCP effect |
| CI-002 | P2 | confirmed | CI installs only `[dev]`, but a test module imports `duckdb` unconditionally |
| CI-003 | P2 | confirmed | 8 tests require a git-ignored `benchmark_expansion_sources/SOURCE_MANIFEST.json`; they fail in any clean clone |
| KC-002 | P2 | confirmed | Discovery reports `verification_status: partial` for ~half of real packages, often for harmless reasons |
| KC-003 | P2 | confirmed | `list_package_functions` and `get_function_docs` disagree on what "same version" means |
| SEC-001 | P2 | confirmed (exploitability unverified) | `dcf()` is quadratic on continuation lines; 2 MiB DESCRIPTION blocks the event loop ≈ 1 minute |
| SEC-002 | P2 | confirmed | HTTP transport: no authentication, no rate limit, unauthenticated GET holds an SSE stream open indefinitely |
| MCP-001 | P2 | confirmed | `outputSchema` is the empty-object schema for all 16/35 tools |
| AGT-001 | P2 | confirmed | Tool descriptions say what a tool is, not when to use it; legacy surface has no parameter descriptions |
| AGT-002 | P2 | confirmed | Two default tools and two resource templates are empty on a fresh install |
| BEN-002 | P2 | confirmed | D/E-block scorers use exact frozen-URL/version membership; live MCP data cannot match a time-pinned snapshot |
| BEN-003 | P2 | confirmed | A/B design: fixed arm order, pooled heterogeneous configurations, differential attrition, no token/cost accounting |
| BEN-004 | P2 | confirmed | Most tasks are saturated or never touch MCP; the suite cannot discriminate |
| BEN-005 | P2 | confirmed | "Frozen" evidence (`results/`) is untracked; reports link to files that do not exist in the repository |
| TST-001 | P2 | confirmed | Test portfolio is dominated by benchmark-harness tests; synthetic mocks hid KC-001/KC-002; no property tests |
| ARCH-001 | P2 | confirmed | `KnowledgeService` (1 952 lines, 50 methods) and `PromptIntelligence` (1 648 lines) are god classes |
| PI-001 | P2 | confirmed | Prompt Intelligence heuristics are unvalidated (intent 21/30 on an exploratory set) and the structural score is gameable |
| CI-004 | P2 | confirmed | "Frozen" hash manifests are line-ending dependent: 6 of 36 pinned files validate only on the author's CRLF tree; fails on Linux; no `.gitattributes` |
| SEC-003 | P3 | confirmed | Default INFO logging writes upstream URLs, including Context7 question text, to stderr |
| SEC-004 | P3 | confirmed | Context7 redaction rewrites ordinary words ("token", "password") |
| SEC-005 | P3 | confirmed | GitHub repository identity comes from a package-author-controlled field but is labelled "verified" |
| SEC-006 | P3 | confirmed | Package-author text is returned with no per-field untrusted marker |
| SEC-007 | P3 | confirmed | Supply-chain hygiene: unpinned base image, no lockfile/hashes, actions pinned by tag, no HEALTHCHECK |
| SEC-008 | P3 | possible | LRU `OrderedDict` is mutated from a worker thread |
| SEC-009 | P3 | possible | `yaml.safe_load` of upstream `config.yaml` runs on the event loop with alias expansion |
| MCP-002 | P3 | confirmed | Protocol nits: unknown tool → `isError` result; missing resource → success payload; legacy annotations over-claim `openWorldHint` |
| MCP-003 | P3 | confirmed | Every result carries the payload twice (`content` and `structuredContent`) |
| MCP-004 | P3 | confirmed | Input constraints are stated in prose; 26 of 109 parameters carry a machine-readable constraint |
| TST-002 | P3 | confirmed | Stale/inconsistent assertions that only run with Docker/Linux (telemetry schema 1.1 vs 1.2; `environment_error` str vs dict) |
| KC-004 | P3 | possible | Hard `source_too_large` (not partial) when NAMESPACE > 4 000 directives or index > 10 000 entries |
| KC-005 | P3 | confirmed | "exports" are static declarations; S4 class/method names differ from `getNamespaceExports()` |
| ARCH-002 | P3 | confirmed | `parsers.py` ("data-only") lazily imports an analyzer module; dead code `_gap` |
| DOC-001 | P3 | confirmed | Documentation drift (tool count, GitHub token, version, links, container default host) |
| PERF-001 | P3 | confirmed | Bioconductor provider rebuilt and `config.yaml` re-parsed on every cache refresh/call (≈ 12 ms per call) |

Counts: P0 0 · P1 3 · P2 17 · P3 16 · total 36.

---

## P1

### CI-001 — Bare `pytest` cannot import `benchmarks`; the CI test job fails at collection
- **Severity / confidence:** P1 / confirmed. **Subsystem:** testing, CI.
- **Location:** `pyproject.toml:27-28` (`testpaths = ["tests"]`, `pythonpath = ["src"]`); `.github/workflows/tests.yml:16,19`
  (`pip install -e '.[dev]'`, then `pytest`); 25 test modules do `from benchmarks.codex_r… import …`
  (for example `tests/test_baseline_root_cause_audit.py:12`).
- **Evidence:** `evidence/ci/wsl_ci_bare.txt` (Ubuntu/WSL, Python 3.14.4, CI's exact install and commands: ruff check pass,
  ruff format pass, `pytest` → "22 errors during collection", every one `ModuleNotFoundError: No module named 'benchmarks'`);
  `evidence/ci/pytest_bare_collect_windows.txt` (23 errors, same cause); `evidence/ci/github_actions_run.json`
  (GitHub Actions run 40513710256 for this SHA: `test (3.11/3.12/3.13/3.14)` all failed or were cancelled at step "Run pytest";
  `docker` and `native (3.11/3.14)` succeeded). `python -m pytest --collect-only` collects 1 606 tests, so the tests themselves import fine.
- **Reproduction:** `git clone … && git checkout 4d2266c && python -m venv v && v/bin/pip install -e '.[dev]' && v/bin/pytest`.
- **Expected:** the suite is collected. **Actual:** pytest is interrupted; zero tests run.
- **Root cause:** `pip install -e .` makes only `src/` importable (`[tool.setuptools.packages.find] where = ["src"]`).
  `benchmarks/` is importable only when the current directory is on `sys.path`, which `python -m pytest` does and the `pytest`
  console script does not.
- **Impact:** the repository's only automated gate verifies nothing on any advertised Python version.
- **Fix (smallest robust):** `pythonpath = ["src", "."]` in `[tool.pytest.ini_options]`. Verified: `pytest -o pythonpath="src ."`
  collects 1 606 tests on Windows/3.14 and 1 554 + 1 error (CI-002) on 3.11 with only `[dev]` installed. Add `pytest --collect-only -q`
  as a CI step so collection errors are reported separately.
- **Regression test:** CI itself; plus a one-line test that `importlib.import_module("benchmarks.codex_r")` succeeds under the console-script `pytest`.
- **Complexity:** trivial. **Depends on:** CI-002 and CI-003 for a green run.

### KC-001 — One Rd file with its own `\encoding{}` breaks `get_function_docs` for the whole package
- **Severity / confidence:** P1 / confirmed (real upstream data). **Subsystem:** CRAN provider, Function Discovery vs docs.
- **Location:** `src/cran_knowledge_mcp/providers/base.py:240-252` (`_alias_index` decodes *every* `.Rd` with the DESCRIPTION encoding,
  line 248); `parsers.py:124-128` (`decode` raises `unsupported_encoding`); contrast `function_discovery.py:198-203`, which tolerates the same
  failure and marks the index partial.
- **Evidence:** `evidence/probes/probe_real3_cluster_docs.txt`: CRAN `cluster` 2.1.8.3 (a recommended package shipped with R):
  `get_function_docs("cluster","agnes")`, `("cluster","daisy")` and `("cluster","plantTraits")` all return `unsupported_encoding`, while `MASS::lm.ridge`
  works. `evidence/probes/probe_real2_encoding_namespace.txt`: `cluster/man/plantTraits.Rd` is not decodable as UTF-8 and declares `\encoding{latin1}`
  in the file; DESCRIPTION has no `Encoding`.
- **Expected:** documentation for `agnes` is returned; only the one undecodable Rd is skipped or decoded with its declared encoding (R's own Rd rule).
  **Actual:** a package-wide failure with a misleading error. `list_package_functions("cluster")` succeeds (partial, 83 of 84 aliases), so the two tools disagree:
  discovery offers `agnes`, docs refuse it.
- **Impact:** total docs outage for each package with a mixed-encoding Rd set. Prevalence is unknown: 0 of a seeded random sample of 30 current CRAN packages
  showed it (`evidence/real_cran_sample.json`; 95 % upper bound ≈ 11 %), but it hits a package distributed with R.
- **Fix:** decode each Rd with its `\encoding{}` declaration (fall back to DESCRIPTION, then to a lossy decode flagged `partial`); make `_alias_index` skip and
  report undecodable members instead of raising.
- **Regression test:** synthetic tarball with 3 UTF-8 Rd files and one latin1 Rd containing `\encoding{latin1}` and a byte `0xE9`; assert docs for a UTF-8 alias succeed, the latin1 alias resolves, and `rd` status is `verified` or `partial` as appropriate.
- **Complexity:** small. **Depends on:** none.

### BEN-001 — No evidence yet supports or refutes an MCP effect
- **Severity / confidence:** P1 (measurement validity) / confirmed. **Subsystem:** `benchmarks/codex_r/`.
- **Evidence** (local, untracked results rebuilt into DuckDB: `evidence/benchmark/bench_stats.txt`, `bench_err.txt`, `bench_d01.txt`; see BEN-005 for provenance caveat):
  91 trials in 25 runs over 22 tasks, all `gpt-6-luna`/medium. 26 of 42 task×mode cells have n = 1. Of 43 scored with-MCP trials, 9 (21 %) made any MCP call.
  Of 21 tasks that have both arms, 17 show no difference (ceiling or no MCP use) and 4 differ in mixed directions (D01 +0.38, E04 +0.20, D02 −0.12, H10 −0.06; one-sided sign test on the 4 non-ties p = 0.69).
  Replicates of D01 with MCP range 0.25–1.0. Token usage was observed in 1 of 91 trials, cost in 0 of 91.
  The latest "discovery enabled vs disabled" pair (3/4 vs 1/4, `p1e_discovery_evidence_audit_20261027.md`) has **0 MCP calls in the disabled arm** (`results/…091937Z-29e767cb/results.json`),
  so it compares *used* with *unused* MCP, not discovery on/off; an earlier pair on the same task went the other way (2/4 vs 4/4, `p1d_evidence_audit.md`).
- **Balance:** on D01 alone, all 6 trials that used MCP scored 3–4/4 and all 6 that did not scored 1–2/4 (`bench_d01.txt`) — suggestive of a use-conditional benefit where the no-browsing agent has no other source, but use was not randomised and D01 is one task.
- **Expected:** a pre-registered, adequately replicated paired design that can estimate an effect with an interval. **Actual:** exploratory descriptive runs, as the project's own reports state
  ("Воспроизводимый causal effect не оценён"; "descriptive, not causal").
- **Impact:** the central product question — does the server improve agent outcomes — is unanswered; no decision should rest on the current numbers.
- **Fix:** see `BENCHMARK_SCIENTIFIC_AUDIT.md` §7 (confirmatory design) and `ROADMAP.md` Stage 2. **Complexity:** large (design + budget). **Depends on:** BEN-002..004.

---

## P2

### CI-002 — CI installs `[dev]` only; a test module imports `duckdb` at import time
- **Location:** `tests/test_mcp_discovery.py:16` → `benchmarks/codex_r/analytics/import_results.py:19` (`import duckdb`); `pyproject.toml` `[project.optional-dependencies] analytics`; `tests.yml:16`.
- **Evidence:** `evidence/ci/py311_collect_fixedpath.txt`: with CI-001 fixed and `.[dev]` only, 1 collection error `No module named 'duckdb'` (Python 3.11).
- **Fix:** install `.[dev,analytics]` in CI, or `pytest.importorskip("duckdb")` before the import. **Complexity:** trivial. **Depends on:** CI-001.

### CI-003 — Eight tests need a git-ignored manifest
- **Location:** `benchmark_expansion_sources/.gitignore` (`*`, `!.gitignore`); `benchmarks/codex_r/expansion/registry.py:135`; `tests/test_codex_expansion_registry.py` (8 tests).
- **Evidence:** `evidence/ci/pytest_linux_fixed.txt` and `evidence/ci/pytest_windows_clone_cov.txt`: the same 8 tests fail on Linux and Windows clones with `Cannot read JSON manifest …/SOURCE_MANIFEST.json`.
- **Expected:** tests pass or skip in a clean clone. **Actual:** deterministic failures independent of platform.
- **Fix:** commit a public manifest, or `skipif` when the private manifest is absent (and say so). **Complexity:** small.

### CI-004 — Frozen hash manifests depend on line endings
- **Severity / confidence:** P2 / confirmed. **Subsystem:** benchmark evidence integrity, CI.
- **Location:** `benchmarks/codex_r/knowledge_pilot/metadata/E-source-snapshot.sha256` (36 pinned files); `tests/test_bioc_benchmark.py:24-35`; no `.gitattributes`.
- **Evidence:** the author's working tree stores 184 tracked files with CRLF (`git ls-files --eol`: `i/lf w/crlf`). Six of the 36 pinned files (`metadata/E-source-snapshot.json`, `E01.json`…`E05.json`) were hashed over their **CRLF** bytes; git stores them as LF.
  On an LF checkout (Ubuntu/WSL, identical to GitHub's runner) `test_e02_fixture_is_nonnegative_integer_nb_input_with_provenance` fails (`e0ae5270… != 6a3046f5…`, `evidence/ci/pytest_linux_fixed.txt`); on a Windows clone with `core.autocrlf=true` the same test fails earlier because `E02-counts.csv` (pinned over LF) becomes CRLF (`evidence/ci/pytest_windows_clone_cov.txt`).
  The pinned set therefore validates only on one specific line-ending configuration.
- **Impact:** the "frozen" scorer/task inputs are not byte-identical across checkouts, so the freeze cannot be verified by a third party on Linux — the platform the benchmark containers use. Agents that read `/mnt/c` Windows trees would see CRLF task files.
- **Fix:** add `.gitattributes` (`benchmarks/** -text`, or `eol=lf` for pinned files), re-pin from `git show HEAD:<path>` bytes, and verify pins in CI on Linux. **Regression test:** the existing pin test, run on Linux CI. **Complexity:** small.

### KC-002 — "partial" is the norm, often for harmless reasons
- **Location:** `parsers.py:332-336` (every NAMESPACE argument must be a literal; only the *named-argument* check exempts `useDynLib`, so `.registration = TRUE` is "non-literal"); `parsers.py:417-420` (`\if`, `\ifelse`, `\Sexpr`… anywhere in an Rd file marks it "incomplete").
- **Evidence:** seeded random sample of 30 current CRAN packages: 16 `verified`, 14 `partial` (47 %, Wilson 95 % CI 30–64 %); causes `rd_literal_coverage_partial` 6, `export_patterns_not_expanded` 5 (legitimate), `namespace_nonliteral_arguments` 3 (`evidence/real_cran_sample.json`).
  Of 15 hand-picked packages, 12 were partial (`evidence/real_discovery_vs_R.json`). `probe_real2…`: MASS, cluster, survival are flagged only because of `useDynLib(pkg, .registration = TRUE)`.
  `probe_rdpartial…`: all 44 "incomplete" Rd files of `termr` 1.0.1 contain roxygen-generated `\if{html}{…}` blocks — documentation formatting, irrelevant to `\alias`.
- **Impact:** a status that is "partial" for about half of packages carries no information; agents learn to ignore it, and the benchmark's "9 of 9 partial" observation (P1-E) is explained without any real coverage problem.
- **Fix:** exempt `useDynLib` arguments; apply the macro check only to `\name`/`\alias` context; report *which* entries are unverifiable instead of downgrading the whole result.
- **Regression test:** NAMESPACE with `useDynLib(x, .registration = TRUE)` is `verified`; Rd with `\if{html}{…}` in `\description` is `verified`; Rd with `\alias{\Sexpr{…}}` is `partial`.
- **Complexity:** small. **Depends on:** none.

### KC-003 — Two tools disagree on version equality
- **Location:** `providers/base.py:280-296` (exact string comparison of `package_version` with the repository string) vs `service.py:1694,1712` (normalised `version_parts` comparison).
- **Evidence:** `evidence/probes/probe_a_version_equivalence.txt` (current `2.10-1`): requesting `2.10.1`, `2.10-1.0` or `2.10-01` gives `requested_version_unavailable` from discovery but success from docs.
  Real-world trigger: R's `packageVersion("MASS")` prints `7.3.65` while DESCRIPTION says `7.3-65` (`evidence/real_truth_versions.txt`); R treats `.` and `-` as equivalent.
- **Impact:** an agent that passes the installed version in the form R prints it gets a false "version unavailable" from `list_package_functions` and a misleading message ("Only the selected repository version is available").
- **Fix:** use `version_parts` in `providers/base.py` (both call sites). **Regression test:** parametrised over the four spellings for both tools. **Complexity:** trivial.

### SEC-001 — Quadratic `dcf()` blocks the event loop
- **Location:** `parsers.py:22-23` (`record[key] += " " + line.strip()` copies the growing value for each continuation line); called synchronously from coroutines at `providers/cran.py:101` and `providers/base.py:225`.
- **Evidence:** `evidence/probes/probe_redos.txt`: 80 000 continuation lines 0.12 s, 350 000 lines 2.4 s, 698 000 lines (just under the 2 MiB DESCRIPTION cap) ≈ 57 s. `bounded()` (`service.py:2265`) cannot interrupt synchronous code.
- **Precondition (unverified):** a hostile DESCRIPTION accepted by CRAN/Bioconductor, or a compromised upstream. I did not test whether CRAN's own checks reject such a file.
- **Impact:** one tool call stalls every client of a shared HTTP deployment for about a minute.
- **Fix:** collect continuation lines in a list and `"".join`; run the parse in `asyncio.to_thread`; cap field length. **Regression test:** 700 000-line field parses in < 1 s.
- **Complexity:** small.

### SEC-002 — HTTP transport has no authentication, rate limiting or idle limits
- **Evidence:** `evidence/probes/probe_http_transport.txt`: Host/Origin validation works (421/403 for foreign hosts/origins; default allows only loopback); request body > 1 MB → 413; a request with no credentials is served;
  `GET /mcp` returns `200 text/event-stream` and the stream is still open 3 s later with no events (no idle timeout, no keepalive policy); a 100 000-deep JSON body yields HTTP 500 and a `RecursionError` stack in the server log.
  `Dockerfile:10` binds `0.0.0.0`; the container refuses inter-container Host names (421) until `--allowed-host` is given (verified in a local container run).
- **Documented?** Yes: `docs/security.md:70-75` calls the listener a development server and tells operators to add TLS/auth/limits. The finding is therefore a *readiness blocker* for remote hosting, not a hidden vulnerability.
- **Fix:** reverse-proxy requirements in the deployment guide; optional bearer-token middleware; connection/idle limits; per-IP concurrency cap. **Complexity:** medium.

### MCP-001 — `outputSchema` is effectively empty
- **Evidence:** `evidence/mcp/tools_consolidated.json`; `evidence/probes/probe_mcp_shape.txt`: `{"additionalProperties": true, "title": "get_packageDictOutput", "type": "object"}` for every tool (return type `dict[str, Any]`, e.g. `server.py:1032`).
- **Impact:** clients cannot validate or type results; the documented envelope (`package, repository, package_version, bioc_version, source_url, checked_at, verification_status, sources, error`) is a convention only.
- **Fix:** declare a shared envelope model with `additionalProperties: true` for tool-specific payload; test that `structuredContent` validates against `outputSchema`. **Complexity:** medium; **risk:** clients that currently ignore the schema will start validating (benign if the envelope is permissive).

### AGT-001 — Descriptions describe, they do not guide
- **Evidence:** `evidence/mcp/tools_*.json`. Consolidated: 16 tools, 109 parameters, all described, but descriptions are one line (median 82 characters; only `list_package_functions` has more, 407) with no *when to use / when not to use / what evidence is returned / which source is authoritative*.
  Legacy (35 tools, 140 parameters): **0** parameter descriptions, **0** titles, `openWorldHint=true` on every tool including purely local ones. Overloaded signatures: `build_r_prompt` 21 parameters, `analyze_r_source` 13 (a `kind` union), `get_package` 9 with conditionally required parameters (`revision` only with `agent_guidance`, `question` only with `context7`).
  Default server instructions (`mcp_discovery.py:8-24`, "control") are provenance/safety prose; the usage-oriented text exists only as the experimental "treatment" variant (`mcp_discovery.py:26-37`).
- **Impact (probable, not proven):** consistent with the observation that 79 % of scored with-MCP trials made no MCP call (BEN-001), but that data cannot isolate description quality. See `AGENT_USABILITY_AUDIT.md`.
- **Fix:** rewrite descriptions to a fixed template; keep `get_package.include` sections but state prerequisites in the description; do not force use. **Complexity:** small (text) + experiment (BEN-001 design).

### AGT-002 — R manual tools are empty until an undocumented-in-the-tool step
- **Evidence:** `evidence/probes/probe_f_rdoc_fresh_install.txt`: with no index file, `search_r_documentation` returns all six manuals as `index_status: not_indexed`, `section_count: 0` (honest, but useless).
  The refresh command (`python -m cran_knowledge_mcp.providers.r_documentation --refresh`, `docs/R_DOCUMENTATION.md:26`) is not a console script; the tool descriptions do not mention the prerequisite.
- **Impact:** 2 of 16 default tools and 2 of 3 resource templates are dead on a fresh install, inflating the surface the agent must reason about. **Fix:** console script + one sentence in the description, or hide the tools until an index exists. **Complexity:** small.

### BEN-002 — Scorer design: exact URLs, hidden string contracts, frozen snapshot, live tool
- **Location:** `benchmarks/codex_r/knowledge_pilot.py:547-548,591-600` (D block: `url in _resource_urls(frozen, kind)`; `version == expected["version"]`); `knowledge_pilot.py:651-726` (E block: exact dict equality such as `packages["DESeq2"] == {"version": "1.50.2", "repository": "Bioconductor 3.22"}`, `changed_fields == ["r_version"]`, every `sources` URL must start with `https://bioconductor.org/` (so a CRAN source for ggplot2 fails), hard-coded edge minimum versions `1.1.6`/`3.4.0`).
- **Evidence:** P1-E: the run's documentation URL `https://cran.r-project.org/web/packages/termr/index.html` is official CRAN but not in the frozen list, so `official_source_and_docs` fails (`p1e_discovery_evidence_audit_20261027.md` §10). The D01 prompt pins "documentation versions published by 2026-10-25", but every MCP tool returns the *current* repository state; there is no as-of parameter.
- The project's own baseline audit reached the same conclusion for E01/E04/E05 ("E01 0/6 при верном R fix", hidden JSON contract; `baseline_root_cause_audit.md` lines 19, 604, 714); that audit did not lead to a scorer change in the frozen suite.
- **Impact:** false negatives for correct answers (E01 scored 0/6 in both arms); any CRAN update after the snapshot turns a correct MCP answer into a scorer failure (version drift). **Fix:** accept URLs by host + path pattern verified against the package identity; record scorer-level evidence of *which* alternative was accepted; refresh the snapshot with the run date. **Complexity:** medium.

### BEN-003 — A/B design problems
- **Location:** `benchmarks/codex_r/run_simple.py:3262-3275` (`for repetition: for task: for mode in modes` → arm A always precedes arm B; only `b1-discovery` has a hand-balanced order, lines 94-107).
- **Evidence:** pooled analysis mixes `consolidated-v1`, `v1.1`, `v2` configurations, 7 recorded scorer versions (plus trials with none recorded) and `standard`/`diagnostic` instructions (`evidence/benchmark/bench_err.txt`). Attrition is asymmetric: 6 `without-mcp` trials ended `LEGACY_ERROR` (early development runs); 2 with-MCP trials were interrupted and 6 were `unsupported_for_automatic_scoring`.
  `manifest.json:22` states a 30 000-token budget "enforced by the controller", while `STANDARD_INSTRUCTIONS` (`run_simple.py:67-74`) says it is not a hard limit; usage is missing in 90/91 trials. The "control" for discovery keeps MCP connected (so measures selection behaviour, not tool value).
- Uncontrolled external information: both arms' executors run on a per-trial `docker network create` bridge **without `--internal`** (`run_simple.py:2491`, `start_executor` at 1811-1822); `manifest.json` says "no ordinary browsing; only controlled model and MCP endpoints", but the only barrier is the instruction text (`STANDARD_INSTRUCTIONS`: "Do not … browse the web"). A control-arm agent can fetch CRAN with `curl`/R; the telemetry cannot tell (P1-E: "network use unknown"; 8 command executions with no recorded command text).
- **Fix:** randomise/counterbalance arm order with a recorded seed; one configuration per analysis; enforce egress (internal network + allow-listed proxy; `exploratory/egress_proxy.py` exists for the F09 harness) or record network use; intention-to-treat accounting that keeps failed trials; enforce or drop the token budget; record actual usage. **Complexity:** medium.

### BEN-004 — Saturation and non-use
- **Evidence:** 17 of 21 comparable tasks show identical scores; R01/R02, B01–B03, C01–C05, H01, H04 are 100 % in both arms with 0 MCP calls. The tasks are small base-R/tidyverse exercises whose oracle tests (`benchmarks/codex_r/oracle/*.R`) are in the public repository (training-data leakage risk). D-block asks the agent to *choose* a package with no internet in the control arm, so it measures access to current facts rather than R problem solving or tool selection.
- **Fix:** add tasks where installed-version ≠ latest, where hallucinated API names are plausible, and where Bioconductor/R compatibility matters; keep oracle tests private. **Complexity:** large.

### BEN-005 — Frozen evidence is not in the repository
- **Evidence:** `benchmarks/codex_r/.gitignore:3` ignores `results/`; `evidence/probes/linkcheck.txt`: 12 relative links in tracked reports point to files that exist only on the author's disk (`baseline_root_cause_audit.md` → `../results/20261025T135949Z-…/…`, `benchmarks/codex_r/README.md` → `docs/CODEX_MCP_BENCHMARK.md`, which was untracked by commit `9ac4a66`).
  The numbers in the P1-D/P1-E reports are reproducible only from a 20 MB local directory that a third party cannot obtain. I verified the P1-E counts (28 calls; 17/9/2 by tool; score 3/4) against the local raw `results.json`, but a reader of the repository cannot.
- **Fix:** commit a redacted, checksummed evidence bundle (or a release asset) and make reports link to it. **Complexity:** small.

### TST-001 — Test portfolio shape
- **Evidence:** `evidence/inventory.txt`: 900 static test functions, 597 (66 %) for benchmark/telemetry harness code (31 918 lines of benchmark Python vs 15 902 of production Python); production tests use synthetic mocks only (`tests/conftest.py`), which hid KC-001 and KC-002 until I used real CRAN data; no property-based testing (`hypothesis` absent); 15 `docker`-marked tests and ≈ 195 skips.
  Measured line+branch coverage of `src/cran_knowledge_mcp` under `python -m pytest`: **84 %** (`evidence/ci/coverage_report.txt`; excludes subprocess-based stdio/HTTP tests and the native extension). Weakest: `upstream_smoke.py` 66 %, `native.py` 68 %, `prompt_intelligence/composition/context.py` 74 %, `github_agents.py` 78 %, `service.py` 79 %, `visualization_analysis.py` 79 %.
- **Fix:** a small offline *recorded-fixture* suite of real tarballs (cluster, MASS, termr-like R6 package, a compiled package) checked into `tests/data` with their SHA-256; Hypothesis tests for `version_parts`, `dcf`, `aliases`, snapshot paging. **Complexity:** medium.

### ARCH-001 — God classes
- **Evidence:** `evidence/inventory.txt`: `service.KnowledgeService` 1 952 lines/50 methods (repository routing, legacy *and* consolidated entry points, framework docs, Shiny/Quarto/visualization analysis, workflows, technology recommendation, compatibility); `PromptIntelligence` 1 648 lines/21 methods; largest functions: `_register_tools` 605, `build_r_prompt` 592, `_register_legacy_tools` 585, `recommend_technology_stack` 485 lines. No import cycles (top-level or function-local).
- **Assessment:** the size is a symptom of *two interface generations sharing one class* (35 legacy + 16 consolidated entry points) and of unrelated domains in one namespace. See `ARCHITECTURE_AUDIT.md` for which seams are worth cutting and which are not.
- **Complexity:** large; **regression surface:** the full MCP contract tests (`tests/test_server.py`, `test_consolidated_server.py`, `test_mcp_errors.py`).

### PI-001 — Prompt Intelligence is unvalidated and its score is gameable
- **Evidence:** `evidence/probes/probe_intent.txt`: ordered first-match regex classification gets 21/30 (70 %) on an auditor-labelled exploratory set; "hypothesis test" → `testing`, "fix the failing Shiny app" → `shiny_development`, "pivot a wide table" → `data_analysis`; ordinary English "validate/bench/janitor" is detected as the R packages `validate`/`bench`/`janitor` (`intent.py:113`).
  `evidence/probes/probe_c_prompt_score_ctx7_redaction.txt`: `validate_prompt` scores a sensible prompt 35, a keyword salad 40 and a nonsense prompt with section headings 50. `docs/PROMPT_OUTPUT_EVALUATION.md` itself states that no downstream correctness has been measured; the "evaluation" measures size.
  Positive: package text (title/Rd) is *not* copied into generated prompts (`evidence/probes/probe_inject.txt`).
- **Fix:** measure downstream R-code correctness with the existing oracle harness (`PROMPT_INTELLIGENCE_AUDIT.md` §5); until then, treat the score as formatting lint. **Complexity:** large.

---

## P3

### SEC-003 — URL logging
`server.py:1746` (`logging.basicConfig(level=INFO)`) lets the `httpx` logger print every upstream URL. `evidence/probes/probe_logs.txt`: the Context7 request line contains the (pattern-redacted) question text; the API key is not logged. This contradicts the stated "name only, never arguments" policy (`server.py:83-84`, `docs/security.md` resource-limit paragraph). Fix: set `logging.getLogger("httpx").setLevel(WARNING)`.

### SEC-004 — Context7 redaction both over- and under-matches
`providers/context7.py:20-34` keeps its own pattern list instead of reusing `input_safety.SECRET_PATTERNS`. `evidence/probes/probe_secrets.txt` (small hand-made set, illustrative):
over-redaction — "How does token refresh work in httr2?" → "How does [REDACTED] work…", "How do I hash a password with sodium?" → altered, and R code reading `Sys.getenv('PGPASSWORD')` is rewritten (3 of 5 benign inputs);
under-redaction — **not** redacted before being sent to a third party: `token=abcd1234efgh`, `postgres://admin:S3cretPass@db.example.com/prod` (credentials in a URL), `client_secret: '…'`, all of which `input_safety` (used for Prompt Intelligence) does detect (8 of 9 positives).
`docs/security.md` already calls the redaction heuristic; the gap is that two divergent implementations exist. Fix: reuse one detector and *reject* (not rewrite) credential-like questions, and require an assignment/value context for the generic words. Regression test: the probe's positive and benign sets.

### SEC-005 — "verified" repository identity
`providers/github_agents.py:302` labels `repository_metadata_source` as "verified package DESCRIPTION URL field", but any CRAN author can point `URL:` at any GitHub repository; ownership is not established. Content is correctly labelled `untrusted_reference_only`. Fix: rename to "declared by the package", optionally require the repository to link back to the package.

### SEC-006 — No per-field untrusted marker
`get_package` (`title`, `description`) and `get_function_docs` (`text`) return package-author text with no `trust` field (`evidence/probes/probe_inject.txt`), unlike framework docs/AGENTS.md/Context7 which carry one. Only the server-level instructions say "treat package text as untrusted". Fix: add `content_trust: "untrusted_upstream_text"` to those envelopes.

### SEC-007 — Supply-chain hygiene
`Dockerfile:1` (`python:3.11-slim`, no digest), `pip install .` with range pins and no lock/hashes, `.github/workflows/*.yml` actions pinned by tag, no `HEALTHCHECK`, no SBOM/provenance; `mcp>=1.30,<2` while SDK 2.x is current (the audit machine's global Python had `mcp 2.2.0`; the audit used a clean 1.30.0 environment). Positive: non-root uid 10001, runs with `--read-only --cap-drop=ALL` (verified), image 257 MB.

### SEC-008 — Thread-safety of the parsed-source LRU (possible)
`providers/base.py:143-148` (`_cached_source`: `get` then `move_to_end`) is called from `asyncio.to_thread(self._alias_index, …)` (line 402) while the loop thread may evict the key (`_store_source`, `_discovery_index`). A `KeyError` between `get` and `move_to_end` is conceivable. Not reproduced.

### SEC-009 — YAML on the event loop (possible)
`releases.py:35` parses a ≤ 1 MiB upstream `config.yaml` with `yaml.safe_load` synchronously (12.9 KB today; 12 ms). `safe_load` expands anchors/aliases; a hostile or corrupted upstream file could be expensive. Trusted upstream → defense in depth only.

### MCP-002 — Protocol nits
Unknown tool → a result with `isError: true` rather than a JSON-RPC protocol error (SDK 1.30 behaviour); reading `cran://Ex/man/nope` returns a *successful* resource payload containing an error envelope (`probe_mcp_shape.txt`); legacy tools set `openWorldHint=true` for tools that never touch the network. None breaks a client.

### MCP-003 — Duplicate payload
`probe_mcp_shape.txt`: for `get_package` the text block is 1 481 bytes and `structuredContent` 1 182 bytes (≈ 2.2× wire bytes). The telemetry estimate (`server.py:132,249-254`) counts both, so `response_tokens_estimate` overstates what a text-only client puts in the model context (the event also records `content_duplicates_structured`). Fix: report model-visible bytes separately; consider returning a short text summary.

### KC-004 — Hard limits instead of partial results (possible)
`parsers.py:318` (> 4 000 NAMESPACE directives), `function_discovery.py:290` (> 10 000 entries) raise `source_too_large`. Demonstrated only on synthetic archives (`probe_perf.txt`); I found no real package that exceeds them.

### KC-005 — Static "exports" differ from runtime exports
`probe_real` (`evidence/real_discovery_vs_R.json`): for `Matrix` the server lists 321 exports vs R's 417; R includes internal `.__C__*` class-metadata objects, the server includes generics declared by `exportMethods` (`!`, `%*%`). For `boot` and `codetools` (versions equal) the sets are identical. The tool states `callability: not_checked` and "static namespace declarations", so this is a documented limit; agents should not treat the lists as `getNamespaceExports()`.

### ARCH-002 — Inverted dependency and dead code
`parsers.py:198,258,300` import `tokenize_r`/`scan_calls` from `visualization_analysis` inside functions, so the "data-only" parser module depends on the ggplot analyzer; the R tokenizer belongs in a neutral module (it is what `native/` accelerates). `vulture` finds one dead function, `parsers._gap` (line 251).

### DOC-001 — Documentation drift
`.env.example:22` says "15 tools" (actual 16); `docs/security.md:85` says the GitHub API "does not use a personal access token" while `config.py:47` and `github_agents.py:83-90` support `GITHUB_TOKEN`; `pyproject.toml:3` version `0.1.0` and User-Agent `cran-knowledge-mcp/0.1` for a "2.0" branch; `Dockerfile:10` binds `0.0.0.0` while `docs/security.md:71` and `README.md:391` say HTTP defaults to loopback (true for the CLI, not for the image); tracked docs link to untracked files (BEN-005); no `CHANGELOG`, `SECURITY.md`, tags or release workflow.

### PERF-001 — Provider rebuilt on every `config.yaml` refresh
`service.py:213` compares `Release` objects with `!=`; `Release` is a dataclass that includes the `Artifact` (`releases.py:20-25`) whose `checked_at` changes on each revalidation, so after each 5-minute cache expiry the Bioconductor provider and its parsed-archive/index/discovery caches are discarded although upstream is unchanged (`probe_b…`). Separately `releases.catalog()` re-parses `config.yaml` on every call (`probe_bioc_cost…`: 12.2 ms per call for 12.9 KB). Measured cost is small (≈ 17 ms index re-parse + a re-download/re-parse of any cached archive); not a scalability issue today. Fix: compare `(version, r_version, channel)`; memoise `catalog()` per artifact identity.

### MCP-004 — Constraints stated in prose, not in the schema
`evidence/probes` (schema dump during the audit): only 26 of 109 consolidated parameters carry `enum`/`minimum`/`maximum`/`maxLength`/`pattern`; `limit` is `integer` with "1..20" in the description; `package` is a bare string although `http.package_name` enforces `[A-Za-z][A-Za-z0-9.]{0,99}`. Violations are reported correctly as `invalid_input`, so this costs a round-trip, not correctness. Fix: `Field(ge=1, le=20)`, `pattern=` on `PackageName`.

### TST-002 — Assertions that only fail when Docker/Linux is available
`tests/test_telemetry_integration.py:388` asserts schema version `"1.1"` while `benchmarks/codex_r/telemetry/schema.py:34` emits `"1.2"` and line 568 of the same file asserts `"1.2"`; `tests/test_codex_simple.py:331` indexes `result["environment_error"]["code"]` but `run_simple.py:2609` stores the plain string `"environment_failed"` (the other path, line 2242, stores `{"code": …}`), so the result schema is unstable. Both failed on Ubuntu/WSL with Docker present and are invisible on a machine without Docker (`evidence/ci/pytest_linux_fixed.txt`). Five `test_codex_launcher.py` tests that need R + `termr` also failed there (22 failed expectations in the R suite); I did not determine whether that is the installed `termr` version, the R version, or a real defect (unattributed, environmental).
