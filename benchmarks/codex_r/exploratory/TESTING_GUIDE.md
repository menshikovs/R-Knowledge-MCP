# R01-A Offline Benchmark Testing Guide

This suite checks the local benchmark protocol with synthetic records, fake
HTTP transports, injected command runners, and temporary state. It does not
authorize or execute a real R01-A attempt. Keep the live gate closed.

## Coverage map

| Area | Main tests | Key invariant |
| --- | --- | --- |
| Authorization and spend | `test_codex_single_trial_adapter.py`, `test_codex_managed_agents_lifecycle.py`, `test_codex_managed_agents.py` | Attempt-bound approval and positive integer cents are checked before session transport; closed historical attempts stay closed. |
| API contract and ambiguity | `test_codex_managed_agents.py`, `test_codex_executor_contract_integration.py` | Fixed routes, bounded responses, safe diagnostics, one create attempt, and uncertainty after ambiguous outcomes. |
| Lifecycle and durability | `test_codex_managed_agents_lifecycle.py`, `test_codex_lifecycle_durability.py` | Side effects follow durable intent; deadlines, cleanup, audit, and lease outcomes fail closed. |
| Docker boundary construction | `test_codex_docker_runtime.py`, `test_codex_benchmark.py`, `test_codex_controller.py` | Synthetic command assertions cover isolation flags, public workspace contents, scoring records, and cleanup commands without launching Docker. |
| Restricted egress | `test_codex_egress_proxy.py` | Loopback proxy behavior is synthetic; upstream name resolution and tunnel destinations are injected. |
| External-action tripwire | `test_codex_offline_tripwire.py` | The shared test guard rejects external socket targets and live commands while permitting a synthetic Python child. |

## Coverage gaps

| Gap | Current evidence | Limit |
| --- | --- | --- |
| OpenAI TLS/WSS registration, provider timeouts, billing, and credential identity | Fake HTTP transport and local code-path checks | Mock service behavior cannot establish live compatibility or provider-side state. |
| Real Docker executor end-to-end behavior | Synthetic command construction and injected command results | Seven Docker-marked tests are excluded; the historical fourth-attempt failure is not reproduced by these simulations. |
| Host crash or power loss | Bounded synthetic child-process exits and journal fault injection | No evidence about OS recovery, filesystem caches, storage controllers, or power-loss durability. |
| Arbitrary child-process network access | Parent pytest process has socket and command tripwires | Only reviewed synthetic child scripts are safe by inspection; the guard is not injected into arbitrary child interpreters. |
| Branch/mutation coverage | Not collected | Coverage and Hypothesis tooling are absent from the Windows environments inspected; WSL2 could not be checked. |

The 132-pass, two-failure operator result predates the local fixes to the two
reported spend-approval regressions. A new full-suite run is still required to
verify those changes. Existing authorization checks recur across adapter,
client, and lifecycle tests because each boundary enforces a separate contract;
they are not interchangeable duplicates. Process-crash and proxy tests use
bounded children/threads and may take longer than pure unit tests; no timing
benchmark was collected.

Tests use `httpx.MockTransport`, fake Docker command results, in-memory
authorizations, and fresh temporary directories. The shared
`r01a_offline_guard` is applied to the core offline modules. It blocks DNS and
socket targets outside loopback, and commands for Docker, Codex, common network
clients, `authorize-one`, or `run-one`. Local loopback is allowed for tests of
the synthetic egress proxy. The durability and executor-contract modules have
their own narrower network/subprocess guards. Spawned Python children are
reviewed synthetic test helpers; the parent-process guard does not instrument
arbitrary child Python code.

## Safe execution

Run focused changed tests first:

```bash
cd /mnt/c/programming_pj/cran-mcp
test_root=$(mktemp -d /tmp/r01a-test-expansion-focused-XXXXXX)
chmod 700 "$test_root"

PYTHONDONTWRITEBYTECODE=1 \
.venv-wsl/bin/python -m pytest \
  tests/test_codex_offline_tripwire.py \
  tests/test_codex_managed_agents.py::test_session_creation_http_rejection_has_safe_structured_diagnostics \
  tests/test_codex_managed_agents.py::test_partial_success_response_is_uncertain_and_never_retried \
  tests/test_codex_single_trial_adapter.py::test_unexpected_authorization_validation_error_stops_before_controller \
  tests/test_codex_benchmark.py::test_plan_is_independent_of_current_working_directory \
  -q -p no:cacheprovider -m 'not docker' \
  --basetemp="$test_root/pytest-tmp"
```

Then run the relevant offline benchmark modules. `-m 'not docker'` excludes the
seven Docker-marked integration tests; do not remove that filter for an offline
run.

```bash
cd /mnt/c/programming_pj/cran-mcp
test_root=$(mktemp -d /tmp/r01a-test-expansion-core-XXXXXX)
chmod 700 "$test_root"

PYTHONDONTWRITEBYTECODE=1 \
.venv-wsl/bin/python -m pytest \
  tests/test_codex_managed_agents.py \
  tests/test_codex_managed_agents_lifecycle.py \
  tests/test_codex_single_trial_adapter.py \
  -q -p no:cacheprovider -m 'not docker' \
  --basetemp="$test_root/pytest-tmp"
```

After the core modules, run the expanded offline benchmark selection:

```bash
cd /mnt/c/programming_pj/cran-mcp
test_root=$(mktemp -d /tmp/r01a-test-expansion-XXXXXX)
chmod 700 "$test_root"

PYTHONDONTWRITEBYTECODE=1 \
.venv-wsl/bin/python -m pytest \
  tests/test_codex_managed_agents.py \
  tests/test_codex_managed_agents_lifecycle.py \
  tests/test_codex_single_trial_adapter.py \
  tests/test_codex_executor_contract_integration.py \
  tests/test_codex_lifecycle_durability.py \
  tests/test_codex_docker_runtime.py \
  tests/test_codex_egress_proxy.py \
  tests/test_codex_controller.py \
  tests/test_codex_benchmark.py \
  tests/test_codex_offline_tripwire.py \
  -q -p no:cacheprovider -m 'not docker' \
  --basetemp="$test_root/pytest-tmp"
```

Use `ruff check` and `ruff format --check` on the changed Python files, and run
`git diff --check`. Record exact passed, failed, skipped, and deselected counts.
Hypothesis, coverage.py, and pytest-cov were not installed in the Windows
system Python or repository virtual environment inspected. WSL2 could not be
queried from this sandbox, so availability there is unknown. No mutation-test
tooling was found in the project configuration. Do not add dependencies just
to report a percentage.

## Verification record — 2026-10-24

- Focused no-filesystem selection (tripwire, local egress proxy, and targeted
  regressions): **25 passed**, one existing pytest warning for the unrecognized
  `cache_dir` option.
- Expanded-suite collection only: **410 collected, 7 Docker-marked tests
  deselected**. Collection is not execution and is not a pass.
- Filesystem-backed focused tests and the full offline selection remain
  unverified. Windows pytest received `PermissionError: [WinError 5]` on fresh
  temporary roots both outside and inside the workspace. Starting Ubuntu WSL2
  from this environment returned `E_ACCESSDENIED`.
- `ruff check .` passed with warnings for inaccessible directories. Ruff check
  and format checks on the changed Python files passed. Repository-wide
  `ruff format --check .` panicked with `Expected a ruff source file` while
  traversing the working tree. `git diff --check` passed.
- No coverage percentage or mutation result is available. Do not treat the
  focused subset as verification of the full benchmark suite.

## Interpretation and limits

- Fake HTTP responses do not establish live OpenAI TLS/WSS compatibility,
  account permissions, billing behavior, or provider-side cleanup.
- Docker command and workspace tests do not reproduce the historical fourth
  attempt failure. The seven Docker-marked tests require a separately approved
  Ubuntu environment and are not part of this offline command.
- Process-crash tests exercise synthetic child processes and temporary
  journals. They do not prove power-loss durability or storage-controller
  behavior.
- A failing synthetic test identifies a local contract mismatch; a passing
  suite is not authorization or readiness to run a benchmark.
- Windows Codex pytest runs have previously failed while creating pytest
  temporary directories. If that recurs, report it as an environment failure
  and run the commands above directly in Ubuntu WSL2; do not count collection,
  skipped tests, or blocked runs as passes.
- Unverified areas still include live TLS/WSS registration, service behavior on
  real timeouts, actual executor registration, and physical power-loss
  guarantees. R01-A remains NO-GO.
