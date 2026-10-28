import asyncio
import re

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.parsers import parse_namespace
from cran_knowledge_mcp.service import KnowledgeService

ENC = re.compile(rb"\\encoding\{([^}]*)\}")


async def main():
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        cran = await svc.provider("cran")
        for pkg in ("MASS", "cluster", "survival"):
            meta, files, art, idx = await cran.source(pkg)
            ns = files[pkg + "/NAMESPACE"].decode("utf-8", "replace")
            print("==", pkg, meta["Version"], "DESCRIPTION Encoding:", meta.get("Encoding"))
            r = parse_namespace(ns)
            print(" parse issues:", r["issues"])
            print(" useDynLib lines:", [line.strip() for line in ns.splitlines() if "useDynLib" in line])
            if pkg == "cluster":
                for n, b in files.items():
                    if n.endswith(".Rd"):
                        try:
                            b.decode(meta.get("Encoding", "UTF-8"))
                        except UnicodeError:
                            m = ENC.search(b)
                            print(" undecodable under DESCRIPTION encoding:", n, "| in-file encoding declaration:", m.group(1) if m else None)
            if pkg == "survival":
                for line in ns.splitlines():
                    if re.match(r"\s*(if|else|\{|\})", line):
                        print("   conditional line:", line.strip()[:90])


asyncio.run(main())
