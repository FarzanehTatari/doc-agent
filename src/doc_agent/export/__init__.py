"""Phase 5 — export consolidated documentation to HTML / DOCX.

Public surface:
    Bundle.from_directory(path)   — collect every .md (respect _INDEX.md order)
    Bundle.from_single_file(path) — single-doc bundle
    write_html(bundle, out_path)  — render to standalone HTML with TOC + CSS
    write_docx(bundle, out_path)  — render to .docx with TOC + styled headings
"""

from doc_agent.export.bundle import Bundle, BundleEntry
from doc_agent.export.docx_writer import write_docx
from doc_agent.export.html_writer import render_html_string, write_html
from doc_agent.export.pdf_writer import is_available as pdf_is_available
from doc_agent.export.pdf_writer import write_pdf

__all__ = [
    "Bundle",
    "BundleEntry",
    "pdf_is_available",
    "render_html_string",
    "write_docx",
    "write_html",
    "write_pdf",
]
