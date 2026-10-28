import asyncio, json, tempfile
from pathlib import Path
from cran_knowledge_mcp.providers.r_documentation import RDocumentationProvider
async def main():
    p = RDocumentationProvider(None, Path(tempfile.mkdtemp()) / "none.json")
    r = await p.asearch("data frame", None, 5, None)
    print(json.dumps(r, indent=1)[:1500])
asyncio.run(main())
