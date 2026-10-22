"""Bioconductor's official, dynamically checked R/release map (also used by BiocManager)."""

import re
from dataclasses import dataclass

import yaml

from .errors import KnowledgeError
from .http import Artifact, BioconductorHTTP, version_parts

BIOC_VERSION = re.compile(r"[0-9]+\.[0-9]+\Z")


def r_minor(value: str) -> str:
    if not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", value):
        raise KnowledgeError("invalid_input", "Use a numeric R version, e.g. 4.4.2")
    return ".".join(str(int(x)) for x in value.split(".")[:2])


@dataclass(frozen=True)
class Release:
    version: str
    r_version: str
    channel: str
    config: Artifact


class BioconductorReleases:
    def __init__(self, http: BioconductorHTTP):
        self.http = http

    async def catalog(self) -> tuple[dict[str, Release], Artifact]:
        artifact = await self.http.fetch("/config.yaml")
        try:
            config = yaml.safe_load(artifact.body)
            mapping = config["r_ver_for_bioc_ver"]
            stable, devel = config["release_version"], config["devel_version"]
            if not isinstance(mapping, dict) or not all(
                isinstance(v, str) and BIOC_VERSION.fullmatch(v) for v in (stable, devel)
            ):
                raise ValueError("Malformed release map")
            releases = {}
            for version, r in mapping.items():
                if not isinstance(version, str) or not BIOC_VERSION.fullmatch(version):
                    raise ValueError("Malformed release version")
                channel = (
                    "release"
                    if version == stable
                    else "devel"
                    if version == devel
                    else "historical"
                )
                releases[version] = Release(version, r_minor(r), channel, artifact)
            if stable not in releases or devel not in releases or stable == devel:
                raise ValueError("Missing release/devel mapping")
            return releases, artifact
        except (yaml.YAMLError, ValueError, TypeError, KeyError, KnowledgeError) as exc:
            raise KnowledgeError(
                "invalid_source", "Invalid Bioconductor release map", artifact.source_url
            ) from exc

    async def resolve(self, requested: str | None = None) -> Release:
        requested = requested or "release"
        if requested not in ("release", "stable", "devel") and not BIOC_VERSION.fullmatch(
            requested
        ):
            raise KnowledgeError(
                "invalid_input", "Use release, stable, devel or a numeric Bioconductor release"
            )
        releases, artifact = await self.catalog()
        if requested in ("release", "stable", "devel"):
            channel = "release" if requested == "stable" else requested
            return next(r for r in releases.values() if r.channel == channel)
        if requested not in releases:
            raise KnowledgeError(
                "release_not_found", "Release is absent from the official map", artifact.source_url
            )
        return releases[requested]

    async def for_r(self, r_version: str) -> dict:
        minor = r_minor(r_version)
        releases, artifact = await self.catalog()
        matches = sorted(
            (r for r in releases.values() if r.r_version == minor),
            key=lambda r: version_parts(r.version),
        )
        stable = [r for r in matches if r.channel != "devel"]
        recommended = stable[-1].version if stable else None
        return {
            "package": None,
            "repository": "bioconductor",
            "package_version": None,
            "bioc_version": recommended,
            "r_version": r_version,
            "releases": [
                {"bioc_version": r.version, "r_version": r.r_version, "channel": r.channel}
                for r in matches
            ],
            "recommended_bioc_version": recommended,
            "verification_status": "verified",
            "sources": [artifact.provenance()],
            "warnings": (
                ["No released Bioconductor version is mapped to this R version"]
                if not stable
                else []
            ),
        }
