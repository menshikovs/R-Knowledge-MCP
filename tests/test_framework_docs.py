import httpx
import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.providers.framework_docs import DOCS, FrameworkDocsProvider


@pytest.mark.parametrize(
    ("topic", "path"),
    [
        ("reactivity", "/r/articles/build/reactivity-overview/"),
        ("modules", "/r/articles/improve/modules/"),
        ("async", "/r/articles/improve/nonblocking/"),
    ],
)
async def test_shiny_catalog_uses_canonical_urls_and_retrieves_without_redirect(topic, path):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "shiny.posit.co"
        assert request.url.path == path
        return httpx.Response(200, text="<main>official Shiny guidance</main>")

    assert DOCS["shiny"][topic] == f"https://shiny.posit.co{path}"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await FrameworkDocsProvider(client).get_docs("shiny", topic)
    assert result["source_url"] == f"https://shiny.posit.co{path}"
    assert result["verification_status"] == "retrieved_official_documentation"
    assert "official Shiny guidance" in result["text"]
    assert len(calls) == 1


@pytest.mark.parametrize("topic", ["reactivity", "modules", "async"])
async def test_shiny_redirects_are_rejected_without_following_them(topic):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            301,
            headers={"location": DOCS["shiny"][topic] + "redirected"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KnowledgeError, match="HTTP 301"):
            await FrameworkDocsProvider(client).get_docs("shiny", topic)
    assert len(calls) == 1
    assert calls[0].url == httpx.URL(DOCS["shiny"][topic])


async def test_official_framework_docs_use_fixed_urls_extract_text_and_cache():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "positron.posit.co"
        assert request.url.path == "/managing-interpreters.html"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            text=(
                "<html><nav>Nav</nav><main><h1>Sessions</h1>"
                "<p>R session guidance</p></main><script>secret()</script></html>"
            ),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FrameworkDocsProvider(client)
        result = await provider.get_docs("positron", "interpreters")
        again = await provider.get_docs("positron", "interpreters")
    assert result["verification_status"] == "retrieved_official_documentation"
    assert result["source_url"].startswith("https://positron.posit.co/")
    assert "R session guidance" in result["text"]
    assert "secret()" not in result["text"]
    assert again["cache_status"] == "hit"
    assert len(calls) == 1


async def test_framework_doc_topic_cannot_select_arbitrary_url():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("network"))
    ) as client:
        provider = FrameworkDocsProvider(client)
        with pytest.raises(KnowledgeError, match="Unsupported topic"):
            await provider.get_docs("quarto", "https://127.0.0.1/admin")


@pytest.mark.parametrize("status", [404, 503])
async def test_framework_upstream_errors_are_explicit(status):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, text="unavailable"))
    ) as client:
        provider = FrameworkDocsProvider(client)
        with pytest.raises(KnowledgeError, match=str(status)) as error:
            await provider.get_docs("shiny", "modules")
    assert error.value.code == ("not_found" if status == 404 else "source_unavailable")
    assert error.value.source_url == "https://shiny.posit.co/r/articles/improve/modules/"
