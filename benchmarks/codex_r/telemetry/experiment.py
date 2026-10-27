"""Record the exact experimental configuration of a run (``experiment.json``).

Everything stored is identification only: revisions, digests, versions and identifiers.
No environment variables, credentials or task/user data are read or written.
"""

from __future__ import annotations

import hashlib
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from . import schema

MAX_HASHED_FILE_BYTES = 5 << 20


def _git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, timeout=30, check=False
    )
    return result.stdout if result.returncode == 0 else None


def git_state(repo):
    """Commit, branch and a fingerprint of uncommitted changes (not their names or text).

    ``working_tree_sha256`` hashes every modified, deleted or untracked (non-ignored) file
    by path and content, so two runs with the same fingerprint used identical sources.
    """
    revision = _git(repo, "rev-parse", "HEAD")
    if revision is None:
        return {"revision": None, "dirty": None, "changed_paths": None}
    branch = (_git(repo, "rev-parse", "--abbrev-ref", "HEAD") or b"").decode().strip()
    listed = _git(repo, "ls-files", "-m", "-o", "--exclude-standard", "-z")
    paths = sorted({p for p in (listed or b"").decode("utf-8", "replace").split("\0") if p})
    digest = hashlib.sha256()
    for relative in paths:
        digest.update(relative.encode("utf-8", "replace") + b"\0")
        path = Path(repo) / relative
        if path.is_file() and path.stat().st_size <= MAX_HASHED_FILE_BYTES:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            digest.update(b"absent-or-oversized")
    return {
        "revision": revision.decode().strip(),
        "branch": branch or None,
        "dirty": bool(paths),
        "changed_paths": len(paths),
        "working_tree_sha256": digest.hexdigest() if paths else None,
    }


def tree_sha256(root, suffix=".py"):
    """Digest of the source files the MCP container executes (they are bind-mounted)."""
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob(f"*{suffix}")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(
    *,
    run_id,
    repo,
    configuration,
    toolset,
    allowed_tools,
    registered_tools,
    images,
    scorer_versions,
    model,
    effort,
    instructions,
    modes,
    tasks,
    repetitions,
    timeout_seconds,
    r_version,
    renv_lock,
    package_pins,
):
    """Assemble the configuration record; every value is an identifier, digest or version."""
    repo = Path(repo)
    pyproject = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "configuration_id": configuration,
        "repository": git_state(repo),
        "mcp_server": {
            "package_version": pyproject["project"]["version"],
            "toolset": toolset,
            "registered_tool_count": len(registered_tools),
            "registered_tools": sorted(registered_tools),
            "allowed_tool_count": len(allowed_tools),
            "allowed_tools": sorted(allowed_tools),
            "source_sha256": tree_sha256(repo / "src"),
            "source_note": "bind-mounted into the MCP container; the image supplies only Python",
        },
        "images": dict(images),
        "telemetry_schema_version": schema.SCHEMA_VERSION,
        "scorer_versions": dict(scorer_versions),
        "model": model,
        "effort": effort,
        "instructions": instructions,
        "modes": list(modes),
        "tasks": list(tasks),
        "repetitions": repetitions,
        "timeout_seconds": timeout_seconds,
        "environment": {
            "r_version": r_version,
            "renv_lock_sha256": file_sha256(renv_lock),
            "task_package_pins": dict(package_pins),
        },
    }
