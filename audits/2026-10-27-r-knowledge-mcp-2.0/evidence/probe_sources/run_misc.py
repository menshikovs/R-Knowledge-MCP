"""Record exit codes/timestamps for the small tool-version and verification commands used in the audit."""
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

S = Path(sys.argv[1])
OUT = Path(sys.argv[2])
CLONE = S / "clone"
REPO = Path("C:/programming_pj/cran-mcp")
PY = str(S / "venv" / "Scripts" / "python.exe")

COMMANDS = [
    ("git_head", ["git", "-C", str(REPO), "rev-parse", "HEAD"], REPO),
    ("git_branch", ["git", "-C", str(REPO), "branch", "--show-current"], REPO),
    ("git_status_porcelain_lines", ["git", "-C", str(REPO), "status", "--short"], REPO),
    ("git_ls_remote_2.0", ["git", "-C", str(REPO), "ls-remote", "origin", "2.0"], REPO),
    ("clone_head", ["git", "-C", str(CLONE), "rev-parse", "HEAD"], CLONE),
    ("python_versions", [PY, "--version"], CLONE),
    ("pip_list_audit_venv", [PY, "-m", "pip", "list", "--format=freeze"], CLONE),
    ("ruff_check_clone", [str(S / "venv/Scripts/ruff.exe"), "check", "."], CLONE),
    ("ruff_format_check_clone", [str(S / "venv/Scripts/ruff.exe"), "format", "--check", "."], CLONE),
    ("pytest_collect_only_python_m", [PY, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], CLONE),
    ("pytest_collect_only_console_script", [str(S / "venv/Scripts/pytest.exe"), "--collect-only", "-q", "-p", "no:cacheprovider"], CLONE),
    ("pytest_collect_only_pythonpath_fix", [str(S / "venv/Scripts/pytest.exe"), "-o", "pythonpath=src .", "--collect-only", "-q", "-p", "no:cacheprovider"], CLONE),
    ("cargo_fmt_check", ["cargo", "fmt", "--check"], CLONE / "native"),
    ("rustc_version", ["rustc", "--version"], CLONE),
    ("cargo_version", ["cargo", "--version"], CLONE),
    ("docker_version", ["docker", "--version"], CLONE),
    ("docker_build", ["docker", "build", "-q", "-t", "rkmcp-audit:test", "."], CLONE),
    ("docker_run_help", ["docker", "run", "--rm", "rkmcp-audit:test", "--help"], CLONE),
    ("docker_run_id", ["docker", "run", "--rm", "--entrypoint", "id", "rkmcp-audit:test"], CLONE),
    ("docker_image_inspect", ["docker", "image", "inspect", "rkmcp-audit:test", "--format", "{{.Size}} bytes; user={{.Config.User}}; healthcheck={{.Config.Healthcheck}}"], CLONE),
    ("docker_rmi", ["docker", "rmi", "rkmcp-audit:test"], CLONE),
    ("pip_audit_runtime_closure", [str(S / "venvrt/Scripts/python.exe"), "-m", "pip_audit", "--local", "--progress-spinner", "off"], CLONE),
    ("rscript_version", ["Rscript", "--version"], CLONE),
    ("rscript_ground_truth_vers", ["Rscript", str(S / "probes/vers.R")], CLONE),
    ("uv_version", ["uv", "--version"], CLONE),
    ("wsl_python", ["wsl", "-d", "Ubuntu", "--", "python3", "--version"], CLONE),
]
records = []
for name, cmd, cwd in COMMANDS:
    started = datetime.now(UTC)
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
        code, out = proc.returncode, (proc.stdout + proc.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        code, out = "error", repr(exc)
    lines = out.splitlines()
    summary = "\n".join(lines[-3:]) if name.startswith(("pytest", "ruff", "pip_audit")) else "\n".join(lines[:3])
    if name == "pip_list_audit_venv":
        keep = ("mcp==", "httpx==", "pytest==", "pytest-asyncio==", "PyYAML==", "pydantic==", "starlette==", "uvicorn==", "anyio==", "duckdb==", "pandas==", "streamlit==", "coverage==", "vulture==", "ruff==", "cran-knowledge-mcp==")
        summary = "; ".join(line for line in lines if line.startswith(keep))
    records.append({"id": name, "command": " ".join(map(str, cmd)), "cwd": str(cwd), "exit_code": code, "started_utc": started.isoformat(), "ended_utc": datetime.now(UTC).isoformat(), "output_tail": summary[:1500]})
    print(name, code, flush=True)
OUT.write_text(json.dumps(records, indent=1), encoding="utf-8")
