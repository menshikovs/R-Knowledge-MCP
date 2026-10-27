"""Start the real MCP server entry point with fixed fixtures instead of CRAN.

Runs inside the MCP container (mounted at /fixture). Only the HTTP transport is replaced:
every repository request is answered from /fixture/routes.json, anything else is a 404, so
the container never contacts an external host. Argument parsing, the ASGI app, uvicorn,
logging and the telemetry wrapper are the unmodified server code.
"""

import gzip
import json
import sys
from pathlib import Path

import httpx

import cran_knowledge_mcp.server as server

DATA = Path("/fixture")
ROUTES = {
    path: (DATA / name).read_bytes()
    for path, name in json.loads((DATA / "routes.json").read_text(encoding="utf-8")).items()
}


def handler(request):
    content = ROUTES.get(request.url.path)
    if content is None and request.url.path.endswith("/PACKAGES.gz"):
        plain = ROUTES.get(request.url.path.removesuffix(".gz"))
        content = gzip.compress(plain) if plain is not None else None
    return httpx.Response(404 if content is None else 200, content=content or b"")


server.make_client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
sys.argv = ["cran-knowledge-mcp", *sys.argv[1:]]
server.main()
