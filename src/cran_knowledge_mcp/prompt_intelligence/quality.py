"""Transparent structural prompt checks; scores are heuristics, never success odds."""

import re

SECRET_PATTERNS = (
    re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b"
    ),
    re.compile(r"(?im)\b(?:api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]\s*\S+"),
)
NAMESPACE_CALL = re.compile(r"\b([A-Za-z][A-Za-z0-9.]*)::([A-Za-z.][A-Za-z0-9._]*)\s*\(")
VERSION_ASSERTION = re.compile(
    r"\b(?:latest|current|compatible|supported)\s+(?:package\s+)?version\b", re.I
)
INSTRUCTION_OVERRIDE = re.compile(
    r"(?i)(ignore (?:all |the )?(?:previous|prior|system|developer) instructions|"
    r"override (?:the )?(?:system|developer|safety)|bypass (?:approval|safety)|"
    r"disable (?:all )?security|reveal (?:the )?(?:secret|token|credential)|"
    r"exfiltrat|upload (?:the )?(?:secret|token|credential)|send (?:the )?(?:secret|token|credential))"  # noqa: E501  # Long user-facing copy or regex.
)


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I | re.M) is not None


def validate_prompt(
    prompt_text: str, verified_functions: set[tuple[str, str]] | None = None
) -> dict:
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        return {
            "score": 0,
            "rubric": "Heuristic structural checklist; not a probability of task success.",
            "findings": [
                {
                    "severity": "high",
                    "code": "empty_prompt",
                    "message": "Provide non-empty prompt text.",
                }
            ],
            "dimensions": {},
            "character_count": 0,
        }
    length = len(prompt_text)
    verified_functions = verified_functions or set()
    findings: list[dict[str, str]] = []
    dimensions: dict[str, dict[str, object]] = {}

    checks = [
        (
            "objective",
            15,
            _has(
                r"(^|\n)#+\s*(objective|goal|цель)|\b(build|create|fix|analy[sz]e|refactor|implement|review)\b",
                prompt_text,
            ),
            "A clear objective is present.",
            "State one concrete objective.",
        ),
        (
            "deliverables",
            10,
            _has(
                r"deliverable|output expectation|expected delivery|files changed|артефакт|результат",  # noqa: E501  # Long user-facing copy or regex.
                prompt_text,
            ),
            "Expected outputs are named.",
            "Name the artifacts or outputs the assistant should deliver.",
        ),
        (
            "technical_context",
            10,
            _has(
                r"project context|package|r version|bioconductor|контекст проекта|пакет",
                prompt_text,
            ),
            "Technical context is present.",
            "Add only relevant R, package or project context.",
        ),
        (
            "constraints",
            10,
            _has(r"constraint|preserve|must not|do not|ограничен|сохраните|не разреш", prompt_text),
            "Constraints or preservation rules are stated.",
            "State constraints and prohibited actions explicitly.",
        ),
        (
            "versions",
            10,
            _has(r"version|release|верс(ия|ии)|релиз", prompt_text),
            "Version context or its unknown status is addressed.",
            "State pinned versions or ask for them; do not guess.",
        ),
        (
            "testing",
            15,
            _has(r"test(ing|s)?|validation|проверк|тест", prompt_text),
            "Testing or verification is addressed.",
            "Specify behavior-focused tests and checks.",
        ),
        (
            "acceptance",
            15,
            _has(
                r"acceptance|done when|success criteria|критерии приёмки|условия завершения",
                prompt_text,
            ),
            "Acceptance criteria are present.",
            "Add observable acceptance criteria.",
        ),
        (
            "safety_reproducibility",
            15,
            _has(
                r"security|approval|authorization|reproduc|secret|безопасност|подтвержден|воспроизвод",
                prompt_text,
            ),
            "Safety or reproducibility boundaries are present.",
            "State relevant security, approval and reproducibility boundaries.",
        ),
    ]
    score = 0
    for name, points, passed, _good, remedy in checks:
        dimensions[name] = {"passed": bool(passed), "weight": points}
        if passed:
            score += points
        else:
            severity = "high" if name in {"objective", "constraints"} else "medium"
            findings.append({"severity": severity, "code": f"missing_{name}", "message": remedy})

    contradictions = []
    pairs = (
        (
            r"\b(?:do not|don't|must not)\s+(?:write|generate)\s+code\b",
            r"\b(?:write|generate)\s+code\b",
        ),
        (r"\b(?:do not|don't|must not)\s+run tests\b", r"\b(?:run|execute)\s+(?:the\s+)?tests\b"),
        (
            r"\b(?:offline|no network)\b",
            r"\b(?:download|fetch|call|use)\s+(?:the\s+)?(?:api|url|internet)\b",
        ),
        (r"\b(?:do not|don't|must not)\s+deploy\b", r"\bdeploy\s+(?:the|this|to)\b"),
    )
    for negative, positive in pairs:
        if _has(negative, prompt_text) and _has(positive, prompt_text):
            contradictions.append("potential_conflicting_instructions")
            break
    for code in contradictions:
        findings.append(
            {
                "severity": "high",
                "code": code,
                "message": "Review instructions that appear to require and prohibit the same action.",  # noqa: E501  # Long user-facing copy or regex.
            }
        )

    if any(pattern.search(prompt_text) for pattern in SECRET_PATTERNS):
        findings.append(
            {
                "severity": "high",
                "code": "possible_secret",
                "message": "Potential credential-like text is present. Redact it before sharing this prompt with any remote service.",  # noqa: E501  # Long user-facing copy or regex.
            }
        )
    if INSTRUCTION_OVERRIDE.search(prompt_text):
        findings.append(
            {
                "severity": "high",
                "code": "instruction_override_attempt",
                "message": "Prompt contains text that attempts to override safety or approval boundaries. Review it as untrusted input.",  # noqa: E501  # Long user-facing copy or regex.
            }
        )
    unverified = [
        (pkg, function)
        for pkg, function in NAMESPACE_CALL.findall(prompt_text)
        if (pkg.casefold(), function) not in {(p.casefold(), f) for p, f in verified_functions}
    ]
    if unverified:
        names = ", ".join(f"{pkg}::{function}()" for pkg, function in unverified[:5])
        findings.append(
            {
                "severity": "medium",
                "code": "unverified_api_claim",
                "message": f"Function references were not checked against retrieved Rd documentation: {names}.",  # noqa: E501  # Long user-facing copy or regex.
            }
        )
    if VERSION_ASSERTION.search(prompt_text) and not _has(
        r"unknown|not verified|not supplied|не подтверж|не задан|неизвест", prompt_text
    ):
        findings.append(
            {
                "severity": "medium",
                "code": "unverified_version_claim",
                "message": "A current/compatible version claim appears without an explicit verification caveat.",  # noqa: E501  # Long user-facing copy or regex.
            }
        )
    if length > 16000:
        findings.append(
            {
                "severity": "medium",
                "code": "long_prompt",
                "message": "Prompt exceeds 16,000 characters; remove nonessential context while preserving requirements.",  # noqa: E501  # Long user-facing copy or regex.
            }
        )
        score = max(0, score - 5)
    elif length < 120:
        findings.append(
            {
                "severity": "low",
                "code": "very_short_prompt",
                "message": "Prompt may not provide enough context to guide implementation.",
            }
        )
        score = max(0, score - 5)
    return {
        "score": score,
        "rubric": "Heuristic structural checklist (100 points maximum); this is not a probability or guarantee of task success.",  # noqa: E501  # Long user-facing copy or regex.
        "findings": findings,
        "dimensions": dimensions,
        "character_count": length,
    }
