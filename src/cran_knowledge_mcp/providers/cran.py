"""Canonical current CRAN provider; preserves the original operations."""

import asyncio
from datetime import UTC, datetime

from ..errors import KnowledgeError
from ..http import CATALOG, INDEX, Artifact, same_content, version_parts
from ..parsers import CatalogParser, dcf, decode, description_text
from .base import PackageSearchIndex, SourceRepository

SEARCH_SCOPE = (
    "CRAN package names and titles; all terms must match; ranked by exact name, "
    "name prefix/word, then title word matches"
)


def _parse_index(artifact: Artifact) -> dict[str, dict[str, str]]:
    records = dcf(decode(artifact.body))
    if not records or any(not r.get("Package") or not r.get("Version") for r in records):
        raise KnowledgeError("invalid_source", "Invalid CRAN package index", artifact.source_url)
    # CRAN appends R-version-specific Recommended subdirectories with
    # duplicate package names and different R constraints. Our source
    # scope is the canonical src/contrib root, never a Path override.
    root_records = [r for r in records if not r.get("Path")]
    parsed = {r["Package"]: r for r in root_records}
    if not parsed or len(parsed) != len(root_records):
        raise KnowledgeError(
            "invalid_source", "Duplicate package in CRAN index", artifact.source_url
        )
    return parsed


def _parse_catalog(artifact: Artifact) -> dict[str, str]:
    parser = CatalogParser()
    parser.feed(decode(artifact.body))
    return parser.rows


class CranProvider(SourceRepository):
    repository = "cran"
    bioc_version = None

    def __init__(self, http):
        super().__init__(http)
        self._catalog_artifact: Artifact | None = None
        self._catalog_rows: dict[str, str] = {}
        self._search_key: tuple[Artifact, Artifact] | None = None
        self._search: PackageSearchIndex | None = None

    async def _search_index(self, records, index, rows, catalog) -> PackageSearchIndex:
        if self._search_key is None or not (
            same_content(self._search_key[0], index) and same_content(self._search_key[1], catalog)
        ):
            entries = [(name, title) for name, title in rows.items() if name in records]
            self._search = await asyncio.to_thread(PackageSearchIndex, entries)
            self._search_key = (index, catalog)
        return self._search

    def archive_path(self, package: str, version: str) -> str:
        return f"/src/contrib/{package}_{version}.tar.gz"

    def page_path(self, package: str) -> str:
        return f"/web/packages/{package}/index.html"

    def description_path(self, package: str) -> str:
        return f"/web/packages/{package}/DESCRIPTION"

    async def get_package_info(self, package: str, verify_archive: bool = True) -> dict:
        if verify_archive:
            result = await super().get_package_info(package, verify_archive=True)
        else:
            record, index = await self.current(package)
            try:
                result = await self._lightweight_description(package, record, index)
            except KnowledgeError as exc:
                if exc.code != "not_found":
                    raise
                result = {
                    **self.package_metadata(
                        package, record, [index.provenance()], "index_verified"
                    ),
                    "verification_status": "partial",
                    "metadata_details_status": "unavailable",
                    "metadata_error": {
                        "code": exc.code,
                        "message": str(exc),
                        "source_url": exc.source_url,
                        "attempted_at": datetime.now(UTC).isoformat(),
                    },
                }
        return {
            **result,
            "latest_cran_version": result["package_version"],
            "cran_url": f"https://cran.r-project.org/package={package}",
        }

    async def _lightweight_description(self, package, record, index):
        artifact = await self.http.fetch(self.description_path(package))
        related_sources = [index.provenance(), artifact.provenance()]
        try:
            records = dcf(description_text(artifact.body))
        except KnowledgeError as exc:
            raise KnowledgeError(
                exc.code,
                str(exc),
                artifact.source_url,
                related_sources=related_sources,
            ) from exc
        if len(records) != 1:
            raise KnowledgeError(
                "invalid_source",
                "Expected one DESCRIPTION record",
                artifact.source_url,
                related_sources=related_sources,
            )
        metadata = records[0]
        if not metadata.get("Package") or not metadata.get("Version"):
            raise KnowledgeError(
                "invalid_source",
                "DESCRIPTION lacks package identity fields",
                artifact.source_url,
                related_sources=related_sources,
            )
        try:
            version_parts(metadata["Version"])
        except KnowledgeError as exc:
            raise KnowledgeError(
                "invalid_source",
                "DESCRIPTION contains an invalid package version",
                artifact.source_url,
                related_sources=related_sources,
            ) from exc
        if metadata["Package"] != package or metadata["Version"] != record["Version"]:
            raise KnowledgeError(
                "version_mismatch",
                "Lightweight DESCRIPTION does not match the selected CRAN index record",
                artifact.source_url,
                related_sources=related_sources,
            )
        return self.package_metadata(
            package,
            metadata,
            related_sources,
            "description_version_matched",
        )

    async def get_dependencies(self, package: str) -> dict:
        result = await super().get_dependencies(package)
        return {**result, "latest_cran_version": result["package_version"]}

    async def index(self) -> tuple[dict[str, dict[str, str]], Artifact]:
        artifact = await self.fetch_index(INDEX)
        if not same_content(self._index_artifact, artifact):
            async with self._index_lock:
                if not same_content(self._index_artifact, artifact):
                    # A multi-megabyte DCF parse must not stall other requests.
                    self._index_records = await asyncio.to_thread(_parse_index, artifact)
        # Keep the newest artifact so provenance reports the latest check time.
        self._index_artifact = artifact
        return self._index_records, artifact

    async def _catalog(self) -> tuple[dict[str, str], Artifact]:
        catalog = await self.http.fetch(CATALOG)
        if not same_content(self._catalog_artifact, catalog):
            async with self._index_lock:
                if not same_content(self._catalog_artifact, catalog):
                    self._catalog_rows = await asyncio.to_thread(_parse_catalog, catalog)
        self._catalog_artifact = catalog
        return self._catalog_rows, catalog

    async def search_packages(self, query: str, limit: int = 10, offset: int = 0) -> dict:
        if (
            not query.strip()
            or len(query) > 200
            or not 1 <= limit <= 20
            or not 0 <= offset <= 100000
        ):
            raise KnowledgeError(
                "invalid_input", "Use query 1..200 chars, limit 1..20, offset 0..100000"
            )
        records, index = await self.index()
        rows, catalog = await self._catalog()
        if not rows or not set(rows).intersection(records):
            raise KnowledgeError(
                "invalid_source", "Unrecognized CRAN title catalog", catalog.source_url
            )
        ranked = (await self._search_index(records, index, rows, catalog)).search(query)
        matches = [
            {"package": name, "title": rows[name], "latest_cran_version": records[name]["Version"]}
            for name in ranked
        ]
        return {
            "query": query,
            "search_scope": SEARCH_SCOPE,
            "results": matches[offset : offset + limit],
            "total": len(matches),
            "next_offset": offset + limit if offset + limit < len(matches) else None,
            "sources": [index.provenance(), catalog.provenance()],
        }

    async def check_package_version(self, package: str, installed_version: str) -> dict:
        installed = version_parts(installed_version)
        record, artifact = await self.current(package)
        latest = version_parts(record["Version"])
        relation = "equal" if installed == latest else "older" if installed < latest else "newer"
        return {
            "package": package,
            "installed_version": installed_version,
            "installed_version_source": "client_supplied (not inspected or verified)",
            "latest_cran_version": record["Version"],
            "comparison": relation,
            "is_latest": relation == "equal",
            "sources": [artifact.provenance()],
        }
