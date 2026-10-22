"""Opt-in live CRAN smoke check; never part of the offline unit suite.

Run from an installed checkout: python scripts/smoke_cran.py
"""

import asyncio
import json

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.service import KnowledgeService, bounded


async def main():
    async with make_client() as client:
        api = KnowledgeService(CranHTTP(client))
        info = await bounded(api.get_package_info("dplyr"))
        assert "error" not in info, info
        operations = {
            "search_packages": api.search_packages("dplyr"),
            "get_dependencies": api.get_dependencies("dplyr"),
            "get_function_docs": api.get_function_docs("dplyr", "filter"),
            "check_package_version": api.check_package_version(
                "dplyr", info["latest_cran_version"]
            ),
        }
        for name, operation in operations.items():
            result = await bounded(operation)
            assert "error" not in result, result
            print(json.dumps({"tool": name, "ok": True, "sources": result["sources"]}))
        print(
            json.dumps(
                {
                    "tool": "get_package_info",
                    "ok": True,
                    "latest_cran_version": info["latest_cran_version"],
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
