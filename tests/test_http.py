import asyncio
import gzip

import httpx
import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.http import CATALOG, INDEX, CranHTTP, same_content


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
        "/web/packages/a/DESCRIPTION?x=1",
        "/web/packages/a/../DESCRIPTION",
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
        source._cache[INDEX] = (0, a, {})
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


async def test_oversized_archive_failures_are_narrowly_cached_and_expire(monkeypatch):
    class TinyArchiveHTTP(CranHTTP):
        @staticmethod
        def _response_limit(path):
            return 8 if path.endswith(".tar.gz") else CranHTTP._response_limit(path)

    now = [1000.0]
    monkeypatch.setattr("cran_knowledge_mcp.http.monotonic", lambda: now[0])
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=b"x" * 9)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = TinyArchiveHTTP(client)
        first = "/src/contrib/ExamplePkg_1.0.tar.gz"
        other = "/src/contrib/OtherPkg_1.0.tar.gz"
        with pytest.raises(KnowledgeError) as original:
            await source.fetch(first)
        assert original.value.code == "source_too_large" and not original.value.cached
        with pytest.raises(KnowledgeError) as cached:
            await source.fetch(first)
        assert cached.value.code == "source_too_large" and cached.value.cached
        with pytest.raises(KnowledgeError):
            await source.fetch(other)
        assert calls == [first, other]
        now[0] += 61
        with pytest.raises(KnowledgeError) as expired:
            await source.fetch(first)
        assert expired.value.code == "source_too_large" and not expired.value.cached
        assert calls == [first, other, first]


async def test_oversized_failure_cache_has_a_hard_entry_bound(monkeypatch):
    class TinyArchiveHTTP(CranHTTP):
        @staticmethod
        def _response_limit(path):
            return 1 if path.endswith(".tar.gz") else CranHTTP._response_limit(path)

    monkeypatch.setattr("cran_knowledge_mcp.http.OVERSIZED_FAILURE_CAPACITY", 2)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"xx"))
    ) as client:
        source = TinyArchiveHTTP(client)
        paths = [f"/src/contrib/ExamplePkg{n}_1.0.tar.gz" for n in range(3)]
        for path in paths:
            with pytest.raises(KnowledgeError, match="exceeds limit"):
                await source.fetch(path)
    assert list(source._oversized_failures) == paths[-2:]


def test_repository_response_limits_remain_bounded_by_route():
    assert CranHTTP._response_limit("/src/contrib/ExamplePkg_1.0.tar.gz") == 25 << 20
    assert CranHTTP._response_limit("/web/packages/ExamplePkg/DESCRIPTION") == 2 << 20


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


def expire(source, path):
    _, item, validators = source._cache[path]
    source._cache[path] = (0, item, validators)


async def test_expired_entry_is_revalidated_and_304_reuses_the_same_body():
    calls = []

    def handler(request):
        calls.append(request)
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304, headers={"ETag": '"v1"'})
        return httpx.Response(
            200,
            content=b"index",
            headers={"ETag": '"v1"', "Last-Modified": "Thu, 23 Oct 2026 10:00:00 GMT"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = CranHTTP(client)
        first = await source.fetch(INDEX)
        expire(source, INDEX)
        second = await source.fetch(INDEX)
    assert calls[1].headers["If-None-Match"] == '"v1"'
    assert calls[1].headers["If-Modified-Since"] == "Thu, 23 Oct 2026 10:00:00 GMT"
    assert second is not first and second.body is first.body
    assert same_content(first, second)
    assert second.checked_at >= first.checked_at


async def test_failed_revalidation_never_serves_stale_content():
    responses = iter(
        [httpx.Response(200, content=b"index", headers={"ETag": '"v1"'})]
        + [httpx.Response(503)] * 2
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: next(responses))
    ) as client:
        source = CranHTTP(client)
        await source.fetch(INDEX)
        expire(source, INDEX)
        with pytest.raises(KnowledgeError) as error:
            await source.fetch(INDEX)
    assert error.value.code == "source_unavailable"
    assert INDEX not in source._cache


async def test_compressed_index_is_expanded_with_a_bound(monkeypatch):
    body = gzip.compress(b"Package: A\nVersion: 1.0\n" * 10)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    ) as client:
        artifact = await CranHTTP(client).fetch(INDEX + ".gz")
        assert artifact.body.startswith(b"Package: A")
        assert artifact.source_url.endswith("/src/contrib/PACKAGES.gz")
        monkeypatch.setattr("cran_knowledge_mcp.http.MAX_EXPANDED_INDEX", 32)
        with pytest.raises(KnowledgeError) as error:
            await CranHTTP(client).fetch(INDEX + ".gz")
    assert error.value.code == "source_too_large"


async def test_cran_index_parse_survives_304_with_new_provenance(service):
    api, _, calls = service
    cran = await api.provider("cran")
    records, first = await cran.index()
    expire(api.http, INDEX + ".gz")
    validators = api.http._cache[INDEX + ".gz"][2]
    assert validators == {}  # the fixture sends no ETag, so the index is refetched in full
    api.http._cache[INDEX + ".gz"] = (0, first, {"etag": '"fixture"'})

    original = api.http.client._transport.handler

    def not_modified(request):
        calls.append(request)
        return httpx.Response(304)

    api.http.client._transport.handler = not_modified
    try:
        again, second = await cran.index()
    finally:
        api.http.client._transport.handler = original
    assert again is records
    assert second is not first and second.body is first.body
