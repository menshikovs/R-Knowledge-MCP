import json

import pytest

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.project_analysis import (
    analyze_quarto_document,
    analyze_quarto_project,
    analyze_r_workspace,
    analyze_shiny_app,
)


def test_shiny_analysis_finds_structural_and_security_signals_without_execution():
    result = analyze_shiny_app(
        source="""
ui <- fluidPage(
  textInput("name", "Name"),
  plotOutput("plot"), plotOutput("plot"),
  fileInput("upload", "Upload"),
  HTML(input$name)
)
server <- function(input, output) {
  output$plot <- renderPlot({ eval(parse(text = input$code)) })
  print(input$missing)
}
shinyApp(ui, server)
"""
    )
    kinds = {finding["kind"] for finding in result["findings"]}
    assert result["analysis"] == "static_heuristics"
    assert result["application_shape"]["shinyApp_call_present"]
    assert {
        "input_reference_not_statically_matched",
        "duplicate_ui_output_id",
        "file_upload_review",
        "raw_html_review",
        "dynamic_code_evaluation",
    } <= kinds
    assert result["not_executed"] is True
    assert "runtime reactive graph" in result["limitations"][0]


def test_shiny_manifest_is_path_safe_bounded_and_requires_one_input():
    with pytest.raises(KnowledgeError, match="exactly one"):
        analyze_shiny_app()
    with pytest.raises(KnowledgeError, match="unsafe path"):
        analyze_shiny_app(files={"../app.R": "shinyApp()"})
    with pytest.raises(KnowledgeError, match="256 KiB"):
        analyze_shiny_app(source="x" * ((256 << 10) + 1))
    result = analyze_shiny_app(files={"app.R": "shinyApp(ui, server)", "R/mod.R": "NS('x')"})
    assert result["application_shape"]["module_constructs_present"]


def test_quarto_document_parses_yaml_and_r_chunk_options_without_running_code():
    source = """---
title: Report
format:
  html: default
  docx: default
bibliography: refs.bib
---

See [@smith2024].

```{r}
#| label: summary
#| eval: false
stop("never run")
```
"""
    result = analyze_quarto_document(source, quarto_version="1.7")
    assert result["document_metadata"]["title"] == "Report"
    assert result["output_formats"] == ["html", "docx"]
    assert result["execution"] == "no_executable_r_chunks_detected"
    assert result["r_chunks"][0]["label"] == "summary"
    assert result["not_executed"]
    assert "render_executes_code" not in {f["kind"] for f in result["findings"]}


def test_quarto_analysis_redacts_secret_metadata_and_legacy_module_whitespace():
    source = """---
params:
  api_key: top-secret
environment:
  database_password: another-secret
---
```{r}
callModule (old_module, id)
```
"""
    result = analyze_quarto_document(source)
    serialized = json.dumps(result)
    assert "top-secret" not in serialized
    assert "another-secret" not in serialized
    shiny = analyze_shiny_app(source="callModule (old_module, id)")
    assert "legacy_callModule" in {finding["kind"] for finding in shiny["findings"]}


def test_quarto_duplicate_yaml_keys_aliases_and_unclosed_r_chunks_are_reported():
    duplicate = analyze_quarto_document("---\ntitle: a\ntitle: b\n---\n")
    assert duplicate["findings"][0]["kind"] == "invalid_front_matter"
    alias = analyze_quarto_document("---\na: &x one\nb: *x\n---\n")
    assert "aliases are not accepted" in alias["findings"][0]["message"]
    unclosed = analyze_quarto_document("---\ntitle: x\n---\n```{r}\n1+1\n")
    kinds = {finding["kind"] for finding in unclosed["findings"]}
    assert "unclosed_r_chunk" in kinds
    assert "render_executes_code" in kinds


def test_quarto_yaml_python_tags_never_construct_objects():
    result = analyze_quarto_document(
        "---\ntitle: !!python/object/apply:os.system ['echo unsafe']\n---\n"
    )
    assert result["findings"][0]["kind"] == "invalid_front_matter"


def test_quarto_yaml_safe_values_are_json_friendly_and_mapping_keys_are_strings():
    result = analyze_quarto_document("---\ndate: 2026-10-22\n---\n")
    assert result["document_metadata"]["date"] == "2026-10-22"
    non_string_key = analyze_quarto_document("---\n1: value\n---\n")
    assert non_string_key["findings"][0]["kind"] == "invalid_front_matter"


def test_quarto_project_reports_manifest_bibliography_gap():
    result = analyze_quarto_project(
        "project:\n  type: website\nprofile:\n  default: development\nbibliography: refs.bib\n",
        files=["index.qmd", "_quarto.yml"],
    )
    assert result["project_type"] == "website"
    assert result["profiles_configured"]
    assert result["findings"][0]["kind"] == "bibliography_file_not_in_manifest"
    with pytest.raises(KnowledgeError, match="unsafe path"):
        analyze_quarto_project("project: {}", files=["C:/secret.yml"])


def test_workspace_analysis_redacts_renviron_and_summarizes_lockfile():
    lock = {
        "R": {"Version": "4.4.0"},
        "Packages": {
            "shiny": {
                "Version": "1.0.0",
                "Repository": "https://alice:registry-secret@example.invalid/cran",
            },
            "DESeq2": {"Version": "2.0.0", "Repository": "Bioconductor"},
        },
    }
    result = analyze_r_workspace(
        {
            "app.R": "shinyApp(ui, server)",
            ".qmd": "not-a-file",
            "report.qmd": "---\ntitle: test\n---",
            "renv.lock": json.dumps(lock),
            ".Renviron": "API_TOKEN=top-secret-value\nR_LIBS_USER=/tmp/lib\n",
            ".vscode/settings.json": json.dumps(
                {
                    "positron.r.customBinaries": "${workspaceFolder}/.R/bin/R",
                    "editor.wordWrap": "on",
                }
            ),
            "DESCRIPTION": "Package: analysis\nVersion: 1.0.0\nImports: shiny\n",
            "analysis.Rproj": "Version: 1.0\nRestoreWorkspace: No\nSecretKey: do-not-return\n",
            ".Rprofile": "options(prompt = '> ')\n",
        }
    )
    serialized = json.dumps(result)
    assert "top-secret-value" not in serialized
    assert "registry-secret" not in serialized
    assert result["renviron_variable_names"] == ["API_TOKEN", "R_LIBS_USER"]
    assert result["renv_lock"]["r_version"] == "4.4.0"
    assert result["renv_lock"]["package_count"] == 2
    assert {"quarto", "shiny", "renv_managed", "r_package"} <= set(result["project_types"])
    assert result["rproj"] == {"RestoreWorkspace": "No", "Version": "1.0"}
    assert "do-not-return" not in serialized
    assert "unrecognized_rproj_fields" in {finding["kind"] for finding in result["findings"]}
    assert "invalid_positron_r_path_setting" in {finding["kind"] for finding in result["findings"]}
    assert result["positron_setting_keys"] == ["editor.wordWrap", "positron.r.customBinaries"]
    assert result["local_filesystem_accessed"] is False


def test_workspace_rejects_unsafe_paths_and_malformed_metadata():
    with pytest.raises(KnowledgeError, match="unsafe path"):
        analyze_r_workspace({"../.Renviron": "TOKEN=secret"})
    result = analyze_r_workspace({"renv.lock": "{"})
    assert result["findings"][0]["kind"] == "invalid_renv_lock"
