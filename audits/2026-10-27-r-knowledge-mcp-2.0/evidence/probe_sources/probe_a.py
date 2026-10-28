import asyncio, json, sys, time
sys.path.insert(0, __file__.rsplit("\\",1)[0].rsplit("/",1)[0])
from fx import *
from cran_knowledge_mcp.http import CranHTTP
from cran_knowledge_mcp.service import KnowledgeService

async def main():
    client, routes = make_client()
    async with client:
        svc = KnowledgeService(CranHTTP(client))
        print("== A. version equivalence: discovery vs docs (current=2.10-1)")
        for v in ("2.10-1", "2.10.1", "2.10-1.0", "2.10-01"):
            d = await svc.list_package_functions("Ex", package_version=v) if False else None
            try:
                d = await svc.list_package_functions("Ex", package_version=v)
                dd = ("ok", d["package_version"]) if "error" not in d else ("ERR", d["error"]["code"]) if "error" not in d else ("ERR", d["error"]["code"])
            except Exception as e:
                dd = ("ERR", getattr(e,"code",str(e)))
            r = await svc.get_versioned_function_docs("Ex", "ex", package_version=v)
            dc = ("ok" if "error" not in r else r["error"]["code"])
            print(f"  package_version={v!r:12} discovery={dd}  docs={dc}")
        print("== E. docs_not_found / discovery output")
        r = await svc.get_versioned_function_docs("Ex", "exx")
        print(json.dumps({k: r["error"].get(k) for k in ("code","suggestions","discovery_status","lookup_stage","closest_aliases","available_aliases")}, default=str)[:600])
        d = await svc.list_package_functions("Ex")
        print("  discovery status", d["verification_status"], d["coverage"], d["issues"], d["export_patterns"])
        print("== F. search all pagination")
        res = await svc.search_packages("ex", 1, 0, "all")
        print("  all offset0:", [x["package"] for x in res["results"]], res["total"], res["next_offset"], res["verification_status"])
asyncio.run(main())
