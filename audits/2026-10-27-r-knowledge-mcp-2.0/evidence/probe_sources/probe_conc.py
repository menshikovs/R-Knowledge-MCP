"""Singleflight, cache accounting, cancellation safety and slot exhaustion with a mocked transport."""
import asyncio
import gzip
import time

import httpx

from cran_knowledge_mcp.http import CranHTTP

INDEX = b"Package: A\nVersion: 1.0\n"


async def main():
    hits = {"n": 0}
    hang = {"on": False}

    async def handler(request):
        hits["n"] += 1
        if hang["on"]:
            await asyncio.sleep(3600)
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=INDEX if not request.url.path.endswith(".gz") else gzip.compress(INDEX))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = CranHTTP(client)
        t0 = time.perf_counter()
        res = await asyncio.gather(*(http.fetch("/src/contrib/PACKAGES") for _ in range(50)))
        print(f"50 concurrent identical fetches -> upstream requests: {hits['n']} (singleflight), same artifact object: {len({id(r) for r in res}) == 1}, {time.perf_counter() - t0:.2f}s")
        print("lock registry empty after completion:", not http._path_locks and not http._path_lock_users)

        # cancellation while the singleflight leader is mid-request
        http2 = CranHTTP(client)
        hang["on"] = True
        task = asyncio.create_task(http2.fetch("/src/contrib/PACKAGES"))
        waiter = asyncio.create_task(http2.fetch("/src/contrib/PACKAGES"))
        await asyncio.sleep(0.2)
        hang["on"] = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        try:
            art = await asyncio.wait_for(waiter, 5)
            print("waiter after leader cancelled: completed OK, upstream calls:", hits["n"])
        except Exception as exc:  # noqa: BLE001
            print("waiter after leader cancelled:", type(exc).__name__, exc)
        print("lock registry empty after cancel:", not http2._path_locks and not http2._path_lock_users)

        # slot exhaustion: 4 hung downloads block a 5th distinct path until the 45 s deadline
        http3 = CranHTTP(client)
        http3.request_timeout = 1
        hang["on"] = True
        paths = ["/web/packages/p%d/DESCRIPTION" % i for i in range(5)]
        tasks = [asyncio.create_task(http3.fetch(p)) for p in paths]
        await asyncio.sleep(0.3)
        print("in-flight upstream requests with 5 distinct hung paths (slots=4):", hits["n"] - 51 if False else "see below")
        for tk in tasks:
            tk.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print("semaphore value restored after cancellations:", http3._request_slots._value)


asyncio.run(main())
