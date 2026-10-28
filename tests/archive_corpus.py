"""Offline repositories built from the real archives in tests/fixtures/archives.

The archives are authentic CRAN and Bioconductor source tarballs (see MANIFEST.json for version,
URL, SHA-256, licence and the reason each one is included). They are untrusted data: tests parse
them in memory with the project's bounded parser and never extract or execute them.
"""

import gzip
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from cran_knowledge_mcp.http import CATALOG, INDEX, CranHTTP
from cran_knowledge_mcp.parsers import dcf, description_text, source_files
from cran_knowledge_mcp.service import KnowledgeService

DIRECTORY = Path(__file__).parent / "fixtures" / "archives"
CONFIG = b"""release_version: "3.23"
devel_version: "3.24"
r_ver_for_bioc_ver:
  "3.22": "4.5"
  "3.23": "4.6"
  "3.24": "4.6"
"""
BIOC_VERSION = "3.23"


def manifest() -> dict:
    return json.loads((DIRECTORY / "MANIFEST.json").read_text(encoding="utf-8"))


def entries(repository: str | None = None) -> list[dict]:
    rows = manifest()["archives"]
    if repository == "cran":
        return [row for row in rows if row["repository"] == "CRAN"]
    if repository == "bioconductor":
        return [row for row in rows if row["repository"].startswith("Bioconductor")]
    return rows


def body(entry: dict) -> bytes:
    return (DIRECTORY / entry["file"]).read_bytes()


def parsed(entry: dict) -> tuple[dict, dict[str, bytes]]:
    """(DESCRIPTION record, archive members) of one fixture, via the bounded parser."""
    files = source_files(body(entry), entry["package"])
    metadata = dcf(description_text(files[f"{entry['package']}/DESCRIPTION"]))[0]
    return metadata, files


def _index_text(rows: list[dict]) -> bytes:
    blocks = []
    for entry in rows:
        md5 = hashlib.md5(body(entry), usedforsecurity=False).hexdigest()
        blocks.append(
            f"Package: {entry['package']}\nVersion: {entry['version']}\nMD5sum: {md5}\n"
            f"License: {entry['license']}\n"
        )
    return "\n".join(blocks).encode()


def routes() -> dict[tuple[str, str], bytes]:
    result: dict[tuple[str, str], bytes] = {}
    cran = entries("cran")
    result[("cran.r-project.org", INDEX)] = _index_text(cran)
    result[("cran.r-project.org", CATALOG)] = "".join(
        f"<tr><td>{e['package']}</td><td>{e['title']}</td></tr>" for e in cran
    ).encode()
    for entry in cran:
        package, version = entry["package"], entry["version"]
        result[("cran.r-project.org", f"/src/contrib/{package}_{version}.tar.gz")] = body(entry)
        metadata, _ = parsed(entry)
        text = "".join(f"{k}: {v}\n" for k, v in metadata.items())
        result[("cran.r-project.org", f"/web/packages/{package}/DESCRIPTION")] = text.encode()
    result[("bioconductor.org", "/config.yaml")] = CONFIG
    base = f"/packages/{BIOC_VERSION}"
    result[("bioconductor.org", f"{base}/bioc/src/contrib/PACKAGES")] = _index_text(
        entries("bioconductor")
    )
    # Placeholder records only: the provider rejects an empty category index.
    for category, name in (
        ("data/annotation", "org.Fixture.db"),
        ("data/experiment", "FixtureData"),
    ):
        record = f"Package: {name}\nVersion: 1.0\nLicense: Artistic-2.0\n"
        result[("bioconductor.org", f"{base}/{category}/src/contrib/PACKAGES")] = record.encode()
    for entry in entries("bioconductor"):
        name = f"{entry['package']}_{entry['version']}.tar.gz"
        result[("bioconductor.org", f"{base}/bioc/src/contrib/{name}")] = body(entry)
    return result


@asynccontextmanager
async def corpus_service(extra: dict | None = None, ttl: float | None = None):
    """A KnowledgeService over the corpus; yields (service, routes, calls)."""
    table = {**routes(), **(extra or {})}
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        content = table.get((request.url.host, request.url.path))
        plain = (request.url.host, request.url.path.removesuffix(".gz"))
        if content is None and request.url.path.endswith("/PACKAGES.gz") and plain in table:
            content = gzip.compress(table[plain])
        return httpx.Response(404 if content is None else 200, content=content or b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield KnowledgeService(CranHTTP(client, ttl=ttl)), table, calls
