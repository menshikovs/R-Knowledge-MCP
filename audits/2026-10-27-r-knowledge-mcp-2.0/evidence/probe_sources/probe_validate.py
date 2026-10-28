import asyncio
import re

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.service import KnowledgeService


async def main():
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        cran = await svc.provider("cran")
        meta, files, art, idx = await cran.source("validate")
        print("validate current version:", meta["Version"])
        hits = [n for n, b in files.items() if n.endswith(".Rd") and b"violations" in b]
        print("Rd files mentioning 'violations':", hits[:8])
        for n in hits[:3]:
            text = files[n].decode("utf-8", "replace")
            print(n, "aliases:", re.findall(r"\\alias\{([^}]*)\}", text)[:12])
        r = await svc.list_package_functions("validate", query="violations", limit=10)
        print("discovery(query=violations):", [(m["name"], m["kind"], m["match_type"]) for m in r["matches"]], r["verification_status"], r["issues"])
        r = await svc.get_function_docs("validate", "violations")
        print("get_function_docs(violations):", r.get("error", {}).get("code"), (r.get("error") or {}).get("closest_aliases"))


asyncio.run(main())
