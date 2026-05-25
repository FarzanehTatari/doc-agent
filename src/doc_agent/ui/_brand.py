"""Per-page branding — call `apply_brand()` at the top of every page.

Behavior, all controlled via `.env`:

  • UI_LOGO_PATH         — image path (PNG / JPG / SVG). Relative paths resolve
                            against the repo root. Empty = no logo.
  • UI_LOGO_WIDTH        — max width in px (default 240, keeps aspect ratio).
  • UI_HIDE_CHROME=1     — hides Streamlit's default top-right toolbar
                            (running cyclist, Stop, Deploy, hamburger).

The logo is embedded as a base64 data URI in the page HTML, so there's no
external request and Streamlit's static-file resolution can't interfere.
It's right-aligned at the top of the main content area on every page.
"""

from __future__ import annotations

import base64
from pathlib import Path

from doc_agent.config import REPO_ROOT, settings


# MIME types for the formats we support inline.
_MIME = {
    "png":  "png",
    "jpg":  "jpeg",
    "jpeg": "jpeg",
    "gif":  "gif",
    "webp": "webp",
    "svg":  "svg+xml",
}


_HIDE_CHROME_CSS = """
<style>
  [data-testid="stStatusWidget"]      { display: none !important; }
  [data-testid="stAppDeployButton"]   { display: none !important; }
  [data-testid="stMainMenu"]          { display: none !important; }
  [data-testid="stToolbarActions"]    { display: none !important; }
  [data-testid="stDecoration"]        { display: none !important; }
</style>
"""


def apply_brand() -> None:
    """Apply per-page branding. Call once at the top of each Streamlit page."""
    import streamlit as st

    # 1 · Main-area logo (right-aligned, sized by UI_LOGO_WIDTH) ------
    raw = settings.ui_logo_path
    logo_path = _resolve_logo_path(raw)
    if logo_path is not None:
        try:
            data_uri = _to_data_uri(logo_path)
            width = int(settings.ui_logo_width)
            st.markdown(
                f"""
                <div style="text-align: right; margin: 0 0 1rem 0;">
                  <img src="{data_uri}"
                       alt="brand logo"
                       style="max-width: {width}px; height: auto;
                              display: inline-block;" />
                </div>
                """,
                unsafe_allow_html=True,
            )
        except Exception as e:  # noqa: BLE001
            with st.sidebar:
                st.caption(f"⚠️ Logo render failed: {e}")
    elif raw:
        with st.sidebar:
            st.caption(
                f"⚠️ `UI_LOGO_PATH={raw}` — file not found relative to "
                f"`{REPO_ROOT}`. Check the path / extension."
            )

    # 2 · Hide Streamlit's default chrome (opt-in) --------------------
    if settings.ui_hide_chrome:
        st.markdown(_HIDE_CHROME_CSS, unsafe_allow_html=True)


# ---------- internals -------------------------------------------------------
def _resolve_logo_path(raw: str) -> Path | None:
    """Return an absolute path to the logo file, or None if not usable."""
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return p if p.is_file() else None


def _to_data_uri(path: Path) -> str:
    """Read the image and produce a `data:image/<mime>;base64,<…>` URI."""
    ext = path.suffix.lstrip(".").lower()
    mime = _MIME.get(ext, "png")
    if mime == "svg+xml":
        # SVG can stay text; no need to base64 it.
        return "data:image/svg+xml;utf8," + path.read_text(encoding="utf-8").replace("\n", " ")
    blob = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{blob}"
