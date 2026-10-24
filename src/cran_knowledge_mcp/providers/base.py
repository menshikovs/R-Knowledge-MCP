"""Shared data-only operations for versioned source repositories."""

import asyncio
import hashlib
import re
from abc import ABC, abstractmethod
from urllib.parse import urljoin, urlsplit

from ..errors import KnowledgeError
from ..http import Artifact, RepositoryHTTP, package_name, version_parts
from ..parsers import PackagePageParser, aliases, dcf, decode, description_text, source_files


class SourceRepository(ABC):
    repository: str
    bioc_version: str | None

    @abstractmethod
    async def index(self) -> tuple[dict[str, dict[str, str]], Artifact]: ...

    @abstractmethod
    def archive_path(self, package: str, version: str) -> str: ...

    @abstractmethod
    def page_path(self, package: str) -> str: ...

    def __init__(self, http: RepositoryHTTP):
        self.http = http
        self._parse_lock = asyncio.Lock()
        self._index_artifact: Artifact | None = None
        self._index_records: dict[str, dict[str, str]] = {}

    async def current(self, package: str) -> tuple[dict[str, str], Artifact]:
        package_name(package)
        records, artifact = await self.index()
        if package not in records:
            raise KnowledgeError(
                "package_not_found",
                "Package is not in the selected repository index",
                artifact.source_url,
            )
        version_parts(records[package]["Version"])
        return records[package], artifact

    async def source(self, package: str):
        record, index = await self.current(package)
        version = record["Version"]
        artifact = await self.http.fetch(self.archive_path(package, version))
        if (
            record.get("MD5sum")
            and hashlib.md5(artifact.body, usedforsecurity=False).hexdigest() != record["MD5sum"]
        ):
            raise KnowledgeError(
                "checksum_mismatch", "Archive checksum differs from CRAN index", artifact.source_url
            )
        # Parsing is bounded and off the event loop; only one expanded archive at a time.
        try:
            async with self._parse_lock:
                files = await asyncio.to_thread(source_files, artifact.body, package)
            descriptions = dcf(description_text(files[f"{package}/DESCRIPTION"]))
        except KnowledgeError as exc:
            raise KnowledgeError(exc.code, str(exc), artifact.source_url) from exc
        if len(descriptions) != 1:
            raise KnowledgeError(
                "invalid_source", "Expected one DESCRIPTION record", artifact.source_url
            )
        metadata = descriptions[0]
        if metadata.get("Package") != package or metadata.get("Version") != version:
            raise KnowledgeError(
                "version_mismatch", "Archive does not match CRAN index", artifact.source_url
            )
        return metadata, files, artifact, index

    @staticmethod
    def package_metadata(
        package: str, metadata: dict[str, str], sources: list[dict], verification_level: str
    ) -> dict:
        field_map = {
            "title": "Title",
            "description": "Description",
            "authors": "Author",
            "authors_at_r": "Authors@R",
            "license": "License",
            "urls": "URL",
        }
        return {
            "package": package,
            "package_version": metadata.get("Version"),
            "installed_version": None,
            **{output: metadata.get(source) for output, source in field_map.items()},
            "metadata_verification_level": verification_level,
            "metadata_fields_missing": [
                output for output, source in field_map.items() if not metadata.get(source)
            ],
            "sources": sources,
        }

    async def get_package_info(self, package: str, verify_archive: bool = True) -> dict:
        if not verify_archive:
            record, index = await self.current(package)
            return self.package_metadata(package, record, [index.provenance()], "index_verified")
        metadata, _, artifact, index = await self.source(package)
        record = self._index_records[package]
        verification_level = (
            "archive_checksum_verified" if record.get("MD5sum") else "description_version_matched"
        )
        return self.package_metadata(
            package,
            metadata,
            [index.provenance(), artifact.provenance()],
            verification_level,
        )

    async def get_dependencies(self, package: str) -> dict:
        record, artifact = await self.current(package)
        return {
            "package": package,
            "package_version": record["Version"],
            "dependencies": {
                key: record.get(key, "")
                for key in ("Depends", "Imports", "Suggests", "LinkingTo", "Enhances")
            },
            "format": "Verbatim DCF values; empty string means field absent. Not transitive.",
            "sources": [artifact.provenance()],
        }

    async def get_function_docs(self, package: str, function: str, offset: int = 0) -> dict:
        if not function or len(function) > 160 or any(ord(c) < 32 for c in function) or offset < 0:
            raise KnowledgeError(
                "invalid_input", "Use a function alias (1..160 chars), offset >= 0"
            )
        metadata, files, artifact, index = await self.source(package)
        matches = []
        for name, body in files.items():
            if not name.endswith(".Rd"):
                continue
            text = decode(body, metadata.get("Encoding", "UTF-8"))
            if function in aliases(text):
                matches.append((name, text))
        if not matches:
            raise KnowledgeError(
                "docs_not_found",
                "No literal Rd alias found in this package version",
                artifact.source_url,
            )
        if len(matches) != 1:
            raise KnowledgeError(
                "ambiguous_docs", "Multiple Rd files define this alias", artifact.source_url
            )
        name, text = matches[0]
        if offset > len(text):
            raise KnowledgeError("invalid_input", "Documentation offset exceeds text length")
        end = min(offset + 8000, len(text))
        return {
            "package": package,
            "function": function,
            "package_version": metadata["Version"],
            "version_scope": "latest_cran"
            if self.repository == "cran"
            else "selected_bioconductor_release",
            "format": "text/x-r-doc (raw Rd; macros not evaluated)",
            "archive_member": name,
            "text": text[offset:end],
            "offset": offset,
            "total_characters": len(text),
            "truncated": end < len(text),
            "next_offset": end if end < len(text) else None,
            "sources": [index.provenance(), artifact.provenance()],
        }

    async def get_package_vignettes(self, package: str) -> dict:
        record, index = await self.current(package)
        artifact = await self.http.fetch(self.page_path(package))
        parser = PackagePageParser()
        parser.feed(decode(artifact.body))
        page_version = parser.rows.get("Version", parser.rows.get("Version:"))
        if page_version != record["Version"]:
            raise KnowledgeError(
                "version_mismatch", "Package page version differs from index", artifact.source_url
            )
        if self.repository == "cran":
            prefix = f"/web/packages/{package}/vignettes/"
        else:
            category = record["_category"]
            prefix = f"/packages/{self.bioc_version}/{category}/vignettes/{package}/inst/doc/"
        links = []
        seen = set()
        for href, label in parser.links:
            url = urljoin(artifact.source_url, href)
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != urlsplit(artifact.source_url).netloc
                or parsed.query
                or parsed.fragment
                or not re.fullmatch(
                    re.escape(prefix) + r"[A-Za-z0-9_.-]+\.(?:html|pdf|Rmd|Rnw|qmd|R)", parsed.path
                )
                or url in seen
            ):
                continue
            seen.add(url)
            links.append(
                {
                    "label": label,
                    "url": url,
                    "verification_status": "listed_by_official_package_page",
                }
            )
        return {
            "package": package,
            "package_version": record["Version"],
            "vignettes": links,
            "content_fetched": False,
            "sources": [index.provenance(), artifact.provenance()],
        }
