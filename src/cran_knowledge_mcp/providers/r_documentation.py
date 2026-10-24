"""Bounded indexing and keyword retrieval for the fixed set of official R manuals."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

import httpx

from ..errors import KnowledgeError

MAX_SOURCE_BYTES = 8 << 20
MAX_INDEX_BYTES = 64 << 20
MAX_SECTION_TEXT = 256 << 10
MAX_SECTIONS_PER_SOURCE = 5000
MAX_TOTAL_SECTIONS = 15000
MAX_QUERY_CHARS = 500
MAX_EXCERPT_CHARS = 1200
MAX_RESULTS = 10
SCHEMA_VERSION = 1
R_VERSION = re.compile(r"\bR version\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b", re.I)
TOKEN = re.compile(r"[\w][\w.:-]{0,63}", re.UNICODE)

SOURCES: tuple[dict[str, str], ...] = (
    {
        "document_id": "r-data-import-export",
        "title": "R Data Import/Export",
        "url": "https://cran.r-project.org/doc/manuals/r-release/R-data.html",
    },
    {
        "document_id": "r-installation-administration",
        "title": "R Installation and Administration",
        "url": "https://cran.r-project.org/doc/manuals/r-release/R-admin.html",
    },
    {
        "document_id": "writing-r-extensions",
        "title": "Writing R Extensions",
        "url": "https://cran.r-project.org/doc/manuals/r-release/R-exts.html",
    },
    {
        "document_id": "r-internals",
        "title": "R Internals",
        "url": "https://cran.r-project.org/doc/manuals/r-release/R-ints.html",
    },
    {
        "document_id": "r-faq",
        "title": "R FAQ",
        "url": "https://cran.r-project.org/doc/FAQ/R-FAQ.html",
    },
    {
        "document_id": "introduction-to-r",
        "title": "An Introduction to R",
        "url": "https://cran.r-project.org/doc/manuals/r-release/R-intro.html",
    },
)
SOURCE_BY_ID = {item["document_id"]: item for item in SOURCES}
URL_TO_ID = {item["url"]: item["document_id"] for item in SOURCES}
MANUAL_IDS = tuple(SOURCE_BY_ID)
ManualId = Literal[
    "r-data-import-export",
    "r-installation-administration",
    "writing-r-extensions",
    "r-internals",
    "r-faq",
    "introduction-to-r",
]
_BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "li",
    "ol",
    "p",
    "pre",
    "section",
    "ul",
}
_SKIP_TAGS = {"footer", "header", "nav", "noscript", "script", "style", "svg"}
_SKIP_NAMES = {"contents", "navigation", "shortcontents", "top"}


def default_index_path() -> Path:
    """Return a per-user cache path; callers cannot supply a path through MCP."""
    configured = os.environ.get("R_DOCUMENTATION_INDEX_PATH")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "R-Knowledge-MCP" / "r-documentation-index.json"
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "r-knowledge-mcp" / "r-documentation-index.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _token(match: re.Match) -> str:
    # Keep identifiers such as read.csv, but not sentence punctuation ("connection.").
    return match.group(0).casefold().rstrip(".:-")


def _tokens(value: str) -> list[str]:
    return [token for token in map(_token, TOKEN.finditer(value)) if len(token) > 1]


class _ManualParser(HTMLParser):
    """Extract heading-delimited sections while retaining code and table boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, Any]] = []
        self.title_parts: list[str] = []
        self.heading_stack: list[tuple[int, str, str | None]] = []
        self._heading_level: int | None = None
        self._heading_parts: list[str] = []
        self._heading_anchor: str | None = None
        self._section: dict[str, Any] | None = None
        self._pre_depth = 0
        self._skip_stack: list[tuple[str, bool]] = []
        self._pending_anchor: str | None = None
        self._in_title = 0
        self._text_size = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.casefold(): value for key, value in attrs}
        classes = set((attr.get("class") or "").casefold().split())
        names = {value.casefold() for key, value in attr.items() if key in {"id", "role"} and value}
        hidden = tag in _SKIP_TAGS or bool(names & _SKIP_NAMES) or "toc" in classes
        parent_hidden = self._skip_stack[-1][1] if self._skip_stack else False
        self._skip_stack.append((tag, hidden or parent_hidden))
        if self._skip_stack[-1][1]:
            return
        if tag == "title":
            self._in_title += 1
        if tag in {"a", "h1", "h2", "h3", "h4", "h5", "h6"}:
            anchor = attr.get("id") or attr.get("name")
            if anchor:
                self._pending_anchor = anchor[:200]
        if tag == "pre":
            self._pre_depth += 1
        if tag == "tr":
            self._boundary("\n")
        elif tag in {"td", "th"}:
            self._boundary(" | ")
        elif tag in _BLOCK_TAGS:
            self._boundary("\n")
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self._finish_heading()
            self._heading_level = int(tag[1])
            self._heading_parts = []
            self._heading_anchor = attr.get("id") or attr.get("name") or self._pending_anchor
            self._pending_anchor = None

    def handle_endtag(self, tag: str) -> None:
        active = self._skip_stack[-1][1] if self._skip_stack else False
        if not active:
            if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
                self._finish_heading()
            if tag == "pre" and self._pre_depth:
                self._pre_depth -= 1
            if tag == "title" and self._in_title:
                self._in_title -= 1
            if tag == "tr":
                self._boundary("\n")
            elif tag in _BLOCK_TAGS:
                self._boundary("\n")
        for index in range(len(self._skip_stack) - 1, -1, -1):
            if self._skip_stack[index][0] == tag:
                del self._skip_stack[index:]
                break

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._skip_stack and self._skip_stack[-1][1]:
            return
        if self._in_title:
            self.title_parts.append(data)
        if self._heading_level is not None:
            self._heading_parts.append(data)
            return
        if self._section is None:
            return
        preserve = bool(self._pre_depth)
        normalized = data if preserve else " ".join(data.split())
        if normalized:
            self._section["_parts"].append((normalized, preserve))
            self._text_size += len(normalized)
            if self._text_size > MAX_INDEX_BYTES:
                raise KnowledgeError("source_too_large", "Parsed manual text exceeds index limit")

    def _boundary(self, value: str) -> None:
        if self._heading_level is not None:
            self._heading_parts.append(" ")
        elif self._section is not None and self._section["_parts"]:
            self._section["_parts"].append((value, bool(self._pre_depth)))

    def _finish_heading(self) -> None:
        if self._heading_level is None:
            return
        heading = re.sub(r"\s+", " ", " ".join(self._heading_parts)).strip()
        level = self._heading_level
        self._heading_level = None
        self._heading_parts = []
        if not heading:
            return
        self._finish_section()
        self.heading_stack = [entry for entry in self.heading_stack if entry[0] < level]
        self.heading_stack.append((level, heading, self._heading_anchor))
        self._section = {
            "heading": heading[:500],
            "hierarchy": [entry[1] for entry in self.heading_stack],
            "anchor": self._heading_anchor,
            "_parts": [],
        }
        self._heading_anchor = None
        if len(self.sections) >= MAX_SECTIONS_PER_SOURCE:
            raise KnowledgeError("source_too_large", "Manual contains too many sections")

    def _finish_section(self) -> None:
        if self._section is None:
            return
        parts = []
        for value, preserve in self._section.pop("_parts"):
            if value in {"\n", " | "}:
                parts.append(value)
            elif preserve:
                parts.append(value.replace("\r\n", "\n").replace("\r", "\n"))
            else:
                parts.append(" ".join(value.split()))
        text = "".join(parts).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if text:
            if len(text) > MAX_SECTION_TEXT:
                raise KnowledgeError("source_too_large", "A manual section exceeds the index limit")
            self._section["text"] = text
            self.sections.append(self._section)
        self._section = None

    def finish(self) -> tuple[str, list[dict[str, Any]]]:
        self._finish_heading()
        self._finish_section()
        page_title = re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()
        return page_title[:500], self.sections


def parse_manual(html: str, document_id: str) -> dict[str, Any]:
    """Parse a bounded HTML manual into stable, heading-based section records."""
    if document_id not in SOURCE_BY_ID:
        raise KnowledgeError("invalid_input", "Unknown official R manual")
    if not isinstance(html, str):
        raise KnowledgeError("invalid_source", "Official R manual was not decoded as text")
    try:
        source_size = len(html.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise KnowledgeError(
            "invalid_source", "Official R manual contains invalid Unicode"
        ) from exc
    if source_size > MAX_SOURCE_BYTES:
        raise KnowledgeError("source_too_large", "Official R manual exceeds the byte limit")
    parser = _ManualParser()
    try:
        parser.feed(html)
        page_title, sections = parser.finish()
    except (ValueError, UnicodeError) as exc:
        raise KnowledgeError("invalid_source", "Official R manual could not be parsed") from exc
    seen: set[str] = set()
    seen_section_ids: set[str] = set()
    result = []
    for section in sections:
        identity = "\n".join(section["hierarchy"])
        anchor = section.get("anchor")
        section_id = hashlib.sha256(f"{document_id}\0{anchor or identity}".encode()).hexdigest()[
            :16
        ]
        if section_id in seen_section_ids:
            raise KnowledgeError(
                "invalid_source", "Official R manual contains duplicate section identities"
            )
        text_hash = hashlib.sha256(section["text"].encode("utf-8")).hexdigest()
        if text_hash in seen:
            continue
        seen.add(text_hash)
        seen_section_ids.add(section_id)
        result.append(
            {
                "section_id": section_id,
                "heading": section["heading"],
                "hierarchy": section["hierarchy"],
                "anchor": anchor,
                "text": section["text"],
                "content_hash": text_hash,
            }
        )
    all_text = html[:32768]
    match = R_VERSION.search(re.sub(r"<[^>]+>", " ", all_text))
    return {
        "page_title": page_title,
        "r_version": match.group(1) if match else None,
        "sections": result,
    }


def _safe_index(raw: Any) -> dict[str, Any] | None:
    if (
        not isinstance(raw, dict)
        or type(raw.get("schema_version")) is not int
        or raw.get("schema_version") != SCHEMA_VERSION
    ):
        return None
    sources = raw.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(SOURCE_BY_ID):
        return None
    generated_at = raw.get("generated_at")
    if not _valid_timestamp(generated_at):
        return None
    count = 0
    normalized: dict[str, Any] = {}
    for document_id, definition in SOURCE_BY_ID.items():
        item = sources.get(document_id)
        if not isinstance(item, dict) or item.get("source_url") != definition["url"]:
            return None
        sections = item.get("sections", [])
        if not isinstance(sections, list) or len(sections) > MAX_SECTIONS_PER_SOURCE:
            return None
        count += len(sections)
        if count > MAX_TOTAL_SECTIONS:
            return None
        checked = item.get("checked_at")
        retrieved = item.get("retrieved_at")
        content_hash = item.get("content_hash")
        r_version = item.get("r_version")
        for timestamp in (checked, retrieved):
            if timestamp is not None and not _valid_timestamp(timestamp):
                return None
        if content_hash is not None and not re.fullmatch(r"[a-f0-9]{64}", str(content_hash)):
            return None
        if r_version is not None and (
            not isinstance(r_version, str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", r_version)
        ):
            return None
        for field in ("etag", "last_modified", "refresh_status", "page_title"):
            value = item.get(field)
            if value is not None and (not isinstance(value, str) or len(value) > 1000):
                return None
        if sections and (not isinstance(content_hash, str) or retrieved is None or checked is None):
            return None
        safe_sections = []
        seen_ids: set[str] = set()
        for section in sections:
            if not isinstance(section, dict):
                return None
            section_id = section.get("section_id")
            heading = section.get("heading")
            hierarchy = section.get("hierarchy")
            anchor = section.get("anchor")
            text = section.get("text")
            digest = section.get("content_hash")
            if (
                not isinstance(section_id, str)
                or not re.fullmatch(r"[a-f0-9]{16}", section_id)
                or section_id in seen_ids
                or not isinstance(heading, str)
                or not heading
                or len(heading) > 500
                or not isinstance(hierarchy, list)
                or not hierarchy
                or len(hierarchy) > 6
                or hierarchy[-1] != heading
                or any(
                    not isinstance(value, str) or not value or len(value) > 500
                    for value in hierarchy
                )
                or (anchor is not None and (not isinstance(anchor, str) or len(anchor) > 200))
                or not isinstance(text, str)
                or not text
                or len(text) > MAX_SECTION_TEXT
                or not isinstance(digest, str)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != digest
                or hashlib.sha256(
                    f"{document_id}\0{anchor or chr(10).join(hierarchy)}".encode()
                ).hexdigest()[:16]
                != section_id
            ):
                return None
            seen_ids.add(section_id)
            safe_sections.append(
                {
                    "section_id": section_id,
                    "heading": heading,
                    "hierarchy": hierarchy,
                    "anchor": anchor,
                    "text": text,
                    "content_hash": digest,
                }
            )
        normalized[document_id] = {
            **{
                key: item.get(key)
                for key in (
                    "source_url",
                    "checked_at",
                    "retrieved_at",
                    "r_version",
                    "content_hash",
                    "etag",
                    "last_modified",
                    "refresh_status",
                )
            },
            "title": definition["title"],
            "page_title": item.get("page_title")
            if isinstance(item.get("page_title"), str)
            else None,
            "sections": safe_sections,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "sources": normalized,
    }


class RDocumentationProvider:
    """Reads a local index for MCP calls and refreshes only through an explicit command."""

    def __init__(self, client: httpx.AsyncClient | None = None, index_path: Path | None = None):
        self.client = client
        self.index_path = Path(index_path) if index_path is not None else default_index_path()
        self._loaded_signature: tuple[int, int, int, int] | None = None
        self._index: dict[str, Any] | None = None
        self._load_error: str | None = None
        self._load_lock = threading.RLock()
        self._ranker_index: dict[str, Any] | None = None
        self._ranker_instance: _SectionRanker | None = None

    def _ranker(self, index: dict[str, Any]) -> _SectionRanker | None:
        """Build the in-memory FTS5 index once per validated index object."""
        with self._load_lock:
            if self._ranker_index is not index:
                self._ranker_instance = _SectionRanker.build(index)
                self._ranker_index = index
            return self._ranker_instance

    def _load_state(self) -> tuple[dict[str, Any] | None, str | None]:
        with self._load_lock:
            index = self._load()
            return index, self._load_error

    def _load(self) -> dict[str, Any] | None:
        with self._load_lock:
            try:
                stream = self.index_path.open("rb")
            except OSError:
                self._index = None
                self._loaded_signature = None
                self._load_error = "index_unavailable"
                return None

            with stream:
                try:
                    before = os.fstat(stream.fileno())
                except OSError:
                    self._index = None
                    self._loaded_signature = None
                    self._load_error = "index_unavailable"
                    return None

                signature = self._file_signature(before)
                if signature == self._loaded_signature:
                    return self._index
                if before.st_size > MAX_INDEX_BYTES:
                    self._index = None
                    self._loaded_signature = signature
                    self._load_error = "index_invalid"
                    return None

                try:
                    data = stream.read(MAX_INDEX_BYTES + 1)
                    after_signature = self._file_signature(os.fstat(stream.fileno()))
                except OSError:
                    self._index = None
                    self._loaded_signature = None
                    self._load_error = "index_unavailable"
                    return None

            if len(data) > MAX_INDEX_BYTES or signature != after_signature:
                self._index = None
                # Retry on the next request after a concurrent in-place mutation.
                self._loaded_signature = None
                self._load_error = "index_invalid"
                return None

            try:
                raw = json.loads(data.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError):
                raw = None
            try:
                self._index = _safe_index(raw)
            except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
                self._index = None
            self._loaded_signature = signature
            self._load_error = None if self._index is not None else "index_invalid"
            return self._index

    @staticmethod
    def _file_signature(stat: os.stat_result) -> tuple[int, int, int, int]:
        return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)

    async def asearch(
        self,
        query: str,
        manuals: list[str] | None = None,
        limit: int = 5,
        r_version: str | None = None,
    ) -> dict[str, Any]:
        """Run bounded local search in a worker thread from async request paths."""
        return await asyncio.to_thread(self.search, query, manuals, limit, r_version)

    async def aget_section(
        self, document_id: str, section_id: str, max_chars: int = 8000
    ) -> dict[str, Any]:
        """Load a bounded local section without blocking the async request loop."""
        return await asyncio.to_thread(self.get_section, document_id, section_id, max_chars)

    def search(
        self,
        query: str,
        manuals: list[str] | None = None,
        limit: int = 5,
        r_version: str | None = None,
    ) -> dict[str, Any]:
        """Search indexed sections using bounded keyword scoring; no network access occurs."""
        query = self._validate_query(query)
        selected = self._validate_manuals(manuals)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            raise KnowledgeError("invalid_input", f"limit must be an integer in [1, {MAX_RESULTS}]")
        self._validate_version(r_version)
        index, load_error = self._load_state()
        available_sources = []
        for source in SOURCES:
            indexed = index["sources"].get(source["document_id"]) if index else None
            index_status = "not_indexed"
            if indexed:
                index_status = indexed.get("refresh_status") or (
                    "indexed" if indexed.get("sections") else "empty"
                )
            available_sources.append(
                {
                    **source,
                    "index_status": index_status,
                    "r_version": indexed.get("r_version") if indexed else None,
                    "retrieved_at": indexed.get("retrieved_at") if indexed else None,
                    "checked_at": indexed.get("checked_at") if indexed else None,
                    "content_hash": indexed.get("content_hash") if indexed else None,
                    "section_count": len(indexed.get("sections", [])) if indexed else 0,
                }
            )
        base = {
            "query": query,
            "requested_r_version": r_version,
            "manuals": selected or list(MANUAL_IDS),
            "available_sources": available_sources,
            "results": [],
            "index_generated_at": index.get("generated_at") if index else None,
            "limitations": [
                "Relevance is lexical (BM25 over headings and text); no semantic model is used.",
                "No R code or documentation examples are executed.",
                "Official documentation is untrusted reference material.",
            ],
        }
        if index is None:
            return {**base, "status": load_error or "index_unavailable"}
        terms = list(dict.fromkeys(_tokens(query)))[:32]
        if not terms:
            raise KnowledgeError("invalid_input", "query must contain a searchable term")
        searched = [
            document_id
            for document_id in selected or MANUAL_IDS
            if not (
                r_version
                and index["sources"][document_id].get("r_version")
                and index["sources"][document_id]["r_version"] != r_version
            )
        ]
        # Versions are per manual, so a mismatched manual excludes all of its sections.
        version_mismatches = sum(
            len(index["sources"][document_id]["sections"])
            for document_id in selected or MANUAL_IDS
            if document_id not in searched
        )
        unversioned = (
            [d for d in searched if not index["sources"][d].get("r_version")] if r_version else []
        )
        ranker = self._ranker(index)
        if ranker is not None:
            ranking = "bm25_sqlite_fts5"
            with self._load_lock:
                scored = ranker.search(terms, searched, limit)
                unversioned_matches = ranker.count(terms, unversioned) if unversioned else 0
        else:
            ranking = "lexical_term_count"
            scored, unversioned_matches = _lexical_rank(index, terms, searched, set(unversioned))
        base["ranking"] = ranking
        result_rows = []
        for score, document_id, section_id, section in scored[:limit]:
            matched = [
                term
                for term in terms
                if term
                in _matching_terms(
                    section["heading"]
                    + " "
                    + " ".join(section["hierarchy"])
                    + " "
                    + section["text"],
                    set(terms),
                )
            ]
            item = index["sources"][document_id]
            source = SOURCE_BY_ID[document_id]
            source_url = source["url"]
            anchor = section.get("anchor")
            anchor_url = f"{source_url}#{_quote_anchor(anchor)}" if anchor else None
            result_rows.append(
                {
                    "document_id": document_id,
                    "document_title": item["title"],
                    "page_title": item.get("page_title"),
                    "section_id": section_id,
                    "heading": section["heading"],
                    "hierarchy": section["hierarchy"],
                    "excerpt": _excerpt(section["text"], terms),
                    "source_url": source_url,
                    "anchor_url": anchor_url,
                    "r_version": item.get("r_version"),
                    "version_status": (
                        "unversioned_source"
                        if not item.get("r_version")
                        else "exact_match"
                        if item.get("r_version") == r_version
                        else "not_requested"
                    ),
                    "retrieved_at": item.get("retrieved_at"),
                    "checked_at": item.get("checked_at"),
                    "content_hash": item.get("content_hash"),
                    "refresh_status": item.get("refresh_status") or "indexed",
                    "relevance_score": score,
                    "matched_terms": matched,
                    "verification_status": "indexed_official_documentation",
                    "trust": "untrusted_reference_material",
                }
            )
        selected_items = [index["sources"][document_id] for document_id in (selected or MANUAL_IDS)]
        available_section_count = sum(len(item["sections"]) for item in selected_items)
        status = "ok" if result_rows else "no_matching_sections"
        warning = None
        if not result_rows and r_version and version_mismatches:
            status = "requested_r_version_unavailable"
            warning = (
                "Indexed versioned manuals do not match the requested R version; "
                "no mismatched sections were returned."
            )
        elif not result_rows and not available_section_count:
            source_failures = any(
                item.get("refresh_status") in {"unavailable", "stale_after_refresh_error"}
                for item in selected_items
            )
            if source_failures:
                status = "sources_unavailable"
                warning = "No selected official R manual has usable indexed sections."
            else:
                status = "index_empty"
                warning = (
                    "The selected official R manual index is present but contains no sections."
                )
        elif result_rows:
            warning_parts = []
            if version_mismatches:
                warning_parts.append("Versioned sections from a different R version were excluded.")
            if unversioned_matches:
                warning_parts.append(
                    "Some returned manuals have no detected R version; "
                    "version compatibility is unknown."
                )
            if any(
                item.get("refresh_status") == "stale_after_refresh_error" for item in selected_items
            ):
                warning_parts.append(
                    "Some returned manual content was retained after a refresh error; "
                    "review its retrieval and check timestamps."
                )
            warning = " ".join(warning_parts) or None
        return {
            **base,
            "status": status,
            "results": result_rows,
            "version_mismatch_count": version_mismatches,
            "warning": warning,
        }

    def get_section(
        self, document_id: str, section_id: str, max_chars: int = 8000
    ) -> dict[str, Any]:
        """Retrieve one exact indexed section by its opaque stable identifiers."""
        if document_id not in SOURCE_BY_ID:
            raise KnowledgeError("invalid_input", "Select an official R manual identifier")
        if not isinstance(section_id, str) or not re.fullmatch(r"[a-f0-9]{16}", section_id):
            raise KnowledgeError(
                "invalid_input", "section_id must be a returned section identifier"
            )
        if (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or not 1 <= max_chars <= 32000
        ):
            raise KnowledgeError("invalid_input", "max_chars must be an integer in [1, 32000]")
        index, load_error = self._load_state()
        if index is None:
            return {"status": load_error or "index_unavailable", "section": None}
        item = index["sources"][document_id]
        for section in item["sections"]:
            if section["section_id"] == section_id:
                source_url = SOURCE_BY_ID[document_id]["url"]
                anchor = section.get("anchor")
                return {
                    "status": "ok",
                    "section": {
                        "document_id": document_id,
                        "document_title": item["title"],
                        **section,
                        "text": section["text"][:max_chars],
                        "content_length": len(section["text"]),
                        "truncated": len(section["text"]) > max_chars,
                        "source_url": source_url,
                        "anchor_url": f"{source_url}#{_quote_anchor(anchor)}" if anchor else None,
                        "r_version": item.get("r_version"),
                        "retrieved_at": item.get("retrieved_at"),
                        "checked_at": item.get("checked_at"),
                        "content_hash": item.get("content_hash"),
                        "refresh_status": item.get("refresh_status") or "indexed",
                        "verification_status": "indexed_official_documentation",
                        "trust": "untrusted_reference_material",
                    },
                }
        return {"status": "section_not_found", "section": None}

    def get_outline(self, document_id: str) -> dict[str, Any]:
        """List one indexed manual's section identifiers and headings, without section text."""
        if document_id not in SOURCE_BY_ID:
            raise KnowledgeError("invalid_input", "Select an official R manual identifier")
        index, load_error = self._load_state()
        if index is None:
            return {"status": load_error or "index_unavailable", "document_id": document_id}
        item = index["sources"][document_id]
        return {
            "status": "ok" if item["sections"] else "index_empty",
            "document_id": document_id,
            "document_title": item["title"],
            "source_url": SOURCE_BY_ID[document_id]["url"],
            "r_version": item.get("r_version"),
            "retrieved_at": item.get("retrieved_at"),
            "checked_at": item.get("checked_at"),
            "refresh_status": item.get("refresh_status") or "indexed",
            "sections": [
                {
                    "section_id": section["section_id"],
                    "heading": section["heading"],
                    "level": len(section["hierarchy"]),
                }
                for section in item["sections"]
            ],
            "trust": "untrusted_reference_material",
        }

    async def aget_outline(self, document_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_outline, document_id)

    async def refresh(self) -> dict[str, Any]:
        """Fetch the six fixed sources and atomically replace the local index."""
        if self.client is None:
            raise KnowledgeError("invalid_configuration", "An HTTP client is required for refresh")
        old_index = self._load()
        old_sources = old_index["sources"] if old_index else {}
        records: dict[str, Any] = {}
        outcomes: list[dict[str, Any]] = []
        for source in SOURCES:
            document_id = source["document_id"]
            previous = old_sources.get(document_id, {})
            try:
                fetched = await self._fetch(source, previous)
                if fetched["not_modified"]:
                    updated = {
                        **previous,
                        "checked_at": fetched["checked_at"],
                        "refresh_status": "not_modified",
                    }
                else:
                    body = fetched["body"]
                    parsed = parse_manual(body.decode("utf-8"), document_id)
                    content_hash = hashlib.sha256(body).hexdigest()
                    updated = {
                        "source_url": source["url"],
                        "title": source["title"],
                        "page_title": parsed["page_title"],
                        "r_version": parsed["r_version"],
                        "retrieved_at": fetched["checked_at"],
                        "checked_at": fetched["checked_at"],
                        "content_hash": content_hash,
                        "etag": fetched["etag"],
                        "last_modified": fetched["last_modified"],
                        "refresh_status": "updated",
                        "sections": parsed["sections"],
                    }
                records[document_id] = updated
                outcomes.append(
                    {
                        "document_id": document_id,
                        "status": updated["refresh_status"],
                        "section_count": len(updated.get("sections", [])),
                    }
                )
            except (httpx.HTTPError, TimeoutError, UnicodeError, KnowledgeError) as exc:
                if previous.get("sections"):
                    records[document_id] = {
                        **previous,
                        "refresh_status": "stale_after_refresh_error",
                    }
                else:
                    records[document_id] = {
                        "source_url": source["url"],
                        "title": source["title"],
                        "page_title": None,
                        "r_version": None,
                        "retrieved_at": None,
                        "checked_at": _utc_now(),
                        "content_hash": None,
                        "etag": None,
                        "last_modified": None,
                        "refresh_status": "unavailable",
                        "sections": [],
                    }
                code = exc.code if isinstance(exc, KnowledgeError) else "source_unavailable"
                outcomes.append(
                    {
                        "document_id": document_id,
                        "status": "unavailable",
                        "error_code": code,
                        "section_count": len(records[document_id].get("sections", [])),
                    }
                )
        total_sections = sum(len(item.get("sections", [])) for item in records.values())
        if total_sections > MAX_TOTAL_SECTIONS:
            raise KnowledgeError(
                "source_too_large", "Combined R manual index exceeds section limit"
            )
        index = {"schema_version": SCHEMA_VERSION, "generated_at": _utc_now(), "sources": records}
        self._write_index(index)
        with self._load_lock:
            self._loaded_signature = None
        self._load()
        return {
            "status": "updated"
            if any(item["status"] in {"updated", "not_modified"} for item in outcomes)
            else "unavailable",
            "index_path": str(self.index_path),
            "source_results": outcomes,
            "not_executed": True,
        }

    async def _fetch(self, source: dict[str, str], previous: dict[str, Any]) -> dict[str, Any]:
        headers = {"Accept": "text/html", "Accept-Encoding": "identity"}
        if previous.get("etag"):
            headers["If-None-Match"] = previous["etag"]
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = previous["last_modified"]
        body = bytearray()
        async with asyncio.timeout(30):
            async with self.client.stream(
                "GET", source["url"], follow_redirects=False, timeout=20, headers=headers
            ) as response:
                checked_at = _utc_now()
                if response.status_code == 304 and previous.get("sections"):
                    return {"not_modified": True, "checked_at": checked_at}
                if response.status_code != 200:
                    if 300 <= response.status_code < 400:
                        raise KnowledgeError(
                            "unsafe_redirect",
                            "Official R manual redirects are not followed",
                            source["url"],
                        )
                    code = "not_found" if response.status_code == 404 else "source_unavailable"
                    raise KnowledgeError(
                        code,
                        f"Official R manual returned HTTP {response.status_code}",
                        source["url"],
                    )
                if response.headers.get("content-encoding", "identity").casefold() != "identity":
                    raise KnowledgeError(
                        "invalid_source",
                        "Compressed R manual responses are not accepted",
                        source["url"],
                    )
                content_type = response.headers.get("content-type", "text/html").casefold()
                if "text/html" not in content_type:
                    raise KnowledgeError(
                        "invalid_source", "Official R manual did not return HTML", source["url"]
                    )
                async for chunk in response.aiter_bytes(65536):
                    body.extend(chunk)
                    if len(body) > MAX_SOURCE_BYTES:
                        raise KnowledgeError(
                            "source_too_large", "Official R manual exceeds 8 MiB", source["url"]
                        )
        return {
            "not_modified": False,
            "checked_at": checked_at,
            "body": bytes(body),
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        }

    def _write_index(self, index: dict[str, Any]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_INDEX_BYTES:
            raise KnowledgeError("source_too_large", "R manual index exceeds 64 MiB")
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.index_path.parent,
                prefix=f".{self.index_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.index_path)
        except OSError as exc:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise KnowledgeError("index_write_failed", "R manual index could not be saved") from exc

    @staticmethod
    def _validate_query(query: str) -> str:
        if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
            raise KnowledgeError("invalid_input", "query must be 1..500 characters")
        if any(ord(char) < 32 and char not in "\t\n\r" for char in query):
            raise KnowledgeError("invalid_input", "query contains control characters")
        return query.strip()

    @staticmethod
    def _validate_manuals(manuals: list[str] | None) -> list[str] | None:
        if manuals is None:
            return None
        if not isinstance(manuals, list) or not manuals or len(manuals) > len(MANUAL_IDS):
            raise KnowledgeError(
                "invalid_input", "manuals must select one or more official manual IDs"
            )
        if any(not isinstance(item, str) or item not in SOURCE_BY_ID for item in manuals):
            raise KnowledgeError("invalid_input", "manuals contains an unknown official manual ID")
        if len(set(manuals)) != len(manuals):
            raise KnowledgeError("invalid_input", "manuals must not contain duplicate IDs")
        return manuals

    @staticmethod
    def _validate_version(r_version: str | None) -> None:
        if r_version is not None and (
            not isinstance(r_version, str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", r_version)
        ):
            raise KnowledgeError("invalid_input", "Use an R version such as 4.5 or 4.5.1")


class _SectionRanker:
    """In-memory SQLite FTS5 index; BM25 weights headings above hierarchy above text."""

    def __init__(self, connection: sqlite3.Connection, rows: list[tuple[str, dict[str, Any]]]):
        self.connection = connection
        self.rows = rows

    @classmethod
    def build(cls, index: dict[str, Any]) -> _SectionRanker | None:
        try:
            connection = sqlite3.connect(":memory:", check_same_thread=False)
            connection.execute(
                "CREATE VIRTUAL TABLE sections USING fts5("
                "heading, hierarchy, text, document_id UNINDEXED, "
                "tokenize='unicode61 remove_diacritics 2')"
            )
        except sqlite3.Error:
            return None  # SQLite without FTS5: fall back to lexical counting.
        rows = []
        for document_id in MANUAL_IDS:
            for section in index["sources"][document_id]["sections"]:
                rows.append((document_id, section))
        connection.executemany(
            "INSERT INTO sections(rowid, heading, hierarchy, text, document_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                (rowid, section["heading"], " ".join(section["hierarchy"]), section["text"], doc)
                for rowid, (doc, section) in enumerate(rows)
            ),
        )
        return cls(connection, rows)

    @staticmethod
    def _expression(terms: list[str]) -> str:
        # Each term is a quoted phrase, so query text is never FTS5 syntax.
        return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)

    def search(self, terms, documents, limit):
        if not documents:
            return []
        placeholders = ",".join("?" * len(documents))
        rows = self.connection.execute(
            "SELECT rowid, bm25(sections, 3.0, 2.0, 1.0) AS rank FROM sections "
            f"WHERE sections MATCH ? AND document_id IN ({placeholders}) "
            "ORDER BY rank, rowid LIMIT ?",
            (self._expression(terms), *documents, limit),
        ).fetchall()
        output = []
        for rowid, rank in rows:
            document_id, section = self.rows[rowid]
            output.append((round(-rank, 4), document_id, section["section_id"], section))
        return output

    def count(self, terms, documents):
        placeholders = ",".join("?" * len(documents))
        return self.connection.execute(
            "SELECT count(*) FROM sections "
            f"WHERE sections MATCH ? AND document_id IN ({placeholders})",
            (self._expression(terms), *documents),
        ).fetchone()[0]


def _lexical_rank(index, terms, documents, unversioned):
    scored = []
    unversioned_matches = 0
    wanted = set(terms)
    for document_id in documents:
        for section in index["sources"][document_id]["sections"]:
            text_terms = _matching_terms(section["text"], wanted)
            heading_terms = _matching_terms(
                section["heading"] + " " + " ".join(section["hierarchy"]), wanted
            )
            matched = [term for term in terms if term in text_terms or term in heading_terms]
            if not matched:
                continue
            if document_id in unversioned:
                unversioned_matches += 1
            score = sum((3 if term in heading_terms else 1) for term in matched)
            scored.append((score, document_id, section["section_id"], section))
    scored.sort(key=lambda row: (-row[0], row[1], row[3]["heading"].casefold(), row[2]))
    return scored, unversioned_matches


def _quote_anchor(anchor: str) -> str:
    from urllib.parse import quote

    return quote(anchor, safe="-._~")


def _matching_terms(text: str, wanted: set[str]) -> set[str]:
    """Scan once and retain only the bounded query vocabulary, not the whole token set."""
    return {token for token in map(_token, TOKEN.finditer(text)) if token in wanted}


def _excerpt(text: str, terms: list[str]) -> str:
    folded = text.casefold()
    positions = [folded.find(term) for term in terms if folded.find(term) >= 0]
    start = max(0, min(positions) - 160) if positions else 0
    excerpt = text[start : start + MAX_EXCERPT_CHARS].strip()
    if start:
        excerpt = "…" + excerpt
    if start + MAX_EXCERPT_CHARS < len(text):
        excerpt += "…"
    return excerpt


async def _refresh(index_path: Path) -> dict[str, Any]:
    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=20,
        headers={"User-Agent": "cran-knowledge-mcp/0.1 (official R manuals indexer)"},
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
    ) as client:
        return await RDocumentationProvider(client, index_path).refresh()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the fixed official R manual index")
    parser.add_argument("--refresh", action="store_true", help="Fetch the six fixed CRAN manuals")
    parser.add_argument("--index-path", type=Path, default=default_index_path())
    args = parser.parse_args()
    if not args.refresh:
        parser.error("--refresh is required; ordinary MCP calls never fetch manuals")
    try:
        result = asyncio.run(_refresh(args.index_path))
    except Exception as exc:
        print(f"R documentation refresh failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
