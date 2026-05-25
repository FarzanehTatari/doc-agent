"""PDF writer tests — skipped if weasyprint isn't installed.

Two test paths:
  1. The `is_available()` probe and the install-hint message — always run.
  2. The actual `write_pdf` call — only when weasyprint is present.
"""

from pathlib import Path

import pytest

from doc_agent.export.bundle import Bundle, BundleEntry
from doc_agent.export.pdf_writer import is_available, write_pdf


def _bundle(*content_titles):
    entries = [
        BundleEntry(source_path=Path(f"{t}.md"), content=c, title=t, kind="autodoc")
        for t, c in content_titles
    ]
    return Bundle(model_name="M", entries=entries)


def test_is_available_returns_bool():
    """is_available() must not raise and must return a bool."""
    result = is_available()
    assert isinstance(result, bool)


def test_write_pdf_without_weasyprint_raises_helpful_error(monkeypatch):
    """If weasyprint can't be imported, raise RuntimeError with install hint."""
    # Force the import inside write_pdf to fail
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("no weasyprint")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    bundle = _bundle(("A", "# A\n\nbody"))
    with pytest.raises(RuntimeError) as exc_info:
        write_pdf(bundle, Path("/tmp/should_not_be_created.pdf"))
    msg = str(exc_info.value)
    assert "weasyprint" in msg.lower()
    assert "pip install" in msg


# ---- live PDF generation (skipped unless weasyprint is on the system) -----
weasyprint = pytest.importorskip("weasyprint")


def test_write_pdf_produces_real_pdf(tmp_path):
    bundle = _bundle(("First", "# First\n\nHello.\n\n## Sub\n\n- one\n- two"))
    out = tmp_path / "out.pdf"
    written = write_pdf(bundle, out)
    assert written == out
    assert out.exists()
    # Real PDF files start with %PDF-
    header = out.read_bytes()[:5]
    assert header == b"%PDF-"


def test_write_pdf_multi_entry(tmp_path):
    bundle = _bundle(
        ("A", "# A\n\nFirst entry."),
        ("B", "# B\n\nSecond entry."),
        ("C", "# C\n\nThird entry."),
    )
    out = tmp_path / "multi.pdf"
    write_pdf(bundle, out)
    assert out.exists()
    assert out.stat().st_size > 1000  # any nontrivial PDF
