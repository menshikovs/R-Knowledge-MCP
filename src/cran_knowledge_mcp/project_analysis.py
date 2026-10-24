"""Bounded static analysis for explicitly supplied R, Shiny and Quarto project text."""

import json
import re
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import PurePosixPath, PureWindowsPath

import yaml
from yaml.events import AliasEvent

from .errors import KnowledgeError
from .parsers import dcf

MAX_TEXT = 256 << 10
MAX_MANIFEST = 512 << 10
SECRET_FIELD = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|credential|authorization)"
)


def _text_size(text, maximum, label):
    limit_label = f"{maximum // 1024} KiB" if maximum % 1024 == 0 else f"{maximum} bytes"
    if not isinstance(text, str):
        raise KnowledgeError("invalid_input", f"{label} must be text")
    if len(text) > maximum:
        raise KnowledgeError("input_too_large", f"{label} exceeds {limit_label}")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError as exc:
        raise KnowledgeError("invalid_input", f"{label} must be valid Unicode") from exc
    if size > maximum:
        raise KnowledgeError("input_too_large", f"{label} exceeds {limit_label}")
    return size


class _UniqueSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that reports duplicate mapping keys instead of hiding them."""

    def compose_node(self, parent, index):
        if self.check_event(AliasEvent):
            raise yaml.YAMLError("YAML aliases are not accepted in untrusted project metadata")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "configuration mapping keys must be strings",
                    key_node.start_mark,
                )
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _yaml(text: str):
    _text_size(text, MAX_TEXT, "YAML input")
    try:
        value = yaml.load(text, Loader=_UniqueSafeLoader)
    except (yaml.YAMLError, TypeError, RecursionError) as exc:
        return None, str(exc).splitlines()[0][:300]
    if value is None:
        value = {}
    if not isinstance(value, dict):
        return None, "YAML root must be a mapping"
    try:
        return _normalize_yaml(value), None
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        return None, str(exc)[:300]


def _normalize_yaml(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, dict):
        return {key: _normalize_yaml(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_yaml(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"unsupported YAML value type: {type(value).__name__}")


def _redact_metadata(value, parent_key=""):
    if SECRET_FIELD.search(parent_key) or parent_key.casefold() in {"env", "environment"}:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_FIELD.search(key) else _redact_metadata(item, key)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_metadata(item, parent_key) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1[REDACTED]@", value)
    return value


def _document_front_matter(source: str):
    if not isinstance(source, str):
        raise KnowledgeError("invalid_input", "QMD source must be text")
    _text_size(source, MAX_TEXT, "QMD source")
    lines = source.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, None, 0
    close = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    if close is None:
        return None, "YAML front matter has no closing delimiter", 0
    metadata, error = _yaml("\n".join(lines[1:close]))
    return metadata, error, close + 1


def _qmd_chunks(source: str, body_line: int):
    """Read only fenced R chunk headers and `#|` options; never parse/execute R."""
    lines = source.splitlines()[body_line:]
    chunks, findings = [], []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^\s*(`{3,}|~{3,})\{r(?:[,}\s])?.*\}\s*$", line, re.I)
        if not match:
            index += 1
            continue
        marker = match.group(1)
        header = line[match.end(1) :].strip()
        options = {}
        label = None
        label_match = re.search(r"\b(?:label|name)\s*=\s*['\"]?([\w.-]+)", header)
        if label_match:
            label = label_match.group(1)
        index += 1
        chunk_lines = []
        closed = False
        while index < len(lines):
            current = lines[index]
            if re.match(rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$", current):
                closed = True
                break
            if current.lstrip().startswith("#|"):
                chunk_lines.append(current.lstrip()[2:].strip())
            index += 1
        if chunk_lines:
            option_data, error = _yaml("\n".join(chunk_lines))
            if error:
                findings.append(
                    {
                        "kind": "invalid_chunk_options",
                        "certainty": "definite",
                        "message": error,
                    }
                )
            elif option_data:
                options = option_data
                label = options.get("label", label)
        if not closed:
            findings.append(
                {
                    "kind": "unclosed_r_chunk",
                    "certainty": "definite",
                    "message": "An R code fence has no matching closing fence.",
                }
            )
        chunks.append({"label": label, "options": options, "closed": closed})
        index += 1
    labels = [c["label"] for c in chunks if isinstance(c["label"], str)]
    for label in sorted(value for value, seen in Counter(labels).items() if seen > 1):
        findings.append(
            {
                "kind": "duplicate_chunk_label",
                "certainty": "definite",
                "label": label,
                "message": "Chunk labels should be unique within the document.",
            }
        )
    return chunks, findings


def analyze_quarto_document(source: str, project_config: str | None = None, quarto_version=None):
    metadata, error, body_line = _document_front_matter(source)
    findings = []
    if error:
        findings.append({"kind": "invalid_front_matter", "certainty": "definite", "message": error})
        metadata = {}
    elif metadata is None:
        metadata = {}
    if project_config is not None:
        project, project_error = _yaml(project_config)
        if project_error:
            findings.append(
                {
                    "kind": "invalid_project_config",
                    "certainty": "definite",
                    "message": project_error,
                }
            )
        else:
            # Document metadata takes precedence over shared project metadata.
            metadata = {**project, **metadata}

    formats = metadata.get("format")
    if formats is None:
        output_formats = ["html (Quarto default when no format is specified)"]
    elif isinstance(formats, str):
        output_formats = [formats]
    elif isinstance(formats, dict):
        output_formats = list(formats)
    else:
        output_formats = []
        findings.append(
            {
                "kind": "invalid_format_config",
                "certainty": "definite",
                "message": "`format` must be a string or mapping.",
            }
        )

    chunks, chunk_findings = _qmd_chunks(source, body_line)
    findings.extend(chunk_findings)
    execute = metadata.get("execute", {})
    if not isinstance(execute, dict):
        findings.append(
            {
                "kind": "invalid_execute_config",
                "certainty": "definite",
                "message": "`execute` must be a mapping.",
            }
        )
        execute = {}
    executable = [chunk for chunk in chunks if chunk.get("options", {}).get("eval") is not False]
    if executable and execute.get("enabled") is False:
        execution = "disabled_by_document_metadata"
    elif executable:
        execution = "may_execute_when_rendered"
        findings.append(
            {
                "kind": "render_executes_code",
                "certainty": "definite",
                "message": "Rendering can execute R chunks; this analyzer never executes them.",
            }
        )
    else:
        execution = "no_executable_r_chunks_detected"

    citations = sorted(set(re.findall(r"\[@([A-Za-z0-9_.:-]+)", source)))
    bibliography = metadata.get("bibliography")
    if citations and not bibliography:
        findings.append(
            {
                "kind": "bibliography_not_declared",
                "certainty": "heuristic",
                "citation_keys": citations[:100],
                "message": (
                    "Citations were found but no bibliography is declared in supplied metadata."
                ),
            }
        )
    bibliography_items = bibliography if isinstance(bibliography, list) else [bibliography]
    bibliography_items = [item for item in bibliography_items if isinstance(item, str)]
    chunk_labels = [chunk["label"] for chunk in chunks if chunk.get("label")]
    return {
        "analysis": "static_only",
        "document_metadata": _redact_metadata(metadata),
        "quarto_version": quarto_version,
        "version_scope": "not_checked_against_a_local_Quarto_installation",
        "output_formats": output_formats,
        "execution": execution,
        "r_chunks": _redact_metadata(chunks),
        "bibliography": bibliography_items,
        "citation_keys": citations[:100],
        "chunk_labels": chunk_labels,
        "findings": findings,
        "not_executed": True,
        "verification_status": "user_input_analyzed",
        "source_url": None,
        "checked_at": datetime.now(UTC).isoformat(),
        "limitations": [
            "Quarto's full YAML schema and cross-reference semantics are not validated.",
            (
                "File existence, bibliography keys, dependency availability and rendering "
                "are not checked."
            ),
        ],
    }


def analyze_quarto_project(project_config: str, metadata_config: str | None = None, files=None):
    project, error = _yaml(project_config)
    findings = []
    if error:
        findings.append({"kind": "invalid_project_yaml", "certainty": "definite", "message": error})
        project = {}
    if metadata_config is not None:
        metadata, metadata_error = _yaml(metadata_config)
        if metadata_error:
            findings.append(
                {
                    "kind": "invalid_metadata_yaml",
                    "certainty": "definite",
                    "message": metadata_error,
                }
            )
        elif "bibliography" not in project and "bibliography" in metadata:
            project = {**metadata, **project}
    file_list = _validated_paths(files or [])
    project_block = project.get("project", {})
    if not isinstance(project_block, dict):
        findings.append(
            {
                "kind": "invalid_project_block",
                "certainty": "definite",
                "message": "`project` must be a mapping.",
            }
        )
        project_block = {}
    project_type = project_block.get("type")
    bibliography = project.get("bibliography", [])
    bibliography = bibliography if isinstance(bibliography, list) else [bibliography]
    unresolved = [
        item
        for item in bibliography
        if isinstance(item, str) and file_list and item not in file_list
    ]
    for item in unresolved:
        findings.append(
            {
                "kind": "bibliography_file_not_in_manifest",
                "certainty": "definite",
                "path": item,
                "message": "Referenced bibliography is not present in the supplied manifest.",
            }
        )
    return {
        "analysis": "static_only",
        "project_type": project_type,
        "project_config": _redact_metadata(project),
        "profiles_configured": bool(project.get("profile")),
        "formats": list(project.get("format", {}))
        if isinstance(project.get("format"), dict)
        else [],
        "bibliography": [item for item in bibliography if isinstance(item, str)],
        "file_manifest": file_list,
        "findings": findings,
        "not_executed": True,
        "verification_status": "user_input_analyzed",
        "source_url": None,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def _validated_paths(values):
    if not isinstance(values, list) or len(values) > 500:
        raise KnowledgeError("invalid_input", "File manifest must be a list of at most 500 paths")
    result = []
    for value in values:
        if not isinstance(value, str) or len(value) > 200:
            raise KnowledgeError("invalid_input", "Manifest paths must be short strings")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or PureWindowsPath(value).drive
            or ".." in path.parts
            or "\\" in value
            or value in ("", ".", "..")
        ):
            raise KnowledgeError("invalid_input", "Manifest contains an unsafe path")
        result.append(value)
    return sorted(set(result))


def analyze_r_workspace(files: dict[str, str]):
    if not isinstance(files, dict) or not files or len(files) > 100:
        raise KnowledgeError("invalid_input", "Provide 1..100 explicitly selected project files")
    safe_files = {}
    total = 0
    for name, content in files.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise KnowledgeError(
                "invalid_input", "Workspace entries must map names to bounded text"
            )
        total += _text_size(content, MAX_MANIFEST, "Workspace file")
        if total > MAX_MANIFEST:
            raise KnowledgeError("input_too_large", "Workspace manifest exceeds 512 KiB")
        _validated_paths([name])
        safe_files[name] = content

    names = set(safe_files)
    is_shiny = bool(names.intersection({"app.R", "ui.R", "server.R"}))
    is_quarto = "_quarto.yml" in names or any(name.endswith(".qmd") for name in names)
    package_project = "DESCRIPTION" in names
    project_types = []
    if is_shiny:
        project_types.append("shiny")
    if is_quarto:
        project_types.append("quarto")
    if package_project:
        project_types.append("r_package")
    if ".Rproj" in names or any(name.endswith(".Rproj") for name in names):
        project_types.append("r_project")
    if "renv.lock" in names:
        project_types.append("renv_managed")

    findings = []
    lock_summary = None
    if "renv.lock" in safe_files:
        try:
            lock = json.loads(safe_files["renv.lock"])
            if not isinstance(lock, dict) or not isinstance(lock.get("Packages", {}), dict):
                raise ValueError("expected an object with a Packages mapping")
            packages = lock.get("Packages", {})
            lock_summary = {
                "r_version": (lock.get("R", {}) or {}).get("Version")
                if isinstance(lock.get("R", {}), dict)
                else None,
                "package_count": len(packages),
                "repositories": sorted(
                    {
                        entry.get("Repository")
                        for entry in packages.values()
                        if isinstance(entry, dict) and isinstance(entry.get("Repository"), str)
                    }
                ),
                "package_versions": {
                    name: entry.get("Version")
                    for name, entry in list(packages.items())[:250]
                    if isinstance(name, str)
                    and isinstance(entry, dict)
                    and isinstance(entry.get("Version"), str)
                    and len(entry["Version"]) <= 100
                },
            }
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            findings.append(
                {"kind": "invalid_renv_lock", "certainty": "definite", "message": str(exc)[:300]}
            )

    description_summary = None
    if "DESCRIPTION" in safe_files:
        try:
            record = dcf(safe_files["DESCRIPTION"])[0]
            description_summary = {
                field: record[field]
                for field in ("Package", "Version", "Depends", "Imports", "Suggests", "LinkingTo")
                if field in record
            }
        except (KnowledgeError, IndexError):
            findings.append(
                {
                    "kind": "invalid_description",
                    "certainty": "definite",
                    "message": "DESCRIPTION metadata is malformed.",
                }
            )

    renviron_keys = []
    if ".Renviron" in safe_files:
        for line in safe_files[".Renviron"].splitlines():
            match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*=", line)
            if match:
                renviron_keys.append(match.group(1))
        if renviron_keys:
            findings.append(
                {
                    "kind": "renviron_values_redacted",
                    "certainty": "definite",
                    "message": "Only variable names are returned; values can contain credentials.",
                }
            )

    if ".Rprofile" in safe_files:
        findings.append(
            {
                "kind": "rprofile_not_executed",
                "certainty": "definite",
                "message": (
                    "`.Rprofile` is treated as text; startup code is never run by this analyzer."
                ),
            }
        )
    rproj_summary = None
    rproj_names = sorted(name for name in safe_files if name.endswith(".Rproj"))
    if rproj_names:
        rproj_values = {}
        for line in safe_files[rproj_names[0]].splitlines():
            match = re.match(r"^\s*([A-Za-z][A-Za-z0-9.]*)\s*:\s*(.*?)\s*$", line)
            if match:
                rproj_values[match.group(1)] = match.group(2)
        known_rproj_keys = {
            "Version",
            "RestoreWorkspace",
            "SaveWorkspace",
            "AlwaysSaveHistory",
            "EnableCodeIndexing",
            "UseSpacesForTab",
            "NumSpacesForTab",
            "Encoding",
            "RnwWeave",
            "LaTeX",
        }
        unknown = sorted(set(rproj_values) - known_rproj_keys)
        rproj_summary = {
            key: rproj_values[key] for key in sorted(set(rproj_values) & known_rproj_keys)
        }
        if unknown:
            findings.append(
                {
                    "kind": "unrecognized_rproj_fields",
                    "certainty": "heuristic",
                    "fields": unknown,
                    "message": (
                        "These project fields are outside the analyzer's known-key set; "
                        "verify against the IDE version."
                    ),
                }
            )
    positron_setting_keys = []
    if ".vscode/settings.json" in safe_files:
        try:
            settings = json.loads(safe_files[".vscode/settings.json"])
            if not isinstance(settings, dict):
                raise ValueError("settings root must be an object")
            positron_setting_keys = sorted(key for key in settings if isinstance(key, str))
            for key in ("positron.r.customBinaries", "positron.r.customRootFolders"):
                if key in settings and (
                    not isinstance(settings[key], list)
                    or any(not isinstance(path, str) for path in settings[key])
                ):
                    findings.append(
                        {
                            "kind": "invalid_positron_r_path_setting",
                            "certainty": "definite",
                            "setting": key,
                            "message": "This Positron R discovery setting must be an array "
                            "of path strings.",
                        }
                    )
        except (json.JSONDecodeError, ValueError) as exc:
            findings.append(
                {"kind": "invalid_ide_settings", "certainty": "definite", "message": str(exc)[:300]}
            )

    return {
        "analysis": "metadata_only",
        "project_types": sorted(set(project_types)) or ["unknown"],
        "files_received": sorted(safe_files),
        "renv_lock": _redact_metadata(lock_summary),
        "description": _redact_metadata(description_summary),
        "rproj": rproj_summary,
        "positron_setting_keys": positron_setting_keys,
        "renviron_variable_names": sorted(set(renviron_keys)),
        "findings": findings,
        "installed_r_version": None,
        "local_filesystem_accessed": False,
        "not_executed": True,
        "verification_status": "user_input_analyzed",
        "source_url": None,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def analyze_shiny_app(source: str | None = None, files: dict[str, str] | None = None):
    if (source is None) == (files is None):
        raise KnowledgeError("invalid_input", "Supply exactly one of `source` or `files`")
    if source is not None:
        _text_size(source, MAX_TEXT, "Shiny source")
        texts = {"app.R": source}
    else:
        if not isinstance(files, dict) or not files or len(files) > 50:
            raise KnowledgeError("invalid_input", "Provide 1..50 named R source files")
        texts = {}
        total = 0
        for path, text in files.items():
            if not isinstance(path, str) or not isinstance(text, str) or not path.endswith(".R"):
                raise KnowledgeError(
                    "invalid_input", "Shiny manifest accepts only named .R text files"
                )
            _validated_paths([path])
            total += _text_size(text, MAX_TEXT, "Shiny source file")
            if total > MAX_TEXT:
                raise KnowledgeError("input_too_large", "Shiny file manifest exceeds 256 KiB")
            texts[path] = text
    combined = "\n".join(texts.values())
    _text_size(combined, MAX_TEXT, "Combined Shiny source")

    inputs = re.findall(
        r"\b(?:textInput|numericInput|sliderInput|selectInput|selectizeInput|actionButton|"
        r"checkboxInput|checkboxGroupInput|radioButtons|dateInput|fileInput)\s*\(\s*['\"]([^'\"]+)",
        combined,
    )
    input_refs = set(re.findall(r"\binput\s*\$\s*([A-Za-z][A-Za-z0-9_.]*)", combined))
    output_defs = re.findall(r"\boutput\s*\$\s*([A-Za-z][A-Za-z0-9_.]*)\s*<-", combined)
    output_widgets = re.findall(
        r"\b(?:plotOutput|plotlyOutput|tableOutput|dataTableOutput|textOutput|verbatimTextOutput|"
        r"uiOutput|htmlOutput)\s*\(\s*['\"]([^'\"]+)",
        combined,
    )
    findings = []
    for item in sorted(value for value, seen in Counter(inputs).items() if seen > 1):
        findings.append(
            {
                "kind": "duplicate_ui_input_id",
                "certainty": "heuristic",
                "id": item,
                "message": (
                    "The same supported input widget ID appears more than once in source text."
                ),
            }
        )
    module_present = bool(re.search(r"\b(?:moduleServer|NS|callModule)\s*\(", combined))
    for missing in sorted(input_refs.difference(inputs)):
        findings.append(
            {
                "kind": "input_reference_not_statically_matched",
                "certainty": "heuristic",
                "id": missing,
                "message": (
                    "No supported input constructor matched this ID; namespaced or dynamic "
                    "UI may explain it."
                ),
            }
        )
    if not re.search(r"\bshinyApp\s*\(", combined):
        findings.append(
            {
                "kind": "shinyApp_call_not_found",
                "certainty": "heuristic",
                "message": (
                    "No shinyApp() call was found in supplied text; app.R may be sourced elsewhere."
                ),
            }
        )
    if re.search(r"\bcallModule\s*\(", combined):
        findings.append(
            {
                "kind": "legacy_callModule",
                "certainty": "heuristic",
                "message": (
                    "Current Shiny guidance recommends moduleServer(); check the target "
                    "version before migrating."
                ),
            }
        )
    for item in sorted(value for value, seen in Counter(output_widgets).items() if seen > 1):
        findings.append(
            {
                "kind": "duplicate_ui_output_id",
                "certainty": "heuristic",
                "id": item,
                "message": (
                    "The same supported output widget ID appears more than once in supplied source."
                ),
            }
        )
    if re.search(r"\bfileInput\s*\(", combined):
        findings.append(
            {
                "kind": "file_upload_review",
                "certainty": "heuristic",
                "message": (
                    "Review upload size/type limits, temporary-file handling and user "
                    "authorization."
                ),
            }
        )
    if re.search(r"\bHTML\s*\(", combined):
        findings.append(
            {
                "kind": "raw_html_review",
                "certainty": "heuristic",
                "message": (
                    "Review whether HTML includes user-controlled values before marking it trusted."
                ),
            }
        )
    if re.search(r"\beval\s*\(\s*parse\s*\(", combined):
        findings.append(
            {
                "kind": "dynamic_code_evaluation",
                "certainty": "heuristic",
                "message": "eval(parse(...)) is present; never pass untrusted input to it.",
            }
        )
    if re.search(r"\b(?:read\.csv|readRDS|read\.rds)\s*\(", combined):
        findings.append(
            {
                "kind": "data_io_scope_review",
                "certainty": "heuristic",
                "message": (
                    "Check whether file reads repeat reactively or depend on a "
                    "user-controlled path."
                ),
            }
        )
    return {
        "analysis": "static_heuristics",
        "application_shape": {
            "files": sorted(texts),
            "shinyApp_call_present": bool(re.search(r"\bshinyApp\s*\(", combined)),
            "ui_assignment_present": bool(re.search(r"\bui\s*<-", combined)),
            "server_assignment_present": bool(re.search(r"\bserver\s*<-", combined)),
            "module_constructs_present": module_present,
        },
        "declared_input_ids": sorted(set(inputs)),
        "referenced_input_ids": sorted(input_refs),
        "output_ids": sorted(set(output_defs)),
        "ui_output_ids": output_widgets,
        "findings": findings,
        "not_executed": True,
        "verification_status": "user_input_analyzed",
        "source_url": None,
        "checked_at": datetime.now(UTC).isoformat(),
        "limitations": [
            "Static text matching cannot build Shiny's runtime reactive graph.",
            (
                "R syntax, generated UI, namespaced IDs and sourced files can make static "
                "results incomplete."
            ),
            "This analysis is not a security audit and does not run the application.",
        ],
    }
