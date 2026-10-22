from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.visualization_analysis import (
    analyze_ggplot_code,
    analyze_ggplotly_compatibility,
    analyze_ggraph_code,
    analyze_knitr_chunks,
    analyze_tidyr_pipeline,
    scan_calls,
)


def test_scanner_ignores_comments_strings_and_finds_nested_calls():
    calls = scan_calls('ggplot(data) + geom_point(aes(x = x)) # geom_line()\nx <- "geom_bar()"')
    assert [call.name for call in calls] == ["ggplot", "geom_point", "aes"]


def test_ggplot_mapped_and_fixed_aesthetics_and_schema_warning():
    result = analyze_ggplot_code(
        'ggplot(df, aes(x = time, y = value)) + geom_point(colour="red")',
        {"columns": {"time": "numeric", "other": "character"}},
    )
    assert result["mappings"][0]["mapping_mode"] == "mapped"
    assert result["fixed_aesthetics"][0]["mapping_mode"] == "fixed"
    assert any(f["code"] == "mapping_not_in_supplied_schema" for f in result["findings"])


def test_ggplot_deprecated_mapping_api_is_flagged():
    result = analyze_ggplot_code('ggplot(df) + geom_point(aes_string(x="x"))')
    assert any(f["code"] == "deprecated_ggplot2_mapping_api" for f in result["findings"])


def test_ggraph_node_and_edge_mappings_use_separate_schemas():
    result = analyze_ggraph_code(
        "ggraph(graph, layout='stress') + "
        "geom_edge_link(aes(colour=edge_type)) + geom_node_point(aes(size=degree))",
        node_schema={"degree": "numeric"},
        edge_schema={"edge_type": "character"},
    )
    assert result["mappings"][0]["scope"] == "edge"
    assert result["mappings"][1]["scope"] == "node"
    assert not any(f["code"] == "mapping_not_in_supplied_schema" for f in result["findings"])


def test_tidyr_reports_wider_key_and_superseded_separate():
    result = analyze_tidyr_pipeline(
        "x |> separate(col, into=c('a','b')) |> pivot_wider(names_from=key, values_from=value)",
        input_schema={"id": "integer", "key": "character", "value": "numeric"},
    )
    codes = {finding["code"] for finding in result["findings"]}
    assert "superseded_tidyr_function" in codes
    assert "pivot_wider_cell_uniqueness_unverified" in codes


def test_plotly_warns_only_for_documented_geom_function_conversion():
    result = analyze_ggplotly_compatibility("ggplotly(ggplot(x) + geom_function(fun=f))")
    assert result["compatibility_status"] == "known_limitation_detected"
    assert result["findings"][0]["source_url"].startswith("https://plotly.com/")


def test_knitr_parses_plain_and_optioned_chunks_and_quarto_cell_options():
    result = analyze_knitr_chunks(
        "```{r}\n1 + 1\n```\n"
        "```{r, label='fit', cache=TRUE, dependson='data'}\n"
        "plot(x)\n#| fig-cap: 'Result'\n```",
        "qmd",
    )
    assert len(result["chunks"]) == 2
    assert result["chunks"][0]["header_options"] == {}
    assert result["chunks"][1]["quarto_cell_options"]["fig-cap"] == "'Result'"


def test_static_source_is_never_executed_and_caps_and_schema_validation_hold():
    assert analyze_ggplot_code("stop('do not run')")["not_executed"] is True
    try:
        analyze_ggplot_code("x", {"columns": {"bad": 1}})
    except KnowledgeError as exc:
        assert exc.code == "invalid_input"
    else:
        raise AssertionError("non-string schema type should be rejected")
    try:
        analyze_ggplot_code("x" * ((256 << 10) + 1))
    except KnowledgeError as exc:
        assert exc.code == "input_too_large"
    else:
        raise AssertionError("oversized source should be rejected")
