"""Bounded lexical analysis for R visualization, tidyr and knitr source text.

This is a token-aware scanner, not an R parser. It never evaluates source and only
draws schema conclusions for identifiers and argument forms it can read simply.
"""

import re
from dataclasses import dataclass

from .errors import KnowledgeError

# Human-readable findings are kept intact as structured response strings.
# ruff: noqa: E501

MAX_SOURCE = 256 << 10
MAX_SCHEMA_COLUMNS = 100
MAX_FINDINGS = 100
_IDENTIFIER = re.compile(r"[A-Za-z.][A-Za-z0-9._]*\Z")
_NAME = re.compile(r"[A-Za-z.][A-Za-z0-9._]*\Z")
_OPEN = {"(": ")", "[": "]", "[[": "]]", "{": "}"}
_CLOSE = {v: k for k, v in _OPEN.items()}


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    start: int
    end: int
    line: int


@dataclass(frozen=True)
class Call:
    name: str
    start: int
    end: int
    line: int
    arguments: tuple[tuple[str | None, str], ...]


def _input(source):
    if not isinstance(source, str):
        raise KnowledgeError("invalid_input", "R source must be text")
    if len(source.encode("utf-8")) > MAX_SOURCE:
        raise KnowledgeError("input_too_large", "R source exceeds 256 KiB")
    return source


def tokenize_r(source: str):
    """Tokenize enough R syntax to find calls and top-level arguments safely."""
    source = _input(source)
    tokens, i, line, n = [], 0, 1, len(source)
    while i < n:
        char = source[i]
        if char in " \t\r\f":
            i += 1
            continue
        if char == "\n":
            line += 1
            i += 1
            continue
        if char == "#":
            stop = source.find("\n", i)
            i = n if stop < 0 else stop
            continue
        start, start_line = i, line
        if char in "'\"`":
            quote = char
            i += 1
            value = []
            closed = False
            while i < n:
                current = source[i]
                if current == "\\":
                    if i + 1 < n:
                        value.extend((current, source[i + 1]))
                        if source[i + 1] == "\n":
                            line += 1
                        i += 2
                        continue
                if current == quote:
                    i += 1
                    closed = True
                    break
                if current == "\n":
                    line += 1
                value.append(current)
                i += 1
            tokens.append(
                Token(
                    "identifier" if quote == "`" else "string", "".join(value), start, i, start_line
                )
            )
            if not closed:
                raise KnowledgeError(
                    "invalid_r_syntax", f"Unterminated {quote} at line {start_line}"
                )
            continue
        if (
            char.isalpha()
            or char == "_"
            or (char == "." and i + 1 < n and not source[i + 1].isdigit())
        ):
            i += 1
            while i < n and (source[i].isalnum() or source[i] in "._"):
                i += 1
            tokens.append(Token("identifier", source[start:i], start, i, start_line))
            continue
        if char.isdigit() or (char == "." and i + 1 < n and source[i + 1].isdigit()):
            i += 1
            while i < n and (source[i].isalnum() or source[i] in "."):
                i += 1
            if i < n and source[i] in "+-" and source[i - 1] in "eE":
                i += 1
                while i < n and source[i].isdigit():
                    i += 1
            tokens.append(Token("number", source[start:i], start, i, start_line))
            continue
        if char == "%":
            stop = source.find("%", i + 1)
            if stop >= 0:
                i = stop + 1
                tokens.append(Token("operator", source[start:i], start, i, start_line))
                continue
        operator = next(
            (
                op
                for op in (
                    ":::",
                    "[[",
                    "]]",
                    "<<-",
                    "->>",
                    "::",
                    "<-",
                    "->",
                    "==",
                    "!=",
                    "<=",
                    ">=",
                    "&&",
                    "||",
                    "|>",
                    ":=",
                    "%%",
                    "%/%",
                    "&",
                    "&&",
                )
                if source.startswith(op, i)
            ),
            None,
        )
        if operator:
            i += len(operator)
            tokens.append(Token("operator", operator, start, i, start_line))
        else:
            i += 1
            tokens.append(Token("punctuation", char, start, i, start_line))
    return source, tokens


def _matching(tokens, opening):
    stack = []
    for index in range(opening, len(tokens)):
        value = tokens[index].value
        if value in _OPEN:
            stack.append(_OPEN[value])
        elif value in _CLOSE:
            if not stack or stack[-1] != value:
                return None
            stack.pop()
            if not stack:
                return index
    return None


def _split_arguments(source, tokens, opening, closing):
    if closing == opening + 1:
        return ()
    parts, start, stack = [], opening + 1, []
    for index in range(opening + 1, closing):
        value = tokens[index].value
        if value in _OPEN:
            stack.append(_OPEN[value])
        elif value in _CLOSE:
            if stack and stack[-1] == value:
                stack.pop()
        elif value == "," and not stack:
            parts.append((start, index))
            start = index + 1
    parts.append((start, closing))
    output = []
    for first, last in parts:
        if first >= last:
            continue
        key = None
        if (
            first + 1 < last
            and tokens[first].kind == "identifier"
            and tokens[first + 1].value == "="
        ):
            key = tokens[first].value
            first += 2
        if first < last:
            output.append((key, source[tokens[first].start : tokens[last - 1].end].strip()))
    return tuple(output)


def scan_calls(source: str):
    source, tokens = tokenize_r(source)
    delimiter_stack = []
    for token in tokens:
        if token.value in _OPEN:
            delimiter_stack.append((token.value, token.line))
        elif token.value in _CLOSE:
            if not delimiter_stack or _OPEN[delimiter_stack[-1][0]] != token.value:
                raise KnowledgeError(
                    "invalid_r_syntax", f"Unmatched {token.value} at line {token.line}"
                )
            delimiter_stack.pop()
    if delimiter_stack:
        value, line = delimiter_stack[-1]
        raise KnowledgeError("invalid_r_syntax", f"Unclosed {value} at line {line}")

    calls = []
    for index, token in enumerate(tokens[:-1]):
        if token.kind != "identifier" or tokens[index + 1].value != "(":
            continue
        closing = _matching(tokens, index + 1)
        if closing is None:
            continue
        name = token.value
        if index >= 2 and tokens[index - 1].value in ("::", ":::"):
            name = f"{tokens[index - 2].value}::{name}"
        calls.append(
            Call(
                name=name,
                start=token.start,
                end=tokens[closing].end,
                line=token.line,
                arguments=_split_arguments(source, tokens, index + 1, closing),
            )
        )
    return calls


def _simple_name(value):
    value = value.strip()
    if _NAME.fullmatch(value):
        return value
    match = re.fullmatch(r"\.data\s*\$\s*([A-Za-z.][A-Za-z0-9._]*)", value)
    return match.group(1) if match else None


def _string_value(value):
    value = value.strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return value[1:-1]
    return None


def _arguments_dict(call):
    return {key: value for key, value in call.arguments if key is not None}


def _positional(call):
    return [value for key, value in call.arguments if key is None]


def validate_schema(schema, label="data"):
    """Accept compact `{column: type}` or structured schema metadata."""
    if schema is None:
        return None
    if not isinstance(schema, dict) or len(schema) > MAX_SCHEMA_COLUMNS + 2:
        raise KnowledgeError("invalid_input", f"{label} must be a bounded schema mapping")
    columns = schema.get("columns", schema)
    if isinstance(columns, list):
        if len(columns) > MAX_SCHEMA_COLUMNS:
            raise KnowledgeError("invalid_input", f"{label} supports at most 100 columns")
        normalized = {}
        for item in columns:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise KnowledgeError("invalid_input", f"{label} column entries need a name")
            if len(item["name"]) > 128:
                raise KnowledgeError("invalid_input", f"{label} column names must be short")
            normalized[item["name"]] = item.get("type")
        columns = normalized
    elif isinstance(columns, dict):
        reserved = {"columns", "candidate_keys", "unique_keys", "row_count"}
        columns = {key: value for key, value in columns.items() if key not in reserved}
        if len(columns) > MAX_SCHEMA_COLUMNS:
            raise KnowledgeError("invalid_input", f"{label} supports at most 100 columns")
    else:
        raise KnowledgeError("invalid_input", f"{label}.columns must be a list or mapping")
    if any(not isinstance(key, str) or not key or len(key) > 128 for key in columns):
        raise KnowledgeError("invalid_input", f"{label} column names must be non-empty strings")
    for value in columns.values():
        if value is not None and (not isinstance(value, str) or len(value) > 80):
            raise KnowledgeError("invalid_input", f"{label} column types must be short strings")
    keys = schema.get("candidate_keys", schema.get("unique_keys", []))
    if not isinstance(keys, list) or len(keys) > 50:
        raise KnowledgeError("invalid_input", f"{label}.candidate_keys must be a bounded list")
    for key in keys:
        if (
            not isinstance(key, list)
            or len(key) > MAX_SCHEMA_COLUMNS
            or any(not isinstance(item, str) or len(item) > 128 for item in key)
        ):
            raise KnowledgeError(
                "invalid_input", f"{label} candidate keys must contain column names"
            )
    return {"columns": columns, "candidate_keys": keys}


def _base_result(tool, source, calls, input_schema=None):
    return {
        "analysis": tool,
        "analysis_scope": "token_aware_lexical_heuristics",
        "detected_calls": [{"function": call.name, "line": call.line} for call in calls[:200]],
        "input_schema": input_schema,
        "findings": [],
        "not_executed": True,
        "verification_status": "user_input_analyzed",
        "source_url": None,
        "checked_at": None,
        "sources": [],
        "limitations": [
            "The scanner is not an R parser and cannot infer runtime evaluation or tidy evaluation.",
            "Only simple identifiers and explicitly supplied schema metadata are compared.",
            "No source code, data or user schema is sent to external documentation services.",
        ],
    }


def _calls_named(calls, names):
    return [call for call in calls if call.name.split("::")[-1] in names]


def _findings(result, values):
    result["findings"].extend(values[: max(0, MAX_FINDINGS - len(result["findings"]))])


def _mapping_calls(calls):
    result = []
    positional_names = ("x", "y", "colour", "fill", "size", "shape", "linetype", "alpha", "group")
    aes_calls = _calls_named(calls, {"aes"})
    for mapping in aes_calls:
        containers = [
            call for call in calls if call.start < mapping.start and call.end > mapping.end
        ]
        container = min(containers, key=lambda call: call.end - call.start) if containers else None
        parent = container.name.split("::")[-1] if container else None
        scope = (
            "node"
            if parent and parent.startswith("geom_node_")
            else "edge"
            if parent and parent.startswith("geom_edge_")
            else "plot"
        )
        for index, (key, value) in enumerate(mapping.arguments):
            aesthetic = key or (positional_names[index] if index < len(positional_names) else None)
            if aesthetic is None:
                continue
            result.append(
                {
                    "aesthetic": aesthetic,
                    "expression": value[:200],
                    "variable": _simple_name(value),
                    "line": mapping.line,
                    "mapping_mode": "mapped",
                    "scope": scope,
                }
            )
    return result


def _schema_findings(mappings, schema, scope="plot"):
    if schema is None:
        return []
    names = set(schema["columns"])
    found = []
    for mapping in mappings:
        variable = mapping.get("variable")
        if variable and variable not in names:
            found.append(
                {
                    "code": "mapping_not_in_supplied_schema",
                    "certainty": "heuristic",
                    "scope": scope,
                    "line": mapping["line"],
                    "variable": variable,
                    "message": "A simple mapped name is absent from the caller-supplied schema; dynamic data or layer-specific data may explain it.",
                }
            )
    return found


def analyze_ggplot_code(source, data_schema=None):
    calls = scan_calls(source)
    schema = validate_schema(data_schema, "data_schema")
    result = _base_result("analyze_ggplot_code", source, calls, schema)
    recognized = {
        call.name.split("::")[-1]
        for call in calls
        if call.name.split("::")[-1].startswith(
            ("geom_", "stat_", "scale_", "coord_", "facet_", "theme_")
        )
        or call.name.split("::")[-1]
        in {"ggplot", "aes", "labs", "theme", "guides", "guide_legend", "ggsave"}
    }
    layers = [
        call.name.split("::")[-1]
        for call in calls
        if call.name.split("::")[-1].startswith(("geom_", "stat_"))
    ]
    mappings = _mapping_calls(calls)
    fixed_aesthetics = []
    for call in calls:
        name = call.name.split("::")[-1]
        if not name.startswith(("geom_", "stat_")):
            continue
        for key, value in call.arguments:
            if key in {"x", "y", "colour", "color", "fill", "size", "shape", "linetype", "alpha"}:
                fixed_aesthetics.append(
                    {
                        "aesthetic": key,
                        "expression": value[:200],
                        "line": call.line,
                        "mapping_mode": "fixed",
                    }
                )
    result.update(layers=layers, mappings=mappings, recognized_ggplot_calls=sorted(recognized))
    result["fixed_aesthetics"] = fixed_aesthetics
    _findings(result, _schema_findings(mappings, schema))
    for call in calls:
        name = call.name.split("::")[-1]
        if name in {"aes_string", "aes_", "aes_q"}:
            result["findings"].append(
                {
                    "code": "deprecated_ggplot2_mapping_api",
                    "certainty": "official_current_documentation",
                    "line": call.line,
                    "function": name,
                    "message": "Current ggplot2 documentation marks this programmatic mapping API deprecated; check the selected package version before changing it.",
                    "source_url": "https://ggplot2.tidyverse.org/reference/aes_.html",
                }
            )
    result["suggestions"] = [
        "Mapped aesthetics inside aes() are evaluated as data mappings; arguments outside aes() are fixed layer settings.",
        "Check each geom's current Rd documentation for required aesthetics; this scanner does not infer all geom/stat requirements.",
    ]
    return result


def analyze_ggraph_code(source, node_schema=None, edge_schema=None):
    calls = scan_calls(source)
    nodes, edges = (
        validate_schema(node_schema, "node_schema"),
        validate_schema(edge_schema, "edge_schema"),
    )
    result = _base_result("analyze_ggraph_code", source, calls, {"nodes": nodes, "edges": edges})
    graph_calls = _calls_named(calls, {"ggraph", "create_layout"})
    node_calls = [call for call in calls if call.name.split("::")[-1].startswith("geom_node_")]
    edge_calls = [call for call in calls if call.name.split("::")[-1].startswith("geom_edge_")]
    mappings = _mapping_calls(calls)
    result.update(
        graph_constructors=[call.name.split("::")[-1] for call in graph_calls],
        layouts=[_string_value(_arguments_dict(call).get("layout", "")) for call in graph_calls],
        node_layers=[call.name.split("::")[-1] for call in node_calls],
        edge_layers=[call.name.split("::")[-1] for call in edge_calls],
        mappings=mappings,
        graph_object_conversion_detected=bool(_calls_named(calls, {"as_tbl_graph", "tbl_graph"})),
    )
    if not graph_calls:
        result["findings"].append(
            {
                "code": "ggraph_constructor_not_found",
                "certainty": "heuristic",
                "message": "No ggraph() or create_layout() call was found in the supplied source.",
            }
        )
    elif not _positional(graph_calls[0]) and "graph" not in _arguments_dict(graph_calls[0]):
        result["findings"].append(
            {
                "code": "graph_input_not_visible",
                "certainty": "heuristic",
                "line": graph_calls[0].line,
                "message": "No graph argument is visible in the first graph constructor; it may be supplied through a wrapper or computed expression.",
            }
        )
    _findings(
        result, _schema_findings([m for m in mappings if m["scope"] == "node"], nodes, "node")
    )
    _findings(
        result, _schema_findings([m for m in mappings if m["scope"] == "edge"], edges, "edge")
    )
    result["suggestions"] = [
        "ggraph supports graph objects with an appropriate as_tbl_graph() method; the source scanner cannot prove an input object's class.",
        "Layout suitability depends on graph structure and the communication goal; no optimal layout is inferred.",
    ]
    result["sources"] = [
        {
            "source_url": "https://ggraph.data-imaginist.com/reference/ggraph.html",
            "verification_status": "official_documentation_reference",
            "checked_at": None,
        }
    ]
    return result


def _selection(value):
    value = value.strip()
    match = re.fullmatch(r"c\((.*)\)", value, re.S)
    if match:
        members = [part.strip().strip("`\"'") for part in match.group(1).split(",")]
        if members and all(_NAME.fullmatch(part) for part in members):
            return members
    if _NAME.fullmatch(value):
        return [value]
    return None


def analyze_tidyr_pipeline(source, input_schema=None, expected_schema=None):
    calls = scan_calls(source)
    schema = validate_schema(input_schema, "input_schema")
    expected = validate_schema(expected_schema, "expected_schema")
    result = _base_result("analyze_tidyr_pipeline", source, calls, schema)
    operations = {
        "pivot_longer",
        "pivot_wider",
        "separate_wider_delim",
        "separate_wider_position",
        "separate_wider_regex",
        "separate",
        "extract",
        "unite",
        "nest",
        "unnest",
        "unnest_longer",
        "unnest_wider",
        "hoist",
        "complete",
        "expand",
        "drop_na",
        "replace_na",
        "fill",
        "gather",
        "spread",
    }
    transforms = [call for call in calls if call.name.split("::")[-1] in operations]
    result["transformations"] = [
        {
            "function": call.name.split("::")[-1],
            "line": call.line,
            "arguments": dict(call.arguments),
        }
        for call in transforms
    ]
    if any(call.name.split("::")[-1] == "separate" for call in transforms):
        result["findings"].append(
            {
                "code": "superseded_tidyr_function",
                "certainty": "official_current_documentation",
                "function": "separate",
                "message": "Current tidyr documentation says separate() is superseded by separate_wider_*() functions.",
                "source_url": "https://tidyr.tidyverse.org/reference/separate.html",
            }
        )
    for call in transforms:
        if call.name.split("::")[-1] != "pivot_wider":
            continue
        args = _arguments_dict(call)
        names_from = _selection(args.get("names_from", ""))
        values_from = _selection(args.get("values_from", ""))
        id_cols = _selection(args.get("id_cols", ""))
        if schema is None:
            certainty = "heuristic"
            detail = "No input schema or uniqueness metadata was supplied, so pivot cell uniqueness cannot be checked."
        elif names_from is None or values_from is None:
            certainty = "heuristic"
            detail = "names_from/values_from are not simple identifiers, so pivot cell uniqueness cannot be checked."
        else:
            if id_cols is None:
                id_cols = [
                    name for name in schema["columns"] if name not in set(names_from + values_from)
                ]
            pivot_key = set(id_cols + names_from)
            unique = any(set(key).issubset(pivot_key) for key in schema["candidate_keys"])
            if unique:
                continue
            certainty = "heuristic"
            detail = "No supplied candidate key proves that id_cols plus names_from identify each output cell."
        values_fn = args.get("values_fn")
        result["findings"].append(
            {
                "code": "pivot_wider_cell_uniqueness_unverified",
                "certainty": certainty,
                "line": call.line,
                "may_create_list_columns": values_fn is None,
                "message": detail
                + (
                    " With no values_fn, duplicate cells can produce list-columns."
                    if values_fn is None
                    else " values_fn is supplied; verify the chosen aggregation matches the analysis."
                ),
            }
        )
    result["expected_output_schema"] = None
    for call in transforms:
        if call.name.split("::")[-1] != "pivot_longer" or schema is None:
            continue
        args = _arguments_dict(call)
        selected = _selection(args.get("cols", ""))
        if not selected or any(name not in schema["columns"] for name in selected):
            continue
        names_to = _string_value(args.get("names_to", '"name"')) or "name"
        values_to = _string_value(args.get("values_to", '"value"')) or "value"
        retained = [name for name in schema["columns"] if name not in selected]
        result["expected_output_schema"] = {
            "columns_known_from_simple_selection": retained + [names_to, values_to],
            "value_type": "not_inferred; selected columns may need compatible types or a values_ptypes constraint",
        }
        break
    if expected is not None:
        result["expected_schema_supplied"] = list(expected["columns"])
        result["expected_schema_comparison"] = (
            "not_performed_without_complete_data-dependent name expansion"
        )
    result["suggestions"] = [
        "pivot_wider() uniqueness depends on id_cols and names_from; a supplied candidate key is only as reliable as the caller's metadata.",
        "List-column and type behavior depends on actual rows, values_fn, and vctrs type negotiation; this analyzer does not execute the transformation.",
    ]
    result["sources"] = [
        {
            "source_url": "https://tidyr.tidyverse.org/reference/pivot_wider.html",
            "verification_status": "official_documentation_reference",
            "checked_at": None,
        }
    ]
    return result


def analyze_ggplotly_compatibility(source):
    calls = scan_calls(source)
    result = _base_result("analyze_ggplotly_compatibility", source, calls)
    plotly_calls = _calls_named(
        calls,
        {
            "ggplotly",
            "plot_ly",
            "add_trace",
            "add_markers",
            "add_lines",
            "add_bars",
            "layout",
            "subplot",
            "event_data",
            "highlight",
            "config",
            "saveWidget",
        },
    )
    geom_function = _calls_named(calls, {"geom_function", "stat_function"})
    result["plotly_calls"] = [
        {"function": call.name.split("::")[-1], "line": call.line} for call in plotly_calls
    ]
    result["ggplotly_present"] = bool(_calls_named(calls, {"ggplotly"}))
    if geom_function and result["ggplotly_present"]:
        result["findings"].append(
            {
                "code": "documented_ggplotly_geom_limitation",
                "certainty": "official_plotly_documentation_example",
                "function": "geom_function",
                "line": geom_function[0].line,
                "message": "Plotly's R documentation example shows geom_function() producing a not-implemented conversion warning. This is a version-sensitive documented example, not a complete compatibility matrix.",
                "source_url": "https://plotly.com/ggplot2/layers/geoms/geom_function/",
            }
        )
    if result["ggplotly_present"]:
        tooltip = []
        for call in _calls_named(calls, {"ggplotly"}):
            value = _arguments_dict(call).get("tooltip")
            if value is not None:
                tooltip.append({"line": call.line, "expression": value[:200]})
        result["tooltip_arguments"] = tooltip
        result["findings"].append(
            {
                "code": "conversion_requires_render_validation",
                "certainty": "general_limitation",
                "message": "ggplotly() translates a ggplot object; this static scan cannot establish that every geom, scale, theme, facet, tooltip, or widget behavior is preserved.",
            }
        )
    result["compatibility_status"] = (
        "known_limitation_detected" if result["findings"] else "unknown_not_claimed"
    )
    result["sources"] = [
        {
            "source_url": "https://plotly.com/ggplot2/getting-started/",
            "verification_status": "official_documentation_reference",
            "checked_at": None,
        }
    ]
    return result


_KNITR_OPTIONS = {
    "eval",
    "echo",
    "include",
    "warning",
    "message",
    "error",
    "cache",
    "fig.width",
    "fig.height",
    "fig.cap",
    "out.width",
    "results",
    "dependson",
    "cache.path",
    "cache.rebuild",
    "cache.lazy",
    "cache.comments",
    "fig.show",
    "fig.align",
    "dev",
    "label",
}
_QUARTO_ONLY = {
    "freeze",
    "execute-dir",
    "fig-format",
    "fig-dpi",
    "fig-pos",
    "fig-alt",
    "code-fold",
    "code-summary",
}


def _chunk_header(line):
    match = re.match(r"^\s*(`{3,}|~{3,})\{r(?:\s*,\s*(.*)|\s+([^}]*))?\}\s*$", line, re.I)
    if not match:
        return None
    tail = (match.group(2) if match.group(2) is not None else (match.group(3) or "")).strip()
    current, quote, depth, escaped = [], None, 0, False
    pieces = []
    for char in tail:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current.append(char)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            pieces.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    pieces.append("".join(current).strip())
    options = {}
    label = None
    for index, piece in enumerate(pieces):
        if not piece:
            continue
        if "=" not in piece and index == 0:
            label = piece.strip("`\"'")
            options["label"] = label
        elif "=" in piece:
            key, value = piece.split("=", 1)
            options[key.strip()] = value.strip()
    return match.group(1), label, options


def analyze_knitr_chunks(source, document_type=None):
    source = _input(source)
    if document_type is not None and document_type not in {"rmd", "qmd"}:
        raise KnowledgeError("invalid_input", "document_type must be rmd or qmd")
    lines = source.splitlines()
    chunks, findings = [], []
    index = 0
    while index < len(lines):
        parsed = _chunk_header(lines[index])
        if parsed is None:
            index += 1
            continue
        marker, label, options = parsed
        start_line = index + 1
        index += 1
        closed = False
        qmd_options = {}
        while index < len(lines):
            line = lines[index]
            if re.match(rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$", line):
                closed = True
                break
            if line.lstrip().startswith("#|"):
                key_value = line.lstrip()[2:].strip()
                if ":" in key_value:
                    key, value = key_value.split(":", 1)
                    qmd_options[key.strip()] = value.strip()
            index += 1
        chunks.append(
            {
                "label": label,
                "header_options": options,
                "quarto_cell_options": qmd_options,
                "line": start_line,
                "closed": closed,
            }
        )
        index += 1
    labels = [chunk["label"] for chunk in chunks if chunk["label"]]
    for label in sorted({item for item in labels if labels.count(item) > 1}):
        findings.append(
            {
                "code": "duplicate_chunk_label",
                "certainty": "definite",
                "label": label,
                "message": "Chunk labels should be unique in a document.",
            }
        )
    label_set = set(labels)
    for chunk in chunks:
        if not chunk["closed"]:
            findings.append(
                {
                    "code": "unclosed_chunk",
                    "certainty": "definite",
                    "line": chunk["line"],
                    "message": "An R chunk fence has no closing fence.",
                }
            )
        options = chunk["header_options"]
        for name in options:
            if name in _QUARTO_ONLY:
                findings.append(
                    {
                        "code": "quarto_option_in_knitr_header",
                        "certainty": "heuristic",
                        "line": chunk["line"],
                        "option": name,
                        "message": "This option is Quarto-specific and should not be assumed to be a knitr chunk option.",
                    }
                )
            elif name not in _KNITR_OPTIONS and name != "label":
                findings.append(
                    {
                        "code": "unrecognized_knitr_option",
                        "certainty": "heuristic",
                        "line": chunk["line"],
                        "option": name,
                        "message": "This name is not in the analyzer's documented knitr option subset; custom options or newer versions may explain it.",
                    }
                )
        cache = options.get("cache", "FALSE").strip().upper()
        if cache not in {"FALSE", "F", "0", "NULL"}:
            depends = options.get("dependson")
            if depends:
                mentioned = re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", depends)
                missing = sorted(set(mentioned) - label_set)
                if missing:
                    findings.append(
                        {
                            "code": "missing_cached_chunk_dependency",
                            "certainty": "heuristic",
                            "line": chunk["line"],
                            "labels": missing,
                            "message": "dependson names do not match a supplied explicit chunk label.",
                        }
                    )
            else:
                findings.append(
                    {
                        "code": "cache_dependency_not_declared",
                        "certainty": "heuristic",
                        "line": chunk["line"],
                        "message": "Cached output can depend on prior chunks, external files, or data not visible here; review invalidation and explicit dependson as needed.",
                    }
                )
        if "freeze" in chunk["quarto_cell_options"] or "freeze" in options:
            findings.append(
                {
                    "code": "freeze_is_quarto_project_behavior",
                    "certainty": "official_documentation_reference",
                    "line": chunk["line"],
                    "message": "Quarto freeze configuration and knitr chunk cache are distinct mechanisms; check Quarto's project-level freeze behavior.",
                }
            )
    result = {
        "analysis": "analyze_knitr_chunks",
        "analysis_scope": "bounded_fenced_R_chunk_scan",
        "document_type": document_type
        or ("qmd" if "format:" in source[:2048] or "#|" in source else "rmd_or_qmd"),
        "chunks": chunks,
        "findings": findings[:MAX_FINDINGS],
        "not_executed": True,
        "verification_status": "user_input_analyzed",
        "source_url": None,
        "checked_at": None,
        "sources": [
            {
                "source_url": "https://yihui.org/knitr/options/",
                "verification_status": "official_documentation_reference",
                "checked_at": None,
            }
        ],
        "limitations": [
            "Only fenced R chunks and explicit header options are analyzed; inline R, child documents, engines, YAML inheritance, runtime dependencies, and Quarto rendering are not resolved.",
            "Quarto #| cell options are returned separately and are not treated as knitr header options.",
            "No code chunks are executed.",
        ],
    }
    return result
