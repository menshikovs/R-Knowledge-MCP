"""Run the bounded, read-only checks against official R documentation sources."""

import asyncio

from cran_knowledge_mcp.upstream_smoke import main

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
