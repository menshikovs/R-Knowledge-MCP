# Evidence directory

Raw outputs behind the audit reports. Nothing here modifies the audited repository; probes ran against a clean `git clone` of commit `4d2266c994849ac460514ac2ae6df8a6fc5c180e` in a scratch directory with a fresh virtual environment built from `pyproject.toml`.

| Path | Content |
|---|---|
| `ci/` | CI reproduction outputs (Ubuntu/WSL and Windows), coverage report, Rust checks, ruff, the GitHub Actions run summary |
| `mcp/` | `tools_consolidated.json`, `tools_legacy.json`: the registered tools, annotations, schemas statistics and descriptions |
| `probes/` | one `.txt` per probe with the exact command, UTC start/end and exit code in its header (`../probe_runs.json` indexes them); plus `parity_*.json`, `linkcheck.txt`, `pip_audit.txt` |
| `benchmark/` | statistics rebuilt from the author's local (untracked) saved results with the project's own importer; prompt-output evaluation; tool response sizes |
| `probe_sources/` | every probe script (and the driver `run_all_probes.py`) |
| `real_cran_sample.json` | seeded random sample (seed 1729) of 30 current CRAN packages: discovery status, issues, docs lookup |
| `real_discovery_vs_R.json` | 14 packages: server discovery vs R 4.5.2 `getNamespaceExports()`/`Rd_db()` |
| `real_truth_versions.txt` | R-side version and count summary and the `package_version()` equivalence checks |
| `inventory.txt` | static inventory (LOC, import graph, cycles, largest functions/classes, test counts) |

## Re-running

```
python -m venv venv && venv/bin/pip install "<clone>[dev,analytics]"        # pinned by pyproject ranges
cd <clone> && venv/bin/python -I <probe_sources>/probe_a.py                   # offline probes need nothing else
```
Probes marked `network_to_public_upstream: True` in their header read public CRAN/Bioconductor/official-doc URLs sequentially; they need no credentials. `probe_sources/probe_real.py`, `probe_sample.py` and `probe_parity.py` (the three heaviest network probes: ≈ 55 package archives) were run once during the audit; their raw JSON is stored here and they are not part of `run_all_probes.py`. Their numeric results depend on the upstream state of 2026-10-27 and on the R library installed on the audit machine (R 4.5.2).

## Caveats that apply to everything in here
- `ci/pytest_windows_gitarchive_run.txt` was produced from a `git archive` export (no `.git` directory), which adds one artefact failure (`working_tree_sha256`); the later clone-based runs are the authoritative ones.
- Benchmark statistics come from `benchmarks/codex_r/results/`, which is git-ignored (finding BEN-005); they cannot be reproduced from the repository alone.
- Timings are from one Windows 11 machine (CPython 3.14.4, pure-Python path unless stated) and are meant for ratios and order of magnitude.
