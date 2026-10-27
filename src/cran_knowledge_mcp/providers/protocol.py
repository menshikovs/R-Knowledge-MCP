"""Structural interface: another repository need not inherit either provider."""

from typing import Protocol, runtime_checkable

from ..http import Artifact


@runtime_checkable
class PackageRepository(Protocol):
    repository: str
    bioc_version: str | None

    async def index(self) -> tuple[dict[str, dict[str, str]], Artifact]: ...
    async def current(self, package: str) -> tuple[dict[str, str], Artifact]: ...
    async def search_packages(self, query: str, limit: int = 10, offset: int = 0) -> dict: ...
    async def get_package_info(self, package: str, verify_archive: bool = True) -> dict: ...
    async def get_dependencies(self, package: str) -> dict: ...
    async def get_function_docs(self, package: str, function: str, offset: int = 0) -> dict: ...
    async def get_package_vignettes(self, package: str) -> dict: ...
    async def list_package_functions(
        self,
        package: str,
        query: str | None = None,
        limit: int = 20,
        offset: int = 0,
        package_version: str | None = None,
        snapshot: str | None = None,
    ) -> dict: ...
