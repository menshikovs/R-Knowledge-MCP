"""Bounded local reads and closed projections; never copy raw agent/event payloads."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
SHA = re.compile(r"(?:sha256:)?[a-f0-9]{40,64}\Z")
SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|"
    r"(?:OPENAI_(?:EXECUTOR_)?API_KEY|CODEX_API_KEY|api_key|password|secret|authorization)"
    r"[\"']?\s*[=:]\s*[\"']?[^\s,;]+|https?://[^/:\s]+:[^/@\s]+@|"
    r"[?&](?:token|api_key|access_token|key)=[^&\s]+",
    re.IGNORECASE,
)
MAX_FILE = 64 << 20
MAX_PREVIEW = 64 << 10


def token(value, default=None):
    return (
        value
        if isinstance(value, str) and ID.fullmatch(value) and not SECRET.search(value)
        else default
    )


def digest(value):
    return value if isinstance(value, str) and SHA.fullmatch(value) else None


def number(value, *, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    return int(value) if integer and value == int(value) else None if integer else value


def boolean(value):
    return value if type(value) is bool else None


def tokens(value):
    return [item for item in value if token(item)] if isinstance(value, list) else None


def error(value):
    if not isinstance(value, dict):
        return None
    required = {key: token(value.get(key)) for key in ("origin", "category", "reason_code")}
    if not all(required.values()):
        return None
    return {
        **required,
        "source_code": token(value.get("source_code")),
        "count": number(value.get("count"), integer=True),
        "severity": value.get("severity")
        if value.get("severity") in {"fatal", "recoverable"}
        else None,
    }


def confined(root, relative):
    """Accept only explicit relative paths without symlinks, even within the root."""
    root = Path(root).resolve()
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("unsafe_relative_path")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink_source")
    if not current.resolve().is_relative_to(root):
        raise ValueError("source_outside_root")
    return current


def read_bytes(root, relative, *, limit=MAX_FILE):
    path = confined(root, relative)
    before = path.stat()
    if not path.is_file() or before.st_size > limit:
        raise ValueError("source_not_regular_or_oversized")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    after = path.stat()
    stamp = (after.st_size, after.st_mtime_ns)
    if len(content) > limit or stamp != (before.st_size, before.st_mtime_ns):
        raise ValueError("source_changed_during_read")
    return content, hashlib.sha256(content).hexdigest(), stamp


def redact_preview(text):
    return SECRET.sub("[REDACTED]", text)


def package_pins(value):
    if not isinstance(value, dict):
        return {}
    return {
        task: {
            package: version
            for package, version in packages.items()
            if isinstance(package, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9.]{0,99}", package)
            and isinstance(version, str)
            and re.fullmatch(r"[0-9]+(?:[.-][0-9A-Za-z]+)*", version)
        }
        for task, packages in value.items()
        if isinstance(task, str)
        and re.fullmatch(r"[A-Z][0-9]{2}", task)
        and isinstance(packages, dict)
    }
