"""Render a `Bundle` to a single self-contained HTML file with TOC and CSS.

Each entry's content is converted via markdown-it-py. The whole bundle becomes
one navigable document — no external assets, no JS, no network. Print-friendly.
"""

from __future__ import annotations

import html as _html
import re
from datetime import datetime, timezone
from pathlib import Path

from doc_agent.export.bundle import Bundle


def render_html_string(bundle: Bundle) -> str:
    """Render `bundle` to a complete standalone HTML *string* (no file I/O).

    Split out so `pdf_writer.write_pdf` can pipe this directly into weasyprint
    without writing an intermediate .html file.
    """
    from markdown_it import MarkdownIt

    md = (
        MarkdownIt("commonmark", {"breaks": True, "html": False, "linkify": True})
        .enable("table")
        .enable("strikethrough")
    )

    toc_items: list[str] = []
    body_parts: list[str] = []
    for entry in bundle.entries:
        slug = _slugify(f"{entry.title}-{entry.kind}")
        toc_items.append(
            f'<li><a href="#{slug}"><span class="kind kind-{entry.kind}">'
            f'{entry.kind}</span> {_html.escape(entry.title)}</a></li>'
        )
        rendered = md.render(entry.content)
        body_parts.append(f'<section id="{slug}" class="entry">\n{rendered}\n</section>')

    toc_html = (
        '<nav class="toc" aria-label="Table of contents">'
        f'<h2>Contents <span class="count">({len(bundle.entries)})</span></h2>'
        "<ul>" + "\n".join(toc_items) + "</ul></nav>"
    )
    body_html = "\n".join(body_parts)

    return _TEMPLATE.format(
        title=_html.escape(f"{bundle.model_name} — Documentation"),
        model=_html.escape(bundle.model_name),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        css=_CSS,
        toc=toc_html,
        body=body_html,
        entry_count=len(bundle.entries),
    )


def write_html(bundle: Bundle, out_path: Path | str) -> Path:
    """Write `bundle` to a standalone HTML file. Returns the path written."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html_string(bundle), encoding="utf-8")
    return out_path


# ----- helpers -----------------------------------------------------------
def _slugify(text: str) -> str:
    """ASCII slug suitable for HTML id attributes."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9\s_-]+", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "section"


_CSS = """
:root {
  --fg: #1c1f24; --bg: #ffffff;
  --muted: #5c6470; --rule: #e3e6ea;
  --accent: #0b66c1; --code-bg: #f4f5f7;
  --table-stripe: #f8f9fb;
  --kind-autodoc: #0b66c1; --kind-sysreq: #5d378f; --kind-unitreq: #2c7a4a;
  --max-width: 880px;
}
* { box-sizing: border-box; }
body {
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--fg); background: var(--bg); margin: 0; padding: 0;
}
.container { max-width: var(--max-width); margin: 0 auto; padding: 32px 24px 96px; }
.cover { border-bottom: 2px solid var(--rule); padding-bottom: 24px; margin-bottom: 32px; }
.cover h1 { font-size: 36px; margin: 0 0 8px; }
.cover .meta { color: var(--muted); font-size: 14px; }
.toc { background: var(--code-bg); border: 1px solid var(--rule); border-radius: 6px;
       padding: 16px 24px; margin-bottom: 40px; }
.toc h2 { font-size: 18px; margin: 0 0 12px; }
.toc .count { color: var(--muted); font-weight: 400; font-size: 14px; }
.toc ul { margin: 0; padding-left: 16px; }
.toc li { margin: 4px 0; }
.toc a { text-decoration: none; color: var(--accent); }
.toc a:hover { text-decoration: underline; }
.kind { display: inline-block; min-width: 64px; padding: 1px 6px; border-radius: 3px;
        font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
        color: white; margin-right: 8px; text-align: center; }
.kind-autodoc { background: var(--kind-autodoc); }
.kind-sysreq  { background: var(--kind-sysreq); }
.kind-unitreq { background: var(--kind-unitreq); }
.kind-doc     { background: var(--muted); }
.entry { margin-bottom: 56px; padding-top: 16px; border-top: 1px dashed var(--rule); }
.entry:first-of-type { border-top: 0; padding-top: 0; }
h1 { font-size: 28px; margin: 24px 0 8px; }
h2 { font-size: 22px; margin: 28px 0 8px; border-bottom: 1px solid var(--rule); padding-bottom: 4px; }
h3 { font-size: 17px; margin: 20px 0 6px; }
h4 { font-size: 15px; margin: 18px 0 4px; }
p { margin: 8px 0; }
ul, ol { margin: 8px 0; padding-left: 24px; }
li { margin: 2px 0; }
code { background: var(--code-bg); padding: 1px 5px; border-radius: 3px;
       font: 13px/1.4 "SF Mono", Consolas, Monaco, monospace; }
pre { background: var(--code-bg); border: 1px solid var(--rule); border-radius: 4px;
      padding: 12px 16px; overflow-x: auto; }
pre code { background: transparent; padding: 0; font-size: 13px; }
blockquote { border-left: 3px solid var(--accent); margin: 12px 0; padding: 4px 16px;
             color: var(--muted); background: var(--code-bg); }
hr { border: 0; border-top: 1px solid var(--rule); margin: 24px 0; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }
th, td { border: 1px solid var(--rule); padding: 6px 10px; text-align: left; vertical-align: top; }
thead th { background: var(--code-bg); }
tbody tr:nth-child(even) { background: var(--table-stripe); }
a { color: var(--accent); }
@media print {
  body { font-size: 12px; }
  .toc { page-break-after: always; }
  .entry { page-break-before: always; }
  .entry:first-of-type { page-break-before: auto; }
}
"""


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
  <div class="container">
    <header class="cover">
      <h1>{model}</h1>
      <div class="meta">{entry_count} document(s) — generated {generated_at}</div>
    </header>
    {toc}
    {body}
  </div>
</body>
</html>
"""
