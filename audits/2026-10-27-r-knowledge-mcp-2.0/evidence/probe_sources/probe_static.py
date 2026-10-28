"""Static-analyzer worst-case timing at the documented 256 KiB source cap (no R is executed)."""
import asyncio
import time

import httpx

from cran_knowledge_mcp.http import CranHTTP
from cran_knowledge_mcp.service import KnowledgeService

CAP = 256 << 10


def cases():
    yield "repeated ggplot( calls", "ggplot(df, aes(x, y)) + geom_point()\n" * (CAP // 38)
    yield "open parens", "(" * CAP
    yield "nested calls f(f(f(", "f(" * (CAP // 2)
    yield "pipe chain", "df |> filter(x > 1) " * (CAP // 20)
    yield "long string", 'x <- "' + "a" * (CAP - 10) + '"'
    yield "many assignments", "a <- b\n" * (CAP // 7)
    yield "unicode", "é" * (CAP // 2 - 10)
    yield "backticks", "`" * CAP
    yield "brackets [[ [[", "x[[" * (CAP // 3)


async def main():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    async with client:
        svc = KnowledgeService(CranHTTP(client))
        for label, source in cases():
            for kind, fn in (("ggplot", svc.analyze_ggplot_code), ("tidyr", svc.analyze_tidyr_pipeline), ("knitr", svc.analyze_knitr_chunks)):
                t0 = time.perf_counter()
                try:
                    r = await fn(source)
                    out = r.get("verification_status") or "ok"
                except Exception as exc:  # noqa: BLE001
                    out = type(exc).__name__ + ":" + getattr(exc, "code", "")
                print(f"{label:26} {kind:7} {(time.perf_counter() - t0) * 1000:9.1f} ms  {out}")


asyncio.run(main())
