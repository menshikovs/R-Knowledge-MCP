import asyncio

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.service import KnowledgeService


async def main():
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        for fn in ("agnes", "plantTraits", "daisy"):
            r = await svc.get_function_docs("cluster", fn)
            err = r.get("error")
            print("cluster::" + fn, "->", "OK len=%s" % r.get("total_characters") if not err else (err["code"], err["message"]))
        r = await svc.get_function_docs("MASS", "lm.ridge")
        print("MASS::lm.ridge ->", "OK" if "error" not in r else r["error"]["code"])


asyncio.run(main())
