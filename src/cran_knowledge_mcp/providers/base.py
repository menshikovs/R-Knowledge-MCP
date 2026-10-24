"""Shared data-only operations for versioned source repositories."""

import asyncio
import hashlib
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from urllib.parse import urljoin, urlsplit

from ..errors import KnowledgeError
from ..http import Artifact, RepositoryHTTP, package_name, same_content, version_parts
from ..native import native
from ..parsers import PackagePageParser, aliases, dcf, decode, description_text, source_files

PARSED_SOURCE_CAPACITY = 8
PARSED_SOURCE_BYTES = 48 << 20


_WORD = re.compile(r"[0-9a-z]+")


class PackageSearchIndex:
    """Ranked name/title search, precomputed once per repository index.

    Every query term must match. Names match by exact value, prefix, word or (3+ chars)
    substring; titles match by whole word or (3+ chars) word prefix, so 'api' does not
    match 'therapy'. Ties sort by shorter name, then name.
    """

    def __init__(self, entries):
        entries = list(entries)
        self._native = (
            native.SearchIndex(
                [(name, name.casefold(), (title or "").casefold()) for name, title in entries]
            )
            if native is not None
            else None
        )
        self.entries = []
        if self._native is not None:
            return
        for name, title in entries:
            folded = name.casefold()
            title_folded = (title or "").casefold()
            self.entries.append(
                (
                    name,
                    folded,
                    set(_WORD.findall(folded)),
                    title_folded,
                    tuple(_WORD.findall(title_folded)),
                )
            )

    @staticmethod
    def _term_score(term, folded, name_words, title_folded, title_words):
        if folded == term:
            return 100
        if folded.startswith(term):
            return 40
        if term in name_words:
            return 30
        if any(word.startswith(term) for word in name_words):
            return 20
        if len(term) >= 3 and term in folded:
            return 10
        if _WORD.fullmatch(term) is None:
            # Punctuated terms such as data.table match title text literally.
            return 6 if len(term) >= 3 and term in title_folded else 0
        if term in title_words:
            return 8
        if len(term) >= 3 and any(word.startswith(term) for word in title_words):
            return 4
        return 0

    def search(self, query: str) -> list[str]:
        folded_query = " ".join(query.casefold().split())
        terms = folded_query.split()
        if self._native is not None:
            return self._native.search(terms, folded_query)
        ranked = []
        for name, folded, name_words, title_folded, title_words in self.entries:
            score = 0
            for term in terms:
                term_score = self._term_score(term, folded, name_words, title_folded, title_words)
                if not term_score:
                    break
                score += term_score
            else:
                if folded == folded_query:
                    score += 1000
                ranked.append((-score, len(name), folded, name))
        ranked.sort()
        return [row[-1] for row in ranked]


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
        self._index_lock = asyncio.Lock()
        self._index_artifact: Artifact | None = None
        self._index_records: dict[str, dict[str, str]] = {}
        # Verified archive contents, valid only while the HTTP cache returns the same
        # Artifact object; a refetch (new checked_at) is checked and parsed again.
        self._parsed: OrderedDict[str, dict] = OrderedDict()
        self._parsed_bytes = 0
        self._gz_index_available = True

    async def fetch_index(self, path: str) -> Artifact:
        """Prefer the official compressed PACKAGES.gz; use PACKAGES only if it is absent."""
        if self._gz_index_available:
            try:
                return await self.http.fetch(path + ".gz")
            except KnowledgeError as exc:
                if exc.code != "not_found":
                    raise
                self._gz_index_available = False
        return await self.http.fetch(path)

    def _cached_source(self, artifact: Artifact) -> dict | None:
        entry = self._parsed.get(artifact.source_url)
        if entry is None or not same_content(entry["artifact"], artifact):
            return None
        self._parsed.move_to_end(artifact.source_url)
        return entry

    def _store_source(self, artifact: Artifact, metadata: dict, files: dict) -> None:
        size = sum(len(body) for body in files.values())
        if size > PARSED_SOURCE_BYTES:
            return
        previous = self._parsed.pop(artifact.source_url, None)
        if previous is not None:
            self._parsed_bytes -= previous["size"]
        while self._parsed and (
            self._parsed_bytes + size > PARSED_SOURCE_BYTES
            or len(self._parsed) >= PARSED_SOURCE_CAPACITY
        ):
            self._parsed_bytes -= self._parsed.popitem(last=False)[1]["size"]
        self._parsed[artifact.source_url] = {
            "artifact": artifact,
            "metadata": metadata,
            "files": files,
            "aliases": None,
            "size": size,
        }
        self._parsed_bytes += size

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
        cached = self._cached_source(artifact)
        if cached is not None:
            return cached["metadata"], cached["files"], artifact, index
        # Parsing is bounded and off the event loop; only one expanded archive at a time.
        async with self._parse_lock:
            cached = self._cached_source(artifact)
            if cached is not None:
                return cached["metadata"], cached["files"], artifact, index
            if record.get("MD5sum"):
                digest = await asyncio.to_thread(
                    lambda: hashlib.md5(artifact.body, usedforsecurity=False).hexdigest()
                )
                if digest != record["MD5sum"]:
                    raise KnowledgeError(
                        "checksum_mismatch",
                        "Archive checksum differs from CRAN index",
                        artifact.source_url,
                    )
            try:
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
            self._store_source(artifact, metadata, files)
        return metadata, files, artifact, index

    def _alias_index(self, artifact, metadata, files) -> dict[str, list[str]]:
        """Map each literal Rd alias to its archive members, once per verified archive."""
        entry = self._cached_source(artifact)
        if entry is not None and entry["aliases"] is not None:
            return entry["aliases"]
        index: dict[str, list[str]] = {}
        for name, body in files.items():
            if name.endswith(".Rd"):
                for alias in aliases(decode(body, metadata.get("Encoding", "UTF-8"))):
                    index.setdefault(alias, []).append(name)
        if entry is not None:
            entry["aliases"] = index
        return index

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
        # The index may have been refreshed while the archive was fetched.
        record = self._index_records.get(package, {})
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
        alias_index = await asyncio.to_thread(self._alias_index, artifact, metadata, files)
        matches = [
            (name, decode(files[name], metadata.get("Encoding", "UTF-8")))
            for name in alias_index.get(function, [])
        ]
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
