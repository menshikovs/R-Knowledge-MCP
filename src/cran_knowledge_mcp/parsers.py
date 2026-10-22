"""Parse data only. Never extract archives to disk, run R, or evaluate Rd macros."""

import gzip
import io
import re
import tarfile
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
                if name != f"{package}/DESCRIPTION" and not re.fullmatch(
                    re.escape(package) + r"/man/[^/\\]+\.Rd", name
                ):
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
