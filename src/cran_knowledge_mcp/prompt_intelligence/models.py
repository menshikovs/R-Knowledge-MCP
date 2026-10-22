"""Typed data contracts for the prompt intelligence subsystem."""

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PromptSource:
    package: str | None
    repository: str
    package_version: str | None
    bioconductor_release: str | None
    source_url: str
    checked_at: str | None
    kind: str
    verification_status: str = "verified"


@dataclass(frozen=True)
class PromptSpecification:
    original_request: str
    task_category: str
    target: str
    detail_level: str
    objective: str
    functional_requirements: list[str]
    nonfunctional_requirements: list[str]
    packages: list[dict[str, Any]]
    r_version_context: str | None
    bioconductor_release_context: str | None
    project_context: dict[str, str]
    assumptions: list[str]
    unknowns: list[str]
    implementation_guidance: list[str]
    testing_requirements: list[str]
    acceptance_criteria: list[str]
    security_boundaries: list[str]
    output_expectations: list[str]
    sources: list[PromptSource] = field(default_factory=list)
    function_documentation: list[dict[str, Any]] = field(default_factory=list)
    structured_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromptEnhancementProvider(Protocol):
    """Optional, explicitly injected enhancement provider; no default client exists."""

    async def enhance(self, prompt_text: str, target: str) -> str: ...
