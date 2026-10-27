"""Parse data only. Never extract archives to disk, run R, or evaluate Rd macros."""

import gzip
import io
import re
import tarfile
from difflib import SequenceMatcher
from html.parser import HTMLParser

from .errors import KnowledgeError


def dcf(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    record: dict[str, str] = {}
    key = ""
    for line in text.splitlines() + [""]:
        if not line.strip():
            if record:
                records.append(record)
            record, key = {}, ""
        elif line[0].isspace() and key:
            record[key] += " " + line.strip()
        elif ":" in line:
            key, value = line.split(":", 1)
            if key in record:
                raise KnowledgeError("invalid_source", "Duplicate DCF field")
            record[key] = value.strip()
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


def description_text(body: bytes) -> str:
    encoding = re.search(rb"(?m)^Encoding:[ \t]*([^\r\n]+)", body)
    return decode(body, decode(encoding[1], "ascii").strip() if encoding else "UTF-8")


def aliases(rd: str) -> set[str]:
    # Literal aliases only. Do not expand user macros, conditional Rd or Sexpr.
    uncommented = re.sub(r"(?<!\\)%[^\n]*", "", rd)
    values = re.findall(r"\\alias\{((?:\\.|[^{}\\])*)\}", uncommented)
    return {re.sub(r"\\([{}%\\])", r"\1", value) for value in values}


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


def parse_namespace(source: str | None) -> dict:
    """Only unconditional, isolated supported calls establish declarations."""
    from .visualization_analysis import scan_calls, tokenize_r

    result = {
        "exports": [],
        "methods": [],
        "patterns": [],
        "imports": [],
        "status": "verified",
        "issues": [],
    }
    if source is None:
        return {**result, "status": "unavailable", "issues": ["namespace_missing"]}
    if len(source.encode("utf-8")) > 256 << 10:
        raise KnowledgeError("source_too_large", "NAMESPACE exceeds 256 KiB")
    try:
        calls, unsupported = _namespace_statements(source, scan_calls(source))
    except KnowledgeError:
        return {**result, "status": "partial", "issues": ["namespace_malformed"]}
    if len(calls) > MAX_NAMESPACE_DECLARATIONS:
        raise KnowledgeError("source_too_large", "Too many NAMESPACE declarations")
    if unsupported:
        result["issues"].append("namespace_unsupported_expression")
    for call in calls:
        _, directive_tokens = tokenize_r(source[call.start : call.end])
        pairs = zip(directive_tokens, directive_tokens[1:], strict=False)
        if any(
            a.value in {"(", ","} and b.value in {",", ")"}
            for a, b in pairs
            if a.kind == b.kind == "punctuation"
        ):
            result["issues"].append("namespace_empty_argument")
            continue
        values = [_namespace_literal(value) for _, value in call.arguments]
        if not values or any(value is None for value in values):
            result["issues"].append("namespace_nonliteral_arguments")
            continue
        if any(key is not None for key, _ in call.arguments) and call.name != "useDynLib":
            result["issues"].append("namespace_named_arguments_unsupported")
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
            result["issues"].append("export_patterns_not_expanded")
        elif call.name == "S3method" and len(values) in (2, 3):
            generic, cls = values[:2]
            result["methods"].append(
                {
                    "name": values[2] if len(values) == 3 else f"{generic}.{cls}",
                    "method_kind": "S3",
                    "generic": generic,
                    "class": cls,
                    "evidence": evidence,
                    "callability": "not_checked",
                }
            )
        elif call.name in {"importFrom", "importClassesFrom", "importMethodsFrom"}:
            if len(values) < 2:
                result["issues"].append("namespace_malformed_import")
            else:
                result["imports"].extend(
                    {"package": values[0], "name": value, "directive": call.name}
                    for value in values[1:]
                )
        elif call.name not in {"import", "useDynLib"}:
            result["issues"].append("namespace_unsupported_directive")
        if (
            sum(len(result[k]) for k in ("exports", "methods", "patterns", "imports"))
            > MAX_NAMESPACE_ENTRIES
        ):
            raise KnowledgeError("source_too_large", "Too many NAMESPACE entries")
    result["issues"] = sorted(set(result["issues"]))
    if result["issues"]:
        result["status"] = "partial"
    return result


def _rd_complete(text: str) -> bool:
    depth, pos = 0, 0
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "%":
            stop = text.find("\n", pos)
            pos = len(text) if stop < 0 else stop
            continue
        if char == "{":
            depth += 1
            if depth > 128:
                return False
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
        pos += 1
    return depth == 0 and not re.search(
        r"\\(?:Sexpr|eval|if|ifelse|newcommand|renewcommand|RdOpts)\b",
        re.sub(r"(?<!\\)%[^\n]*", "", text),
    )


def rd_index_record(member: str, text: str) -> tuple[str, list[str], bool, str]:
    """Literal topic/alias evidence only; comments cannot establish topic names."""
    uncommented = re.sub(r"(?<!\\)%[^\n]*", "", text)
    names = sorted(aliases(text))
    good = [name for name in names if discovery_name(name)]
    literal_topics = re.findall(r"\\name\{([^{}\\]*)\}", uncommented)
    literal_topic = len(literal_topics) == 1 and discovery_name(literal_topics[0])
    topic = literal_topics[0] if literal_topic else member.rsplit("/", 1)[1][:-3]
    complete = _rd_complete(text) and len(good) == len(names) and literal_topic
    complete = complete and len(re.findall(r"\\alias\s*\{", uncommented)) == len(names)
    return topic, good, bool(complete), "rd_name" if literal_topic else "archive_filename"
