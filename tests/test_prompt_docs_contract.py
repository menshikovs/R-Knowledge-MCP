from __future__ import annotations

import gzip
import io
import tarfile

import httpx
import pytest

from cran_knowledge_mcp.http import INDEX, CranHTTP
from cran_knowledge_mcp.prompt_intelligence import PromptIntelligence
from cran_knowledge_mcp.providers.cran import CranProvider
from cran_knowledge_mcp.service import KnowledgeService

PACKAGE = "ExamplePkg"
VERSION = "2.10-1"
ARCHIVE_PATH = f"/src/contrib/{PACKAGE}_{VERSION}.tar.gz"
INDEX_TEXT = f"""Package: {PACKAGE}
Version: {VERSION}
Depends: R (>= 4.1)
Imports: stats
License: MIT
"""
DESCRIPTION = f"""Package: {PACKAGE}
Version: {VERSION}
Title: Synthetic Documentation Fixture
Description: A synthetic fixture for contract tests.
License: MIT
"""
RD = r"""\name{example}
\alias{example}
\title{Synthetic example}
\description{Fixture documentation.}
\usage{example(x)}
"""


def _archive(*rd_files: tuple[str, str | bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        files = [(f"{PACKAGE}/DESCRIPTION", DESCRIPTION), *rd_files]
        for name, content in files:
            body = content.encode() if isinstance(content, str) else content
            member = tarfile.TarInfo(name)
            member.size = len(body)
            tar.addfile(member, io.BytesIO(body))
    return gzip.compress(stream.getvalue())


class _MetadataVersionOverride:
    repository = "cran"
    bioc_version = None

    def __init__(self, http, version_override=None):
        self.delegate = CranProvider(http)
        self.version_override = version_override

    async def get_package_info(self, package):
        return {
            "package": package,
            "package_version": self.version_override or VERSION,
            "title": "Synthetic Documentation Fixture",
            "sources": [
                {
                    "source_url": "https://cran.r-project.org/src/contrib/PACKAGES",
                    "checked_at": "2026-10-22T00:00:00+00:00",
                }
            ],
        }

    async def get_dependencies(self, package):
        return {
            "package": package,
            "package_version": self.version_override or VERSION,
            "dependencies": {"Depends": "R (>= 4.1)", "Imports": "stats"},
            "sources": [
                {
                    "source_url": "https://cran.r-project.org/src/contrib/PACKAGES",
                    "checked_at": "2026-10-22T00:00:00+00:00",
                }
            ],
        }

    async def get_function_docs(self, package, function, offset=0):
        return await self.delegate.get_function_docs(package, function, offset)


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("matching", "verified"),
        ("missing", "docs_not_found"),
        ("ambiguous", "ambiguous_docs"),
        ("unavailable", "source_unavailable"),
        ("oversized", "source_too_large"),
        ("version_mismatch", "version_mismatch"),
    ],
)
async def test_build_prompt_preserves_function_docs_contract_and_provenance(case, expected_status):
    archive = _archive(
        ("ExamplePkg/man/example.Rd", RD),
        *(("ExamplePkg/man/other.Rd", RD),) if case == "ambiguous" else (),
        *(("ExamplePkg/man/large.Rd", b"\\name{large}\n\\alias{large}\n" + b"x" * (2 << 20)),)
        if case == "oversized"
        else (),
    )
    if case == "missing":
        archive = _archive(("ExamplePkg/man/other.Rd", RD.replace("example", "other")))

    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == INDEX:
            return httpx.Response(200, text=INDEX_TEXT)
        if request.url.path == ARCHIVE_PATH:
            if case == "unavailable":
                return httpx.Response(503, text="temporarily unavailable")
            return httpx.Response(200, content=archive)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = CranHTTP(client)
        provider = _MetadataVersionOverride(
            http, version_override="9.0" if case == "version_mismatch" else None
        )
        knowledge = KnowledgeService(http, providers={"cran": provider})
        result = await PromptIntelligence(knowledge).build_r_prompt(
            "Use ExamplePkg::example() to process the sample.", packages=[PACKAGE]
        )

    reference = result["function_documentation"][0]
    assert reference["status"] == expected_status
    if case == "matching":
        assert reference["verification_status"] == "verified"
        assert reference["package_version"] == VERSION
        assert reference["repository"] == "cran"
        assert reference["source_url"].endswith(ARCHIVE_PATH)
        assert reference["checked_at"]
        assert any(source["source_url"].endswith(ARCHIVE_PATH) for source in result["sources"])
        assert "Verified function documentation" in result["prompt_text"]
    else:
        assert reference["status"] != "verified"
        assert reference["source_url"].endswith(ARCHIVE_PATH)
        assert "Verified function documentation" not in result["prompt_text"]
    if case in {"missing", "ambiguous", "unavailable", "oversized"}:
        assert reference["verification_status"] == "failed"
        assert reference["checked_at"] is None
        assert reference["attempted_at"]
    if case == "version_mismatch":
        assert reference["verification_status"] == "verified"
        assert reference["package_version"] == VERSION
        assert reference["checked_at"]
    assert any(request.url.path == ARCHIVE_PATH for request in calls)
