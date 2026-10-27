# P1-D D01 replication status and comparison

## Execution status

The bounded replication did not start. It remains at **0 of 2 model trials**, and
there are no new Run IDs. I did not create an Agents API session, inspect credentials,
or start Docker resources.

Two blockers stop execution:

1. The repository `AGENTS.md` rule says never execute R. The D01 runner uses a Docker
   executor for the R task, so running either treatment or control would violate that
   rule.
2. The requested WSL Python failed to start with
   `Wsl/Service/CreateInstance/E_ACCESSDENIED`. Offline checks use the Windows project
   virtual environment as a documented fallback.

The runner parser accepted all required arguments when checked with the Windows
interpreter and `PYTHONPATH=src`; this verified the CLI shape only. It did not execute
the runner or create a trial. The actual model-session commands below are validated
against that parser but were **not executed**.

## Offline verification

The final targeted regression command completed with **282 passed, 62 skipped, and
7 deselected**. It covered the benchmark client and launcher, discovery and allowlist
behavior, telemetry, DuckDB analytics, Knowledge Pilot scorers, and the evidence audit.
The full pytest suite was not rerun. A temporary repo-local pytest fixture was used
because the Windows environment denies pytest's normal temporary-directory ACL
changes; the fixture was removed after the tests. After the final evidence-audit
report adjustment, its focused regression module was rerun: **4 passed**.

`.venv/Scripts/python.exe -m ruff check .` passed. Ruff printed access-denied warnings
for leftover protected pytest scratch directories in the workspace, but returned 0.
The requested directory-wide `ruff format --check .` crashed in Ruff 0.17.1 with
`Expected a ruff source file` (exit 101). The explicit check over all 157 accessible
`.py`/`.pyi`/`.ipynb` source paths passed: **157 files already formatted**. One test,
`test_r02_seals_reviewed_filename_inside_root`, was excluded from the final test run
after its use of an external Windows `TemporaryDirectory` failed with `PermissionError`
during export/cleanup.

## Planned order and commands

The intended order is control first, then treatment. The model, scorer, task, mode,
effort, instructions, repetitions, timeout, and tool descriptions are the same; the
only planned difference is whether `list_package_functions` is allowed.

```bash
# 1. Control — not executed
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple \
  --effort medium \
  --tasks D01 \
  --modes with-mcp \
  --repetitions 1 \
  --timeout 900 \
  --instructions standard \
  --knowledge-pilot-scorer legacy \
  --function-discovery disabled

# 2. Treatment — not executed
.venv-wsl/bin/python -m benchmarks.codex_r.run_simple \
  --effort medium \
  --tasks D01 \
  --modes with-mcp \
  --repetitions 1 \
  --timeout 900 \
  --instructions standard \
  --knowledge-pilot-scorer legacy \
  --function-discovery enabled
```

No `--experiment standard` argument is used; standard is the runner default. The
machine-readable blockers, preflight status, and command strings are in
`p1d_replication_results.json`.

## Historical observations

| Measure | Historical enabled | Historical disabled |
|---|---|---|
| Run ID / historical order | `20261027T080622Z-16d73779` / 1 | `20261027T080923Z-f0bf06a8` / 2 |
| Score | 2/4 | 4/4 |
| MCP canonical calls | 0 | 15 |
| Server `tools/list` request count | 1 | 1 |
| `list_package_functions` | Allowed; 0 calls | Excluded; 0 calls |
| Registered / configured allowed tools | 16 / 13 | 16 / 12 |
| Final package/version | `termr 0.1.0` | `climenu 0.2.0` |
| Pinned version | `termr 1.0.1` | `climenu 0.2.0` |
| Observed tool-result version facts | None retained | None retained |
| Citation/source access | Unknown | Unknown |
| API usage/cost | Unavailable | Unavailable |

The enabled run failed scorer checks `accepted_package_and_version` and
`official_source_and_docs`. Its answer version differs from the frozen `termr 1.0.1`
reference. The answer's official CRAN package URL matches the frozen source identity
after host normalization, but its documentation URL does not match the frozen
documentation identity. Historical telemetry contains no version-specific tool
response fact, so the mismatch does not show that the model ignored retrieved
`1.0.1` evidence. It made zero observed MCP calls. The allowed discovery function
was not called.

The disabled run scored 4/4 and made 15 canonical MCP calls: `get_function_docs` 6,
`get_package` 7, and `search_packages` 2. It had one `docs_not_found` server error.
Its answer's `climenu 0.2.0` matches the frozen version and documentation URL. The
answer's source is a version-specific official CRAN tarball URL rather than the
frozen package-page identity. The historical response projection does not preserve
the version and URLs the agent actually received, so source access and tool-evidence
support remain unknown.

The disabled run has 15 client starts, 11 client successes and 4 client failures;
server telemetry independently has 11 successes and 4 failures. These are
source-specific lifecycle observations around the same 15 canonical calls, not
additional calls. Server/client correlations are ordinal and unconfirmed. Both
historical runs show one server `tools/list` request, but no authoritative remote
tool-name discovery list was saved. The one request count does not prove which tool
names the remote agent discovered. The optional session-configuration response echo
was added in telemetry 1.1 and was not recorded in these schema 1.0 runs; historical
exposure can be confirmed only from saved request/configuration metadata.

## Interpretation

- `list_package_functions` was configured in the enabled historical run but was
  not called. It was not allowed in the disabled run.
- The termr version mismatch against the frozen benchmark reference is real. The
  historical evidence is insufficient to say whether the agent saw the pinned
  version through a tool or another retrieval source.
- Neither the cited URL nor zero MCP calls resolves whether an external page was
  accessed. The old records do not provide complete non-MCP source-access coverage.
- There is no new enabled/disabled comparison and no causal conclusion. The
  historical sample is one trial per condition.

No answers, saved results, frozen verifier evidence, historical B1 outcomes, or
rescore reports were modified. The next experiment should be run only in an
environment and under project instructions that explicitly permit the D01 R/Docker
execution, after the offline regression checks pass.
