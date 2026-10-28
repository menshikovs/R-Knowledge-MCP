import asyncio, sys, time, json
sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
from fx import *
from cran_knowledge_mcp.http import CranHTTP
from cran_knowledge_mcp.service import KnowledgeService

async def main():
    calls = []
    client, routes = make_client(calls=calls)
    async with client:
        svc = KnowledgeService(CranHTTP(client))
        svc.bioc_http.ttl = 0.05   # emulate TTL expiry (prod default is 300 s)
        p1 = await svc.provider("bioconductor")
        await svc.get_function_docs("BEx", "bx", repository="bioconductor")
        n1 = sum("BEx_1.0.0.tar.gz" in c for c in calls)
        await asyncio.sleep(0.12)
        p2 = await svc.provider("bioconductor")
        await svc.get_function_docs("BEx", "bx", repository="bioconductor")
        n2 = sum("BEx_1.0.0.tar.gz" in c for c in calls)
        print("provider object replaced after cache expiry (unchanged upstream):", p1 is not p2)
        print("archive downloads after 2 calls:", n1, "->", n2, "(content unchanged, no ETag in mock => refetch expected anyway)")
        print("release equality across refetch:", p1.release == p2.release, "same body:", p1.release.config.body == p2.release.config.body)

        # per-call yaml parse cost: how many times is config.yaml parsed per tool call?
        import yaml
        orig = yaml.safe_load; cnt = {"n": 0}
        def counting(*a, **k):
            cnt["n"] += 1; return orig(*a, **k)
        yaml.safe_load = counting
        svc.bioc_http.ttl = 300
        for _ in range(5):
            await svc.get_function_docs("BEx", "bx", repository="bioconductor")
        yaml.safe_load = orig
        print("yaml.safe_load calls for 5 consecutive bioc tool calls:", cnt["n"])
asyncio.run(main())
