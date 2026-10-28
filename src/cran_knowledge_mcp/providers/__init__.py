"""Independent repository providers and the extension contract."""

from .bioconductor import BioconductorProvider
from .cran import CranProvider
from .github_agents import GitHubAgentsProvider
from .protocol import PackageRepository

__all__ = [
    "BioconductorProvider",
    "CranProvider",
    "GitHubAgentsProvider",
    "PackageRepository",
]
