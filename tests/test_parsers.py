import gzip

import pytest
from conftest import DESCRIPTION, RD, archive

from cran_knowledge_mcp.errors import KnowledgeError
from cran_knowledge_mcp.parsers import aliases, dcf, source_files


def test_dcf_continuation_and_duplicate():
    assert dcf("Title: First\n  second\n") == [{"Title": "First second"}]
    with pytest.raises(KnowledgeError):
        dcf("Version: 1\nVersion: 2\n")


def test_literal_aliases_and_comments():
    assert aliases("% \\alias{fake}\n\\alias{real}\n\\alias{\\%operator\\%}") == {
        "real",
        "%operator%",
    }


def test_no_path_extraction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    files = source_files(
        archive(
            {
                "ExamplePkg/DESCRIPTION": DESCRIPTION,
                "ExamplePkg/man/example.Rd": RD,
                "../owned": "bad",
                "/absolute": "bad",
                "ExamplePkg/R/code.R": "system('bad')",
            }
        ),
        "ExamplePkg",
    )
    assert set(files) == {"ExamplePkg/DESCRIPTION", "ExamplePkg/man/example.Rd"}
    assert list(tmp_path.iterdir()) == []


def test_member_limit():
    with pytest.raises(KnowledgeError, match="2 MiB"):
        source_files(archive({"ExamplePkg/DESCRIPTION": b"x" * ((2 << 20) + 1)}), "ExamplePkg")


@pytest.mark.parametrize("body", [b"not gzip", gzip.compress(b"not tar")])
def test_invalid_archives(body):
    with pytest.raises(KnowledgeError, match="Invalid CRAN"):
        source_files(body, "ExamplePkg")
