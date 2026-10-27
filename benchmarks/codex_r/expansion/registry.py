"""Build and safely export the public part of the R benchmark expansion source set.

This module only reads allow-listed public task specifications and the source
manifest. It never opens private evaluator or answer-key files and never executes
R code from the source documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = "benchmark_expansion_sources"
REGISTRY_PATH = Path("benchmarks/codex_r/expansion/registry-v1.json")
MAPPING_PATH = Path("benchmarks/codex_r/expansion/source-mapping-v1.json")
AUDIT_PATH = Path("benchmarks/codex_r/expansion/audit-v1.json")

# This is deliberately an explicit allowlist. Candidate exports must never read
# private answer keys, evaluator notes, verifier sources, or hidden fixtures.
SOURCE_GROUPS = (
    {
        "suite": "beginner",
        "prefix": "BEGINNER",
        "source": "public/README_TEST.md",
        "expected_count": 20,
        "parser": "numbered",
    },
    {
        "suite": "ggplot",
        "prefix": "GGP",
        "source": "public/ggplot_benchmark_tests.md",
        "expected_count": 41,
        "parser": "heading",
    },
    {
        "suite": "ecosystem",
        "prefix": "ECO",
        "source": "public/r_mcp_benchmark_tasks.md",
        "expected_count": 37,
        "parser": "heading",
    },
    {
        "suite": "ecosystem_addon",
        "prefix": "ADDON",
        "source": "public/r_mcp_benchmark_addon_tasks.md",
        "expected_count": 25,
        "parser": "heading",
    },
    {
        "suite": "anova",
        "prefix": "ANOVA",
        "source": "public/ANOVA_Benchmark_Tasks.md",
        "expected_count": 15,
        "parser": "heading",
    },
    {
        "suite": "hard_blueprint",
        "prefix": "HARD",
        "source": "blueprints/R_Knowledge_MCP_Hard_Benchmark_v1.md",
        "expected_count": 10,
        "parser": "heading",
    },
)
EXPECTED_SOURCE_COUNT = sum(group["expected_count"] for group in SOURCE_GROUPS)
ALLOWED_STATUSES = {"spec_only", "blocked", "mapped_existing"}
TASK_HEADING = re.compile(r"^(#{2,3})\s+([A-Z]+\d{2})\s+[—–-]\s+(.+?)\s*$")
NUMBERED_TASK = re.compile(r"^\s*(\d{1,2})\.\s+\*\*(.+?)\*\*\s*(.*)$")

# These source specs have local hard-v1 counterparts. H04 is intentionally an
# API/package substitution; the mapping does not claim literal implementation.
EXISTING_HARD_MAPPINGS = {
    "H01": {"task_id": "H01", "match": "close", "adaptation": None},
    "H04": {
        "task_id": "H04",
        "match": "semantic_with_package_substitution",
        "adaptation": "Source asks for data.table; local suite uses pinned dplyr rolling joins.",
    },
    "H10": {"task_id": "H10", "match": "close", "adaptation": None},
}
LEGACY_RELATED_SPECS = {
    "R01": ["GGP-P01"],
    "R02": ["ECO-T01"],
    "R03": ["ECO-V03", "ADDON-B02"],
    "R04": ["GGP-R02"],
    "R05": ["GGP-T05"],
    "R06": [],
    "R07": ["HARD-H06"],
    "R08": ["ADDON-B08"],
    "R09": ["ECO-SH03"],
    "R10": ["GGP-K01", "GGP-K03"],
    "R11": [],
    "R12": ["GGP-K03"],
}


class RegistryError(ValueError):
    """Raised when the source inventory or generated catalog is inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Cannot read JSON manifest: {path}") from exc
    if not isinstance(value, dict):
        raise RegistryError(f"Expected a JSON object: {path}")
    return value


def _public_source_path(root: Path, relative_path: str) -> Path:
    """Resolve an allow-listed source path without permitting traversal/private files."""
    rel = PurePosixPath(relative_path)
    if rel.is_absolute() or ".." in rel.parts or rel.parts[0] not in {"public", "blueprints"}:
        raise RegistryError(f"Non-public source path is not allowed: {relative_path}")
    allowed = {group["source"] for group in SOURCE_GROUPS}
    if relative_path not in allowed:
        raise RegistryError(f"Source path is not in the reviewed allowlist: {relative_path}")

    source_root = (root / SOURCE_ROOT).resolve()
    path = (source_root / Path(*rel.parts)).resolve()
    if not path.is_relative_to(source_root) or not path.is_file():
        raise RegistryError(
            f"Public source is missing or outside the source bundle: {relative_path}"
        )
    return path


def _source_hashes(root: Path) -> dict[str, str]:
    """Validate the bundled source manifest and return hashes for public inputs only."""
    manifest_path = root / SOURCE_ROOT / "SOURCE_MANIFEST.json"
    manifest = _read_json(manifest_path)
    if manifest.get("version") != 1 or manifest.get("specification_count") != EXPECTED_SOURCE_COUNT:
        raise RegistryError("Unsupported or inconsistent source manifest")
    if manifest.get("document_count") != 11:
        raise RegistryError("Source manifest document count differs from the supplied bundle")

    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise RegistryError("Source manifest must contain a files array")
    by_path = {entry.get("path"): entry for entry in entries if isinstance(entry, dict)}
    hashes: dict[str, str] = {}
    for group in SOURCE_GROUPS:
        relative_path = group["source"]
        entry = by_path.get(relative_path)
        if not entry or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
            raise RegistryError(f"Missing source hash for {relative_path}")
        content = _public_source_path(root, relative_path).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != entry["sha256"] or len(content) != entry.get("bytes"):
            raise RegistryError(f"Source manifest hash or size mismatch for {relative_path}")
        hashes[relative_path] = digest
    return hashes


def _task_section(lines: list[str], start: int, level: int) -> str:
    end = len(lines)
    for index in range(start + 1, len(lines)):
        heading = re.match(r"^(#{1,6})\s", lines[index])
        if heading and len(heading.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip() + "\n"


def _parse_heading_tasks(text: str, group: dict[str, Any]) -> list[dict[str, Any]]:
    lines = text.splitlines()
    starts: list[tuple[int, int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = TASK_HEADING.match(line)
        if match:
            starts.append((index, len(match.group(1)), match))

    tasks = []
    for index, level, match in starts:
        source_id, title = match.group(2), match.group(3).strip()
        prompt = _task_section(lines, index, level)
        if group["suite"] == "hard_blueprint":
            hidden_marker = re.search(r"(?m)^\*\*Hidden verification:\*\*", prompt)
            if hidden_marker is None:
                raise RegistryError(
                    f"Hard blueprint task lacks a hidden-verification boundary: {source_id}"
                )
            prompt = prompt[: hidden_marker.start()].rstrip() + "\n"
        tasks.append(
            {
                "id": f"{group['prefix']}-{source_id}",
                "source_id": source_id,
                "title": title,
                "candidate_prompt": prompt,
            }
        )
    return tasks


def _parse_numbered_tasks(text: str, group: dict[str, Any]) -> list[dict[str, Any]]:
    lines = text.splitlines()
    starts = [(index, NUMBERED_TASK.match(line)) for index, line in enumerate(lines)]
    starts = [(index, match) for index, match in starts if match]
    tasks = []
    for offset, (index, match) in enumerate(starts):
        end = starts[offset + 1][0] if offset + 1 < len(starts) else len(lines)
        number = int(match.group(1))
        if number != offset + 1:
            raise RegistryError("Beginner task numbers must be contiguous from 1")
        body = "\n".join(lines[index:end]).strip()
        task_id = f"{group['prefix']}-{number:03d}"
        title = match.group(2).strip().rstrip(":")
        prompt = f"### {task_id} — {title}\n\n{body}\n"
        tasks.append(
            {
                "id": task_id,
                "source_id": f"{number:02d}",
                "title": title,
                "candidate_prompt": prompt,
            }
        )
    return tasks


def _hard_mapping(root: Path, source_id: str) -> dict[str, Any] | None:
    mapping = EXISTING_HARD_MAPPINGS.get(source_id)
    if mapping is None:
        return None

    hard_root = root / "benchmarks/codex_r/hard"
    hard_manifest = _read_json(hard_root / "manifest.json")
    local_tasks = {task.get("id"): task for task in hard_manifest.get("tasks", [])}
    task = local_tasks.get(mapping["task_id"])
    if task is None:
        raise RegistryError(f"Expected existing hard-v1 task is missing: {source_id}")
    for relative in (task["spec"], task["metadata"], task["verifier"]):
        path = (hard_root / relative).resolve()
        if not path.is_relative_to(hard_root.resolve()) or not path.is_file():
            raise RegistryError(f"Existing hard-v1 mapping is incomplete: {source_id}")
    return {
        "local_suite": hard_manifest["benchmark"],
        "local_task_id": mapping["task_id"],
        "match": mapping["match"],
        "adaptation": mapping["adaptation"],
        "validation_evidence": "benchmarks/codex_r/hard/README.md",
        "validation_state": "reported_offline_validated_2026-10-24_not_replayed",
    }


def _pilot_environment(root: Path) -> dict[str, Any]:
    """Read pinned versions from the legacy manifest and lock without running R."""
    manifest = _read_json(root / "benchmarks/codex_r/manifest.json")
    lock_relative = manifest.get("environment", {}).get("lockfile")
    if not isinstance(lock_relative, str):
        raise RegistryError("Legacy manifest does not declare a lockfile")
    lock_path = (root / "benchmarks/codex_r" / lock_relative).resolve()
    benchmark_root = (root / "benchmarks/codex_r").resolve()
    if not lock_path.is_relative_to(benchmark_root) or not lock_path.is_file():
        raise RegistryError("Legacy lockfile path is invalid")
    lock = _read_json(lock_path)
    r_version = manifest.get("environment", {}).get("r")
    if lock.get("R", {}).get("Version") != r_version:
        raise RegistryError("Legacy R version does not match its lockfile")
    packages = lock.get("Packages", {})
    ggplot = packages.get("ggplot2", {})
    return {
        "r": r_version,
        "bioconductor": manifest.get("environment", {}).get("bioconductor"),
        "lockfile": str(lock_relative).replace("\\", "/"),
        "ggplot2": ggplot.get("Version") if isinstance(ggplot, dict) else None,
    }


def _legacy_crosswalk(root: Path, expansion_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Index R01-R12 and note thematic leads without claiming deduplication."""
    manifest = _read_json(root / "benchmarks/codex_r/manifest.json")
    tasks = manifest.get("tasks", [])
    legacy = [task for task in tasks if re.fullmatch(r"R\d{2}", str(task.get("id", "")))]
    legacy.sort(key=lambda task: task["id"])
    expected_ids = [f"R{i:02d}" for i in range(1, 13)]
    if [task["id"] for task in legacy] != expected_ids:
        raise RegistryError("Expected the existing R01-R12 pilot inventory")
    expansion_ids = {task["id"] for task in expansion_tasks}
    crosswalk = []
    for task in legacy:
        related = LEGACY_RELATED_SPECS[task["id"]]
        if not set(related) <= expansion_ids:
            raise RegistryError(f"Invalid thematic crosswalk for {task['id']}")
        crosswalk.append(
            {
                "task_id": task["id"],
                "area": task.get("area", ""),
                "spec": task.get("spec", ""),
                "thematic_source_candidates": related,
                "deduplication_status": "not_verified; thematic links are not duplicates",
            }
        )
    return crosswalk


def build_registry(root: Path | str | None = None) -> dict[str, Any]:
    """Parse all 148 public source specs into a versioned, validated registry."""
    repo = Path(root or REPO_ROOT).resolve()
    hashes = _source_hashes(repo)
    pilot_environment = _pilot_environment(repo)
    tasks: list[dict[str, Any]] = []
    suites = []
    for group in SOURCE_GROUPS:
        text = _public_source_path(repo, group["source"]).read_text(encoding="utf-8")
        parser = _parse_numbered_tasks if group["parser"] == "numbered" else _parse_heading_tasks
        parsed = parser(text, group)
        if len(parsed) != group["expected_count"]:
            raise RegistryError(
                f"{group['suite']}: expected {group['expected_count']} specs, found {len(parsed)}"
            )
        suites.append(
            {
                "suite": group["suite"],
                "prefix": group["prefix"],
                "source_document": group["source"],
                "source_sha256": hashes[group["source"]],
                "specification_count": len(parsed),
            }
        )
        for item in parsed:
            mapping = (
                _hard_mapping(repo, item["source_id"])
                if group["suite"] == "hard_blueprint"
                else None
            )
            status = "mapped_existing" if mapping else "spec_only"
            blockers = []
            if not mapping:
                blockers.append(
                    "No expansion-owned fixture, hidden verifier, artifact adapter, "
                    "and offline gate."
                )
            if group["suite"] == "anova":
                blockers.append(
                    "Source marks fixtures and verifiers as proposed; current repo is "
                    "R 4.5.2/Bioconductor 3.22, while some specs require R 4.6/"
                    "Bioconductor 3.23."
                )
            if group["suite"] == "ggplot":
                blockers.append(
                    "Source preparation states its solution examples were not executed; "
                    "the pilot pins ggplot2 4.0.3, while version-specific source tasks "
                    "require 4.0.0; rendering checks are absent."
                )
            task = {
                "id": item["id"],
                "suite": group["suite"],
                "source_id": item["source_id"],
                "title": item["title"],
                "source_document": group["source"],
                "source_sha256": hashes[group["source"]],
                "status": status,
                "validation_state": (mapping["validation_state"] if mapping else "not_validated"),
                "candidate_prompt": item["candidate_prompt"],
                "mapping": mapping,
                "blockers": blockers,
            }
            tasks.append(task)

    registry = {
        "schema_version": 1,
        "registry": "r-agent-benchmark-expansion",
        "registry_version": "1.0.0",
        "source_manifest": f"{SOURCE_ROOT}/SOURCE_MANIFEST.json",
        "source_specification_count": EXPECTED_SOURCE_COUNT,
        "existing_pilot_environment": pilot_environment,
        "known_source_version_gaps": [
            {
                "source_requirement": "R 4.6 with stable Bioconductor 3.23",
                "affected_tasks": ["ADDON-C09"],
                "existing_pilot": (
                    f"R {pilot_environment['r']} with Bioconductor "
                    f"{pilot_environment['bioconductor']}"
                ),
            },
            {
                "source_requirement": "ggplot2 4.0.0",
                "affected_tasks": ["ECO-GP01", "ECO-GP02", "ADDON-C02"],
                "existing_pilot": f"ggplot2 {pilot_environment['ggplot2']}",
            },
        ],
        "legacy_r01_r12_crosswalk": _legacy_crosswalk(repo, tasks),
        "suites": suites,
        "tasks": tasks,
    }
    validate_registry(registry)
    return registry


def validate_registry(registry: dict[str, Any]) -> None:
    """Check catalog identity, provenance, privacy boundary, and task counts."""
    if (
        registry.get("schema_version") != 1
        or registry.get("registry") != "r-agent-benchmark-expansion"
    ):
        raise RegistryError("Unsupported expansion registry")
    if registry.get("source_specification_count") != EXPECTED_SOURCE_COUNT:
        raise RegistryError("Registry source count differs from the reviewed source set")
    tasks = registry.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != EXPECTED_SOURCE_COUNT:
        raise RegistryError("Registry does not contain exactly 148 source task specs")
    seen: set[str] = set()
    for task in tasks:
        task_id = task.get("id")
        source = task.get("source_document", "")
        if not isinstance(task_id, str) or task_id in seen:
            raise RegistryError(f"Missing or duplicate canonical task id: {task_id}")
        seen.add(task_id)
        if source not in {group["source"] for group in SOURCE_GROUPS}:
            raise RegistryError(f"Non-public source in task record: {source}")
        if (
            source.startswith("private/")
            or "evaluator" in source.lower()
            or "solution" in source.lower()
        ):
            raise RegistryError(f"Private source entered registry: {source}")
        if task.get("status") not in ALLOWED_STATUSES:
            raise RegistryError(f"Unsupported task status for {task_id}")
        if task.get("validation_state") not in {
            "not_validated",
            "reported_offline_validated_2026-10-24_not_replayed",
        }:
            raise RegistryError(f"Unsupported validation state for {task_id}")
        if (
            not isinstance(task.get("candidate_prompt"), str)
            or not task["candidate_prompt"].strip()
        ):
            raise RegistryError(f"Missing public prompt for {task_id}")
        if (
            task.get("suite") == "hard_blueprint"
            and "**Hidden verification:**" in task["candidate_prompt"]
        ):
            raise RegistryError(f"Hidden hard-benchmark checks entered prompt: {task_id}")
        if task.get("status") == "mapped_existing" and not task.get("mapping"):
            raise RegistryError(f"Existing task mapping missing for {task_id}")
        if task.get("status") != "mapped_existing" and task.get("mapping") is not None:
            raise RegistryError(f"Unexpected local task mapping for {task_id}")
    legacy = registry.get("legacy_r01_r12_crosswalk")
    if not isinstance(legacy, list) or [item.get("task_id") for item in legacy] != [
        f"R{i:02d}" for i in range(1, 13)
    ]:
        raise RegistryError("Legacy R01-R12 crosswalk is incomplete")


def source_mapping(registry: dict[str, Any]) -> dict[str, Any]:
    """Return the machine-readable source-ID to local-status mapping."""
    validate_registry(registry)
    return {
        "schema_version": 1,
        "mapping_version": "1.0.0",
        "source_specification_count": EXPECTED_SOURCE_COUNT,
        "entries": [
            {
                "id": task["id"],
                "suite": task["suite"],
                "source_id": task["source_id"],
                "source_document": task["source_document"],
                "status": task["status"],
                "local_mapping": task["mapping"],
                "validation_state": task["validation_state"],
                "blockers": task["blockers"],
            }
            for task in registry["tasks"]
        ],
        "legacy_r01_r12": registry["legacy_r01_r12_crosswalk"],
    }


def audit_summary(registry: dict[str, Any]) -> dict[str, Any]:
    """Compute counts without treating source specs as runnable tasks."""
    validate_registry(registry)
    by_suite = {suite["suite"]: suite["specification_count"] for suite in registry["suites"]}
    mapped = sum(task["status"] == "mapped_existing" for task in registry["tasks"])
    spec_only = sum(task["status"] == "spec_only" for task in registry["tasks"])
    return {
        "schema_version": 1,
        "audit_version": "1.0.0",
        "source_specifications_imported": len(registry["tasks"]),
        "specifications_by_suite": by_suite,
        "mapped_to_existing_hard_suite": mapped,
        "pending_spec_only": spec_only,
        "new_r_tasks_implemented_in_this_change": 0,
        "new_r_tasks_offline_validated_in_this_change": 0,
        "existing_legacy_r_tasks": len(registry["legacy_r01_r12_crosswalk"]),
        "existing_hard_tasks_with_recorded_offline_validation_not_replayed": mapped,
        "gross_inventory_if_all_source_specs_are_implemented_plus_legacy_r_tasks": 160,
        "semantic_deduplication_against_r01_r12_complete": False,
        "verified_unique_inventory": None,
        "minimum_additional_unique_tasks_for_240_if_all_inventory_is_distinct": 80,
        "existing_pilot_environment": registry["existing_pilot_environment"],
        "r_execution_allowed_by_repository_instructions": False,
    }


def export_candidate_prompt(
    task_id: str, destination: Path | str, root: Path | str | None = None
) -> dict[str, str]:
    """Export one allow-listed public prompt to a new, isolated directory.

    The destination must be outside the repository and must not already exist.
    Only ``TASK.md`` is written; metadata, solutions, and verifiers are omitted.
    """
    registry = build_registry(root)
    task = next((item for item in registry["tasks"] if item["id"] == task_id), None)
    if task is None:
        raise RegistryError(f"Unknown expansion task id: {task_id}")

    repo = Path(root or REPO_ROOT).resolve()
    output = Path(destination).absolute()
    if output.exists() or output.is_symlink():
        raise RegistryError("Candidate export destination must be new and not a symlink")
    if any(parent.is_symlink() for parent in (output.parent, *output.parent.parents)):
        raise RegistryError("Candidate export path cannot contain symlink parents")
    resolved = output.resolve()
    if resolved.is_relative_to(repo):
        raise RegistryError("Candidate export destination must be outside the repository")

    output.mkdir(parents=True)
    content = task["candidate_prompt"].encode("utf-8")
    prompt_path = output / "TASK.md"
    prompt_path.write_bytes(content)
    return {
        "task_id": task_id,
        "path": str(prompt_path),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def write_registry_files(root: Path | str | None = None) -> dict[str, Any]:
    """Regenerate versioned registry, mapping, and count report in the repository."""
    repo = Path(root or REPO_ROOT).resolve()
    registry = build_registry(repo)
    generated = {
        REGISTRY_PATH: registry,
        MAPPING_PATH: source_mapping(registry),
        AUDIT_PATH: audit_summary(registry),
    }
    for relative, value in generated.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit_summary(registry)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build", help="regenerate registry, mapping, and audit JSON")
    export = subparsers.add_parser(
        "export", help="export one public TASK.md outside the repository"
    )
    export.add_argument("task_id")
    export.add_argument("destination", type=Path)
    args = parser.parse_args()

    if args.command == "build":
        result = write_registry_files()
    else:
        result = export_candidate_prompt(args.task_id, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
