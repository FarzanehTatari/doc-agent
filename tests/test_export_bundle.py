"""Bundle collection + ordering — no markdown-it, no python-docx required."""

from doc_agent.export.bundle import Bundle, BundleEntry, _extract_title, _infer_kind


def _seed(tmp_path, files: dict):
    """Write {name: content} into tmp_path/<model>/ and return the dir path."""
    d = tmp_path / "VSEModel"
    d.mkdir()
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return d


def test_extract_title_first_h1():
    assert _extract_title("# Hello\n\nbody") == "Hello"


def test_extract_title_skips_other_lines():
    assert _extract_title("> note\n\n# Hello") == "Hello"


def test_extract_title_returns_empty_if_no_h1():
    assert _extract_title("just prose") == ""


def test_infer_kind_recognizes_known_suffixes():
    assert _infer_kind("WheelAverager_autodoc.md") == "autodoc"
    assert _infer_kind("Foo_sysreq.md") == "sysreq"
    assert _infer_kind("Bar_unitreq.md") == "unitreq"
    assert _infer_kind("misc.md") == "doc"


def test_bundle_from_directory_sorts_alphabetically_without_index(tmp_path):
    d = _seed(tmp_path, {
        "Z_autodoc.md": "# Z\n",
        "A_autodoc.md": "# A\n",
        "M_autodoc.md": "# M\n",
    })
    b = Bundle.from_directory(d)
    assert [e.title for e in b.entries] == ["A", "M", "Z"]
    assert b.model_name == "VSEModel"


def test_bundle_from_directory_honors_index_order(tmp_path):
    d = _seed(tmp_path, {
        "Z_autodoc.md": "# Z\n",
        "A_autodoc.md": "# A\n",
        "M_autodoc.md": "# M\n",
        "_INDEX.md": (
            "# VSEModel — Generated Documentation\n"
            "| Subsystem | Deliverables |\n"
            "|---|---|\n"
            "| `VSEModel/Z` | [autodoc](Z_autodoc.md) |\n"
            "| `VSEModel/A` | [autodoc](A_autodoc.md) |\n"
            "| `VSEModel/M` | [autodoc](M_autodoc.md) |\n"
        ),
    })
    b = Bundle.from_directory(d)
    assert [e.title for e in b.entries] == ["Z", "A", "M"]


def test_bundle_excludes_index_from_entries(tmp_path):
    d = _seed(tmp_path, {"_INDEX.md": "# Idx", "A_autodoc.md": "# A"})
    b = Bundle.from_directory(d)
    titles = [e.title for e in b.entries]
    assert "Idx" not in titles
    assert "A" in titles


def test_bundle_kind_is_inferred(tmp_path):
    d = _seed(tmp_path, {
        "Foo_autodoc.md": "# Foo",
        "Foo_sysreq.md":  "# Foo Sys",
    })
    b = Bundle.from_directory(d)
    kinds = sorted(e.kind for e in b.entries)
    assert kinds == ["autodoc", "sysreq"]


def test_bundle_from_single_file(tmp_path):
    p = tmp_path / "alone.md"
    p.write_text("# Alone\n\nsolo doc", encoding="utf-8")
    b = Bundle.from_single_file(p)
    assert len(b) == 1
    assert b.entries[0].title == "Alone"


def test_bundle_from_directory_missing_raises(tmp_path):
    import pytest
    with pytest.raises(NotADirectoryError):
        Bundle.from_directory(tmp_path / "does_not_exist")


def test_bundle_entry_from_path_reads_content(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("# X\n\nbody", encoding="utf-8")
    e = BundleEntry.from_path(p)
    assert e.title == "X"
    assert "body" in e.content
