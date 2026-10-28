"""KC-002: what makes Function Discovery `partial` (and what must not).

`verification_status` is "verified" for `complete` and `complete_with_diagnostics`, "partial" for
`incomplete` (a known gap) and `unestablished` (completeness cannot be determined statically).
Observations that cannot change what is enumerated are `info` diagnostics.
"""

import dataclasses

import pytest

from cran_knowledge_mcp import function_discovery as fd
from cran_knowledge_mcp import native as native_module
from cran_knowledge_mcp import visualization_analysis as va
from cran_knowledge_mcp.parsers import (
    DIAGNOSTIC_CLASS,
    diagnostic_class,
    parse_namespace,
    rd_coverage,
    rd_index_record,
)


def codes(result, klass=None):
    return {d["code"] for d in result["diagnostics"] if klass is None or d["class"] == klass}


# ---------------------------------------------------------------- NAMESPACE


@pytest.mark.parametrize(
    "namespace",
    [
        "useDynLib(pkg, .registration = TRUE)",
        'useDynLib(pkg, .registration = TRUE, .fixes = "C_")',
        "useDynLib(pkg, foo, bar)\nexport(a)",
        "import(methods, except = c(a, b))",
        "import(R6)\nuseDynLib(pkg, .registration=TRUE)\nexport(a)",
    ],
)
def test_harmless_native_and_import_options_do_not_downgrade(namespace):
    result = parse_namespace(namespace)
    assert result["status"] == "verified" and result["issues"] == []
    assert codes(result, "info") <= {
        "namespace_native_library_declared",
        "namespace_import_arguments_unparsed",
    }


def test_useDynLib_registration_is_visible_as_info_with_its_line():
    result = parse_namespace("export(a)\nuseDynLib(pkg, .registration = TRUE)\n")
    (note,) = result["diagnostics"]
    assert note == {
        "code": "namespace_native_library_declared",
        "class": "info",
        "directive": "useDynLib",
        "line": 2,
    }
    assert [e["name"] for e in result["exports"]] == ["a"]


@pytest.mark.parametrize(
    ("namespace", "code", "klass"),
    [
        ("exportPattern('^a')", "export_patterns_not_expanded", "incomplete"),
        ("export(f(x))", "namespace_nonliteral_arguments", "incomplete"),
        ("export(a, TRUE)", "namespace_nonliteral_arguments", "incomplete"),
        ("export(a,,b)", "namespace_empty_argument", "incomplete"),
        ("export(a = b)", "namespace_named_arguments_unsupported", "incomplete"),
        ("S3method(a::b::c, cls)", "namespace_nonliteral_arguments", "incomplete"),
        ("S3method(generic)", "namespace_unsupported_directive", "incomplete"),
        ("if (TRUE) export(a)", "namespace_unsupported_expression", "unestablished"),
        ("eval(parse(text='export(a)'))", "namespace_unsupported_expression", "unestablished"),
    ],
)
def test_genuine_namespace_uncertainty_stays_partial_and_visible(namespace, code, klass):
    result = parse_namespace(namespace)
    assert result["status"] == "partial"
    assert code in result["issues"]
    assert {"code": code, "class": klass}.items() <= next(
        d for d in result["diagnostics"] if d["code"] == code
    ).items()


def test_missing_namespace_is_unestablished_not_verified():
    result = parse_namespace(None)
    assert result["status"] == "unavailable" and result["issues"] == ["namespace_missing"]
    assert codes(result, "unestablished") == {"namespace_missing"}


def test_harmless_directive_does_not_hide_a_genuine_gap_in_the_same_file():
    result = parse_namespace("useDynLib(pkg, .registration = TRUE)\nexportPattern('^x')\n")
    assert result["status"] == "partial" and result["issues"] == ["export_patterns_not_expanded"]
    assert codes(result) == {"namespace_native_library_declared", "export_patterns_not_expanded"}


def test_s3method_on_another_packages_generic_is_enumerated():
    result = parse_namespace("S3method(utils::.DollarNames, R6)\nS3method(print, R6)\n")
    assert result["status"] == "verified" and result["issues"] == []
    delayed, plain = result["methods"]
    assert (delayed["generic"], delayed["name"], delayed["generic_package"]) == (
        "utils::.DollarNames",
        ".DollarNames.R6",
        "utils",
    )
    assert (plain["generic"], plain["name"]) == ("print", "print.R6")
    assert "generic_package" not in plain


def test_s3method_qualified_generic_with_explicit_function_name():
    result = parse_namespace("S3method(ggplot2::autoplot, mi_gains, autoplot_gains)")
    (method,) = result["methods"]
    assert (method["generic"], method["class"], method["name"]) == (
        "ggplot2::autoplot",
        "mi_gains",
        "autoplot_gains",
    )


@pytest.mark.parametrize("generic", ["pkg:::hidden", "1pkg::f", "pkg::", "::f", "a::b::c"])
def test_malformed_qualified_generics_are_not_accepted(generic):
    result = parse_namespace(f"S3method({generic}, cls)")
    assert result["methods"] == [] and result["status"] == "partial"


def test_every_diagnostic_code_has_an_explicit_class():
    assert set(DIAGNOSTIC_CLASS.values()) == {"info", "incomplete", "unestablished"}
    assert diagnostic_class("a_code_nobody_classified") == "incomplete"  # never harmless by default


# --------------------------------------------------------------------- Rd


def rd(body: str, name="f", alias="f") -> str:
    return f"\\name{{{name}}}\n\\alias{{{alias}}}\n\\title{{T}}\n{body}"


@pytest.mark.parametrize(
    "body",
    [
        "\\description{Text \\if{html}{\\out{<div class='x'>}}more}",
        "\\description{\\ifelse{html}{\\href{u}{a}}{a}}",
        "\\description{\\Sexpr[results=rd,stage=render]{lifecycle::badge('stable')}}",
        "\\details{\\Sexpr{1 + 1} and \\eval{x}}",
        "\\newcommand{\\pkg}{\\strong{#1}}\n\\description{x}",
        "% \\Sexpr{commented out}\n\\description{x}",
    ],
)
def test_constructs_that_cannot_change_the_alias_set_are_info_only(body):
    record = rd_coverage("pkg/man/f.Rd", rd(body))
    assert record["complete"] is True, record
    assert all(diagnostic_class(c) == "info" for c in record["diagnostics"])


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("\\Sexpr[results=rd,stage=build]{make_aliases()}", "rd_dynamic_top_level"),
        ("\\Sexpr{stop('never')}", "rd_dynamic_top_level"),
        ("\\RdOpts{stage=build}", "rd_dynamic_top_level"),
        ("\\if{html}{\\alias{hidden}}", "rd_conditional_structure"),
        ("\\ifelse{html}{\\name{a}}{\\name{b}}", "rd_conditional_structure"),
        ("\\newcommand{\\mk}{\\alias{z}}", "rd_macro_definition_structural"),
        ("\\description{unclosed", "rd_unbalanced_braces"),
        ("\\description{x}}", "rd_unbalanced_braces"),
    ],
)
def test_constructs_that_may_create_aliases_or_break_structure_are_limiting(body, code):
    record = rd_coverage("pkg/man/f.Rd", rd(body))
    assert record["complete"] is False
    assert code in record["diagnostics"] and diagnostic_class(code) != "info"


def test_non_literal_alias_and_name_are_incomplete():
    assert (
        "rd_alias_not_literal"
        in rd_coverage("p/man/f.Rd", rd("", alias="\\Sexpr{x}"))["diagnostics"]
    )
    nonliteral_name = rd_coverage("p/man/f.Rd", rd("", name="\\foo"))
    assert "rd_name_not_literal" in nonliteral_name["diagnostics"]
    assert nonliteral_name["identifier_source"] == "archive_filename"


def test_escaped_percent_in_name_is_a_literal_topic():
    record = rd_coverage("p/man/pipe.Rd", rd("", name="\\%>\\%", alias="\\%>\\%"))
    assert record["complete"] and record["topic"] == "%>%" and record["aliases"] == ["%>%"]
    assert record["identifier_source"] == "rd_name"


def test_duplicate_alias_in_one_file_is_not_a_coverage_problem():
    text = "\\name{f}\n\\alias{f}\n\\alias{f}\n\\title{T}\n"
    assert rd_coverage("p/man/f.Rd", text)["complete"] is True


def test_rd_index_record_keeps_its_four_tuple_contract():
    topic, aliases, complete, source = rd_index_record("p/man/f.Rd", rd("\\description{x}"))
    assert (topic, aliases, complete, source) == ("f", ["f"], True, "rd_name")


# ------------------------------------------------------------------ index


def build(namespace, rd_files):
    files = {"P/DESCRIPTION": b"Package: P\nVersion: 1.0\n"}
    if namespace is not None:
        files["P/NAMESPACE"] = namespace.encode()
    files.update({f"P/man/{k}": v.encode() for k, v in rd_files.items()})
    return fd.build_discovery_index("P", {"Encoding": "UTF-8"}, files)


PLAIN = {"f.Rd": rd("\\description{x}")}


@pytest.mark.parametrize(
    ("namespace", "rd_files", "completeness", "verified"),
    [
        ("export(f)", PLAIN, "complete", True),
        ("useDynLib(P, .registration = TRUE)\nexport(f)", PLAIN, "complete_with_diagnostics", True),
        (
            "export(f)",
            {"f.Rd": rd("\\description{\\if{html}{x}}")},
            "complete_with_diagnostics",
            True,
        ),
        ("exportPattern('^f')", PLAIN, "incomplete", False),
        ("export(f)", {"f.Rd": rd("", alias="\\Sexpr{x}")}, "incomplete", False),
        ("if (TRUE) export(f)", PLAIN, "unestablished", False),
        (None, PLAIN, "unestablished", False),
        ("export(f)", {"f.Rd": rd("\\Sexpr[results=rd]{x}")}, "unestablished", False),
    ],
)
def test_completeness_levels_and_verification_status(namespace, rd_files, completeness, verified):
    index = build(namespace, rd_files)
    assert index.completeness == completeness
    page = index.page("P", None, 50, 0)
    assert page["coverage"]["completeness"] == completeness
    is_verified = index.namespace_status == index.rd_status == "verified"
    assert is_verified is verified
    assert (not index.issues) == verified
    assert page["diagnostics_count"] == len(index.diagnostics)


def test_a_limiting_issue_is_never_hidden_by_harmless_ones():
    many = {
        f"d{i}.Rd": rd("\\description{\\if{html}{x}}", name=f"d{i}", alias=f"d{i}")
        for i in range(30)
    }
    many["bad.Rd"] = rd("", name="bad", alias="\\Sexpr{x}")
    index = build("export(f)", many)
    assert index.completeness == "incomplete" and "rd_literal_coverage_partial" in index.issues
    info = next(d for d in index.diagnostics if d["code"] == "rd_conditional_formatting")
    assert info["count"] == 30 and len(info["examples"]) == fd.MAX_DIAGNOSTIC_EXAMPLES
    bad = next(d for d in index.diagnostics if d["code"] == "rd_alias_not_literal")
    assert bad["examples"] == [{"archive_member": "P/man/bad.Rd"}]


def test_topic_entries_report_per_file_verification():
    index = build("export(f)", {**PLAIN, "g.Rd": rd("\\if{html}{\\alias{h}}", name="g", alias="g")})
    status = {
        t["archive_member"]: t["verification_status"] for t in index.entries if t["kind"] == "topic"
    }
    assert status == {"P/man/f.Rd": "verified", "P/man/g.Rd": "partial"}


CASES = [
    ("export(f)\nS3method(utils::.DollarNames, P)\nuseDynLib(P, .registration=TRUE)", PLAIN),
    ("exportPattern('^f')", {"f.Rd": rd("\\if{html}{\\alias{hid}}")}),
    ("if (TRUE) export(f)", {"p.Rd": rd("", name="\\%>\\%", alias="\\%>\\%")}),
]


@pytest.mark.parametrize("namespace, rd_files", CASES)
def test_python_and_actual_native_backends_agree(namespace, rd_files, monkeypatch):
    if native_module.native is None:
        pytest.skip("actual PyO3 module is unavailable; parity not verified")
    monkeypatch.setattr(va, "native", None)
    reference = build(namespace, rd_files)
    monkeypatch.setattr(va, "native", native_module.native)
    actual = build(namespace, rd_files)
    assert dataclasses.asdict(actual) == dataclasses.asdict(reference)


# ------------------------------------------------------------ boundedness

BACKSLASH = chr(92)


@pytest.mark.parametrize(
    "text",
    [
        (BACKSLASH + "if{html}{b}") * 20_000,
        (BACKSLASH + "if{") * 25_000,
        ((BACKSLASH + "if{a}{") * 120 + "x" + "}" * 120) * 300,  # nested conditionals, 288 KB
        ((BACKSLASH + "if{a}{") * 60 + "x" + "}" * 60) * 2000,
        (BACKSLASH + "Sexpr{1}") * 50_000,
        BACKSLASH * 2_000_000,
        "{" * 200_000,
    ],
    ids=["sequential", "unclosed", "nested-120", "nested-60", "sexpr", "backslashes", "braces"],
)
def test_rd_scanning_is_linear_on_adversarial_input(text):
    import time

    started = time.perf_counter()
    rd_coverage("p/man/f.Rd", text)
    # Measured 0.001-0.25 s; the bound only catches a return to quadratic behaviour.
    assert time.perf_counter() - started < 5
