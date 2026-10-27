"""docs_not_found reports the verified Rd alias index; synthetic archives mirror D01 packages."""

import gzip
import json

import httpx
import pytest
from conftest import archive
from mcp.shared.memory import create_connected_server_and_client_session

from cran_knowledge_mcp.http import INDEX, CranHTTP
from cran_knowledge_mcp.parsers import FULL_ALIAS_LIST_LIMIT, alias_hints
from cran_knowledge_mcp.server import create_server
from cran_knowledge_mcp.service import KnowledgeService, bounded

# Real alias names of termr 1.0.1 (a subset above the 30-alias threshold); the Rd bodies are fake.
TERMR_ALIASES = [
    "App",
    "Widget",
    "ScrollView",
    "Select",
    "Checkbox",
    "OptionList",
    "DataTable",
    "KeyEvent",
    "app",
    "bind",
    "button",
    "checkbox",
    "computed",
    "data_table",
    "dropdown",
    "input",
    "label",
    "on",
    "option_list",
    "panel",
    "reactive",
    "run",
    "run_process",
    "scroll_view",
    "select",
    "signal",
    "tabs",
    "termr",
    "termr-package",
    "test_app",
    "text_area",
    "tree_view",
    "watch",
    "widget",
]
CLIMENU_ALIASES = ["checkbox", "menu", "select"]


def _package(name, version, aliases):
    description = f"Package: {name}\nVersion: {version}\nTitle: Synthetic\nEncoding: UTF-8\n"
    files = {f"{name}/DESCRIPTION": description}
    for index, alias in enumerate(aliases):
        files[f"{name}/man/topic{index}.Rd"] = (
            f"\\name{{topic{index}}}\n\\alias{{{alias}}}\n\\title{{Synthetic {alias}}}\n"
            f"\\description{{Fixture for {alias}.}}\n"
        )
    return description, archive(files)


@pytest.fixture
async def d01_service():
    packages = {
        "termr": ("1.0.1", TERMR_ALIASES),
        "climenu": ("0.2.0", CLIMENU_ALIASES),
        "tinypkg": ("1.0", ["only"]),
    }
    routes = {
        INDEX: "\n\n".join(
            f"Package: {name}\nVersion: {version}\nLicense: MIT"
            for name, (version, _) in packages.items()
        ).encode()
    }
    for name, (version, aliases) in packages.items():
        description, tarball = _package(name, version, aliases)
        routes[f"/web/packages/{name}/DESCRIPTION"] = description.encode()
        routes[f"/src/contrib/{name}_{version}.tar.gz"] = tarball

    def handler(request):
        content = routes.get(request.url.path)
        if content is None and request.url.path.endswith("/PACKAGES.gz"):
            plain = routes.get(request.url.path.removesuffix(".gz"))
            content = gzip.compress(plain) if plain is not None else None
        return httpx.Response(404 if content is None else 200, content=content or b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield KnowledgeService(CranHTTP(client))


async def _docs(service, package, function):
    return await bounded(
        service.get_function_docs(package, function), compact=True, package=package
    )


async def test_climenu_documented_aliases_keep_the_success_contract(d01_service):
    for alias in CLIMENU_ALIASES:
        result = await _docs(d01_service, "climenu", alias)
        assert "error" not in result
        assert result["function"] == alias and result["package_version"] == "0.2.0"
        assert {"archive_member", "text", "offset", "total_characters", "next_offset"} <= set(
            result
        )
        assert not {"alias_count", "available_aliases", "closest_aliases"} & set(result)


@pytest.mark.parametrize(
    "missing",
    ["Select", "SELECT", "menu()", "select()", "climenu::menu", "climenu:::select", "nope"],
)
async def test_small_package_lists_every_alias(d01_service, missing):
    result = await _docs(d01_service, "climenu", missing)
    error = result["error"]
    assert result["verification_status"] == "failed"
    assert error["code"] == "docs_not_found"
    assert error["message"] == "No literal Rd alias found in this package version"
    assert error["source_url"].endswith("/src/contrib/climenu_0.2.0.tar.gz")
    assert error["alias_count"] == 3
    assert error["available_aliases"] == CLIMENU_ALIASES
    assert error["alias_list_complete"] is True
    assert "closest_aliases" not in error


@pytest.mark.parametrize(
    "missing", ["scrollview", "SCROLLVIEW", "ScrollView()", "termr::ScrollView", " ScrollView "]
)
async def test_large_package_ranks_case_paren_and_prefix_variants(d01_service, missing):
    error = (await _docs(d01_service, "termr", missing))["error"]
    assert error["code"] == "docs_not_found"
    assert error["alias_count"] == len(TERMR_ALIASES) > FULL_ALIAS_LIST_LIMIT
    assert "available_aliases" not in error and error["alias_list_complete"] is False
    assert error["closest_aliases"][0] == "ScrollView"
    assert len(error["closest_aliases"]) == 10
    assert set(error["closest_aliases"]) <= set(TERMR_ALIASES)  # nothing invented


async def test_unrelated_missing_alias_still_returns_only_real_names(d01_service):
    error = (await _docs(d01_service, "termr", "run_app"))["error"]
    assert "run" in error["closest_aliases"] and "app" in error["closest_aliases"]
    assert set(error["closest_aliases"]) <= set(TERMR_ALIASES)
    assert len(json.dumps(error)) < 1500


async def test_hints_are_bounded_and_skip_unrequestable_names():
    long_name = "x" * 161
    hints = alias_hints("anything", ["ok", long_name, "bad\nname"])
    assert hints["alias_count"] == 3
    assert hints["available_aliases"] == ["ok"] and hints["alias_list_complete"] is False

    many = [f"alias_{index}" for index in range(5000)]
    hints = alias_hints("alias_42x", many)
    assert hints["alias_count"] == 5000 and len(hints["closest_aliases"]) == 10
    assert hints["closest_aliases"][0] == "alias_42"
    boundary = alias_hints("z", [f"a{index}" for index in range(FULL_ALIAS_LIST_LIMIT)])
    assert "available_aliases" in boundary and "closest_aliases" not in boundary
    over = alias_hints("z", [f"a{index}" for index in range(FULL_ALIAS_LIST_LIMIT + 1)])
    assert "closest_aliases" in over and "available_aliases" not in over


async def test_other_docs_errors_do_not_gain_alias_fields(d01_service):
    invalid = await _docs(d01_service, "climenu", "")
    assert invalid["error"]["code"] == "invalid_input"
    missing = await _docs(d01_service, "nosuchpkg", "x")
    assert missing["error"]["code"] == "package_not_found"
    for result in (invalid, missing):
        assert not {"alias_count", "available_aliases", "closest_aliases"} & set(result["error"])


async def test_mcp_tool_returns_hints_as_error_result(d01_service, monkeypatch):
    monkeypatch.setenv("MCP_TOOLSET", "consolidated")
    async with create_connected_server_and_client_session(
        create_server(service=d01_service)
    ) as session:
        missing = await session.call_tool(
            "get_function_docs", {"package": "climenu", "function": "Menu"}
        )
        found = await session.call_tool(
            "get_function_docs", {"package": "climenu", "function": "menu"}
        )
    assert missing.isError is True
    error = missing.structuredContent["error"]
    assert error["code"] == "docs_not_found" and error["available_aliases"] == CLIMENU_ALIASES
    assert json.loads(missing.content[0].text) == missing.structuredContent
    assert found.isError is False and "error" not in found.structuredContent
