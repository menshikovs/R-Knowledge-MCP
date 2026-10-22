import httpx
import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.providers.framework_docs import FrameworkDocsProvider


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
    assert error.value.source_url == "https://shiny.posit.co/r/articles/improve/modules"
