"""Bioconductor software, annotation and experiment data within one resolved release."""

import asyncio

from ..errors import KnowledgeError
from ..http import Artifact, BioconductorHTTP, package_name, same_content, version_parts
from ..parsers import dcf, decode
from ..releases import Release
from .base import PackageSearchIndex, SourceRepository

CATEGORIES = {"bioc": "software", "data/annotation": "annotation", "data/experiment": "experiment"}


def _parse_indexes(artifacts: dict[str, Artifact]) -> dict[str, dict[str, str]]:
    parsed = {}
    for category, artifact in artifacts.items():
        try:
            records = dcf(decode(artifact.body))
            if not records:
                raise KnowledgeError("invalid_source", "Empty Bioconductor package index")
            for record in records:
                name = package_name(record.get("Package", ""))
                version_parts(record.get("Version", ""))
                if name in parsed or record.get("Path"):
                    raise KnowledgeError("invalid_source", "Ambiguous Bioconductor index entry")
                parsed[name] = {**record, "_category": category}
        except KnowledgeError as exc:
            raise KnowledgeError("invalid_source", str(exc), artifact.source_url) from exc
    return parsed


class BioconductorProvider(SourceRepository):
    repository = "bioconductor"

    def __init__(self, http: BioconductorHTTP, release: Release):
        super().__init__(http)
        self.release = release
        self.bioc_version = release.version
        self._sources: dict[str, Artifact] = {}
        self._search_for: dict | None = None
        self._search: PackageSearchIndex | None = None

    def archive_path(self, package: str, version: str) -> str:
        category = self._index_records[package]["_category"]
        return f"/packages/{self.bioc_version}/{category}/src/contrib/{package}_{version}.tar.gz"

    def page_path(self, package: str) -> str:
        category = self._index_records[package]["_category"]
        return f"/packages/{self.bioc_version}/{category}/html/{package}.html"

    async def index(self):
        fetched = await asyncio.gather(
            *(
                self.fetch_index(f"/packages/{self.bioc_version}/{category}/src/contrib/PACKAGES")
                for category in CATEGORIES
            )
        )
        artifacts = dict(zip(CATEGORIES, fetched, strict=True))
        if not self._same_sources(artifacts):
            async with self._index_lock:
                if not self._same_sources(artifacts):
                    self._index_records = await asyncio.to_thread(_parse_indexes, artifacts)
        # Keep the newest artifacts so provenance reports the latest check time.
        self._sources = artifacts
        return self._index_records, artifacts["bioc"]

    def _same_sources(self, artifacts: dict[str, Artifact]) -> bool:
        # Identity, not equality: equal-looking artifacts would compare whole bodies.
        return self._sources.keys() == artifacts.keys() and all(
            same_content(self._sources[key], artifact) for key, artifact in artifacts.items()
        )

    async def current(self, package: str):
        package_name(package)
        records, artifact = await self.index()
        if package not in records:
            raise KnowledgeError(
                "package_not_found",
                "Package is absent from the selected Bioconductor release",
                artifact.source_url,
            )
        record = records[package]
        return record, self._sources[record["_category"]]

    async def search_packages(self, query: str, limit: int = 10, offset: int = 0):
        if (
            not query.strip()
            or len(query) > 200
            or not 1 <= limit <= 20
            or not 0 <= offset <= 100000
        ):
            raise KnowledgeError("invalid_input", "Invalid search query, limit or offset")
        records, _ = await self.index()
        if self._search_for is not records:
            self._search = await asyncio.to_thread(
                PackageSearchIndex,
                [(name, record.get("Title", "")) for name, record in records.items()],
            )
            self._search_for = records
        matches = []
        for name in self._search.search(query):
            record = records[name]
            # PACKAGES may omit Title; never invent a title or fetch every archive.
            matches.append(
                {
                    "package": name,
                    "title": record.get("Title") or None,
                    "package_version": record["Version"],
                    "category": CATEGORIES[record["_category"]],
                    "sources": [self._sources[record["_category"]].provenance()],
                }
            )
        return {
            "query": query,
            "results": matches[offset : offset + limit],
            "total": len(matches),
            "next_offset": offset + limit if offset + limit < len(matches) else None,
            "search_scope": (
                "Bioconductor names and available PACKAGES titles; all terms must match; ranked"
            ),
            "sources": [a.provenance() for a in self._sources.values()],
        }
