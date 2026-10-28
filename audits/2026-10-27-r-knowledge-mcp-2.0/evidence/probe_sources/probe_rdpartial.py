import asyncio
import collections
import re

from cran_knowledge_mcp.http import CranHTTP, make_client
from cran_knowledge_mcp.parsers import _rd_complete, aliases, discovery_name
from cran_knowledge_mcp.service import KnowledgeService

TRIGGER = re.compile(r"\\(Sexpr|eval|if|ifelse|newcommand|renewcommand|RdOpts)\b")


async def main():
    async with make_client() as client:
        svc = KnowledgeService(CranHTTP(client))
        cran = await svc.provider("cran")
        for pkg in ("termr", "ggnext", "fabletools", "einops", "tidyREDCap", "RBMRB", "runner"):
            meta, files, art, idx = await cran.source(pkg)
            reasons = collections.Counter()
            examples = {}
            for name, body in files.items():
                if not name.endswith(".Rd"):
                    continue
                text = body.decode(meta.get("Encoding", "UTF-8"), "replace")
                uncommented = re.sub(r"(?<!\\)%[^\n]*", "", text)
                if _rd_complete(text):
                    names = sorted(aliases(text))
                    topics = re.findall(r"\\name\{([^{}\\]*)\}", uncommented)
                    if not (len(topics) == 1 and discovery_name(topics[0])):
                        reasons["non-literal or multiple \\name"] += 1
                    elif len(re.findall(r"\\alias\s*\{", uncommented)) != len(names):
                        reasons["alias count mismatch"] += 1
                    continue
                m = TRIGGER.search(re.sub(r"(?<!\\)%[^\n]*", "", text))
                key = "macro:" + m.group(1) if m else "unbalanced braces/depth"
                reasons[key] += 1
                if m:
                    examples.setdefault(key, text[max(0, m.start() - 20): m.end() + 60].replace("\n", " "))
            print(pkg, meta["Version"], dict(reasons))
            for k, v in examples.items():
                print("   ", k, "::", v)


asyncio.run(main())
