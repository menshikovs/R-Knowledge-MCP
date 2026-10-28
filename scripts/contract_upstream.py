"""Nightly real-upstream contract checks (see cran_knowledge_mcp.upstream_contract)."""

import asyncio

from cran_knowledge_mcp.upstream_contract import main

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
