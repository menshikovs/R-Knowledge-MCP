"""Independent repository providers and the extension contract."""

from .bioconductor import BioconductorProvider
from .context7 import Context7Provider
from .cran import CranProvider
from .github_agents import GitHubAgentsProvider
from .protocol import PackageRepository

__all__ = [
    "BioconductorProvider",
    "Context7Provider",
    "CranProvider",
    "GitHubAgentsProvider",
    "PackageRepository",
]
