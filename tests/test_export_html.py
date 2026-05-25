"""HTML writer tests — requires markdown-it-py installed."""

import pytest

pytest.importorskip("markdown_it")

from doc_agent.export.bundle import Bundle, BundleEntry
from doc_agent.export.html_writer import _slugify, write_html


def _bundle(entries):
    return Bundle(model_name="M", entries=entries)


def _entry(title, content, kind="autodoc"):
    from pathlib import Path
    return BundleEntry(source_path=Path(f"{title}.md"),
                       content=content, title=title, kind=kind)


def test_slugify_basic():
    assert _slugify("Wheel Averager") == "wheel-averager"
    assert _slugify("VSE Model — Filter") == "vse-model-filter"
    assert _slugify("") == "section"


def test_write_html_produces_single_file(tmp_path):
    bundle = _bundle([_entry("A", "# A\n\nbody")])
    out = tmp_path / "out.html"
    written = write_html(bundle, out)
    assert written == out
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    # Standalone
    assert "<!DOCTYPE html>" in html
    assert "<style>" in html
    # Cover + body
    assert "M" in html
    assert "<h1>A</h1>" in html or ">A<" in html
    # TOC
    assert 'class="toc"' in html


def test_html_renders_tables_and_lists(tmp_path):
    bundle = _bundle([_entry("T",
        "# T\n\n"
        "## Section\n\n"
        "- item 1\n- item 2\n\n"
        "| h1 | h2 |\n|---|---|\n| a | b |\n"
    )])
    out = tmp_path / "x.html"
    write_html(bundle, out)
    html = out.read_text(encoding="utf-8")
    assert "<ul>" in html and "<li>" in html
    assert "<table>" in html
    assert "<th>h1</th>" in html
    assert "<td>a</td>" in html


def test_html_escapes_title():
    title = "<script>x</script>"
    bundle = _bundle([_entry(title, "# X\n\nbody")])
    out = bundle  # unused, but ensure call doesn't crash
    from pathlib import Path
    tmp = Path("/tmp/__doc_agent_test_escape.html")
    write_html(bundle, tmp)
    html = tmp.read_text(encoding="utf-8")
    assert "<script>" not in html.split("<style>")[0]   # not in TOC unescaped
    tmp.unlink(missing_ok=True)


def test_html_multiple_entries_appear_in_order(tmp_path):
    bundle = _bundle([
        _entry("First",  "# First\n",  kind="autodoc"),
        _entry("Second", "# Second\n", kind="sysreq"),
        _entry("Third",  "# Third\n",  kind="unitreq"),
    ])
    out = tmp_path / "all.html"
    write_html(bundle, out)
    html = out.read_text(encoding="utf-8")
    assert html.index("First") < html.index("Second") < html.index("Third")
    # All three kind badges
    assert "kind-autodoc" in html
    assert "kind-sysreq" in html
    assert "kind-unitreq" in html
