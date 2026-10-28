"""Seeded random sample of current CRAN packages: how often do discovery/docs degrade? Sequential, low volume."""
import asyncio
import collections
import json
import random
import sys
import time

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.service import KnowledgeService

N = int(sys.argv[2])
OUT = sys.argv[1]


async def main():
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        cran = await svc.provider("cran")
        records, index = await cran.index()
        names = sorted(records)
        rng = random.Random(1729)
        sample = rng.sample(names, N)
        rows = []
        for pkg in sample:
            t0 = time.time()
            row = {"pkg": pkg, "version": records[pkg]["Version"], "needs_compilation": records[pkg].get("NeedsCompilation")}
            d = await svc.list_package_functions(pkg, limit=50)
            if "error" in d:
                row["discovery"] = "error:" + d["error"]["code"]
            else:
                row["discovery"] = d["verification_status"]
                row["issues"] = d["issues"]
                row["n_exports"] = d["collections"]["exports"]["total"]
                row["n_aliases"] = d["collections"]["aliases"]["total"]
                row["patterns"] = d["export_patterns_count"]
                row["ns"], row["rd"] = d["coverage"]["namespace"], d["coverage"]["rd"]
                first = (d["aliases"] or d["exports"] or [{}])[0].get("name")
                if first:
                    g = await svc.get_function_docs(pkg, first)
                    row["docs_first_alias"] = "ok" if "error" not in g else "error:" + g["error"]["code"]
            row["secs"] = round(time.time() - t0, 2)
            rows.append(row)
            print(json.dumps(row), flush=True)
            await asyncio.sleep(0.5)
        json.dump(rows, open(OUT, "w"), indent=1)
        c = collections.Counter(r["discovery"] for r in rows)
        print("DISCOVERY", dict(c))
        print("DOCS", dict(collections.Counter(r.get("docs_first_alias") for r in rows)))
        iss = collections.Counter(i for r in rows for i in r.get("issues", []))
        print("ISSUES", dict(iss))


asyncio.run(main())
