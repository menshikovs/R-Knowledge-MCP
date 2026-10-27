"""Regression coverage for pytest temporary-directory access on Windows."""


def test_tmp_path_factory_directories_are_writable_and_isolated(tmp_path, tmp_path_factory):
    nested = tmp_path / "nested"
    nested.mkdir()
    marker = nested / "marker.txt"
    marker.write_text("pytest temp is usable", encoding="utf-8")

    assert marker.read_text(encoding="utf-8") == "pytest temp is usable"
    basetemp = tmp_path_factory.getbasetemp().resolve()
    second = tmp_path_factory.mktemp("independent-")
    assert tmp_path.resolve().is_relative_to(basetemp)
    assert second != tmp_path
    assert second.parent == basetemp
