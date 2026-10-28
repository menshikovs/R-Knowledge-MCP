"""Run every audit probe with a recorded command, exit code and UTC timestamps; store raw output as evidence."""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

S = Path(sys.argv[1])  # scratchpad
EVID = Path(sys.argv[2])  # audit evidence dir
PY = S / "venv" / "Scripts" / "python.exe"
CLONE = S / "clone"
PROBES = S / "probes"
(EVID / "probes").mkdir(parents=True, exist_ok=True)


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


runs = [
    # name, script, args, network, timeout
    ("inspect_tools", "../inspect_tools.py", [str(EVID / "mcp")], False, 120),
    ("probe_a_version_equivalence", "probe_a.py", [], False, 120),
    ("probe_b_bioc_provider_rebuild", "probe_b.py", [], False, 120),
    ("probe_c_prompt_score_ctx7_redaction", "probe_c.py", [], False, 120),
    ("probe_f_rdoc_fresh_install", "probe_f.py", [], False, 120),
    ("probe_stdio_protocol", "probe_stdio.py", [str(S / "venv" / "Scripts" / "r-knowledge-mcp.exe")], False, 180),
    ("probe_http_transport", "probe_http.py", [], False, 300),
    ("probe_mcp_shape", "probe_mcp_shape.py", [str(PROBES)], False, 180),
    ("probe_inject", "probe_inject.py", [str(PROBES)], False, 120),
    ("probe_logs", "probe_logs.py", [], False, 120),
    ("probe_conc", "probe_conc.py", [], False, 180),
    ("probe_redos", "probe_redos.py", [], False, 900),
    ("probe_static", "probe_static.py", [], False, 600),
    ("probe_intent", "probe_intent.py", [], False, 120),
    ("probe_flags", "probe_flags.py", [], False, 120),
    ("probe_secrets", "probe_secrets.py", [], False, 120),
    ("probe_pi_build", "probe_pi.py", [str(PROBES)], False, 180),
    ("probe_pi_followup", "probe_pi2.py", [str(PROBES)], False, 180),
    ("probe_pi_conflicts", "probe_pi3.py", [str(PROBES)], False, 180),
    ("probe_archive_hostile", "probe_archive.py", [], False, 900),
    ("probe_rss_hostile_archive", "probe_rss.py", [], False, 600),
    ("probe_perf", "probe_perf.py", [], True, 900),
    ("probe_framework", "probe_framework.py", [], True, 300),
    ("probe_real2_encoding_namespace", "probe_real2.py", [], True, 600),
    ("probe_real3_cluster_docs", "probe_real3.py", [], True, 600),
    ("probe_rdpartial", "probe_rdpartial.py", [], True, 600),
    ("probe_validate", "probe_validate.py", [], True, 600),
    ("probe_bioc", "probe_bioc.py", [], True, 600),
    ("probe_bioc_cost", "probe_bioc_cost.py", [], True, 600),
]
meta = {
    "src_tree_sha256_installed_copy": tree_hash(S / "venv" / "Lib" / "site-packages" / "cran_knowledge_mcp"),
    "src_tree_sha256_audited_clone": tree_hash(CLONE / "src" / "cran_knowledge_mcp"),
}
records = []
for name, script, args, network, timeout in runs:
    script_path = (PROBES / script).resolve()
    cmd = [str(PY), "-I", str(script_path), *args]
    started = datetime.now(UTC)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=CLONE, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        code, out = proc.returncode, proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr.strip() else "")
    except subprocess.TimeoutExpired as exc:
        code, out = "timeout", (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    ended = datetime.now(UTC)
    header = f"# command: python -I {script_path.name} {' '.join(Path(a).name if os.path.exists(a) else a for a in args)}\n# started_utc: {started.isoformat()}\n# ended_utc: {ended.isoformat()}\n# exit_code: {code}\n# network_to_public_upstream: {network}\n\n"
    # Keep stderr bounded (verbose telemetry lines) but never drop stdout.
    (EVID / "probes" / f"{name}.txt").write_text(header + out[:400_000], encoding="utf-8")
    records.append({"name": name, "script": script_path.name, "args": [Path(a).name if os.path.exists(a) else a for a in args], "exit_code": code, "started_utc": started.isoformat(), "ended_utc": ended.isoformat(), "seconds": round(time.time() - t0, 1), "public_network": network})
    print(name, code, f"{time.time() - t0:.1f}s", flush=True)
(EVID / "probe_runs.json").write_text(json.dumps({"meta": meta, "runs": records}, indent=1), encoding="utf-8")
print(meta)
