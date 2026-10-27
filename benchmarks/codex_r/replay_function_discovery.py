"""Deterministic offline discovery replay. No live transport or model is available here."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import httpx

from cran_knowledge_mcp.http import INDEX, CranHTTP, package_name, version_parts
from cran_knowledge_mcp.parsers import dcf, decode
from cran_knowledge_mcp.service import KnowledgeService

ROOT = Path(__file__).resolve().parent
DEFAULT_INVENTORY = ROOT / "reports/p1_docs_not_found_inventory_20261026.csv"
MAX_REPLAY_FIXTURES = 16
MAX_REPLAY_BYTES = 128 << 20


def _read_verified(path: Path, digest: str, limit: int) -> bytes:
    if path.stat().st_size > limit:
        raise ValueError("Offline fixture exceeds its byte limit")
    with path.open("rb") as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Offline fixture exceeds its byte limit")
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("Offline fixture SHA256 mismatch")
    return body


def load_fixtures(manifest_path: Path | None) -> dict:
    if manifest_path is None:
        return {}
    if manifest_path.stat().st_size > 1 << 20:
        raise ValueError("Fixture manifest exceeds 1 MiB")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(manifest["fixtures"]) > MAX_REPLAY_FIXTURES:
        raise ValueError("Too many offline source fixtures")
    fixtures = {}
    total_bytes = 0
    for item in manifest["fixtures"]:
        if item["repository"] != "cran":
            raise ValueError("Historical B1 replay currently accepts CRAN fixtures only")
        package_name(item["package"])
        version_parts(item["package_version"])
        base = manifest_path.parent
        archive_url = (
            "https://cran.r-project.org/src/contrib/"
            f"{item['package']}_{item['package_version']}.tar.gz"
        )
        if item["source_url"] != archive_url:
            raise ValueError("Fixture URL must be the fixed official versioned archive route")
        captured = datetime.fromisoformat(item["upstream_checked_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError("Fixture upstream_checked_at must include UTC offset")
        if item["fixture_kind"] not in {"real_pinned_source", "synthetic_test"}:
            raise ValueError("Fixture kind must explicitly identify real versus synthetic data")
        tarball = _read_verified(base / item["archive_path"], item["archive_sha256"], 25 << 20)
        index = _read_verified(base / item["index_path"], item["index_sha256"], 16 << 20)
        total_bytes += len(tarball) + len(index)
        if total_bytes > MAX_REPLAY_BYTES:
            raise ValueError("Offline source fixture set exceeds 128 MiB")
        records = [r for r in dcf(decode(index)) if r.get("Package") == item["package"]]
        if len(records) != 1 or records[0].get("Version") != item["package_version"]:
            raise ValueError("Pinned PACKAGES record does not match fixture identity")
        key = (item["repository"], item["package"], item["package_version"])
        if key in fixtures:
            raise ValueError("Duplicate fixture identity")
        fixtures[key] = {**item, "archive_body": tarball, "index_body": index}
    return fixtures


async def evaluate_request(row: dict, fixture: dict) -> dict:
    archive_route = fixture["source_url"].removeprefix("https://cran.r-project.org")
    routes = {INDEX: fixture["index_body"], archive_route: fixture["archive_body"]}

    def handler(request):
        body = routes.get(request.url.path)
        return httpx.Response(404 if body is None else 200, content=body or b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = KnowledgeService(CranHTTP(client))
        package, name = row["package"], row["requested_name"]
        baseline = await service.get_versioned_function_docs(
            package, name, package_version=fixture["package_version"]
        )
        discovery = await service.list_package_functions(
            package, package_version=fixture["package_version"], query=name, limit=50
        )
        if "error" in discovery:
            return {
                "status": "source_error",
                "error_code": discovery["error"]["code"],
                "baseline_error": baseline.get("error", {}).get("code"),
            }
        # Baseline already had verified alias hints; retain them in the comparison.
        old_error = baseline.get("error", {})
        baseline_hints = old_error.get("available_aliases", old_error.get("closest_aliases", []))
        alias_by_id = {entry["id"]: entry for entry in discovery["aliases"]}
        topic_by_id = {entry["id"]: entry for entry in discovery["documentation_topics"]}
        candidates = []
        for match in discovery["matches"]:
            if match["match_type"] == "fuzzy":
                continue
            if match["kind"] == "alias":
                entry = alias_by_id[match["id"]]
                if entry["documentation_topics_count"] == 1:
                    candidates.append((entry["name"], entry["documentation_topics"][0]))
            elif match["kind"] == "topic":
                entry = topic_by_id[match["id"]]
                if entry["aliases"]:
                    candidates.append((entry["aliases"][0], entry["archive_member"]))
        targets = {topic for _, topic in candidates}
        new_docs = baseline
        resolution = "literal"
        if "error" in baseline and len(targets) == 1:
            alias, topic = sorted(candidates)[0]
            candidate_docs = await service.get_versioned_function_docs(
                package, alias, package_version=fixture["package_version"]
            )
            if "error" not in candidate_docs and candidate_docs["archive_member"] == topic:
                new_docs, resolution = candidate_docs, "verified_alias_or_topic"
        return {
            "status": "evaluated",
            "fixture_kind": fixture["fixture_kind"],
            "archive_sha256": fixture["archive_sha256"],
            "fixture_upstream_checked_at": fixture["upstream_checked_at"],
            "verification_mode": "offline_fixture_not_live_upstream",
            "baseline_exact_success": "error" not in baseline,
            "baseline_error": old_error.get("code"),
            "baseline_verified_alias_hints": baseline_hints,
            "new_docs_success": "error" not in new_docs,
            "resolution": resolution if "error" not in new_docs else None,
            "verified_export_discovery": any(
                m["kind"] == "export" and m["match_type"] == "exact" for m in discovery["matches"]
            ),
            "verified_alias_discovery": any(
                m["kind"] == "alias" and m["match_type"] in {"alias", "normalized"}
                for m in discovery["matches"]
            ),
            "fuzzy_suggestions": sum(m["match_type"] == "fuzzy" for m in discovery["matches"]),
            "unresolved": "error" in new_docs,
            # Runtime intent and export truth need separate fixture/oracle assertions in tests.
            "false_verified_assertions": None,
        }


async def replay(inventory: Path, fixture_manifest: Path | None = None) -> dict:
    if inventory.stat().st_size > 2 << 20:
        raise ValueError("Replay inventory exceeds 2 MiB")
    with inventory.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) > 1000:
        raise ValueError("Replay inventory exceeds 1000 requests")
    fixtures = load_fixtures(fixture_manifest)
    outcomes = []
    for row in rows:
        safe = {
            key: row.get(key, "")
            for key in (
                "trial_id",
                "call_number",
                "argument_fingerprint",
                "package",
                "requested_name",
            )
        }
        if not row.get("package") or not row.get("requested_name"):
            outcomes.append({**safe, "status": "excluded_missing_identity"})
            continue
        version = row.get("requested_package_version") or row.get("task_reference_version")
        basis = "requested" if row.get("requested_package_version") else "task_reference"
        fixture = fixtures.get((row.get("repository", "cran"), row["package"], version))
        if fixture is None:
            outcomes.append(
                {
                    **safe,
                    "status": "excluded_missing_source_fixture",
                    "package_version": version,
                    "version_basis": basis,
                }
            )
            continue
        evaluated = await evaluate_request(row, fixture)
        outcomes.append({**safe, **evaluated, "package_version": version, "version_basis": basis})
    evaluated = [r for r in outcomes if r["status"] == "evaluated"]
    real = [r for r in evaluated if r["fixture_kind"] == "real_pinned_source"]
    return {
        "schema_version": 1,
        "run_id": "20261026T104750Z-f78eabf1",
        "historical_files_modified": False,
        "model_calls": 0,
        "network_requests": 0,
        "total_requests": len(rows),
        "requests_with_identity": sum(
            bool(r.get("package") and r.get("requested_name")) for r in rows
        ),
        "evaluated_requests": len(evaluated),
        "real_source_requests_evaluated": len(real),
        "excluded_missing_identity": sum(
            r["status"] == "excluded_missing_identity" for r in outcomes
        ),
        "excluded_missing_source_fixture": sum(
            r["status"] == "excluded_missing_source_fixture" for r in outcomes
        ),
        "source_fixtures_available": len(fixtures),
        "source_errors": sum(r["status"] == "source_error" for r in outcomes),
        "version_mismatches": sum(
            r.get("error_code") in {"version_mismatch", "requested_version_unavailable"}
            for r in outcomes
        ),
        "false_verified_assertions": None,
        "historical_metrics": {
            "baseline_exact_success": sum(r["baseline_exact_success"] for r in real),
            "new_docs_success": sum(r["new_docs_success"] for r in real),
            "verified_exports": sum(r["verified_export_discovery"] for r in real),
            "verified_aliases": sum(r["verified_alias_discovery"] for r in real),
            "fuzzy_suggestions": sum(r["fuzzy_suggestions"] for r in real),
            "unresolved": sum(r["unresolved"] for r in real),
        }
        if real
        else None,
        "limitations": [
            "A fuzzy suggestion alone is never counted as prevented docs_not_found.",
            "Baseline already returned verified available_aliases/closest_aliases.",
            "Task reference scope does not reconstruct B1 resolved source version.",
            "Synthetic fixture measurements are not historical B1 improvements.",
            "No agent behavior or final answer improvement is measured by retrieval replay.",
        ],
        "outcomes": outcomes,
    }


def render(report: dict) -> str:
    return "\n".join(
        [
            "# P1-B offline function discovery replay",
            "",
            f"Run: {report['run_id']}",
            "",
            f"- Requests: {report['total_requests']}",
            f"- Preserved identities: {report['requests_with_identity']}",
            f"- Evaluated: {report['evaluated_requests']}",
            f"- Source fixtures available: {report['source_fixtures_available']}",
            f"- Excluded missing identity: {report['excluded_missing_identity']}",
            f"- Excluded missing archive: {report['excluded_missing_source_fixture']}",
            "",
            "Historical improvement is unmeasured while historical_metrics is null.",
            "Replay compares literal docs plus existing hints against proactive",
            "discovery and exact alias/topic retrieval. Fuzzy output is never a docs success.",
            "No historical files, task prompts, scorer or B1 descriptions were changed.",
            "",
            "## Reproduce",
            "",
            "Set PYTHONPATH=src and run:",
            "python -m benchmarks.codex_r.replay_function_discovery",
            "Supply --fixture-manifest PATH when verified local archives are available.",
            "",
            "Manifest fixtures require repository, package, package_version, source_url,",
            "upstream_checked_at, fixture_kind (real_pinned_source/synthetic_test),",
            "archive_path/archive_sha256 and index_path/index_sha256. Paths are operator-local;",
            "only the fixed CRAN archive URL is accepted. Both bodies are digest-checked,",
            "then the actual provider verifies index/DESCRIPTION/checksum through MockTransport.",
            "No automatic download or live fallback exists.",
            "",
            *["- " + note for note in report["limitations"]],
            "",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--fixture-manifest", type=Path)
    parser.add_argument(
        "--output-prefix", type=Path, default=ROOT / "reports/p1b_function_discovery_replay"
    )
    args = parser.parse_args()
    report = asyncio.run(replay(args.inventory, args.fixture_manifest))
    args.output_prefix.with_suffix(".json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.output_prefix.with_suffix(".md").write_text(render(report), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "outcomes"}))


if __name__ == "__main__":
    main()
