"""Repository router, provenance envelopes and conservative cross-repository checks."""

import asyncio
import copy
import json
import logging
import re
from collections import OrderedDict
from collections.abc import Awaitable
from datetime import UTC, datetime

from .config import cache_ttl, github_token
from .diagnostics import awaitable_operation_id, log_internal_failure
from .errors import KnowledgeError
from .http import BioconductorHTTP, CranHTTP, package_name, version_parts
from .project_analysis import (
    analyze_quarto_document as analyze_quarto_source,
)
from .project_analysis import (
    analyze_quarto_project as analyze_quarto_config,
)
from .project_analysis import (
    analyze_r_workspace as analyze_workspace_metadata,
)
from .project_analysis import (
    analyze_shiny_app as analyze_shiny_source,
)
from .providers import BioconductorProvider, CranProvider, PackageRepository
from .providers.bioconductor import CATEGORIES
from .providers.framework_docs import DOCS as FRAMEWORK_DOCS
from .providers.framework_docs import FrameworkDocsProvider
from .providers.github_agents import GitHubAgentsProvider
from .providers.r_documentation import RDocumentationProvider
from .releases import BioconductorReleases, r_minor
from .technology_recommendation import (
    metadata_supports_role,
    package_candidates,
    project_plan,
    resolve_project_type,
    validate_recommendation_inputs,
)
from .visualization_analysis import (
    analyze_ggplot_code,
    analyze_ggplotly_compatibility,
    analyze_ggraph_code,
    analyze_knitr_chunks,
    analyze_tidyr_pipeline,
)

MAX_RESULT_BYTES = 60_000
# Archive fallback cannot help when the package or request itself is wrong.
NO_ARCHIVE_RETRY = {"package_not_found", "invalid_input"}
MIN_TRUNCATED_CHARS = 256
TRUNCATION_RESERVE = 1024
TRUNCATION_MARKER = " …[truncated by server output limit]"
SHINY_PACKAGE_DOCS = {
    name.casefold(): name
    for name in (
        "shiny",
        "bslib",
        "htmltools",
        "shinyWidgets",
        "DT",
        "plotly",
        "promises",
        "future",
        "shinyvalidate",
        "shinytest2",
        "testthat",
        "reactlog",
        "thematic",
    )
}
SHINY_FUNCTION_OWNERS = {
    name: "shiny"
    for name in (
        "shinyApp",
        "fluidPage",
        "moduleServer",
        "NS",
        "reactive",
        "reactiveVal",
        "reactiveValues",
        "observe",
        "observeEvent",
        "eventReactive",
        "renderPlot",
        "renderTable",
        "renderUI",
        "req",
        "validate",
        "need",
        "testServer",
    )
}
SHINY_FUNCTION_OWNERS["page_sidebar"] = "bslib"
WORKFLOW_TOPICS = {
    "shiny_bioconductor": [("shiny", "reactivity"), ("shiny", "modules")],
    "quarto_positron": [("positron", "interpreters"), ("quarto", "r"), ("quarto", "projects")],
    "quarto_bioconductor": [("quarto", "r"), ("quarto", "citations")],
    "analysis_to_shiny": [("shiny", "basics"), ("shiny", "reactivity"), ("shiny", "modules")],
}
VISUALIZATION_WORKFLOWS = {
    "tidy_to_plot": {
        "sequence": [
            ("tidyr", "pivot_longer"),
            ("ggplot2", "ggplot"),
            ("ggplot2", "aes"),
            ("ggplot2", "geom_point"),
        ],
        "scope": "Use pivot_longer() to create a long table, then map columns in ggplot2.",
    },
    "graph_plot": {
        "sequence": [
            ("ggraph", "ggraph"),
            ("ggraph", "geom_edge_link"),
            ("ggraph", "geom_node_point"),
        ],
        "scope": "Build a graph visualization by adding edge and node layers to a ggraph layout.",
    },
    "interactive_plot": {
        "sequence": [("plotly", "ggplotly")],
        "scope": (
            "Convert a ggplot object to a Plotly widget and validate rendering "
            "in the client environment."
        ),
    },
    "reproducible_report": {
        "sequence": [("knitr", "knit"), ("knitr", "opts_chunk"), ("ggplot2", "ggsave")],
        "scope": (
            "Review chunk execution options and figure export while keeping "
            "the rendering environment explicit."
        ),
    },
}


PACKAGE_SECTIONS = ("metadata", "dependencies", "vignettes", "agent_guidance")
_LOCK_OPTIONS = frozenset({"package_versions", "renv_lock"})
# kind -> (accepted schema names, accepted optional arguments)
SOURCE_ANALYZERS = {
    "ggplot": (("data",), _LOCK_OPTIONS),
    "ggraph": (("nodes", "edges"), _LOCK_OPTIONS),
    "tidyr": (("input", "expected"), _LOCK_OPTIONS),
    "ggplotly": ((), _LOCK_OPTIONS),
    "knitr": ((), _LOCK_OPTIONS | {"document_type"}),
    "shiny": ((), frozenset({"files", "shiny_version"})),
    "quarto": ((), frozenset({"project_config", "quarto_version", "r_version", "dependencies"})),
}
SCHEMA_ARGUMENTS = {
    "data": "data_schema",
    "nodes": "node_schema",
    "edges": "edge_schema",
    "input": "input_schema",
    "expected": "expected_schema",
}
R_CONSTRAINT = re.compile(r"\s*R\s*\((>=|<=|==|!=|>|<)\s*([0-9][0-9.-]*)\)\s*")
# Static explanatory text that compact responses omit; safety flags such as trust,
# not_executed and verification_status are always kept.
COMPACT_DROPPED_KEYS = frozenset({"limitations", "verification_notes", "dependency_field_scope"})


def failure(exc: KnowledgeError, package=None, repository=None, bioc_version=None):
    return {
        "package": package,
        "repository": repository,
        "package_version": None,
        "bioc_version": bioc_version,
        "source_url": exc.source_url,
        "checked_at": None,
        "verification_status": "failed",
        "sources": list(exc.related_sources),
        "error": {
            "code": exc.code,
            "message": str(exc),
            "source_url": exc.source_url,
            "attempted_at": datetime.now(UTC).isoformat(),
            **({"cached": True} if exc.cached else {}),
            **exc.details,
        },
    }


class KnowledgeService:
    def __init__(
        self,
        http: CranHTTP,
        providers: dict[str, PackageRepository] | None = None,
        agents_provider: GitHubAgentsProvider | None = None,
        framework_docs_provider: FrameworkDocsProvider | None = None,
        r_documentation_provider: RDocumentationProvider | None = None,
    ):
        self.http = http  # Backward-compatible injection point for offline clients/tests.
        self.bioc_http = BioconductorHTTP(http.client)
        self.releases = BioconductorReleases(self.bioc_http)
        self.providers = providers if providers is not None else {"cran": CranProvider(http)}
        self._bioc: OrderedDict[str, BioconductorProvider] = OrderedDict()
        self.agents = agents_provider or GitHubAgentsProvider(
            http.client, ttl=cache_ttl(3600), token=github_token()
        )
        self.framework_docs = framework_docs_provider or FrameworkDocsProvider(http.client)
        self.r_documentation = r_documentation_provider or RDocumentationProvider(http.client)

    async def provider(self, repository: str, bioc_version: str | None = None):
        if repository == "bioconductor":
            release = await self.releases.resolve(bioc_version)
            key = release.version
            if key not in self._bioc or self._bioc[key].release != release:
                if key in self._bioc:
                    del self._bioc[key]
                while len(self._bioc) >= 8:
                    self._bioc.popitem(last=False)
                self._bioc[key] = BioconductorProvider(self.bioc_http, release)
            self._bioc.move_to_end(key)
            return self._bioc[key]
        if repository in self.providers:
            if bioc_version is not None:
                raise KnowledgeError(
                    "invalid_input", "bioc_version is only applicable to Bioconductor"
                )
            return self.providers[repository]
        raise KnowledgeError("invalid_input", "repository must be cran, bioconductor or all")

    def enrich(self, result: dict, provider: PackageRepository) -> dict:
        result = dict(result)
        sources = list(result.get("sources", []))
        primary = sources[-1] if sources else {}
        result.update(
            repository=provider.repository,
            bioc_version=provider.bioc_version,
            package_version=result.get("package_version", result.get("latest_cran_version")),
            source_url=primary.get("source_url"),
            checked_at=primary.get("checked_at"),
            verification_status=result.get("verification_status", "verified"),
        )
        result.setdefault("package", None)
        if isinstance(provider, BioconductorProvider):
            result.pop("latest_cran_version", None)
            result.pop("cran_url", None)
            if "version_scope" in result:
                result["version_scope"] = "selected_bioconductor_release"
            result.update(
                channel=provider.release.channel,
                required_r_version=provider.release.r_version,
                compatibility_status="not_checked",
            )
            if result.get("package") in provider._index_records:
                result["category"] = CATEGORIES[
                    provider._index_records[result["package"]]["_category"]
                ]
            result["warnings"] = [
                "R version not supplied; run check_package_compatibility before use"
            ]
            if provider.release.channel == "devel":
                result["warnings"].append(
                    "Development release; packages and R requirements may change"
                )
            if provider.release.channel == "historical":
                result["warnings"].append(
                    "Historical release; current CRAN dependencies may no longer match"
                )
            sources.append(provider.release.config.provenance())
        result["sources"] = sources
        if "results" in result:
            result["results"] = [
                self.enrich({**item, "sources": item.get("sources", sources)}, provider)
                for item in result["results"]
            ]
        return result

    async def _one(
        self,
        method,
        package,
        repository,
        bioc_version,
        resolve_repositories=False,
        dependency_bioc_version=None,
        **kwargs,
    ):
        provider = None
        try:
            package_name(package)
            provider = await self.provider(repository, bioc_version)
            result = await getattr(provider, method)(package, **kwargs)
            if method == "get_dependencies" and (
                repository == "bioconductor" or resolve_repositories
            ):
                bioc = (
                    provider
                    if repository == "bioconductor"
                    else await self.provider("bioconductor", dependency_bioc_version)
                )
                result["resolved_dependencies"] = await self.resolve_dependencies(
                    result["dependencies"], bioc
                )
                result["dependency_bioc_version"] = bioc.bioc_version
                result["sources"] += await self.dependency_sources(bioc)
            return self.enrich(result, provider)
        except KnowledgeError as exc:
            return failure(
                exc, package, repository, provider.bioc_version if provider else bioc_version
            )

    async def _dispatch(self, method, package, repository, bioc_version, **kwargs):
        if repository != "all":
            return await self._one(method, package, repository, bioc_version, **kwargs)
        results = await asyncio.gather(
            *(
                self._one(
                    method,
                    package,
                    name,
                    bioc_version if name == "bioconductor" else None,
                    **kwargs,
                )
                for name in ("cran", "bioconductor")
            )
        )
        return self.aggregate(list(results), package, bioc_version)

    @staticmethod
    def aggregate(results, package=None, bioc_version=None):
        successes = [r for r in results if "error" not in r]
        errors = [r for r in results if "error" in r]
        status = (
            "verified"
            if successes and all(r["error"]["code"] == "package_not_found" for r in errors)
            else "partial"
            if successes
            else "failed"
        )
        sources = [s for r in results for s in r.get("sources", [])]
        return {
            "package": package,
            "repository": "all",
            "package_version": None,
            "bioc_version": bioc_version,
            "results": successes,
            "errors": errors,
            "verification_status": status,
            "sources": sources,
            "source_url": None,
            "checked_at": min((s["checked_at"] for s in sources), default=None),
        }

    async def search_packages(
        self, query, limit=10, offset=0, repository="cran", bioc_version=None
    ):
        if repository != "all":
            provider = await self.provider(repository, bioc_version)
            return self.enrich(await provider.search_packages(query, limit, offset), provider)
        if not 1 <= limit <= 20 or not 0 <= offset <= 100000:
            raise KnowledgeError("invalid_input", "Invalid search limit or offset")
        results, consumed, matches, errors = [], 0, [], []
        for name in ("cran", "bioconductor"):
            try:
                provider = await self.provider(
                    name, bioc_version if name == "bioconductor" else None
                )
                result = self.enrich(
                    await provider.search_packages(query, limit, max(0, offset - consumed)),
                    provider,
                )
                results.append(result)
                consumed += result["total"]
                matches.extend(result["results"])
            except KnowledgeError as exc:
                errors.append(failure(exc, repository=name))
        aggregate = self.aggregate(results + errors, bioc_version=bioc_version)
        aggregate.update(
            query=query,
            results=matches[:limit],
            total=consumed,
            next_offset=offset + limit if offset + limit < consumed else None,
            search_scope="CRAN then Bioconductor; independent repository identities",
        )
        return aggregate

    async def get_package_info(
        self, package, repository="cran", bioc_version=None, verify_archive=True
    ):
        if not isinstance(verify_archive, bool):
            raise KnowledgeError("invalid_input", "verify_archive must be a boolean")
        mode = {} if verify_archive else {"verify_archive": False}
        return await self._dispatch(
            "get_package_info",
            package,
            repository,
            bioc_version,
            **mode,
        )

    async def get_dependencies(
        self, package, repository="cran", bioc_version=None, resolve_repositories=False
    ):
        scope_version = None if repository == "cran" and resolve_repositories else bioc_version
        return await self._dispatch(
            "get_dependencies",
            package,
            repository,
            scope_version,
            resolve_repositories=resolve_repositories or repository == "all",
            dependency_bioc_version=bioc_version,
        )

    async def dependency_sources(self, bioc):
        cran = await self.provider("cran")
        _, artifact = await cran.index()
        return [
            artifact.provenance(),
            bioc.release.config.provenance(),
            *(a.provenance() for a in bioc._sources.values()),
        ]

    async def get_function_docs(
        self, package, function, offset=0, repository="cran", bioc_version=None
    ):
        return await self._dispatch(
            "get_function_docs", package, repository, bioc_version, function=function, offset=offset
        )

    async def list_package_functions(
        self,
        package,
        repository="cran",
        bioc_version=None,
        package_version=None,
        query=None,
        limit=20,
        offset=0,
        snapshot=None,
    ):
        if repository not in ("cran", "bioconductor"):
            raise KnowledgeError("invalid_input", "Discovery requires one repository")
        result = await self._one(
            "list_package_functions",
            package,
            repository,
            bioc_version,
            query=query,
            limit=limit,
            offset=offset,
            package_version=package_version,
            snapshot=snapshot,
        )
        if _encoded_size(result) > 20 << 10:
            raise KnowledgeError("response_too_large", "Narrow discovery query or reduce limit")
        return result

    async def get_package_vignettes(self, package, repository="cran", bioc_version=None):
        return await self._dispatch("get_package_vignettes", package, repository, bioc_version)

    async def _external_package_metadata(self, package, repository, bioc_version):
        package_name(package)
        provider = await self.provider(repository, bioc_version)
        if provider.repository == "cran":
            # CRAN's version-matched DESCRIPTION already carries the URL field.
            try:
                info = await provider.get_package_info(package, verify_archive=False)
            except KnowledgeError as exc:
                if exc.code in NO_ARCHIVE_RETRY:
                    raise
                info = None
            if info is not None and info.get("verification_status", "verified") == "verified":
                return provider, self.enrich(info, provider)
        info = await provider.get_package_info(package)
        enriched = self.enrich(info, provider)
        return provider, enriched

    async def get_package_agent_guidance(
        self, package, revision, repository="cran", bioc_version=None
    ):
        provider, info = await self._external_package_metadata(package, repository, bioc_version)
        return await self.agents.get_package_agent_guidance(
            package,
            info["package_version"],
            info.get("urls"),
            revision,
            repository,
            provider.bioc_version,
        )

    async def search_r_documentation(self, query, manuals=None, limit=5, r_version=None):
        """Search the local official R manual index; this method never fetches sources."""
        return await self.r_documentation.asearch(query, manuals, limit, r_version)

    async def get_r_documentation_section(self, document_id, section_id, max_chars=8000):
        """Read one section from the local official R manual index."""
        return await self.r_documentation.aget_section(document_id, section_id, max_chars)

    async def _package_metadata(self, package, repository, bioc_version):
        """Prefer CRAN's lightweight DESCRIPTION; download the archive only as a fallback."""
        if repository != "cran":
            return await self._one("get_package_info", package, repository, bioc_version)
        info = await self._one(
            "get_package_info", package, repository, bioc_version, verify_archive=False
        )
        if info.get("verification_status") == "verified" or (
            info.get("error", {}).get("code") in NO_ARCHIVE_RETRY
        ):
            return info
        return await self._one("get_package_info", package, repository, bioc_version)

    async def get_package_knowledge(
        self,
        package,
        repository="cran",
        bioc_version=None,
        revision=None,
    ):
        if repository == "all":
            raise KnowledgeError(
                "invalid_input",
                "Select cran or bioconductor so each knowledge bundle has one package identity",
            )
        provider = await self.provider(repository, bioc_version)
        info = await self._package_metadata(package, repository, bioc_version)
        dependencies = await self._one("get_dependencies", package, repository, bioc_version)
        sections = {"package_info": info, "dependencies": dependencies}
        if "error" in info:
            sections["agent_guidance"] = {
                "status": "not_attempted",
                "reason": "package metadata could not be verified",
            }
        else:
            if revision:
                try:
                    sections["agent_guidance"] = await self.agents.get_package_agent_guidance(
                        package,
                        info["package_version"],
                        info.get("urls"),
                        revision,
                        repository,
                        provider.bioc_version,
                    )
                except KnowledgeError as exc:
                    sections["agent_guidance"] = failure(
                        exc, package, repository, provider.bioc_version
                    )
            else:
                sections["agent_guidance"] = {
                    "status": "not_requested",
                    "reason": "Specify revision (branch, tag or commit ref) to inspect AGENTS.md",
                }
        errors = [
            {"section": name, "error": result["error"]}
            for name, result in sections.items()
            if isinstance(result, dict) and "error" in result
        ]
        sources = [
            source
            for result in sections.values()
            if isinstance(result, dict)
            for source in result.get("sources", [])
        ]
        overall = (
            "partial"
            if errors
            or any(
                result.get("status") == "not_requested"
                for result in sections.values()
                if isinstance(result, dict)
            )
            else "verified"
        )
        return {
            "package": package,
            "repository": repository,
            "package_version": info.get("package_version"),
            "bioc_version": provider.bioc_version,
            "sections": sections,
            "errors": errors,
            "source_url": info.get("source_url"),
            "checked_at": max((s["checked_at"] for s in sources), default=info.get("checked_at")),
            "verification_status": overall,
            "sources": sources,
        }

    async def get_shiny_docs(self, package, function, package_version=None):
        canonical = SHINY_PACKAGE_DOCS.get(package.casefold()) if isinstance(package, str) else None
        if canonical is None:
            raise KnowledgeError(
                "unsupported_package",
                "Select a documented Shiny ecosystem package: "
                f"{', '.join(SHINY_PACKAGE_DOCS.values())}",
            )
        owner = SHINY_FUNCTION_OWNERS.get(function) if isinstance(function, str) else None
        if owner and canonical != owner:
            raise KnowledgeError(
                "function_owner_mismatch",
                f"Official Shiny reference identifies {function} as belonging to {owner}",
            )
        info = await self.get_package_info(canonical, "cran", verify_archive=False)
        if "error" in info:
            return {"package": canonical, "documentation": info, "verification_status": "failed"}
        actual_version = info["package_version"]
        if package_version is not None and version_parts(package_version) != version_parts(
            actual_version
        ):
            error = KnowledgeError(
                "requested_version_unavailable",
                "Only current indexed CRAN source documentation is implemented; "
                "the requested version was not substituted.",
            )
            return {
                **failure(error, canonical, "cran"),
                "latest_package_version": actual_version,
                "requested_package_version": package_version,
            }
        docs = await self.get_function_docs(canonical, function, repository="cran")
        if "error" in docs:
            return {
                "package": canonical,
                "package_version": actual_version,
                "requested_package_version": package_version,
                "documentation": docs,
                "source_url": docs.get("source_url"),
                "checked_at": docs.get("checked_at"),
                "sources": docs.get("sources", []),
                "verification_status": "failed",
            }
        return {
            "package": canonical,
            "repository": "cran",
            "package_version": actual_version,
            "requested_package_version": package_version,
            "function": function,
            "documentation": docs,
            "package_metadata_source": info["source_url"],
            "source_url": docs.get("source_url"),
            "checked_at": docs.get("checked_at"),
            "sources": info.get("sources", []) + docs.get("sources", []),
            "verification_status": "verified",
            "version_scope": "exact_current_indexed_source_archive",
        }

    async def get_visualization_docs(self, package, function, package_version=None):
        allowed = {"ggplot2", "ggraph", "tidyr", "plotly", "knitr"}
        if not isinstance(package, str) or package.casefold() not in allowed:
            raise KnowledgeError(
                "unsupported_package", "Choose ggplot2, ggraph, tidyr, plotly or knitr"
            )
        canonical = package.casefold()
        if not isinstance(function, str) or not re.fullmatch(r"[A-Za-z.][A-Za-z0-9._]*", function):
            raise KnowledgeError("invalid_input", "function must be an R function alias")
        info = await self.get_package_info(canonical, "cran", verify_archive=False)
        if "error" in info:
            return {
                "package": canonical,
                "function": function,
                "documentation": info,
                "verification_status": "failed",
            }
        actual_version = info["package_version"]
        if package_version is not None and version_parts(package_version) != version_parts(
            actual_version
        ):
            error = KnowledgeError(
                "requested_version_unavailable",
                "Only current indexed CRAN documentation is available; no version was substituted.",
            )
            return {
                **failure(error, canonical, "cran"),
                "function": function,
                "latest_package_version": actual_version,
                "requested_package_version": package_version,
                "sources": info.get("sources", []),
                "source_url": info.get("source_url"),
                "checked_at": info.get("checked_at"),
            }
        docs = await self.get_function_docs(canonical, function, repository="cran")
        return {
            "package": canonical,
            "repository": "cran",
            "package_version": actual_version,
            "requested_package_version": package_version,
            "function": function,
            "documentation": docs,
            "package_metadata_source": info.get("source_url"),
            "source_url": docs.get("source_url"),
            "checked_at": docs.get("checked_at"),
            "sources": info.get("sources", []) + docs.get("sources", []),
            "verification_status": "failed" if "error" in docs else "verified",
            "version_scope": "exact_current_indexed_source_archive",
        }

    async def get_visualization_workflow(self, scenario, package_versions=None):
        if scenario not in VISUALIZATION_WORKFLOWS:
            raise KnowledgeError(
                "invalid_input",
                f"scenario must be one of: {', '.join(sorted(VISUALIZATION_WORKFLOWS))}",
            )
        if package_versions is None:
            package_versions = {}
        if not isinstance(package_versions, dict) or len(package_versions) > 5:
            raise KnowledgeError("invalid_input", "Supply at most five explicit package versions")
        if any(
            key not in {"ggplot2", "ggraph", "tidyr", "plotly", "knitr"}
            or not isinstance(value, str)
            for key, value in package_versions.items()
        ):
            raise KnowledgeError(
                "invalid_input", "Package versions must name supported packages and string versions"
            )
        workflow = VISUALIZATION_WORKFLOWS[scenario]
        results = []
        errors = []
        for package, function in workflow["sequence"]:
            try:
                result = await self.get_visualization_docs(
                    package, function, package_versions.get(package)
                )
            except KnowledgeError as exc:
                result = failure(exc, package, "cran")
            results.append(result)
            if result.get("verification_status") != "verified":
                errors.append({"package": package, "function": function, "result": result})
        sources = [source for item in results for source in item.get("sources", [])]
        return {
            "scenario": scenario,
            "scope": workflow["scope"],
            "steps": results,
            "sources": sources,
            "checked_at": max((s.get("checked_at", "") for s in sources), default=None),
            "source_url": sources[-1].get("source_url") if sources else None,
            "repository": "cran",
            "bioc_version": None,
            "verification_status": "partial" if errors else "verified",
            "errors": errors,
            "no_code_executed": True,
            "limitations": [
                "Workflow steps are fixed documentation groupings, not generated or tested R code.",
                "Function documentation is available only for the current indexed "
                "CRAN source version.",
            ],
        }

    async def _visualization_analysis(self, analyzer, source, schemas, package_versions, renv_lock):
        if renv_lock is not None:
            if not isinstance(renv_lock, str) or len(renv_lock) > 512 << 10:
                raise KnowledgeError("invalid_input", "renv.lock text is limited to 512 KiB")
            try:
                if len(renv_lock.encode("utf-8")) > 512 << 10:
                    raise KnowledgeError("invalid_input", "renv.lock text is limited to 512 KiB")
            except UnicodeError as exc:
                raise KnowledgeError("invalid_input", "renv.lock must be valid Unicode") from exc
            try:
                lock = json.loads(renv_lock)
            except (ValueError, TypeError) as exc:
                raise KnowledgeError("invalid_input", "renv.lock must be valid JSON") from exc
            if not isinstance(lock, dict) or not isinstance(lock.get("Packages", {}), dict):
                raise KnowledgeError("invalid_input", "renv.lock needs a Packages object")
            if len(lock.get("Packages", {})) > 5000:
                raise KnowledgeError(
                    "invalid_input", "renv.lock supports at most 5000 package records"
                )
            allowed = {"ggplot2", "ggraph", "tidyr", "plotly", "knitr"}
            for name, entry in lock["Packages"].items():
                if isinstance(name, str) and name.casefold() in allowed and isinstance(entry, dict):
                    version = entry.get("Version")
                    if version is not None and (not isinstance(version, str) or len(version) > 100):
                        raise KnowledgeError(
                            "invalid_input", "renv.lock package versions must be short strings"
                        )
            lock_versions = {
                name.casefold(): entry.get("Version")
                for name, entry in lock["Packages"].items()
                if isinstance(name, str) and isinstance(entry, dict)
            }
        else:
            lock_versions = {}
        # CPU-bound static analysis must not block the event loop for other requests.
        result = await asyncio.to_thread(analyzer, source, **schemas)
        requested = package_versions or {}
        if not isinstance(requested, dict) or len(requested) > 12:
            raise KnowledgeError(
                "invalid_input", "package_versions must be a mapping of at most 12 packages"
            )
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in requested.items()):
            raise KnowledgeError("invalid_input", "Package names and versions must be strings")
        versions = {}
        sources = []
        allowed = {"ggplot2", "ggraph", "tidyr", "plotly", "knitr"}
        for package, supplied in requested.items():
            name = package.casefold()
            if name not in allowed:
                raise KnowledgeError(
                    "unsupported_package", "Only visualization core packages may be version checked"
                )
            info = await self.get_package_info(name, "cran", verify_archive=False)
            if "error" in info:
                versions[name] = {"verification_status": "failed", "error": info["error"]}
                continue
            latest = info.get("package_version")
            lock_version = lock_versions.get(name)
            versions[name] = {
                "client_supplied_version": supplied,
                "renv_lock_version": lock_version,
                "latest_cran_version": latest,
                "version_matches_cran": version_parts(supplied) == version_parts(latest),
                "lock_matches_supplied": lock_version is None or lock_version == supplied,
                "verification_status": "verified_current_cran_comparison",
                "version_scope": "latest_cran_not_installed_version",
            }
            sources.extend(info.get("sources", []))
        for package, version in lock_versions.items():
            if package in allowed and package not in versions:
                versions[package] = {
                    "renv_lock_version": version,
                    "verification_status": "client_supplied_lock_unverified",
                    "version_scope": "renv_lock_not_installed_version",
                }
        result.update(
            package_versions=versions,
            package_version_sources=sources,
            checked_at=max((source.get("checked_at", "") for source in sources), default=None),
            repository="cran",
            bioc_version=None,
            verification_status="verified"
            if not versions
            or all(v.get("verification_status") != "failed" for v in versions.values())
            else "partial",
            source_url=sources[-1].get("source_url") if sources else None,
            renv_lock_checked=False,
            not_executed=True,
        )
        return result

    async def analyze_ggplot_code(
        self, source, data_schema=None, package_versions=None, renv_lock=None
    ):
        return await self._visualization_analysis(
            analyze_ggplot_code, source, {"data_schema": data_schema}, package_versions, renv_lock
        )

    async def analyze_ggraph_code(
        self, source, node_schema=None, edge_schema=None, package_versions=None, renv_lock=None
    ):
        return await self._visualization_analysis(
            analyze_ggraph_code,
            source,
            {"node_schema": node_schema, "edge_schema": edge_schema},
            package_versions,
            renv_lock,
        )

    async def analyze_tidyr_pipeline(
        self, source, input_schema=None, expected_schema=None, package_versions=None, renv_lock=None
    ):
        return await self._visualization_analysis(
            analyze_tidyr_pipeline,
            source,
            {"input_schema": input_schema, "expected_schema": expected_schema},
            package_versions,
            renv_lock,
        )

    async def analyze_ggplotly_compatibility(self, source, package_versions=None, renv_lock=None):
        return await self._visualization_analysis(
            analyze_ggplotly_compatibility, source, {}, package_versions, renv_lock
        )

    async def analyze_knitr_chunks(
        self, source, document_type=None, package_versions=None, renv_lock=None
    ):
        return await self._visualization_analysis(
            analyze_knitr_chunks,
            source,
            {"document_type": document_type},
            package_versions,
            renv_lock,
        )

    async def explain_shiny_reactivity(self, topic, question=None, source=None):
        if question is not None and (not isinstance(question, str) or len(question) > 500):
            raise KnowledgeError("invalid_input", "Question must be at most 500 characters")
        docs = await self.framework_docs.get_docs("shiny", topic)
        analysis = (
            await asyncio.to_thread(analyze_shiny_source, source=source)
            if source is not None
            else None
        )
        guidance = {
            "reactivity": (
                "Reactive sources, expressions and endpoints form a dependency graph. "
                "Expressions track reads and cache values until invalidated."
            ),
            "isolation": (
                "isolate() lets code read reactive values without registering those reads "
                "as dependencies of the current reactive context."
            ),
            "modules": (
                "Shiny modules namespace UI IDs and create scoped server logic. "
                "moduleServer() supports testServer() testing."
            ),
            "async": (
                "For long-running work, current Shiny guidance recommends considering "
                "Extended Tasks first; async programming remains supported."
            ),
            "basics": (
                "A Shiny app connects UI inputs to server-side reactive computations "
                "and rendered outputs."
            ),
        }[topic.casefold()]
        return {
            "framework": "shiny",
            "topic": topic,
            "question_received": question is not None,
            "explanation": guidance,
            "official_documentation": docs,
            "source_analysis": analysis,
            "not_executed": True,
            "verification_status": "verified_official_source",
            "sources": [
                {
                    "source_url": docs["source_url"],
                    "checked_at": docs["checked_at"],
                    "verification_status": docs["verification_status"],
                }
            ],
        }

    async def analyze_shiny_app(self, source=None, files=None, shiny_version=None):
        result = await asyncio.to_thread(analyze_shiny_source, source=source, files=files)
        if shiny_version is not None:
            result["client_supplied_shiny_version"] = shiny_version
            result["version_check"] = await self.check_package_version("shiny", shiny_version)
            result["version_warning"] = (
                "Static findings do not establish runtime compatibility; the version "
                "check compares supplied version only to current CRAN."
            )
        return result

    async def get_positron_guidance(
        self, topic, positron_version=None, operating_system=None, r_version=None, project_type=None
    ):
        result = await self.framework_docs.get_docs("positron", topic, positron_version)
        result.update(
            operating_system=operating_system,
            r_version=r_version,
            project_type=project_type,
            version_warning=(
                "Positron documentation is current and not pinned to the requested version."
                if positron_version
                else None
            ),
            integration_note=(
                "This server provides guidance and MCP tools. "
                "It does not control Positron or an R session."
            ),
        )
        return result

    async def get_quarto_docs(self, topic, quarto_version=None):
        result = await self.framework_docs.get_docs("quarto", topic, quarto_version)
        if quarto_version:
            result["version_warning"] = (
                "Current official docs are not pinned to the requested Quarto version."
            )
        return result

    async def analyze_quarto_document(
        self, source, project_config=None, quarto_version=None, r_version=None, dependencies=None
    ):
        if dependencies is not None and (
            not isinstance(dependencies, list)
            or len(dependencies) > 100
            or any(
                not isinstance(item, str) or not item or len(item) > 200 for item in dependencies
            )
        ):
            raise KnowledgeError(
                "invalid_input",
                "Dependencies must be at most 100 non-empty names of 200 characters",
            )
        result = await asyncio.to_thread(
            analyze_quarto_source, source, project_config, quarto_version
        )
        result["r_version"] = r_version
        result["dependencies_supplied"] = dependencies or []
        result["dependency_analysis"] = "caller_supplied_names_unverified"
        return result

    async def analyze_quarto_project(
        self, project_config, metadata_config=None, file_manifest=None
    ):
        return await asyncio.to_thread(
            analyze_quarto_config, project_config, metadata_config, file_manifest
        )

    async def analyze_r_workspace(self, files):
        return await asyncio.to_thread(analyze_workspace_metadata, files)

    async def get_r_workflow_guidance(
        self, scenario, packages=None, r_version=None, bioc_version=None
    ):
        if scenario not in WORKFLOW_TOPICS:
            raise KnowledgeError(
                "invalid_input", f"scenario must be one of: {', '.join(sorted(WORKFLOW_TOPICS))}"
            )
        packages = packages or []
        if not isinstance(packages, list) or len(packages) > 6:
            raise KnowledgeError("invalid_input", "Supply at most six explicit package requests")
        knowledge, errors = [], []
        for item in packages:
            if not isinstance(item, dict) or set(item) - {"package", "repository"}:
                raise KnowledgeError(
                    "invalid_input", "Each package needs package and optional repository"
                )
            name = item.get("package")
            repo = item.get("repository", "cran")
            if not isinstance(name, str) or not name:
                raise KnowledgeError("invalid_input", "Each workflow package needs a package name")
            if repo not in ("cran", "bioconductor"):
                raise KnowledgeError(
                    "invalid_input", "Workflow package repository must be cran or bioconductor"
                )
            bundle = await self.get_package_knowledge(
                name, repo, bioc_version if repo == "bioconductor" else None
            )
            knowledge.append(bundle)
            if bundle.get("errors"):
                errors.append({"package": name, "section": "package_knowledge", "result": bundle})
            if repo == "bioconductor" and r_version:
                compatibility = await self.check_package_compatibility(
                    name, r_version, bioc_version
                )
                if "error" in compatibility or compatibility.get("compatibility_status") in (
                    "incompatible",
                    "unknown",
                ):
                    errors.append(
                        {"package": name, "section": "compatibility", "result": compatibility}
                    )
        documentation = []
        for framework, topic in WORKFLOW_TOPICS[scenario]:
            try:
                documentation.append(await self.framework_docs.get_docs(framework, topic))
            except KnowledgeError as exc:
                errors.append({"framework": framework, "topic": topic, "error": failure(exc)})
        return {
            "scenario": scenario,
            "r_version": r_version,
            "bioc_version": bioc_version,
            "package_knowledge": knowledge,
            "official_framework_docs": documentation,
            "errors": errors,
            "verification_status": "partial" if errors else "verified",
            "not_executed": True,
            "limitations": [
                "Package recommendations are limited to names supplied explicitly by the caller.",
                "No app, report, dependency graph or local R environment is executed or inferred.",
            ],
        }

    async def recommend_technology_stack(
        self,
        objective,
        project_type=None,
        requirements=None,
        existing_stack=None,
        deployment_target=None,
        preferences=None,
    ):
        """Return a deterministic architecture plan with repository-checked R package candidates."""
        inputs = validate_recommendation_inputs(
            objective,
            project_type,
            requirements,
            existing_stack,
            deployment_target,
            preferences,
        )
        resolved_type, type_basis = resolve_project_type(
            inputs["project_type"], inputs["objective"], inputs["requirements"]
        )
        plan = project_plan(resolved_type)
        candidates = package_candidates(resolved_type)
        discovery = {
            "status": "workflow_template_candidates" if candidates else "not_applicable",
            "query": None,
            "candidate_limit": 5,
        }
        discovery_sources: list[dict] = []
        dynamic_role = None
        if not candidates and resolved_type in ("api", "ml"):
            query, dynamic_role = (
                ("api", "API framework")
                if resolved_type == "api"
                else ("machine learning", "modeling framework")
            )
            discovery["query"] = query
            try:
                search_result = await self.search_packages(query, limit=5, repository="cran")
            except KnowledgeError as exc:
                search_result = {"error": {"code": exc.code}}
            search_sources = (
                search_result.get("sources", []) if isinstance(search_result, dict) else []
            )
            if isinstance(search_sources, list):
                discovery_sources.extend(
                    source for source in search_sources if isinstance(source, dict)
                )
            if (
                not isinstance(search_result, dict)
                or "error" in search_result
                or not isinstance(search_result.get("results"), list)
            ):
                discovery["status"] = "repository_search_unavailable"
                if isinstance(search_result, dict) and isinstance(search_result.get("error"), dict):
                    discovery["error_code"] = search_result["error"].get("code")
            else:
                discovery["status"] = "repository_search_completed"
                for item in search_result["results"][:5]:
                    if not isinstance(item, dict) or not isinstance(item.get("package"), str):
                        continue
                    try:
                        package_name(item["package"])
                    except KnowledgeError:
                        continue
                    candidates.append(
                        {
                            "package": item["package"],
                            "role": dynamic_role,
                            "role_fit": dynamic_role,
                            "rationale": (
                                f"Discovered through current CRAN search for {query}; "
                                "the package DESCRIPTION must also support this role."
                            ),
                            "template_id": "provider_search",
                        }
                    )
        excluded = {item.casefold() for item in inputs["preferences"]["exclude"]}
        existing = {item.casefold() for item in inputs["existing_stack"]}
        preferred = {item.casefold() for item in inputs["preferences"]["prefer"]}
        grouped: dict[str, list[dict]] = {}
        dependencies: list[dict] = []
        sources: list[dict] = list(discovery_sources)
        package_checks: list[dict] = []

        # Fetch independent repository lookups concurrently; evaluation below stays ordered.
        active = [c["package"] for c in candidates if c["package"].casefold() not in excluded]
        infos = dict(
            zip(
                active,
                await asyncio.gather(
                    *(self.get_package_info(name, "cran", verify_archive=False) for name in active)
                ),
                strict=True,
            )
        )
        found = [name for name in active if "error" not in infos[name]]
        dependency_infos = dict(
            zip(
                found,
                await asyncio.gather(*(self.get_dependencies(name, "cran") for name in found)),
                strict=True,
            )
        )

        for candidate in candidates:
            package = candidate["package"]
            if package.casefold() in excluded:
                package_checks.append(
                    {
                        "package": package,
                        "role": candidate["role"],
                        "status": "excluded_by_user_preference",
                    }
                )
                continue
            info = infos[package]
            info_sources = info.get("sources", []) if isinstance(info, dict) else []
            if not isinstance(info_sources, list):
                info_sources = []
            sources.extend(info_sources)
            if (
                not isinstance(info, dict)
                or "error" in info
                or info.get("verification_status") != "verified"
                or info.get("package") != package
                or info.get("repository") != "cran"
                or info.get("metadata_verification_level") != "description_version_matched"
                or not info.get("package_version")
                or not info_sources
                or any(
                    not isinstance(source, dict)
                    or not isinstance(source.get("source_url"), str)
                    or not isinstance(source.get("checked_at"), str)
                    for source in info_sources
                )
            ):
                package_checks.append(
                    {
                        "package": package,
                        "role": candidate["role"],
                        "status": "repository_metadata_unavailable",
                        "error_code": info.get("error", {}).get("code")
                        if isinstance(info, dict) and isinstance(info.get("error"), dict)
                        else None,
                    }
                )
                continue

            fits_role = metadata_supports_role(
                package,
                info.get("title"),
                info.get("description"),
                candidate.get("role_fit"),
            )
            is_existing = package.casefold() in existing
            package_entry = {
                "package": package,
                "role": candidate["role"],
                "recommendation_status": "pending_role_selection",
                "rationale": candidate["rationale"],
                "metadata_fit_status": "title_or_description_matches_role"
                if fits_role
                else "metadata_does_not_confirm_role_fit",
                "package_version": info["package_version"],
                "repository": info.get("repository", "cran"),
                "metadata_verification_level": info.get("metadata_verification_level"),
                "sources": info_sources,
                "_fits_role": fits_role,
                "_is_existing": is_existing,
                "_is_preferred": package.casefold() in preferred,
            }
            if package.casefold() in preferred:
                package_entry["preference_match"] = "user_preferred"

            dep_info = dependency_infos[package]
            dep_sources = dep_info.get("sources", []) if isinstance(dep_info, dict) else []
            if not isinstance(dep_sources, list):
                dep_sources = []
            sources.extend(dep_sources)
            dep_values = dep_info.get("dependencies") if isinstance(dep_info, dict) else None
            dep_version_matches = (
                isinstance(dep_info, dict)
                and "error" not in dep_info
                and dep_info.get("package") == package
                and dep_info.get("repository") == "cran"
                and dep_info.get("package_version") == info.get("package_version")
                and isinstance(dep_values, dict)
                and bool(dep_sources)
                and all(
                    isinstance(source, dict)
                    and isinstance(source.get("source_url"), str)
                    and isinstance(source.get("checked_at"), str)
                    for source in dep_sources
                )
            )
            if dep_version_matches:
                dependencies.append(
                    {
                        "package": package,
                        "package_version": info["package_version"],
                        "required": {
                            key: dep_values.get(key, "")
                            for key in ("Depends", "Imports", "LinkingTo")
                        },
                        "runtime_required": {
                            key: dep_values.get(key, "") for key in ("Depends", "Imports")
                        },
                        "build_time": {"LinkingTo": dep_values.get("LinkingTo", "")},
                        "optional": {
                            key: dep_values.get(key, "") for key in ("Suggests", "Enhances")
                        },
                        "dependency_field_scope": {
                            "required": (
                                "Compatibility field retained from the initial response schema; "
                                "includes runtime and build-time fields."
                            ),
                            "runtime_required_fields": ["Depends", "Imports"],
                            "build_time_fields": ["LinkingTo"],
                            "optional_fields": ["Suggests", "Enhances"],
                        },
                        "scope": (
                            "verbatim direct repository fields; not a transitive dependency graph"
                        ),
                        "sources": dep_sources,
                    }
                )
                package_entry["dependency_verification_status"] = (
                    "same_version_direct_fields_verified"
                )
            else:
                package_entry["dependency_verification_status"] = "unavailable_or_version_mismatch"
            grouped.setdefault(candidate["role"], []).append(package_entry)
            package_checks.append(
                {
                    "package": package,
                    "role": candidate["role"],
                    "status": "metadata_and_dependencies_checked",
                    "recommendation_status": "pending_role_selection",
                    "dependency_verification_status": package_entry[
                        "dependency_verification_status"
                    ],
                }
            )

        for entries in grouped.values():
            eligible = [
                entry for entry in entries if entry["_fits_role"] and not entry["_is_existing"]
            ]
            preferred_eligible = [entry for entry in eligible if entry["_is_preferred"]]
            selected = (preferred_eligible or eligible or [None])[0]
            for entry in entries:
                if entry["_is_existing"]:
                    entry["recommendation_status"] = "already_selected_by_user"
                elif not entry["_fits_role"]:
                    entry["recommendation_status"] = "requires_user_review"
                elif entry is selected:
                    entry["recommendation_status"] = "recommended"
                else:
                    entry["recommendation_status"] = "alternative"
                entry.pop("_fits_role")
                entry.pop("_is_existing")
                entry.pop("_is_preferred")
                for check in package_checks:
                    if check.get("package") == entry["package"]:
                        check["status"] = entry["recommendation_status"]
                        check["recommendation_status"] = entry["recommendation_status"]

        stack_doc_policy = {
            "analytics": (
                ["introduction-to-r", "r-data-import-export"],
                "R data objects vectors import export connections",
            ),
            "api": (
                ["r-installation-administration", "writing-r-extensions"],
                "R installation libraries packages system requirements",
            ),
            "dashboard": (
                ["r-installation-administration"],
                "R installation runtime libraries environment",
            ),
            "package": (
                ["writing-r-extensions"],
                "package DESCRIPTION namespace dependencies documentation tests",
            ),
            "etl": (
                ["r-data-import-export", "r-installation-administration"],
                "data import export connections files encodings installation",
            ),
            "ml": (
                ["introduction-to-r"],
                "R objects functions data frames statistical models",
            ),
            "other": (
                ["introduction-to-r"],
                "R objects functions data structures programming",
            ),
        }
        manuals, documentation_query = stack_doc_policy[resolved_type]
        documentation_result = await self.search_r_documentation(
            documentation_query, manuals=manuals, limit=2
        )
        documentation = {
            "status": documentation_result.get("status", "index_unavailable"),
            "references": documentation_result.get("results", []),
            "warning": documentation_result.get("warning"),
            "limitations": [
                "The manuals can support R runtime, package and data-handling guidance only.",
                "They do not establish claims about unrelated third-party products.",
                "No package installation or transitive compatibility graph is tested.",
            ],
        }

        unique_sources = []
        seen_sources = set()
        for source in sources:
            if not isinstance(source, dict):
                continue
            key = (source.get("source_url"), source.get("checked_at"))
            if key not in seen_sources:
                seen_sources.add(key)
                unique_sources.append(source)

        target_notes = {
            None: ["Choose an explicit deployment target before finalizing operational controls."],
            "local": ["Keep secrets outside source files and record the R/package environment."],
            "docker": [
                "Use a minimal image, a non-root runtime, pinned dependencies, and "
                "runtime-injected secrets; do not bake credentials into image layers."
            ],
            "cloud": [
                "Verify identity, network exposure, secret storage, scaling limits, logging, "
                "and backup/retention controls for the selected provider."
            ],
            "on_premises": [
                "Verify identity integration, patch ownership, network boundaries, secret "
                "storage, backup, and recovery procedures."
            ],
        }
        if resolved_type == "api":
            unknowns_for_api = (
                "Review the metadata-matched API framework candidates and confirm one "
                "fits the request contract; no curated API workflow template exists."
            )
        else:
            unknowns_for_api = None
        unknowns = [
            "Target R version and whether current repository versions meet the project "
            "support policy.",
            "Data size, concurrency, latency, and availability requirements.",
            "Authentication, authorization, data sensitivity, and retention requirements.",
            "Whether optional integrations and deployment components are approved for this "
            "project.",
        ]
        if resolved_type in ("api", "etl"):
            unknowns.append(
                "Database engine/dialect, transaction policy, and credential owner, if a "
                "database is used."
            )
        if resolved_type == "ml":
            unknowns.append(
                "Model family, evaluation metric, data-splitting policy, and artifact lifecycle."
            )
        if unknowns_for_api:
            unknowns.insert(0, unknowns_for_api)
        if type_basis == "unresolved":
            unknowns.insert(
                0,
                "Project type is unresolved; provide project_type to select a workflow profile.",
            )

        return {
            "tool": "recommend_technology_stack",
            "recommendation_status": "provisional",
            "project_type": {"value": resolved_type, "basis": type_basis},
            "recommended_architecture": {
                "pattern": plan["pattern"],
                "components": plan["components"],
                "basis": (
                    "deterministic workflow profile; validate against the supplied requirements"
                ),
            },
            "stack": {
                "r_packages_by_role": [
                    {"role": role, "packages": packages} for role, packages in grouped.items()
                ],
                "complementary_technologies": {
                    "by_role": [
                        {
                            "role": "R runtime",
                            "technologies": [
                                {
                                    "name": "R",
                                    "basis": "project scope",
                                    "version": None,
                                }
                            ],
                        },
                        {
                            "role": "user-selected existing technologies; role not inferred",
                            "technologies": inputs["existing_stack"],
                        },
                        {
                            "role": "user preferences; not independently verified",
                            "technologies": [
                                {"kind": "preferred", "name": name}
                                for name in inputs["preferences"]["prefer"]
                            ]
                            + [
                                {"kind": "excluded", "name": name}
                                for name in inputs["preferences"]["exclude"]
                            ],
                        },
                    ],
                    "user_selected_existing_stack": inputs["existing_stack"],
                    "user_preferences": inputs["preferences"],
                    "additional_named_technology_recommendations": [],
                    "note": (
                        "No complementary product is named without project-specific "
                        "evidence and verification."
                    ),
                    "package_selection_policy": (
                        "At most one metadata-matched package is recommended per role; "
                        "other matching packages are alternatives."
                    ),
                },
            },
            "package_checks": package_checks,
            "package_discovery": discovery,
            "dependencies": {
                "by_package": dependencies,
                # Preserve the original field for existing MCP clients. New
                # clients should use the explicit runtime/build-time groups.
                "required_fields": ["Depends", "Imports", "LinkingTo"],
                "runtime_required_fields": ["Depends", "Imports"],
                "build_time_fields": ["LinkingTo"],
                "optional_fields": ["Suggests", "Enhances"],
                "limitations": (
                    "Direct repository metadata only; not a solved or transitive dependency graph."
                ),
            },
            "compatibility": {
                "r_version": None,
                "claims": [],
                "limitation": (
                    "No target R version was supplied; package metadata does not establish "
                    "compatibility with the user's installed environment."
                ),
            },
            "alternatives_and_tradeoffs": plan["alternatives"],
            "security_maintenance_deployment": {
                "security": [
                    "Keep credentials in an approved runtime secret store.",
                    "Validate inputs at service boundaries and use least-privilege data access.",
                ],
                "maintenance": [
                    "Review package metadata and direct dependencies before adoption.",
                    "Pin the project environment after choosing a supported R version.",
                ],
                "deployment_target": inputs["deployment_target"],
                "deployment_considerations": target_notes[inputs["deployment_target"]],
            },
            "suggested_implementation_sequence": plan["sequence"],
            "sources": unique_sources,
            "official_r_documentation": documentation,
            "verification_status": "partial",
            "verification_notes": [
                "Architecture and trade-offs are deterministic heuristics, not "
                "provider-verified facts.",
                "A package is recommended only when current CRAN metadata is available and "
                "its title or description matches its workflow role.",
                "Package versions describe repository metadata at checked_at; they are "
                "not installed versions or compatibility guarantees.",
                "User-selected complementary technologies are preserved but not "
                "independently verified by this tool.",
            ],
            "user_inputs_preserved": {
                "objective": inputs["objective"],
                "requirements": inputs["requirements"],
                "existing_stack": inputs["existing_stack"],
                "preferences": inputs["preferences"],
            },
            "unknowns_requiring_user_decisions": unknowns,
            "not_executed": True,
        }

    # Consolidated MCP surface. Each method routes to the existing operations so that
    # provenance and failure semantics stay identical to the legacy tools.

    async def get_package(
        self,
        package,
        repository="cran",
        bioc_version=None,
        include=None,
        verify_archive=False,
        resolve_repositories=False,
        revision=None,
    ):
        include = list(dict.fromkeys(include or ["metadata"]))
        unknown = set(include) - set(PACKAGE_SECTIONS)
        if not include or unknown:
            raise KnowledgeError(
                "invalid_input", f"include must name sections from: {', '.join(PACKAGE_SECTIONS)}"
            )
        if repository == "all" and "agent_guidance" in include:
            raise KnowledgeError(
                "invalid_input",
                "agent_guidance needs one repository so the package identity is unique",
            )
        if "agent_guidance" in include and not revision:
            raise KnowledgeError(
                "invalid_input", "agent_guidance needs revision (a branch, tag or commit ref)"
            )
        if revision and "agent_guidance" not in include:
            raise KnowledgeError("invalid_input", "revision is used only with agent_guidance")
        package_name(package)
        operations = {
            "metadata": lambda: self.get_package_info(
                package, repository, bioc_version, verify_archive
            ),
            "dependencies": lambda: self.get_dependencies(
                package, repository, bioc_version, resolve_repositories
            ),
            "vignettes": lambda: self.get_package_vignettes(package, repository, bioc_version),
            "agent_guidance": lambda: self.get_package_agent_guidance(
                package, revision, repository, bioc_version
            ),
        }

        async def section(name):
            try:
                return await operations[name]()
            except KnowledgeError as exc:
                return failure(exc, package, repository, bioc_version)

        results = dict(zip(include, await asyncio.gather(*map(section, include)), strict=True))
        errors = [
            {"section": name, "error": result["error"]}
            for name, result in results.items()
            if "error" in result
        ]
        failed = [
            name
            for name, result in results.items()
            if result.get("verification_status") == "failed"
        ]
        status = (
            "failed"
            if len(failed) == len(results)
            else "partial"
            if failed or any(r.get("verification_status") == "partial" for r in results.values())
            else "verified"
        )
        sources = _unique_sources(
            source for result in results.values() for source in result.get("sources", [])
        )
        first = next(iter(results.values()))
        return {
            "package": package,
            "repository": repository,
            "package_version": first.get("package_version"),
            "bioc_version": first.get("bioc_version", bioc_version),
            "sections": results,
            "errors": errors,
            "source_url": first.get("source_url"),
            "checked_at": max(
                (s["checked_at"] for s in sources if s.get("checked_at")), default=None
            ),
            "verification_status": status,
            "sources": sources,
        }

    async def get_versioned_function_docs(
        self,
        package,
        function,
        offset=0,
        repository="cran",
        bioc_version=None,
        package_version=None,
    ):
        """Return Rd only for the selected version; never substitute the current one."""
        if package_version is not None:
            if repository == "all":
                raise KnowledgeError(
                    "invalid_input", "package_version needs one repository, not all"
                )
            info = await self.get_package_info(package, repository, bioc_version, False)
            if "error" in info:
                return info
            if version_parts(package_version) != version_parts(info["package_version"]):
                error = KnowledgeError(
                    "requested_version_unavailable",
                    "Only the selected repository's current source documentation is available; "
                    "the requested version was not substituted.",
                    info.get("source_url"),
                )
                return {
                    **failure(error, package, repository, info.get("bioc_version")),
                    "requested_package_version": package_version,
                    "available_package_version": info["package_version"],
                    "sources": info.get("sources", []),
                }
        result = await self.get_function_docs(package, function, offset, repository, bioc_version)
        resolved = result.get("package_version") or result.get("error", {}).get(
            "resolved_package_version"
        )
        if package_version is not None and resolved is not None:
            if version_parts(package_version) != version_parts(resolved):
                error = KnowledgeError(
                    "requested_version_unavailable",
                    "Package version changed during resolution.",
                    result.get("source_url"),
                    related_sources=result.get("sources", []),
                    details={
                        "requested_package_version": package_version,
                        "available_package_version": resolved,
                    },
                )
                return failure(error, package, repository, result.get("bioc_version"))
        if result.get("error", {}).get("code") == "docs_not_found":
            result["requested_package_version"] = package_version
            result["error"]["requested_package_version"] = package_version
        return result

    async def check_r_compatibility(
        self, r_version, package=None, repository="cran", bioc_version=None
    ):
        if repository not in ("cran", "bioconductor"):
            raise KnowledgeError("invalid_input", "repository must be cran or bioconductor")
        if package is None:
            if repository != "bioconductor":
                raise KnowledgeError(
                    "invalid_input",
                    "Without package, only the Bioconductor release map can be checked",
                )
            return await self.get_bioconductor_version(r_version)
        if repository == "bioconductor":
            return await self.check_package_compatibility(package, r_version, bioc_version)
        if bioc_version is not None:
            raise KnowledgeError("invalid_input", "bioc_version is only applicable to Bioconductor")
        return await self.check_cran_compatibility(package, r_version)

    async def check_cran_compatibility(self, package, r_version):
        """Check the current CRAN record's direct R and dependency constraints."""
        r_minor(r_version)
        package_name(package)
        cran = await self.provider("cran")
        record, artifact = await cran.current(package)
        warnings = [
            "Only the current CRAN version is checked; an older R may need an archived version, "
            "which this server does not substitute.",
        ]
        statuses = []
        r_constraints = []
        for token in record.get("Depends", "").split(","):
            match = R_CONSTRAINT.fullmatch(token)
            if match:
                status = r_constraint_status(r_version, *match.groups())
                statuses.append(status)
                r_constraints.append({"constraint": token.strip(), "satisfied": status})
        deps = await self.resolve_dependencies(
            {k: record.get(k, "") for k in ("Depends", "Imports", "LinkingTo")}
        )
        for dep in deps:
            if dep["resolution"] == "r_runtime":
                continue
            if dep["resolution"] != "found":
                statuses.append(None)
                warnings.append(
                    f"Dependency {dep['package']} is not in the CRAN index "
                    "(it may come from Bioconductor or another repository)"
                )
                continue
            candidate = dep["candidates"][0]
            if not candidate["constraint_satisfied"]:
                statuses.append(False)
                warnings.append(f"Current CRAN dependency does not satisfy {dep['constraint']}")
            for token in candidate["r_constraints"].split(","):
                match = R_CONSTRAINT.fullmatch(token)
                if match:
                    status = r_constraint_status(r_version, *match.groups())
                    statuses.append(status)
                    if status is False:
                        warnings.append(f"Dependency {dep['package']} requires {token.strip()}")
        if record.get("NeedsCompilation", "").strip().casefold() == "yes":
            warnings.append(
                "Package needs compilation; toolchain and system libraries are unchecked"
            )
        if any(status is False for status in statuses):
            compatibility = "incompatible"
        elif any(status is None for status in statuses):
            compatibility = "unknown"
            warnings.append(
                "Some constraints could not be decided (unresolved origin, or a patch-level "
                "requirement for an R minor version)"
            )
        else:
            compatibility = "metadata_compatible"
        result = self.enrich(
            {
                "package": package,
                "package_version": record["Version"],
                "latest_cran_version": record["Version"],
                "sources": [artifact.provenance()],
                "r_version": r_version,
                "r_constraints": r_constraints,
                "resolved_dependencies": deps,
            },
            cran,
        )
        result.update(
            compatible={"incompatible": False, "unknown": None}.get(compatibility, True),
            compatibility_status=compatibility,
            compatibility_scope=(
                "Current CRAN record's R constraint and direct required dependencies; "
                "not a transitive solver or installation test"
            ),
            warnings=warnings
            + ["R/platform/system libraries and the installed environment were not inspected"],
        )
        return result

    async def get_framework_docs(
        self,
        framework,
        topic,
        version=None,
        question=None,
        operating_system=None,
        r_version=None,
        project_type=None,
    ):
        if framework not in ("shiny", "positron", "quarto"):
            raise KnowledgeError("invalid_input", "framework must be shiny, positron or quarto")
        positron_only = {
            "operating_system": operating_system,
            "r_version": r_version,
            "project_type": project_type,
        }
        misplaced = [
            name for name, value in positron_only.items() if value and framework != "positron"
        ]
        if question and framework != "shiny":
            misplaced.append("question")
        if misplaced:
            raise KnowledgeError(
                "invalid_input", f"{', '.join(misplaced)} not applicable to {framework}"
            )
        if framework == "shiny":
            if topic not in FRAMEWORK_DOCS["shiny"]:
                raise KnowledgeError(
                    "unsupported_topic",
                    "Unsupported topic; choose one of: "
                    + ", ".join(sorted(FRAMEWORK_DOCS["shiny"])),
                )
            result = await self.explain_shiny_reactivity(topic, question)
            if version:
                result["requested_version"] = version
                result["version_warning"] = (
                    "Current official Shiny docs are not pinned to the requested version."
                )
            return result
        if framework == "positron":
            return await self.get_positron_guidance(
                topic, version, operating_system, r_version, project_type
            )
        return await self.get_quarto_docs(topic, version)

    async def get_workflow(
        self, scenario, packages=None, r_version=None, bioc_version=None, package_versions=None
    ):
        if scenario in VISUALIZATION_WORKFLOWS:
            if packages or r_version or bioc_version:
                raise KnowledgeError(
                    "invalid_input",
                    "Visualization scenarios accept only package_versions",
                )
            return await self.get_visualization_workflow(scenario, package_versions)
        if package_versions:
            raise KnowledgeError(
                "invalid_input", "package_versions applies only to visualization scenarios"
            )
        return await self.get_r_workflow_guidance(scenario, packages, r_version, bioc_version)

    async def analyze_r_source(
        self,
        kind,
        source=None,
        files=None,
        schemas=None,
        package_versions=None,
        renv_lock=None,
        document_type=None,
        project_config=None,
        quarto_version=None,
        r_version=None,
        dependencies=None,
        shiny_version=None,
    ):
        if kind not in SOURCE_ANALYZERS:
            raise KnowledgeError(
                "invalid_input", f"kind must be one of: {', '.join(SOURCE_ANALYZERS)}"
            )
        allowed_schemas, allowed_options = SOURCE_ANALYZERS[kind]
        supplied = {
            "files": files,
            "package_versions": package_versions,
            "renv_lock": renv_lock,
            "document_type": document_type,
            "project_config": project_config,
            "quarto_version": quarto_version,
            "r_version": r_version,
            "dependencies": dependencies,
            "shiny_version": shiny_version,
        }
        misplaced = sorted(
            name
            for name, value in supplied.items()
            if value is not None and name not in allowed_options
        )
        schemas = schemas or {}
        if not isinstance(schemas, dict):
            raise KnowledgeError("invalid_input", "schemas must be a mapping")
        misplaced += sorted(f"schemas.{name}" for name in set(schemas) - set(allowed_schemas))
        if misplaced:
            # Reject rather than silently ignore inputs the selected analyzer cannot use.
            raise KnowledgeError(
                "invalid_input", f"Not applicable to kind={kind}: {', '.join(misplaced)}"
            )
        if kind != "shiny" and source is None:
            raise KnowledgeError("invalid_input", f"kind={kind} needs source")
        if kind == "shiny":
            return await self.analyze_shiny_app(source, files, shiny_version)
        if kind == "quarto":
            return await self.analyze_quarto_document(
                source, project_config, quarto_version, r_version, dependencies
            )
        method = {
            "ggplot": self.analyze_ggplot_code,
            "ggraph": self.analyze_ggraph_code,
            "tidyr": self.analyze_tidyr_pipeline,
            "ggplotly": self.analyze_ggplotly_compatibility,
            "knitr": self.analyze_knitr_chunks,
        }[kind]
        keyword = {name: schemas.get(name) for name in allowed_schemas}
        keyword = {SCHEMA_ARGUMENTS[name]: value for name, value in keyword.items()}
        if kind == "knitr":
            keyword["document_type"] = document_type
        return await method(
            source, **keyword, package_versions=package_versions, renv_lock=renv_lock
        )

    async def analyze_r_project(self, files, file_manifest=None):
        result = await self.analyze_r_workspace(files)
        quarto = None
        if isinstance(files, dict) and "_quarto.yml" in files:
            manifest = sorted(set(files) | set(file_manifest or []))
            quarto = await self.analyze_quarto_project(
                files["_quarto.yml"], files.get("_metadata.yml"), manifest
            )
        elif file_manifest:
            raise KnowledgeError(
                "invalid_input", "file_manifest is used only when _quarto.yml is supplied"
            )
        return {**result, "quarto_project": quarto}

    async def check_package_version(self, package, installed_version):
        provider = await self.provider("cran")
        return self.enrich(
            await provider.check_package_version(package, installed_version), provider
        )

    async def get_bioconductor_version(self, r_version):
        result = await self.releases.for_r(r_version)
        result.update(
            source_url=result["sources"][0]["source_url"],
            checked_at=result["sources"][0]["checked_at"],
        )
        return result

    async def resolve_dependencies(self, dependencies, bioc=None):
        """Resolve direct dependency origins in CRAN and an optional Bioconductor release."""
        bioc_records = (await bioc.index())[0] if bioc is not None else {}
        cran = await self.provider("cran")
        cran_records, cran_source = await cran.index()
        runtime = {
            "R",
            "base",
            "compiler",
            "datasets",
            "graphics",
            "grDevices",
            "grid",
            "methods",
            "parallel",
            "splines",
            "stats",
            "stats4",
            "tcltk",
            "tools",
            "utils",
        }
        resolved = []
        for field, raw in dependencies.items():
            for token in filter(None, (s.strip() for s in raw.split(","))):
                match = re.fullmatch(
                    r"([A-Za-z][A-Za-z0-9.]*)\s*(?:\((>=|<=|==|!=|>|<)\s*([0-9][0-9.-]*)\))?", token
                )
                if not match:
                    raise KnowledgeError("invalid_source", "Unsupported dependency constraint")
                name, operator, required = match.groups()
                candidates = []
                for records, repository in (
                    (cran_records, "cran"),
                    (bioc_records, "bioconductor"),
                ):
                    if name not in records:
                        continue
                    record = records[name]
                    source = (
                        cran_source if repository == "cran" else bioc._sources[record["_category"]]
                    )
                    candidates.append(
                        {
                            "package": name,
                            "repository": repository,
                            "package_version": record["Version"],
                            "bioc_version": bioc.bioc_version
                            if repository == "bioconductor"
                            else None,
                            "r_constraints": record.get("Depends", ""),
                            **source.provenance(),
                            "constraint_satisfied": satisfies(
                                record["Version"], operator, required
                            ),
                        }
                    )
                resolved.append(
                    {
                        "package": name,
                        "field": field,
                        "constraint": token,
                        "operator": operator,
                        "required_version": required,
                        "resolution": "r_runtime"
                        if name in runtime
                        else "found"
                        if len(candidates) == 1
                        else "ambiguous"
                        if candidates
                        else "not_found",
                        "candidates": candidates,
                    }
                )
                if len(resolved) > 250:
                    raise KnowledgeError("response_too_large", "More than 250 direct dependencies")
        return resolved

    async def check_package_compatibility(self, package, r_version, bioc_version=None):
        minor = r_minor(r_version)
        package_name(package)
        if bioc_version is None:
            mapping = await self.releases.for_r(r_version)
            bioc_version = mapping["recommended_bioc_version"]
            if bioc_version is None:
                raise KnowledgeError(
                    "no_compatible_release",
                    "No released Bioconductor maps to this R version",
                    mapping["sources"][0]["source_url"],
                )
        bioc = await self.provider("bioconductor", bioc_version)
        record, artifact = await bioc.current(package)
        warnings = []
        compatible = minor == bioc.release.r_version
        if not compatible:
            warnings.append(f"Selected Bioconductor release requires R {bioc.release.r_version}.x")
        r_constraints = []
        for token in record.get("Depends", "").split(","):
            match = re.fullmatch(r"\s*R\s*\((>=|<=|==|!=|>|<)\s*([0-9][0-9.-]*)\)\s*", token)
            if match:
                passed = satisfies(r_version, *match.groups())
                compatible = compatible and passed
                r_constraints.append({"constraint": token.strip(), "satisfied": passed})
        deps = await self.resolve_dependencies(
            {k: record.get(k, "") for k in ("Depends", "Imports", "LinkingTo")}, bioc
        )
        uncertain = False
        for dep in deps:
            if dep["resolution"] == "r_runtime":
                continue
            if dep["resolution"] != "found":
                uncertain = True
                warnings.append(
                    f"Dependency {dep['package']} has {dep['resolution']} repository resolution"
                )
            elif not dep["candidates"][0]["constraint_satisfied"]:
                compatible = False
                warnings.append(f"Available dependency does not satisfy {dep['constraint']}")
            else:
                for token in dep["candidates"][0]["r_constraints"].split(","):
                    match = re.fullmatch(
                        r"\s*R\s*\((>=|<=|==|!=|>|<)\s*([0-9][0-9.-]*)\)\s*", token
                    )
                    if match and not satisfies(r_version, *match.groups()):
                        compatible = False
                        warnings.append(f"Dependency {dep['package']} requires {token.strip()}")
        result = self.enrich(
            {
                "package": package,
                "package_version": record["Version"],
                "sources": [artifact.provenance(), *(await self.dependency_sources(bioc))],
                "r_version": r_version,
                "r_constraints": r_constraints,
                "resolved_dependencies": deps,
            },
            bioc,
        )
        result["compatible"] = False if not compatible else None if uncertain else True
        result["compatibility_status"] = (
            "incompatible" if not compatible else "unknown" if uncertain else "metadata_compatible"
        )
        result["compatibility_scope"] = (
            "Official R/release mapping and direct required dependency constraints; "
            "not a transitive solver or installation test"
        )
        result["warnings"] = [
            w for w in result["warnings"] if not w.startswith("R version not supplied")
        ]
        result["warnings"] += warnings + [
            "R/platform/system libraries and the installed environment were not inspected"
        ]
        return result


def satisfies(version, operator, required):
    if operator is None:
        return True
    actual, expected = version_parts(version), version_parts(required)
    return {
        ">=": actual >= expected,
        "<=": actual <= expected,
        "==": actual == expected,
        "!=": actual != expected,
        ">": actual > expected,
        "<": actual < expected,
    }[operator]


def r_constraint_status(r_version, operator, required):
    """Decide an `R (op version)` bound; None when an R minor series straddles it."""
    actual = [int(part) for part in r_version.split(".")]
    expected = [int(part) for part in re.split(r"[.-]", required)]
    if len(actual) == 2 and len(expected) >= 3 and expected[:2] == actual:
        # "4.1" means some 4.1.x release; only bounds at patch 0 are decidable.
        if all(part == 0 for part in expected[2:]):
            return {">=": True, "<": False}.get(operator)
        return None
    return satisfies(r_version, operator, required)


def _unique_sources(sources):
    unique, seen = [], set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        key = (source.get("source_url"), source.get("checked_at"))
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


def compact_result(result: dict) -> dict:
    """Drop repeated static notes and hoist nested source lists into one deduplicated list.

    Nested items keep their own source_url/checked_at; full mode returns everything.
    """
    hoisted = []

    def walk(value, depth):
        if isinstance(value, dict):
            output = {}
            for key, item in value.items():
                if key in COMPACT_DROPPED_KEYS:
                    continue
                if key == "sources" and depth > 0 and isinstance(item, list):
                    hoisted.extend(item)
                    continue
                output[key] = walk(item, depth + 1)
            return output
        if isinstance(value, list):
            return [walk(item, depth + 1) for item in value]
        return value

    compacted = walk(result, 0)
    if hoisted or "sources" in compacted:
        compacted["sources"] = _unique_sources([*compacted.get("sources", []), *hoisted])
    compacted["response_mode"] = "compact"
    return compacted


def _encoded_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode())


def _long_strings(value, path=""):
    """Yield (container, key, path) for string leaves that can be shortened."""
    items = value.items() if isinstance(value, dict) else enumerate(value)
    for key, item in items:
        item_path = f"{path}[{key}]" if isinstance(value, list) else f"{path}.{key}".lstrip(".")
        if isinstance(item, str):
            if len(item) > MIN_TRUNCATED_CHARS:
                yield value, key, item_path
        elif isinstance(item, (dict, list)):
            yield from _long_strings(item, item_path)


def fit_result(result: dict, limit: int = MAX_RESULT_BYTES) -> dict:
    """Shorten the longest text fields to fit the output limit, recording every cut.

    Identity, version, status and provenance fields are short and stay intact; when
    shortening text cannot fit the limit the caller still gets response_too_large.
    """
    size = _encoded_size(result)
    if size <= limit:
        return result
    if not isinstance(result, dict):
        raise KnowledgeError(
            "response_too_large", f"Result exceeds {limit} bytes; narrow the query"
        )
    result = copy.deepcopy(result)
    candidates = sorted(_long_strings(result), key=lambda e: len(e[0][e[1]]), reverse=True)
    truncated_fields = []
    for container, key, path in candidates:
        if size <= limit:
            break
        text = container[key]
        # Every removed character saves at least one encoded byte.
        keep = max(MIN_TRUNCATED_CHARS, len(text) - (size - limit) - TRUNCATION_RESERVE)
        container[key] = text[:keep] + TRUNCATION_MARKER
        truncated_fields.append(
            {"field": path, "original_characters": len(text), "returned_characters": keep}
        )
        result["output_truncation"] = {
            "truncated": True,
            "limit_bytes": limit,
            "fields": truncated_fields,
            "note": "Text was shortened by the server output limit; it was not summarized.",
        }
        size = _encoded_size(result)
    if size > limit:
        raise KnowledgeError(
            "response_too_large", f"Result exceeds {limit} bytes; narrow the query"
        )
    return result


async def bounded(operation: Awaitable[dict], compact: bool = False, **context) -> dict:
    """Keep a future transport or integration free of implementation-specific exceptions."""
    try:
        async with asyncio.timeout(60):
            result = await operation
        if compact and isinstance(result, dict):
            result = compact_result(result)
        return fit_result(result)
    except TimeoutError:
        error = KnowledgeError("timeout", "Tool deadline exceeded")
    except UnicodeError:
        error = KnowledgeError("invalid_input", "Input or result contains invalid Unicode")
    except RecursionError:
        error = KnowledgeError("input_too_complex", "Input nesting exceeds safe processing limits")
    except KnowledgeError as exc:
        error = exc
    except Exception as exc:
        log_internal_failure(logging.getLogger(__name__), awaitable_operation_id(operation), exc)
        error = KnowledgeError(
            "internal_error", "The tool could not complete due to an internal error"
        )
    return failure(error, **context)
