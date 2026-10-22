"""Repository router, provenance envelopes and conservative cross-repository checks."""

import asyncio
import json
import re
from collections import OrderedDict
from collections.abc import Awaitable
from datetime import UTC, datetime

from .config import cache_ttl, context7_api_key
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
from .providers.context7 import Context7Provider
from .providers.framework_docs import FrameworkDocsProvider
from .providers.github_agents import GitHubAgentsProvider
from .releases import BioconductorReleases, r_minor
from .visualization_analysis import (
    analyze_ggplot_code,
    analyze_ggplotly_compatibility,
    analyze_ggraph_code,
    analyze_knitr_chunks,
    analyze_tidyr_pipeline,
)

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


def failure(exc: KnowledgeError, package=None, repository=None, bioc_version=None):
    return {
        "package": package,
        "repository": repository,
        "package_version": None,
        "bioc_version": bioc_version,
        "source_url": exc.source_url,
        "checked_at": None,
        "verification_status": "failed",
        "sources": [],
        "error": {
            "code": exc.code,
            "message": str(exc),
            "source_url": exc.source_url,
            "attempted_at": datetime.now(UTC).isoformat(),
        },
    }


class KnowledgeService:
    def __init__(
        self,
        http: CranHTTP,
        providers: dict[str, PackageRepository] | None = None,
        agents_provider: GitHubAgentsProvider | None = None,
        context7_provider: Context7Provider | None = None,
        framework_docs_provider: FrameworkDocsProvider | None = None,
    ):
        self.http = http  # Backward-compatible injection point for offline clients/tests.
        self.bioc_http = BioconductorHTTP(http.client)
        self.releases = BioconductorReleases(self.bioc_http)
        self.providers = providers if providers is not None else {"cran": CranProvider(http)}
        self._bioc: OrderedDict[str, BioconductorProvider] = OrderedDict()
        self.agents = agents_provider or GitHubAgentsProvider(http.client, ttl=cache_ttl(3600))
        self.context7 = context7_provider or Context7Provider(
            http.client, context7_api_key(), ttl=cache_ttl(21600)
        )
        self.framework_docs = framework_docs_provider or FrameworkDocsProvider(http.client)

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
            verification_status="verified",
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
        results = [
            await self._one(
                method, package, name, bioc_version if name == "bioconductor" else None, **kwargs
            )
            for name in ("cran", "bioconductor")
        ]
        return self.aggregate(results, package, bioc_version)

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

    async def get_package_info(self, package, repository="cran", bioc_version=None):
        return await self._dispatch("get_package_info", package, repository, bioc_version)

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

    async def get_package_vignettes(self, package, repository="cran", bioc_version=None):
        return await self._dispatch("get_package_vignettes", package, repository, bioc_version)

    async def _external_package_metadata(self, package, repository, bioc_version):
        package_name(package)
        provider = await self.provider(repository, bioc_version)
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

    async def get_context7_docs(self, package, question, repository="cran", bioc_version=None):
        provider, info = await self._external_package_metadata(package, repository, bioc_version)
        return await self.context7.get_context7_docs(
            package,
            info["package_version"],
            info.get("urls"),
            question,
            repository,
            provider.bioc_version,
        )

    async def get_package_knowledge(
        self,
        package,
        repository="cran",
        bioc_version=None,
        question=None,
        revision=None,
    ):
        if repository == "all":
            raise KnowledgeError(
                "invalid_input",
                "Select cran or bioconductor so each knowledge bundle has one package identity",
            )
        provider = await self.provider(repository, bioc_version)
        info = await self._one("get_package_info", package, repository, bioc_version)
        dependencies = await self._one("get_dependencies", package, repository, bioc_version)
        sections = {"package_info": info, "dependencies": dependencies}
        if "error" in info:
            sections["agent_guidance"] = {
                "status": "not_attempted",
                "reason": "package metadata could not be verified",
            }
            sections["context7_docs"] = {
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
            if question:
                try:
                    sections["context7_docs"] = await self.context7.get_context7_docs(
                        package,
                        info["package_version"],
                        info.get("urls"),
                        question,
                        repository,
                        provider.bioc_version,
                    )
                except KnowledgeError as exc:
                    sections["context7_docs"] = failure(
                        exc, package, repository, provider.bioc_version
                    )
            else:
                sections["context7_docs"] = {
                    "status": "not_requested",
                    "reason": "Supply a concrete question to retrieve indexed documentation",
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
        info = await self.get_package_info(canonical, "cran")
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
        info = await self.get_package_info(canonical, "cran")
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
        package_versions = package_versions or {}
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
            if not isinstance(renv_lock, str) or len(renv_lock.encode("utf-8")) > 512 << 10:
                raise KnowledgeError("invalid_input", "renv.lock text is limited to 512 KiB")
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
        result = analyzer(source, **schemas)
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
            info = await self.get_package_info(name, "cran")
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
        analysis = analyze_shiny_source(source=source) if source is not None else None
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
        result = analyze_shiny_source(source=source, files=files)
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
        result = analyze_quarto_source(source, project_config, quarto_version)
        result["r_version"] = r_version
        result["dependencies_supplied"] = dependencies or []
        result["dependency_analysis"] = "caller_supplied_names_unverified"
        return result

    async def analyze_quarto_project(
        self, project_config, metadata_config=None, file_manifest=None
    ):
        return analyze_quarto_config(project_config, metadata_config, file_manifest)

    async def analyze_r_workspace(self, files):
        return analyze_workspace_metadata(files)

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

    async def resolve_dependencies(self, dependencies, bioc):
        bioc_records, _ = await bioc.index()
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
                for records, repository in ((cran_records, "cran"), (bioc_records, "bioconductor")):
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


async def bounded(operation: Awaitable[dict], **context) -> dict:
    """Keep a future transport or integration free of implementation-specific exceptions."""
    import json

    try:
        async with asyncio.timeout(60):
            result = await operation
        if len(json.dumps(result, ensure_ascii=False).encode()) > 60_000:
            raise KnowledgeError(
                "response_too_large", "Result exceeds 60000 bytes; narrow the query"
            )
        return result
    except TimeoutError:
        error = KnowledgeError("timeout", "Tool deadline exceeded")
    except KnowledgeError as exc:
        error = exc
    return failure(error, **context)
