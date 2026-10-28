"""Function Discovery on authentic CRAN and Bioconductor source archives (no network).

Synthetic fixtures hid KC-001 and KC-002; these archives are the real thing. Every expectation in
tests/fixtures/archives/MANIFEST.json was cross-checked against R 4.5.2's own parsers
(audits/2026-10-27-r-knowledge-mcp-2.0/stage1-evidence/r_comparison_fixtures.json).
"""

import dataclasses
import hashlib
import time

import pytest
from archive_corpus import DIRECTORY, body, entries, manifest, parsed

from cran_knowledge_mcp import function_discovery as fd
from cran_knowledge_mcp import native as native_module
from cran_knowledge_mcp import visualization_analysis as va

ENTRIES = entries()
IDS = [f"{e['package']}-{e['version']}" for e in ENTRIES]
ALLOWED_URL_PREFIXES = (
    "https://cloud.r-project.org/src/contrib/",
    "https://bioconductor.org/packages/",
)
REQUIRED = {
    "package",
    "version",
    "repository",
    "url",
    "file",
    "bytes",
    "sha256",
    "retrieved_utc",
    "license",
    "reason",
    "expected",
}


def discover(entry):
    metadata, files = parsed(entry)
    return fd.build_discovery_index(entry["package"], metadata, files)


def by_kind(index, kind):
    return [e for e in index.entries if e["kind"] == kind]


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_manifest_provenance_and_digest(entry):
    assert REQUIRED <= set(entry)
    assert entry["url"].startswith(ALLOWED_URL_PREFIXES)
    assert entry["file"] == f"{entry['package']}_{entry['version']}.tar.gz"
    assert entry["license"] and entry["reason"] and entry["retrieved_utc"]
    data = body(entry)
    assert len(data) == entry["bytes"]
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    metadata, _ = parsed(entry)
    assert (metadata["Package"], metadata["Version"]) == (entry["package"], entry["version"])


def test_corpus_covers_the_required_cases_and_stays_small():
    names = {e["package"] for e in ENTRIES}
    assert {"cluster", "R6", "BiocGenerics", "checkglobals", "RBMRB", "TSEtools"} <= names
    assert any(e["repository"].startswith("Bioconductor") for e in ENTRIES)
    assert sum(e["bytes"] for e in ENTRIES) < 3 << 20
    on_disk = {p.name for p in DIRECTORY.glob("*.tar.gz")}
    assert on_disk == {e["file"] for e in ENTRIES}
    assert manifest()["schema_version"] == 1


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_recorded_discovery_expectations(entry):
    expected = entry["expected"]
    index = discover(entry)
    status = "verified" if index.namespace_status == index.rd_status == "verified" else "partial"
    assert status == expected["verification_status"]
    assert index.completeness == expected["completeness"]
    assert {k: len(by_kind(index, k)) for k in ("export", "alias", "topic", "method")} == (
        expected["counts"]
    )
    assert len(index.patterns) == expected["patterns"]
    assert {d["code"]: d["count"] for d in index.diagnostics} == expected["diagnostics"]
    assert list(index.issues) == expected["issues"]


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_partial_means_a_limiting_diagnostic_and_nothing_else(entry):
    index = discover(entry)
    limiting = [d for d in index.diagnostics if d["class"] != "info"]
    partial = "partial" in (index.namespace_status, index.rd_status)
    assert partial == bool(limiting)
    assert (index.completeness in {"incomplete", "unestablished"}) == partial


def test_cluster_mixed_rd_encodings_are_all_discovered():
    """KC-001 on real data: plantTraits.Rd declares latin1, the rest is UTF-8/ASCII."""
    (entry,) = [e for e in ENTRIES if e["package"] == "cluster"]
    index = discover(entry)
    aliases = {e["name"] for e in by_kind(index, "alias")}
    assert {"plantTraits", "agnes", "daisy", "pam"} <= aliases
    assert index.rd_status == "verified" and "rd_encoding_unavailable" not in index.issues
    codes = {d["code"]: d["class"] for d in index.diagnostics}
    assert codes == {"namespace_native_library_declared": "info"}  # useDynLib(.registration=TRUE)


def test_r6_registers_a_method_on_another_packages_generic():
    (entry,) = [e for e in ENTRIES if e["package"] == "R6"]
    methods = by_kind(discover(entry), "method")
    (delayed,) = [m for m in methods if m.get("generic_package")]
    assert (delayed["generic"], delayed["class"], delayed["name"]) == (
        "utils::.DollarNames",
        "R6",
        ".DollarNames.R6",
    )
    assert delayed["generic_package"] == "utils" and delayed["method_kind"] == "S3"


def test_escaped_percent_topic_name_is_literal():
    (entry,) = [e for e in ENTRIES if e["package"] == "einops"]
    index = discover(entry)
    topics = {t["name"]: t for t in by_kind(index, "topic")}
    assert topics["%>%"]["identifier_source"] == "rd_name"
    assert "rd_name_not_literal" not in {d["code"] for d in index.diagnostics}


def test_export_pattern_stays_partial_with_the_unexpandable_pattern_visible():
    (entry,) = [e for e in ENTRIES if e["package"] == "TSEtools"]
    index = discover(entry)
    assert index.completeness == "incomplete" and index.patterns
    page = index.page("TSEtools", None, 50, 0)
    assert page["coverage"]["completeness"] == "incomplete"
    assert page["export_patterns"] and "export_patterns_not_expanded" in page["issues"]
    flagged = [d for d in page["diagnostics"] if d["code"] == "export_patterns_not_expanded"]
    assert flagged[0]["class"] == "incomplete" and flagged[0]["examples"]


def test_conditional_rd_formatting_is_reported_but_does_not_downgrade():
    (entry,) = [e for e in ENTRIES if e["package"] == "RBMRB"]
    index = discover(entry)
    assert index.rd_status == "verified" and index.issues == ()
    (note,) = [d for d in index.diagnostics if d["code"] == "rd_conditional_formatting"]
    assert note["class"] == "info" and note["count"] == 3
    assert 1 <= len(note["examples"]) <= fd.MAX_DIAGNOSTIC_EXAMPLES


def test_bioconductor_s4_package_has_exports_methods_and_shared_topics():
    (entry,) = [e for e in ENTRIES if e["repository"].startswith("Bioconductor")]
    index = discover(entry)
    kinds = {kind for e in by_kind(index, "export") for kind in e["declaration_kinds"]}
    assert kinds == {"export", "exportMethods", "exportClasses"}
    assert any(m["method_kind"] == "S4_export" for m in by_kind(index, "method"))
    # One Rd topic documenting several aliases: the topic lists them, each alias links back.
    multi = [t for t in by_kind(index, "topic") if t["alias_count"] > 1]
    assert multi
    for topic in multi[:5]:
        for name in topic["aliases"]:
            alias = next(a for a in by_kind(index, "alias") if a["name"] == name)
            assert topic["archive_member"] in (
                alias["documentation_topics"]
                if alias["documentation_topics_complete"]
                else [topic["archive_member"]]
            )
    exported_and_documented = [
        e for e in by_kind(index, "export") if e["documentation_topics_count"]
    ]
    assert len(exported_and_documented) > 100
    assert index.completeness == "complete"


def test_large_documentation_set_is_bounded_and_fast():
    (entry,) = [e for e in ENTRIES if e["package"] == "fabletools"]
    started = time.perf_counter()
    index = discover(entry)
    assert time.perf_counter() - started < 10  # measured well below 1 s; generous for CI
    assert len(by_kind(index, "topic")) > 50
    first = index.page("fabletools", None, 50, 0)
    assert len(str(first)) <= fd.PAGE_BYTES * 2
    assert len(first["diagnostics"]) <= fd.MAX_PAGE_DIAGNOSTICS


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_python_and_actual_native_backends_agree_on_real_archives(entry, monkeypatch):
    if native_module.native is None:
        pytest.skip("actual PyO3 module is unavailable; parity not verified")
    monkeypatch.setattr(va, "native", None)
    reference = discover(entry)
    monkeypatch.setattr(va, "native", native_module.native)
    actual = discover(entry)
    assert dataclasses.asdict(actual) == dataclasses.asdict(reference)
    for query in (None, entry["package"], "print", "data"):
        assert actual.page(entry["package"], query, 20, 0) == reference.page(
            entry["package"], query, 20, 0
        )
