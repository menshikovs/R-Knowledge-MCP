"""Canonical current CRAN provider; preserves the original operations."""

from ..errors import KnowledgeError
from ..http import CATALOG, INDEX, Artifact, version_parts
from ..parsers import CatalogParser, dcf, decode
from .base import SourceRepository


class CranProvider(SourceRepository):
    repository = "cran"
    bioc_version = None

    def archive_path(self, package: str, version: str) -> str:
        return f"/src/contrib/{package}_{version}.tar.gz"

    def page_path(self, package: str) -> str:
        return f"/web/packages/{package}/index.html"

    async def get_package_info(self, package: str) -> dict:
        result = await super().get_package_info(package)
        return {
            **result,
            "latest_cran_version": result["package_version"],
            "cran_url": f"https://cran.r-project.org/package={package}",
        }

    async def get_dependencies(self, package: str) -> dict:
        result = await super().get_dependencies(package)
        return {**result, "latest_cran_version": result["package_version"]}

    async def index(self) -> tuple[dict[str, dict[str, str]], Artifact]:
        artifact = await self.http.fetch(INDEX)
        if artifact is not self._index_artifact:
            records = dcf(decode(artifact.body))
            if not records or any(not r.get("Package") or not r.get("Version") for r in records):
                raise KnowledgeError(
                    "invalid_source", "Invalid CRAN package index", artifact.source_url
                )
            # CRAN appends R-version-specific Recommended subdirectories with
            # duplicate package names and different R constraints. Our source
            # scope is the canonical src/contrib root, never a Path override.
            root_records = [r for r in records if not r.get("Path")]
            parsed = {r["Package"]: r for r in root_records}
            if not parsed or len(parsed) != len(root_records):
                raise KnowledgeError(
                    "invalid_source", "Duplicate package in CRAN index", artifact.source_url
                )
            self._index_records = parsed
            self._index_artifact = artifact
        return self._index_records, artifact

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
        catalog = await self.http.fetch(CATALOG)
        parser = CatalogParser()
        parser.feed(decode(catalog.body))
        if not parser.rows or not set(parser.rows).intersection(records):
            raise KnowledgeError(
                "invalid_source", "Unrecognized CRAN title catalog", catalog.source_url
            )
        terms = query.casefold().split()
        matches = [
            {"package": name, "title": title, "latest_cran_version": records[name]["Version"]}
            for name, title in parser.rows.items()
            if name in records and all(t in f"{name} {title}".casefold() for t in terms)
        ]
        matches.sort(
            key=lambda r: (r["package"].casefold() != query.casefold(), r["package"].casefold())
        )
        return {
            "query": query,
            "search_scope": "CRAN package names and titles (all terms)",
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
