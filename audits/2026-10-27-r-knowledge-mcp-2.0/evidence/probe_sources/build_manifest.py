"""Assemble EVIDENCE_MANIFEST.json from recorded command logs and hand-listed session commands. Counts are recomputed from FINDINGS.md."""
import json
import re
import sys
from pathlib import Path

A = Path(sys.argv[1])  # audit dir
S = Path(sys.argv[2])  # scratchpad
probe_runs = json.loads((A / "evidence" / "probe_runs.json").read_text(encoding="utf-8"))
misc = json.loads((A / "evidence" / "misc_commands.json").read_text(encoding="utf-8"))
findings = (A / "FINDINGS.md").read_text(encoding="utf-8")
ids = re.findall(r"^### ([A-Z]+-\d{3}) ", findings, re.M)
sev = {}
section = None
for line in findings.splitlines():
    if line.startswith("## P1"):
        section = "P1"
    elif line.startswith("## P2"):
        section = "P2"
    elif line.startswith("## P3"):
        section = "P3"
    elif line.startswith("### ") and section:
        sev.setdefault(section, []).append(line.split()[1])


def tail(path, n=1):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return lines[-n:] if lines else []


def read_first(path):
    return Path(path).read_text().strip().splitlines()


session = [
    {"id": "ruff_check_clean_checkout_windows", "command": "ruff check .", "env": "Windows 11, venv from pyproject (ruff 0.17.3)", "started_utc": read_first(S / "out/start.txt")[0], "exit_code": 0, "result": "All checks passed!", "evidence": "evidence/ci/ruff_check.txt"},
    {"id": "ruff_format_check_clean_checkout_windows", "command": "ruff format --check .", "exit_code": 0, "result": "311 files already formatted (git-archive tree incl. untracked-free files)", "evidence": "evidence/ci/ruff_format.txt"},
    {"id": "pytest_console_script_gitarchive", "command": "pytest -x -q -p no:cacheprovider (git archive export)", "exit_code": 1, "result": "ModuleNotFoundError: No module named 'benchmarks' at tests/test_baseline_root_cause_audit.py", "evidence": "n/a (first reproduction; superseded by clone-based runs)"},
    {"id": "pytest_python_m_gitarchive_full", "command": "python -m pytest -q (git archive export, no .git)", "exit_code": 1, "result": "11 failed, 1400 passed, 195 skipped in 424.76s (one failure is an artefact of the export lacking .git)", "evidence": "evidence/ci/pytest_windows_gitarchive_run.txt"},
    {"id": "pytest_console_script_collect_clone_windows", "command": "pytest --collect-only -q (real clone)", "exit_code": "not captured (pytest reports 'Interrupted: 23 errors during collection')", "result": "23 collection errors, all ModuleNotFoundError: benchmarks", "evidence": "evidence/ci/pytest_bare_collect_windows.txt"},
    {"id": "pytest_python_m_full_with_coverage_clone_windows", "command": "coverage run --branch --source=src/cran_knowledge_mcp -m pytest -q -p no:cacheprovider", "started_utc": "2026-10-27T13:57:09Z", "ended_utc": "2026-10-27T14:04:01Z", "exit_code": 1, "result": "10 failed, 1401 passed, 195 skipped in 408.64s; coverage 84% (6419 stmts, 829 missed, 2752 branches, 496 partial)", "evidence": "evidence/ci/pytest_windows_clone_cov.txt, evidence/ci/coverage_report.txt"},
    {"id": "wsl_ci_exact_commands", "command": "(WSL Ubuntu, Python 3.14.4, pip install -e '.[dev]') ruff check .; ruff format --check .; pytest -q -p no:cacheprovider", "started_utc": "2026-10-27T14:13Z (approx.)", "exit_code": "pytest: interrupted (22 collection errors); the wrapper did not capture exit codes", "result": "ruff check pass; ruff format pass (267 files); pytest: Interrupted: 22 errors during collection", "evidence": "evidence/ci/wsl_ci_bare.txt"},
    {"id": "wsl_pytest_pythonpath_fixed_with_analytics", "command": "(WSL) sed pythonpath=[\"src\", \".\"]; pip install -e '.[dev,analytics]'; pytest -q -p no:cacheprovider", "started_utc": "2026-10-27T14:17:08Z", "ended_utc": "2026-10-27T14:23:26Z", "exit_code": "1 by pytest convention (wrapper wrote exit=0 because of a quoting artefact; the summary line is authoritative)", "result": "17 failed, 1529 passed, 60 skipped in 377.66s", "evidence": "evidence/ci/pytest_linux_fixed.txt"},
    {"id": "pytest_py311_collect_pythonpath_fixed_dev_only", "command": "pytest -o pythonpath='src .' --collect-only -q (Python 3.11, [dev] only)", "exit_code": "not captured (1 collection error reported)", "result": "1554 collected, 1 error: No module named 'duckdb'", "evidence": "evidence/ci/py311_collect_fixedpath.txt"},
    {"id": "pytest_py311_full", "command": "python -m pytest -q -o pythonpath='src .' --deselect tests/test_codex_expansion_registry.py --deselect tests/test_bioc_benchmark.py (Python 3.11, +duckdb,pandas)", "started_utc": "2026-10-27T14:25:05Z", "ended_utc": "2026-10-27T14:31:15Z", "exit_code": 1, "result": "1 failed (streamlit not installed), 1367 passed, 198 skipped", "evidence": "evidence/ci/pytest_py3.11.txt"},
    {"id": "pytest_py312_full", "command": "same, Python 3.12", "started_utc": "2026-10-27T14:31:15Z", "ended_utc": "2026-10-27T14:37:38Z", "exit_code": 1, "result": "1 failed (streamlit not installed), 1367 passed, 198 skipped", "evidence": "evidence/ci/pytest_py3.12.txt"},
    {"id": "pytest_py313_full", "command": "same, Python 3.13", "started_utc": "2026-10-27T14:37:38Z", "ended_utc": "2026-10-27T14:44Z (approx.)", "exit_code": 1, "result": "1 failed (streamlit not installed), 1367 passed, 198 skipped", "evidence": "evidence/ci/pytest_py3.13.txt"},
    {"id": "cargo_test_clippy_fmt", "command": "cargo test --release; cargo clippy --release -- -D warnings; cargo fmt --check (native/)", "exit_code": 0, "result": "4 tests passed; clippy clean; fmt clean", "evidence": "evidence/ci/cargo_test.txt, cargo_clippy.txt, cargo_fmt.txt"},
    {"id": "maturin_build_and_native_tests", "command": "maturin build --release; pip install wheel; pytest tests/test_native_parity.py tests/test_function_discovery.py tests/test_function_discovery_replay.py -o usefixtures=r01a_offline_guard", "exit_code": 0, "result": "wheel cran_knowledge_native-0.1.0-cp311-abi3-win_amd64.whl built in 7s; 108 passed with native module loaded", "evidence": "evidence/probes/parity_python.json, parity_rust.json"},
    {"id": "github_actions_api_read", "command": "GET https://api.github.com/repos/menshikovs/R-Knowledge-MCP/actions/runs/40513710256 (+/jobs), unauthenticated", "exit_code": 0, "result": "run conclusion failure; test jobs fail at 'Run pytest'; docker and native success", "evidence": "evidence/ci/github_actions_run.json"},
    {"id": "analytics_rebuild_from_local_results", "command": "python -B -m benchmarks.codex_r.analytics.import_results --database <scratch> --rebuild", "exit_code": 0, "result": "30 runs, 91 trials, 21 tables, 10.9 s", "evidence": "evidence/benchmark/analytics_import.txt, bench_stats.txt, bench_err.txt, bench_d01.txt"},
    {"id": "real_upstream_sampling", "command": "probe_real.py, probe_sample.py, probe_parity.py (fetch) — see evidence/probe_sources", "exit_code": 0, "result": "14 packages vs R ground truth; 30-package seeded sample; 10-package Python/Rust parity", "evidence": "evidence/real_discovery_vs_R.json, real_cran_sample.json, probes/parity_*.json"},
    {"id": "mcp_spec_pages_read", "command": "WebFetch modelcontextprotocol.io/specification/2025-11-25/server/tools and /basic/transports", "exit_code": 0, "result": "spec text used in MCP_PROTOCOL_AUDIT.md", "evidence": "n/a"},
]
manifest = {
    "audit": {"title": "Independent audit of R-Knowledge-MCP 2.0", "date": "2026-10-27", "directory": "audits/2026-10-27-r-knowledge-mcp-2.0/", "mode": "audit-only; only files under audits/ were created in the repository; no production code, benchmark artefact, scorer, reference solution, historical result or report was modified"},
    "target": {"repository": "https://github.com/menshikovs/R-Knowledge-MCP", "branch": "2.0", "commit": "4d2266c994849ac460514ac2ae6df8a6fc5c180e", "commit_date": "2026-10-27T15:37:26+02:00", "origin_2.0_equals_local_head": True, "working_tree_clean": True, "tracked_files": 515},
    "environment": {
        "os": "Windows 11 Home 10.0.26100; WSL2 Ubuntu (python3 3.14.4)",
        "python_audit_venvs": ["3.14.4 (main)", "3.11.17", "3.12.15", "3.13.5"],
        "note_on_global_python": "the machine's global Python had mcp 2.2.0 (outside the project's <2 pin); it was not used for audit runs",
        "tool_versions_source": "evidence/misc_commands.json (pip_list_audit_venv, rustc_version, cargo_version, docker_version, rscript_version, uv_version)",
    },
    "findings": {"counts": {"P0": 0, "P1": len(sev.get("P1", [])), "P2": len(sev.get("P2", [])), "P3": len(sev.get("P3", [])), "total": len(ids)}, "ids_by_severity": sev},
    "session_commands": session,
    "recorded_command_runs": misc,
    "probe_runs": probe_runs["runs"],
    "probe_meta": probe_runs["meta"],
    "external_reads": [
        {"what": "CRAN PACKAGES(.gz), title catalogue, ~75 package source archives (sequential)", "host": "cran.r-project.org", "public": True},
        {"what": "Bioconductor config.yaml, three PACKAGES indexes, three archives", "host": "bioconductor.org", "public": True},
        {"what": "three fixed official framework documentation pages", "host": "shiny.posit.co, quarto.org, positron.posit.co", "public": True},
        {"what": "GitHub Actions run summary and ls-remote", "host": "api.github.com, github.com", "public": True},
        {"what": "MCP specification pages", "host": "modelcontextprotocol.io", "public": True},
        {"what": "PyPI/OSV vulnerability data via pip-audit; Python/uv/crates downloads for toolchains", "host": "pypi.org, osv.dev, crates.io, python-build-standalone", "public": True},
    ],
    "not_contacted": ["paid model APIs", "OpenAI Agents API", "Context7", "authenticated GitHub endpoints", "any private service"],
    "r_execution": "Rscript was run only on my own scripts (evidence/probe_sources/truth.R, vers.R) against the locally installed R 4.5.2 base/recommended libraries; no repository, package or benchmark R code, Rd expression or package script was executed",
    "limitations": [
        "Windows and WSL on one machine; no macOS",
        "Full test runs on Python 3.11-3.13 are Windows-only",
        "GitHub job logs not readable (authentication)",
        "Benchmark results directory is git-ignored; statistics are reproducible only with the author's local files",
        "Live GitHub AGENTS.md, Context7, R-manual refresh, third-party MCP clients, SDK 2.x, concurrent-client load: not tested",
        "Five R/termr-dependent launcher tests failing under WSL were not attributed",
        "Timing numbers are single-machine micro-measurements",
    ],
}
(A / "EVIDENCE_MANIFEST.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
print("manifest written; findings", manifest["findings"]["counts"])
