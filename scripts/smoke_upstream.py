"""Bounded, read-only live checks for official R documentation sources.

Run with ``python scripts/smoke_upstream.py``. The checks use only fixed HTTPS
URLs, reject redirects, cap response bodies, and never download package archives.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import yaml

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.http import version_parts
from cran_knowledge_mcp.parsers import dcf, decode
from cran_knowledge_mcp.providers.framework_docs import DOCS

USER_AGENT = "R-Knowledge-MCP-upstream-smoke/1.0 (+https://github.com/menshikovs/R-Knowledge-MCP)"
ALLOWED_HOSTS = {
    "cran.r-project.org",
    "bioconductor.org",
    "shiny.posit.co",
    "positron.posit.co",
    "quarto.org",
}
MAX_INDEX_BYTES = 16 << 20
MAX_DOC_BYTES = 2 << 20
REQUEST_TIMEOUT = 8.0
REQUEST_DEADLINE = 10.0


@dataclass(frozen=True)
class Check:
    source: str
    name: str
    url: str
    max_bytes: int = MAX_DOC_BYTES
    content_type: str | None = None


class SmokeFailure(Exception):
    """A classified failure with safe, fixed diagnostic text."""

    def __init__(self, category: str, message: str, official_url: str | None = None):
        super().__init__(message)
        self.category = category
        self.official_url = official_url


class UpstreamSmokeChecker:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self._slots = asyncio.Semaphore(4)

    async def fetch(self, check: Check) -> bytes:
        parsed = urlsplit(check.url)
        path_allowed = (
            (
                parsed.hostname == "cran.r-project.org"
                and parsed.path
                in {
                    "/src/contrib/PACKAGES",
                    "/web/packages/ggplot2/DESCRIPTION",
                }
            )
            or (
                parsed.hostname == "bioconductor.org"
                and (
                    parsed.path == "/config.yaml"
                    or re.fullmatch(
                        r"/packages/[0-9]+\.[0-9]+/(?:bioc|data/annotation|data/experiment)/src/contrib/PACKAGES",
                        parsed.path,
                    )
                    is not None
                )
            )
            or any(parsed.geturl() == url for pages in DOCS.values() for url in pages.values())
        )
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or not path_allowed
            or check.max_bytes < 1
            or check.max_bytes > MAX_INDEX_BYTES
        ):
            raise SmokeFailure(
                "local_configuration_error", "Check URL or size is not allow-listed", check.url
            )

        content = bytearray()
        try:
            async with self._slots, asyncio.timeout(REQUEST_DEADLINE):
                async with self.client.stream(
                    "GET",
                    check.url,
                    follow_redirects=False,
                    timeout=REQUEST_TIMEOUT,
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise SmokeFailure(
                            "redirect_introduced", "Official URL returned a redirect", check.url
                        )
                    if response.status_code != 200:
                        raise SmokeFailure(
                            "unexpected_http_status",
                            f"Official URL returned HTTP {response.status_code}",
                            check.url,
                        )
                    encoding = response.headers.get("content-encoding", "identity").casefold()
                    if encoding != "identity":
                        raise SmokeFailure(
                            "invalid_response_body", "Unexpected encoded response", check.url
                        )
                    response_type = (
                        response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                    )
                    if check.content_type and not (
                        response_type == check.content_type
                        or response_type.startswith(check.content_type + "+")
                    ):
                        raise SmokeFailure(
                            "invalid_response_body", "Unexpected response content type", check.url
                        )
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        content.extend(chunk)
                        if len(content) > check.max_bytes:
                            raise SmokeFailure(
                                "invalid_response_body",
                                "Response exceeds the byte limit",
                                check.url,
                            )
        except SmokeFailure:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise SmokeFailure("network_timeout", "Official request timed out", check.url) from exc
        except httpx.HTTPError as exc:
            raise SmokeFailure(
                "upstream_unavailable", "Official request failed", check.url
            ) from exc
        if not content:
            raise SmokeFailure(
                "invalid_response_body", "Official URL returned an empty body", check.url
            )
        return bytes(content)

    async def execute(self, check: Check, operation) -> dict:
        checked_at = datetime.now(UTC).isoformat()
        try:
            await operation()
        except SmokeFailure as exc:
            return {
                "source_identifier": check.source,
                "check_name": check.name,
                "status": "failed",
                "failure_category": exc.category,
                "message": str(exc),
                "official_url": exc.official_url or check.url,
                "timestamp": checked_at,
            }
        except KnowledgeError as exc:
            return {
                "source_identifier": check.source,
                "check_name": check.name,
                "status": "failed",
                "failure_category": "invalid_response_body",
                "message": "Official metadata could not be validated",
                "official_url": exc.source_url or check.url,
                "timestamp": checked_at,
            }
        except Exception as exc:
            return {
                "source_identifier": check.source,
                "check_name": check.name,
                "status": "failed",
                "failure_category": "internal_smoke_error",
                "message": f"Smoke check failed internally ({type(exc).__name__})",
                "official_url": check.url,
                "timestamp": checked_at,
            }
        return {
            "source_identifier": check.source,
            "check_name": check.name,
            "status": "success",
            "failure_category": None,
            "message": "Official response passed semantic checks",
            "official_url": check.url,
            "timestamp": checked_at,
        }

    async def check_cran(self) -> None:
        index_check = Check(
            "cran",
            "canonical_package_index",
            "https://cran.r-project.org/src/contrib/PACKAGES",
            MAX_INDEX_BYTES,
        )
        description_check = Check(
            "cran",
            "ggplot2_metadata",
            "https://cran.r-project.org/web/packages/ggplot2/DESCRIPTION",
            MAX_DOC_BYTES,
        )
        index_body = await self.fetch(index_check)
        description_body = await self.fetch(description_check)
        try:
            validate_cran_identity(index_body, description_body, description_check.url)
        except KnowledgeError as exc:
            raise SmokeFailure(
                "invalid_response_body",
                "CRAN package metadata could not be validated",
                description_check.url,
            ) from exc

    async def check_bioconductor(self) -> None:
        config_check = Check(
            "bioconductor",
            "official_release_configuration",
            "https://bioconductor.org/config.yaml",
            1 << 20,
        )
        try:
            config = yaml.safe_load(await self.fetch(config_check))
        except yaml.YAMLError as exc:
            raise SmokeFailure(
                "invalid_response_body",
                "Bioconductor release configuration is malformed",
                config_check.url,
            ) from exc
        try:
            stable = config["release_version"]
            devel = config["devel_version"]
            releases = config["r_ver_for_bioc_ver"]
            if (
                not isinstance(stable, str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+", stable)
                or not isinstance(devel, str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+", devel)
                or stable == devel
                or not isinstance(releases, dict)
                or stable not in releases
                or devel not in releases
                or not isinstance(releases[stable], str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", releases[stable])
                or not isinstance(releases[devel], str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", releases[devel])
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise SmokeFailure(
                "invalid_response_body",
                "Bioconductor release configuration is malformed",
                config_check.url,
            ) from exc

        categories = (
            ("software", "bioc", "DESeq2"),
            ("annotation", "data/annotation", "org.Hs.eg.db"),
            ("experiment", "data/experiment", "airway"),
        )
        for label, route, expected_package in categories:
            check = Check(
                "bioconductor",
                f"{stable}_{label}_index",
                f"https://bioconductor.org/packages/{stable}/{route}/src/contrib/PACKAGES",
                MAX_INDEX_BYTES,
                "text/plain",
            )
            try:
                records = dcf(decode(await self.fetch(check)))
            except KnowledgeError as exc:
                raise SmokeFailure(
                    "invalid_response_body",
                    "Bioconductor package index could not be validated",
                    check.url,
                ) from exc
            by_name = {}
            for record in records:
                name = record.get("Package")
                if (
                    not isinstance(name, str)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9.]{0,99}", name)
                    or name in by_name
                    or not record.get("Version")
                ):
                    raise SmokeFailure(
                        "invalid_response_body",
                        "Bioconductor package index is malformed",
                        check.url,
                    )
                by_name[name] = record
            expected = by_name.get(expected_package)
            if expected is None or not expected.get("Version"):
                raise SmokeFailure(
                    "metadata_identity_mismatch",
                    f"Bioconductor {label} index lacks expected package metadata",
                    check.url,
                )
            try:
                version_parts(expected["Version"])
            except KnowledgeError as exc:
                raise SmokeFailure(
                    "invalid_response_body",
                    "Bioconductor package index contains an invalid version",
                    check.url,
                ) from exc

    async def check_document(self, check: Check, markers: tuple[str, ...]) -> None:
        body = await self.fetch(check)
        try:
            text = body.decode("utf-8", errors="strict").casefold()
        except UnicodeError as exc:
            raise SmokeFailure(
                "invalid_response_body", "Official page is not valid UTF-8", check.url
            ) from exc
        if not all(marker.casefold() in text for marker in markers):
            raise SmokeFailure(
                "invalid_response_body", "Official page lacks expected topic content", check.url
            )

    def document_operation(self, check: Check, markers: tuple[str, ...]):
        async def operation():
            await self.check_document(check, markers)

        return operation

    async def run(self) -> list[dict]:
        checks = [
            (
                Check(
                    "cran",
                    "package_index_and_ggplot2_metadata",
                    "https://cran.r-project.org/src/contrib/PACKAGES",
                    MAX_INDEX_BYTES,
                ),
                self.check_cran,
            ),
            (
                Check(
                    "bioconductor",
                    "release_and_category_indices",
                    "https://bioconductor.org/config.yaml",
                    1 << 20,
                ),
                self.check_bioconductor,
            ),
        ]
        for topic, markers in (
            ("reactivity", ("reactive",)),
            ("modules", ("moduleServer",)),
            ("async", ("non-blocking",)),
        ):
            check = Check("shiny", topic, DOCS["shiny"][topic], MAX_DOC_BYTES, "text/html")
            checks.append((check, self.document_operation(check, markers)))
        for framework, topic, markers in (
            ("positron", "interpreters", ("interpreter",)),
            ("positron", "r_installation", ("r",)),
            ("quarto", "r", ("r",)),
            ("quarto", "projects", ("project",)),
        ):
            check = Check(framework, topic, DOCS[framework][topic], MAX_DOC_BYTES, "text/html")
            checks.append((check, self.document_operation(check, markers)))

        async def run_check(check: Check, operation) -> dict:
            return await self.execute(check, operation)

        return list(
            await asyncio.gather(*(run_check(check, operation) for check, operation in checks))
        )


def validate_cran_identity(index_body: bytes, description_body: bytes, description_url: str) -> str:
    """Check that a small CRAN DESCRIPTION agrees with the canonical index."""
    index_records = dcf(decode(index_body))
    indexed = next((record for record in index_records if record.get("Package") == "ggplot2"), None)
    if indexed is None or not indexed.get("Version"):
        raise SmokeFailure(
            "metadata_identity_mismatch",
            "CRAN index lacks ggplot2 identity/version",
            description_url,
        )
    version_parts(indexed["Version"])
    description = dcf(decode(description_body))
    if len(description) != 1:
        raise SmokeFailure(
            "invalid_response_body", "CRAN DESCRIPTION must contain one record", description_url
        )
    record = description[0]
    if record.get("Package") != "ggplot2" or record.get("Version") != indexed["Version"]:
        raise SmokeFailure(
            "metadata_identity_mismatch",
            "CRAN package identity/version differs from index",
            description_url,
        )
    return indexed["Version"]


async def main() -> int:
    try:
        client = httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=REQUEST_TIMEOUT,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={"User-Agent": USER_AGENT},
        )
    except (ValueError, httpx.HTTPError) as exc:
        print(
            json.dumps(
                {
                    "source_identifier": "local",
                    "check_name": "client_configuration",
                    "status": "failed",
                    "failure_category": "local_configuration_error",
                    "message": f"HTTP client configuration failed ({type(exc).__name__})",
                    "official_url": None,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        )
        return 1
    async with client:
        results = await UpstreamSmokeChecker(client).run()
    for result in results:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 1 if any(result["status"] == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
