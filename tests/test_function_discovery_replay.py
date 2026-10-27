"""Replay tests use synthetic bytes and never claim historical B1 improvements."""

import csv
import hashlib
import json
from pathlib import Path

import pytest
from conftest import archive
from test_function_discovery import CASES, files_for

from benchmarks.codex_r.replay_function_discovery import load_fixtures, render, replay


def digest(body):
    return hashlib.sha256(body).hexdigest()


def write_inventory(path, rows):
    columns = [
        "trial_id",
        "call_number",
        "argument_fingerprint",
        "package",
        "requested_name",
        "repository",
        "requested_package_version",
        "task_reference_version",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def fixture_manifest(tmp_path):
    tarball = archive(files_for(CASES[0]))
    index = (
        "Package: DiscoveryPkg\nVersion: 1.0.0\nMD5sum: "
        + hashlib.md5(tarball, usedforsecurity=False).hexdigest()
        + "\n"
    ).encode()
    (tmp_path / "source.tar.gz").write_bytes(tarball)
    (tmp_path / "PACKAGES").write_bytes(index)
    fixture = {
        "repository": "cran",
        "package": "DiscoveryPkg",
        "package_version": "1.0.0",
        "source_url": "https://cran.r-project.org/src/contrib/DiscoveryPkg_1.0.0.tar.gz",
        "upstream_checked_at": "2026-10-26T00:00:00Z",
        "fixture_kind": "synthetic_test",
        "archive_path": "source.tar.gz",
        "archive_sha256": digest(tarball),
        "index_path": "PACKAGES",
        "index_sha256": digest(index),
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"fixtures": [fixture]}), encoding="utf-8")
    return path


async def test_missing_data_denominators_on_unchanged_real_inventory():
    result = await replay(
        Path("benchmarks/codex_r/reports/p1_docs_not_found_inventory_20261026.csv")
    )
    assert result["total_requests"] == 59 and result["requests_with_identity"] == 42
    assert result["excluded_missing_identity"] == 17
    assert result["excluded_missing_source_fixture"] == 42
    assert result["evaluated_requests"] == 0 and result["historical_metrics"] is None


async def test_synthetic_topic_recovery_compares_existing_alias_hints(tmp_path):
    manifest = fixture_manifest(tmp_path)
    inventory = tmp_path / "inventory.csv"
    write_inventory(
        inventory,
        [
            {
                "trial_id": "synthetic",
                "call_number": "1",
                "argument_fingerprint": "synthetic",
                "package": "DiscoveryPkg",
                "requested_name": "selection",
                "repository": "cran",
                "requested_package_version": "1.0.0",
            }
        ],
    )
    result = await replay(inventory, manifest)
    assert result["evaluated_requests"] == 1 and result["historical_metrics"] is None
    outcome = result["outcomes"][0]
    assert outcome["fixture_kind"] == "synthetic_test"
    assert not outcome["baseline_exact_success"]
    assert outcome["baseline_verified_alias_hints"] == ["choose", "select"]
    assert outcome["new_docs_success"] and outcome["resolution"] == "verified_alias_or_topic"
    assert "not historical" in render(result).lower()


async def test_fuzzy_alone_does_not_count_as_retrieval(tmp_path):
    manifest = fixture_manifest(tmp_path)
    inventory = tmp_path / "inventory.csv"
    write_inventory(
        inventory,
        [
            {
                "trial_id": "synthetic",
                "call_number": "1",
                "argument_fingerprint": "fuzzy",
                "package": "DiscoveryPkg",
                "requested_name": "choos",
                "repository": "cran",
                "requested_package_version": "1.0.0",
            }
        ],
    )
    outcome = (await replay(inventory, manifest))["outcomes"][0]
    assert outcome["fuzzy_suggestions"] > 0 and not outcome["new_docs_success"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("archive_sha256", "0" * 64),
        ("source_url", "https://evil.invalid/pkg.tar.gz"),
        ("package_version", "9.0"),
        ("fixture_kind", "claimed_verified"),
    ],
)
def test_manifest_verifies_body_identity_and_fixed_sources(tmp_path, field, value):
    path = fixture_manifest(tmp_path)
    data = json.loads(path.read_text())
    data["fixtures"][0][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_fixtures(path)


def test_fixture_manifest_count_and_aggregate_memory_are_bounded(tmp_path, monkeypatch):
    from benchmarks.codex_r import replay_function_discovery as module

    manifest = fixture_manifest(tmp_path)
    monkeypatch.setattr(module, "MAX_REPLAY_FIXTURES", 0)
    with pytest.raises(ValueError, match="Too many"):
        load_fixtures(manifest)
    monkeypatch.setattr(module, "MAX_REPLAY_FIXTURES", 16)
    monkeypatch.setattr(module, "MAX_REPLAY_BYTES", 1)
    with pytest.raises(ValueError, match="128 MiB"):
        load_fixtures(manifest)
