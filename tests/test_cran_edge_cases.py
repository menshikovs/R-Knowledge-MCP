import hashlib

from conftest import DESCRIPTION, INDEX_TEXT

from cran_knowledge_mcp.http import INDEX
from cran_knowledge_mcp.parsers import description_text
from cran_knowledge_mcp.service import bounded


async def test_recommended_path_variants_do_not_override_canonical_root(service):
    api, routes, _ = service
    routes[INDEX] = (
        INDEX_TEXT + "\nPackage: ExamplePkg\nVersion: 9.0\n"
        "Path: 4.7.0/Recommended\nDepends: R (>= 4.7)\n"
    ).encode()
    result = await api.get_dependencies("ExamplePkg")
    assert result["latest_cran_version"] == "2.10-1"
    assert result["dependencies"]["Depends"] == "R (>= 4.1)"


async def test_duplicate_root_records_rejected(service):
    api, routes, _ = service
    routes[INDEX] = (INDEX_TEXT + "\nPackage: ExamplePkg\nVersion: 9.0\n").encode()
    assert (await bounded(api.get_dependencies("ExamplePkg")))["error"]["code"] == "invalid_source"


async def test_archive_checksum_validation(service):
    api, routes, _ = service
    body = routes["/src/contrib/ExamplePkg_2.10-1.tar.gz"]
    digest = hashlib.md5(body, usedforsecurity=False).hexdigest()
    routes[INDEX] = INDEX_TEXT.replace(
        "Version: 2.10-1", f"Version: 2.10-1\nMD5sum: {digest}"
    ).encode()
    assert "error" not in await bounded(api.get_package_info("ExamplePkg"))
    api.http._cache.clear()
    api.http._bytes = 0
    routes["/src/contrib/ExamplePkg_2.10-1.tar.gz"] = body + b"changed"
    assert (await bounded(api.get_package_info("ExamplePkg")))["error"][
        "code"
    ] == "checksum_mismatch"


def test_latin1_description():
    body = (
        DESCRIPTION.replace("UTF-8", "latin1").replace("Test Author", "Andr\u00e9").encode("latin1")
    )
    assert "Andr\u00e9" in description_text(body)
