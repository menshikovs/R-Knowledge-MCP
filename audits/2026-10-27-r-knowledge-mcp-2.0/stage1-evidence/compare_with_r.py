"""Compare the server's static aliases/exports with R's own parse (r_crosscheck.R output).

usage: python -I compare_with_r.py <src_dir> <archives_dir> <r.tsv> <out.json>
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

src, archives, tsv, out = sys.argv[1:5]
sys.path.insert(0, src)
from cran_knowledge_mcp import function_discovery as fd  # noqa: E402
from cran_knowledge_mcp.parsers import dcf, description_text, source_files  # noqa: E402

r_alias, r_export, r_s3, r_pat = defaultdict(set), defaultdict(set), defaultdict(set), {}
for line in Path(tsv).read_text(encoding="utf-8").splitlines():
    parts = line.split("\t")
    if parts[0] in ("A", "E", "M") and len(parts) >= 3:
        if parts[2]:
            {"A": r_alias, "E": r_export, "M": r_s3}[parts[0]][parts[1]].add(parts[2])
    elif len(parts) == 4 and parts[0] not in ("A", "E", "M"):
        r_pat[parts[0]] = parts[3]
rows = []
for entry in json.loads((Path(archives) / "manifest.json").read_text()):
    pkg, version = entry["package"], entry["version"]
    files = source_files((Path(archives) / f"{pkg}_{version}.tar.gz").read_bytes(), pkg)
    meta = dcf(description_text(files[f"{pkg}/DESCRIPTION"]))[0]
    index = fd.build_discovery_index(pkg, meta, files)
    mine_a = {e["name"] for e in index.entries if e["kind"] == "alias"}
    mine_e = {e["name"] for e in index.entries if e["kind"] == "export"}
    mine_m = {f"{e['generic'].split('::')[-1]} {e['class']}" for e in index.entries if e["kind"] == "method" and e["method_kind"] == "S3"}
    ra, re_ = r_alias[pkg], {x for x in r_export[pkg] if x not in ("NA", "")}
    rows.append(
        {
            "package": pkg,
            "version": version,
            "completeness": index.completeness,
            "alias_equal": mine_a == ra,
            "alias_only_server": sorted(mine_a - ra)[:5],
            "alias_only_R": sorted(ra - mine_a)[:5],
            "export_equal": mine_e == re_,
            "export_only_server": sorted(mine_e - re_)[:5],
            "export_only_R": sorted(re_ - mine_e)[:5],
            "s3_equal": mine_m == r_s3[pkg],
            "s3_only_server": sorted(mine_m - r_s3[pkg])[:5],
            "s3_only_R": sorted(r_s3[pkg] - mine_m)[:5],
            "R_export_patterns": r_pat.get(pkg),
        }
    )
Path(out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
for r in rows:
    print(f"{r['package']:14} {r['completeness']:26} alias={'=' if r['alias_equal'] else 'DIFF'} export={'=' if r['export_equal'] else 'DIFF'} s3={'=' if r['s3_equal'] else 'DIFF'} patterns_R={r['R_export_patterns']}",
          "" if r["alias_equal"] and r["export_equal"] and r["s3_equal"] else f"| aliasS-R {r['alias_only_server']} R-S {r['alias_only_R']} | expS-R {r['export_only_server']} R-S {r['export_only_R']} | s3 S-R {r['s3_only_server']} R-S {r['s3_only_R']}")
