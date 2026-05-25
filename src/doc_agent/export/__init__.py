"""Phase 5 — export consolidated documentation to HTML / DOCX.

Public surface:
    Bundle.from_directory(path)   — collect every .md (respect _INDEX.md order)
    Bundle.from_single_file(path) — single-doc bundle
    write_html(bundle, out_path)  — render to standalone HTML with TOC + CSS
    write_docx(bundle, out_path)  — render to .docx with TOC + styled headings
"""

from doc_agent.export.bundle import Bundle, BundleEntry
from doc_agent.export.docx_writer import write_docx
from doc_agent.export.html_writer import write_html

__all__ = ["Bundle", "BundleEntry", "write_html", "write_docx"]
