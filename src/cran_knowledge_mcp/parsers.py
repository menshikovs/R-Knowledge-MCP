"""Parse data only. Never extract archives to disk, run R, or evaluate Rd macros."""

import codecs
import gzip
import io
import re
import tarfile
from bisect import bisect_left
from difflib import SequenceMatcher
from html.parser import HTMLParser

from .errors import KnowledgeError


def dcf(text: str) -> list[dict[str, str]]:
    """Parse Debian-control-format records in linear time.

    Continuation lines are collected as parts and joined once per field; repeatedly appending to a
    growing string made a long continuation field quadratic in its length. The result is identical
    to joining each continuation (stripped) onto the value with one leading space.
    """
    records: list[dict[str, str]] = []
    record: dict[str, list[str]] = {}
    key = ""

    def finish() -> None:
        if record:
            records.append({name: "".join(parts) for name, parts in record.items()})

    for line in text.splitlines() + [""]:
        if not line.strip():
            finish()
            record, key = {}, ""
        elif line[0].isspace() and key:
            record[key].append(" " + line.strip())
        elif ":" in line:
            key, value = line.split(":", 1)
            if key in record:
                raise KnowledgeError("invalid_source", "Duplicate DCF field")
            record[key] = [value.strip()]
        else:
            raise KnowledgeError("invalid_source", "Malformed CRAN DCF data")
    return records


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: dict[str, str] = {}
        self.cells: list[str] = []
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        elif tag == "td":
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and len(self.cells) == 2:
            self.rows[self.cells[0]] = self.cells[1]


class PackagePageParser(CatalogParser):
    """Collect published links and Version cells without evaluating HTML."""

    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._label = []

    def handle_data(self, data):
        super().handle_data(data)
        if self._href is not None:
            self._label.append(data)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._label).split())))
            self._href = None


def source_files(body: bytes, package: str) -> dict[str, bytes]:
    # Bound gzip expansion before tar parsing (including headers and padding).
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as gz:
            expanded = gz.read((128 << 20) + 1)
        if len(expanded) > 128 << 20:
            raise KnowledgeError("source_too_large", "Expanded source exceeds 128 MiB")
        files: dict[str, bytes] = {}
        total = 0
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
            for count, member in enumerate(archive):
                if count >= 20000:
                    raise KnowledgeError("source_too_large", "Too many archive members")
                if not member.isfile():
                    continue
                name = member.name
                if name not in {
                    f"{package}/DESCRIPTION",
                    f"{package}/NAMESPACE",
                } and not re.fullmatch(re.escape(package) + r"/man/[^/\\]+\.Rd", name):
                    continue
                if member.size > 2 << 20:
                    raise KnowledgeError("source_too_large", "Documentation member exceeds 2 MiB")
                total += member.size
                if total > 16 << 20:
                    raise KnowledgeError("source_too_large", "Documentation exceeds 16 MiB")
                if name in files:
                    raise KnowledgeError("invalid_source", "Duplicate source archive member")
                stream = archive.extractfile(member)
                if stream is not None:
                    files[name] = stream.read()
        if f"{package}/DESCRIPTION" not in files:
            raise KnowledgeError("invalid_source", "Source archive has no DESCRIPTION")
        return files
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise KnowledgeError("invalid_source", "Invalid CRAN source archive") from exc


def decode(body: bytes, encoding: str = "UTF-8") -> str:
    try:
        return body.decode(encoding)
    except (UnicodeError, LookupError) as exc:
        raise KnowledgeError("unsupported_encoding", "Source text encoding is unsupported") from exc


# An Rd file may declare its own encoding (`\encoding{latin1}`); R applies that declaration to the
# file in preference to the package's DESCRIPTION `Encoding`. The declaration is plain ASCII, so it
# can be located in the raw bytes before the file is decoded. Commented (`%`) lines are ignored.
_RD_ENCODING_DECLARATION = re.compile(rb"(?m)^[^%\r\n]*?\\encoding\{([^}\r\n]{1,40})\}")


def rd_declared_encoding(body: bytes) -> str | None:
    r"""Return the Python codec named by a file's `\encoding{}` declaration, or None if absent.

    `unknown` counts as no declaration (R's own meaning). A declared but unrecognised name raises
    `unsupported_encoding` instead of being guessed.
    """
    match = _RD_ENCODING_DECLARATION.search(body)
    if match is None:
        return None
    try:
        name = match[1].decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise KnowledgeError("unsupported_encoding", "Rd encoding declaration is invalid") from exc
    if name.casefold() in {"", "unknown"}:
        return None
    try:
        return codecs.lookup(name).name
    except LookupError as exc:
        raise KnowledgeError(
            "unsupported_encoding", "Rd file declares an unsupported encoding"
        ) from exc


def decode_rd(body: bytes, package_encoding: str | None = None) -> tuple[str, str, str]:
    r"""Decode one Rd file; return (text, encoding, source).

    Precedence follows R: the file's own `\encoding{}` declaration, then the DESCRIPTION
    `Encoding`, then UTF-8. `source` is `rd_declaration`, `description` or `default`. Undecodable
    bytes raise `unsupported_encoding`; nothing is replaced or guessed.
    """
    declared = rd_declared_encoding(body)
    if declared is not None:
        return decode(body, declared), declared, "rd_declaration"
    if package_encoding:
        return decode(body, package_encoding), package_encoding, "description"
    return decode(body, "UTF-8"), "UTF-8", "default"


def description_text(body: bytes) -> str:
    encoding = re.search(rb"(?m)^Encoding:[ \t]*([^\r\n]+)", body)
    return decode(body, decode(encoding[1], "ascii").strip() if encoding else "UTF-8")


def _alias_values(uncommented: str) -> list[str]:
    """Every literal alias argument, duplicates included (comments already removed)."""
    values = re.findall(r"\\alias\{((?:\\.|[^{}\\])*)\}", uncommented)
    return [re.sub(r"\\([{}%\\])", r"\1", value) for value in values]


def aliases(rd: str) -> set[str]:
    # Literal aliases only. Do not expand user macros, conditional Rd or Sexpr.
    return set(_alias_values(re.sub(r"(?<!\\)%[^\n]*", "", rd)))


MAX_ALIAS_LENGTH = 160  # get_function_docs rejects longer names, so they cannot be requested.
FULL_ALIAS_LIST_LIMIT = 30
CLOSEST_ALIAS_LIMIT = 10


def _alias_needle(query: str) -> str:
    """Casefold a requested alias, ignoring a call-style `pkg::` prefix and `()` suffix."""
    needle = query.strip()
    needle = re.sub(r"^[A-Za-z][A-Za-z0-9.]*:::?", "", needle)
    return needle.removesuffix("()").casefold()


def alias_hints(query: str, alias_names) -> dict:
    """Describe the verified alias index for a missed lookup without inventing any name.

    Lists every requestable alias when the package has few, otherwise the closest ones.
    Matching stays literal; case and call syntax only influence the ranking.
    """
    names = sorted(
        name for name in alias_names if 0 < len(name) <= MAX_ALIAS_LENGTH and name.isprintable()
    )
    hints: dict = {
        "alias_count": len(alias_names),
        "alias_matching": "literal and case-sensitive; no parentheses or package prefix",
    }
    if len(alias_names) <= FULL_ALIAS_LIST_LIMIT:
        hints["available_aliases"] = names
        hints["alias_list_complete"] = len(names) == len(alias_names)
        return hints
    needle = _alias_needle(query)

    def rank(name: str):
        folded = name.casefold()
        if folded == needle:
            return (0, 0.0, name)
        score = SequenceMatcher(None, needle, folded).ratio()
        if needle and (needle in folded or folded in needle):
            score += 0.25
        return (1, -score, name)

    hints["closest_aliases"] = sorted(names, key=rank)[:CLOSEST_ALIAS_LIMIT]
    hints["alias_list_complete"] = False
    return hints


MAX_NAMESPACE_ENTRIES = 10_000
MAX_NAMESPACE_DECLARATIONS = 4000


def discovery_name(value: str) -> bool:
    return 0 < len(value) <= 160 and value.isprintable()


def _namespace_literal(text: str) -> str | None:
    """Accept one literal/symbol only; reject evaluation, escapes we cannot resolve."""
    from .visualization_analysis import tokenize_r

    try:
        _, tokens = tokenize_r(text)
    except KnowledgeError:
        return None
    if len(tokens) != 1 or tokens[0].kind not in {"identifier", "string"}:
        return None
    token = tokens[0]
    value = token.value
    if token.kind == "identifier" and text[token.start] != chr(96):
        reserved = {
            "if",
            "else",
            "repeat",
            "while",
            "function",
            "for",
            "in",
            "next",
            "break",
            "TRUE",
            "FALSE",
            "NULL",
            "Inf",
            "NaN",
            "NA",
            "NA_integer_",
            "NA_real_",
            "NA_complex_",
            "NA_character_",
        }
        if value in reserved or not re.fullmatch(r"(?:[^\W\d_]|\.(?!\d))[\w.]*", value):
            return None
    if "\\" in value and not re.match(r"""[rR][\x27"]""", text.strip()):
        # Conservative subset of R escapes, with no Python/R evaluation.
        def unescape(match):
            escape = match[1]
            if escape in ("\\", "'", '"', chr(96)):
                return escape
            if escape.startswith(("u", "U")):
                code = int(escape[1:], 16)
                if code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF:
                    return chr(code)
            raise ValueError

        try:
            value = re.sub(r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)", unescape, value)
        except ValueError:
            return None
    return value if discovery_name(value) else None


_QUALIFIED_GENERIC = re.compile(r"\s*([A-Za-z][A-Za-z0-9.]*)::([A-Za-z.][A-Za-z0-9._]*)\s*")


def _qualified_generic(text: str) -> tuple[str, str] | None:
    """`pkg::generic`, as `S3method()` writes a method for another package's generic."""
    match = _QUALIFIED_GENERIC.fullmatch(text)
    if match is None or not discovery_name(match[2]):
        return None
    return match[1], match[2]


def _gap(text: str, between: bool = False) -> bool:
    cleaned = re.sub(r"#[^\n]*", "", text)
    return not cleaned.strip(" \t\r\n\f;") and (not between or "\n" in text or ";" in cleaned)


def _namespace_statements(source: str, calls) -> tuple[list, bool]:
    """Only whole top-level statements can establish unconditional directives."""
    from .visualization_analysis import tokenize_r

    _, tokens = tokenize_r(source)
    statements, start, depth = [], 0, 0
    controls = {"if", "else", "for", "while", "repeat", "function"}
    for index, token in enumerate(tokens):
        previous = tokens[index - 1] if index else None
        if depth == 0 and index > start:
            gap = source[previous.end : token.start]
            control_open = tokens[start].value in controls and previous.value != "}"
            if (
                "\n" in gap
                and previous.kind != "operator"
                and token.kind != "operator"
                and not control_open
            ):
                statements.append(tokens[start:index])
                start = index
        if token.kind == "punctuation":
            if token.value == ";" and depth == 0:
                if index > start:
                    statements.append(tokens[start:index])
                start = index + 1
            elif token.value in "([{":
                depth += 1
            elif token.value in ")]}":
                depth -= 1
    if start < len(tokens):
        statements.append(tokens[start:])
    by_span = {(call.start, call.end): call for call in calls if call.parent is None}
    accepted, unsupported = [], False
    for statement in statements:
        call = by_span.get((statement[0].start, statement[-1].end))
        if call is None:
            unsupported = True
        else:
            accepted.append(call)
    return accepted, unsupported


# Discovery diagnostics. `info` never lowers verification; the others do, and say how:
#   incomplete   - a known gap (some declared names are not enumerated);
#   unestablished - completeness cannot be determined statically.
# Codes absent from this table are treated as `incomplete`, never as harmless.
DIAGNOSTIC_CLASS = {
    "namespace_native_library_declared": "info",
    "namespace_import_arguments_unparsed": "info",
    "rd_conditional_formatting": "info",
    "rd_dynamic_in_section": "info",
    "rd_macro_definition": "info",
    "export_patterns_not_expanded": "incomplete",
    "namespace_nonliteral_arguments": "incomplete",
    "namespace_empty_argument": "incomplete",
    "namespace_named_arguments_unsupported": "incomplete",
    "namespace_unsupported_directive": "incomplete",
    "namespace_malformed_import": "incomplete",
    "rd_encoding_unavailable": "incomplete",
    "rd_member_name_too_long": "incomplete",
    "rd_topic_name_unavailable": "incomplete",
    "rd_alias_not_literal": "incomplete",
    "rd_name_not_literal": "incomplete",
    "namespace_missing": "unestablished",
    "namespace_unsupported_expression": "unestablished",
    "namespace_malformed": "unestablished",
    "namespace_encoding_unavailable": "unestablished",
    "rd_unbalanced_braces": "unestablished",
    "rd_dynamic_top_level": "unestablished",
    "rd_conditional_structure": "unestablished",
    "rd_macro_definition_structural": "unestablished",
}
MAX_NAMESPACE_DIAGNOSTICS = 50
NAMESPACE_DIRECTIVES = frozenset(
    {
        "export",
        "exportClasses",
        "exportMethods",
        "exportPattern",
        "S3method",
        "import",
        "importFrom",
        "importClassesFrom",
        "importMethodsFrom",
        "useDynLib",
    }
)


def diagnostic_class(code: str) -> str:
    return DIAGNOSTIC_CLASS.get(code, "incomplete")


def parse_namespace(source: str | None) -> dict:
    """Only unconditional, isolated supported calls establish declarations.

    `diagnostics` lists every observation with its class; `issues` and `status` reflect only the
    non-`info` ones, so harmless constructs (native-library registration, import options) no longer
    downgrade the result while genuine uncertainty stays visible.
    """
    from .visualization_analysis import scan_calls, tokenize_r

    result = {
        "exports": [],
        "methods": [],
        "patterns": [],
        "imports": [],
        "status": "verified",
        "issues": [],
        "diagnostics": [],
    }

    def note(code: str, call=None) -> None:
        if len(result["diagnostics"]) < MAX_NAMESPACE_DIAGNOSTICS:
            item = {"code": code, "class": diagnostic_class(code)}
            if call is not None:
                item.update(directive=call.name, line=call.line)
            result["diagnostics"].append(item)
        if diagnostic_class(code) != "info":
            result["issues"].append(code)

    if source is None:
        note("namespace_missing")
        return {**result, "status": "unavailable"}
    if len(source.encode("utf-8")) > 256 << 10:
        raise KnowledgeError("source_too_large", "NAMESPACE exceeds 256 KiB")
    try:
        calls, unsupported = _namespace_statements(source, scan_calls(source))
    except KnowledgeError:
        note("namespace_malformed")
        return {**result, "status": "partial"}
    if len(calls) > MAX_NAMESPACE_DECLARATIONS:
        raise KnowledgeError("source_too_large", "Too many NAMESPACE declarations")
    if unsupported:
        note("namespace_unsupported_expression")
    for call in calls:
        if call.name in {"useDynLib", "import"}:
            # Neither can add an export, a method or a re-export origin, so options such as
            # `.registration = TRUE` or `except = c(...)` do not affect what is enumerated.
            if not call.arguments or any(
                key is not None or _namespace_literal(value) is None
                for key, value in call.arguments
            ):
                note(
                    "namespace_native_library_declared"
                    if call.name == "useDynLib"
                    else "namespace_import_arguments_unparsed",
                    call,
                )
            continue
        _, directive_tokens = tokenize_r(source[call.start : call.end])
        pairs = zip(directive_tokens, directive_tokens[1:], strict=False)
        if any(
            a.value in {"(", ","} and b.value in {",", ")"}
            for a, b in pairs
            if a.kind == b.kind == "punctuation"
        ):
            note("namespace_empty_argument", call)
            continue
        arguments = list(call.arguments)
        qualified = None
        if call.name == "S3method" and arguments and arguments[0][0] is None:
            qualified = _qualified_generic(arguments[0][1])
            if qualified is not None:
                arguments[0] = (None, qualified[1])
        values = [_namespace_literal(value) for _, value in arguments]
        if not values or any(value is None for value in values):
            # An arbitrary call (eval(), a helper function) may declare anything at load time.
            note(
                "namespace_nonliteral_arguments"
                if call.name in NAMESPACE_DIRECTIVES
                else "namespace_unsupported_expression",
                call,
            )
            continue
        if any(key is not None for key, _ in call.arguments):
            note("namespace_named_arguments_unsupported", call)
            continue
        evidence = {"archive_member": "NAMESPACE", "line": call.line, "directive": call.name}
        if call.name in {"export", "exportClasses", "exportMethods"}:
            for value in values:
                result["exports"].append(
                    {
                        "name": value,
                        "declaration_kind": call.name,
                        "evidence": evidence,
                        "callability": "not_checked",
                    }
                )
                if call.name == "exportMethods":
                    result["methods"].append(
                        {
                            "name": value,
                            "method_kind": "S4_export",
                            "generic": value,
                            "class": None,
                            "evidence": evidence,
                            "callability": "not_checked",
                        }
                    )
        elif call.name == "exportPattern":
            result["patterns"].extend(values)
            note("export_patterns_not_expanded", call)
        elif call.name == "S3method" and len(values) in (2, 3):
            generic, cls = values[:2]
            result["methods"].append(
                {
                    "name": values[2] if len(values) == 3 else f"{generic}.{cls}",
                    "method_kind": "S3",
                    "generic": f"{qualified[0]}::{generic}" if qualified else generic,
                    "class": cls,
                    **({"generic_package": qualified[0]} if qualified else {}),
                    "evidence": evidence,
                    "callability": "not_checked",
                }
            )
        elif call.name in {"importFrom", "importClassesFrom", "importMethodsFrom"}:
            if len(values) < 2:
                note("namespace_malformed_import", call)
            else:
                result["imports"].extend(
                    {"package": values[0], "name": value, "directive": call.name}
                    for value in values[1:]
                )
        else:
            note("namespace_unsupported_directive", call)
        if (
            sum(len(result[k]) for k in ("exports", "methods", "patterns", "imports"))
            > MAX_NAMESPACE_ENTRIES
        ):
            raise KnowledgeError("source_too_large", "Too many NAMESPACE entries")
    result["issues"] = sorted(set(result["issues"]))
    if result["issues"]:
        result["status"] = "partial"
    return result


_RD_STRUCTURE = re.compile(r"\\(?:alias|name|Sexpr|eval|newcommand|renewcommand|RdOpts)\b")
_RD_MACRO = re.compile(r"[A-Za-z]+")
_RD_DYNAMIC = frozenset({"Sexpr", "eval", "RdOpts"})
_RD_MAX_DEPTH = 128


def _rd_pairs(text: str) -> dict[int, int] | None:
    """Map each `{` to its matching `}` in one pass; None if unbalanced or nested too deeply."""
    stack: list[int] = []
    pairs: dict[int, int] = {}
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "{":
            stack.append(pos)
            if len(stack) > _RD_MAX_DEPTH:
                return None
        elif char == "}":
            if not stack:
                return None
            pairs[stack.pop()] = pos
        pos += 1
    return None if stack else pairs


def _rd_groups(text: str, pos: int, count: int, pairs: dict[int, int]) -> list[tuple[int, int]]:
    """Content spans of `count` consecutive brace groups after `pos` (whitespace allowed)."""
    spans = []
    for _ in range(count):
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos not in pairs:
            return []
        spans.append((pos + 1, pairs[pos]))
        pos = pairs[pos] + 1
    return spans


def _rd_structure(text: str) -> tuple[bool, set[str]]:
    """Brace balance and the dynamic/conditional constructs that bear on completeness.

    `text` must have its comments removed. Where a construct appears decides what it can do: a
    top-level `\\Sexpr[results=rd]` can emit a `\\alias` (verified with R 4.5.2), one inside a
    section cannot; `\\if`/`\\ifelse` only matter if their body contains Rd structure. Linear in
    the size of `text`: brace pairs come from one pass and structural macros are located once.
    """
    pairs = _rd_pairs(text)
    if pairs is None:
        return False, set()
    structural = [match.start() for match in _RD_STRUCTURE.finditer(text)]

    def has_structure(span: tuple[int, int]) -> bool:
        index = bisect_left(structural, span[0])
        return index < len(structural) and structural[index] < span[1]

    depth, pos, codes = 0, 0, set()
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            macro = _RD_MACRO.match(text, pos + 1)
            if macro is None:
                pos += 2
                continue
            name, pos = macro[0], macro.end()
            if name in _RD_DYNAMIC:
                codes.add("rd_dynamic_top_level" if depth == 0 else "rd_dynamic_in_section")
            elif name in {"newcommand", "renewcommand"}:
                spans = _rd_groups(text, pos, 2, pairs)
                structural_body = len(spans) != 2 or has_structure(spans[1])
                codes.add(
                    "rd_macro_definition_structural" if structural_body else "rd_macro_definition"
                )
            elif name in {"if", "ifelse"}:
                spans = _rd_groups(text, pos, 2 if name == "if" else 3, pairs)
                structural_body = not spans or any(has_structure(span) for span in spans[1:])
                codes.add(
                    "rd_conditional_structure" if structural_body else "rd_conditional_formatting"
                )
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        pos += 1
    return True, codes


def rd_coverage(member: str, text: str) -> dict:
    """Literal topic/alias evidence plus classified diagnostics for one Rd file.

    `complete` is False only for a limiting diagnostic (known gap or undeterminable); constructs
    that cannot change the alias set (formatting conditionals, `\\Sexpr` inside a section) are
    reported as `info` diagnostics instead of downgrading the file.
    """
    uncommented = re.sub(r"(?<!\\)%[^\n]*", "", text)
    literal = _alias_values(uncommented)
    names = sorted(set(literal))
    good = [name for name in names if discovery_name(name)]
    # `\name{\%>\%}` is a literal topic: only the escapes that `\alias` already resolves count.
    literal_topics = [
        re.sub(r"\\([{}%\\])", r"\1", value)
        for value in re.findall(r"\\name\{((?:\\[{}%\\]|[^{}\\])*)\}", uncommented)
    ]
    literal_topic = len(literal_topics) == 1 and discovery_name(literal_topics[0])
    topic = literal_topics[0] if literal_topic else member.rsplit("/", 1)[1][:-3]
    balanced, codes = _rd_structure(uncommented)
    if not balanced:
        codes.add("rd_unbalanced_braces")
    if len(good) != len(names) or len(re.findall(r"\\alias\s*\{", uncommented)) != len(literal):
        codes.add("rd_alias_not_literal")
    if not literal_topic:
        codes.add("rd_name_not_literal")
    return {
        "topic": topic,
        "aliases": good,
        "complete": all(diagnostic_class(code) == "info" for code in codes),
        "identifier_source": "rd_name" if literal_topic else "archive_filename",
        "diagnostics": sorted(codes),
    }


def rd_index_record(member: str, text: str) -> tuple[str, list[str], bool, str]:
    """Literal topic/alias evidence only; comments cannot establish topic names."""
    record = rd_coverage(member, text)
    return record["topic"], record["aliases"], record["complete"], record["identifier_source"]
