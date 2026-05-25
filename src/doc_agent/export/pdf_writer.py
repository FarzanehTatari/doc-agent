"""Render a `Bundle` to PDF via weasyprint.

PDF is opt-in: install with `pip install -e ".[pdf]"`. weasyprint pulls in
Pango / Cairo / GDK-PixBuf which need system libraries (`brew install pango`
on macOS). If weasyprint isn't available, this writer raises a clear,
actionable error instead of failing silently.

Implementation: render the same HTML as `html_writer` produces, then hand
it to weasyprint. That way the print stylesheet (the `@media print` rules
embedded in `_CSS`) controls pagination automatically — TOC on its own
page, each entry page-breaks before, etc.
"""

from __future__ import annotations

from pathlib import Path

from doc_agent.export.bundle import Bundle
from doc_agent.export.html_writer import render_html_string


_INSTALL_HINT = (
    "PDF export needs weasyprint, which isn't installed.\n\n"
    "Install with:\n"
    '  pip install -e ".[pdf]"\n\n'
    "macOS users may also need system libraries first:\n"
    "  brew install pango\n\n"
    "If you can't install weasyprint, you can still get a PDF by:\n"
    "  1. running `doc-agent export <dir> -f html`\n"
    "  2. opening the resulting .html in any browser\n"
    "  3. using the browser's File → Print → Save as PDF."
)


def write_pdf(bundle: Bundle, out_path: Path | str) -> Path:
    """Write `bundle` to a paginated PDF. Returns the path written.

    Raises RuntimeError with install instructions if weasyprint isn't available.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(_INSTALL_HINT) from e

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html_str = render_html_string(bundle)
    # `base_url` is required when the HTML refers to relative assets;
    # ours is self-contained, so any sane base works.
    HTML(string=html_str, base_url=str(out_path.parent)).write_pdf(target=str(out_path))
    return out_path


def is_available() -> bool:
    """Quick check the CLI can use to gate the --format pdf option."""
    try:
        import weasyprint  # noqa: F401
        return True
    except ImportError:
        return False
