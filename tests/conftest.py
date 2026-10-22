"""Synthetic HTTP fixtures, deliberately unrelated to real package versions."""

import gzip
import io
import tarfile

import httpx
import pytest

from cran_knowledge_mcp.http import CATALOG, INDEX, CranHTTP
from cran_knowledge_mcp.service import KnowledgeService

INDEX_TEXT = """Package: ExamplePkg
Version: 2.10-1
Depends: R (>= 4.1)
Imports: stats, other (>= 1.0)
Suggests: testthat,
    knitr
License: MIT

Package: AnotherPkg
Version: 1.0
License: GPL-3
"""
DESCRIPTION = """Package: ExamplePkg
Version: 2.10-1
Title: Synthetic Data Tools
Description: A synthetic fixture for tests.
Author: Test Author
Authors@R: person('Test', 'Author')
License: MIT
URL: https://example.invalid
Encoding: UTF-8
"""
RD = r"""\name{example}
\alias{example}
\alias{example_alias}
\title{Synthetic example}
\description{Fixture documentation, not an actual R package.}
\usage{example(x)}
\arguments{\item{x}{Input.}}
\examples{example(1)}
"""


def archive(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in files.items():
            body = text.encode() if isinstance(text, str) else text
            member = tarfile.TarInfo(name)
            member.size = len(body)
            tar.addfile(member, io.BytesIO(body))
    return gzip.compress(buffer.getvalue())


@pytest.fixture
async def service():
    routes = {
        INDEX: INDEX_TEXT.encode(),
        CATALOG: b"<table><tr><td><a>ExamplePkg</a></td><td>Synthetic Data Tools</td></tr>"
        b"<tr><td>AnotherPkg</td><td>Other Tools</td></tr></table>",
        "/src/contrib/ExamplePkg_2.10-1.tar.gz": archive(
            {
                "ExamplePkg/DESCRIPTION": DESCRIPTION,
                "ExamplePkg/man/example.Rd": RD,
            }
        ),
    }
    calls = []

    def handler(request):
        calls.append(request)
        content = routes.get(request.url.path)
        return httpx.Response(404 if content is None else 200, content=content or b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield KnowledgeService(CranHTTP(client)), routes, calls
