"""Bounded heuristics for rejecting common credential-shaped caller text."""

from __future__ import annotations

import re

SECRET_PATTERNS = (
    re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b"
    ),
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+[^\s,;]{4,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}={0,2}\b"),
    re.compile(
        r"(?i)\b(?:(?:[a-z0-9]+[_-])?(?:x[_-]?api[_-]?key|api[_ -]?key|"
        r"access[_ -]?token|"
        r"refresh[_ -]?token|id[_ -]?token|auth[_ -]?token|token|"
        r"client[_ -]?secret|secret[_ -]?key|secret[_ -]?access[_ -]?key|"
        r"password|credential))"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9][A-Za-z0-9._~+/@=-]{3,}"
    ),
    re.compile(r"(?i)\bhttps?://[^\s/@:]+:[^\s/@]+@[^\s/]+"),
    re.compile(
        r"(?i)[?&](?:api[_-]?key|x[_-]?api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token|token|client[_-]?secret|password|secret)="
        r"[^&#\s]+"
    ),
)


def contains_credential_like_text(value: str) -> bool:
    """Return whether text matches common credential formats.

    This is a conservative heuristic, not a complete secret detector. Callers
    should reject matched input before copying it to prompts or results.
    """
    return isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS)
