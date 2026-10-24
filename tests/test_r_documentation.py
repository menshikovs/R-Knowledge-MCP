import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.providers import r_documentation as r_docs
from cran_knowledge_mcp.providers.r_documentation import (
    MANUAL_IDS,
    SOURCES,
    RDocumentationProvider,
    parse_manual,
)

HTML_FIXTURE = """<!doctype html>
<html><head><title>R Manual, R version 4.5.1</title></head>
<body><nav><a href="#import">Navigation import data</a></nav>
<h1 id="manual-title">Manual title</h1>
<p>Introductory text with <code>read.csv</code> and import.</p>
<h2 id="data-import">Data import</h2>
<p>Use read.table for delimited data. CSV import and export are supported.</p>
<table><tr><th>Function</th><th>Purpose</th></tr>
<tr><td>read.csv</td><td>Read comma-separated values</td></tr></table>
<pre>read.csv(\n  file = "data.csv"\n)</pre>
<h3 id="nested-topic">Nested topic</h3><p>Nested section uses a connection.</p>
</body></html>"""


@pytest.fixture
def index_path():
    """Use an isolated temporary file in the existing test directory, not a temp directory."""
    path = Path(__file__).with_name(f".r-doc-index-{uuid4().hex}.json")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


async def build_index(path, handler=None):
    calls = []

    def default_handler(request):
        calls.append(request)
        assert request.url.host == "cran.r-project.org"
        assert request.url.query == b""
        return httpx.Response(
            200,
            text=HTML_FIXTURE,
            headers={
                "content-type": "text/html; charset=utf-8",
                "etag": '"fixture-v1"',
                "last-modified": "Thu, 23 Oct 2026 10:00:00 GMT",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler or default_handler),
        trust_env=False,
        follow_redirects=False,
    ) as client:
        provider = RDocumentationProvider(client, path)
        report = await provider.refresh()
    return provider, report, calls


def test_official_source_registry_contains_exactly_six_fixed_cran_urls():
    assert len(SOURCES) == 6
    assert {item["document_id"] for item in SOURCES} == set(MANUAL_IDS)
    assert all(item["url"].startswith("https://cran.r-project.org/doc/") for item in SOURCES)
    assert len({item["url"] for item in SOURCES}) == 6


def test_parser_preserves_heading_hierarchy_anchor_tables_and_code():
    parsed = parse_manual(HTML_FIXTURE, "r-data-import-export")

    assert parsed["page_title"] == "R Manual, R version 4.5.1"
    assert parsed["r_version"] == "4.5.1"
    assert [item["heading"] for item in parsed["sections"]] == [
        "Manual title",
        "Data import",
        "Nested topic",
    ]
    imported = parsed["sections"][1]
    assert imported["hierarchy"] == ["Manual title", "Data import"]
    assert imported["anchor"] == "data-import"
    assert "Function | Purpose" in imported["text"]
    assert 'read.csv(\n  file = "data.csv"\n)' in imported["text"]
    assert "Navigation import data" not in " ".join(item["text"] for item in parsed["sections"])


def test_parser_deduplicates_identical_section_text_and_handles_malformed_html():
    parsed = parse_manual(
        "<h1>Manual</h1><h2>First</h2><p>same text</p><h2>Second</h2><p>same text</p><h3>Unclosed",
        "r-faq",
    )
    assert len(parsed["sections"]) == 1
    assert parsed["sections"][0]["text"] == "same text"

    with pytest.raises(KnowledgeError, match="duplicate section identities"):
        parse_manual(
            '<h1 id="duplicate">First</h1><p>first content</p>'
            '<h2 id="duplicate">Second</h2><p>second content</p>',
            "r-faq",
        )


@pytest.mark.asyncio
async def test_explicit_refresh_indexes_sections_and_search_returns_citations(index_path):
    path = index_path
    provider, report, calls = await build_index(path)

    result = provider.search("CSV import read.csv", ["r-data-import-export"], limit=3)
    assert report["status"] == "updated"
    assert len(calls) == 6
    assert result["status"] == "ok"
    assert result["results"]
    first = result["results"][0]
    assert first["document_id"] == "r-data-import-export"
    assert first["heading"] == "Data import"
    assert first["anchor_url"] == first["source_url"] + "#data-import"
    assert first["r_version"] == "4.5.1"
    assert len(first["content_hash"]) == 64
    assert len(first["excerpt"]) <= 1202
    assert first["trust"] == "untrusted_reference_material"

    retrieved = provider.get_section(first["document_id"], first["section_id"])
    assert retrieved["status"] == "ok"
    assert retrieved["section"]["text"]
    assert retrieved["section"]["anchor_url"] == first["anchor_url"]
    bounded = provider.get_section(first["document_id"], first["section_id"], max_chars=12)
    assert bounded["section"]["truncated"] is True
    assert len(bounded["section"]["text"]) == 12


@pytest.mark.asyncio
async def test_async_concurrent_searches_share_validated_index_safely(index_path):
    provider, _, _ = await build_index(index_path)

    results = await asyncio.gather(
        *(
            provider.asearch("CSV import read.csv", ["r-data-import-export"], limit=3)
            for _ in range(12)
        )
    )

    assert all(result["status"] == "ok" for result in results)
    assert all(
        result["results"][0]["source_url"].startswith("https://cran.r-project.org/")
        for result in results
    )


@pytest.mark.asyncio
async def test_atomic_index_replacement_invalidates_cached_metadata(index_path):
    provider, _, _ = await build_index(index_path)
    first = provider.search("CSV import read.csv", ["r-data-import-export"])
    assert first["results"][0]["refresh_status"] == "updated"

    replacement = index_path.with_name(index_path.name + ".replacement")
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    raw["generated_at"] = "2026-10-24T00:00:01Z"
    raw["sources"]["r-data-import-export"]["refresh_status"] = "stale_after_refresh_error"
    replacement.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")
    original_mtime = index_path.stat().st_mtime_ns
    os.utime(replacement, ns=(original_mtime + 1_000_000_000,) * 2)
    os.replace(replacement, index_path)

    updated = await provider.asearch("CSV import read.csv", ["r-data-import-export"])

    assert updated["status"] == "ok"
    assert updated["results"][0]["refresh_status"] == "stale_after_refresh_error"
    assert "retained after a refresh error" in updated["warning"]


@pytest.mark.asyncio
async def test_present_empty_index_is_distinct_from_missing_and_no_match(index_path):
    provider, _, _ = await build_index(index_path)
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    for item in raw["sources"].values():
        item["sections"] = []
    index_path.write_text(json.dumps(raw), encoding="utf-8")

    empty = await provider.asearch("R data import")

    assert empty["status"] == "index_empty"
    assert empty["results"] == []

    provider, _, _ = await build_index(index_path)
    no_match = await provider.asearch("zzuniquequerytoken", ["r-data-import-export"])
    assert no_match["status"] == "no_matching_sections"
    assert no_match["results"] == []


@pytest.mark.asyncio
async def test_refresh_uses_conditional_requests_and_preserves_content_hash(index_path):
    path = index_path
    await build_index(path)
    first = json.loads(path.read_text(encoding="utf-8"))
    calls = []

    def unchanged(request):
        calls.append(request)
        assert request.headers["if-none-match"] == '"fixture-v1"'
        return httpx.Response(304)

    provider, report, _ = await build_index(path, unchanged)
    after = json.loads(path.read_text(encoding="utf-8"))
    assert report["status"] == "updated"
    assert len(calls) == 6
    assert all(item["status"] == "not_modified" for item in report["source_results"])
    assert after["sources"]["r-faq"]["content_hash"] == first["sources"]["r-faq"]["content_hash"]
    assert after["sources"]["r-faq"]["sections"] == first["sources"]["r-faq"]["sections"]


@pytest.mark.asyncio
async def test_refresh_failure_marks_retained_citations_as_stale(index_path):
    await build_index(index_path)

    def unavailable(_request):
        return httpx.Response(503)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unavailable),
        trust_env=False,
        follow_redirects=False,
    ) as client:
        provider = RDocumentationProvider(client, index_path)
        report = await provider.refresh()

    result = await provider.asearch("CSV import read.csv", ["r-data-import-export"])

    assert report["status"] == "unavailable"
    assert result["status"] == "ok"
    assert result["results"][0]["refresh_status"] == "stale_after_refresh_error"
    assert "retained after a refresh error" in result["warning"]


@pytest.mark.asyncio
async def test_version_mismatch_is_not_silently_returned(index_path):
    provider, _, _ = await build_index(index_path)
    result = provider.search("CSV import read.csv", ["r-data-import-export"], r_version="4.4.3")
    assert result["status"] == "requested_r_version_unavailable"
    assert result["results"] == []
    assert result["version_mismatch_count"] > 0
    assert result["warning"]


def test_missing_and_corrupt_indexes_fail_closed_without_network(index_path):
    path = index_path
    provider = RDocumentationProvider(index_path=path)
    missing = provider.search("R data import")
    assert missing["status"] == "index_unavailable"
    assert missing["results"] == []

    path.write_text("{ truncated", encoding="utf-8")
    corrupt = provider.search("R data import")
    assert corrupt["status"] == "index_invalid"
    assert corrupt["results"] == []

    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    unsupported_schema = provider.search("R data import")
    assert unsupported_schema["status"] == "index_invalid"
    assert unsupported_schema["results"] == []


def test_index_read_enforces_limit_even_if_open_file_metadata_underreports_size(
    index_path, monkeypatch
):
    monkeypatch.setattr(r_docs, "MAX_INDEX_BYTES", 32)
    index_path.write_bytes(b"x" * 33)
    real_fstat = os.fstat

    def underreport_size(file_descriptor):
        stat = real_fstat(file_descriptor)
        return SimpleNamespace(
            st_dev=stat.st_dev,
            st_ino=stat.st_ino,
            st_mtime_ns=stat.st_mtime_ns,
            st_size=1,
        )

    monkeypatch.setattr(r_docs.os, "fstat", underreport_size)
    result = RDocumentationProvider(index_path=index_path).search("R manual")

    assert result["status"] == "index_invalid"
    assert result["results"] == []


@pytest.mark.asyncio
async def test_index_section_tampering_is_rejected(index_path):
    provider, _, _ = await build_index(index_path)
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    raw["sources"]["r-data-import-export"]["sections"][0]["text"] += " altered"
    index_path.write_text(json.dumps(raw), encoding="utf-8")

    result = provider.search("R manual")
    assert result["status"] == "index_invalid"
    assert result["results"] == []


@pytest.mark.asyncio
async def test_external_redirects_are_rejected_and_never_followed(index_path):
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://example.invalid/manual.html"})

    provider, report, _ = await build_index(index_path, redirect)
    assert report["status"] == "unavailable"
    assert len(calls) == 6
    assert all(item["status"] == "unavailable" for item in report["source_results"])
    assert all(item["error_code"] == "unsafe_redirect" for item in report["source_results"])
    unavailable = provider.search("R manual")
    assert unavailable["status"] == "sources_unavailable"
    assert all(item["index_status"] == "unavailable" for item in unavailable["available_sources"])


def test_search_rejects_unknown_manuals_and_non_integer_limits(index_path):
    provider = RDocumentationProvider(index_path=index_path)
    with pytest.raises(KnowledgeError, match="manuals contains"):
        provider.search("R data", ["https://example.invalid"])
    with pytest.raises(KnowledgeError, match="limit must"):
        provider.search("R data", limit=True)
