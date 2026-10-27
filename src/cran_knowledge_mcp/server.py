"""Official SDK FastMCP adapter and CLI (stdio by default)."""

import argparse
import json
import logging
import math
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, ValidationError

from .config import function_discovery_enabled, mcp_toolset, prompt_intelligence_enabled
from .diagnostics import log_internal_failure, safe_operation_id
from .errors import KnowledgeError
from .http import FETCH_STATS, CranHTTP, make_client
from .mcp_discovery import MCP_DISCOVERY_ENV, server_description
from .prompt_intelligence import PromptIntelligence
from .prompt_intelligence.native_prompts import register_native_prompts
from .providers.framework_docs import DOCS as FRAMEWORK_DOCS
from .providers.r_documentation import ManualId
from .service import KnowledgeService, bounded, failure
from .telemetry import (
    RepeatTracker,
    discovery_signals,
    result_signals,
    safe_protocol_call_id,
    utc_timestamp,
)
from .telemetry import error_codes as _telemetry_error_codes


def _is_failed_envelope(result: Any) -> bool:
    """Classify only the application's explicit top-level failure envelope."""
    if not isinstance(result, dict) or result.get("verification_status") != "failed":
        return False
    error = result.get("error")
    if (
        isinstance(error, dict)
        and isinstance(error.get("code"), str)
        and isinstance(error.get("message"), str)
    ):
        return True
    # Repository aggregation keeps provider errors in `errors` and has no usable results.
    return isinstance(result.get("errors"), list) and not result.get("results")


def _safe_error_context(arguments: dict[str, Any]) -> dict[str, str | None]:
    package = arguments.get("package")
    repository = arguments.get("repository")
    bioc_version = arguments.get("bioc_version")
    return {
        "package": package
        if isinstance(package, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9.]{0,99}", package)
        else None,
        "repository": repository
        if isinstance(repository, str) and repository in {"cran", "bioconductor", "all"}
        else None,
        "bioc_version": bioc_version
        if isinstance(bioc_version, str)
        and re.fullmatch(r"(?:[0-9]+\.[0-9]+|release|devel)", bioc_version)
        else None,
    }


class ErrorAwareFastMCP(FastMCP):
    """FastMCP adapter that retains application error envelopes in tool results."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._telemetry_call_number = 0
        self._telemetry_origin = time.perf_counter_ns()
        self._telemetry_repeats = RepeatTracker()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        # Name only, never arguments: lets operators audit which tools were called.
        logger = logging.getLogger(__name__)
        tool_name = safe_operation_id(name)
        self._telemetry_call_number += 1
        call_number = self._telemetry_call_number
        started = time.perf_counter_ns()
        request_bytes = _telemetry_size({"name": tool_name, "arguments": arguments})
        fingerprint, repeat_kind, repeat_count = self._telemetry_repeats.begin(tool_name, arguments)
        fetch_stats: dict[str, int] = {}
        fetch_token = FETCH_STATS.set(fetch_stats)
        signals: dict[str, Any] = {}
        response_bytes = None
        status = "error"
        error_code = None
        error_codes: list[str] = []
        error_type = None
        truncated = False
        result = None
        protocol_call_id = None
        try:
            logger.info("Tool call: %s", tool_name)
            context = self.get_context()
            protocol_call_id = _telemetry_protocol_call_id(context)
            try:
                converted = await self._tool_manager.call_tool(
                    name, arguments, context=context, convert_result=True
                )
                result = self._normalize_result(converted)
            except UrlElicitationRequiredError as exc:
                error_code = "url_elicitation_required"
                error_type = safe_operation_id(type(exc).__name__)
                raise
            except Exception as exc:
                cause = exc.__cause__
                if isinstance(cause, ValidationError) and cause.title.endswith("Arguments"):
                    code, message = "invalid_input", "Tool arguments failed validation"
                elif isinstance(exc, ToolError) and str(exc).startswith("Unknown tool:"):
                    code, message = "tool_not_found", "The requested tool is not available"
                else:
                    log_internal_failure(logger, f"mcp_tool.{tool_name}", cause or exc)
                    code, message = (
                        "internal_error",
                        "The tool could not complete due to an internal error",
                    )
                envelope = failure(KnowledgeError(code, message), **_safe_error_context(arguments))
                result = self._result(envelope, is_error=True)
                error_code = code
                error_type = safe_operation_id(type(cause or exc).__name__)

            response_bytes = _telemetry_result_size(result)
            status = "error" if result.isError else "ok"
            # Section errors of a successful (partial) result are kept too; only a failed
            # call reports the single error_code.
            error_codes = _telemetry_error_codes(result.structuredContent)
            if status == "error" and error_code is None and error_codes:
                error_code = error_codes[0]
            truncated = _telemetry_truncated(result)
            signals = result_signals(arguments, result)
            return result
        finally:
            FETCH_STATS.reset(fetch_token)
            self._telemetry_repeats.finish(fingerprint, status == "error")
            elapsed_ms = max(0.0, (time.perf_counter_ns() - started) / 1_000_000)
            event = {
                "run_id": _telemetry_identifier(os.environ.get("RKMCP_BENCH_RUN_ID")),
                "trial_id": _telemetry_identifier(os.environ.get("RKMCP_BENCH_TRIAL_ID")),
                "tool_name": tool_name,
                "protocol_call_id": protocol_call_id,
                "call_number": call_number,
                "status": status,
                "request_bytes": request_bytes,
                "response_bytes": response_bytes,
                "response_tokens_estimate": (
                    math.ceil(response_bytes / 4) if response_bytes is not None else None
                ),
                "response_token_estimate_method": "ceil(UTF-8 result JSON bytes / 4)",
                "duration_ms": round(elapsed_ms, 3),
                "error_code": error_code,
                "error_codes": error_codes,
                "error_type": error_type,
                "truncated": truncated,
                "argument_fingerprint": fingerprint,
                "repeat_count": repeat_count,
                "repeat_kind": repeat_kind,
                "timestamp_utc": utc_timestamp(),
                "process_offset_ms": round(
                    (time.perf_counter_ns() - self._telemetry_origin) / 1_000_000, 3
                ),
                "cache_hits": fetch_stats.get("hit", 0),
                "cache_network_requests": fetch_stats.get("network", 0),
                "result_bytes": response_bytes,
                **signals,
            }
            if (
                event["run_id"] != "unknown"
                and event["trial_id"] != "unknown"
                and result is not None
            ):
                event.update(discovery_signals(tool_name, arguments, result))
            diagnostic_alias = _diagnostic_function_alias(tool_name, arguments)
            if diagnostic_alias is not None:
                event["diagnostic_function_alias"] = diagnostic_alias
            logger.info(
                "RKMCP_BENCH_TELEMETRY %s",
                json.dumps(event, ensure_ascii=True, separators=(",", ":")),
            )

    @staticmethod
    def _normalize_result(converted: Any) -> CallToolResult:
        if isinstance(converted, CallToolResult):
            return converted
        if isinstance(converted, tuple) and len(converted) == 2:
            content, structured = converted
        elif isinstance(converted, dict):
            structured = converted
            content = [
                TextContent(
                    type="text",
                    text=json.dumps(converted, ensure_ascii=False, separators=(",", ":")),
                )
            ]
        else:
            return CallToolResult(content=list(converted), isError=False)
        return CallToolResult(
            content=list(content),
            structuredContent=structured,
            isError=_is_failed_envelope(structured),
        )

    @staticmethod
    def _result(envelope: dict[str, Any], *, is_error: bool) -> CallToolResult:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
                )
            ],
            structuredContent=envelope,
            isError=is_error,
        )


_TELEMETRY_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_TELEMETRY_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _telemetry_identifier(value: str | None) -> str:
    return value if isinstance(value, str) and _TELEMETRY_IDENTIFIER.fullmatch(value) else "unknown"


def _telemetry_protocol_call_id(context: Context) -> str | None:
    try:
        value = context.request_id
    except Exception:
        return None
    return safe_protocol_call_id(value)


def _telemetry_size(value: Any) -> int | None:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None


def _telemetry_result_size(result: CallToolResult) -> int | None:
    try:
        payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None
    return _telemetry_size(payload)


_DIAGNOSTIC_ALIAS_ENV = "RKMCP_DIAGNOSTIC_FUNCTION_ALIASES"
_DIAGNOSTIC_ALIAS_LENGTH = 64


def _diagnostic_function_alias(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Opt-in local debugging aid: a sanitized, truncated get_function_docs alias.

    Off unless RKMCP_DIAGNOSTIC_FUNCTION_ALIASES=1. Control and non-ASCII characters
    become '?', so a name cannot forge extra log lines.
    """
    if os.environ.get(_DIAGNOSTIC_ALIAS_ENV) != "1" or tool_name != "get_function_docs":
        return None
    alias = arguments.get("function")
    if not isinstance(alias, str):
        return None
    return re.sub(r"[^!-~]", "?", alias[:_DIAGNOSTIC_ALIAS_LENGTH])


def _telemetry_truncated(value: Any) -> bool:
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="python", by_alias=True, exclude_none=True)
        except (TypeError, ValueError):
            return False
    if isinstance(value, dict):
        if value.get("truncated") is True:
            return True
        return any(_telemetry_truncated(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_telemetry_truncated(item) for item in value)
    return False


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    allowed_hosts: list[str] | None = None,
    service: KnowledgeService | None = None,
    toolset: Literal["consolidated", "legacy"] | None = None,
    mcp_discovery_variant: Literal["control", "treatment"] | None = None,
) -> FastMCP:
    toolset = toolset or mcp_toolset()
    if mcp_discovery_variant is None:
        mcp_discovery_variant = os.environ.get(MCP_DISCOVERY_ENV)
    instructions = server_description(mcp_discovery_variant)

    @asynccontextmanager
    async def lifespan(server):
        if service is not None:
            yield service
            return
        async with make_client() as client:
            yield KnowledgeService(CranHTTP(client))

    server = ErrorAwareFastMCP(
        "R Knowledge MCP",
        lifespan=lifespan,
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        instructions=instructions,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts
            or ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"],
            # A same-origin request to an explicitly allowed Host is not a rebinding
            # attempt; cross-origin browser requests are still rejected.
            allowed_origins=["http://localhost:*", "http://127.0.0.1:*"]
            + [f"http://{host}" for host in allowed_hosts or [] if "*" not in host],
        ),
    )
    if toolset == "legacy":
        _register_legacy_tools(server)
    else:
        _register_tools(server)
    _register_resources(server)
    if prompt_intelligence_enabled():
        register_native_prompts(server)
    return server


def _register_legacy_tools(server: FastMCP) -> None:
    """Original 35-tool surface, kept unchanged for benchmark comparability (MCP_TOOLSET=legacy)."""
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)

    if prompt_intelligence_enabled():

        @server.tool(annotations=annotations)
        async def build_r_prompt(
            request: str,
            ctx: Context,
            target: Literal["codex", "chatgpt", "generic"] | None = None,
            detail_level: Literal["concise", "standard", "comprehensive"] | None = None,
            task_category: str | None = None,
            packages: list[str] | None = None,
            r_version: str | None = None,
            bioconductor_release: str | None = None,
            project_context: dict[str, str] | None = None,
            constraints: list[str] | None = None,
            include_sources: bool = True,
            enhancement_mode: Literal["deterministic", "auto", "external"] = "deterministic",
            language: str = "auto",
            structured_context: dict[str, Any] | None = None,
            composition_mode: Literal["auto", "single", "composed"] = "auto",
            templates: list[str] | None = None,
            workflow_context: dict[str, Any] | None = None,
            include_plan: bool = True,
            include_provenance: bool = True,
        ) -> dict[str, Any]:
            """Build one editable R prompt; compose detected workflow stages without executing them."""  # noqa: E501
            intelligence = PromptIntelligence(ctx.request_context.lifespan_context)
            return await bounded(
                intelligence.build_r_prompt(
                    request,
                    target,
                    detail_level,
                    task_category,
                    packages,
                    r_version,
                    bioconductor_release,
                    project_context,
                    constraints,
                    include_sources,
                    enhancement_mode,
                    language,
                    structured_context,
                    composition_mode,
                    templates,
                    workflow_context,
                    include_plan,
                    include_provenance,
                ),
                repository="prompt_intelligence",
                bioc_version=bioconductor_release,
            )

        @server.tool(annotations=annotations)
        async def improve_r_prompt(
            existing_prompt: str,
            ctx: Context,
            improvement_goals: list[str] | None = None,
            target: Literal["codex", "chatgpt", "generic"] | None = None,
            detail_level: Literal["concise", "standard", "comprehensive"] | None = None,
            packages: list[str] | None = None,
            r_version: str | None = None,
            bioconductor_release: str | None = None,
            project_context: dict[str, str] | None = None,
            enhancement_mode: Literal["deterministic", "auto", "external"] = "deterministic",
            structured_context: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Structure an existing prompt while retaining its complete original text and constraints."""  # noqa: E501  # Long user-facing copy or regex.
            intelligence = PromptIntelligence(ctx.request_context.lifespan_context)
            return await bounded(
                intelligence.improve_r_prompt(
                    existing_prompt,
                    improvement_goals,
                    target,
                    detail_level,
                    packages,
                    r_version,
                    bioconductor_release,
                    project_context,
                    enhancement_mode,
                    structured_context,
                ),
                repository="prompt_intelligence",
                bioc_version=bioconductor_release,
            )

        @server.tool(annotations=annotations)
        async def validate_r_prompt(prompt_text: str) -> dict[str, Any]:
            """Check prompt structure, conflicts, possible secrets and unverified API claims."""

            async def operation():
                return PromptIntelligence(None).validate_r_prompt(prompt_text)

            return await bounded(operation(), repository="prompt_intelligence")

        @server.tool(annotations=annotations)
        async def list_r_prompt_templates() -> dict[str, Any]:
            """List stable built-in R prompt template identifiers and descriptions."""
            return PromptIntelligence(None).list_r_prompt_templates()

        @server.tool(annotations=annotations)
        async def get_r_prompt_context(
            packages: list[str],
            ctx: Context,
            r_version: str | None = None,
            bioconductor_release: str | None = None,
        ) -> dict[str, Any]:
            """Resolve selected R package versions, direct dependencies and source provenance."""
            intelligence = PromptIntelligence(ctx.request_context.lifespan_context)
            return await bounded(
                intelligence.get_r_prompt_context(packages, r_version, bioconductor_release),
                repository="prompt_intelligence",
                bioc_version=bioconductor_release,
            )

    @server.tool(annotations=annotations)
    async def search_packages(
        query: str,
        ctx: Context,
        limit: int = 10,
        offset: int = 0,
        repository: Literal["cran", "bioconductor", "all"] = "cran",
        bioc_version: str | None = None,
    ) -> dict[str, Any]:
        """Search repository names and available title keywords; repository defaults to cran."""
        return await bounded(
            ctx.request_context.lifespan_context.search_packages(
                query, limit, offset, repository, bioc_version
            ),
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def search_r_documentation(
        query: str,
        ctx: Context,
        manuals: list[ManualId] | None = None,
        limit: int = 5,
        r_version: str | None = None,
    ) -> dict[str, Any]:
        """Search the local index of six official CRAN R manuals; this tool never fetches pages."""
        return await bounded(
            ctx.request_context.lifespan_context.search_r_documentation(
                query, manuals, limit, r_version
            ),
            repository="r_documentation",
        )

    @server.tool(annotations=annotations)
    async def get_r_documentation_section(
        document_id: ManualId,
        section_id: str,
        ctx: Context,
        max_chars: int = 8000,
    ) -> dict[str, Any]:
        """Retrieve one exact section from the local official R manual index."""
        return await bounded(
            ctx.request_context.lifespan_context.get_r_documentation_section(
                document_id, section_id, max_chars
            ),
            repository="r_documentation",
        )

    @server.tool(annotations=annotations)
    async def get_package_info(
        package: str,
        ctx: Context,
        repository: Literal["cran", "bioconductor", "all"] = "cran",
        bioc_version: str | None = None,
        verify_archive: bool = True,
    ) -> dict[str, Any]:
        """Get metadata with index/DESCRIPTION lookup or deep archive verification."""
        return await bounded(
            ctx.request_context.lifespan_context.get_package_info(
                package, repository, bioc_version, verify_archive
            ),
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def get_dependencies(
        package: str,
        ctx: Context,
        repository: Literal["cran", "bioconductor", "all"] = "cran",
        bioc_version: str | None = None,
        resolve_repositories: bool = False,
    ) -> dict[str, Any]:
        """Get direct dependency fields; Bioconductor also resolves CRAN/Bioconductor origins."""
        return await bounded(
            ctx.request_context.lifespan_context.get_dependencies(
                package, repository, bioc_version, resolve_repositories
            ),
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def get_function_docs(
        package: str,
        function: str,
        ctx: Context,
        offset: int = 0,
        repository: Literal["cran", "bioconductor", "all"] = "cran",
        bioc_version: str | None = None,
    ) -> dict[str, Any]:
        """Get raw Rd by literal alias from the selected repository and release source archive."""
        return await bounded(
            ctx.request_context.lifespan_context.get_function_docs(
                package, function, offset, repository, bioc_version
            ),
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def check_package_version(
        package: str, installed_version: str, ctx: Context
    ) -> dict[str, Any]:
        """Compare a client-supplied R package version to CRAN; never claims local verification."""
        return await bounded(
            ctx.request_context.lifespan_context.check_package_version(package, installed_version),
            package=package,
            repository="cran",
        )

    @server.tool(annotations=annotations)
    async def get_bioconductor_version(r_version: str, ctx: Context) -> dict[str, Any]:
        """Map R to official Bioconductor releases; never recommend devel implicitly."""
        return await bounded(
            ctx.request_context.lifespan_context.get_bioconductor_version(r_version),
            repository="bioconductor",
        )

    @server.tool(annotations=annotations)
    async def check_package_compatibility(
        package: str, r_version: str, ctx: Context, bioc_version: str | None = None
    ) -> dict[str, Any]:
        """Check R/release and direct required dependency constraints; installation is untested."""
        return await bounded(
            ctx.request_context.lifespan_context.check_package_compatibility(
                package, r_version, bioc_version
            ),
            package=package,
            repository="bioconductor",
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def get_package_vignettes(
        package: str,
        ctx: Context,
        repository: Literal["cran", "bioconductor", "all"] = "cran",
        bioc_version: str | None = None,
    ) -> dict[str, Any]:
        """List vignette links from the version-checked official page; never execute content."""
        return await bounded(
            ctx.request_context.lifespan_context.get_package_vignettes(
                package, repository, bioc_version
            ),
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def get_package_agent_guidance(
        package: str,
        revision: str,
        ctx: Context,
        repository: Literal["cran", "bioconductor"] = "cran",
        bioc_version: str | None = None,
    ) -> dict[str, Any]:
        """Read AGENTS.md at a metadata-verified GitHub ref; never execute it."""
        return await bounded(
            ctx.request_context.lifespan_context.get_package_agent_guidance(
                package, revision, repository, bioc_version
            ),
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def get_context7_docs(
        package: str,
        question: str,
        ctx: Context,
        repository: Literal["cran", "bioconductor"] = "cran",
        bioc_version: str | None = None,
    ) -> dict[str, Any]:
        """Fetch Context7 docs after matching its ID to verified package metadata."""
        return await bounded(
            ctx.request_context.lifespan_context.get_context7_docs(
                package, question, repository, bioc_version
            ),
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def get_package_knowledge(
        package: str,
        ctx: Context,
        repository: Literal["cran", "bioconductor"] = "cran",
        bioc_version: str | None = None,
        question: str | None = None,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """Combine package metadata with requested AGENTS.md and Context7 material."""
        return await bounded(
            ctx.request_context.lifespan_context.get_package_knowledge(
                package, repository, bioc_version, question, revision
            ),
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def get_shiny_docs(
        package: str, function: str, ctx: Context, package_version: str | None = None
    ) -> dict[str, Any]:
        """Get genuine Rd for a Shiny function from a CRAN source archive."""
        return await bounded(
            ctx.request_context.lifespan_context.get_shiny_docs(package, function, package_version),
            package=package,
            repository="cran",
        )

    @server.tool(annotations=annotations)
    async def explain_shiny_reactivity(
        topic: Literal["reactivity", "isolation", "modules", "async", "basics"],
        question: str,
        ctx: Context,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Explain a Shiny topic with official docs and optional static source checks."""
        return await bounded(
            ctx.request_context.lifespan_context.explain_shiny_reactivity(topic, question, source),
            repository="shiny",
        )

    @server.tool(annotations=annotations)
    async def analyze_shiny_app(
        ctx: Context,
        source: str | None = None,
        files: dict[str, str] | None = None,
        shiny_version: str | None = None,
    ) -> dict[str, Any]:
        """Run bounded heuristic checks on supplied Shiny source; never executes it."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_shiny_app(source, files, shiny_version),
            repository="shiny",
        )

    @server.tool(annotations=annotations)
    async def get_positron_guidance(
        topic: Literal["interpreters", "r_installation", "startup", "extensions", "mcp"],
        ctx: Context,
        positron_version: str | None = None,
        operating_system: str | None = None,
        r_version: str | None = None,
        project_type: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve official Positron guidance; this does not control the IDE or an R session."""
        return await bounded(
            ctx.request_context.lifespan_context.get_positron_guidance(
                topic, positron_version, operating_system, r_version, project_type
            ),
            repository="positron",
        )

    @server.tool(annotations=annotations)
    async def analyze_r_workspace(files: dict[str, str], ctx: Context) -> dict[str, Any]:
        """Analyze supplied project text; never reads paths or exposes .Renviron values."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_r_workspace(files),
            repository="r_workspace",
        )

    @server.tool(annotations=annotations)
    async def get_quarto_docs(
        topic: Literal["r", "projects", "profiles", "citations", "rendering"],
        ctx: Context,
        quarto_version: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve a page from the fixed catalog of official Quarto documentation."""
        return await bounded(
            ctx.request_context.lifespan_context.get_quarto_docs(topic, quarto_version),
            repository="quarto",
        )

    @server.tool(annotations=annotations)
    async def analyze_quarto_document(
        source: str,
        ctx: Context,
        project_config: str | None = None,
        quarto_version: str | None = None,
        r_version: str | None = None,
        dependencies: list[str] | None = None,
    ) -> dict[str, Any]:
        """Safely parse QMD YAML and fenced R chunk options without rendering or executing code."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_quarto_document(
                source, project_config, quarto_version, r_version, dependencies
            ),
            repository="quarto_document",
        )

    @server.tool(annotations=annotations)
    async def analyze_quarto_project(
        project_config: str,
        ctx: Context,
        metadata_config: str | None = None,
        file_manifest: list[str] | None = None,
    ) -> dict[str, Any]:
        """Analyze supplied Quarto YAML and a path-only manifest; no server filesystem access."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_quarto_project(
                project_config, metadata_config, file_manifest
            ),
            repository="quarto_project",
        )

    @server.tool(annotations=annotations)
    async def get_r_workflow_guidance(
        scenario: Literal[
            "shiny_bioconductor", "quarto_positron", "quarto_bioconductor", "analysis_to_shiny"
        ],
        ctx: Context,
        packages: list[dict[str, str]] | None = None,
        r_version: str | None = None,
        bioc_version: str | None = None,
    ) -> dict[str, Any]:
        """Combine official framework docs with knowledge for explicitly named packages."""
        return await bounded(
            ctx.request_context.lifespan_context.get_r_workflow_guidance(
                scenario, packages, r_version, bioc_version
            ),
            repository="r_workflow",
            bioc_version=bioc_version,
        )

    @server.tool(annotations=annotations)
    async def recommend_technology_stack(
        objective: str,
        ctx: Context,
        project_type: Literal["analytics", "api", "dashboard", "package", "etl", "ml", "other"]
        | None = None,
        requirements: list[str] | None = None,
        existing_stack: list[str] | None = None,
        deployment_target: Literal["local", "docker", "cloud", "on_premises"] | None = None,
        preferences: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """Recommend a provisional R project architecture with current package provenance."""
        return await bounded(
            ctx.request_context.lifespan_context.recommend_technology_stack(
                objective,
                project_type,
                requirements,
                existing_stack,
                deployment_target,
                preferences,
            ),
            repository="technology_stack",
        )

    @server.tool(annotations=annotations)
    async def get_visualization_docs(
        package: Literal["ggplot2", "ggraph", "tidyr", "plotly", "knitr"],
        function: str,
        ctx: Context,
        package_version: str | None = None,
    ) -> dict[str, Any]:
        """Get exact current CRAN Rd by alias; historical versions are not substituted."""
        return await bounded(
            ctx.request_context.lifespan_context.get_visualization_docs(
                package, function, package_version
            ),
            package=package,
            repository="cran",
        )

    @server.tool(annotations=annotations)
    async def get_visualization_workflow(
        scenario: Literal["tidy_to_plot", "graph_plot", "interactive_plot", "reproducible_report"],
        ctx: Context,
        package_versions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Group current official function references; no code is generated or run."""
        return await bounded(
            ctx.request_context.lifespan_context.get_visualization_workflow(
                scenario, package_versions
            ),
            repository="cran",
        )

    @server.tool(annotations=annotations)
    async def analyze_ggplot_code(
        source: str,
        ctx: Context,
        data_schema: dict[str, Any] | None = None,
        package_versions: dict[str, str] | None = None,
        renv_lock: str | None = None,
    ) -> dict[str, Any]:
        """Statically inspect ggplot calls and optional schemas; R source is never run."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_ggplot_code(
                source, data_schema, package_versions, renv_lock
            ),
            repository="cran",
        )

    @server.tool(annotations=annotations)
    async def analyze_ggraph_code(
        source: str,
        ctx: Context,
        node_schema: dict[str, Any] | None = None,
        edge_schema: dict[str, Any] | None = None,
        package_versions: dict[str, str] | None = None,
        renv_lock: str | None = None,
    ) -> dict[str, Any]:
        """Statically inspect ggraph calls, separate node/edge mappings, and optional schemas."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_ggraph_code(
                source, node_schema, edge_schema, package_versions, renv_lock
            ),
            repository="cran",
        )

    @server.tool(annotations=annotations)
    async def analyze_tidyr_pipeline(
        source: str,
        ctx: Context,
        input_schema: dict[str, Any] | None = None,
        expected_schema: dict[str, Any] | None = None,
        package_versions: dict[str, str] | None = None,
        renv_lock: str | None = None,
    ) -> dict[str, Any]:
        """Statically inspect tidyr operations; data-dependent results are not inferred."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_tidyr_pipeline(
                source, input_schema, expected_schema, package_versions, renv_lock
            ),
            repository="cran",
        )

    @server.tool(annotations=annotations)
    async def analyze_ggplotly_compatibility(
        source: str,
        ctx: Context,
        package_versions: dict[str, str] | None = None,
        renv_lock: str | None = None,
    ) -> dict[str, Any]:
        """Find documented ggplotly caveats; full compatibility is not claimed."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_ggplotly_compatibility(
                source, package_versions, renv_lock
            ),
            repository="cran",
        )

    @server.tool(annotations=annotations)
    async def analyze_knitr_chunks(
        source: str,
        ctx: Context,
        document_type: Literal["rmd", "qmd"] | None = None,
        package_versions: dict[str, str] | None = None,
        renv_lock: str | None = None,
    ) -> dict[str, Any]:
        """Inspect knitr and Quarto chunk options statically; never render or execute chunks."""
        return await bounded(
            ctx.request_context.lifespan_context.analyze_knitr_chunks(
                source, document_type, package_versions, renv_lock
            ),
            repository="cran",
        )


PackageName = Annotated[
    str, Field(description="Exact R package name as published, e.g. 'ggplot2' (case-sensitive).")
]
Repository = Annotated[
    Literal["cran", "bioconductor", "all"],
    Field(
        description=(
            "Repository to query. 'all' queries CRAN and Bioconductor separately and keeps "
            "each result's identity."
        )
    ),
]
SingleRepository = Annotated[
    Literal["cran", "bioconductor"], Field(description="Repository that publishes the package.")
]
BiocVersion = Annotated[
    str | None,
    Field(
        description=(
            "Bioconductor release: 'release', 'devel' or a number such as '3.20'. Defaults to "
            "the current release; only valid when Bioconductor is queried."
        )
    ),
]
RVersion = Annotated[
    str, Field(description="R version as major.minor[.patch], e.g. '4.4' or '4.4.1'.")
]
OptionalRVersion = Annotated[
    str | None, Field(description="R version as major.minor[.patch], e.g. '4.4' or '4.4.1'.")
]
PackageVersions = Annotated[
    dict[str, str] | None,
    Field(
        description=(
            "Client-supplied installed versions to compare with current CRAN, e.g. "
            "{'ggplot2': '3.5.1'}. Never treated as verified."
        )
    ),
]
RenvLock = Annotated[
    str | None,
    Field(description="Raw renv.lock JSON text (max 512 KiB); versions stay client-supplied."),
]
Verbosity = Annotated[
    Literal["compact", "full"],
    Field(
        description=(
            "'compact' omits repeated static notes (limitations, verification_notes) and merges "
            "nested source lists into one top-level 'sources'; 'full' returns everything."
        )
    ),
]
FrameworkTopic = Literal[
    "reactivity",
    "isolation",
    "modules",
    "async",
    "basics",
    "interpreters",
    "r_installation",
    "startup",
    "extensions",
    "mcp",
    "r",
    "projects",
    "profiles",
    "citations",
    "rendering",
]
WorkflowScenario = Literal[
    "shiny_bioconductor",
    "quarto_positron",
    "quarto_bioconductor",
    "analysis_to_shiny",
    "tidy_to_plot",
    "graph_plot",
    "interactive_plot",
    "reproducible_report",
]


def _annotations(title: str, *, open_world: bool = True) -> ToolAnnotations:
    # Every tool is read-only. Per the MCP spec, destructiveHint and idempotentHint only
    # carry meaning when readOnlyHint is false, so they are not set.
    return ToolAnnotations(title=title, readOnlyHint=True, openWorldHint=open_world)


def _service(ctx: Context) -> KnowledgeService:
    return ctx.request_context.lifespan_context


def _register_tools(server: FastMCP) -> None:
    """Consolidated 16-tool surface (default, MCP_TOOLSET=consolidated)."""

    @server.tool(annotations=_annotations("Search R packages"))
    async def search_packages(
        query: Annotated[
            str,
            Field(description="1..200 chars; every whitespace-separated term must match."),
        ],
        ctx: Context,
        limit: Annotated[int, Field(description="Results per page, 1..20.")] = 10,
        offset: Annotated[int, Field(description="Pagination offset from next_offset.")] = 0,
        repository: Repository = "cran",
        bioc_version: BiocVersion = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Search package names and titles in CRAN and/or Bioconductor."""
        return await bounded(
            _service(ctx).search_packages(query, limit, offset, repository, bioc_version),
            compact=verbosity == "compact",
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=_annotations("Get R package knowledge"))
    async def get_package(
        package: PackageName,
        ctx: Context,
        include: Annotated[
            list[Literal["metadata", "dependencies", "vignettes", "agent_guidance", "context7"]]
            | None,
            Field(
                description=(
                    "Sections to return (default ['metadata']). dependencies: verbatim direct "
                    "DESCRIPTION fields; vignettes: links from the official page; "
                    "agent_guidance: AGENTS.md at a GitHub ref (needs revision); context7: "
                    "third-party indexed docs (needs question)."
                )
            ),
        ] = None,
        repository: Repository = "cran",
        bioc_version: BiocVersion = None,
        verify_archive: Annotated[
            bool,
            Field(
                description=(
                    "metadata only: download the source archive and verify its checksum "
                    "(slow). Default reads the version-matched DESCRIPTION/index record."
                )
            ),
        ] = False,
        resolve_repositories: Annotated[
            bool,
            Field(description="dependencies only: resolve each dependency's repository origin."),
        ] = False,
        revision: Annotated[
            str | None,
            Field(description="agent_guidance only: GitHub branch, tag or commit ref."),
        ] = None,
        question: Annotated[
            str | None,
            Field(description="context7 only: concrete question, max 500 chars; secrets redacted."),
        ] = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Get package metadata and optional dependencies, vignettes, AGENTS.md, Context7 docs."""
        return await bounded(
            _service(ctx).get_package(
                package,
                repository,
                bioc_version,
                include,
                verify_archive,
                resolve_repositories,
                revision,
                question,
            ),
            compact=verbosity == "compact",
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=_annotations("Get R function documentation"))
    async def get_function_docs(
        package: PackageName,
        function: Annotated[
            str,
            Field(description="Literal Rd alias, usually the function name, e.g. 'geom_point'."),
        ],
        ctx: Context,
        offset: Annotated[
            int, Field(description="Character offset for paging; use next_offset.")
        ] = 0,
        repository: Repository = "cran",
        bioc_version: BiocVersion = None,
        package_version: Annotated[
            str | None,
            Field(
                description=(
                    "Expected package version. If it differs from the current repository "
                    "version, the call fails instead of substituting other documentation."
                )
            ),
        ] = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Get raw Rd for one alias from the verified current source archive (8000 chars/page)."""
        return await bounded(
            _service(ctx).get_versioned_function_docs(
                package, function, offset, repository, bioc_version, package_version
            ),
            compact=verbosity == "compact",
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    if function_discovery_enabled():

        @server.tool(annotations=_annotations("Discover verified package API names"))
        async def list_package_functions(
            package: PackageName,
            ctx: Context,
            repository: SingleRepository = "cran",
            bioc_version: BiocVersion = None,
            package_version: Annotated[
                str | None,
                Field(description="Exact selected repository version; history is not substituted."),
            ] = None,
            query: Annotated[
                str | None, Field(description="Optional name/topic query, 1..200 characters.")
            ] = None,
            limit: Annotated[
                int, Field(description="Maximum entity entries per page, 1..50.")
            ] = 20,
            offset: Annotated[int, Field(description="Shared entity offset; use next_offset.")] = 0,
            snapshot: Annotated[
                str | None,
                Field(description="Returned snapshot token; required for continuation pages."),
            ] = None,
            verbosity: Verbosity = "compact",
        ) -> dict[str, Any]:
            """Discover names when the precise function is unknown, before guessing docs lookups.
            Inspect static exports, documented aliases, topics and methods from a verified package
            source archive. Arrays project one paginated entity stream. Export declarations and Rd
            aliases are distinct; fuzzy matches do not prove runtime callability. Use
            get_function_docs with a returned literal alias for detailed documentation.
            """
            return await bounded(
                _service(ctx).list_package_functions(
                    package,
                    repository,
                    bioc_version,
                    package_version,
                    query,
                    limit,
                    offset,
                    snapshot,
                ),
                compact=verbosity == "compact",
                package=package,
                repository=repository,
                bioc_version=bioc_version,
            )

    @server.tool(annotations=_annotations("Compare installed version with CRAN"))
    async def check_package_version(
        package: PackageName,
        installed_version: Annotated[
            str, Field(description="Client-supplied installed version, e.g. '1.2-3'.")
        ],
        ctx: Context,
    ) -> dict[str, Any]:
        """Compare a client-supplied version with the latest CRAN version; nothing is inspected."""
        return await bounded(
            _service(ctx).check_package_version(package, installed_version),
            package=package,
            repository="cran",
        )

    @server.tool(annotations=_annotations("Check R compatibility"))
    async def check_r_compatibility(
        r_version: RVersion,
        ctx: Context,
        package: Annotated[
            str | None,
            Field(
                description=(
                    "Package to check. Omit with repository='bioconductor' to map R to "
                    "Bioconductor releases only."
                )
            ),
        ] = None,
        repository: Annotated[
            Literal["cran", "bioconductor"], Field(description="Repository of the package.")
        ] = "cran",
        bioc_version: BiocVersion = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Check R and direct dependency constraints in metadata; installation is never tested."""
        return await bounded(
            _service(ctx).check_r_compatibility(r_version, package, repository, bioc_version),
            compact=verbosity == "compact",
            package=package,
            repository=repository,
            bioc_version=bioc_version,
        )

    @server.tool(annotations=_annotations("Search official R manuals", open_world=False))
    async def search_r_documentation(
        query: Annotated[str, Field(description="Keywords, 1..500 chars.")],
        ctx: Context,
        manuals: Annotated[
            list[ManualId] | None, Field(description="Restrict to these manuals; default all six.")
        ] = None,
        limit: Annotated[int, Field(description="Results, 1..10.")] = 5,
        r_version: OptionalRVersion = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Search the local index of six official R manuals; never fetches pages."""
        return await bounded(
            _service(ctx).search_r_documentation(query, manuals, limit, r_version),
            compact=verbosity == "compact",
            repository="r_documentation",
        )

    @server.tool(annotations=_annotations("Read an R manual section", open_world=False))
    async def get_r_documentation_section(
        document_id: Annotated[ManualId, Field(description="document_id from search results.")],
        section_id: Annotated[str, Field(description="section_id from search results.")],
        ctx: Context,
        max_chars: Annotated[int, Field(description="Characters to return, 1..32000.")] = 8000,
    ) -> dict[str, Any]:
        """Read one exact section from the local official R manual index."""
        return await bounded(
            _service(ctx).get_r_documentation_section(document_id, section_id, max_chars),
            repository="r_documentation",
        )

    @server.tool(annotations=_annotations("Get Shiny, Positron or Quarto docs"))
    async def get_framework_docs(
        framework: Annotated[
            Literal["shiny", "positron", "quarto"], Field(description="Documentation set.")
        ],
        topic: Annotated[
            FrameworkTopic,
            Field(
                description=(
                    "shiny: reactivity, isolation, modules, async, basics; positron: "
                    "interpreters, r_installation, startup, extensions, mcp; quarto: r, "
                    "projects, profiles, citations, rendering."
                )
            ),
        ],
        ctx: Context,
        version: Annotated[
            str | None,
            Field(description="Version the caller uses; docs are current, not version-pinned."),
        ] = None,
        question: Annotated[
            str | None, Field(description="shiny only: the question being answered (max 500).")
        ] = None,
        operating_system: Annotated[str | None, Field(description="positron only.")] = None,
        r_version: Annotated[str | None, Field(description="positron only.")] = None,
        project_type: Annotated[str | None, Field(description="positron only.")] = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Retrieve one page from the fixed catalog of official framework documentation."""
        return await bounded(
            _service(ctx).get_framework_docs(
                framework, topic, version, question, operating_system, r_version, project_type
            ),
            compact=verbosity == "compact",
            repository=framework,
        )

    @server.tool(annotations=_annotations("Get R workflow guidance"))
    async def get_r_workflow_guidance(
        scenario: Annotated[
            WorkflowScenario,
            Field(
                description=(
                    "Framework scenarios (shiny_bioconductor, quarto_positron, "
                    "quarto_bioconductor, analysis_to_shiny) combine docs and package knowledge; "
                    "visualization scenarios (tidy_to_plot, graph_plot, interactive_plot, "
                    "reproducible_report) group current function references."
                )
            ),
        ],
        ctx: Context,
        packages: Annotated[
            list[dict[str, str]] | None,
            Field(
                description=(
                    "Framework scenarios only: up to 6 items like "
                    "{'package': 'DESeq2', 'repository': 'bioconductor'}."
                )
            ),
        ] = None,
        r_version: OptionalRVersion = None,
        bioc_version: BiocVersion = None,
        package_versions: PackageVersions = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Combine official docs with explicitly named packages; no code is generated or run."""
        return await bounded(
            _service(ctx).get_workflow(
                scenario, packages, r_version, bioc_version, package_versions
            ),
            compact=verbosity == "compact",
            repository="r_workflow",
            bioc_version=bioc_version,
        )

    @server.tool(annotations=_annotations("Analyze R source statically"))
    async def analyze_r_source(
        kind: Annotated[
            Literal["ggplot", "ggraph", "tidyr", "ggplotly", "knitr", "shiny", "quarto"],
            Field(description="Analyzer to run on the supplied text."),
        ],
        ctx: Context,
        source: Annotated[
            str | None,
            Field(description="R, Rmd or QMD text (max 256 KiB). Required except kind=shiny."),
        ] = None,
        files: Annotated[
            dict[str, str] | None,
            Field(description="shiny only: up to 50 named .R files instead of source."),
        ] = None,
        schemas: Annotated[
            dict[str, dict[str, Any]] | None,
            Field(
                description=(
                    "Caller-supplied column schemas: ggplot {'data'}, ggraph {'nodes','edges'}, "
                    "tidyr {'input','expected'}. Each is {column: type} or "
                    "{'columns': [...], 'candidate_keys': [[...]]}."
                )
            ),
        ] = None,
        package_versions: PackageVersions = None,
        renv_lock: RenvLock = None,
        document_type: Annotated[
            Literal["rmd", "qmd"] | None, Field(description="knitr only.")
        ] = None,
        project_config: Annotated[
            str | None, Field(description="quarto only: _quarto.yml text.")
        ] = None,
        quarto_version: Annotated[str | None, Field(description="quarto only.")] = None,
        r_version: Annotated[str | None, Field(description="quarto only.")] = None,
        dependencies: Annotated[
            list[str] | None, Field(description="quarto only: dependency names (unverified).")
        ] = None,
        shiny_version: Annotated[
            str | None, Field(description="shiny only: compared with current CRAN shiny.")
        ] = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Run bounded lexical checks on supplied R/Shiny/Quarto text; nothing is executed."""
        return await bounded(
            _service(ctx).analyze_r_source(
                kind,
                source,
                files,
                schemas,
                package_versions,
                renv_lock,
                document_type,
                project_config,
                quarto_version,
                r_version,
                dependencies,
                shiny_version,
            ),
            compact=verbosity == "compact",
            repository="r_source",
        )

    @server.tool(annotations=_annotations("Analyze R project metadata", open_world=False))
    async def analyze_r_project(
        files: Annotated[
            dict[str, str],
            Field(
                description=(
                    "1..100 project-relative paths mapped to file text, e.g. DESCRIPTION, "
                    "renv.lock, _quarto.yml, *.Rproj. Paths are never read from disk; "
                    ".Renviron values are not returned."
                )
            ),
        ],
        ctx: Context,
        file_manifest: Annotated[
            list[str] | None,
            Field(description="Extra project paths (names only) when _quarto.yml is supplied."),
        ] = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Analyze supplied R/Quarto project files as data; never reads paths or runs code."""
        return await bounded(
            _service(ctx).analyze_r_project(files, file_manifest),
            compact=verbosity == "compact",
            repository="r_project",
        )

    @server.tool(annotations=_annotations("Recommend an R technology stack"))
    async def recommend_technology_stack(
        objective: Annotated[str, Field(description="What the project must achieve (max 4000).")],
        ctx: Context,
        project_type: Annotated[
            Literal["analytics", "api", "dashboard", "package", "etl", "ml", "other"] | None,
            Field(description="Workflow profile; inferred from objective when omitted."),
        ] = None,
        requirements: Annotated[
            list[str] | None, Field(description="Up to 20 requirements, kept verbatim.")
        ] = None,
        existing_stack: Annotated[
            list[str] | None, Field(description="Up to 30 technologies already in use.")
        ] = None,
        deployment_target: Annotated[
            Literal["local", "docker", "cloud", "on_premises"] | None,
            Field(description="Where it will run."),
        ] = None,
        preferences: Annotated[
            dict[str, list[str]] | None,
            Field(description="{'prefer': [...], 'exclude': [...]} package or technology names."),
        ] = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Recommend a provisional architecture with repository-checked R package candidates."""
        return await bounded(
            _service(ctx).recommend_technology_stack(
                objective,
                project_type,
                requirements,
                existing_stack,
                deployment_target,
                preferences,
            ),
            compact=verbosity == "compact",
            repository="technology_stack",
        )

    if not prompt_intelligence_enabled():
        return

    @server.tool(annotations=_annotations("Build or improve an R prompt"))
    async def build_r_prompt(
        request: Annotated[
            str,
            Field(description="Task request, or the existing prompt text when mode='improve'."),
        ],
        ctx: Context,
        mode: Annotated[
            Literal["build", "improve"],
            Field(description="'improve' restructures an existing prompt and keeps it verbatim."),
        ] = "build",
        improvement_goals: Annotated[
            list[str] | None, Field(description="improve only: goals added as constraints.")
        ] = None,
        target: Annotated[
            Literal["codex", "chatgpt", "generic"] | None,
            Field(description="Assistant the prompt is written for; server default otherwise."),
        ] = None,
        detail_level: Annotated[
            Literal["concise", "standard", "comprehensive"] | None,
            Field(description="Prompt length and depth; server default otherwise."),
        ] = None,
        task_category: Annotated[
            str | None, Field(description="build only: explicit category; inferred otherwise.")
        ] = None,
        packages: Annotated[
            list[str] | None, Field(description="Package names to ground with repository data.")
        ] = None,
        r_version: OptionalRVersion = None,
        bioconductor_release: BiocVersion = None,
        project_context: Annotated[
            dict[str, str] | None, Field(description="Short labelled context; treated as data.")
        ] = None,
        constraints: Annotated[
            list[str] | None, Field(description="build only: explicit constraints.")
        ] = None,
        include_sources: Annotated[
            bool, Field(description="build only: cite repository sources in the prompt.")
        ] = True,
        enhancement_mode: Annotated[
            Literal["deterministic", "auto", "external"],
            Field(description="External rewriting runs only if a reviewed adapter is configured."),
        ] = "deterministic",
        language: Annotated[str, Field(description="build only: auto, en or ru.")] = "auto",
        structured_context: Annotated[
            dict[str, Any] | None,
            Field(description="CSV/SQL context such as delimiter, encoding, database_dialect."),
        ] = None,
        composition_mode: Annotated[
            Literal["auto", "single", "composed"],
            Field(description="build only: one template, multi-stage, or detect automatically."),
        ] = "auto",
        templates: Annotated[
            list[str] | None, Field(description="build only: explicit template ids.")
        ] = None,
        workflow_context: Annotated[
            dict[str, Any] | None,
            Field(description="build only: inputs, outputs, stage_order, technical_constraints."),
        ] = None,
        include_plan: Annotated[
            bool, Field(description="build only: return workflow stages and dependencies.")
        ] = True,
        include_provenance: Annotated[
            bool, Field(description="build only: return per-package source provenance.")
        ] = True,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Build an editable R prompt, or improve an existing one; nothing is executed."""
        intelligence = PromptIntelligence(_service(ctx))
        if mode == "improve":
            build_only = {
                "task_category": task_category is not None,
                "constraints": constraints is not None,
                "templates": templates is not None,
                "workflow_context": workflow_context is not None,
                "language": language != "auto",
                "composition_mode": composition_mode != "auto",
                "include_sources": include_sources is not True,
                "include_plan": include_plan is not True,
                "include_provenance": include_provenance is not True,
            }
            misplaced = [name for name, used in build_only.items() if used]
            if misplaced:
                error = KnowledgeError(
                    "invalid_input", f"Not applicable to mode=improve: {', '.join(misplaced)}"
                )
                return failure(error, repository="prompt_intelligence")
            operation = intelligence.improve_r_prompt(
                request,
                improvement_goals,
                target,
                detail_level,
                packages,
                r_version,
                bioconductor_release,
                project_context,
                enhancement_mode,
                structured_context,
            )
        else:
            if improvement_goals is not None:
                error = KnowledgeError(
                    "invalid_input", "improvement_goals is used only with mode=improve"
                )
                return failure(error, repository="prompt_intelligence")
            operation = intelligence.build_r_prompt(
                request,
                target,
                detail_level,
                task_category,
                packages,
                r_version,
                bioconductor_release,
                project_context,
                constraints,
                include_sources,
                enhancement_mode,
                language,
                structured_context,
                composition_mode,
                templates,
                workflow_context,
                include_plan,
                include_provenance,
            )
        return await bounded(
            operation,
            compact=verbosity == "compact",
            repository="prompt_intelligence",
            bioc_version=bioconductor_release,
        )

    @server.tool(annotations=_annotations("Validate an R prompt", open_world=False))
    async def validate_r_prompt(
        prompt_text: Annotated[str, Field(description="Prompt text to check, max 32000 chars.")],
    ) -> dict[str, Any]:
        """Check prompt structure, conflicts, possible secrets and unverified API claims."""

        async def operation():
            return PromptIntelligence(None).validate_r_prompt(prompt_text)

        return await bounded(operation(), repository="prompt_intelligence")

    @server.tool(annotations=_annotations("Get R prompt package context"))
    async def get_r_prompt_context(
        packages: Annotated[list[str], Field(description="Package names to resolve.")],
        ctx: Context,
        r_version: OptionalRVersion = None,
        bioconductor_release: BiocVersion = None,
        verbosity: Verbosity = "compact",
    ) -> dict[str, Any]:
        """Resolve package versions, direct dependencies and provenance for prompt grounding."""
        return await bounded(
            PromptIntelligence(_service(ctx)).get_r_prompt_context(
                packages, r_version, bioconductor_release
            ),
            compact=verbosity == "compact",
            repository="prompt_intelligence",
            bioc_version=bioconductor_release,
        )


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _register_resources(server: FastMCP) -> None:
    """Read-only catalogs and addressable documents for clients that support resources."""

    @server.resource(
        "r-knowledge://framework-docs",
        name="framework-docs-catalog",
        title="Official framework documentation catalog",
        description="Fixed Shiny, Positron and Quarto topics and their official URLs.",
        mime_type="application/json",
    )
    def framework_docs_catalog() -> str:
        return _json(
            {
                "catalog": FRAMEWORK_DOCS,
                "retrieve_with": "get_framework_docs (legacy: get_*_docs tools)",
                "note": "Caller input selects a topic, never a URL.",
            }
        )

    if prompt_intelligence_enabled():

        @server.resource(
            "r-knowledge://prompt-templates",
            name="prompt-templates",
            title="R prompt templates",
            description="Built-in deterministic R prompt template identifiers and descriptions.",
            mime_type="application/json",
        )
        def prompt_templates() -> str:
            return _json(PromptIntelligence(None).list_r_prompt_templates())

    @server.resource(
        "r-manual://{document_id}",
        name="r-manual-outline",
        title="Official R manual outline",
        description="Section ids and headings of one locally indexed official R manual.",
        mime_type="application/json",
    )
    async def r_manual_outline(document_id: str, ctx: Context) -> str:
        return _json(
            await bounded(
                _service(ctx).r_documentation.aget_outline(document_id),
                repository="r_documentation",
            )
        )

    @server.resource(
        "r-manual://{document_id}/{section_id}",
        name="r-manual-section",
        title="Official R manual section",
        description="One section of a locally indexed official R manual (up to 32000 chars).",
        mime_type="application/json",
    )
    async def r_manual_section(document_id: str, section_id: str, ctx: Context) -> str:
        return _json(
            await bounded(
                _service(ctx).get_r_documentation_section(document_id, section_id, 32000),
                repository="r_documentation",
            )
        )

    @server.resource(
        "cran://{package}/man/{alias}",
        name="cran-function-docs",
        title="CRAN function documentation",
        description=(
            "Raw Rd for one alias from the current verified CRAN source archive; first 8000 "
            "characters (page further with get_function_docs)."
        ),
        mime_type="application/json",
    )
    async def cran_function_docs(package: str, alias: str, ctx: Context) -> str:
        return _json(
            await bounded(
                _service(ctx).get_function_docs(package, alias, repository="cran"),
                package=package,
                repository="cran",
            )
        )


def create_http_app(allowed_hosts: list[str] | None = None):
    # In SDK 1.x stateless HTTP invokes the server lifespan per request.
    # Own the shared connection pool and cache in the ASGI application lifespan.
    client = make_client()
    service = KnowledgeService(CranHTTP(client))
    server = create_server(allowed_hosts=allowed_hosts, service=service)
    app = server.streamable_http_app()
    sdk_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with client, sdk_lifespan(app):
            yield

    app.router.lifespan_context = lifespan
    return app


def main():
    parser = argparse.ArgumentParser(description="Read-only R Knowledge MCP")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=os.environ.get("MCP_PORT", "8000"))
    parser.add_argument(
        "--allowed-host",
        action="append",
        dest="allowed_hosts",
        help="Allowed HTTP Host, repeatable; include port if needed",
    )
    args = parser.parse_args()
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        parser.error("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    logging.basicConfig(level=log_level)
    if not 1 <= args.port <= 65535:
        parser.error("--port / MCP_PORT must be in [1, 65535]")
    if args.transport == "stdio":
        create_server().run(transport="stdio")
    else:
        import uvicorn

        uvicorn.run(create_http_app(args.allowed_hosts), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
