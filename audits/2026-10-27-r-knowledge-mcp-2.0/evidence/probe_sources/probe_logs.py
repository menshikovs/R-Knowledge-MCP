"""Does default INFO logging (as configured by main()) record upstream URLs containing user text? Mocked transport only."""
import asyncio
import io
import json
import logging

import httpx

from cran_knowledge_mcp.providers.context7 import Context7Provider

buffer = io.StringIO()
handler = logging.StreamHandler(buffer)
logging.basicConfig(level="INFO", handlers=[handler], force=True)  # same level/handler type as server.main()


def route(request):
    if request.url.path.endswith("/libs/search"):
        return httpx.Response(200, json={"results": [{"id": "/own/ex", "title": "ex"}]})
    return httpx.Response(200, json={"infoSnippets": [{"content": "doc", "title": "t"}], "codeSnippets": []})


async def main():
    async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
        provider = Context7Provider(client, "ctx7sk-SECRETSECRETSECRET")
        await provider.get_context7_docs("ex", "1.0", "https://github.com/own/ex", "How do I read the customer file acme_q3_payroll.csv with ex?", "cran", None)


asyncio.run(main())
log = buffer.getvalue()
print(log)
print("API key in log:", "SECRETSECRET" in log)
print("user question text in log:", "acme_q3_payroll" in log)
