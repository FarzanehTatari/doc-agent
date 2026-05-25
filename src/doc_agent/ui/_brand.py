"""Per-page branding — call `apply_brand()` at the top of every page.

Two effects, both controlled via `.env`:

  • UI_LOGO_PATH        — shows a logo in the sidebar top (`st.logo`).
                           Relative paths resolve against the repo root.
  • UI_HIDE_CHROME=1    — hides Streamlit's default top-right toolbar:
                           the running cyclist indicator, Stop, Deploy, menu.
                           Recommended for branded local deploys; leave off
                           if you want to keep the Stop affordance.

This helper is idempotent — calling it multiple times in one page is harmless.
"""

from __future__ import annotations

from pathlib import Path

from doc_agent.config import REPO_ROOT, settings


_HIDE_CHROME_CSS = """
<style>
  /* Streamlit's "running" cyclist + Stop button cluster (top-right header). */
  [data-testid="stStatusWidget"]      { display: none !important; }
  /* The Deploy button (irrelevant for local installs). */
  [data-testid="stAppDeployButton"]   { display: none !important; }
  /* The 3-dot main menu. */
  [data-testid="stMainMenu"]          { display: none !important; }
  /* The "Deploy" cluster in newer Streamlit builds. */
  [data-testid="stToolbarActions"]    { display: none !important; }
  /* The decorative pink stripe at the very top. */
  [data-testid="stDecoration"]        { display: none !important; }
</style>
"""


def apply_brand() -> None:
    """Apply per-page branding. Call once at the top of each Streamlit page."""
    import streamlit as st

    # 1 · Sidebar logo --------------------------------------------------
    logo_path = _resolve_logo_path(settings.ui_logo_path)
    if logo_path is not None:
        try:
            # st.logo arrived in Streamlit 1.34; arg name `size` arrived in 1.46.
            # We require 1.46 already, so this signature is safe.
            st.logo(str(logo_path), size="large")
        except Exception:  # noqa: BLE001
            # Don't let a logo-rendering hiccup break the whole page.
            pass

    # 2 · Hide Streamlit's default chrome (opt-in) ----------------------
    if settings.ui_hide_chrome:
        st.markdown(_HIDE_CHROME_CSS, unsafe_allow_html=True)


def _resolve_logo_path(raw: str) -> Path | None:
    """Return an absolute path to the logo file, or None if not usable."""
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    if p.is_file():
        return p
    return None
