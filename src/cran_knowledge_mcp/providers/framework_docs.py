"""Fixed-catalog retrieval from official Shiny, Positron and Quarto documentation."""

import asyncio
import re
from collections import OrderedDict
from datetime import UTC, datetime
from html.parser import HTMLParser
from time import monotonic

import httpx

from ..errors import KnowledgeError

MAX_PAGE = 2 << 20
MAX_TEXT = 8 << 10
DOCS = {
    "shiny": {
        "reactivity": "https://shiny.posit.co/r/articles/build/reactivity-overview",
        "isolation": "https://shiny.posit.co/r/articles/build/isolation/",
        "modules": "https://shiny.posit.co/r/articles/improve/modules",
        "async": "https://shiny.posit.co/r/articles/improve/nonblocking",
        "basics": "https://shiny.posit.co/r/articles/start/basics/",
    },
    "positron": {
        "interpreters": "https://positron.posit.co/managing-interpreters.html",
        "r_installation": "https://positron.posit.co/r-installations.html",
        "startup": "https://positron.posit.co/interpreter-startup.html",
        "extensions": "https://positron.posit.co/extensions.html",
        "mcp": "https://positron.posit.co/assistant.html",
    },
    "quarto": {
        "r": "https://quarto.org/docs/computations/r.html",
        "projects": "https://quarto.org/docs/projects/quarto-projects.html",
        "profiles": "https://quarto.org/docs/projects/profiles.html",
        "citations": "https://quarto.org/docs/authoring/citations.html",
        "rendering": "https://quarto.org/docs/computations/r.html",
    },
}


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "svg", "nav", "header", "footer", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "svg", "nav", "header", "footer", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(" ".join(data.split()))


class FrameworkDocsProvider:
    """Only catalog identifiers select an upstream URL; caller text is never a URL."""

    def __init__(self, client: httpx.AsyncClient, ttl: int = 3600):
        self.client = client
        self.ttl = ttl
        self._cache: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()

    async def get_docs(self, framework: str, topic: str, version: str | None = None) -> dict:
        framework = framework.casefold()
        topic = topic.casefold()
        if framework not in DOCS or topic not in DOCS[framework]:
            available = DOCS.get(framework)
            raise KnowledgeError(
                "unsupported_topic",
                "Unknown official documentation topic"
                if available is None
                else f"Unsupported topic; choose one of: {', '.join(sorted(available))}",
            )
        url = DOCS[framework][topic]
        key = (framework, topic)
        now = monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            self._cache.move_to_end(key)
            result = dict(cached[1])
            result["cache_status"] = "hit"
            return result
        self._cache.pop(key, None)
        content = bytearray()
        try:
            async with asyncio.timeout(25):
                async with self.client.stream(
                    "GET",
                    url,
                    follow_redirects=False,
                    timeout=15,
                    headers={"Accept": "text/html", "Accept-Encoding": "identity"},
                ) as response:
                    if response.status_code != 200:
                        code = "not_found" if response.status_code == 404 else "source_unavailable"
                        raise KnowledgeError(
                            code,
                            (
                                f"Official {framework} documentation returned "
                                f"HTTP {response.status_code}"
                            ),
                            url,
                        )
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise KnowledgeError(
                            "invalid_source", "Unexpected documentation compression", url
                        )
                    async for chunk in response.aiter_bytes(65536):
                        content.extend(chunk)
                        if len(content) > MAX_PAGE:
                            raise KnowledgeError(
                                "source_too_large", "Official docs page exceeds 2 MiB", url
                            )
        except (httpx.HTTPError, TimeoutError) as exc:
            raise KnowledgeError(
                "source_unavailable", "Official documentation request failed or timed out", url
            ) from exc
        try:
            html = content.decode("utf-8")
            parser = _VisibleText()
            parser.feed(html)
            text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
        except (UnicodeError, ValueError) as exc:
            raise KnowledgeError(
                "invalid_source", "Official docs page could not be decoded", url
            ) from exc
        checked_at = datetime.now(UTC).isoformat()
        result = {
            "framework": framework,
            "topic": topic,
            "requested_version": version,
            "version_scope": "current_official_docs_not_version_pinned",
            "text": text[:MAX_TEXT],
            "truncated": len(text) > MAX_TEXT,
            "source_url": url,
            "checked_at": checked_at,
            "verification_status": "retrieved_official_documentation",
            "trust": "untrusted_reference_material",
            "not_executed": True,
            "cache_status": "miss",
        }
        self._cache[key] = (now + self.ttl, result)
        while len(self._cache) > 32:
            self._cache.popitem(last=False)
        return result
