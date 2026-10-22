"""Repository router, provenance envelopes and conservative cross-repository checks."""

import asyncio
import re
from collections import OrderedDict
from collections.abc import Awaitable
from datetime import UTC, datetime

from .errors import KnowledgeError
from .http import BioconductorHTTP, CranHTTP, package_name, version_parts
from .providers import BioconductorProvider, CranProvider, PackageRepository
from .providers.bioconductor import CATEGORIES
from .releases import BioconductorReleases, r_minor


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
    def __init__(self, http: CranHTTP, providers: dict[str, PackageRepository] | None = None):
        self.http = http  # Backward-compatible injection point for offline clients/tests.
        self.bioc_http = BioconductorHTTP(http.client)
        self.releases = BioconductorReleases(self.bioc_http)
        self.providers = providers if providers is not None else {"cran": CranProvider(http)}
        self._bioc: OrderedDict[str, BioconductorProvider] = OrderedDict()

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
