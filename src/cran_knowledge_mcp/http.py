"""Bounded async transport with independent fixed repository route policies."""

import asyncio
import random
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

import httpx

from .config import cache_bytes as configured_cache_bytes
from .config import cache_ttl, http_user_agent, positive_float
from .errors import KnowledgeError

BASE = "https://cran.r-project.org"
INDEX = "/src/contrib/PACKAGES"
CATALOG = "/web/packages/available_packages_by_name.html"
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9.]{0,99}\Z")
VERSION = re.compile(r"[0-9]+(?:[.-][0-9]+)*\Z")
OVERSIZED_FAILURE_TTL = 60
OVERSIZED_FAILURE_CAPACITY = 128
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

    def __init__(
        self, client: httpx.AsyncClient, ttl: float | None = None, cache_bytes: int | None = None
    ):
        self.client = client
        self.ttl = cache_ttl(300) if ttl is None else ttl
        self.cache_bytes = configured_cache_bytes() if cache_bytes is None else cache_bytes
        self.request_timeout = positive_float("HTTP_TIMEOUT_SECONDS", 15)
        self._cache: OrderedDict[str, tuple[float, Artifact]] = OrderedDict()
        self._oversized_failures: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._bytes = 0
        # Coalesce identical requests without blocking unrelated repository routes.
        self._cache_lock = asyncio.Lock()
        self._path_lock_guard = asyncio.Lock()
        self._path_locks: dict[str, asyncio.Lock] = {}
        self._path_lock_users: dict[str, int] = {}
        self._request_slots = asyncio.Semaphore(4)

    @asynccontextmanager
    async def _singleflight(self, path: str):
        async with self._path_lock_guard:
            lock = self._path_locks.setdefault(path, asyncio.Lock())
            self._path_lock_users[path] = self._path_lock_users.get(path, 0) + 1
        try:
            async with lock:
                yield
        finally:
            async with self._path_lock_guard:
                users = self._path_lock_users[path] - 1
                if users:
                    self._path_lock_users[path] = users
                else:
                    self._path_lock_users.pop(path, None)
                    self._path_locks.pop(path, None)

    async def fetch(self, path: str) -> Artifact:
        if not self.allowed_path(path):
            raise KnowledgeError("blocked_url", "Only fixed repository source routes are allowed")
        url = self.base_url + path
        limit = self._response_limit(path)
        async with self._singleflight(path):
            async with self._cache_lock:
                now = monotonic()
                if path in self._cache:
                    expires, item = self._cache[path]
                    if expires > now:
                        self._cache.move_to_end(path)
                        return item
                    self._bytes -= len(self._cache.pop(path)[1].body)
            failed = self._oversized_failures.get(path)
            if failed:
                if failed[0] > monotonic():
                    self._oversized_failures.move_to_end(path)
                    raise KnowledgeError("source_too_large", failed[1], url, cached=True)
                self._oversized_failures.pop(path, None)
            async with self._request_slots:
                try:
                    async with asyncio.timeout(45):
                        for attempt in range(2):
                            try:
                                async with self.client.stream(
                                    "GET",
                                    url,
                                    follow_redirects=False,
                                    timeout=self.request_timeout,
                                    headers={"Accept-Encoding": "identity"},
                                ) as response:
                                    if response.status_code == 429:
                                        retry_after = self._retry_after(
                                            response.headers.get("Retry-After")
                                        )
                                        if (
                                            attempt == 0
                                            and retry_after is not None
                                            and retry_after <= 1
                                        ):
                                            await asyncio.sleep(retry_after)
                                            continue
                                        message = "Repository rate limit exceeded"
                                        if retry_after is not None:
                                            message += f"; retry after {retry_after:g} seconds"
                                        raise KnowledgeError("rate_limited", message, url)
                                    if (
                                        response.status_code in (500, 502, 503, 504)
                                        and attempt == 0
                                    ):
                                        await asyncio.sleep(0.1 + random.random() * 0.2)
                                        continue
                                    if response.status_code != 200:
                                        code = (
                                            "not_found"
                                            if response.status_code == 404
                                            else "source_unavailable"
                                        )
                                        raise KnowledgeError(
                                            code, f"Repository HTTP {response.status_code}", url
                                        )
                                    if (
                                        response.headers.get("content-encoding", "identity")
                                        != "identity"
                                    ):
                                        raise KnowledgeError(
                                            "invalid_source", "Unexpected HTTP compression", url
                                        )
                                    chunks = bytearray()
                                    async for chunk in response.aiter_bytes(chunk_size=65536):
                                        chunks.extend(chunk)
                                        if len(chunks) > limit:
                                            raise KnowledgeError(
                                                "source_too_large",
                                                "Repository download exceeds limit",
                                                url,
                                            )
                                    break
                            except httpx.HTTPError:
                                if attempt == 0:
                                    await asyncio.sleep(0.1 + random.random() * 0.2)
                                    continue
                                raise
                except (httpx.HTTPError, TimeoutError) as exc:
                    raise KnowledgeError(
                        "source_unavailable", "Repository request failed or timed out", url
                    ) from exc
                except KnowledgeError as exc:
                    if exc.code == "source_too_large":
                        self._oversized_failures[path] = (
                            monotonic() + OVERSIZED_FAILURE_TTL,
                            str(exc),
                        )
                        self._oversized_failures.move_to_end(path)
                        while len(self._oversized_failures) > OVERSIZED_FAILURE_CAPACITY:
                            self._oversized_failures.popitem(last=False)
                    raise
            item = Artifact(bytes(chunks), url, datetime.now(UTC).isoformat())
            async with self._cache_lock:
                if len(item.body) <= self.cache_bytes:
                    while self._cache and (
                        self._bytes + len(item.body) > self.cache_bytes or len(self._cache) >= 32
                    ):
                        self._bytes -= len(self._cache.popitem(last=False)[1].body)
                    self._cache[path] = (monotonic() + self.ttl, item)
                    self._bytes += len(item.body)
            return item

    @staticmethod
    def _response_limit(path: str) -> int:
        if path == "/config.yaml":
            return 1 << 20
        if path.endswith("/DESCRIPTION"):
            return 2 << 20
        return (25 if path.endswith(".tar.gz") else 16) << 20

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            from email.utils import parsedate_to_datetime

            try:
                return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None


class CranHTTP(RepositoryHTTP):
    base_url = BASE

    def allowed_path(self, path: str) -> bool:
        return (
            path in (INDEX, CATALOG)
            or bool(ARCHIVE_ROUTE.fullmatch(path))
            or bool(re.fullmatch(r"/web/packages/[A-Za-z][A-Za-z0-9.]{0,99}/DESCRIPTION", path))
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
    timeout = positive_float("HTTP_TIMEOUT_SECONDS", 15)
    return httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        headers={"User-Agent": http_user_agent()},
    )
