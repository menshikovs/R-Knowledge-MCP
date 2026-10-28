import asyncio, json, sys, os, time
from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.service import KnowledgeService
TRUTH = sys.argv[1]
PKGS = ["MASS","lattice","cluster","rpart","boot","nnet","class","codetools","foreign","KernSmooth","nlme","Matrix","survival","mgcv","termr"]
async def pages(svc, pkg):
    ex, al, tp, me, off, snap, calls, first = [], [], [], [], 0, None, 0, None
    while True:
        r = await svc.list_package_functions(pkg, limit=50, offset=off, snapshot=snap)
        calls += 1
        if "error" in r: return {"error": r["error"]}
        first = first or r
        ex += [e["name"] for e in r["exports"]]; al += [e["name"] for e in r["aliases"]]
        tp += [e["name"] for e in r["documentation_topics"]]; me += [e["name"] for e in r["methods"]]
        snap = r["snapshot"]
        if r["next_offset"] is None: break
        off = r["next_offset"]
    return dict(pkg=pkg, ver=first["package_version"], status=first["verification_status"], issues=first["issues"], cov=first["coverage"], patterns=first["export_patterns"],
        exports=sorted(set(ex)), aliases=sorted(set(al)), methods=sorted(set(me)), calls=calls, total=first["total_matches"], archive_sha=first["archive_sha256"][:12])
def load(p):
    d = {"E": [], "A": [], "V": None}
    for line in open(os.path.join(TRUTH, p + ".txt"), encoding="utf-8"):
        k, _, v = line.rstrip("\n").partition("\t")
        if k == "V": d["V"] = v
        elif k in ("E", "A"): d[k].append(v)
    return d
async def main():
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        rows = []
        for p in PKGS:
            t0 = time.time()
            r = await pages(svc, p)
            dt = time.time() - t0
            if "error" in r:
                print(p, "ERROR", r["error"]["code"], r["error"]["message"][:100]); rows.append({"pkg":p,"error":r["error"]["code"]}); continue
            if p == "termr":
                print(p, r["ver"], r["status"], r["issues"], r["cov"], r["patterns"], len(r["exports"]), len(r["aliases"])); rows.append({k:r[k] for k in ("pkg","ver","status","issues","patterns")}); continue
            t = load(p)
            te, ta = set(t["E"]), set(t["A"]); de, da = set(r["exports"]), set(r["aliases"])
            same_ver = t["V"].replace("-", ".") == r["ver"].replace("-", ".")
            row = dict(pkg=p, installed=t["V"], cran=r["ver"], same_version=same_ver, status=r["status"], issues=r["issues"], patterns=r["patterns"],
                R_exports=len(te), srv_exports=len(de), exports_missing=len(te-de), exports_extra=len(de-te),
                R_aliases=len(ta), srv_aliases=len(da), aliases_missing=len(ta-da), aliases_extra=len(da-ta), calls=r["calls"], secs=round(dt,2),
                miss_sample=sorted(te-de)[:5], extra_sample=sorted(de-te)[:5], amiss_sample=sorted(ta-da)[:5])
            rows.append(row); print(json.dumps(row))
    json.dump(rows, open(os.path.join(TRUTH, "..", "out", "real_discovery.json"), "w"), indent=1)
asyncio.run(main())
