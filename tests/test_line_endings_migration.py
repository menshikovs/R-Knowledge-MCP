"""CI-004: pinned benchmark files verify on LF and CRLF checkouts; no frozen digest changes."""

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.codex_r import line_endings as le

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "benchmarks/codex_r/knowledge_pilot"


def test_canonical_form_is_lf_and_crlf_round_trips():
    assert le.lf(b"a\r\nb\nc\r\n") == b"a\nb\nc\n"
    assert le.crlf(b"a\nb\r\n") == b"a\r\nb\r\n"
    assert le.lf(b"lone\rcr") == b"lone\rcr"  # only CRLF pairs are normalised
    assert le.sha256(b"x") == hashlib.sha256(b"x").hexdigest()


def test_pin_matches_accepts_only_the_two_digests_of_the_same_content(tmp_path):
    path = tmp_path / "frozen.json"
    path.write_bytes(b'{"a": 1}\n')
    canonical = hashlib.sha256(b'{"a": 1}\n').hexdigest()
    legacy = hashlib.sha256(b'{"a": 1}\r\n').hexdigest()
    assert le.pin_matches(path, canonical) and le.pin_matches(path, legacy)
    # The same pins hold when the file was checked out with CRLF.
    path.write_bytes(b'{"a": 1}\r\n')
    assert le.pin_matches(path, canonical) and le.pin_matches(path, legacy)
    # Any content change is still detected.
    path.write_bytes(b'{"a": 2}\n')
    assert not le.pin_matches(path, canonical) and not le.pin_matches(path, legacy)
    assert not le.pin_matches(path, "0" * 64)


def test_migration_record_is_consistent_with_the_files():
    assert le.verify() == []


def test_migration_record_preserves_the_historical_digests_of_the_e_snapshot():
    """The exact values historical results recorded (CRLF era) stay in the record unchanged."""
    record = json.loads(le.RECORD.read_text(encoding="utf-8"))
    by_path = {entry["path"]: entry for entry in record["entries"]}
    snapshot = by_path["benchmarks/codex_r/knowledge_pilot/metadata/E-source-snapshot.json"]
    manifest = by_path["benchmarks/codex_r/knowledge_pilot/metadata/E-source-snapshot.sha256"]
    # Values recorded as source_snapshot_sha256 / source_checksum_manifest_sha256 by run
    # 20261025T135949Z-9ff06c47.
    assert snapshot["legacy_sha256"] == (
        "6a3046f5d26ed1c0ee63ffedd3244daf6d306e49b7f186efadcea33edcbcc4f0"
    )
    assert manifest["legacy_sha256"] == (
        "2a29319425f70031f494ddf8c72ebeba52bd1db7517eb9efdeed10062b8638f3"
    )
    assert snapshot["canonical_sha256"] != snapshot["legacy_sha256"]
    assert record["baseline_commit"] == "4d2266c994849ac460514ac2ae6df8a6fc5c180e"


def test_frozen_e_source_snapshot_pins_hold_on_any_checkout():
    """Every line of the unmodified legacy manifest verifies; CRLF-pinned files via the record."""
    record = json.loads(le.RECORD.read_text(encoding="utf-8"))
    migrated = {entry["path"] for entry in record["entries"]}
    lines = (PILOT / "metadata/E-source-snapshot.sha256").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 36
    legacy_crlf = 0
    for line in lines:
        sha, relative = line.split("  ", 1)
        path = PILOT / relative
        assert le.pin_matches(path, sha), f"frozen pin no longer matches {relative}"
        if le.canonical_sha256(path) != sha:
            legacy_crlf += 1
            assert path.relative_to(ROOT).as_posix() in migrated, relative
    # Exactly the six files audited as CRLF-pinned (E-source-snapshot.json, E01..E05.json).
    assert legacy_crlf == 6


def test_gitattributes_makes_benchmark_inputs_lf_everywhere():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "benchmarks/** text=auto eol=lf" in attributes
    assert "tests/data/** text=auto eol=lf" in attributes


@pytest.mark.parametrize(
    "relative",
    ["fixtures/E02-counts.csv", "fixtures/E02-samples.csv", "fixtures/E01-renv.lock"],
)
def test_public_fixtures_have_one_canonical_digest(relative):
    path = PILOT / relative
    assert le.canonical_sha256(path) == hashlib.sha256(le.lf(path.read_bytes())).hexdigest()
