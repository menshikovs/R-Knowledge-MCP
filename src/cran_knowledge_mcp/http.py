"""Bounded async transport with independent fixed repository route policies."""

import asyncio
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

import httpx

from .errors import KnowledgeError

BASE = "https://cran.r-project.org"
INDEX = "/src/contrib/PACKAGES"
CATALOG = "/web/packages/available_packages_by_name.html"
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9.]{0,99}\Z")
VERSION = re.compile(r"[0-9]+(?:[.-][0-9]+)*\Z")
ARCHIVE_ROUTE = re.compile(
    r"/src/contrib/[A-Za-z][A-Za-z0-9.]{0,99}_[0-9]+(?:[.-][0-9]+)*\.tar\.gz\Z"
)


def package_name(value: str) -> str:
    if not PACKAGE.fullmatch(value):
        raise KnowledgeError("invalid_input", "Invalid R package name")
    return value


def version_parts(value: str) -> tuple[int, ...]:
    if len(value) > 100 or not VERSION.fullmatch(value):
        raise KnowledgeError("invalid_input", "Use a numeric R version, e.g. 1.2-3")
    parts = [int(x) for x in re.split(r"[.-]", value)]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


@dataclass(frozen=True)
class Artifact:
    body: bytes
    source_url: str
    checked_at: str

    def provenance(self) -> dict:
        return {
            "source_url": self.source_url,
            "checked_at": self.checked_at,
            "verification_status": "verified",
        }


class RepositoryHTTP(ABC):
    """Process-local TTL/LRU cache. Errors are never cached or replaced by stale data."""

    base_url: str

    @abstractmethod
    def allowed_path(self, path: str) -> bool:
        """Validate a relative route before constructing any URL."""

    def __init__(self, client: httpx.AsyncClient, ttl: float = 300, cache_bytes: int = 64 << 20):
        self.client = client
        self.ttl = ttl
        self.cache_bytes = cache_bytes
        self._cache: OrderedDict[str, tuple[float, Artifact]] = OrderedDict()
        self._bytes = 0
        # Serializes downloads, collapses concurrent cache misses and bounds memory in flight.
        self._lock = asyncio.Lock()

    async def fetch(self, path: str) -> Artifact:
        if not self.allowed_path(path):
            raise KnowledgeError("blocked_url", "Only fixed repository source routes are allowed")
        url = self.base_url + path
        limit = (25 if path.endswith(".tar.gz") else 16) << 20
        if path == "/config.yaml":
            limit = 1 << 20
        async with self._lock:
            now = monotonic()
            if path in self._cache:
                expires, item = self._cache[path]
                if expires > now:
                    self._cache.move_to_end(path)
                    return item
                self._bytes -= len(self._cache.pop(path)[1].body)
            try:
                async with asyncio.timeout(45):
                    async with self.client.stream(
                        "GET",
                        url,
                        follow_redirects=False,
                        timeout=15,
                        headers={"Accept-Encoding": "identity"},
                    ) as response:
                        if response.status_code != 200:
                            code = (
                                "not_found" if response.status_code == 404 else "source_unavailable"
                            )
                            raise KnowledgeError(
                                code, f"Repository HTTP {response.status_code}", url
                            )
                        if response.headers.get("content-encoding", "identity") != "identity":
                            raise KnowledgeError(
                                "invalid_source", "Unexpected HTTP compression", url
                            )
                        chunks = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            chunks.extend(chunk)
                            if len(chunks) > limit:
                                raise KnowledgeError(
                                    "source_too_large", "Repository download exceeds limit", url
                                )
            except (httpx.HTTPError, TimeoutError) as exc:
                raise KnowledgeError(
                    "source_unavailable", "Repository request failed or timed out", url
                ) from exc
            item = Artifact(bytes(chunks), url, datetime.now(UTC).isoformat())
            if len(item.body) <= self.cache_bytes:
                while self._cache and (
                    self._bytes + len(item.body) > self.cache_bytes or len(self._cache) >= 32
                ):
                    self._bytes -= len(self._cache.popitem(last=False)[1].body)
                self._cache[path] = (monotonic() + self.ttl, item)
                self._bytes += len(item.body)
            return item


class CranHTTP(RepositoryHTTP):
    base_url = BASE

    def allowed_path(self, path: str) -> bool:
        return (
            path in (INDEX, CATALOG)
            or bool(ARCHIVE_ROUTE.fullmatch(path))
            or bool(re.fullmatch(r"/web/packages/[A-Za-z][A-Za-z0-9.]{0,99}/index\.html", path))
        )


class BioconductorHTTP(RepositoryHTTP):
    base_url = "https://bioconductor.org"

    def allowed_path(self, path: str) -> bool:
        prefix = r"/packages/[0-9]+\.[0-9]+/(?:bioc|data/annotation|data/experiment)"
        return path == "/config.yaml" or bool(
            re.fullmatch(
                prefix + r"/(?:src/contrib/(?:PACKAGES|[A-Za-z][A-Za-z0-9.]{0,99}_"
                r"[0-9]+(?:[.-][0-9]+)*\.tar\.gz)|html/[A-Za-z][A-Za-z0-9.]{0,99}\.html)",
                path,
            )
        )


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=15,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        headers={
            "User-Agent": "cran-knowledge-mcp/0.1 (+https://github.com/menshikovs/R-Knowledge-MCP)"
        },
    )
