"""Rust accelerators must return exactly what the Python reference returns."""

import random

import pytest

from cran_knowledge_mcp import native as native_module
from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.providers import base
from cran_knowledge_mcp.visualization_analysis import (
    MAX_ARGUMENT_CHARS,
    Call,
    _scan_calls_python,
    scan_calls,
)

native = native_module.native
pytestmark = pytest.mark.skipif(native is None, reason="cran-knowledge-native is not installed")

FRAGMENTS = [
    "ggplot(df, aes(x = a, y = b))",
    " + geom_point(colour = 'red')",
    "pkg::fn(",
    "pkg:::hidden(",
    "x[y[1]]",
    "z[[i]][[j]]",
    "df[idx[1], ]",
    'r"(a"b)"',
    "R'[c(]'",
    'r"--{x}"}--"',
    '"esc\\"aped"',
    "`odd name`(1)",
    "# comment ) ( ]\n",
    "%in%",
    "%%",
    "x <- 1e-5 + .5 + 0x1F",
    "a |> b()",
    "f(a = , b)",
    '"Привет, мир"',
    "# комментарий\n",
    "　",
    "\x0b",
    "\x1c",
    "\n",
    ", ",
    "(",
    ")",
    "{",
    "}",
    "[",
    "]",
    "=",
    "'",
    '"',
    "`",
    "\\",
    ".data$col",
    "function(x) { x + 1 }",
]
UNICODE_CODE = ["é", "ß", "²", "µ", "Ⅻ", "́", "日本"]


def python_result(source):
    try:
        return ("ok", _scan_calls_python(source))
    except KnowledgeError as exc:
        return ("error", exc.code, str(exc))


def native_result(source):
    try:
        records = native.scan_calls(source)
    except ValueError as exc:
        return ("error", *exc.args)
    if records is None:
        return None
    return ("ok", list(map(Call._make, records)))


def generated_sources(seed, count, extra=()):
    rng = random.Random(seed)
    pool = FRAGMENTS + list(extra)
    for _ in range(count):
        yield "".join(rng.choice(pool) for _ in range(rng.randint(1, 40)))


@pytest.mark.parametrize("seed", range(6))
def test_scan_calls_matches_python_on_generated_ascii_and_string_unicode(seed):
    deferred = 0
    for source in generated_sources(seed, 600):
        expected = python_result(source)
        actual = native_result(source)
        if actual is None:
            deferred += 1
            continue
        assert actual == expected, repr(source)
    # Cyrillic and ideographic spaces here only occur inside strings, comments or as
    # whitespace-like punctuation; the fast path must handle most inputs.
    assert deferred < 600 * 0.6


@pytest.mark.parametrize("seed", range(3))
def test_unicode_code_outside_strings_defers_or_matches(seed):
    for source in generated_sources(100 + seed, 400, UNICODE_CODE):
        actual = native_result(source)
        assert actual is None or actual == python_result(source), repr(source)


def test_public_scan_calls_falls_back_for_unicode_identifiers():
    source = "café(x) + données::f(y)"
    assert native.scan_calls(source) is None
    assert scan_calls(source) == _scan_calls_python(source)


def test_long_arguments_truncate_identically():
    source = "f(" + "x + " * MAX_ARGUMENT_CHARS + "y, '" + "　" * 3000 + "')"
    assert native_result(source) == python_result(source)


def test_deep_nesting_matches():
    source = "f(" * 5000 + "g(1, 2)" + ")" * 5000
    assert native_result(source) == python_result(source)


def python_search_index(entries):
    index = base.PackageSearchIndex.__new__(base.PackageSearchIndex)
    index._native = None
    index.entries = []
    for name, title in entries:
        folded = name.casefold()
        title_folded = (title or "").casefold()
        index.entries.append(
            (
                name,
                folded,
                set(base._WORD.findall(folded)),
                title_folded,
                tuple(base._WORD.findall(title_folded)),
            )
        )
    return index


@pytest.mark.parametrize("seed", range(4))
def test_package_search_matches_python_ranking(seed):
    rng = random.Random(seed)
    words = ["data", "table", "api", "Plot", "ggplot2", "tidy", "Données", "STRASSE", "straße", "x"]
    entries = []
    for number in range(400):
        name = rng.choice(["", "gg", "R", "tidy"]) + rng.choice(words).replace("é", "e")
        name = f"{name}{number}" if rng.random() < 0.7 else name.replace("ß", "ss")
        if not name[0].isalpha():
            name = "p" + name
        title = " ".join(rng.choice(words + ["data.frame", "(API)", "web-apis"]) for _ in range(5))
        entries.append((name, title if rng.random() < 0.9 else None))
    fast = base.PackageSearchIndex(entries)
    reference = python_search_index(entries)
    assert fast._native is not None
    queries = ["api", "data table", "plot", "data.frame", "ggplot2", "straße", "STRASSE", "x"]
    queries += [" ".join(rng.sample(words, 2)) for _ in range(40)]
    for query in queries:
        assert fast.search(query) == reference.search(query), query


ATOMS = [
    "x",
    "df",
    ".data$col",
    "1",
    "2.5e-3",
    ".5",
    "TRUE",
    "'a'",
    '"Привет"',
    'r"(a"b)"',
    "R'[c(]'",
    "`odd name`",
    "NULL",
    '"x = (1, 2]"',
]
NAMES = ["f", "ggplot", "aes", "geom_point", "pkg::fn", "base:::g", ".hidden", "pivot_wider"]
OPERATORS_R = [" + ", " - ", " |> ", " %in% ", " <- ", " == ", " & ", " %>% "]


def expression(rng, depth=0):
    roll = rng.random()
    if depth > 7 or roll < 0.25:
        return rng.choice(ATOMS)
    if roll < 0.6:
        arguments = []
        for _ in range(rng.randint(0, 4)):
            value = expression(rng, depth + 1)
            arguments.append(
                f"{rng.choice(['x', 'y', 'colour'])} = {value}" if rng.random() < 0.4 else value
            )
        separator = rng.choice([", ", ",\n  ", " ,"])
        return f"{rng.choice(NAMES)}({separator.join(arguments)})"
    if roll < 0.72:
        inner = expression(rng, depth + 1)
        return f"{rng.choice(ATOMS[:3])}[{inner}]" if rng.random() < 0.5 else f"x[[{inner}]]"
    if roll < 0.82:
        return (
            "{\n  "
            + expression(rng, depth + 1)
            + "  # note ) ]\n  "
            + expression(rng, depth + 1)
            + "\n}"
        )
    return expression(rng, depth + 1) + rng.choice(OPERATORS_R) + expression(rng, depth + 1)


@pytest.mark.parametrize("seed", range(8))
def test_scan_calls_matches_python_on_generated_valid_r(seed):
    rng = random.Random(1000 + seed)
    compared = 0
    for _ in range(300):
        source = "\n".join(expression(rng) for _ in range(rng.randint(1, 4)))
        expected = python_result(source)
        actual = native_result(source)
        assert actual is not None, repr(source)  # only ASCII code here: never deferred
        assert expected[0] == "ok", repr(source)
        assert actual == expected, repr(source)
        compared += len(expected[1])
    assert compared > 300
