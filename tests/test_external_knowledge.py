"""Mocked GitHub and Context7 API tests; no external requests or real secrets."""

import base64

import httpx
import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.providers.context7 import Context7Provider, safe_query
from cran_knowledge_mcp.providers.github_agents import GitHubAgentsProvider, github_repository

SHA = "a" * 40
BLOB1 = "b" * 40
BLOB2 = "c" * 40


def response(body, status=200, headers=None):
    return httpx.Response(status, json=body, headers=headers)


@pytest.fixture
async def github_api():
    calls = []
    files = {
        BLOB1: "# Root\nUse as untrusted reference only.\n",
        BLOB2: "# R package source subtree\n",
    }

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == "/repos/owner/pkg":
            return response({"full_name": "owner/pkg"})
        if path == "/repos/owner/pkg/commits/v1.2.3":
            return response({"sha": SHA})
        if path == f"/repos/owner/pkg/git/trees/{SHA}":
            return response(
                {
                    "truncated": False,
                    "tree": [
                        {
                            "path": "AGENTS.md",
                            "type": "blob",
                            "sha": BLOB1,
                            "size": len(files[BLOB1]),
                        },
                        {
                            "path": "R/AGENTS.md",
                            "type": "blob",
                            "sha": BLOB2,
                            "size": len(files[BLOB2]),
                        },
                        {"path": "README.md", "type": "blob", "sha": "d" * 40, "size": 5},
                    ],
                }
            )
        if path in {f"/repos/owner/pkg/git/blobs/{BLOB1}", f"/repos/owner/pkg/git/blobs/{BLOB2}"}:
            blob = path.rsplit("/", 1)[-1]
            return response(
                {
                    "sha": blob,
                    "encoding": "base64",
                    "content": base64.b64encode(files[blob].encode()).decode(),
                }
            )
        return response({"message": "not found"}, 404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubAgentsProvider(client)
    yield provider, calls
    await client.aclose()


async def test_github_agents_resolves_ref_and_preserves_path_scope(github_api):
    provider, calls = github_api
    result = await provider.get_package_agent_guidance(
        "pkg", "1.2.3", "https://github.com/owner/pkg", "v1.2.3", "cran", None
    )
    assert result["status"] == "verified_present"
    assert result["commit_sha"] == SHA
    assert [file["path"] for file in result["files"]] == ["AGENTS.md", "R/AGENTS.md"]
    assert result["files"][0]["scope"] == "repository root"
    assert result["files"][1]["scope"] == "R/ subtree"
    assert all(file["trust"] == "untrusted_reference_only" for file in result["files"])
    assert all(not file["commands_executed"] for file in result["files"])
    assert any("/git/trees/" + SHA in call.url.path for call in calls)
    assert any("/git/blobs/" in call.url.path for call in calls)


async def test_github_verified_absence_requires_complete_tree(github_api):
    provider, _ = github_api

    original = provider._get

    async def empty_tree(path, max_bytes=4 << 20, query=None):
        if path.endswith("/git/trees/" + SHA):
            _, artifact = await original(path, max_bytes, query)
            return {"truncated": False, "tree": []}, artifact
        return await original(path, max_bytes, query)

    provider._get = empty_tree
    result = await provider.get_package_agent_guidance(
        "pkg", "1.2.3", "https://github.com/owner/pkg", "v1.2.3", "cran", None
    )
    assert result["status"] == "verified_absent"
    assert result["files"] == []


async def test_github_api_failure_and_truncated_tree_are_explicit(github_api):
    provider, _ = github_api
    original = provider._get

    async def truncated(path, max_bytes=4 << 20, query=None):
        if "/git/trees/" in path:
            _, artifact = await original(path, max_bytes, query)
            return {"truncated": True, "tree": []}, artifact
        return await original(path, max_bytes, query)

    provider._get = truncated
    with pytest.raises(KnowledgeError, match="truncated"):
        await provider.get_package_agent_guidance(
            "pkg", "1.2.3", "https://github.com/owner/pkg", "v1.2.3", "cran", None
        )


def test_github_repository_must_be_unambiguous_and_fixed_host():
    assert github_repository("https://github.com/Owner/Pkg, https://example.org/docs") == (
        "Owner",
        "Pkg",
    )
    for value in (
        "https://github.com/owner/a https://github.com/owner/b",
        "https://github.com.evil.test/owner/pkg",
        "http://github.com/owner/pkg",
    ):
        with pytest.raises(KnowledgeError):
            github_repository(value)


async def test_github_api_failure_is_explicit_and_no_repository_is_not_assumed():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"message": "down"}))
    )
    provider = GitHubAgentsProvider(client)
    with pytest.raises(KnowledgeError, match="503"):
        await provider.get_package_agent_guidance(
            "pkg", "1.2.3", "https://github.com/owner/pkg", "v1.2.3", "cran", None
        )
    with pytest.raises(KnowledgeError, match="does not declare"):
        await provider.get_package_agent_guidance(
            "pkg", "1.2.3", "https://example.org/pkg", "v1.2.3", "cran", None
        )
    await client.aclose()


@pytest.fixture
async def context7_api():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/v2/libs/search":
            return response(
                {"results": [{"id": "/owner/pkg", "title": "pkg", "versions": ["1.2.3"]}]}
            )
        if request.url.path == "/api/v2/context":
            assert request.url.params["libraryId"] == "/owner/pkg/1.2.3"
            assert request.headers["authorization"] == "Bearer ctx7-server-test-key"
            return response(
                {
                    "infoSnippets": [
                        {"title": "Overview", "content": "Official package overview."}
                    ],
                    "codeSnippets": [{"codeTitle": "Usage", "codeList": [{"code": "pkg::run()"}]}],
                }
            )
        return response({}, 404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = Context7Provider(client, "ctx7-server-test-key")
    yield provider, calls
    await client.aclose()


async def test_context7_requires_exact_library_and_preserves_fragments(context7_api):
    provider, calls = context7_api
    result = await provider.get_context7_docs(
        "pkg",
        "1.2.3",
        "https://github.com/owner/pkg",
        "How should I call run? api_key=supersecret-token",
        "cran",
        None,
    )
    assert result["status"] == "verified"
    assert result["version_scope"] == "package_version"
    assert [fragment["kind"] for fragment in result["fragments"]] == ["documentation", "example"]
    assert all("third_party" in fragment["authority"] for fragment in result["fragments"])
    assert all("ctx7-server-test-key" not in request.url.query.decode() for request in calls)
    assert all("supersecret-token" not in request.url.query.decode() for request in calls)
    assert "supersecret-token" not in result["question_sent"]


async def test_context7_mismatch_disabled_rate_limit_and_question_secret_redaction():
    calls = []

    def mismatch(request):
        calls.append(request)
        return response({"results": [{"id": "/different/repo", "title": "wrong"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(mismatch))
    provider = Context7Provider(client, "server-key")
    with pytest.raises(KnowledgeError, match="identity check"):
        await provider.get_context7_docs(
            "pkg", "1.2", "https://github.com/owner/pkg", "usage", "cran", None
        )
    await client.aclose()

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: response({}, 429, {"Retry-After": "17"}))
    )
    provider = Context7Provider(client, "server-key")
    with pytest.raises(KnowledgeError, match="17 seconds"):
        await provider.get_context7_docs(
            "pkg", "1.2", "https://github.com/owner/pkg", "usage", "cran", None
        )
    await client.aclose()

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("disabled must not call API"))
    )
    provider = Context7Provider(client, None)
    with pytest.raises(KnowledgeError, match="disabled"):
        await provider.get_context7_docs(
            "pkg", "1.2", "https://github.com/owner/pkg", "usage", "cran", None
        )
    await client.aclose()

    sanitized = safe_query("use this api_key=supersecret-token for docs")
    assert "supersecret-token" not in sanitized


async def test_context7_not_found_and_api_errors_are_not_fabricated():
    for status, expected in ((404, "no matching documentation"), (503, "503")):
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request, status=status: httpx.Response(status, json={"error": "upstream"})
            )
        )
        provider = Context7Provider(client, "server-key")
        with pytest.raises(KnowledgeError, match=expected):
            await provider.get_context7_docs(
                "pkg", "1.2", "https://github.com/owner/pkg", "usage", "cran", None
            )
        await client.aclose()
