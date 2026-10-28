import asyncio
import json
import time

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.service import KnowledgeService


def brief(r, *keys):
    if "error" in r:
        return ("ERROR", r["error"]["code"], r["error"]["message"][:90])
    return {k: r.get(k) for k in keys}


async def main():
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        for v in ("release", "devel", "3.20", "9.99"):
            try:
                rel = await svc.releases.resolve(v)
                print("resolve", v, "->", rel.version, rel.channel, "R", rel.r_version)
            except Exception as e:
                print("resolve", v, "-> ERR", getattr(e, "code", e))
        print("for_r 4.5.2 ->", json.dumps({k: v for k, v in (await svc.get_bioconductor_version("4.5.2")).items() if k in ("recommended_bioc_version", "releases", "warnings")}))
        print("for_r 3.0.0 ->", json.dumps({k: v for k, v in (await svc.get_bioconductor_version("3.0.0")).items() if k in ("recommended_bioc_version", "warnings")}))
        t0 = time.time()
        r = await svc.list_package_functions("BiocGenerics", "bioconductor", None, limit=50)
        print("BiocGenerics discovery:", brief(r, "package_version", "bioc_version", "channel", "verification_status", "issues"), round(time.time() - t0, 1), "s")
        r = await svc.get_versioned_function_docs("BiocGenerics", "updateObject", repository="bioconductor")
        print("BiocGenerics::updateObject docs:", brief(r, "package_version", "bioc_version", "verification_status"))
        r = await svc.get_versioned_function_docs("BiocGenerics", "updateObject", repository="bioconductor", bioc_version="3.20")
        print("... bioc 3.20:", brief(r, "package_version", "bioc_version", "verification_status"))
        r = await svc.get_package("DESeq2", "bioconductor", None, ["metadata", "dependencies"], False, True)
        print("DESeq2 get_package:", brief(r, "package_version", "bioc_version", "verification_status", "errors"))
        r = await svc.check_r_compatibility("4.2.0", "DESeq2", "bioconductor")
        print("DESeq2 compat R 4.2.0:", brief(r, "bioc_version", "compatibility_status", "warnings"))
        r = await svc.check_r_compatibility("4.5.2", "ggplot2")
        print("ggplot2 compat R 4.5.2:", brief(r, "package_version", "compatibility_status"))
        r = await svc.check_r_compatibility("3.6.0", "ggplot2")
        print("ggplot2 compat R 3.6.0:", brief(r, "package_version", "compatibility_status", "warnings"))
        r = await svc.search_packages("DESeq2", 3, 0, "all")
        print("search all DESeq2:", [(x["package"], x["repository"]) for x in r["results"]], r["verification_status"])
        r = await svc.check_package_version("ggplot2", "3.5.1")
        print("check_package_version ggplot2 3.5.1:", brief(r, "latest_cran_version", "comparison"))
        r = await svc.get_package("S4Vectors", "all", None, ["metadata"], False)
        print("S4Vectors repo=all:", brief(r, "verification_status", "errors"))


asyncio.run(main())
