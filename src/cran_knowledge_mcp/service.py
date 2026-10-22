"""Transport-independent knowledge API. Installed versions are client-supplied only."""

import asyncio
import hashlib
from collections.abc import Awaitable
from datetime import UTC

from .errors import KnowledgeError
from .http import CATALOG, INDEX, Artifact, CranHTTP, package_name, version_parts
from .parsers import CatalogParser, aliases, dcf, decode, description_text, source_files


class KnowledgeService:
    def __init__(self, http: CranHTTP):
        self.http = http
        self._parse_lock = asyncio.Lock()
        self._index_artifact: Artifact | None = None
        self._index_records: dict[str, dict[str, str]] = {}

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

    async def current(self, package: str) -> tuple[dict[str, str], Artifact]:
        package_name(package)
        records, artifact = await self.index()
        if package not in records:
            raise KnowledgeError(
                "package_not_found",
                "Package is not in the current CRAN source index",
                artifact.source_url,
            )
        version_parts(records[package]["Version"])
        return records[package], artifact

    async def source(self, package: str):
        record, index = await self.current(package)
        version = record["Version"]
        artifact = await self.http.fetch(f"/src/contrib/{package}_{version}.tar.gz")
        if (
            record.get("MD5sum")
            and hashlib.md5(artifact.body, usedforsecurity=False).hexdigest() != record["MD5sum"]
        ):
            raise KnowledgeError(
                "checksum_mismatch", "Archive checksum differs from CRAN index", artifact.source_url
            )
        # Parsing is bounded and off the event loop; only one expanded archive at a time.
        async with self._parse_lock:
            files = await asyncio.to_thread(source_files, artifact.body, package)
        descriptions = dcf(description_text(files[f"{package}/DESCRIPTION"]))
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

    async def get_package_info(self, package: str) -> dict:
        metadata, _, artifact, index = await self.source(package)
        return {
            "package": package,
            "latest_cran_version": metadata["Version"],
            "installed_version": None,
            "title": metadata.get("Title"),
            "description": metadata.get("Description"),
            "authors": metadata.get("Author"),
            "authors_at_r": metadata.get("Authors@R"),
            "license": metadata.get("License"),
            "urls": metadata.get("URL"),
            "cran_url": f"https://cran.r-project.org/package={package}",
            "sources": [index.provenance(), artifact.provenance()],
        }

    async def get_dependencies(self, package: str) -> dict:
        record, artifact = await self.current(package)
        return {
            "package": package,
            "latest_cran_version": record["Version"],
            "dependencies": {
                key: record.get(key, "") for key in ("Depends", "Imports", "Suggests", "LinkingTo")
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
                "No literal Rd alias found in this CRAN version",
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
            "version_scope": "latest_cran",
            "format": "text/x-r-doc (raw Rd; macros not evaluated)",
            "archive_member": name,
            "text": text[offset:end],
            "offset": offset,
            "total_characters": len(text),
            "truncated": end < len(text),
            "next_offset": end if end < len(text) else None,
            "sources": [index.provenance(), artifact.provenance()],
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


async def bounded(operation: Awaitable[dict]) -> dict:
    """Keep a future transport or integration free of implementation-specific exceptions."""
    import json
    from datetime import datetime

    try:
        async with asyncio.timeout(60):
            result = await operation
        if len(json.dumps(result, ensure_ascii=False).encode()) > 60_000:
            raise KnowledgeError(
                "response_too_large", "Result exceeds 60000 bytes; narrow the query"
            )
        return result
    except TimeoutError:
        error = KnowledgeError("timeout", "Tool deadline exceeded")
    except KnowledgeError as exc:
        error = exc
    return {
        "error": {
            "code": error.code,
            "message": str(error),
            "source_url": error.source_url,
            "attempted_at": datetime.now(UTC).isoformat(),
        }
    }
