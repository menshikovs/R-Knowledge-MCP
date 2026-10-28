"""Every evidence/... path and every FINDINGS ID mentioned in the reports must exist / be defined."""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
docs = [p for p in root.glob("*.md")]
findings = (root / "FINDINGS.md").read_text(encoding="utf-8")
defined = set(re.findall(r"^### ([A-Z]+-\d{3})", findings, re.M))
print("defined findings:", len(defined))
missing_paths, unknown_ids = set(), set()
for doc in docs:
    text = doc.read_text(encoding="utf-8")
    for m in re.findall(r"`?(evidence/[A-Za-z0-9_./\-]+)`?", text):
        path = root / m.rstrip(".,;:)")
        if not path.exists() and not list(root.glob(m.rstrip(".,;:)") + "*")):
            missing_paths.add((doc.name, m))
    for fid in set(re.findall(r"\b((?:CI|KC|BEN|SEC|MCP|AGT|TST|ARCH|PI|DOC|PERF)-\d{3})\b", text)):
        if fid not in defined:
            unknown_ids.add((doc.name, fid))
    # bare probe names such as `probe_http_transport.txt` / `probe_c…`
    for name in re.findall(r"`(probe_[a-z0-9_]+\.txt)`", text):
        if not (root / "evidence" / "probes" / name).exists():
            missing_paths.add((doc.name, "evidence/probes/" + name))
print("missing evidence paths:", sorted(missing_paths))
print("unknown finding ids:", sorted(unknown_ids))
