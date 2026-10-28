import asyncio, os, sys
from cran_knowledge_mcp.server import create_server
async def n(**env):
    for k, v in env.items(): os.environ[k] = v
    s = create_server()
    t = await s.list_tools(); p = await s.list_prompts(); r = await s.list_resources()
    for k in env: del os.environ[k]
    return len(t), len(p), len(r), sorted(x.name for x in t)[:0]
for env in ({}, {"FUNCTION_DISCOVERY_ENABLED": "false"}, {"PROMPT_INTELLIGENCE_ENABLED": "false"}, {"MCP_TOOLSET": "legacy"}, {"MCP_TOOLSET": "legacy", "FUNCTION_DISCOVERY_ENABLED": "false"}):
    print(env, "-> tools, prompts, resources:", asyncio.run(n(**env))[:3])
try:
    os.environ["MCP_TOOLSET"] = "bogus"; create_server()
except Exception as e: print("bogus toolset ->", type(e).__name__, str(e)[:80])
