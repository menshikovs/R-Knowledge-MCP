"""Cost of the Bioconductor provider rebuild that happens whenever the cached config.yaml artifact is refreshed."""
import asyncio
import os
import statistics
import time

import yaml

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.providers.bioconductor import _parse_indexes
from cran_knowledge_mcp.service import KnowledgeService


def timeit(fn, n=5):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return round(statistics.median(xs), 1)


async def main():
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        _, cfg = await svc.releases.catalog()
        print("config.yaml bytes:", len(cfg.body), "| safe_load median ms:", timeit(lambda: yaml.safe_load(cfg.body)))
        p = await svc.provider("bioconductor")
        records, art = await p.index()
        sizes = {k: len(v.body) for k, v in p._sources.items()}
        print("bioc PACKAGES bytes by category:", sizes, "| records:", len(records))
        print("_parse_indexes (3 categories) median ms:", timeit(lambda: _parse_indexes(dict(p._sources))))
        # catalog() parse per tool call vs total call latency from a warm cache
        t0 = time.perf_counter()
        for _ in range(20):
            await svc.releases.resolve(None)
        print("releases.resolve() warm, per call ms:", round((time.perf_counter() - t0) * 1000 / 20, 2))


asyncio.run(main())
