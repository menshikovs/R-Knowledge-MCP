"""Safely extract only man/*.Rd, NAMESPACE and DESCRIPTION of saved archives for an R cross-check.

usage: python -I extract_for_r.py <archives_dir> <out_dir>   (out_dir must not exist)
Rejects absolute/parent paths and non-regular members; bounded per file and in total.
"""

import sys
import tarfile
from pathlib import Path

archives, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True)
total = 0
for archive in sorted(archives.glob("*.tar.gz")):
    pkg = archive.name.split("_")[0]
    with tarfile.open(archive) as tar:
        for member in tar:
            parts = Path(member.name).parts
            if not member.isreg() or ".." in parts or member.name.startswith("/") or len(parts) < 2:
                continue
            rel = "/".join(parts[1:])
            if rel in {"NAMESPACE", "DESCRIPTION"} or (rel.startswith("man/") and rel.endswith(".Rd")):
                if member.size > 4 << 20 or total > 400 << 20:
                    continue
                target = out / pkg / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
                total += member.size
print("extracted", total, "bytes")
