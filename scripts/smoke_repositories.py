"""Opt-in live CRAN/Bioconductor validation, with no assumed release numbers."""

import asyncio
import json

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.service import KnowledgeService, bounded


async def main():
    async with make_client() as client:
        api = KnowledgeService(CranHTTP(client))
        release = await api.releases.resolve("release")
        checks = [
            ("cran_search", lambda: api.search_packages("ggplot2", repository="cran")),
            ("bioc_search", lambda: api.search_packages("DESeq2", repository="bioconductor")),
            ("bioc_info", lambda: api.get_package_info("DESeq2", "bioconductor")),
            ("bioc_dependencies", lambda: api.get_dependencies("DESeq2", "bioconductor")),
            (
                "bioc_docs",
                lambda: api.get_function_docs("DESeq2", "DESeq", repository="bioconductor"),
            ),
            ("bioc_vignettes", lambda: api.get_package_vignettes("DESeq2", "bioconductor")),
            ("cran_vignettes", lambda: api.get_package_vignettes("ggplot2")),
            ("release_map", lambda: api.get_bioconductor_version(release.r_version)),
            ("compatibility", lambda: api.check_package_compatibility("DESeq2", release.r_version)),
            (
                "devel",
                lambda: api.search_packages(
                    "DESeq2", repository="bioconductor", bioc_version="devel"
                ),
            ),
            ("all", lambda: api.search_packages("ggplot2", repository="all")),
        ]
        for name, operation in checks:
            result = await bounded(operation())
            assert "error" not in result, result
            assert result["verification_status"] == "verified", result
            print(
                json.dumps(
                    {
                        "check": name,
                        "status": result["verification_status"],
                        "bioc_version": result.get("bioc_version"),
                        "package_version": result.get("package_version"),
                        "compatibility_status": result.get("compatibility_status"),
                        "sources": result["sources"],
                    }
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
