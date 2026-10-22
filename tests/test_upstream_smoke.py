import httpx
import pytest

from cran_knowledge_mcp.upstream_smoke import (
    Check,
    SmokeFailure,
    UpstreamSmokeChecker,
    validate_cran_identity,
)

URL = "https://cran.r-project.org/src/contrib/PACKAGES"


async def response_for(response):
    async def handler(request):
        return response

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (301, "redirect_introduced"),
        (404, "unexpected_http_status"),
        (503, "unexpected_http_status"),
    ],
)
async def test_http_failures_are_classified_without_following_redirects(status, category):
    client = await response_for(httpx.Response(status, headers={"location": "https://evil.test"}))
    async with client:
        with pytest.raises(SmokeFailure) as error:
            await UpstreamSmokeChecker(client).fetch(Check("cran", "index", URL))
    assert error.value.category == category


async def test_successful_upstream_response_is_bounded_and_read():
    client = await response_for(
        httpx.Response(
            200,
            content=b"Package: ggplot2\nVersion: 3.5.0\n",
            headers={"content-type": "text/plain"},
        )
    )
    async with client:
        body = await UpstreamSmokeChecker(client).fetch(
            Check("cran", "index", URL, content_type="text/plain")
        )
    assert b"Package: ggplot2" in body


async def test_oversized_response_is_rejected_at_configured_limit():
    client = await response_for(httpx.Response(200, content=b"12345"))
    async with client:
        with pytest.raises(SmokeFailure) as error:
            await UpstreamSmokeChecker(client).fetch(Check("cran", "small", URL, max_bytes=4))
    assert error.value.category == "invalid_response_body"


async def test_timeout_is_reported_without_raw_transport_message():
    async def handler(request):
        raise httpx.ReadTimeout("credential=do-not-log", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(SmokeFailure) as error:
            await UpstreamSmokeChecker(client).fetch(Check("cran", "index", URL))
    assert error.value.category == "network_timeout"
    assert "do-not-log" not in str(error.value)


async def test_empty_and_unexpected_content_are_rejected():
    empty_client = await response_for(httpx.Response(200, content=b""))
    async with empty_client:
        with pytest.raises(SmokeFailure, match="empty body") as error:
            await UpstreamSmokeChecker(empty_client).fetch(Check("cran", "index", URL))
    assert error.value.category == "invalid_response_body"

    content_client = await response_for(httpx.Response(200, content=b"not the expected topic"))
    async with content_client:
        checker = UpstreamSmokeChecker(content_client)
        result = await checker.execute(
            Check("shiny", "modules", "https://shiny.posit.co/r/articles/improve/modules/"),
            lambda: checker.check_document(
                Check("shiny", "modules", "https://shiny.posit.co/r/articles/improve/modules/"),
                ("moduleServer",),
            ),
        )
    assert result["failure_category"] == "invalid_response_body"
    assert result["status"] == "failed"


def test_cran_package_identity_must_match_index_version():
    index = b"Package: ggplot2\nVersion: 3.5.0\n\n"
    description = b"Package: ggplot2\nVersion: 3.5.1\n"
    with pytest.raises(SmokeFailure) as error:
        validate_cran_identity(
            index, description, "https://cran.r-project.org/web/packages/ggplot2/DESCRIPTION"
        )
    assert error.value.category == "metadata_identity_mismatch"


async def test_only_fixed_official_routes_can_be_requested():
    client = await response_for(httpx.Response(200, content=b"no"))
    async with client:
        with pytest.raises(SmokeFailure) as error:
            await UpstreamSmokeChecker(client).fetch(
                Check("cran", "arbitrary", "https://cran.r-project.org/anything")
            )
    assert error.value.category == "local_configuration_error"


async def test_bioconductor_smoke_resolves_release_and_categories_from_official_config():
    bodies = {
        "/config.yaml": (
            b"release_version: '99.2'\n"
            b"devel_version: '99.3'\n"
            b"r_ver_for_bioc_ver:\n  '99.2': '5.2'\n  '99.3': '5.3'\n"
        ),
        "/packages/99.2/bioc/src/contrib/PACKAGES": b"Package: DESeq2\nVersion: 1.42.0\n",
        "/packages/99.2/data/annotation/src/contrib/PACKAGES": (
            b"Package: org.Hs.eg.db\nVersion: 3.19.0\n"
        ),
        "/packages/99.2/data/experiment/src/contrib/PACKAGES": (
            b"Package: airway\nVersion: 1.20.0\n"
        ),
    }
    requested_paths = []

    async def handler(request):
        requested_paths.append(request.url.path)
        return httpx.Response(
            200,
            content=bodies[request.url.path],
            headers={"content-type": "text/plain"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with client:
        await UpstreamSmokeChecker(client).check_bioconductor()
    assert requested_paths == list(bodies)
    assert all("/packages/99.2/" in path for path in requested_paths[1:])
