"""Canonical byte semantics for pinned benchmark files and the line-ending migration record.

Frozen benchmark inputs are pinned by SHA-256. Historical runs hashed the files exactly as they
were checked out on the author's Windows tree, where 116 tracked text files were CRLF although git
stores them as LF. A hash over platform-dependent bytes cannot be verified on Linux, so the
canonical form is now **LF**: ``.gitattributes`` makes every checkout LF, and
:func:`canonical_sha256` hashes the LF-normalised content however the file was checked out.

Nothing historical is rewritten. ``LINE_ENDING_MIGRATION-v1.json`` records, per affected file, the
legacy digest (CRLF bytes, as recorded in historical results) next to the canonical digest, so
both remain verifiable from the same content.

Verify with ``python -m benchmarks.codex_r.line_endings --verify``. ``--write`` needs a checkout
whose affected files are still CRLF and refuses to overwrite an existing record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORD = Path(__file__).with_name("LINE_ENDING_MIGRATION-v1.json")
SCOPES = ("benchmarks", "tests/data")
BASELINE_COMMIT = "4d2266c994849ac460514ac2ae6df8a6fc5c180e"


def lf(data: bytes) -> bytes:
    """Canonical content: CRLF → LF (lone CRs are left untouched)."""
    return data.replace(b"\r\n", b"\n")


def crlf(data: bytes) -> bytes:
    """The legacy Windows form of canonical content."""
    return lf(data).replace(b"\n", b"\r\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(path: Path) -> str:
    return sha256(lf(Path(path).read_bytes()))


def legacy_crlf_sha256(path: Path) -> str:
    return sha256(crlf(Path(path).read_bytes()))


def pin_matches(path: Path, pinned: str) -> bool:
    """True if ``pinned`` is the canonical (LF) or the legacy (CRLF) digest of the file's content.

    Both forms hash the same content; accepting exactly these two digests keeps the pin as strict as
    before while making it independent of the checkout's line endings.
    """
    return pinned in {canonical_sha256(path), legacy_crlf_sha256(path)}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", *SCOPES],
        capture_output=True,
        check=True,
    ).stdout
    return sorted(item.decode() for item in out.split(b"\0") if item)


def _baseline_bytes(relative: str) -> bytes:
    """The stored (LF) blob at the baseline commit, immune to later working-tree edits."""
    return subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{BASELINE_COMMIT}:{relative}"],
        capture_output=True,
        check=True,
    ).stdout


def build_record() -> dict:
    entries = []
    for relative in _tracked_files():
        working = (ROOT / relative).read_bytes()
        if b"\r\n" not in working:
            continue
        baseline = _baseline_bytes(relative)
        if b"\0" in baseline:
            continue
        entries.append(
            {
                "path": relative,
                "legacy_line_endings": "crlf" if working == crlf(working) else "mixed",
                "legacy_sha256": sha256(crlf(baseline)),
                "canonical_sha256": sha256(lf(baseline)),
                # Source code under active development: the digests describe the baseline commit
                # only and are not re-checked against later edits.
                "mutable": relative.endswith(".py"),
            }
        )
    return {
        "schema_version": 1,
        "purpose": (
            "Versioned migration of pinned benchmark file digests from platform-dependent (CRLF) "
            "bytes to canonical LF bytes. Historical results and frozen pins are unchanged."
        ),
        "canonical_form": "LF (CRLF normalised to LF before hashing; .gitattributes enforces LF)",
        "baseline_commit": BASELINE_COMMIT,
        "legacy_digest_origin": (
            "SHA-256 of the file bytes as checked out on the author's Windows working tree when "
            "historical benchmark runs were executed (CRLF)"
        ),
        "entries": entries,
    }


def verify(record_path: Path = RECORD) -> list[str]:
    """Return a list of problems; empty means every recorded digest is consistent with the files."""
    record = json.loads(record_path.read_text(encoding="utf-8"))
    problems = []
    for entry in record["entries"]:
        path = ROOT / entry["path"]
        if not path.is_file():
            problems.append(f"missing: {entry['path']}")
            continue
        if entry.get("mutable"):
            continue  # active source code: digests describe the baseline commit only
        if canonical_sha256(path) != entry["canonical_sha256"]:
            problems.append(f"canonical digest mismatch: {entry['path']}")
        if (
            entry["legacy_line_endings"] == "crlf"
            and legacy_crlf_sha256(path) != (entry["legacy_sha256"])
        ):
            problems.append(f"legacy digest mismatch: {entry['path']}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        if RECORD.exists():
            print(f"{RECORD.name} already exists; refusing to overwrite a frozen record")
            return 1
        record = build_record()
        RECORD.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {len(record['entries'])} entries")
        return 0
    problems = verify()
    print("\n".join(problems) if problems else "line-ending migration record verified")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
