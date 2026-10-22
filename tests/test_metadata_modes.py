from __future__ import annotations

import gzip
import io
import random
import tarfile
from time import perf_counter

import httpx
import pytest
from conftest import DESCRIPTION, INDEX_TEXT

from cran_knowledge_mcp.http import INDEX, CranHTTP
from cran_knowledge_mcp.service import KnowledgeService, bounded

PACKAGE = "ExamplePkg"
VERSION = "2.10-1"
DESCRIPTION_PATH = f"/web/packages/{PACKAGE}/DESCRIPTION"
ARCHIVE_PATH = f"/src/contrib/{PACKAGE}_{VERSION}.tar.gz"


async def test_cran_lightweight_description_matches_index_without_fetching_archive(service):
    api, _, calls = service
    result = await api.get_package_info(PACKAGE, verify_archive=False)
    assert result["package_version"] == VERSION
    assert result["latest_cran_version"] == VERSION
    assert result["description"] == "A synthetic fixture for tests."
    assert result["authors"] == "Test Author"
    assert result["metadata_verification_level"] == "description_version_matched"
    assert result["verification_status"] == "verified"
    assert [request.url.path for request in calls] == [INDEX, DESCRIPTION_PATH]
    assert [source["source_url"].rsplit("/", 1)[-1] for source in result["sources"]] == [
        "PACKAGES",
        "DESCRIPTION",
    ]


async def test_default_cran_info_keeps_deep_archive_verification(service):
    api, _, calls = service
    result = await api.get_package_info(PACKAGE)
    assert result["metadata_verification_level"] == "description_version_matched"
    assert result["verification_status"] == "verified"
    assert [request.url.path for request in calls] == [INDEX, ARCHIVE_PATH]


async def test_lightweight_cran_info_never_opens_an_oversized_archive_stream():
    class LargeArchiveStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(26 * 16):
                yield b"x" * (1 << 20)

        async def aclose(self):
            return None

    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == INDEX:
            return httpx.Response(200, content=INDEX_TEXT.encode())
        if request.url.path == DESCRIPTION_PATH:
            return httpx.Response(200, content=DESCRIPTION.encode())
        if request.url.path == ARCHIVE_PATH:
            return httpx.Response(200, stream=LargeArchiveStream())
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KnowledgeService(CranHTTP(client)).get_package_info(
            PACKAGE, verify_archive=False
        )
    assert result["metadata_verification_level"] == "description_version_matched"
    assert calls == [INDEX, DESCRIPTION_PATH]


async def test_missing_lightweight_description_returns_explicit_index_partial(service):
    api, routes, calls = service
    routes.pop(DESCRIPTION_PATH)
    result = await api.get_package_info(PACKAGE, verify_archive=False)
    assert result["verification_status"] == "partial"
    assert result["metadata_verification_level"] == "index_verified"
    assert result["metadata_details_status"] == "unavailable"
    assert result["metadata_error"]["code"] == "not_found"
    assert result["metadata_error"]["source_url"].endswith(DESCRIPTION_PATH)
    assert result["metadata_error"]["attempted_at"]
    assert "description" in result["metadata_fields_missing"]
    assert [request.url.path for request in calls] == [INDEX, DESCRIPTION_PATH]


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (DESCRIPTION.replace(VERSION, "9.0").encode(), "version_mismatch"),
        (b"not a valid DCF record", "invalid_source"),
        (b"", "invalid_source"),
    ],
)
async def test_lightweight_description_mismatch_or_malformed_is_explicit(
    service, body, expected_code
):
    api, routes, _ = service
    routes[DESCRIPTION_PATH] = body
    result = await api.get_package_info(PACKAGE, verify_archive=False)
    assert result["error"]["code"] == expected_code
    assert result["source_url"].endswith(DESCRIPTION_PATH)
    assert {s["source_url"].rsplit("/", 1)[-1] for s in result["sources"]} == {
        "PACKAGES",
        "DESCRIPTION",
    }


def _archive_with_payload(size: int) -> bytes:
    payload = random.Random(31).randbytes(size)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, body in (
            (f"{PACKAGE}/DESCRIPTION", DESCRIPTION.encode()),
            (f"{PACKAGE}/data/payload.bin", payload),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(body)
            tar.addfile(member, io.BytesIO(body))
    return gzip.compress(buffer.getvalue())


async def _measured_cran_metadata(verify_archive: bool, payload_size: int):
    archive_body = _archive_with_payload(payload_size)
    description_body = DESCRIPTION.encode()
    calls = []
    transferred = 0
    routes = {
        INDEX: INDEX_TEXT.encode(),
        DESCRIPTION_PATH: description_body,
        ARCHIVE_PATH: archive_body,
    }

    def handler(request):
        nonlocal transferred
        calls.append(request.url.path)
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        transferred += len(body)
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = KnowledgeService(CranHTTP(client))
        started = perf_counter()
        result = await api.get_package_info(PACKAGE, verify_archive=verify_archive)
        elapsed = perf_counter() - started
        request_count = len(calls)
        await api.get_package_info(PACKAGE, verify_archive=verify_archive)
        cache_hits = request_count - (len(calls) - request_count)
    return {
        "result": result,
        "requests": calls[:request_count],
        "request_count": request_count,
        "cache_hits": cache_hits,
        "elapsed_seconds": elapsed,
        "bytes": transferred,
        "archive_bytes": len(archive_body),
        "archive_downloads": sum(path == ARCHIVE_PATH for path in calls[:request_count]),
    }


@pytest.mark.parametrize(("scenario", "payload_size"), [("small", 2048), ("medium", 180_000)])
async def test_mocked_cran_transfer_measurements(scenario, payload_size):
    lightweight = await _measured_cran_metadata(False, payload_size)
    deep = await _measured_cran_metadata(True, payload_size)
    assert lightweight["result"]["metadata_verification_level"] == "description_version_matched"
    assert deep["result"]["metadata_verification_level"] == "description_version_matched"
    assert lightweight["requests"] == [INDEX, DESCRIPTION_PATH]
    assert deep["requests"] == [INDEX, ARCHIVE_PATH]
    assert lightweight["bytes"] == len(INDEX_TEXT.encode()) + len(DESCRIPTION.encode())
    assert deep["bytes"] == len(INDEX_TEXT.encode()) + deep["archive_bytes"]
    assert lightweight["bytes"] < deep["bytes"]
    assert lightweight["archive_downloads"] == 0 and deep["archive_downloads"] == 1
    assert lightweight["request_count"] == deep["request_count"] == 2
    assert lightweight["cache_hits"] == deep["cache_hits"] == 2
    assert lightweight["elapsed_seconds"] >= 0 and deep["elapsed_seconds"] >= 0
    assert scenario in {"small", "medium"}


async def test_cran_lightweight_unavailable_description_is_not_misreported():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == INDEX:
            return httpx.Response(200, content=INDEX_TEXT.encode())
        if request.url.path == DESCRIPTION_PATH:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KnowledgeService(CranHTTP(client)).get_package_info(
            PACKAGE, verify_archive=False
        )
    assert result["error"]["code"] == "source_unavailable"
    assert result["source_url"].endswith(DESCRIPTION_PATH)
    assert calls == [INDEX, DESCRIPTION_PATH, DESCRIPTION_PATH]


async def test_oversized_archive_error_provenance_is_reported_as_cached(monkeypatch):
    class TinyArchiveHTTP(CranHTTP):
        @staticmethod
        def _response_limit(path):
            return 8 if path.endswith(".tar.gz") else CranHTTP._response_limit(path)

    now = [1000.0]
    monkeypatch.setattr("cran_knowledge_mcp.http.monotonic", lambda: now[0])
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == INDEX:
            return httpx.Response(200, content=INDEX_TEXT.encode())
        return httpx.Response(200, content=b"x" * 9)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = KnowledgeService(TinyArchiveHTTP(client))
        first = await api.get_package_info(PACKAGE)
        second = await api.get_package_info(PACKAGE)
    assert first["error"]["code"] == "source_too_large"
    assert first["source_url"].endswith(ARCHIVE_PATH)
    assert "cached" not in first["error"]
    assert second["error"]["cached"] is True
    assert calls == [INDEX, ARCHIVE_PATH]


async def test_lightweight_mode_rejects_non_boolean_flag(service):
    api, _, calls = service
    result = await bounded(api.get_package_info(PACKAGE, verify_archive="false"))
    assert result["error"]["code"] == "invalid_input"
    assert calls == []
