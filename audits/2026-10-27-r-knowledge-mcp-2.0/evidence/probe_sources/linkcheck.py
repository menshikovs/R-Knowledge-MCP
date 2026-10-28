"""Relative-link check over tracked Markdown at the audited commit (clean clone: ignored/untracked files do not exist)."""
import os
import re
import subprocess
import sys

root = sys.argv[1]
files = [f for f in subprocess.check_output(["git", "-C", root, "ls-files"], text=True).split("\n") if f.endswith(".md")]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
broken = []
total = 0
for f in files:
    text = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
    for target in LINK.findall(text):
        if re.match(r"^(https?:|mailto:|#)", target):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        total += 1
        resolved = os.path.normpath(os.path.join(root, os.path.dirname(f), path))
        if not os.path.exists(resolved):
            broken.append((f, target))
print("markdown files:", len(files), "relative links:", total, "broken:", len(broken))
for b in broken:
    print("  ", b)
# plain-text mentions of untracked docs
for f in files:
    text = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
    for name in ("ARCHITECTURE_AUDIT.md", "CODEX_MCP_BENCHMARK.md", "INTEGRATION_AUDIT.md", "CHANGE_IMPACT_REVIEW"):
        if name in text:
            print("   mentions untracked doc", name, "in", f)
