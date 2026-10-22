"""Optional Context7 documentation retrieval constrained to a verified package repo."""

import asyncio
import json
import re
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import urlencode

import httpx

from ..errors import KnowledgeError
from ..http import Artifact
from .github_agents import github_repository

CONTEXT7 = "https://context7.com"
MAX_RESPONSE = 4 << 20
MAX_OUTPUT = 48 << 10
TOKEN_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bctx7(?:sk|op)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(
        r"(?i)\b(password|passwd|secret|token|credential|api[_-]?key)\b\s+(?:is\s+)?"
        r"[\"']?[^\s,;\"']{4,}"
    ),
    re.compile(r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)


def safe_query(value: str) -> str:
    if not value.strip() or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise KnowledgeError("invalid_input", "Question must contain 1..500 printable characters")
    result = value
    for pattern in TOKEN_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


class Context7Provider:
    """Calls Context7 only with a server-owned key and exact package repository identity."""

    def __init__(self, client: httpx.AsyncClient, api_key: str | None, ttl: float = 21600):
        self.client = client
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.ttl = ttl
        self._cache: dict[str, tuple[float, dict]] = {}

    async def _get(self, route: str, params: dict[str, str], max_bytes=MAX_RESPONSE):
        if route not in ("/api/v2/libs/search", "/api/v2/context"):
            raise KnowledgeError("blocked_url", "Context7 route failed fixed-host validation")
        url = f"{CONTEXT7}{route}?{urlencode(params)}"
        if not self.api_key:
            raise KnowledgeError(
                "integration_disabled", "Context7 is disabled; set server-side CONTEXT7_API_KEY"
            )
        body = bytearray()
        try:
            async with asyncio.timeout(30):
                async with self.client.stream(
                    "GET",
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                    },
                    follow_redirects=False,
                    timeout=20,
                ) as response:
                    if response.status_code != 200:
                        if response.status_code == 404:
                            raise KnowledgeError(
                                "not_found", "Context7 has no matching documentation", url
                            )
                        if response.status_code == 429:
                            retry_after = response.headers.get("Retry-After")
                            message = "Context7 rate limit exceeded"
                            if retry_after and retry_after.isdigit():
                                message += f"; retry after {retry_after} seconds"
                            raise KnowledgeError("rate_limited", message, url)
                        if response.status_code == 401:
                            raise KnowledgeError(
                                "authentication_failed", "Context7 rejected the server API key", url
                            )
                        raise KnowledgeError(
                            "source_unavailable", f"Context7 HTTP {response.status_code}", url
                        )
                    async for chunk in response.aiter_bytes(65536):
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise KnowledgeError(
                                "source_too_large", "Context7 response exceeds byte limit", url
                            )
        except (httpx.HTTPError, TimeoutError) as exc:
            raise KnowledgeError(
                "source_unavailable", "Context7 request failed or timed out", url
            ) from exc
        try:
            payload = json.loads(body)
        except (ValueError, json.JSONDecodeError) as exc:
            raise KnowledgeError("invalid_source", "Context7 returned invalid JSON", url) from exc
        if not isinstance(payload, dict):
            raise KnowledgeError("invalid_source", "Context7 response must be a JSON object", url)
        return payload, Artifact(bytes(body), url, datetime.now(UTC).isoformat())

    async def get_context7_docs(
        self,
        package: str,
        package_version: str,
        metadata_urls: str | None,
        question: str,
        repository: str,
        bioc_version: str | None,
    ) -> dict:
        query = safe_query(question)
        owner, repo = github_repository(metadata_urls)
        expected_id = f"/{owner}/{repo}".casefold()
        cache_key = f"{repository}:{bioc_version}:{package}:{expected_id}@{package_version}:{query}"
        now = monotonic()
        if cache_key in self._cache and self._cache[cache_key][0] > now:
            return self._cache[cache_key][1]
        search, search_artifact = await self._get(
            "/api/v2/libs/search",
            {
                "libraryName": package,
                "query": f"R package {package}; official source {owner}/{repo}",
            },
        )
        results = search.get("results")
        if not isinstance(results, list):
            raise KnowledgeError(
                "invalid_source",
                "Context7 library search lacks results",
                search_artifact.source_url,
            )
        matches = []
        for item in results:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            library_id = item["id"]
            match = re.fullmatch(
                re.escape(expected_id) + r"(?:/[A-Za-z0-9._+-]{1,80}|@[A-Za-z0-9._+-]{1,80})?",
                library_id,
                re.IGNORECASE,
            )
            if match:
                matches.append(item)
        if len(matches) != 1:
            reason = (
                "no exact repository match" if not matches else "multiple exact repository matches"
            )
            raise KnowledgeError(
                "library_mismatch",
                f"Context7 library identity check failed: {reason}",
                search_artifact.source_url,
            )
        match = matches[0]
        library_id = match["id"]
        version_scope = (
            "context7_selected_version" if library_id != expected_id else "context7_unpinned"
        )
        # Prefer an exact version only when Context7 itself lists it. Do not invent an ID suffix.
        versions = match.get("versions")
        if isinstance(versions, list):
            exact = next(
                (
                    v
                    for v in versions
                    if isinstance(v, str)
                    and v.removeprefix("v") == package_version.removeprefix("v")
                ),
                None,
            )
            if exact:
                library_id = f"{expected_id}/{exact}"
                version_scope = "package_version"
        docs, docs_artifact = await self._get(
            "/api/v2/context",
            {"libraryId": library_id, "query": query, "type": "json"},
        )
        fragments = []
        for info in (
            docs.get("infoSnippets", []) if isinstance(docs.get("infoSnippets", []), list) else []
        ):
            if isinstance(info, dict) and isinstance(info.get("content"), str):
                fragments.append(
                    {"kind": "documentation", "title": info.get("title"), "text": info["content"]}
                )
        for snippet in (
            docs.get("codeSnippets", []) if isinstance(docs.get("codeSnippets", []), list) else []
        ):
            if not isinstance(snippet, dict):
                continue
            code_list = snippet.get("codeList", [])
            if isinstance(code_list, list):
                for code in code_list:
                    if isinstance(code, dict) and isinstance(code.get("code"), str):
                        fragments.append(
                            {
                                "kind": "example",
                                "title": snippet.get("codeTitle"),
                                "text": code["code"],
                            }
                        )
        selected, used = [], 0
        for fragment in fragments[:32]:
            encoded_size = len(fragment["text"].encode("utf-8"))
            if used + encoded_size > MAX_OUTPUT:
                break
            used += encoded_size
            selected.append(
                {
                    **fragment,
                    "library_id": library_id,
                    "library_title": match.get("title"),
                    "repository_match": f"{owner}/{repo}",
                    "version_scope": version_scope,
                    "source_url": f"https://context7.com{library_id}",
                    "checked_at": docs_artifact.checked_at,
                    "verification_status": "retrieved_from_context7",
                    "authority": (
                        "indexed_third_party_documentation; verify against official package docs"
                    ),
                }
            )
        result = {
            "package": package,
            "repository": repository,
            "package_version": package_version,
            "bioc_version": bioc_version,
            "official_repository": f"{owner}/{repo}",
            "question_sent": query,
            "library_id": library_id,
            "version_scope": version_scope,
            "fragments": selected,
            "status": "verified" if selected else "no_documentation_found",
            "authority_warning": (
                "Context7 is an indexed secondary source, not automatically more authoritative "
                "than CRAN, Bioconductor or package documentation."
            ),
            "source_url": docs_artifact.source_url,
            "checked_at": docs_artifact.checked_at,
            "verification_status": "verified" if selected else "empty",
            "sources": [search_artifact.provenance(), docs_artifact.provenance()],
            "truncated": len(selected) < len(fragments),
        }
        self._cache[cache_key] = (now + self.ttl, result)
        return result
