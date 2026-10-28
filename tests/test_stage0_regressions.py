"""Regression tests for audit findings SEC-001 (quadratic DCF parsing) and KC-001 (Rd encodings).

Synthetic fixtures only: no network, no R, no real package content.
"""

import asyncio
import random
import time

import httpx
import pytest
from conftest import archive

from benchmarks.codex_r import run_simple
from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.http import CATALOG, INDEX, CranHTTP
from cran_knowledge_mcp.parsers import dcf, decode_rd, rd_declared_encoding
from cran_knowledge_mcp.service import KnowledgeService

# ---------------------------------------------------------------------------------------------
# SEC-001: dcf() must be effectively linear and behave exactly like the previous implementation.
# ---------------------------------------------------------------------------------------------


def reference_dcf(text):
    """The previous quadratic algorithm, kept only as an oracle for equivalence tests."""
    records, record, key = [], {}, ""
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


def assert_same_as_reference(text):
    try:
        expected = reference_dcf(text)
    except KnowledgeError as exc:
        with pytest.raises(KnowledgeError) as raised:
            dcf(text)
        assert raised.value.code == exc.code
        return
    assert dcf(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n\n",
        "A: 1\n",
        "A: 1\n\nB: 2\n",
        "Depends:\n  a,\n  b\n",
        "Title: First\n  second\n\tthird   \n",
        "A: x\n \nB: y\n",
        "A:\n",
        "A: 1\r\n  more\r\n\r\nB: 2\r\n",
        "Description: " + "word " * 50 + "\n" + "  continued line\n" * 5,
        " leading continuation without a key\nA: 1\n",
        "A: 1\nA: 2\n",
        "no colon\n",
    ],
)
def test_dcf_is_identical_to_the_previous_implementation_on_fixed_inputs(text):
    assert_same_as_reference(text)


def test_dcf_is_identical_to_the_previous_implementation_on_seeded_random_inputs():
    rng = random.Random(20261027)
    pieces = ["A: v", "B:", "  cont", "\tcont2", "", " ", "C: x y", "bad line", "A: dup", "   "]
    for _ in range(400):
        assert_same_as_reference("\n".join(rng.choice(pieces) for _ in range(rng.randrange(0, 14))))


def test_dcf_keeps_explicit_errors_and_per_record_duplicate_semantics():
    with pytest.raises(KnowledgeError, match="Malformed CRAN DCF data"):
        dcf("no colon here\n")
    with pytest.raises(KnowledgeError, match="Duplicate DCF field"):
        dcf("A: 1\n  more\nA: 2\n")
    assert dcf("A: 1\n\nA: 2\n") == [{"A": "1"}, {"A": "2"}]


def test_dcf_long_continuation_field_is_linear_not_quadratic():
    """Audited stall: ~700 000 continuation lines (just under the 2 MiB cap) took ~57 s."""
    lines = 698_000
    text = "Package: x\nDescription: start\n" + " y\n" * lines
    started = time.perf_counter()
    records = dcf(text)
    elapsed = time.perf_counter() - started
    assert len(records) == 1
    assert records[0]["Description"] == "start" + " y" * lines
    assert elapsed < 10, f"DCF parse took {elapsed:.1f}s; expected effectively linear time"


@pytest.mark.parametrize(
    "text",
    [
        "A: 1\n\n" * 200_000,
        "".join(f"Field{i}: v\n" for i in range(100_000)),
        "A:" + " x" * 500_000 + "\n",
        "A: 1\n" + "\n".join([" "] * 200_000),
    ],
    ids=["many-records", "many-fields", "one-long-value", "many-blank-lines"],
)
def test_dcf_adversarial_shapes_finish_quickly(text):
    started = time.perf_counter()
    assert dcf(text)
    assert time.perf_counter() - started < 10


# ---------------------------------------------------------------------------------------------
# KC-001: per-file Rd decoding.
# ---------------------------------------------------------------------------------------------


def test_rd_declared_encoding_reads_the_files_own_declaration():
    assert rd_declared_encoding(b"\\encoding{latin1}\n\\name{x}\n") == "iso8859-1"
    assert rd_declared_encoding(b"\\name{x}\n\\encoding{UTF-8}\n") == "utf-8"
    assert rd_declared_encoding(b"\\name{x}\n") is None
    assert rd_declared_encoding(b"\\encoding{unknown}\n") is None
    # A commented-out declaration does not count.
    assert rd_declared_encoding(b"% \\encoding{latin1}\n\\name{x}\n") is None
    with pytest.raises(KnowledgeError) as raised:
        rd_declared_encoding(b"\\encoding{not-a-real-codec}\n")
    assert raised.value.code == "unsupported_encoding"


def test_decode_rd_precedence_follows_r_and_never_guesses():
    latin = b"\\encoding{latin1}\n\\title{caf\xe9}\n"
    text, encoding, source = decode_rd(latin, None)
    assert "café" in text and source == "rd_declaration" and encoding == "iso8859-1"
    # The file's own declaration wins over the DESCRIPTION encoding.
    assert decode_rd(latin, "UTF-8")[2] == "rd_declaration"
    # No declaration: the DESCRIPTION encoding, then UTF-8.
    assert decode_rd(b"\\title{caf\xe9}\n", "latin1") == (
        "\\title{café}\n",
        "latin1",
        "description",
    )
    assert decode_rd("\\title{café}\n".encode(), None)[2] == "default"
    # Undecodable bytes raise instead of being replaced.
    with pytest.raises(KnowledgeError) as raised:
        decode_rd(b"\\title{caf\xe9}\n", None)
    assert raised.value.code == "unsupported_encoding"


PACKAGE_INDEX = b"Package: MixedPkg\nVersion: 1.0\nLicense: MIT\n"
DESCRIPTION = "Package: MixedPkg\nVersion: 1.0\nTitle: Mixed\nDescription: Mixed Rd encodings.\n"
NAMESPACE = "export(utf_fn)\nexport(latin_fn)\nexport(bad_fn)\n"


def rd(name, title):
    return f"\\name{{{name}}}\n\\alias{{{name}}}\n\\title{{{title}}}\n"


def mixed_files(description=DESCRIPTION):
    return {
        "MixedPkg/DESCRIPTION": description.encode(),
        "MixedPkg/NAMESPACE": NAMESPACE.encode(),
        "MixedPkg/man/utf_fn.Rd": rd("utf_fn", "naïve café").encode("utf-8"),
        # The audited case (CRAN cluster/plantTraits): an in-file declaration, DESCRIPTION silent.
        "MixedPkg/man/latin_fn.Rd": b"\\encoding{latin1}\n"
        + rd("latin_fn", "caf\xe9").encode("latin1"),
        # No declaration and not valid UTF-8: genuinely unreadable.
        "MixedPkg/man/bad_fn.Rd": rd("bad_fn", "caf\xe9").encode("latin1"),
    }


def make_service(files):
    routes = {
        INDEX: PACKAGE_INDEX,
        CATALOG: b"<table><tr><td>MixedPkg</td><td>Mixed</td></tr></table>",
        "/src/contrib/MixedPkg_1.0.tar.gz": archive(files),
    }

    def handler(request):
        import gzip

        path = request.url.path
        content = routes.get(path)
        if content is None and path.endswith("/PACKAGES.gz") and path[:-3] in routes:
            content = gzip.compress(routes[path[:-3]])
        return httpx.Response(404 if content is None else 200, content=content or b"")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return KnowledgeService(CranHTTP(client)), client


async def test_one_undecodable_rd_file_does_not_block_unrelated_documentation():
    service, client = make_service(mixed_files())
    async with client:
        utf = await service.get_function_docs("MixedPkg", "utf_fn")
        latin = await service.get_function_docs("MixedPkg", "latin_fn")
        missing = await service.get_function_docs("MixedPkg", "bad_fn")

    assert "error" not in utf and "naïve café" in utf["text"]
    assert utf["rd_encoding"] == {"encoding": "UTF-8", "source": "default"}
    assert utf["unreadable_rd_members_in_package"] == 1
    assert "error" not in latin and "café" in latin["text"]
    assert latin["rd_encoding"] == {"encoding": "iso8859-1", "source": "rd_declaration"}
    # The unreadable file is reported explicitly; absence is not claimed as verified.
    error = missing["error"]
    assert error["code"] == "docs_not_found"
    assert error["alias_index_complete"] is False
    assert error["unreadable_rd_members"] == 1
    assert error["unreadable_rd_member_names"] == ["MixedPkg/man/bad_fn.Rd"]
    # Provenance is preserved.
    assert latin["sources"] and latin["sources"][-1]["verification_status"] == "verified"


async def test_discovery_and_docs_agree_on_which_rd_files_are_readable():
    service, client = make_service(mixed_files())
    async with client:
        discovery = await service.list_package_functions("MixedPkg", limit=50)
        docs = {
            name: await service.get_function_docs("MixedPkg", name)
            for name in ("utf_fn", "latin_fn")
        }

    aliases = {entry["name"] for entry in discovery["aliases"]}
    assert {"utf_fn", "latin_fn"} <= aliases and "bad_fn" not in aliases
    assert "rd_encoding_unavailable" in discovery["issues"]
    assert discovery["verification_status"] == "partial"
    assert all("error" not in result for result in docs.values())


async def test_fully_declared_package_is_verified_and_description_encoding_is_honoured():
    files = {
        "MixedPkg/DESCRIPTION": (DESCRIPTION + "Encoding: latin1\n").encode(),
        "MixedPkg/NAMESPACE": b"export(latin_fn)\nexport(own_fn)\n",
        # Undeclared file decoded with the DESCRIPTION encoding.
        "MixedPkg/man/latin_fn.Rd": rd("latin_fn", "caf\xe9").encode("latin1"),
        # The file's own declaration wins over the DESCRIPTION encoding.
        "MixedPkg/man/own_fn.Rd": b"\\encoding{UTF-8}\n" + rd("own_fn", "naïve").encode("utf-8"),
    }
    service, client = make_service(files)
    async with client:
        latin = await service.get_function_docs("MixedPkg", "latin_fn")
        own = await service.get_function_docs("MixedPkg", "own_fn")
        discovery = await service.list_package_functions("MixedPkg", limit=50)

    assert latin["rd_encoding"] == {"encoding": "latin1", "source": "description"}
    assert "café" in latin["text"]
    assert own["rd_encoding"]["source"] == "rd_declaration" and "naïve" in own["text"]
    assert "unreadable_rd_members_in_package" not in latin
    assert discovery["coverage"]["rd"] == "verified"


async def test_rd_macros_are_not_evaluated_while_decoding():
    rd_with_macro = (
        b"\\encoding{latin1}\n\\name{macro_fn}\n\\alias{macro_fn}\n"
        b"\\description{\\Sexpr[results=rd]{stop('executed')} caf\xe9}\n"
    )
    files = {
        "MixedPkg/DESCRIPTION": DESCRIPTION.encode(),
        "MixedPkg/NAMESPACE": b"export(macro_fn)\n",
        "MixedPkg/man/macro_fn.Rd": rd_with_macro,
    }
    service, client = make_service(files)
    async with client:
        result = await service.get_function_docs("MixedPkg", "macro_fn")

    assert "error" not in result
    assert "\\Sexpr[results=rd]{stop('executed')}" in result["text"]
    assert "R code" not in result["text"]


# ---------------------------------------------------------------------------------------------
# SEC-001: DESCRIPTION parsing does not block the event loop.
# ---------------------------------------------------------------------------------------------


async def test_large_description_parse_keeps_the_event_loop_responsive():
    lines = 600_000
    description = "Package: MixedPkg\nVersion: 1.0\nTitle: T\nDescription: start\n" + " y\n" * lines
    routes = {
        INDEX: PACKAGE_INDEX,
        "/web/packages/MixedPkg/DESCRIPTION": description.encode(),
    }

    def handler(request):
        import gzip

        path = request.url.path
        content = routes.get(path)
        if content is None and path.endswith("/PACKAGES.gz") and path[:-3] in routes:
            content = gzip.compress(routes[path[:-3]])
        return httpx.Response(404 if content is None else 200, content=content or b"")

    gaps = []
    stop = asyncio.Event()

    async def heartbeat():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = KnowledgeService(CranHTTP(client))
        beat = asyncio.create_task(heartbeat())
        started = time.perf_counter()
        info = await service.get_package_info("MixedPkg", "cran", None, False)
        elapsed = time.perf_counter() - started
        stop.set()
        await beat

    assert "error" not in info and info["package_version"] == "1.0"
    assert len(info["description"]) == len("start") + 2 * lines
    assert elapsed < 10
    assert max(gaps) < 2, f"event loop stalled for {max(gaps):.1f}s"


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {"environment": {"error": {"code": "environment_connection_timeout", "message": "x"}}},
            {"code": "environment_connection_timeout"},
        ),
        ({"environment": {"error": {"message": "no code"}}}, "environment_failed"),
        ({"environment": {"error": {"code": "Not A Reviewed Code!"}}}, "environment_failed"),
        ({"environment": {}}, "environment_failed"),
        ({}, "environment_failed"),
    ],
)
def test_environment_failure_record_uses_reviewed_code_or_fixed_marker(event, expected):
    # Platform-independent: the trial loop that calls this needs Linux SIGALRM.
    assert run_simple.environment_failure(event) == expected
