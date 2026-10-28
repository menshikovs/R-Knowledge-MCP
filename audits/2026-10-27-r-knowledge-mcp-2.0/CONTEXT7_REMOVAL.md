# Context7 integration removal (R-Knowledge-MCP 2.0)

Intentional simplification requested separately from Stage 0: Context7 is no longer part of the
project's core value (verified, source-attributed R package facts). Implemented in the same working
tree as Stage 0 (see `STAGE0_REMEDIATION.md`); nothing is committed or pushed.

## 1. Dependency map before removal (tracked files, audit evidence excluded)

| Layer | Reference | Role |
|---|---|---|
| Provider | `src/cran_knowledge_mcp/providers/context7.py` (266 lines) | Context7 HTTP client, exact-repository matching, question redaction, 6 h cache |
| Provider exports | `providers/__init__.py` | `Context7Provider` |
| Service | `service.py` | `context7_provider` constructor argument and `self.context7`; `get_context7_docs()`; `context7` section of `get_package()` (`PACKAGE_SECTIONS`, `question` parameter and its validation rules); `context7_docs` section of legacy `get_package_knowledge()` |
| Server | `server.py` | legacy tool `get_context7_docs`; legacy `get_package_knowledge(question=…)`; consolidated `get_package(include=[…"context7"], question=…)` |
| Configuration | `config.py` `context7_api_key()`, env `CONTEXT7_API_KEY`, `.env.example` | server-side key |
| Server instructions | `mcp_discovery.py` `CONTROL_SERVER_DESCRIPTION` | advertised "Context7 data" and "Context7 snippets" |
| Packaging text | `pyproject.toml` description; `http.py` comment | wording |
| Tests | `tests/test_external_knowledge.py` (4 Context7 tests + fixture), `test_mcp_errors.py` (2), `test_config.py` (1), `test_server.py` (tool list), `test_consolidated_server.py` (parameter rule, tool count) | |
| Docs | `README.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/security.md`, `docs/sources.md`, `docs/UPSTREAM_MONITORING.md` | |
| Not changed (frozen/historical) | `benchmarks/codex_r/manifest.json` (hash list of production sources at the evaluated commit, incl. `providers/context7.py`), `benchmarks/codex_r/reports/*`, `benchmarks/codex_r/README.md`, `measurement_hardening_v2.md`, `telemetry/README.md`, `docs/PULL_REQUEST.md`, and all `audits/` evidence | historical records; they describe past behaviour |

Network: the only code that contacted Context7 was `providers/context7.py` (fixed host `context7.com`).
The benchmark gateway comparison of production-source hashes (`runner/gateway.py`) already differed from
the evaluated commit before this change (e.g. `server.py`), so removing a hashed file does not newly
break it.

## 2. Public API impact

| Surface | Change | Justification |
|---|---|---|
| Legacy toolset | `get_context7_docs` removed (35 → **34** tools) | its only purpose was Context7 |
| Legacy `get_package_knowledge` | `question` parameter and `context7_docs` section removed | only used for Context7 |
| Consolidated `get_package` | `include` no longer accepts `"context7"` (schema enum) and the `question` parameter is removed | only used for Context7; a stale `include=["context7"]` is rejected as `invalid_input` |
| Consolidated toolset | otherwise unchanged: still 16 tools, same names, same annotations, same other parameters | |
| Resources / prompts | unchanged (2 resources, 3 templates, 14 prompts) | |
| Server `instructions` text | no longer mentions Context7 | accuracy; control description therefore differs from the pre-B1 string in that clause only |
| Config | `CONTEXT7_API_KEY` is no longer read (ignored) | |
| Python API | `KnowledgeService(context7_provider=…)`, `Context7Provider`, `config.context7_api_key` removed | |

Stage 0.5 update: originally a stale `question` was silently ignored by the SDK. `get_package` and
`get_package_knowledge` now reject any unknown argument (`invalid_input`, schema `additionalProperties:
false`); see `STAGE05_VERIFICATION.md`. A stale `include=["context7"]` is rejected as before.

## 3. Capabilities preserved (verified)
CRAN/Bioconductor discovery, Function Discovery, official Rd docs, version/compatibility checks, R manuals,
framework docs, static analysis, resources, prompts, stdio and Streamable HTTP. Evidence: full test suite
passes after the removal (Windows, Python 3.14: **1426 passed, 186 skipped, 0 failed**,
`stage0-evidence/after_context7_full_pytest.txt`); an installed-wheel stdio session (protocol versions,
16 tools, resources, prompts, ping, error semantics) and an HTTP probe match the audited baseline
(`wheel_cli_stdio_check.txt`, `http_transport_check.txt`); the built wheel and Docker image contain no
`providers.context7` module (`docker_check.txt`). No substitute service was added; no fallback content is
presented as verified.

## 4. Regression tests
`test_mcp_errors.py::test_context7_tool_and_section_are_removed_and_never_contacted` (tool absent, call →
`tool_not_found`, no `context7_docs` section, service has no `context7` attribute, no request URL mentions
Context7); `test_consolidated_server.py::test_get_package_rejects_section_arguments_that_would_be_ignored`
(now also rejects `include=["context7"]`); legacy tool count 34; partial-failure behaviour re-covered for
the remaining AGENTS.md section (`test_partial_agent_guidance_failure_does_not_fail_overall_tool`).

## 5. Remaining references
`grep -ri context7` over tracked files outside `audits/`: only the regression tests above, one code
comment in `mcp_discovery.py`, the "removed" notes in `README.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, and
the frozen/historical benchmark files listed in §1. No active code path can contact Context7.
