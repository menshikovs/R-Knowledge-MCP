"""Where are conflicts detected? Free prose vs explicit constraints vs structured fields."""
import asyncio
import json
import sys

sys.path.insert(0, sys.argv[1])
import fx  # noqa: E402

from cran_knowledge_mcp.http import CranHTTP  # noqa: E402
from cran_knowledge_mcp.prompt_intelligence import PromptIntelligence  # noqa: E402
from cran_knowledge_mcp.service import KnowledgeService  # noqa: E402


async def main():
    client, _ = fx.make_client()
    async with client:
        pi = PromptIntelligence(KnowledgeService(CranHTTP(client)))
        tries = {
            "prose only": dict(request="Write a query in PostgreSQL and also make it work in MySQL on the same connection"),
            "explicit constraints": dict(request="Query the orders table", constraints=["Use PostgreSQL", "Use MySQL"]),
            "read-only vs write (constraints)": dict(request="Update customer rows in the database", constraints=["read-only connection", "must write updated rows"]),
            "structured_context dialect": dict(request="Query the orders table", structured_context={"sql": {"dialect": "postgresql"}}, constraints=["Use MySQL"]),
        }
        for label, kw in tries.items():
            try:
                o = await pi.build_r_prompt(**kw)
                print(f"{label:36} conflicts: {json.dumps(o['conflicts'], default=str)[:300]}")
            except Exception as exc:  # noqa: BLE001
                print(f"{label:36} {type(exc).__name__}: {str(exc)[:160]}")


asyncio.run(main())
