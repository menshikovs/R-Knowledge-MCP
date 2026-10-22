from cran_knowledge_mcp.errors import KnowledgeError


class _Docs:
    async def get_docs(self, framework, topic, version=None):
        return {
            "framework": framework,
            "topic": topic,
            "source_url": f"https://docs.invalid/{framework}/{topic}",
            "checked_at": "2026-10-22T00:00:00+00:00",
            "verification_status": "retrieved_official_documentation",
            "text": "fixture",
        }


async def test_reactivity_explanation_keeps_official_provenance(service):
    knowledge, _, _ = service
    knowledge.framework_docs = _Docs()
    result = await knowledge.explain_shiny_reactivity(
        "reactivity", "Why does this recompute?", source="shinyApp(ui, server)"
    )
    assert "dependency graph" in result["explanation"]
    assert result["source_analysis"]["not_executed"]
    assert result["sources"][0]["source_url"] == "https://docs.invalid/shiny/reactivity"


async def test_cross_framework_workflow_uses_selected_topics_and_not_guesses(service):
    knowledge, _, _ = service
    knowledge.framework_docs = _Docs()
    result = await knowledge.get_r_workflow_guidance("quarto_positron")
    assert result["package_knowledge"] == []
    assert [(d["framework"], d["topic"]) for d in result["official_framework_docs"]] == [
        ("positron", "interpreters"),
        ("quarto", "r"),
        ("quarto", "projects"),
    ]
    assert result["verification_status"] == "verified"


async def test_workflow_returns_structured_error_when_official_docs_are_unavailable(service):
    class UnavailableDocs:
        async def get_docs(self, framework, topic, version=None):
            raise KnowledgeError(
                "source_unavailable",
                "Official documentation is unavailable",
                f"https://docs.invalid/{framework}/{topic}",
            )

    knowledge, _, _ = service
    knowledge.framework_docs = UnavailableDocs()
    result = await knowledge.get_r_workflow_guidance("analysis_to_shiny")
    assert result["verification_status"] == "partial"
    assert len(result["errors"]) == 3
    assert all(
        error["error"]["error"]["code"] == "source_unavailable"
        for error in result["errors"]
    )
    assert all(
        error["error"]["error"]["source_url"].startswith("https://docs.invalid/")
        for error in result["errors"]
    )


async def test_workflow_rejects_implicit_or_invalid_package_recommendations(service):
    knowledge, _, _ = service
    for packages in ([{"package": "ExamplePkg", "repository": "all"}], [{"repository": "cran"}]):
        try:
            await knowledge.get_r_workflow_guidance("analysis_to_shiny", packages=packages)
        except KnowledgeError as error:
            assert error.code == "invalid_input"
        else:
            raise AssertionError("invalid package request should fail")


async def test_quarto_dependencies_are_bounded_and_marked_unverified(service):
    knowledge, _, _ = service
    result = await knowledge.analyze_quarto_document(
        "---\ntitle: test\n---", dependencies=["ggplot2"]
    )
    assert result["dependencies_supplied"] == ["ggplot2"]
    assert result["dependency_analysis"] == "caller_supplied_names_unverified"
    for value in (["ggplot2", 4], ["x" * 201], ["pkg"] * 101):
        try:
            await knowledge.analyze_quarto_document("text", dependencies=value)
        except KnowledgeError as error:
            assert error.code == "invalid_input"
        else:
            raise AssertionError("invalid dependency metadata should fail")
