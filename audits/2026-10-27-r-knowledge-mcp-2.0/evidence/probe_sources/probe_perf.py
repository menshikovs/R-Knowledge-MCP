"""Deterministic local microbenchmarks (synthetic archives; one real PACKAGES.gz fetch for index timing)."""
import asyncio
import gzip
import io
import json
import statistics
import sys
import tarfile
import time
import tracemalloc

import httpx

from cran_knowledge_mcp import native as native_mod
from cran_knowledge_mcp.function_discovery import build_discovery_index
from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.parsers import dcf, source_files
from cran_knowledge_mcp.providers.base import PackageSearchIndex
from cran_knowledge_mcp.providers.cran import _parse_index
from cran_knowledge_mcp.service import KnowledgeService

NL = chr(10)
BS = chr(92)


def timeit(fn, n=5):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return round(statistics.median(xs), 2), round(min(xs), 2), round(max(xs), 2)


def synthetic_tarball(n_rd, aliases_per_rd=3, extra_body=2000):
    buf = io.BytesIO()
    desc = NL.join(["Package: Big", "Version: 1.0", "Title: T", "Description: D.", "License: MIT", "Encoding: UTF-8", ""])
    ns = NL.join(f"export(fn_{i}_0)" for i in range(n_rd)) + NL
    ns = ns[: 250 * 1024]  # parser limit 256 KiB
    with tarfile.open(fileobj=buf, mode="w") as t:
        def add(name, text):
            b = text.encode()
            m = tarfile.TarInfo(name)
            m.size = len(b)
            t.addfile(m, io.BytesIO(b))
        add("Big/DESCRIPTION", desc)
        add("Big/NAMESPACE", ns)
        for i in range(n_rd):
            al = NL.join(BS + f"alias{{fn_{i}_{j}}}" for j in range(aliases_per_rd))
            body = (BS + f"name{{fn_{i}_0}}" + NL + al + NL + BS + "title{T}" + NL + BS + "description{" + ("lorem ipsum " * (extra_body // 12)) + "}" + NL)
            add(f"Big/man/fn_{i}.Rd", body)
    return gzip.compress(buf.getvalue())


async def main():
    print("native accelerators loaded:", native_mod.native is not None)
    # ---- real CRAN index
    async with make_client() as client:
        http = CranHTTP(client)
        art = await http.fetch("/src/contrib/PACKAGES.gz")
        cat = await http.fetch("/web/packages/available_packages_by_name.html")
    print(f"real PACKAGES expanded: {len(art.body)/1e6:.1f} MB; catalog {len(cat.body)/1e6:.1f} MB")
    t_dcf = timeit(lambda: _parse_index(art), 3)
    records = _parse_index(art)
    print(f"CRAN _parse_index: {len(records)} records; median/min/max ms = {t_dcf}")
    from cran_knowledge_mcp.providers.cran import _parse_catalog
    rows = _parse_catalog(cat)
    entries = [(n, t) for n, t in rows.items() if n in records]
    print("PackageSearchIndex build ms:", timeit(lambda: PackageSearchIndex(entries), 3), "entries", len(entries))
    idx = PackageSearchIndex(entries)
    for q in ("ggplot", "time series forecasting", "a"):
        print(f"search {q!r} ms:", timeit(lambda q=q: idx.search(q), 5), "hits", len(idx.search(q)))

    # ---- synthetic archive: archive parse, discovery build, page, memory
    for n_rd in (500, 1800):
        body = synthetic_tarball(n_rd)
        print(f"-- synthetic {n_rd} Rd files; tarball {len(body)/1e6:.2f} MB")
        t_files = timeit(lambda: source_files(body, "Big"), 3)
        files = source_files(body, "Big")
        meta = {"Package": "Big", "Version": "1.0", "Encoding": "UTF-8"}
        print("source_files ms:", t_files, "| parsed bytes:", sum(len(v) for v in files.values()))
        tracemalloc.start()
        t0 = time.perf_counter()
        di = build_discovery_index("Big", meta, files)
        t_build = (time.perf_counter() - t0) * 1000
        cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f"build_discovery_index: {t_build:.0f} ms (under tracemalloc), entries={len(di.entries)} est_bytes={di.estimated_bytes} peak_traced={peak/1e6:.1f} MB")
        print("page(no query) ms:", timeit(lambda: di.page("Big", None, 50, 0), 5))
        print("page(fuzzy query) ms:", timeit(lambda: di.page("Big", "fn_77_x", 50, 0), 5), "| fuzzy_complete:", di.page("Big", "fn_77_x", 50, 0)["coverage"]["fuzzy_search_complete"])
        print("page(deep offset) ms:", timeit(lambda: di.page("Big", None, 50, 0), 3))

    # ---- event loop stall + concurrency through the service with a mocked network
    body = synthetic_tarball(1800)
    index_text = NL.join(["Package: Big", "Version: 1.0", "License: MIT", ""]).encode()
    import hashlib
    routes = {
        "/src/contrib/PACKAGES": index_text,
        "/src/contrib/Big_1.0.tar.gz": body,
        "/web/packages/available_packages_by_name.html": b"<table></table>",
    }

    def handler(request):
        c = routes.get(request.url.path)
        if c is None and request.url.path.endswith(".gz") and request.url.path[:-3] in routes:
            c = gzip.compress(routes[request.url.path[:-3]])
        return httpx.Response(404 if c is None else 200, content=c or b"")

    stalls = []

    async def heartbeat(stop):
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            stalls.append((now - last) * 1000)
            last = now

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = KnowledgeService(CranHTTP(client))
        stop = asyncio.Event()
        hb = asyncio.create_task(heartbeat(stop))
        t0 = time.perf_counter()
        r = await svc.list_package_functions("Big", limit=50)
        cold = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        r2 = await svc.list_package_functions("Big", limit=50, query="fn_12", snapshot=None)
        warm = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        results = await asyncio.gather(*(svc.get_function_docs("Big", f"fn_{i}_0") for i in range(40)))
        conc = (time.perf_counter() - t0) * 1000
        stop.set()
        await hb
        print(f"service cold discovery {cold:.0f} ms; warm query {warm:.0f} ms; 40 concurrent docs {conc:.0f} ms; ok={sum('error' not in x for x in results)}/40")
        print(f"event-loop heartbeat gaps (5ms tick): max {max(stalls):.0f} ms, p99 {sorted(stalls)[int(len(stalls)*0.99)]:.0f} ms, n={len(stalls)}")
        print("discovery status:", r["verification_status"], "issues", r["issues"], "total", r["total_matches"], "response bytes", len(json.dumps(r)))


asyncio.run(main())
