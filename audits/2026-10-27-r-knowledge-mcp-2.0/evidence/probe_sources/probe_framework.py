"""Three live fetches of fixed official catalog pages: how much of each page does the tool expose?"""
import asyncio
import re

import httpx

from cran_knowledge_mcp.http import make_client
from cran_knowledge_mcp.providers import framework_docs as fd


async def main():
    async with make_client() as client:
        provider = fd.FrameworkDocsProvider(client)
        for framework, topic in (("shiny", "reactivity"), ("quarto", "citations"), ("positron", "interpreters")):
            r = await provider.get_docs(framework, topic)
            # recompute the full visible-text length to show how much is cut
            async with client.stream("GET", fd.DOCS[framework][topic], headers={"Accept-Encoding": "identity"}) as resp:
                body = (await resp.aread()).decode("utf-8", "replace")
            parser = fd._VisibleText()
            parser.feed(body)
            full = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
            print(f"{framework}/{topic}: returned {len(r['text'])} chars, truncated={r['truncated']}, full visible text {len(full)} chars ({len(r['text']) / max(1, len(full)):.0%} exposed); no offset parameter exists")


asyncio.run(main())
