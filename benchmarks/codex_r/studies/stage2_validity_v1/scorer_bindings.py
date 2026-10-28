"""Which executable scorer a catalogue scorer label denotes (versioned, explicit).

The task catalogue labels every knowledge-pilot task ``knowledge-pilot-v2.1``, but that scorer
accepts only D01 and D03 (``knowledge_pilot_v21.SUPPORTED_TASKS``). For the other knowledge-pilot
tasks the only scorer the benchmark runner can execute is the knowledge-pilot ``legacy`` scorer,
which is also the scorer that produced their historical Arm-A screens. Rather than pin the digest
of a module that never runs, each task is bound to the scorer that actually executes, and the
catalogue label is kept alongside with ``label_executable`` so the substitution is visible.

``scorer_version`` values stay inside the preregistered vocabulary (``legacy``, ``hard-v1``,
``knowledge-pilot-v2.1``); the suite disambiguates the two legacy scorers. Scorer files are never
modified here; they are only hashed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from benchmarks.codex_r import knowledge_pilot, knowledge_pilot_v21

from . import manifest

BINDING_VERSION = "stage3a-scorer-binding-v1"
CODEX = manifest.CODEX


@dataclass(frozen=True)
class ScorerBinding:
    task: str
    catalogue_label: str
    scorer_version: str  # what executes; also run_simple's --knowledge-pilot-scorer value
    implementation: str  # human-readable identity of the executed scorer
    files: tuple[Path, ...]
    label_executable: bool
    multidimensional: bool  # canonical result has dimensions and no passed/total

    def digest(self) -> str:
        """SHA-256 over the executed scorer's implementation files (relative path -> digest)."""
        listing = {
            str(p.relative_to(manifest.ROOT)).replace("\\", "/"): manifest.digest(p)
            for p in self.files
        }
        return hashlib.sha256(
            json.dumps(listing, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def to_dict(self) -> dict:
        return {
            "binding_version": BINDING_VERSION,
            "catalogue_label": self.catalogue_label,
            "scorer_version": self.scorer_version,
            "implementation": self.implementation,
            "label_executable": self.label_executable,
            "multidimensional": self.multidimensional,
            "scorer_sha256": self.digest(),
        }


def bind(task: str, catalogue_label: str) -> ScorerBinding:
    if task.startswith("R") and catalogue_label == "legacy":
        return ScorerBinding(
            task,
            catalogue_label,
            "legacy",
            "runner/bench.py (codex-r R verifier in the scorer image)",
            (CODEX / "runner" / "bench.py",),
            True,
            False,
        )
    if task.startswith("H") and catalogue_label == "hard-v1":
        return ScorerBinding(
            task,
            catalogue_label,
            "hard-v1",
            "hard/suite.py (hard R verifier in the scorer image)",
            (CODEX / "hard" / "suite.py", CODEX / "runner" / "bench.py"),
            True,
            False,
        )
    if task in knowledge_pilot.PILOT_TASK_IDS:
        pilot = CODEX / "knowledge_pilot.py"
        v21_supported = task in knowledge_pilot_v21.SUPPORTED_TASKS
        if catalogue_label == "knowledge-pilot-v2.1" and v21_supported:
            return ScorerBinding(
                task,
                catalogue_label,
                "knowledge-pilot-v2.1",
                "knowledge_pilot_v21.py (host JSON scorer with versioned claim evidence)",
                (
                    pilot,
                    CODEX / "knowledge_pilot_v2.py",
                    CODEX / "knowledge_pilot_v21.py",
                    knowledge_pilot_v21.EVIDENCE_PATH,
                ),
                True,
                True,
            )
        if catalogue_label in ("knowledge-pilot-v2.1", "legacy"):
            return ScorerBinding(
                task,
                catalogue_label,
                "legacy",
                "knowledge_pilot.py legacy scorer (R verifier or legacy JSON rules)",
                (pilot, CODEX / "runner" / "bench.py"),
                catalogue_label == "legacy",
                False,
            )
    raise ValueError(f"no executable scorer for task {task!r} with label {catalogue_label!r}")
