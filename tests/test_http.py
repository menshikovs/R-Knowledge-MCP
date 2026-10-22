import asyncio

import httpx
import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.http import CATALOG, INDEX, CranHTTP


@pytest.mark.parametrize("status", [301, 302, 404, 429, 500, 503])
async def test_http_errors_no_redirects_or_error_cache(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = CranHTTP(client)
        for _ in range(2):
            with pytest.raises(KnowledgeError) as error:
                await source.fetch(INDEX)
            assert error.value.source_url.endswith(INDEX)
        assert len(calls) == (4 if status in (500, 503) else 2)
        assert all(c.url.host == "cran.r-project.org" for c in calls)


async def test_small_retry_after_is_honored_for_one_retry():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=b"index")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        artifact = await CranHTTP(client).fetch(INDEX)
    assert artifact.body == b"index"
    assert len(calls) == 2


async def test_long_retry_after_is_reported_without_early_retry():
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (
                calls.append(request) or httpx.Response(429, headers={"Retry-After": "17"})
            )
        )
    ) as client:
        with pytest.raises(KnowledgeError, match="17 seconds") as error:
            await CranHTTP(client).fetch(INDEX)
    assert error.value.code == "rate_limited"
    assert len(calls) == 1


async def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KnowledgeError, match="timed out"):
            await CranHTTP(client).fetch(INDEX)


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.test/",
        "//localhost/x",
        "/src/contrib/../x",
        "/src/contrib/a_1.tar.gz?x=1",
        "/web/packages/a",
    ],
)
async def test_route_allowlist(path):
    async with httpx.AsyncClient() as client:
        with pytest.raises(KnowledgeError, match="fixed repository"):
            await CranHTTP(client).fetch(path)


async def test_cache_expiry_and_concurrent_misses():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"index")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = CranHTTP(client)
        a, b = await asyncio.gather(source.fetch(INDEX), source.fetch(INDEX))
        assert a is b and len(calls) == 1
        source._cache[INDEX] = (0, a)
        c = await source.fetch(INDEX)
        assert c is not a and len(calls) == 2


async def test_unrelated_routes_download_concurrently():
    class DelayedTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def handle_async_request(self, request):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.02)
                return httpx.Response(200, content=request.url.path.encode())
            finally:
                self.active -= 1

    transport = DelayedTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        source = CranHTTP(client)
        await asyncio.gather(source.fetch(INDEX), source.fetch(CATALOG))
    assert transport.max_active == 2


async def test_download_size_limit():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"x" * ((16 << 20) + 1))
        )
    ) as client:
        with pytest.raises(KnowledgeError, match="exceeds limit"):
            await CranHTTP(client).fetch(INDEX)


async def test_cache_byte_budget():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"large"))
    ) as client:
        source = CranHTTP(client, cache_bytes=4)
        await source.fetch(INDEX)
        assert not source._cache


async def test_environment_config_applies_to_requests_and_cache(monkeypatch):
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "42")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
        source = CranHTTP(c)
        await source.fetch(INDEX)
        assert source.request_timeout == 7.5
        assert source.ttl == 42
