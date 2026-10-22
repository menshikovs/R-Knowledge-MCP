# Architecture, security and quality audit

Date: 2026-10-22  
Audited base: `c17e9b5` (`feat/visualization-reporting-intelligence`)  
Audit branch: `audit/security-quality-hardening`

## Executive summary

The repository has a modular, source-attributed read-only design for CRAN,
Bioconductor, GitHub AGENTS.md, Context7, and the Shiny/Positron/Quarto and
visualization analysis tools. Official package identity is tied to repository
indices and selected releases; external GitHub and Context7 material is treated
as untrusted reference content. The audit confirmed three concrete reliability
defects and fixed them with regression tests: unhandled exceptions escaping the
tool response boundary, recursive/invalid Unicode input breaking static project
analysis, and a process-wide download lock serializing unrelated repository
requests.

No code executes R, package scripts, examples, or AGENTS.md commands. Repository
transport uses fixed HTTPS hosts and routes, rejects redirects, avoids proxy
environment variables, and applies response, cache and timeout bounds. This
does not make the Docker HTTP endpoint safe to expose publicly: it binds to
`0.0.0.0` without authentication or per-client rate limiting. Public deployment
is therefore a release blocker pending an authenticated/rate-limited edge.

## Scope and method

Reviewed the checked-out history and branch relationships, package metadata,
provider/service/server/transport code, analyzers, external integrations,
tests, README and architecture docs, GitHub Actions, Dockerfile, and dependency
configuration. Existing behavior was tested before changes and again after the
fixes. No production service was contacted or deployed; automated tests use
synthetic HTTP responses. Official live-source behavior, full Python 3.11–3.14
CI, a wheel build, Docker build, and stdio subprocess interoperability could
not all be established in this restricted Windows environment; see verification
below.

## Baseline and verification

| Check | Before audit changes | After changes |
| --- | --- | --- |
| pytest, offline suite | 139 passed; 2 environment-restricted tests deselected | 145 passed; same 2 deselected |
| Ruff lint | passed | passed |
| Ruff format check | passed | passed |
| MCP in-process Streamable HTTP | covered by existing SDK integration test | covered by passing suite |
| MCP stdio subprocess | blocked by Windows sandbox named-pipe/process restriction | not rerun; unchanged code path |
| Docker daemon/build | Docker CLI exists; engine pipe access denied | not buildable in this environment |
| Python package wheel | not established | blocked: pip could not create its build-tracker temp directory |
| CLI argument parsing | package import initially needed `PYTHONPATH=src` | `python -m cran_knowledge_mcp.server --help` succeeds with `PYTHONPATH=src` |
| dependency consistency | `pip check`: no broken requirements | no dependency changes |
| GitHub CI | no run/status available for audited base commit | CI not run from this workstation |

The two deselected tests are `test_stdio_subprocess_initialize_and_error` and
`test_no_path_extraction`. The former needs a subprocess stdio transport; the
latter uses pytest's temporary-directory fixture. Attempts to run them in this
environment failed on OS sandbox permissions, not on assertions. `pytest` from
the global interpreter also cannot import `httpx`; the project `.venv` has the
declared runtime/test dependencies and was used for the passing runs. Python
3.14.4, MCP SDK 1.30.0, httpx 0.28.1, PyYAML 6.0.3, pytest 9.1.1 and Ruff 0.17.1
were available. No separate type checker or dependency vulnerability scanner
was configured or installed.

## Findings

### AUD-01 — P2: unexpected provider failures escaped the MCP error envelope — fixed

`bounded()` handled expected source/input errors and timeouts, but an unexpected
exception could propagate through the MCP handler and become an opaque transport
failure. It now catches ordinary `Exception`, logs only the exception class,
and returns a stable `internal_error` envelope without exposing exception text.
Unicode and recursion failures receive explicit safe error codes. Regression
tests verify both the generic failure and that private exception details are not
returned.

**Impact:** callers receive the documented failure shape for unexpected internal
faults, while server logs retain a small diagnostic signal. Cancellation and
other `BaseException` control flow are not swallowed.

### AUD-02 — P2: unrelated repository downloads serialized behind one lock — fixed

`RepositoryHTTP.fetch()` previously held one async lock across cache lookup and
the network request. A slow CRAN fetch therefore blocked unrelated Bioconductor
routes on the same provider instance despite the HTTP connection pool allowing
multiple connections. The implementation now uses a short-lived cache lock,
per-path single-flight locks for duplicate requests, and a bounded four-request
semaphore. Tests prove duplicate misses still coalesce and independent routes
can download concurrently.

**Impact:** unrelated source lookups no longer queue behind a single slow route;
duplicate requests continue to avoid redundant downloads. The process remains
bounded by the configured HTTP connection pool.

### AUD-03 — P2: adversarial or malformed text could escape static analyzers — fixed

Some input-size checks encoded strings before converting encoding errors to a
tool error, and deeply nested YAML could raise `RecursionError` during
normalization. Shiny file manifests also called `.endswith()` before validating
that a path key was text. These paths now validate Unicode/byte limits and
shapes before parsing, and deep YAML returns a finding rather than crashing.
`renv.lock` summary extraction ignores non-string or overlong version values so
arbitrary nested JSON values are not echoed as package versions. Regression
tests cover invalid Unicode, deeply nested YAML, malformed manifest keys, and
malformed version values.

**Impact:** malformed input fails explicitly and boundedly without claiming
invented package metadata or crashing the tool handler.

### AUD-04 — P1: container HTTP mode has no client authentication or request quota — open deployment blocker

The Dockerfile starts Streamable HTTP bound to `0.0.0.0`. MCP transport security
protects host/origin handling, but does not authenticate callers or impose
per-client quotas. If an operator publishes the container port directly, any
reachable caller can consume upstream API/network capacity. This audit does not
add an authentication system or deploy the service. Before public exposure, put
the endpoint behind authenticated access control and request/rate limits (and
TLS), or add and test server-side auth and abuse controls. Keep the service
undeployed until this is addressed.

### AUD-05 — P2: packaging and container release checks are not locally verified — open verification gap

The source CLI and tests work, but a wheel build could not start because pip was
unable to create a temporary build-tracker directory outside the writable
workspace. Docker engine access was denied through the Desktop named pipe. CI
workflow configuration contains lint, format, test, and Docker jobs on Python
3.11–3.14, but no run/status was available for the audited commit. Run those
checks in GitHub Actions before release, especially the wheel/install and Docker
paths. Do not infer a successful package/container build from source tests.

## Architecture and security assessment

- `PackageRepository` is a structural provider contract; CRAN and Bioconductor
  route through fixed independent source policies. New providers can be
  registered without making user input an arbitrary URL.
- Bioconductor release identity is resolved from the official dynamic config;
  package category and release are kept in identity/provenance. Cross-repository
  dependency resolution reports ambiguity/unavailability rather than guessing.
- The MCP surface uses the official Python SDK 1.x FastMCP API and supports
  stdio and Streamable HTTP. The dependency upper bound `<2` is intentional
  because SDK 2 changed the server API; upgrade requires explicit compatibility
  work and protocol tests.
- HTTP clients disable environment proxies and redirects. Repository requests
  use validated fixed host/path combinations, response byte caps, timeouts,
  bounded caches and no stale-on-error fallback. Archive members are read in
  memory and validated; they are not extracted and no package code is executed.
- GitHub AGENTS.md retrieval starts from checked package metadata, resolves an
  explicit revision to a commit SHA, and returns path scopes as untrusted
  reference text. It does not execute or adopt those instructions.
- Context7 is optional, sends its key only in a header, redacts common secret
  patterns in questions, and requires an exact library/repository match.
  Context7 remains secondary to official package data. Its API guide currently
  documents the v2 search/context endpoints used here, as well as a newer v3
  search path; this implementation uses documented v2 routes.
- Analysis tools operate on caller-provided bounded text and do not read
  server-side project paths or evaluate R/Quarto code. `renv.lock` versions are
  client-supplied metadata, not evidence of installed versions.
- Failures retain explicit status/source details. Aggregate operations can
  return partial results; consumers need to inspect each result's verification
  status and error list.
- Public availability still needs operational controls noted in AUD-04.
  DNS-rebinding protections are not identity/authentication controls.

## Maintainability and future debt

`service.py` and `server.py` register many tools and have grown substantially.
Current separation between providers, source transport, analyzers and MCP
registration remains understandable, but service orchestration is the main
change-risk area. Prefer a follow-up extraction by domain (package knowledge,
framework docs, project analysis) with contract tests rather than broad
rewrites. Avoid expanding supported APIs without source fixtures, provenance
tests and explicit “unknown/unavailable” behavior.

## Remediation and release criteria

1. Keep fixes AUD-01–03 and their regression tests.
2. Before public deployment, add authenticated ingress plus abuse/rate controls
   and TLS; test unauthorized requests and quota enforcement.
3. Require a green GitHub Actions run on the audit commit, including Python
   3.11–3.14 and Docker build/run checks.
4. Add a reproducible package build/install check to CI if wheel publication is
   intended. Consider a dependency audit job and type checking as separate CI
   improvements.
5. Preserve provider boundaries and source/checked-time provenance in future
   integrations; never treat external instructions or indexed snippets as
   executable authority.

## Conclusion

The audited code is suitable for continued local development and review. The
three confirmed correctness/reliability defects are fixed and covered by
regressions. Tests, lint and formatting pass within the available environment.
The Docker HTTP endpoint is not ready for unauthenticated public exposure, and
package/container release checks remain unverified until CI or a Docker-enabled
build environment completes them.
