"""Python vs Rust parity on real CRAN sources. mode=fetch caches source files; mode=run builds discovery + search."""
import asyncio
import hashlib
import json
import os
import pickle
import sys
import time

MODE, CACHE = sys.argv[1], sys.argv[2]
PKGS = ["MASS", "lattice", "cluster", "nlme", "Matrix", "survival", "mgcv", "termr", "boot", "rpart"]


async def fetch():
    from cran_knowledge_mcp.http import CranHTTP, make_client
    from cran_knowledge_mcp.service import KnowledgeService
    out = {}
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        cran = await svc.provider("cran")
        for p in PKGS:
            try:
                meta, files, art, idx = await cran.source(p)
            except Exception:
                # cluster: source() succeeds; failures here are not expected
                raise
            out[p] = (meta, files)
        records, index = await cran.index()
        out["__index__"] = {k: {"Version": v["Version"]} for k, v in list(records.items())}
        import httpx  # noqa: F401
        cat = await cran.http.fetch("/web/packages/available_packages_by_name.html")
        out["__catalog__"] = cat.body
    pickle.dump(out, open(CACHE, "wb"))
    print("cached", [k for k in out if not k.startswith("__")])


def run():
    from cran_knowledge_mcp import native
    from cran_knowledge_mcp.function_discovery import build_discovery_index
    from cran_knowledge_mcp.parsers import parse_namespace
    from cran_knowledge_mcp.providers.base import PackageSearchIndex
    from cran_knowledge_mcp.providers.cran import _parse_catalog
    from cran_knowledge_mcp.http import Artifact
    data = pickle.load(open(CACHE, "rb"))
    digest, times = {}, {}
    for p in PKGS:
        meta, files = data[p]
        t = time.perf_counter()
        di = build_discovery_index(p, meta, files)
        times[p] = round((time.perf_counter() - t) * 1000, 1)
        digest[p] = hashlib.sha256(json.dumps([di.entries, di.namespace_status, di.rd_status, di.issues, di.patterns], sort_keys=True, default=str).encode()).hexdigest()[:16]
    rows = _parse_catalog(Artifact(data["__catalog__"], "x", "y"))
    entries = [(n, t) for n, t in rows.items() if n in data["__index__"]]
    ts = time.perf_counter()
    idx = PackageSearchIndex(entries)
    build = (time.perf_counter() - ts) * 1000
    res = {}
    qt = {}
    for q in ("ggplot", "time series forecasting", "a", "data.table", "mixed effects"):
        t = time.perf_counter()
        for _ in range(5):
            r = idx.search(q)
        qt[q] = round((time.perf_counter() - t) * 1000 / 5, 2)
        res[q] = hashlib.sha256(json.dumps(r).encode()).hexdigest()[:16]
    print(json.dumps({"native": native.native is not None, "discovery_ms": times, "discovery_digest": digest,
                      "search_build_ms": round(build, 1), "search_ms": qt, "search_digest": res}))


if MODE == "fetch":
    asyncio.run(fetch())
else:
    run()
