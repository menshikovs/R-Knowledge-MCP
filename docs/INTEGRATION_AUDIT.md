# Integration audit and stabilization

Audit date: 2026-10-22  
Repository: `menshikovs/R-Knowledge-MCP`  
Integration base: `main` at `4a0c139` (PR #1 merge)  
Stabilization branch: `integration/stabilize-r-knowledge-mcp`

## Repository state

GitHub reports `main` as the default branch. The first eight development stages
and the later Composable Prompt Engine are present in the merged history of PR
[#1](https://github.com/menshikovs/R-Knowledge-MCP/pull/1), whose head was
`feat/composable-prompt-engine` (`a4a74d0`). The merge commit is `4a0c139`.
The feature branch is an ancestor of `main`; the 13 commits from the original
CRAN foundation through the Composable Prompt Engine were merged once. The
original feature branches remain available and were not rewritten. No open PRs
were returned by the repository PR listing. PR #1 was verified separately as
closed and merged.

The locally cached feature refs were refreshed with `git fetch --all --prune`.
The stabilization branch is based directly on the fetched `origin/main`, so its
review will contain only the fixes and audit documentation in this change.

## Architecture and evidence

The checked implementation has a FastMCP adapter in `server.py`, an orchestration
and result-envelope layer in `KnowledgeService`, independent CRAN and
Bioconductor providers behind `PackageRepository`, fixed-route asynchronous
HTTP clients and bounded caches, separate GitHub AGENTS.md and Context7
providers, static Shiny/Positron/Quarto and visualization analyzers, and a
deterministic Prompt Intelligence layer. Providers and tools retain source,
package/release identity, check times and partial failures. Static analyzers do
not read server paths or execute R, SQL, Quarto, package code or external
AGENTS.md instructions.

The audit also inspected the template registry and composition engine. Tests
exercise the ten CSV/SQL templates and named SQL dialect handling, workflow
decomposition, dependency plans, conflict reporting, deterministic output,
source grounding, output limits and failure behavior. The composable engine is
already implemented in the current merged history; this stabilization change
does not reimplement or expand it.

## Findings and remediation

### INT-01 — P1 — Public HTTP exposure lacks application authentication and client quotas — open blocker

**Evidence:** `create_http_app()` serves stateless Streamable HTTP, and the
container starts the listener on `0.0.0.0`. The SDK's Host and DNS-rebinding
checks do not authenticate a client or impose per-client quotas. Existing
security documentation correctly identifies this gap.

**Impact and root cause:** a directly reachable endpoint can be used by
unauthenticated callers and can drive upstream work. The application has no
identity or per-client abuse-control layer.

**Disposition:** public deployment remains blocked. This audit does not deploy
the service or introduce a partial authentication scheme that could be
misconfigured as complete protection. Internet-facing operation requires TLS,
authenticated ingress, request/body/concurrency and per-client rate limits, and
restricted egress. Do not expose the container port directly. DNS-rebinding
protection is not an authentication control.

### INT-02 — P2 — Public product name differed from repository name — fixed

**Evidence:** the GitHub project is `R-Knowledge-MCP`, while MCP discovery,
CLI help and the README called the product “CRAN Knowledge MCP”.

**Fix:** public title and help now say “R Knowledge MCP”; README, Codex examples
and Docker examples use `r-knowledge-mcp`. The existing Python import path,
distribution name and `cran-knowledge-mcp` executable remain available for
backward compatibility. Docker now invokes the new alias. The Streamable HTTP
test asserts the public MCP server name.

### INT-03 — P2 — CI did not verify wheel installation and installed CLI — fixed in workflow

**Evidence:** the existing workflow ran lint, formatting, pytest and Docker,
but did not build/install a wheel or invoke an installed console script.

**Fix:** the Python matrix now builds and installs the wheel and runs
`r-knowledge-mcp --help`. The Docker job uses the same public image/command name.
The workflow retains read-only repository permissions and has no live API
dependency in its test suite.

No additional P0/P1 code defects were confirmed by the reviewed source and
regression tests. The public HTTP deployment blocker remains the only open P1
found in this audit.

## Test baseline

The full local baseline on Python 3.14.4 and MCP SDK 1.30.0 was:

```text
188 passed, 1 failed, 1 error
```

Both non-passing cases hit Windows sandbox restrictions before their assertions:
the stdio subprocess test cannot create a named pipe, and the path-safety test
cannot create pytest's temporary directory. Running the suite without the
stdio subprocess case still encounters the same temporary-directory permission
error. These are environment limits, not recorded as passing tests.

## Final validation

Commands and observed results before the final report commit:

| Check | Result |
| --- | --- |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 69 Python files |
| `pytest` baseline | 188 passed; 1 sandbox-blocked failure and 1 sandbox-blocked setup error |
| `pytest -q -p no:cacheprovider -k 'not stdio_subprocess_initialize_and_error and not test_no_path_extraction'` | Passed; 188 passed, 2 environment-restricted tests deselected |
| MCP in-process client | Existing tests cover complete tool discovery, prompt discovery/get, tool calls and Streamable HTTP `/mcp` initialization and calls |
| Python wheel build | `python -m pip wheel . --no-deps --wheel-dir dist` passed; produced `cran_knowledge_mcp-0.1.0-py3-none-any.whl` |
| Wheel installation and new CLI alias | GitHub Actions on `cc07cb2` passed wheel build/install and installed CLI startup; wheel metadata confirms both old and new console scripts. Local CLI execution from the installed wheel was unavailable because the project venv has no pip and the global interpreter does not have project dependencies installed |
| Docker | Local Docker Engine unavailable; latest GitHub Actions run on merge commit `4a0c139` completed successfully, including the Docker job |
| stdio subprocess | Blocked locally by Windows named-pipe permissions; exercised by CI suite |
| MCP SDK | `mcp>=1.30,<2`; installed local test SDK was 1.30.0 |

The latest observed GitHub Actions run on `main` was
[successful](https://github.com/menshikovs/R-Knowledge-MCP/actions/runs/39787235698).
The stabilization branch run on `cc07cb2` also
[passed](https://github.com/menshikovs/R-Knowledge-MCP/actions/runs/39787934182),
including the new wheel installation and CLI smoke steps. The feature branch's
run was also successful. The workflow matrix declares Python 3.11, 3.12, 3.13
and 3.14.

## Security and release readiness

Outbound requests use fixed HTTPS hosts and route allowlists, reject redirects,
disable environment proxy use, and apply time, byte, concurrency and cache
bounds. GitHub repository identity is derived from verified package metadata;
AGENTS.md content is commit-pinned, scoped and untrusted. Context7 is optional,
requires a server key, redacts common secret patterns and remains secondary to
official package sources. User-supplied code, schemas and prompts are bounded
data and are not executed or sent to external documentation providers by static
analysis.

Readiness:

- Continued development and review: ready.
- Local installation: source and wheel build are supported; CI now verifies
  wheel installation and CLI startup.
- Private controlled deployment: only behind separately configured TLS,
  authentication, quotas and egress controls; those controls are not provided by
  the application itself.
- Direct public deployment: blocked until authenticated ingress and abuse
  controls are in place and tested.

## Pull request plan

PR #1 already consolidated the historical feature chain into `main`; creating
the original stacked PRs now would duplicate merged changes. This branch is a
focused stabilization follow-up targeting `main`:

- Title: `chore: stabilize R Knowledge MCP integration`
- Base: `main`
- Head: `integration/stabilize-r-knowledge-mcp`
- Compare URL: <https://github.com/menshikovs/R-Knowledge-MCP/compare/main...integration/stabilize-r-knowledge-mcp?expand=1>

Suggested description:

> Align the user-facing server identity with R Knowledge MCP while preserving
> the legacy CLI and import names. Add wheel installation and CLI startup checks
> to CI, and document the verified branch integration, validation evidence and
> remaining public HTTP deployment blocker. No deployment or merge is included.

Do not merge this branch automatically. Review the CI run and public deployment
blocker before release. The Composable Prompt Engine is already in PR #1 and
does not need a separate replay into `main`.
