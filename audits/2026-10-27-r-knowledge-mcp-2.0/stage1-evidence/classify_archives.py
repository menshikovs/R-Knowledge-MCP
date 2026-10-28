"""Run Function Discovery over saved archives with a given source tree (before/after comparison).

usage: python -I classify_archives.py <src_dir> <archives_dir> <out.json>
Reads archives as untrusted data via the project's bounded parser; nothing is extracted or run.
"""

import json
import sys
import time
from pathlib import Path

src, archives, out = sys.argv[1:4]
sys.path.insert(0, src)

from cran_knowledge_mcp import function_discovery as fd  # noqa: E402
from cran_knowledge_mcp.parsers import dcf, description_text, source_files  # noqa: E402

rows = []
for entry in json.loads((Path(archives) / "manifest.json").read_text()):
    pkg, version = entry["package"], entry["version"]
    body = (Path(archives) / f"{pkg}_{version}.tar.gz").read_bytes()
    started = time.perf_counter()
    files = source_files(body, pkg)
    metadata = dcf(description_text(files[f"{pkg}/DESCRIPTION"]))[0]
    index = fd.build_discovery_index(pkg, metadata, files)
    status = "verified" if index.namespace_status == index.rd_status == "verified" else "partial"
    rows.append(
        {
            "package": pkg,
            "version": version,
            "status": status,
            "namespace": index.namespace_status,
            "rd": index.rd_status,
            "issues": list(index.issues),
            "completeness": getattr(index, "completeness", None),
            "diagnostics": [
                {k: d[k] for k in ("code", "class", "count") if k in d}
                for d in getattr(index, "diagnostics", ())
            ],
            "exports": sum(e["kind"] == "export" for e in index.entries),
            "aliases": sum(e["kind"] == "alias" for e in index.entries),
            "topics": sum(e["kind"] == "topic" for e in index.entries),
            "methods": sum(e["kind"] == "method" for e in index.entries),
            "patterns": len(index.patterns),
            "seconds": round(time.perf_counter() - started, 3),
        }
    )
Path(out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(len(rows), "packages;", sum(r["status"] == "verified" for r in rows), "verified")
